#!/usr/bin/env python3
"""Latency / service-continuity report for the critical slices (from ue_rx.txt, 100 ms bins).
usage: python3 ~/latency_report.py ~/jamx_C [jam_start jam_stop]"""
import sys, os, re, glob, statistics as st, collections
root = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/jamx_C')
J0 = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
J1 = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
CRIT = {2: ('military', 50.0), 5: ('ambulance', 100.0), 9: ('IoT', 100.0)}   # IMSI -> (slice, deadline ms)
res = collections.defaultdict(lambda: collections.defaultdict(list))
for d in sorted(glob.glob(root + '/pw*_p*_s*')):
    m = re.search(r'pw(\d+)_(p\d|b\d)_s(\d+)$', d)
    if not m or not os.path.exists(d + '/ue_rx.txt'): continue
    rows = collections.defaultdict(dict)
    for line in open(d + '/ue_rx.txt'):
        x = line.split(',')
        try: rows[int(x[1])][round(float(x[0]), 1)] = (float(x[2]), float(x[3]), float(x[4]))
        except (ValueError, IndexError): pass
    if not rows or max(max(r) for r in rows.values()) < 13.5: continue        # incomplete run
    key = (int(m.group(1)), m.group(2))
    for im, (sl, ddl) in CRIT.items():
        r = rows.get(im)
        if not r: continue
        def bin_(t):
            a, b = r.get(round(t - 0.1, 1)), r.get(round(t, 1))
            if a is None or b is None: return None
            rate = (b[0] - a[0]) / 0.1
            dn = b[1] - a[1]
            dly = (b[2] - a[2]) / dn * 1000 if dn > 0 else None
            return rate, dly
        pre = [bin_(round(1.0 + 0.1 * k, 1)) for k in range(1, 31)]
        pre = [p[0] for p in pre if p]
        if not pre: continue
        ref = st.mean(pre)
        out, worst, late, nb, restore = 0.0, 0.0, 0, 0, None
        ok_run = 0.0
        t = round(J0 + 0.1, 1)
        while t <= J1 + 1e-9:
            b = bin_(t)
            if b:
                rate, dly = b
                nb += 1
                if rate < 0.5 * ref: out += 0.1
                if dly is not None:
                    worst = max(worst, dly)
                    if dly > ddl: late += 1
                elif rate < 0.5 * ref:
                    late += 1
                if restore is None:
                    ok_run = ok_run + 0.1 if rate >= 0.9 * ref else 0.0
                    if ok_run >= 0.5 - 1e-9: restore = (t - 0.5 - J0) * 1000
            t = round(t + 0.1, 1)
        res[key][sl + '.outage_s'].append(out)
        res[key][sl + '.restore_ms'].append(restore if restore is not None else (J1 - J0) * 1000)
        res[key][sl + '.worst100ms'].append(worst)
        res[key][sl + '.late_pct'].append(100.0 * late / nb if nb else 0.0)
def ms(v): return '%7.1f±%-6.1f' % (st.mean(v), st.stdev(v) if len(v) > 1 else 0.0)
print('jammer window (%.1f, %.1f] s ; deadlines: military 50 ms, ambulance 100 ms ; mean ± std over seeds' % (J0, J1))
for sl in ('military', 'ambulance'):
    print('\n== %s' % sl)
    print('%-4s %-4s %-2s %-15s %-15s %-15s %-15s' % ('dBm', 'pol', 'n', 'outage_s', 'restore_ms', 'worst100ms', 'late_bins_%'))
    for key in sorted(res):
        v = res[key]
        if sl + '.outage_s' not in v: continue
        print('%-4d %-4s %-2d %s %s %s %s' % (key[0], key[1], len(v[sl + '.outage_s']), ms(v[sl + '.outage_s']),
              ms(v[sl + '.restore_ms']), ms(v[sl + '.worst100ms']), ms(v[sl + '.late_pct'])))
