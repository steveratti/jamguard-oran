# Offline ROC of JamGuard detectors on logged runs (no new simulation needed)        v2
#   usage: python3 ~/roc_replay.py <run_dir_glob> [...] [--block R] [--k 1,2]
#          e.g.  python3 ~/roc_replay.py "~/jamx_F/pw*_p0_s*" "~/jamx_N/*" --block 2
# Input per run: MmWaveJammerRx.txt (time_s imsi cellId S_dBm J_dBm N_dBm sinr_dB), jammer.txt,
#   UeHandoverEndStats.txt / LteSwitchStats.txt / MmWaveSwitchStats.txt (time imsi cell rnti).
# v2: the serving cell is the RAN's real serving cell (first strongest cell, then changed only by logged
#   handovers; rounds on the LTE anchor are skipped), as in the live xApp. v1 re-picked the strongest cell
#   every round, which reset the UE baselines under fading and under-counted detections.
# Only KPM quantities are used by the detectors (serving / neighbour SINR and RSRP). J is used only as
# ground truth: a UE is "really jammed" in a round if J >= N + 3 dB on its serving link.
# Detectors (a UE is degraded if ...), alarm = K UEs degraded for P consecutive rounds:
#   D1 SINR      serving SINR < S_low and >= DROP below the UE's own baseline   (current JamGuard)
#   D2 +MLINK    D1 and the median neighbour SINR drop >= DROP/2               (jammer hits all links)
#   D3 +RSRP     D1 and serving RSRP dropped < 3 dB                              (SINR falls, signal does not)
#   D4 both      D2 and D3
# Metrics: Pd = attack episodes with an alarm onset inside the episode; delay = onset - start;
#   FA/min = alarm onsets per minute outside [start - 0.1, stop + 2] s;
#   UE recall = really-jammed UE-rounds flagged degraded; UE false flags = UE flag onsets (P rounds) while
#   the UE is not jammed, per UE per minute (these would be wrong evacuations).
# --block R: trace-driven nuisance injection (no buildings in the scenario): per UE, Poisson blockage at
#   R per minute, 0.5-2 s, 15-30 dB on the serving link only (signal AND SINR fall). Fixed seed per run.
import glob, math, os, random, sys, zlib
from collections import defaultdict

args = sys.argv[1:]
def opt(name, default):
    if name in args:
        i = args.index(name); v = args[i + 1]; del args[i:i + 2]; return v
    return default
BLOCK = float(opt('--block', 0))
DMCS = float(opt('--dmcs', 4))   # ROCMCS: MCS indices below the UE's own baseline
KS = [int(k) for k in opt('--k', '1,2').split(',')]
PULSE = '--pulse' in args   # ROCEP: per-pulse episodes only on request
if PULSE: args.remove('--pulse')
S_LOW, P = 0.0, 3
DROPS = (4, 6, 8, 10, 12)
DET = ('D1', 'D2', 'D3', 'D4')
DET = list(DET) + [x for x in ('D5', 'D6') if x not in DET]   # ROCMCS
DET = list(DET) + ['D7']   # ROCD7

dirs = []
for a in args:
    dirs += sorted(glob.glob(os.path.expanduser(a)))
if not dirs:
    sys.exit('no run directories')

def events(d):
    ev = defaultdict(list)
    for f, lte in (('UeHandoverEndStats.txt', 0), ('MmWaveSwitchStats.txt', 0), ('LteSwitchStats.txt', 1)):
        pth = os.path.join(d, f)
        if not os.path.exists(pth):
            continue
        for line in open(pth):
            p = line.replace(',', ' ').split()
            try:
                t, u, c = float(p[0]), int(p[1]), int(p[2])
            except (ValueError, IndexError):
                continue
            ev[u].append((int(t * 10 + 1e-9), 1 if lte else c))
    for u in ev:
        ev[u].sort()
    return ev

