# Live (FlexRIC xApp) vs emulated (in-simulation loop) JamGuard, same seed
#   usage: python3 ~/compare_live.py <live_dir> <emulated_dir>
#   live dir:     jamguard_log.csv, jg_latency.csv, e2_ctrl_rx.csv   (xApp + ns-3 E2 log)
#   emulated dir: jamguard_local.csv
import csv, os, sys, statistics as st

live = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/jamx_live/smoke')
emu = os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else '~/jamx_T/pw50_p4_s1')
ACT = {'DETECT', 'EVAC_LTE', 'HO_NR', 'HOLD_NR', 'PROBE', 'PROBE_OK', 'PROBE_FAIL', 'RETURN',
       'SLICE_CAP', 'SLICE_FREE', 'CLEAR'}

def rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))

def events(path, tcol):
    out = []
    for r in rows(path):
        if r['event'] not in ACT:
            continue
        out.append((float(r[tcol]), r['event'], int(r['imsi']), int(r['from_cell']), int(r['to_cell'])))
    return out

L = [(round(x[0] + float(os.environ.get('OFF', '0')), 2),) + x[1:] for x in events(os.path.join(live, 'jamguard_log.csv'), 't_rep_s')]
E = events(os.path.join(emu, 'jamguard_local.csv'), 't_s')

print('=== decisions: live xApp (%d) vs emulated loop (%d)' % (len(L), len(E)))
print('%-8s %-11s %-6s %-9s | %-8s %-11s %-6s %-9s' % ('t_live', 'event', 'UE', 'from->to', 't_emu', 'event', 'UE', 'from->to'))
used = set(); match = 0; dts = []
for l in L:
    best = None
    for k, e in enumerate(E):
        if k in used or e[1] != l[1] or e[2] != l[2] or e[4] != l[4]:
            continue
        if abs(e[0] - l[0]) <= 1.0 and (best is None or abs(e[0] - l[0]) < abs(E[best][0] - l[0])):
            best = k
    if best is not None:
        used.add(best); match += 1; e = E[best]; dts.append(l[0] - e[0])
        print('%-8.1f %-11s %-6d %d->%-6d | %-8.2f %-11s %-6d %d->%d' % (l[0], l[1], l[2], l[3], l[4], e[0], e[1], e[2], e[3], e[4]))
    else:
        print('%-8.1f %-11s %-6d %d->%-6d | %-8s (no match)' % (l[0], l[1], l[2], l[3], l[4], '-'))
for k, e in enumerate(E):
    if k not in used:
        print('%-8s (no match)                    | %-8.2f %-11s %-6d %d->%d' % ('-', e[0], e[1], e[2], e[3], e[4]))
print('matched %d of %d live and %d emulated decisions' % (match, len(L), len(E)))
if dts:
    print('time offset live - emulated: mean %+.2f s, max |%.2f| s' % (st.mean(dts), max(abs(x) for x in dts)))

# ---------------- latency ----------------
lat = rows(os.path.join(live, 'jg_latency.csv'))
def stat(name, v, unit='ms'):
    if not v:
        print('%-46s n=0' % name); return
    v = sorted(v)
    p = lambda q: v[min(len(v) - 1, int(q * (len(v) - 1) + 0.5))]
    print('%-46s n=%-3d mean %8.3f  median %8.3f  p95 %8.3f  max %8.3f %s' % (name, len(v), st.mean(v), p(.5), p(.95), v[-1], unit))

dec = [r for r in lat if r['kind'] == 'DECIDE']
ctl = [r for r in lat if r['kind'] in ('HO', 'SLICE', 'MCS')]
print('\n=== latency (wall clock, same machine)')
stat('xApp decision (jg_step)', [(int(r['t_end_us']) - int(r['t_start_us'])) / 1000 for r in dec])
stat('KPM arrival -> decision start', [(int(r['t_start_us']) - int(r['t_kpm_us'])) / 1000 for r in dec])
stat('E2 control call (request -> RIC ack)', [(int(r['t_end_us']) - int(r['t_start_us'])) / 1000 for r in ctl])

# xApp send -> ns-3 reception, matched in order per (kind, value)
rx = [r for r in rows(os.path.join(live, 'e2_ctrl_rx.csv')) if r['side'] == 'rx']
ap = [r for r in rows(os.path.join(live, 'e2_ctrl_rx.csv')) if r['side'] == 'apply']
down, rx2ap, used_rx, used_ap = [], [], set(), set()
for r in ctl:
    if r['kind'] == 'HO':
        key = ('3', r['ue_or_cell'], r['target_or_value'])           # value=imsi, cell=target
        cand = [k for k, x in enumerate(rx) if k not in used_rx and x['style'] == '3' and x['value'] == key[1] and x['cell'] == key[2]]
    else:
        v = int(r['target_or_value']); rest = str(v % 1000000); cell = str((v // 1000000) % 10)
        cand = [k for k, x in enumerate(rx) if k not in used_rx and x['style'] == '2' and x['value'] == rest and x['cell'] == cell]
    if not cand:
        continue
    k = cand[0]; used_rx.add(k)
    down.append((int(rx[k]['wall_us']) - int(r['t_start_us'])) / 1000)
    for j, a in enumerate(ap):
        if j not in used_ap and a['style'] == rx[k]['style'] and a['value'] == rx[k]['value'] and a['cell'] == rx[k]['cell']:
            used_ap.add(j); rx2ap.append((int(a['wall_us']) - int(rx[k]['wall_us'])) / 1000); break
stat('E2 downlink: xApp send -> ns-3 E2 reception', down)
stat('ns-3: E2 reception -> action applied', rx2ap)
print('\nnote: ns-3 runs slower than real time, so the last value includes waiting for the simulator thread;')
print('      the KPM -> decision value includes the xApp poll period (JG_POLL_US) and the JG_CLOCK alignment.')
