#!/usr/bin/env python3
"""JamGuard dashboard (local, no extra packages).
   python3 ~/jamguard_dash.py [port] [bind]   -> open http://localhost:8050 in the browser
   bind defaults to 127.0.0.1; use 0.0.0.0 to reach it from another machine.
   Reads run folders under ~/jamx* that contain ue_rx.txt:
     - emulated runs (JamGuard inside ns-3):   jamguard_local.csv  (column 1 = simulated time)
     - live runs (FlexRIC xApp over E2):       jamguard_log.csv    (column 2 = report time, shifted by
       LIVE_OFFSET, default 0.8 s, to simulated time), plus e2_ctrl_rx.csv and jg_latency.csv
   Jammer position and schedule (constant, keyed, several episodes) come from jammer.txt.
   Real time: runs whose files changed in the last 30 s are 'running'; 'follow' jumps to the newest one."""
import http.server, json, os, re, glob, subprocess, sys, time, urllib.parse, statistics

HOME = os.path.expanduser('~')
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8050
BIND = sys.argv[2] if len(sys.argv) > 2 else '127.0.0.1'
LIVE_OFFSET = float(os.environ.get('JG_LIVE_OFFSET', '0.8'))
DEF_SLICES = {2: 1, 5: 2, 9: 3}          # IMSI -> slice (military 1, ambulance 2, IoT 3); others eMBB
SLICE_NAMES = ['eMBB', 'military', 'ambulance', 'IoT']
POLICIES = {0: 'p0 monitor', 1: 'p1 reactive', 2: 'p2 localization', 4: 'p4 slice-aware', 5: 'p5 B2 PRB',
            6: 'p6 B1 MCS', 7: 'p7 A3', 8: 'p8 anchor guard', 9: 'p9 canary'}

def safe(p):
    p = os.path.realpath(os.path.expanduser(p))
    return p if p == HOME or p.startswith(HOME + os.sep) else None

def run_mtime(d):
    m = 0.0
    for f in ('ue_rx.txt', 'jamguard_local.csv', 'jamguard_log.csv'):
        try: m = max(m, os.path.getmtime(os.path.join(d, f)))
        except OSError: pass
    return m

def list_runs():
    out, now = [], time.time()
    for f in glob.glob(HOME + '/jamx*/**/ue_rx.txt', recursive=True):
        d = os.path.dirname(f)
        mt = run_mtime(d)
        out.append({'dir': d, 'name': os.path.relpath(d, HOME), 'mtime': mt,
                    'running': (now - mt) < 30 and not os.path.exists(d + '/.done'),
                    'live': os.path.exists(d + '/jamguard_log.csv') and not os.path.exists(d + '/jamguard_local.csv')})
    out.sort(key=lambda r: r['name'])
    return out

def parse_slices(log):
    m = {}
    try:
        with open(log, errors='ignore') as f:
            for line in f:
                if line.startswith('SLICES') or line.startswith('SLICE: ue') or 'slice profile' in line.lower():
                    for a, b in re.findall(r'(\d+)\s*[:=]\s*s?(\d)\b', line):
                        m[int(a)] = int(b)
                if len(m) > 0 and line.startswith('[JGL]'): break
    except OSError:
        pass
    if not m:  # SLICES: military [2] ambulance [5] iot [9]
        try:
            with open(log, errors='ignore') as f:
                for line in f:
                    if line.startswith('SLICES:'):
                        for name, sl in (('military', 1), ('ambulance', 2), ('iot', 3)):
                            g = re.search(name + r' \[([\d,]*)\]', line)
                            if g:
                                for a in g.group(1).split(','):
                                    if a.strip().isdigit(): m[int(a)] = sl
                        break
        except OSError:
            pass
    return m or dict(DEF_SLICES)

def read_jammer(d):
    """position, power and ON intervals from jammer.txt (x,y,z,power_dbm,jammer_on,rng_run,start_s,stop_s[,period_ms,duty])"""
    j = {'x': 710.0, 'y': 510.0, 'power': None, 'on': [[4.0, 10.0]], 'period_ms': 0.0, 'duty': 0.5, 'file': False}
    try:
        rows = [r.strip().split(',') for r in open(d + '/jammer.txt') if r.strip()]
        h, v = rows[0], rows[1]
        J = dict(zip(h, v))
        j.update({'x': float(J.get('x', 710)), 'y': float(J.get('y', 510)), 'power': float(J.get('power_dbm', 'nan')),
                  'file': True, 'enabled': J.get('jammer_on', '1') == '1'})
        a, b = float(J.get('start_s', 4)), float(J.get('stop_s', 10))
        per, duty = float(J.get('period_ms', 0) or 0), float(J.get('duty', 0.5) or 0.5)
        j['period_ms'], j['duty'] = per, duty
        if per > 0 and 0 < duty < 1:
            T, on, iv, t = per / 1000.0, per / 1000.0 * duty, [], a
            while t < b - 1e-9 and len(iv) < 400:
                iv.append([round(t, 4), round(min(t + on, b), 4)]); t += T
            # very fast keying (shorter than a report) is drawn as one band
            j['on'] = iv if T >= 0.5 else [[a, b]]
            j['keyed_fast'] = T < 0.5
        else:
            j['on'] = [[a, b]]
    except (OSError, IndexError, ValueError):
        pass
    return j