def load(d):
    jam = open(os.path.join(d, 'jammer.txt')).read().strip().splitlines()
    J = dict(zip(jam[0].split(','), jam[1].split(',')))
    t0, t1, pw = float(J['start_s']), float(J['stop_s']), float(J['power_dbm'])
    per, duty = float(J.get('period_ms', 0) or 0), float(J.get('duty', 0.5) or 0.5)
    agg = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])))
    with open(os.path.join(d, 'MmWaveJammerRx.txt')) as f:
        f.readline()
        for line in f:
            p = line.split()
            if len(p) < 7:
                continue
            r = int(float(p[0]) * 10 + 1e-9)
            a = agg[r][int(p[1])][int(p[2])]
            a[0] += 10 ** (float(p[3]) / 10); a[1] += 10 ** (float(p[6]) / 10)
            a[2] += 10 ** (float(p[4]) / 10); a[3] += 10 ** (float(p[5]) / 10); a[4] += 1
    # ROCMCS: mean MCS index per UE per report, from the six PDSCH MCS bins of the DU report.
    # The DU trace has no decodable clock, but its rows are written one per report per UE in
    # order, so instant k is t = (k+1) * period and the replay tick is the same 100 ms.
    mcs = {}
    _bins = ['CARR.PDSCHMCSDist.Bin%d.UEID' % i for i in range(1, 7)]
    _mid = [2.0, 7.0, 12.0, 17.0, 22.0, 27.0]
    for _f in sorted(glob.glob(os.path.join(d, 'du-cell-*.txt'))):
        try:
            _h = open(_f, encoding='latin-1', errors='replace')
        except TypeError:
            _h = open(_f)
        _cols = _h.readline().strip().split(',')
        _cols = [c.strip() for c in _cols]
        try:
            _ix = [_cols.index(b) for b in _bins]
            _iu = _cols.index('ueImsiComplete')
        except ValueError:
            _h.close(); continue
        _k = {}
        for _line in _h:
            _p = _line.rstrip('\n').split(',')
            if len(_p) <= _ix[-1]:
                continue
            try:
                _u = int(_p[_iu])
            except ValueError:
                continue
            _k[_u] = _k.get(_u, 0) + 1
            _n = _t = 0.0
            for _j, _c in zip(_ix, _mid):
                try:
                    _v = float(_p[_j])
                except ValueError:
                    _v = 0.0
                _n += _v * _c; _t += _v
            if _t > 0:
                mcs.setdefault(_k[_u], {})[_u] = _n / _t
    ev = events(d)
    srvmap, evi = {}, defaultdict(int)
    obs = {}
    for r in sorted(agg):
        o = {}
        for u, cs in agg[r].items():
            m = {c: (10 * math.log10(a[0] / a[4]), 10 * math.log10(max(a[1] / a[4], 1e-20))) for c, a in cs.items()}
            jam_true = {c: 10 * math.log10(max(a[2] / a[4], 1e-30)) >= 10 * math.log10(a[3] / a[4]) + 3
                        for c, a in cs.items()}
            if u not in srvmap:
                srvmap[u] = max(m, key=lambda c: m[c][0])
            while evi[u] < len(ev[u]) and ev[u][evi[u]][0] <= r:
                srvmap[u] = ev[u][evi[u]][1]; evi[u] += 1
            srv = srvmap[u]
            if srv == 1 or srv not in m:     # on the LTE anchor or no NR measurement: not observed
                continue
            o[u] = [srv, m, jam_true[srv], mcs.get(r, {}).get(u)]   # ROCMCS
        obs[r] = o
    if BLOCK > 0:
        rng = random.Random(zlib.crc32(os.path.basename(d.rstrip('/')).encode()))
        rs = sorted(obs); ues = sorted({u for r in rs for u in obs[r]})
        for u in ues:
            r = rs[0]
            while True:
                r += int(rng.expovariate(BLOCK / 600.0)) + 1
                if r > rs[-1]:
                    break
                L, depth = rng.randint(5, 20), rng.uniform(15, 30)
                for q in range(r, r + L):
                    if q in obs and u in obs[q]:
                        srv, m, jt, mc = obs[q][u]
                        m = dict(m); m[srv] = (m[srv][0] - depth, m[srv][1] - depth)
                        # ROCMCS: a 15-30 dB loss on the serving link forces the lowest
                        # modulation, so blockage must move the MCS as well; otherwise the
                        # benign baseline is easier for the MCS detector than for the others
                        # and the comparison is rigged in its favour.
                        obs[q][u] = [srv, m, jt, (2.0 if mc is not None else None)]
                r += L
    eps = []
    if pw > -50:
        if per > 0 and PULSE:
            T = per / 1000.0; ts = t0
            while ts < t1 - 1e-9:
                eps.append((ts, min(ts + T * duty, t1))); ts += T
        else:
            eps.append((t0, t1))
    return eps, obs

