#!/usr/bin/env python3
"""Per-packet latency of the critical slices (pkt_delay.txt: t_ms,imsi,delay_us,seq).
usage: python3 ~/pkt_report.py ~/jamx_F [t0 t1]   -> p50/p95/p99, deadline miss"""
import sys, os, re, glob, statistics as st, collections
root = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/jamx_F')
T0 = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
T1 = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
CRIT = {2: ('military', 50.0), 5: ('ambulance', 100.0), 9: ('IoT', 100.0)}
pool = collections.defaultdict(list); miss = collections.defaultdict(list)
for d in sorted(glob.glob(root + '/pw*_p*_s*')):
    m = re.search(r'pw(\d+)_(p\d|b\d)_s(\d+)$', d); f = d + '/pkt_delay.txt'
    if not m or not os.path.exists(f): continue
    per = collections.defaultdict(list)
    for line in open(f):
        x = line.split(',')
        try: t, im, dl = float(x[0]) / 1000, int(x[1]), float(x[2]) / 1000
        except (ValueError, IndexError): continue
        if im in CRIT and T0 < t <= T1: per[im].append(dl)
    for im, v in per.items():
        sl, ddl = CRIT[im]; k = (int(m.group(1)), m.group(2), sl)
        pool[k] += v; miss[k].append(100.0 * sum(1 for x in v if x > ddl) / len(v))
def pct(v, q):
    v = sorted(v); return v[min(len(v) - 1, int(round(q / 100.0 * (len(v) - 1))))]
print('packets received in (%.1f, %.1f] s ; deadlines military 50 ms, ambulance/IoT 100 ms' % (T0, T1))
print('%-4s %-4s %-10s %8s %8s %8s %8s %14s' % ('dBm', 'pol', 'slice', 'pkts', 'p50', 'p95', 'p99', 'miss% (seeds)'))
for k in sorted(pool):
    v = pool[k]; ms = miss[k]
    print('%-4d %-4s %-10s %8d %8.1f %8.1f %8.1f %7.2f±%-5.2f' % (k[0], k[1], k[2], len(v), pct(v, 50), pct(v, 95), pct(v, 99),
          st.mean(ms), st.stdev(ms) if len(ms) > 1 else 0.0))
