# Offline replay of jammer localization estimators on logged runs (no new simulation)
#   usage: python3 ~/loc_replay.py <run_dir> [<run_dir> ...]        e.g. ~/jamx_F/pw50_p0_s*
# UE positions are taken per round (UEs move, random walk 3-7 m/s).
# Inputs per run: MmWaveJammerRx.txt (time_s imsi cellId S_dBm J_dBm N_dBm sinr_dB),
#                 ue_position.txt (timestamp,id,x,y,type,...), jammer.txt (x,y,z,power_dbm,...,start_s,stop_s)
# Per 100-ms round, each UE is described by its strongest NR cell (largest S): S (RSRP proxy) and SINR,
# i.e. only quantities a RAN can report. The jammer power at the UE is never used by the estimators.
#   E0  current JamGuard: degraded UEs (SINR<0 dB, drop>=8 dB), weight = clamp(drop,1,40), radius = max dist + 20 m
#   E1  power-weighted centroid: weight = added interference J^ = S (1/SINR - 1/SINR_base), UEs with drop >= 3 dB,
#       radius = weighted 80th percentile of the distances
#   E2  E1 smoothed over rounds (static jammer: cumulative weighted mean = Kalman filter with zero process noise)
#   E4  interference-power trilateration of ratti2026 (J^ = S/SINR - N, 1-s windows, robust LS, n in [1.5,5])
#   E3  path-loss least squares: 10 log10 J^_u = P - 10 n log10 d_u(x), grid 25 m then 5 m, P in closed form, n = 3
import glob, math, os, sys, statistics as st
from collections import defaultdict

NEXP = 3.0
args = [a for a in sys.argv[1:]]
dirs = []
for a in args:
    dirs += sorted(glob.glob(os.path.expanduser(a)))
if not dirs:
    sys.exit('no run directories')

def load(d):
    jam = open(os.path.join(d, 'jammer.txt')).read().strip().splitlines()
    h = jam[0].split(','); v = jam[1].split(','); J = dict(zip(h, v))
    jx, jy = float(J['x']), float(J['y']); t0, t1 = float(J['start_s']), float(J['stop_s'])
    pos = defaultdict(dict)   # imsi -> round -> (x, y); positions are logged every 100 ms (UEs move)
    with open(os.path.join(d, 'ue_position.txt')) as f:
        f.readline()
        for line in f:
            p = line.strip().split(',')
            if len(p) >= 7 and p[4] == 'mc':
                r = int(round((float(p[0]) - float(p[6])) / 100.0))
                pos[int(p[1])][r] = (float(p[2]), float(p[3]))
    # round -> imsi -> cell -> [sumS_mW, sumSinr_lin, n]
    agg = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0, 0.0])))
    with open(os.path.join(d, 'MmWaveJammerRx.txt')) as f:
        f.readline()
        for line in f:
            p = line.split()
            if len(p) < 7:
                continue
            r = int(float(p[0]) * 10 + 1e-9); u = int(p[1]); c = int(p[2])
            a = agg[r][u][c]
            a[0] += 10 ** (float(p[3]) / 10); a[1] += 10 ** (float(p[6]) / 10); a[2] += 1; a[3] += 10 ** (float(p[5]) / 10)
    obs = {}  # round -> imsi -> (S_mW, sinr_lin, N_mW)
    for r, us in agg.items():
        o = {}
        for u, cs in us.items():
            best = max(cs.values(), key=lambda a: a[0] / a[2])
            o[u] = (best[0] / best[2], best[1] / best[2], best[3] / best[2])
        obs[r] = o
    track = {}   # mobile jammer (patch_mobile_jammer_xapp.py): jammer_track.txt t_s,x,y every 100 ms
    tp = os.path.join(d, 'jammer_track.txt')
    if os.path.exists(tp):
        with open(tp) as f:
            f.readline()
            for line in f:
                q = line.strip().split(',')
                if len(q) >= 3:
                    track[int(round(float(q[0]) * 10))] = (float(q[1]), float(q[2]))
    return (jx, jy, t0, t1, track), pos, obs

def wpct(vals, w, q):
    s = sorted(zip(vals, w)); tot = sum(w); acc = 0
    for v, ww in s:
        acc += ww
        if acc >= q * tot:
            return v
    return s[-1][0]

