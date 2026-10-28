# Handover churn and ping-pong per run
#   usage: python3 ~/ho_churn.py <run_dir_glob> [...]          e.g. "~/jamx_F/pw50_p*_s*"
# Cell changes per UE are collected from
#   UeHandoverEndStats.txt   (time imsi cellId rnti)   NR-NR / RAN handovers
#   LteSwitchStats.txt       (time imsi cellId rnti)   switch to the LTE anchor   (cell 1)
#   MmWaveSwitchStats.txt    (time imsi cellId rnti)   switch back to an NR cell
#   jamguard_local.csv / jamguard_log.csv              xApp actions (HO_NR, EVAC_LTE, PROBE, RETURN, PROBE_FAIL)
# Metrics: cell changes per UE per minute, ping-pong = A->B->A within 1 s, actions per UE per minute,
# --nue N: UEs in the scenario (default 10; 20 for jamx_H). Split by slice (military 2, ambulance 5, IoT 9 by default; JG_SLICES-like string with --slices).
import csv, glob, os, re, sys
from collections import defaultdict

PP_WIN = 1.0
SL = {2: 'military', 5: 'ambulance', 9: 'iot'}
args = sys.argv[1:]
if '--slices' in args:
    i = args.index('--slices'); s = args[i + 1]; del args[i:i + 2]
    SL = {int(a.split(':')[0]): a.split(':')[1] for a in s.split(',')}
NUE = 10
if '--nue' in args:
    i = args.index('--nue'); NUE = int(args[i + 1]); del args[i:i + 2]
dirs = []
for a in args:
    dirs += sorted(glob.glob(os.path.expanduser(a)))
if not dirs:
    sys.exit('no run directories')

def rows(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        m = re.search(r'([0-9.]+)\s+imsi\s*=\s*(\d+)\s+cellId\s*=\s*(\d+)', line)
        if m:   # "SwitchToMmWave 4.32 imsi = 7 cellId = 4 rnti = 3" (switch files)
            out.append((float(m.group(1)), int(m.group(2)), int(m.group(3)))); continue
        p = line.replace(',', ' ').split()
        if len(p) < 3:
            continue
        try:
            out.append((float(p[0]), int(float(p[1])), int(float(p[2]))))
        except ValueError:
            continue   # header
    return out

def sim_time(d):
    # simulated time [s] = last line of MmWaveJammerRx.txt (ue_position.txt has a run-specific offset)
    pth = os.path.join(d, 'MmWaveJammerRx.txt')
    if os.path.exists(pth):
        with open(pth, 'rb') as fh:
            fh.seek(0, 2); n = fh.tell(); fh.seek(max(0, n - 4000))
            last = fh.read().decode(errors='ignore').strip().splitlines()[-1]
        try:
            return float(last.split()[0])
        except ValueError:
            pass
    return 0.0

def churn(ev):
    """ev: imsi -> [(t, new_cell)]; every event to a different cell is one change (the initial cell is not
    logged, so the first event is a change too); ping-pong = A->B->A with the stay in B <= PP_WIN"""
    chg = pp = crit = 0
    for u, seq in ev.items():
        seq.sort()
        cells = []
        for t, c in seq:
            if not cells or cells[-1][1] != c:
                cells.append((t, c))
        n0 = len(cells) - (1 if cells and cells[0][0] < 0.5 else 0)   # initial attach (t < 0.5 s) is not a change
        chg += n0
        if u in SL:
            crit += n0
        for k in range(2, len(cells)):
            if cells[k][1] == cells[k - 2][1] and cells[k][0] - cells[k - 1][0] <= PP_WIN:
                pp += 1
    return chg, pp, crit

tot = defaultdict(list)
print('RAN = cell changes in the RAN traces (handover/switch files); XA = cell changes commanded in the xApp log')
print('%-30s %8s %6s %8s %8s %6s %8s %9s' % ('run', 'RAN/UE/m', 'RANpp', 'RANcrit', 'XA/UE/m', 'XApp', 'XAcrit', 'act/UE/m'))
for d in dirs:
    ev = defaultdict(list)
    for f in ('UeHandoverEndStats.txt', 'MmWaveSwitchStats.txt'):
        for t, u, c in rows(os.path.join(d, f)):
            ev[u].append((t, c))
    for t, u, c in rows(os.path.join(d, 'LteSwitchStats.txt')):
        ev[u].append((t, 1))
    xa = defaultdict(list); na = 0
    for lg in ('jamguard_local.csv', 'jamguard_log.csv'):
        pth = os.path.join(d, lg)
        if os.path.exists(pth):
            for r in csv.DictReader(open(pth)):
                e = r.get('event') or ''
                if e in ('HO_NR', 'EVAC_LTE', 'PROBE', 'RETURN', 'PROBE_FAIL'):
                    try:
                        u = int(r.get('imsi') or 0); to = int(r.get('to_cell') or 0)
                        tt = float(r.get('t_s') or r.get('t_rep_s') or 0)
                    except ValueError:
                        continue
                    na += 1
                    if u > 0 and to > 0:
                        xa[u].append((tt, to))
            break
    T = sim_time(d) / 60.0
    if T <= 0:
        print('skip', d, '(no time)'); continue
    n = NUE
    c1, p1, k1 = churn(ev)
    c2, p2, k2 = churn(xa)
    name = os.path.relpath(d, os.path.expanduser('~'))
    print('%-30s %8.2f %6d %8d %8.2f %6d %8d %9.2f' % (name[-30:], c1 / n / T, p1, k1, c2 / n / T, p2, k2, na / n / T))
    key = os.path.basename(d.rstrip('/')).rsplit('_s', 1)[0]
    tot[key].append((c1 / n / T, p1 / n / T, c2 / n / T, p2 / n / T, na / n / T))

print('\nmean over seeds (per UE per minute)')
for k, v in sorted(tot.items()):
    m = [sum(x[i] for x in v) / len(v) for i in range(5)]
    print('%-16s n=%d  RAN changes %.2f  RAN ping-pong %.3f  | xApp changes %.2f  xApp ping-pong %.3f  actions %.2f'
          % (k, len(v), *m))
