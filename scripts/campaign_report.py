#!/usr/bin/env python3
# usage: python3 ~/campaign_report.py ~/jamx_C [t0 t1]   (default jammer window 4 10)
import sys, os, re, glob, subprocess, statistics as st
root = os.path.expanduser(sys.argv[1]); t0 = sys.argv[2] if len(sys.argv) > 2 else '4'; t1 = sys.argv[3] if len(sys.argv) > 3 else '10'
SL = ['military', 'ambulance', 'IoT', 'eMBB']
data = {}; meta = {}
def complete(d, tmin=13.5):
    try:
        with open(d + '/ue_rx.txt', 'rb') as f:
            f.seek(0, 2); n = f.tell(); f.seek(max(0, n - 300))
            last = f.read().decode(errors='ignore').strip().splitlines()[-1]
        return float(last.split(',')[0]) >= tmin
    except Exception:
        return False
skipped = 0
for d in sorted(glob.glob(root + '/pw*_p*_s*')):
    m = re.search(r'pw(\d+)_p(\d)_s(\d+)$', d)
    if not m or not os.path.exists(d + '/ue_rx.txt'): continue
    if not complete(d):
        skipped += 1; continue
    key = (int(m.group(1)), int(m.group(2)))
    out = subprocess.run(['python3', os.path.expanduser('~/slice_report.py'), d, t0, t1, '5'], capture_output=True, text=True).stdout
    for line in out.splitlines():
        f = line.split()
        if len(f) == 5 and f[0] in SL:
            data.setdefault(key, {}).setdefault(f[0], []).append((float(f[3]), float(f[4])))
    lat, fa, na = float('nan'), 0, 0
    c = d + '/jamguard_local.csv'
    if os.path.exists(c):
        for row in open(c).read().splitlines()[1:]:
            x = row.split(',')
            t, ev = float(x[0]), x[2]
            if ev == 'DETECT':
                if t < 4.0 or t > 10.5: fa += 1
                elif lat != lat: lat = (t - 4.0) * 1000
    log = d + '/log.txt'
    if os.path.exists(log): na = sum(1 for l in open(log) if 'APPLY' in l)
    meta.setdefault(key, []).append((lat, fa, na))
def ms(v):
    v = [x for x in v if x == x]
    if not v: return '   -   '
    return '%6.1f±%-5.1f' % (st.mean(v), st.stdev(v) if len(v) > 1 else 0.0)
print('window (%s,%s] s ; mean ± std over seeds ; deliv %% / delay ms ; complete runs only (%d still running/incomplete)' % (t0, t1, skipped))
print('%-4s %-3s %-2s  ' % ('dBm', 'pol', 'n') + ''.join('%-28s' % s for s in SL) + 'detect_ms     falseAlarm  actions')
for key in sorted(data):
    row = '%-4d p%-2d %-2d  ' % (key[0], key[1], len(meta.get(key, [])))
    for s in SL:
        v = data[key].get(s, [])
        row += '%-28s' % (ms([a for a, b in v]) + '/' + ms([b for a, b in v]).strip())
    mt = meta.get(key, [])
    row += '%-13s %-11s %s' % (ms([a for a, b, c in mt]).strip(), ms([b for a, b, c in mt]).strip(), ms([c for a, b, c in mt]).strip())
    print(row)