def fitqn(obs, gx, gy):
    # for a fixed position, J_k = Q - n * L_k is linear in (Q, n); soft-l1 (scale 6 dB) by IRLS, n clamped
    L = [10 * math.log10(max(math.hypot(p[0] - gx, p[1] - gy), 1.0)) for p, _ in obs]
    y = [j for _, j in obs]; w = [1.0] * len(obs)
    for _ in range(6):
        sw = sum(w); sl = sum(a * b for a, b in zip(w, L)); sy = sum(a * b for a, b in zip(w, y))
        sll = sum(a * b * b for a, b in zip(w, L)); sly = sum(a * b * c for a, b, c in zip(w, L, y))
        den = sw * sll - sl * sl
        n = -(sw * sly - sl * sy) / den if abs(den) > 1e-9 else 3.0
        n = min(max(n, 1.5), 5.0)
        Q = (sy + n * sl) / sw
        rr = [yy - (Q - n * ll) for yy, ll in zip(y, L)]
        w = [1.0 / math.sqrt(1 + (e / 6.0) ** 2) for e in rr]
    return sum(2 * 36 * (math.sqrt(1 + (e / 6.0) ** 2) - 1) for e in rr)

def trilat(obs):
    best = min((fitqn(obs, gx, gy), gx, gy) for gx in range(0, 1001, 25) for gy in range(0, 1001, 25))
    bx, by = best[1], best[2]
    best = min((fitqn(obs, gx, gy), gx, gy) for gx in range(bx - 25, bx + 26, 5) for gy in range(by - 25, by + 26, 5))
    return best[1], best[2]

