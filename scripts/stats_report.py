#!/usr/bin/env python3
"""Paired-policy significance test over seeds (exact two-sided permutation test).
usage: python3 ~/stats_report.py ~/jamx_F [t0 t1]"""
import sys, os, re, glob, itertools, statistics as st, subprocess, collections
root = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/jamx_F')
T0 = sys.argv[2] if len(sys.argv) > 2 else '4'; T1 = sys.argv[3] if len(sys.argv) > 3 else '10'
SL = {2: ('military', 50.0), 5: ('ambulance', 100.0)}
V = collections.defaultdict(dict)
for d in sorted(glob.glob(root + '/pw*_p*_s*')):
    m = re.search(r'pw(\d+)_(p\d)_s(\d+)$', d)
    if not m or not os.path.exists(d + '/ue_rx.txt'): continue
    last = open(d + '/ue_rx.txt').read().strip().splitlines()[-1].split(',')[0]
    if float(last) < 13.5: continue
    pw, pol, s = int(m.group(1)), m.group(2), int(m.group(3))
    out = subprocess.run(['python3', os.path.expanduser('~/slice_report.py'), d, T0, T1, '5'], capture_output=True, text=True).stdout
    for line in out.splitlines():
        f = line.split()
        if len(f) == 5 and f[0] in ('military', 'ambulance', 'eMBB'):
            V[(pw, pol, f[0] + ' deliv%')][s] = float(f[3]); V[(pw, pol, f[0] + ' delay')][s] = float(f[4])
    pf = d + '/pkt_delay.txt'
    if os.path.exists(pf):
        per = collections.defaultdict(list)
        for line in open(pf):
            x = line.split(',')
            try:
                t, im, dl = float(x[0]) / 1000, int(x[1]), float(x[2]) / 1000
            except (ValueError, IndexError): continue
            if im in SL and float(T0) < t <= float(T1): per[im].append(dl)
        for im, v in per.items():
            v.sort(); name, ddl = SL[im]
            V[(pw, pol, name + ' p95')][s] = v[min(len(v) - 1, int(0.95 * (len(v) - 1)))]
            V[(pw, pol, name + ' miss%')][s] = 100.0 * sum(1 for y in v if y > ddl) / len(v)
def perm_p(a, b):
    obs = abs(st.mean(a) - st.mean(b)); pool = a + b; n = len(a); cnt = tot = 0
    for idx in itertools.combinations(range(len(pool)), n):
        x = [pool[i] for i in idx]; y = [pool[i] for i in range(len(pool)) if i not in idx]
        tot += 1; cnt += abs(st.mean(x) - st.mean(y)) >= obs - 1e-12
    return cnt / tot
PAIRS = [('p4', 'p0'), ('p4', 'p5'), ('p4', 'p6'), ('p4', 'p2'), ('p2', 'p1')]
metrics = sorted({k[2] for k in V}); pws = sorted({k[0] for k in V})
print('window (%s,%s] s ; exact permutation test over seeds ; * p<0.05  ** p<0.01' % (T0, T1))
for pw in pws:
    print('\n===== %d dBm' % pw)
    print('%-20s' % 'metric' + ''.join('%-24s' % ('%s vs %s' % p) for p in PAIRS))
    for mt in metrics:
        row = '%-20s' % mt
        for a, b in PAIRS:
            A, Bv = V.get((pw, a, mt), {}), V.get((pw, b, mt), {})
            if len(A) < 3 or len(Bv) < 3: row += '%-24s' % '-'; continue
            p = perm_p(list(A.values()), list(Bv.values()))
            star = '**' if p < 0.01 else ('*' if p < 0.05 else '')
            row += '%-24s' % ('%+.1f p=%.3f%s' % (st.mean(A.values()) - st.mean(Bv.values()), p, star))
        print(row)