def detect(obs, drop, det, K):
    base = {}; nbase = defaultdict(dict); cnt = defaultdict(int)
    mbase = {}   # ROCMCS: per-UE MCS baseline, reset on handover like the SINR one
    cntA = defaultdict(int)   # ROCD7: counter that drives the alarm
    alarm, acnt, quiet, onsets = 0, 0, 0, []
    tp = pos = uefa = 0; ueround = 0
    for r in sorted(obs):
        ndeg = 0
        for u, (srv, m, jt, mc) in obs[r].items():   # ROCMCS
            rs, s = m[srv]
            ueround += 1
            if u not in base or base[u][2] != srv:
                base[u] = [s, rs, srv, 1]; cnt[u] = 0
                mbase[u] = [mc, srv, 1] if mc is not None else None   # ROCMCS
                continue
            b = base[u]
            deg = s < S_LOW and b[0] - s >= drop
            # ROCMCS: the modulation the scheduler actually used, against this UE's own baseline
            mb = mbase.get(u)
            degm = (mc is not None and mb is not None and mb[1] == srv and (mb[0] - mc) >= DMCS)
            if det == 'D5':
                deg = degm
            if deg and det in ('D2', 'D4'):
                dd = sorted(nbase[u][c] - m[c][1] for c in m if c != srv and c in nbase[u])
                if dd:
                    med = dd[len(dd) // 2] if len(dd) % 2 else 0.5 * (dd[len(dd) // 2 - 1] + dd[len(dd) // 2])
                    deg = med >= drop / 2
            if deg and det in ('D3', 'D4'):
                deg = b[1] - rs < 3.0
            degA = deg   # ROCD7: by default the alarm and the per-UE flag are the same test
            if det == 'D7':
                degs = s < S_LOW and b[0] - s >= drop
                ml = False
                if degs:
                    dd = sorted(nbase[u][c] - m[c][1] for c in m if c != srv and c in nbase[u])
                    if dd:
                        med = dd[len(dd) // 2] if len(dd) % 2 else 0.5 * (dd[len(dd) // 2 - 1] + dd[len(dd) // 2])
                        ml = med >= drop / 2
                degA = degs and ml                      # alarm: specific, as in D2
                deg = degA or (alarm and degm)          # attribution: sensitive, gated by the alarm
            if det == 'D6':   # ROCMCS: SINR drop, confirmed by the multi-link test or by the MCS
                degs = s < S_LOW and b[0] - s >= drop
                ml = False
                if degs:
                    dd = sorted(nbase[u][c] - m[c][1] for c in m if c != srv and c in nbase[u])
                    if dd:
                        med = dd[len(dd) // 2] if len(dd) % 2 else 0.5 * (dd[len(dd) // 2 - 1] + dd[len(dd) // 2])
                        ml = med >= drop / 2
                deg = degs and (ml or degm)
            if jt:
                pos += 1; tp += 1 if deg else 0
            if deg:
                cnt[u] += 1
                if cnt[u] == P and not jt:
                    uefa += 1
            else:
                cnt[u] = 0
                if not alarm or s >= 5.0:
                    n = b[3]
                    b[0] = (b[0] * n + s) / (n + 1) if n < 10 else 0.9 * b[0] + 0.1 * s
                    b[1] = (b[1] * n + rs) / (n + 1) if n < 10 else 0.9 * b[1] + 0.1 * rs
                    b[3] += 1
                    if mc is not None:   # ROCMCS: track the MCS baseline too
                        if mb is None:
                            mbase[u] = [mc, srv, 1]
                        else:
                            mb[0] = (mb[0] * mb[2] + mc) / (mb[2] + 1) if mb[2] < 10 \
                                    else 0.9 * mb[0] + 0.1 * mc
                            mb[2] += 1
                    for c in m:
                        if c != srv:
                            nb = nbase[u].get(c)
                            nbase[u][c] = m[c][1] if nb is None else 0.9 * nb + 0.1 * m[c][1]
            cntA[u] = cntA[u] + 1 if degA else 0   # ROCD7
            if (cntA[u] if det == 'D7' else cnt[u]) > 0:
                ndeg += 1
        acnt = acnt + 1 if ndeg >= K else 0
        if not alarm and acnt >= P:
            alarm = 1; quiet = 0; onsets.append(r)
        elif alarm:
            quiet = quiet + 1 if ndeg == 0 else 0
            if quiet >= 20:
                alarm = 0
    return onsets, tp, pos, uefa, ueround

res = {(dt, dr, k): dict(ep=0, hit=0, delay=[], fa=0, negmin=0.0, tp=0, pos=0, uefa=0, uemin=0.0)
       for dt in DET for dr in DROPS for k in KS}
for d in dirs:
    try:
        eps, obs = load(d)
    except Exception as e:
        print('skip', d, e); continue
    rounds = sorted(obs)
    negset = {r for r in rounds if not any(a * 10 - 1 <= r <= b * 10 + 20 for a, b in eps)}
    for dt in DET:
        for dr in DROPS:
            for k in KS:
                on, tp, pos, uefa, uer = detect(obs, dr, dt, k)
                x = res[(dt, dr, k)]
                x['negmin'] += len(negset) / 600.0
                x['fa'] += sum(1 for r in on if r in negset)
                if os.environ.get('RR_FA') and dt == 'D5' and dr == 4: print('FAON', os.path.basename(d.rstrip('/')), k, sorted(r / 10.0 for r in on if r in negset))
                x['tp'] += tp; x['pos'] += pos; x['uefa'] += uefa; x['uemin'] += uer / 600.0
                for a, b in eps:
                    x['ep'] += 1
                    hit = [r for r in on if a * 10 <= r <= b * 10 + 1]
                    if hit:
                        x['hit'] += 1; x['delay'].append(hit[0] / 10.0 - a)
    nobs = sum(len(obs[r]) for r in rounds)
    print('%-28s episodes %d  negative %.1f s  UE-rounds %d' % (os.path.basename(d.rstrip('/')), len(eps),
                                                               len(negset) / 10.0, nobs))

print('\nP=%d S_low=%.0f dB, %d runs, injected blockage %.1f /UE/min' % (P, S_LOW, len(dirs), BLOCK))
print('%-3s %4s %2s %7s %8s %8s %4s %9s %13s' % ('det', 'drop', 'K', 'Pd', 'delay_s', 'FA/min', 'FA',
                                                'UE_recall', 'UE_FF/UE/min'))
for k in KS:
    for dt in DET:
        for dr in DROPS:
            x = res[(dt, dr, k)]
            nan = float('nan')
            print('%-3s %4d %2d %7.3f %8.2f %8.3f %4d %9.3f %13.3f' % (
                dt, dr, k, x['hit'] / x['ep'] if x['ep'] else nan,
                sum(x['delay']) / len(x['delay']) if x['delay'] else nan,
                x['fa'] / x['negmin'] if x['negmin'] else nan, x['fa'],
                x['tp'] / x['pos'] if x['pos'] else nan, x['uefa'] / x['uemin'] if x['uemin'] else nan))