def run(d):
    (jx0, jy0, t0, t1, track), pos, obs = load(d)
    r0, r1 = int(t0 * 10), int(t1 * 10)
    base = {}
    for r in range(max(1, r0 - 25), r0):           # baseline: 2.5 s before the attack
        for u, (S, g, N) in obs.get(r, {}).items():
            base.setdefault(u, []).append(10 * math.log10(g))
    base = {u: st.mean(v) for u, v in base.items()}
    res = {k: [] for k in ('E0', 'E1', 'E2', 'E3', 'E1b', 'E2b', 'E4', 'E4c', 'E4w', 'E4b', 'E4bc', 'E4bw')}; rad = {k: [] for k in ('E0', 'E1', 'E1b')}
    cum = [0.0, 0.0, 0.0]; cumb = [0.0, 0.0, 0.0]
    win = defaultdict(list); e4obs = []; winb = defaultdict(list); e4bobs = []
    hist = {'E4': [], 'E4b': []}
    for r in range(r0 + 1, r1 + 1):
        jx, jy = track.get(r, (jx0, jy0))     # ground truth (moves for a mobile jammer)
        o = obs.get(r, {})
        pts = []
        for u, (S, g, N) in o.items():
            if u not in base or u not in pos or not pos[u]:
                continue
            pr = pos[u].get(r) or pos[u][min(pos[u], key=lambda k: abs(k - r))]
            sdb = 10 * math.log10(g); drop = base[u] - sdb
            jh = S * (1 / g - 1 / (10 ** (base[u] / 10)))
            pts.append((u, pr, sdb, drop, jh))
            jn = S / g - N                       # E4: J^ = S/SINR - N (noise known from B and NF)
            win[u].append((r, pr, jn, N))
            # E4b: KPM-feasible variant (ns-O-RAN KPM has no RSRP): J^/N = SINR_base/SINR - 1
            winb[u].append((r, pr, N * (10 ** (drop / 10) - 1), N))
        # E0
        e0 = [(p, min(max(dr, 1), 40)) for (u, p, s, dr, jh) in pts if s < 0 and dr >= 8]
        if e0:
            sw = sum(w for _, w in e0); x = sum(p[0] * w for p, w in e0) / sw; y = sum(p[1] * w for p, w in e0) / sw
            res['E0'].append(math.hypot(x - jx, y - jy))
            rad['E0'].append(max(30, max(math.hypot(p[0] - x, p[1] - y) for p, _ in e0) + 20))
        # E1 / E2
        e1 = [(p, jh) for (u, p, s, dr, jh) in pts if dr >= 3 and jh > 0]
        if e1:
            sw = sum(w for _, w in e1); x = sum(p[0] * w for p, w in e1) / sw; y = sum(p[1] * w for p, w in e1) / sw
            res['E1'].append(math.hypot(x - jx, y - jy))
            rad['E1'].append(wpct([math.hypot(p[0] - x, p[1] - y) for p, _ in e1], [w for _, w in e1], 0.8))
            cum[0] += sw * x; cum[1] += sw * y; cum[2] += sw
            res['E2'].append(math.hypot(cum[0] / cum[2] - jx, cum[1] / cum[2] - jy))
        # E1b / E2b: SINR-only weights (KPM-feasible): J^/N ~ 10^(drop/10) - 1
        eb = [(p, 10 ** (dr / 10) - 1) for (u, p, s, dr, jh) in pts if dr >= 3]
        if eb:
            sw = sum(w for _, w in eb); x = sum(p[0] * w for p, w in eb) / sw; y = sum(p[1] * w for p, w in eb) / sw
            res['E1b'].append(math.hypot(x - jx, y - jy))
            rad['E1b'].append(wpct([math.hypot(p[0] - x, p[1] - y) for p, _ in eb], [w for _, w in eb], 0.8))
            cumb[0] += sw * x; cumb[1] += sw * y; cumb[2] += sw
            res['E2b'].append(math.hypot(cumb[0] / cumb[2] - jx, cumb[1] / cumb[2] - jy))
        # E4: interference-power trilateration of ratti2026 (1-s windows, median J^, INR >= 6 dB,
        #     robust soft-l1 LS over (x, y, Q, n), n in [1.5, 5]); E4c = all windows of the attack so far
        if (r - r0) % 10 == 0:
            for W, acc, k1, k2 in ((win, e4obs, 'E4', 'E4c'), (winb, e4bobs, 'E4b', 'E4bc')):
                new = []
                for u, L in W.items():
                    if not L:
                        continue
                    js = sorted(x[2] for x in L); jm = js[len(js) // 2]; nm = st.mean(x[3] for x in L)
                    if jm > 0 and jm / nm >= 10 ** 0.6:
                        new.append(((st.mean(x[1][0] for x in L), st.mean(x[1][1] for x in L)), 10 * math.log10(jm)))
                W.clear()
                acc += new
                hist[k1].append(new)   # E4w: sliding window of the last 3 s (mobile jammer)
                sw3 = [o2 for h in hist[k1][-3:] for o2 in h]
                if len(sw3) >= 2:
                    ex, ey = trilat(sw3); res[k1 + 'w'].append(math.hypot(ex - jx, ey - jy))
                if len(new) >= 2:
                    ex, ey = trilat(new); res[k1].append(math.hypot(ex - jx, ey - jy))
                if len(acc) >= 2:
                    ex, ey = trilat(acc); res[k2].append(math.hypot(ex - jx, ey - jy))
        # E3
        e3 = [(p, 10 * math.log10(jh)) for (u, p, s, dr, jh) in pts if dr >= 3 and jh > 0]
        if len(e3) >= 3:
            def cost(gx, gy):
                ds = [10 * NEXP * math.log10(max(math.hypot(p[0] - gx, p[1] - gy), 1.0)) for p, _ in e3]
                P = sum(y + dd for (_, y), dd in zip(e3, ds)) / len(e3)
                return sum((y - (P - dd)) ** 2 for (_, y), dd in zip(e3, ds))
            best = min((cost(gx, gy), gx, gy) for gx in range(0, 1001, 25) for gy in range(0, 1001, 25))
            bx, by = best[1], best[2]
            best = min((cost(gx, gy), gx, gy) for gx in range(bx - 25, bx + 26, 5) for gy in range(by - 25, by + 26, 5))
            res['E3'].append(math.hypot(best[1] - jx, best[2] - jy))
    return res, rad

tot = {k: [] for k in ('E0', 'E1', 'E2', 'E3', 'E1b', 'E2b', 'E4', 'E4c', 'E4w', 'E4b', 'E4bc', 'E4bw')}; totr = {'E0': [], 'E1': [], 'E1b': []}; first = {k: [] for k in tot}
for d in dirs:
    try:
        res, rad = run(d)
    except Exception as e:
        print('skip', d, e); continue
    line = os.path.basename(d.rstrip('/'))
    for k in tot:
        if res[k]:
            tot[k].append(st.median(res[k])); first[k].append(st.mean(res[k][:10]))
            line += '  %s %4.0f m' % (k, st.median(res[k]))
    for k in totr:
        if rad[k]:
            totr[k].append(st.median(rad[k]))
    print(line)

print('\nover %d runs (median over the attack of each run; mean +- std over runs)' % len(dirs))
names = {'E0': 'current (drop-weighted, max radius)', 'E1': 'power-weighted centroid',
         'E2': 'power-weighted + smoothing', 'E3': 'path-loss least squares',
         'E1b': 'SINR-only weighted centroid', 'E2b': 'SINR-only + smoothing',
         'E4': 'interference trilat. ratti2026 (1-s window)', 'E4c': 'interference trilat., all windows',
         'E4w': 'interference trilat., last 3 s', 'E4bw': 'SINR-only interf. trilat., last 3 s',
         'E4b': 'SINR-only interference trilat. (KPM)', 'E4bc': 'SINR-only interf. trilat., all windows'}
for k in ('E0', 'E1', 'E2', 'E3', 'E1b', 'E2b', 'E4', 'E4c', 'E4w', 'E4b', 'E4bc', 'E4bw'):
    v = tot[k]
    if not v:
        continue
    s = '%-38s error %5.0f +- %3.0f m   first 1 s %5.0f m' % (names[k], st.mean(v), st.pstdev(v), st.mean(first[k]))
    if k in totr and totr[k]:
        s += '   radius %4.0f m' % st.mean(totr[k])
    print(s)