def read_events(d):
    ev, mode = [], 'emulated'
    path, tcol = d + '/jamguard_local.csv', 0
    if not os.path.exists(path) and os.path.exists(d + '/jamguard_log.csv'):
        path, tcol, mode = d + '/jamguard_log.csv', 1, 'live'
    try:
        with open(path, errors='ignore') as f:
            next(f, None)
            for line in f:
                x = line.rstrip('\n').split(',', 14)
                if len(x) < 15: continue
                try:
                    t = float(x[tcol]) + (LIVE_OFFSET if mode == 'live' else 0.0)
                    ev.append({'t': round(t, 3), 'ev': x[2], 'imsi': int(x[3]), 'from': int(x[4]), 'to': int(x[5]),
                               'sinr': float(x[6]), 'drop': float(x[7]), 'x': float(x[8]), 'y': float(x[9]),
                               'est': int(x[10]), 'ex': float(x[11]), 'ey': float(x[12]), 'er': float(x[13]), 'note': x[14]})
                except ValueError:
                    continue
    except OSError:
        mode = None
    ev.sort(key=lambda e: e['t'])
    return ev, mode

def pctl(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * (len(v) - 1) + 0.5))] if v else None

def read_live_stats(d):
    s = {}
    try:
        rows = [l.strip().split(',') for l in open(d + '/e2_ctrl_rx.csv') if l.strip()]
        s['e2_controls'] = sum(1 for r in rows[1:] if r and r[0] == 'rx')
    except OSError:
        pass
    try:
        import csv
        with open(d + '/jg_latency.csv') as f:
            rd = list(csv.DictReader(f))
        dec = []
        for r in rd:
            if r.get('kind') == 'DECIDE':
                for k in ('decide_us', 'dt_us', 'us', 'decision_us'):
                    if k in r and r[k]:
                        try: dec.append(float(r[k]) / 1000.0)
                        except ValueError: pass
                        break
        s['decisions'] = sum(1 for r in rd if r.get('kind') == 'DECIDE')
        if dec: s['decide_ms_median'] = round(pctl(dec, .5), 3)
    except (OSError, KeyError):
        pass
    return s

def read_run(d):
    res = {'dir': d, 'name': os.path.relpath(d, HOME)}
    per = {}
    try:
        with open(d + '/ue_rx.txt') as f:
            for line in f:
                x = line.strip().split(',')
                if len(x) < 3: continue
                try:
                    t, im, b = float(x[0]), int(float(x[1])), float(x[2])
                    n = float(x[3]) if len(x) > 3 else 0.0
                    s = float(x[4]) if len(x) > 4 else 0.0
                except ValueError:
                    continue
                per.setdefault(im, []).append((t, b, n, s))
    except OSError:
        pass
    sl = parse_slices(d + '/log.txt')
    ues, tmax = {}, 0.0
    agg = {}
    for im, rows in per.items():
        rows.sort()
        ser = []
        for (t0, b0, n0, s0), (t1, b1, n1, s1) in zip(rows, rows[1:]):
            dt = t1 - t0
            if dt <= 0: continue
            mbps = (b1 - b0) * 8 / dt / 1e6
            dn = n1 - n0
            dly = (s1 - s0) / dn * 1000 if dn > 0 else None
            tt = round(t1, 3)
            ser.append([tt, round(mbps, 3), None if dly is None else round(dly, 2)])
            a = agg.setdefault(sl.get(im, 0), {}).setdefault(tt, [0.0, 0.0, 0.0, 0])
            a[0] += mbps; a[3] += 1
            if dn > 0: a[1] += (s1 - s0); a[2] += dn
            tmax = max(tmax, t1)
        ues[im] = {'slice': sl.get(im, 0), 'series': ser}
    slices = {}
    for s, tm in agg.items():
        slices[SLICE_NAMES[s] if s < 4 else str(s)] = [[t, round(v[0] / max(v[3], 1), 3), round(v[1] / v[2] * 1000, 2) if v[2] > 0 else None]
                                                       for t, v in sorted(tm.items())]
    res['ues'] = ues; res['slices'] = slices; res['tmax'] = tmax
    res['events'], res['mode'] = read_events(d)
    pos, cfg = {}, {}
    try:
        with open(d + '/log.txt', errors='ignore') as f:
            for line in f:
                m = re.match(r'\[JGL\] sanity UE (\d+) serving cell (\d+) raw \S+ -> (\S+) dB.*pos \(([-\d.]+),([-\d.]+)\)', line)
                if m:
                    pos[int(m.group(1))] = {'cell': int(m.group(2)), 'sinr': float(m.group(3)), 'x': float(m.group(4)), 'y': float(m.group(5))}
                elif line.startswith('[JGL] JamGuard-local ON'):
                    cfg['jg'] = line.strip()[6:]
                elif line.startswith('[JGL] canary='):
                    cfg['canary'] = line.strip()[6:]
                elif line.startswith('[JGL] anchor guard='):
                    cfg['anchor'] = line.strip()[6:]
    except OSError:
        pass
    if not pos:  # live runs: first position of every UE from ue_position.txt (timestamp,id,x,y,...)
        try:
            with open(d + '/ue_position.txt') as f:
                next(f, None)
                for line in f:
                    x = line.split(',')
                    if len(x) < 4: continue
                    im = int(x[1])
                    if im not in pos: pos[im] = {'cell': int(x[5]) if len(x) > 5 and x[5].isdigit() else 0, 'sinr': 0.0, 'x': float(x[2]), 'y': float(x[3])}
                    if len(pos) >= len(ues) > 0: break
        except (OSError, ValueError):
            pass
    res['pos'] = pos; res['cfg'] = cfg
    res['jammer'] = read_jammer(d)
    m = re.search(r'pw(\d+)_p(\d)_s(\d+)', d)
    res['power'] = int(m.group(1)) if m else (res['jammer']['power'] if res['jammer'].get('file') else None)
    res['policy'] = int(m.group(2)) if m else None
    res['seed'] = int(m.group(3)) if m else None
    if res['mode'] == 'live':
        m3 = re.search(r'_p(\d)\b', d)
        if m3: res['policy'] = int(m3.group(1))
    if res['policy'] is None:
        m2 = re.search(r'policy=(\d)', cfg.get('jg', ''))
        if m2: res['policy'] = int(m2.group(1))
    evn = {e['ev'] for e in res['events']}
    res['scenario'] = 'B (NR + LTE jammed)' if (re.search(r'jamx_LJ|liveB|/LJ/', d) or 'ANCHOR_BAD' in evn) else 'A (NR jammed)'
    if not res['jammer'].get('enabled', True): res['scenario'] = 'no jammer'
    res['policy_name'] = POLICIES.get(res['policy'], '–' if res['policy'] is None else 'p%d' % res['policy'])
    res['live'] = read_live_stats(d) if res['mode'] == 'live' else {}
    mt = run_mtime(d)
    res['age_s'] = round(time.time() - mt, 1)
    res['complete'] = os.path.exists(d + '/.done') or (tmax > 0 and res['age_s'] > 30)
    return res

