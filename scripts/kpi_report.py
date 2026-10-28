#!/usr/bin/env python3
"""Per-UE KPIs before / during / after the jammer, compared across policies.
usage: python3 ~/kpi_report.py <root> <power> <imsi> [policies]   e.g.  ~/jamx_C 50 2 p0,p2,p4
RSSI proxy = S + J + N (power sum) ; RSRQ proxy = S / RSSI  (ns-3 mmWave does not report 3GPP RSRP/RSRQ)."""
import sys, os, glob, math, statistics as st, collections
root = os.path.expanduser(sys.argv[1]); PW = int(sys.argv[2]); IM = int(sys.argv[3])
POLS = (sys.argv[4] if len(sys.argv) > 4 else 'p0,p2,p4').split(',')
WIN = [('before', 1.0, 3.99), ('during', 4.0, 10.0), ('after', 10.0, 14.0)]
def w_of(t):
    for n, a, b in WIN:
        if a < t <= b: return n
def db2mw(x): return 0.0 if x <= -900 else 10 ** (x / 10.0)
def mw2db(x): return -999.0 if x <= 0 else 10 * math.log10(x)
def run_kpis(d):
    K = collections.defaultdict(lambda: collections.defaultdict(list))
    f = d + '/MmWaveJammerRx.txt'
    if os.path.exists(f):
        for line in open(f):
            x = line.split()
            if len(x) < 7 or not x[1].isdigit() or int(x[1]) != IM: continue
            w = w_of(float(x[0]))
            if not w: continue
            S, J, N, sinr = float(x[3]), float(x[4]), float(x[5]), float(x[6])
            rssi = db2mw(S) + db2mw(J) + db2mw(N)
            K[w]['S_dBm'].append(S); K[w]['J_dBm'].append(J if J > -900 else float('nan'))
            K[w]['J_on_%'].append(100.0 if J > -900 else 0.0)
            K[w]['RSSI_dBm'].append(mw2db(rssi)); K[w]['RSRQ_dB'].append(S - mw2db(rssi)); K[w]['SINR_dB'].append(sinr)
    f = d + '/DlMacStats.txt'
    if os.path.exists(f):
        for line in open(f):
            x = line.split()
            if len(x) < 8 or x[0].startswith('%') or int(x[2]) != IM: continue
            w = w_of(float(x[0]))
            if not w: continue
            if x[1] == '1': K[w]['LTE_MCS'].append(float(x[6]))
    ev = []
    for f in (d + '/LteSwitchStats.txt', d + '/MmWaveSwitchStats.txt'):
        if not os.path.exists(f): continue
        for line in open(f):
            x = line.replace('=', ' ').split()
            try:
                if 'imsi' in x and int(x[x.index('imsi') + 1]) == IM and x[0].startswith('SwitchTo'):
                    ev.append((float(x[1]), x[0].startswith('SwitchToLte')))
            except (ValueError, IndexError): pass
    ev.sort()
    for n, a, b in WIN:
        on, state, t0 = 0.0, False, a
        for te, lte in ev:
            if te <= a: state = lte; continue
            if te >= b: break
            if state: on += te - t0
            state, t0 = lte, te
        if state: on += b - t0
        K[n]['onLTE_%'].append(100.0 * on / (b - a))
    f = d + '/ue_rx.txt'
    if os.path.exists(f):
        rows = {}
        for line in open(f):
            x = line.split(',')
            try:
                if int(x[1]) == IM: rows[round(float(x[0]), 1)] = (float(x[2]), float(x[3]), float(x[4]))
            except (ValueError, IndexError): pass
        for n, a, b in WIN:
            ra = rows.get(round(a, 1)); tb = max([k for k in rows if k <= b] or [None]) if rows else None
            rb = rows.get(tb) if tb is not None else None
            if tb is not None and tb > a: b = tb
            if ra and rb:
                K[n]['thr_Mbps'].append((rb[0] - ra[0]) * 8 / (b - a) / 1e6)
                if rb[1] > ra[1]: K[n]['delay_ms'].append((rb[2] - ra[2]) / (rb[1] - ra[1]) * 1000)
    f = d + '/pkt_delay.txt'
    if os.path.exists(f):
        per = collections.defaultdict(list)
        for line in open(f):
            x = line.split(',')
            try:
                if int(x[1]) == IM:
                    w = w_of(float(x[0]) / 1000)
                    if w: per[w].append(float(x[2]) / 1000)
            except (ValueError, IndexError): pass
        for w, v in per.items():
            v.sort(); K[w]['p95_ms'].append(v[min(len(v) - 1, int(0.95 * (len(v) - 1)))])
    out = {}
    for w, kv in K.items():
        for k, v in kv.items():
            v = [y for y in v if y == y]
            if v: out[(w, k)] = st.mean(v)
    return out
ORDER = ['S_dBm', 'J_on_%', 'J_dBm', 'RSSI_dBm', 'RSRQ_dB', 'SINR_dB', 'onLTE_%', 'LTE_MCS', 'thr_Mbps', 'delay_ms', 'p95_ms']
agg = {}
for p in POLS:
    runs = [run_kpis(d) for d in sorted(glob.glob('%s/pw%d_%s_s*' % (root, PW, p)))]
    runs = [r for r in runs if r]
    agg[p] = (len(runs), {k: [r[k] for r in runs if k in r] for k in set().union(*runs)} if runs else {})
print('UE %d, %d dBm, mean over seeds (n per policy: %s)' % (IM, PW, ', '.join('%s=%d' % (p, agg[p][0]) for p in POLS)))
print('%-10s' % 'KPI' + ''.join('%-24s' % ('%s  bef/dur/aft' % p) for p in POLS))
for k in ORDER:
    line = '%-10s' % k; any_ = False
    for p in POLS:
        cells = []
        for w, _, _ in WIN:
            v = agg[p][1].get((w, k))
            if v: any_ = True; cells.append('%.1f' % st.mean(v))
            else: cells.append('-')
        line += '%-24s' % ' / '.join(cells)
    if any_: print(line)