def campaign(root, t0, t1):
    rep = HOME + '/campaign_report.py'
    if not os.path.exists(rep): return 'campaign_report.py not found in ~'
    r = subprocess.run(['python3', rep, root, t0, t1], capture_output=True, text=True, timeout=180)
    return r.stdout + r.stderr

PAGE = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JamGuard Dashboard</title><style>
:root{--bg:#0f1419;--panel:#171d24;--line:#2a333d;--fg:#e6e9ec;--mut:#8b96a3;--acc:#4ea1ff;--jam:rgba(255,80,80,.14);
--s0:#8b96a3;--s1:#ff9f43;--s2:#ff5c7a;--s3:#2ed3a0;--lte:#b38cff;--bad:#e5484d;--ok:#2ed3a0;--warn:#f5a524}
@media (prefers-color-scheme: light){:root{--bg:#f5f6f8;--panel:#fff;--line:#dde1e6;--fg:#1c232b;--mut:#5f6b78;--jam:rgba(255,60,60,.10)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,Segoe UI,sans-serif}
header{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line)}
h1{font-size:17px;margin:0 8px 0 0}select,input,button{background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:5px 8px;font:inherit}
select{max-width:320px}button{cursor:pointer}header input:not([type]){width:58px}#croot{width:130px!important}.tabs button.on{border-color:var(--acc);color:var(--acc)}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid var(--line)}
.b-live{background:rgba(229,72,77,.15);color:var(--bad);border-color:var(--bad)}.b-emu{color:var(--mut)}.b-run{background:rgba(46,211,160,.12);color:var(--ok);border-color:var(--ok)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--bad);margin-right:5px;animation:bl 1s infinite}@keyframes bl{50%{opacity:.25}}
main{padding:12px 16px;display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));align-items:start}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;min-width:0}
.card h2{font-size:12.5px;margin:0 0 6px;color:var(--mut);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
canvas{width:100%;display:block}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:8px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:6px 8px}.kpi b{display:block;font-size:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.kpi span{color:var(--mut);font-size:11.5px}
.kpi.bad{border-color:var(--bad)}.kpi.bad b{color:var(--bad)}.kpi.ok{border-color:var(--ok)}.kpi.ok b{color:var(--ok)}.kpi.warn{border-color:var(--warn)}.kpi.warn b{color:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:12.5px}td,th{padding:3px 6px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{position:sticky;top:0;background:var(--panel)}.scroll{max-height:300px;overflow:auto}
.legend{display:flex;flex-wrap:wrap;gap:4px 10px;font-size:12px;color:var(--mut);margin-top:4px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
pre{white-space:pre;overflow:auto;font-size:12px;margin:0}.wide{grid-column:1/-1}.mut{color:var(--mut)}
.ev-DETECT{color:#ff5c7a;font-weight:600}.ev-EVAC_LTE{color:#b38cff}.ev-HO_NR{color:#4ea1ff}.ev-PROBE_OK,.ev-RETURN{color:#2ed3a0}.ev-PROBE_FAIL,.ev-RECOVER_FAIL{color:#ff9f43}
.ev-ANCHOR_BAD{color:var(--bad);font-weight:700}.ev-ANCHOR_OK{color:var(--ok);font-weight:700}.ev-ANCHOR_RETRY{color:var(--warn);font-weight:600}
tr.hl td{background:rgba(229,72,77,.07)}
</style></head><body>
<header><h1>JamGuard · O-RAN jamming countermeasure</h1>
<span class="tabs"><button id="tRun" class="on">Run</button> <button id="tCamp">Campaign</button></span>
<span id="runCtl"><select id="run"></select>
<label class="mut"><input type="checkbox" id="follow"> follow newest running</label>
<label class="mut"><input type="checkbox" id="live" checked> auto-refresh</label>
<label class="mut" title="jammer ON intervals come from jammer.txt; edit to override">jammer <input id="j0" size="3">–<input id="j1" size="3"> s</label>
<label class="mut">x,y <input id="jx" size="4"> <input id="jy" size="4"></label></span>
<span id="campCtl" style="display:none"><input id="croot" size="14" value="jamx_LJ"> window <input id="c0" size="3" value="4">–<input id="c1" size="3" value="10"> s <button id="cgo">Load</button></span>
<span id="mode"></span><span id="stat" class="mut"></span></header>
<main id="runView">
 <div class="card wide"><div class="kpis" id="kpis"></div></div>
 <div class="card"><h2>Throughput per UE, mean by slice (Mb/s)</h2><canvas id="cThr" height="230"></canvas><div class="legend" id="lg1"></div></div>
 <div class="card"><h2>Packet delay by slice (ms)</h2><canvas id="cDly" height="230"></canvas><div class="legend" id="lg2"></div></div>
 <div class="card"><h2>Map: UEs, true jammer, JamGuard estimate</h2><canvas id="cMap" height="330"></canvas>
  <div class="legend"><span><i style="background:#ff5c7a"></i>true jammer</span><span><i style="background:#4ea1ff"></i>estimate + zone</span><span><i style="background:var(--lte)"></i>ring = on LTE</span><span id="locerr"></span></div>
  <input type="range" id="tsl" min="0" max="14" step="0.1" value="14" style="width:100%"><span class="mut" id="tslv"></span></div>
 <div class="card"><h2>UE connection lanes and LTE-anchor state</h2><canvas id="cLane" height="330"></canvas>
  <div class="legend"><span><i style="background:var(--lte)"></i>on LTE</span><span><i style="background:#4ea1ff"></i>on NR</span><span><i style="background:var(--bad)"></i>anchor jammed</span><span><i style="background:var(--ok)"></i>anchor verified</span><span><i style="background:var(--warn)"></i>anchor unverified (canary test)</span></div></div>
 <div class="card wide"><h2>JamGuard decisions <span class="mut" id="evn"></span></h2><div class="scroll"><table id="evt"></table></div></div>
</main>
<main id="campView" style="display:none"><div class="card wide"><h2>Campaign summary (mean ± std over seeds, complete runs only)</h2><pre id="camp">Press Load.</pre></div></main>
<script>
const SC={eMBB:'#8b96a3',military:'#ff9f43',ambulance:'#ff5c7a',IoT:'#2ed3a0'},SN=['eMBB','military','ambulance','IoT'];
const $=id=>document.getElementById(id);let R=null,timer=null,RUNS=[],ON=[[4,10]];
function css(v){return getComputedStyle(document.documentElement).getPropertyValue(v).trim()}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function prep(c){if(!c.dataset.h)c.dataset.h=c.getAttribute('height');const H=+c.dataset.h,d=devicePixelRatio||1;c.style.height=H+'px';const r=c.getBoundingClientRect();c.width=Math.round(r.width*d);c.height=Math.round(H*d);const g=c.getContext('2d');g.setTransform(d,0,0,d,0,0);return[g,r.width,H]}
function onIntervals(){const a=+$('j0').value,b=+$('j1').value;if(R&&R.jammer&&R.jammer.on&&+R.jammer.on[0][0]==a&&+R.jammer.on[R.jammer.on.length-1][1]==b)return R.jammer.on;return[[a,b]]}
function jamOn(t){return ON.some(([a,b])=>t>=a&&t<b)}
function shade(g,X,x0,x1,T,Hh){g.fillStyle=css('--jam');for(const[a,b]of ON){const A=Math.max(a,x0),B=Math.min(b,x1);if(B>A)g.fillRect(X(A),T,X(B)-X(A),Hh)}}
function axes(g,W,H,x0,x1,y0,y1){const L=44,B=22,T=8,Rr=10,f=css('--mut'),ln=css('--line');g.strokeStyle=ln;g.fillStyle=f;g.font='11px system-ui';
 const X=v=>L+(v-x0)/(x1-x0)*(W-L-Rr),Y=v=>H-B-(v-y0)/(y1-y0||1)*(H-B-T);
 for(let i=0;i<=4;i++){const v=y0+(y1-y0)*i/4,y=Y(v);g.beginPath();g.moveTo(L,y);g.lineTo(W-Rr,y);g.stroke();g.fillText(v.toFixed(v<10?1:0),4,y+4)}
 const st=x1>30?10:2;for(let t=Math.ceil(x0/st)*st;t<=x1;t+=st){const x=X(t);g.fillText(t+'s',x-6,H-6)}
 shade(g,X,x0,x1,T,H-B-T);return[X,Y]}
const MK={DETECT:['#ff5c7a',[4,3]],PROBE_OK:['#2ed3a0',[4,3]],CLEAR:['#2ed3a0',[2,3]],ANCHOR_BAD:['#e5484d',[]],ANCHOR_OK:['#2ed3a0',[]],ANCHOR_RETRY:['#f5a524',[2,2]]};
function marks(g,X,H){for(const e of R.events){const m=MK[e.ev];if(!m)continue;g.strokeStyle=m[0];g.lineWidth=e.ev.startsWith('ANCHOR')?2:1;g.setLineDash(m[1]);g.beginPath();g.moveTo(X(e.t),8);g.lineTo(X(e.t),H-22);g.stroke();g.setLineDash([]);g.lineWidth=1}}
function lineChart(id,lg,k,ymaxDef){const c=$(id),[g,W,H]=prep(c);const tm=Math.max(R.tmax,1);let ym=0;
 for(const s in R.slices)for(const p of R.slices[s])if(p[k]!=null&&p[0]>0.5)ym=Math.max(ym,p[k]);ym=Math.min(ym*1.1||ymaxDef,ymaxDef*20);
 const[X,Y]=axes(g,W,H,0,tm,0,ym);marks(g,X,H);let lgh='';
 for(const s of SN){const ser=R.slices[s];if(!ser)continue;g.strokeStyle=SC[s];g.lineWidth=1.6;g.beginPath();let st=false;
  for(const p of ser){if(p[k]==null||p[0]<0.3){st=false;continue}const x=X(p[0]),y=Y(Math.min(p[k],ym));st?g.lineTo(x,y):g.moveTo(x,y);st=true}g.stroke();lgh+=`<span><i style="background:${SC[s]}"></i>${s}</span>`}
 g.lineWidth=1;$(lg).innerHTML=lgh+'<span>shaded = jammer on · dashed red = DETECT · green = PROBE_OK / ANCHOR_OK · solid red = ANCHOR_BAD</span>'}
function uePos(t){const P={};for(const k in R.pos)P[k]={...R.pos[k]};for(const e of R.events){if(e.t>t)break;if(e.imsi>0&&e.x>=0){P[e.imsi]=P[e.imsi]||{};P[e.imsi].x=e.x;P[e.imsi].y=e.y}}return P}
function mapChart(){const c=$('cMap'),[g,W,H]=prep(c),t=+$('tsl').value;$('tslv').textContent='t = '+t.toFixed(1)+' s'+(jamOn(t)?'  ·  jammer ON':'');
 const P=uePos(t),jx=+$('jx').value,jy=+$('jy').value;let xs=[jx],ys=[jy];
 /* fixed frame for the whole run (all positions ever seen), so the map does not re-zoom on every refresh */
 for(const k in R.pos){xs.push(R.pos[k].x);ys.push(R.pos[k].y)}for(const e of R.events)if(e.x>=0&&e.y>=0){xs.push(e.x);ys.push(e.y)}for(const k in P)if(P[k].x!=null){xs.push(P[k].x);ys.push(P[k].y)}
 const x0=Math.min(...xs)-80,x1=Math.max(...xs)+80,y0=Math.min(...ys)-80,y1=Math.max(...ys)+80,s=Math.min((W-20)/(x1-x0),(H-20)/(y1-y0));
 const X=v=>10+(v-x0)*s,Y=v=>H-10-(v-y0)*s;g.strokeStyle=css('--line');g.strokeRect(1,1,W-2,H-2);
 let est=null;for(const e of R.events){if(e.t>t)break;if(e.ev=='LOCALIZE'||e.est)est=e.est?e:est;if(e.ev=='PROBE_OK'||e.ev=='CLEAR')est=null}
 const on=jamOn(t);
 if(on){g.fillStyle='rgba(255,92,122,.10)';g.beginPath();g.arc(X(jx),Y(jy),160*s,0,7);g.fill()}
 if(est&&est.er>0){g.strokeStyle='#4ea1ff';g.fillStyle='rgba(78,161,255,.08)';g.setLineDash([5,4]);g.beginPath();g.arc(X(est.ex),Y(est.ey),est.er*s,0,7);g.fill();g.stroke();g.setLineDash([]);
  g.fillStyle='#4ea1ff';g.fillRect(X(est.ex)-5,Y(est.ey)-5,10,10);$('locerr').textContent='localization error '+Math.hypot(est.ex-jx,est.ey-jy).toFixed(0)+' m, zone r='+est.er.toFixed(0)+' m'}else $('locerr').textContent='';
 g.fillStyle=on?'#ff5c7a':css('--mut');g.beginPath();g.moveTo(X(jx),Y(jy)-9);g.lineTo(X(jx)+8,Y(jy)+6);g.lineTo(X(jx)-8,Y(jy)+6);g.fill();g.font='11px system-ui';g.fillText('jammer'+(R.scenario.startsWith('B')?' (NR+LTE)':''),X(jx)+10,Y(jy)+4);
 const st=laneState(t);for(const k in P){if(P[k].x==null)continue;const u=R.ues[k],sl=u?SN[u.slice]||'eMBB':'eMBB';g.fillStyle=SC[sl];g.beginPath();g.arc(X(P[k].x),Y(P[k].y),6,0,7);g.fill();
  if(st[k]=='LTE'){g.strokeStyle=anchorAt(t)=='bad'?css('--bad'):css('--lte');g.lineWidth=2.5;g.stroke();g.lineWidth=1}g.fillStyle=css('--fg');g.fillText('UE'+k+(st[k]?' '+st[k]:''),X(P[k].x)+8,Y(P[k].y)-6)}}
function laneState(t){const s={};for(const k in R.pos)s[k]='c'+R.pos[k].cell;for(const e of R.events){if(e.t>t)break;if(e.imsi<=0)continue;
 if(e.ev=='EVAC_LTE'||e.ev=='PROBE_FAIL')s[e.imsi]='LTE';else if(['HO_NR','PROBE','RETURN'].includes(e.ev))s[e.imsi]='c'+e.to}return s}
/* LTE-anchor state over time: unverified while a canary test runs, bad after ANCHOR_BAD, ok after ANCHOR_OK */
function anchorSegs(){const seg=[];let cur=null,t0=0;const has=R.events.some(e=>e.ev.startsWith('ANCHOR')||/canary/.test(e.note));if(!has)return seg;
 for(const e of R.events){let nx=null;if(e.ev=='ANCHOR_BAD')nx='bad';else if(e.ev=='ANCHOR_OK')nx='ok';else if(e.ev=='ANCHOR_RETRY'||(e.ev=='EVAC_LTE'&&/canary/.test(e.note)))nx='test';else if(e.ev=='DETECT')nx='test';
  if(nx&&nx!=cur){if(cur)seg.push([t0,e.t,cur]);cur=nx;t0=e.t}}if(cur)seg.push([t0,Math.max(R.tmax,t0),cur]);return seg}
function anchorAt(t){let s=null;for(const[a,b,v]of anchorSegs())if(t>=a&&t<b)s=v;return s}
function laneChart(){const c=$('cLane'),[g,W,H]=prep(c),ids=Object.keys(R.ues).map(Number).sort((a,b)=>a-b),tm=Math.max(R.tmax,1);
 const L=74,Rr=10,T=20,B=22,lh=(H-T-B)/Math.max(ids.length,1),X=v=>L+v/tm*(W-L-Rr);g.font='11px system-ui';
 shade(g,X,0,tm,T,H-T-B);
 g.fillStyle=css('--mut');g.fillText('LTE anchor',4,13);const AC={bad:css('--bad'),ok:css('--ok'),test:css('--warn')};
 const segs=anchorSegs();if(!segs.length){g.fillText(R.scenario.startsWith('B')?'(no guard in this run)':'(healthy, not monitored)',X(0)+4,13)}
 for(const[a,b,v]of segs){g.fillStyle=AC[v];g.globalAlpha=.85;g.fillRect(X(a),4,Math.max(X(b)-X(a),2),11);g.globalAlpha=1}
 ids.forEach((im,i)=>{const y=T+i*lh,sl=SN[R.ues[im].slice]||'eMBB';g.fillStyle=SC[sl];g.fillText('UE'+im+' '+sl.slice(0,4),4,y+lh/2+4);
  let cur=R.pos[im]?'c'+R.pos[im].cell:'c?',t0=0;const sg=[];for(const e of R.events){if(e.imsi!=im)continue;let nx=null;
   if(e.ev=='EVAC_LTE'||e.ev=='PROBE_FAIL')nx='LTE';else if(['HO_NR','PROBE','RETURN'].includes(e.ev))nx='c'+e.to;if(nx){sg.push([t0,e.t,cur]);t0=e.t;cur=nx}}
  sg.push([t0,tm,cur]);for(const[a,b,s]of sg){g.fillStyle=s=='LTE'?css('--lte'):'#4ea1ff';g.globalAlpha=s=='LTE'?.85:.35;g.fillRect(X(a),y+1,Math.max(X(b)-X(a),1),Math.max(lh-2,1));g.globalAlpha=1;
   if(X(b)-X(a)>26&&lh>11){g.fillStyle=css('--fg');g.fillText(s,X(a)+3,y+lh/2+4)}}
  for(const e of R.events)if(e.imsi==im&&e.ev!='LOCALIZE'){g.fillStyle=e.ev=='EVAC_LTE'&&/canary/.test(e.note)?css('--warn'):css('--fg');g.fillRect(X(e.t)-1,y+1,2,Math.max(lh-2,1))}});
 g.fillStyle=css('--mut');const st=tm>30?10:2;for(let t=0;t<=tm;t+=st)g.fillText(t+'s',X(t)-6,H-6)}
function meanThr(s,a,b){const v=(R.slices[s]||[]).filter(p=>p[0]>a&&p[0]<=b);return v.length?v.reduce((x,p)=>x+p[1],0)/v.length:null}
function kpis(){const ev=R.events,j0=ON[0][0],j1=ON[ON.length-1][1];
 const dets=ev.filter(e=>e.ev=='DETECT'),inAtk=e=>ON.some(([a,b])=>e.t>=a-0.1&&e.t<=b+2);
 const d=dets.find(e=>e.t>=j0-0.1),fa=dets.filter(e=>!inAtk(e)).length;
 const act=ev.filter(e=>['EVAC_LTE','HO_NR','PROBE','RETURN','PROBE_FAIL'].includes(e.ev)).length;
 const pk=ev.find(e=>(e.ev=='PROBE_OK'||e.ev=='PASSIVE_OK')&&e.t>=j1),loc=ev.filter(e=>e.ev=='LOCALIZE'&&e.t>=j0&&e.t<j1).pop();
 const keep=s=>{const pre=meanThr(s,1,j0),dur=ON.map(([a,b])=>meanThr(s,a,b)).filter(v=>v!=null);if(pre==null||!dur.length||pre<=0)return'–';return(100*dur.reduce((x,v)=>x+v,0)/dur.length/pre).toFixed(0)+' %'};
 const an=anchorSegs(),last=an.length?an[an.length-1][2]:null,anTxt={bad:'jammed',ok:'verified',test:'testing'}[last]||(R.scenario.startsWith('B')?'not checked':'healthy');
 const k=[['run',R.name.split('/').slice(-2).join('/')],['scenario',R.scenario],['policy',R.policy_name],['jammer',(R.power!=null&&!isNaN(R.power)?R.power+' dBm':'–')+(ON.length>1?' · '+ON.length+' episodes':'')],
  ['detection',d?((d.t-j0)*1000).toFixed(0)+' ms':'–',d?'ok':''],['alarms / false',dets.length+' / '+fa,fa?'warn':''],['actions',act],
  ['localization err',loc?Math.hypot(loc.ex-$('jx').value,loc.ey-$('jy').value).toFixed(0)+' m':'–'],
  ['LTE anchor',anTxt,last=='bad'?'bad':last=='ok'?'ok':last=='test'?'warn':''],
  ['military thr kept',keep('military')],['ambulance thr kept',keep('ambulance')],['IoT thr kept',keep('IoT')],
  ['jammer gone seen',pk?(pk.t-j1).toFixed(1)+' s after':'–']];
 if(R.mode=='live'){k.push(['E2 controls',R.live.e2_controls??'–']);if(R.live.decide_ms_median!=null)k.push(['decision (median)',R.live.decide_ms_median+' ms'])}
 k.push(['status',R.complete?'complete':'running',R.complete?'':'ok']);
 $('kpis').innerHTML=k.map(([a,b,c])=>`<div class="kpi ${c||''}"><span>${esc(a)}</span><b title="${esc(b)}">${esc(b)}</b></div>`).join('')}
function table(){const rows=R.events.filter(e=>e.ev!='LOCALIZE');$('evn').textContent='('+rows.length+' events)';
 $('evt').innerHTML='<tr><th>t (s)</th><th>event</th><th>UE</th><th>slice</th><th>from→to</th><th>SINR</th><th>drop</th><th>note</th></tr>'+
 rows.map(e=>{const sl=e.imsi&&R.ues[e.imsi]?SN[R.ues[e.imsi].slice]:'';return`<tr class="${e.ev.startsWith('ANCHOR')?'hl':''}"><td>${e.t.toFixed(2)}</td><td class="ev-${e.ev}">${e.ev}</td><td>${e.imsi||''}</td><td style="color:${SC[sl]||''}">${sl}</td><td>${e.imsi?e.from+'→'+e.to:''}</td><td>${e.imsi?e.sinr.toFixed(1):''}</td><td>${e.imsi?e.drop.toFixed(1):''}</td><td class="mut">${esc(e.note)}</td></tr>`}).join('')}
function draw(){if(!R)return;ON=onIntervals();$('tsl').max=Math.max(R.tmax,1).toFixed(1);kpis();lineChart('cThr','lg1',1,6);lineChart('cDly','lg2',2,60);mapChart();laneChart();table();
 $('mode').innerHTML=(R.mode=='live'?'<span class="badge b-live">LIVE E2 · FlexRIC</span>':'<span class="badge b-emu">emulated loop</span>')+' '+(R.complete?'':'<span class="badge b-run"><span class="dot"></span>running</span>')}
async function loadRuns(){RUNS=await (await fetch('api/runs')).json();const s=$('run'),cur=s.value;
 const opt=x=>`<option value="${esc(x.dir)}">${x.running?'● ':''}${esc(x.name)}${x.live?'  [live]':''}</option>`;
 const run=RUNS.filter(x=>x.running),live=RUNS.filter(x=>x.live&&!x.running),rest=RUNS.filter(x=>!x.running&&!x.live);
 s.innerHTML=(run.length?`<optgroup label="running now">${run.map(opt).join('')}</optgroup>`:'')+(live.length?`<optgroup label="live E2 runs">${live.map(opt).join('')}</optgroup>`:'')+`<optgroup label="emulated runs">${rest.map(opt).join('')}</optgroup>`;
 if($('follow').checked&&run.length){const nw=run.slice().sort((a,b)=>b.mtime-a.mtime)[0];if(nw.dir!=cur){s.value=nw.dir;setJam=true;return loadRun()}}
 if(cur&&RUNS.some(x=>x.dir==cur))s.value=cur;else{const pick=RUNS.filter(x=>/jamx_LJ\/pw50_p9_s1|liveB_p9/.test(x.name)).pop()||RUNS.filter(x=>/expB2\/p2|expB\/p2/.test(x.name)).pop();if(pick)s.value=pick.dir}}
let setJam=true;
async function loadRun(){const d=$('run').value;if(!d)return;$('stat').textContent='loading…';R=await (await fetch('api/run?d='+encodeURIComponent(d))).json();
 if(setJam&&R.jammer){const on=R.jammer.on;$('j0').value=on[0][0];$('j1').value=on[on.length-1][1];$('jx').value=R.jammer.x;$('jy').value=R.jammer.y;setJam=false}
 const atEnd=+$('tsl').value>=+$('tsl').max-0.05;$('tsl').max=Math.max(R.tmax,1).toFixed(1);if(atEnd||!R.complete)$('tsl').value=R.tmax;$('stat').textContent=(R.complete?'complete':'updated '+R.age_s+' s ago')+' · t='+R.tmax.toFixed(1)+' s';draw()}
function live(){clearInterval(timer);if($('live').checked)timer=setInterval(()=>{if(R&&!R.complete)loadRun()},2000)}
$('run').onchange=()=>{$('tsl').value=999;setJam=true;loadRun()};['j0','j1','jx','jy'].forEach(i=>$(i).oninput=draw);$('tsl').oninput=()=>{mapChart()};$('live').onchange=live;
$('follow').onchange=()=>loadRuns();
$('tRun').onclick=()=>{$('tRun').classList.add('on');$('tCamp').classList.remove('on');$('runView').style.display='';$('campView').style.display='none';$('runCtl').style.display='';$('campCtl').style.display='none'};
$('tCamp').onclick=()=>{$('tCamp').classList.add('on');$('tRun').classList.remove('on');$('runView').style.display='none';$('campView').style.display='';$('runCtl').style.display='none';$('campCtl').style.display=''};
$('cgo').onclick=async()=>{$('camp').textContent='running campaign_report.py …';$('camp').textContent=await (await fetch(`api/campaign?root=${encodeURIComponent($('croot').value)}&t0=${$('c0').value}&t1=${$('c1').value}`)).text()};
addEventListener('resize',draw);loadRuns().then(loadRun);live();setInterval(loadRuns,10000);
</script></body></html>'''

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, body, ctype='application/json'):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(200); self.send_header('Content-Type', ctype + '; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ('/', '/index.html'): return self.send(PAGE, 'text/html')
            if u.path == '/api/runs': return self.send(json.dumps(list_runs()))
            if u.path == '/api/run':
                d = safe(q.get('d', [''])[0])
                if not d: return self.send('{}')
                return self.send(json.dumps(read_run(d)))
            if u.path == '/api/campaign':
                root = safe(os.path.join(HOME, q.get('root', ['jamx_LJ'])[0]))
                if not root: return self.send('bad path', 'text/plain')
                return self.send(campaign(root, q.get('t0', ['4'])[0], q.get('t1', ['10'])[0]), 'text/plain')
            self.send_response(404); self.end_headers()
        except Exception as e:
            self.send('error: %s' % e, 'text/plain')

if __name__ == '__main__':
    print('JamGuard dashboard: http://localhost:%d   (bind %s, Ctrl+C to stop)' % (PORT, BIND))
    http.server.ThreadingHTTPServer((BIND, PORT), H).serve_forever()
