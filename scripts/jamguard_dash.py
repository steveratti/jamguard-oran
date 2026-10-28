#!/usr/bin/env python3
"""JamGuard dashboard (local, no extra packages).
   python3 ~/jamguard_dash.py            -> open http://localhost:8050 in the browser
   Reads run folders under ~ that contain ue_rx.txt (jamx_C/*, jamx_expB*/*, ...).
   Live: the page refreshes the selected run every few seconds while it is still running."""
import http.server, json, os, re, glob, subprocess, sys, urllib.parse

HOME = os.path.expanduser('~')
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8050
DEF_SLICES = {2: 1, 5: 2, 9: 3}          # IMSI -> slice (military 1, ambulance 2, IoT 3); others eMBB
SLICE_NAMES = ['eMBB', 'military', 'ambulance', 'IoT']

def safe(p):
    p = os.path.realpath(os.path.expanduser(p))
    return p if p.startswith(HOME) else None

def list_runs():
    out = []
    for f in glob.glob(HOME + '/jamx*/**/ue_rx.txt', recursive=True):
        d = os.path.dirname(f)
        out.append({'dir': d, 'name': os.path.relpath(d, HOME), 'mtime': os.path.getmtime(f)})
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
    return m or dict(DEF_SLICES)

def read_run(d):
    res = {'dir': d, 'name': os.path.relpath(d, HOME)}
    # throughput / delay per UE from ue_rx.txt: t_s,imsi,rx_bytes,dly_pkts,dly_sum_s (cumulative)
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
    agg = {}  # slice -> t -> [mbps_sum, dly_sum, dly_n]
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
    # JamGuard events
    ev = []
    try:
        with open(d + '/jamguard_local.csv', errors='ignore') as f:
            next(f, None)
            for line in f:
                x = line.rstrip('\n').split(',', 14)
                if len(x) < 15: continue
                try:
                    ev.append({'t': float(x[0]), 'ev': x[2], 'imsi': int(x[3]), 'from': int(x[4]), 'to': int(x[5]),
                               'sinr': float(x[6]), 'drop': float(x[7]), 'x': float(x[8]), 'y': float(x[9]),
                               'est': int(x[10]), 'ex': float(x[11]), 'ey': float(x[12]), 'er': float(x[13]), 'note': x[14]})
                except ValueError:
                    continue
    except OSError:
        pass
    res['events'] = ev
    # initial UE positions / cells and run parameters from log.txt
    pos, cfg = {}, {}
    try:
        with open(d + '/log.txt', errors='ignore') as f:
            for line in f:
                m = re.match(r'\[JGL\] sanity UE (\d+) serving cell (\d+) raw \S+ -> (\S+) dB.*pos \(([-\d.]+),([-\d.]+)\)', line)
                if m:
                    pos[int(m.group(1))] = {'cell': int(m.group(2)), 'sinr': float(m.group(3)), 'x': float(m.group(4)), 'y': float(m.group(5))}
                elif line.startswith('[JGL] JamGuard-local ON'):
                    cfg['jg'] = line.strip()[6:]
    except OSError:
        pass
    res['pos'] = pos; res['cfg'] = cfg
    # run options from the folder name / campaign layout
    m = re.search(r'pw(\d+)_p(\d)_s(\d+)', d)
    res['power'] = int(m.group(1)) if m else None
    res['policy'] = int(m.group(2)) if m else None
    res['seed'] = int(m.group(3)) if m else None
    if res['policy'] is None:
        m2 = re.search(r'policy=(\d)', cfg.get('jg', ''))
        if m2: res['policy'] = int(m2.group(1))
    res['complete'] = tmax >= 13.5
    return res

def campaign(root, t0, t1):
    rep = HOME + '/campaign_report.py'
    if not os.path.exists(rep): return 'campaign_report.py not found in ~'
    r = subprocess.run(['python3', rep, root, t0, t1], capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr

PAGE = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JamGuard Dashboard</title><style>
:root{--bg:#0f1419;--panel:#171d24;--line:#2a333d;--fg:#e6e9ec;--mut:#8b96a3;--acc:#4ea1ff;--jam:rgba(255,80,80,.13);
--s0:#8b96a3;--s1:#ff9f43;--s2:#ff5c7a;--s3:#2ed3a0;--lte:#b38cff}
@media (prefers-color-scheme: light){:root{--bg:#f5f6f8;--panel:#fff;--line:#dde1e6;--fg:#1c232b;--mut:#5f6b78;--jam:rgba(255,60,60,.10)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,Segoe UI,sans-serif}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line)}
h1{font-size:17px;margin:0 12px 0 0}select,input,button{background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:5px 8px;font:inherit}
button{cursor:pointer}header input:not([type]){width:58px}#croot{width:110px!important}.tabs button.on{border-color:var(--acc);color:var(--acc)}
main{padding:14px 16px;display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;min-width:0}
.card h2{font-size:13px;margin:0 0 8px;color:var(--mut);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
canvas{width:100%;display:block}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:8px}.kpi b{display:block;font-size:20px}.kpi span{color:var(--mut);font-size:12px}
table{width:100%;border-collapse:collapse;font-size:12.5px}td,th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
.scroll{max-height:340px;overflow:auto}.legend{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--mut);margin-top:6px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
pre{white-space:pre;overflow:auto;font-size:12px;margin:0}.wide{grid-column:1/-1}.mut{color:var(--mut)}
.ev-DETECT{color:#ff5c7a}.ev-EVAC_LTE{color:#b38cff}.ev-HO_NR{color:#4ea1ff}.ev-PROBE_OK,.ev-RETURN{color:#2ed3a0}.ev-PROBE_FAIL{color:#ff9f43}
</style></head><body>
<header><h1>JamGuard · O-RAN jamming countermeasure</h1>
<span class="tabs"><button id="tRun" class="on">Run</button> <button id="tCamp">Campaign</button></span>
<span id="runCtl"><select id="run"></select> <label class="mut">jammer <input id="j0" size="3" value="4">–<input id="j1" size="3" value="10"> s</label>
<label class="mut">true jammer x,y <input id="jx" size="4" value="710"> <input id="jy" size="4" value="510"></label>
<label class="mut"><input type="checkbox" id="live" checked> live</label></span>
<span id="campCtl" style="display:none"><input id="croot" size="14" value="jamx_C"> window <input id="c0" size="3" value="4">–<input id="c1" size="3" value="10"> s <button id="cgo">Load</button></span>
<span id="stat" class="mut"></span></header>
<main id="runView">
 <div class="card wide"><div class="kpis" id="kpis"></div></div>
 <div class="card"><h2>Throughput per UE, mean by slice (Mb/s)</h2><canvas id="cThr" height="260"></canvas><div class="legend" id="lg1"></div></div>
 <div class="card"><h2>Packet delay by slice (ms)</h2><canvas id="cDly" height="260"></canvas><div class="legend" id="lg2"></div></div>
 <div class="card"><h2>Map: UEs, true jammer, JamGuard estimate</h2><canvas id="cMap" height="360"></canvas>
  <div class="legend"><span><i style="background:#ff5c7a"></i>true jammer</span><span><i style="background:#4ea1ff"></i>estimate + zone</span><span>UE colour = slice</span><span id="locerr"></span></div>
  <input type="range" id="tsl" min="0" max="14" step="0.1" value="14" style="width:100%"><span class="mut" id="tslv"></span></div>
 <div class="card"><h2>UE connection lanes (NR cell / LTE anchor)</h2><canvas id="cLane" height="360"></canvas>
  <div class="legend"><span><i style="background:var(--lte)"></i>on LTE (evacuated)</span><span><i style="background:#4ea1ff"></i>on NR</span><span>| markers = JamGuard actions</span></div></div>
 <div class="card wide"><h2>JamGuard decisions</h2><div class="scroll"><table id="evt"></table></div></div>
</main>
<main id="campView" style="display:none"><div class="card wide"><h2>Campaign summary (mean ± std over seeds, complete runs only)</h2><pre id="camp">Press Load.</pre></div></main>
<script>
const SC={eMBB:'#8b96a3',military:'#ff9f43',ambulance:'#ff5c7a',IoT:'#2ed3a0'},SN=['eMBB','military','ambulance','IoT'];
const $=id=>document.getElementById(id);let R=null,timer=null;
function css(v){return getComputedStyle(document.documentElement).getPropertyValue(v).trim()}
function prep(c){const r=c.getBoundingClientRect(),d=devicePixelRatio||1;c.width=r.width*d;c.height=c.getAttribute('height')*d;const g=c.getContext('2d');g.scale(d,d);return[g,r.width,+c.getAttribute('height')]}
function axes(g,W,H,x0,x1,y0,y1,yl){const L=46,B=24,T=8,Rr=10,f=css('--mut'),ln=css('--line');g.strokeStyle=ln;g.fillStyle=f;g.font='11px system-ui';
 const X=v=>L+(v-x0)/(x1-x0)*(W-L-Rr),Y=v=>H-B-(v-y0)/(y1-y0||1)*(H-B-T);
 for(let i=0;i<=4;i++){const v=y0+(y1-y0)*i/4,y=Y(v);g.beginPath();g.moveTo(L,y);g.lineTo(W-Rr,y);g.stroke();g.fillText(v.toFixed(v<10?1:0),4,y+4)}
 for(let t=Math.ceil(x0);t<=x1;t+=2){const x=X(t);g.fillText(t+'s',x-6,H-6)}
 const j0=+$('j0').value,j1=+$('j1').value;g.fillStyle=css('--jam');g.fillRect(X(Math.max(j0,x0)),T,X(Math.min(j1,x1))-X(Math.max(j0,x0)),H-B-T);return[X,Y]}
function marks(g,X,H){for(const e of R.events){if(!['DETECT','PROBE_OK','CLEAR'].includes(e.ev))continue;g.strokeStyle=e.ev=='DETECT'?'#ff5c7a':'#2ed3a0';g.setLineDash([4,3]);g.beginPath();g.moveTo(X(e.t),8);g.lineTo(X(e.t),H-24);g.stroke();g.setLineDash([])}}
function lineChart(id,lg,k,ymaxDef){const c=$(id),[g,W,H]=prep(c);const tm=Math.max(R.tmax,1);let ym=0;
 for(const s in R.slices)for(const p of R.slices[s])if(p[k]!=null&&p[0]>0.5)ym=Math.max(ym,p[k]);ym=Math.min(ym*1.1||ymaxDef,ymaxDef*20);
 const[X,Y]=axes(g,W,H,0,tm,0,ym);marks(g,X,H);let lgh='';
 for(const s of SN){const ser=R.slices[s];if(!ser)continue;g.strokeStyle=SC[s];g.lineWidth=1.6;g.beginPath();let st=false;
  for(const p of ser){if(p[k]==null||p[0]<0.3){st=false;continue}const x=X(p[0]),y=Y(Math.min(p[k],ym));st?g.lineTo(x,y):g.moveTo(x,y);st=true}g.stroke();lgh+=`<span><i style="background:${SC[s]}"></i>${s}</span>`}
 g.lineWidth=1;$(lg).innerHTML=lgh+'<span>shaded = jammer on · dashed = DETECT / PROBE_OK</span>'}
function uePos(t){const P={};for(const k in R.pos)P[k]={...R.pos[k]};for(const e of R.events){if(e.t>t)break;if(e.imsi>0&&e.x>=0){P[e.imsi]=P[e.imsi]||{};P[e.imsi].x=e.x;P[e.imsi].y=e.y}}return P}
function mapChart(){const c=$('cMap'),[g,W,H]=prep(c),t=+$('tsl').value;$('tslv').textContent='t = '+t.toFixed(1)+' s';
 const P=uePos(t),jx=+$('jx').value,jy=+$('jy').value;let xs=[jx],ys=[jy];for(const k in P){xs.push(P[k].x);ys.push(P[k].y)}
 const x0=Math.min(...xs)-80,x1=Math.max(...xs)+80,y0=Math.min(...ys)-80,y1=Math.max(...ys)+80,s=Math.min((W-20)/(x1-x0),(H-20)/(y1-y0));
 const X=v=>10+(v-x0)*s,Y=v=>H-10-(v-y0)*s;g.strokeStyle=css('--line');g.strokeRect(1,1,W-2,H-2);
 let est=null;for(const e of R.events){if(e.t>t)break;if(e.ev=='LOCALIZE'||e.est)est=e.est?e:est;if(e.ev=='PROBE_OK'||e.ev=='CLEAR')est=null}
 const on=t>=+$('j0').value&&t<+$('j1').value;
 if(on){g.fillStyle='rgba(255,92,122,.10)';g.beginPath();g.arc(X(jx),Y(jy),160*s,0,7);g.fill()}
 if(est){g.strokeStyle='#4ea1ff';g.fillStyle='rgba(78,161,255,.08)';g.setLineDash([5,4]);g.beginPath();g.arc(X(est.ex),Y(est.ey),est.er*s,0,7);g.fill();g.stroke();g.setLineDash([]);
  g.fillStyle='#4ea1ff';g.fillRect(X(est.ex)-5,Y(est.ey)-5,10,10);$('locerr').textContent='localization error '+Math.hypot(est.ex-jx,est.ey-jy).toFixed(0)+' m, zone r='+est.er.toFixed(0)+' m'}else $('locerr').textContent='';
 g.fillStyle=on?'#ff5c7a':css('--mut');g.beginPath();g.moveTo(X(jx),Y(jy)-9);g.lineTo(X(jx)+8,Y(jy)+6);g.lineTo(X(jx)-8,Y(jy)+6);g.fill();g.font='11px system-ui';g.fillText('jammer',X(jx)+10,Y(jy)+4);
 const st=laneState(t);for(const k in P){const u=R.ues[k],sl=u?SN[u.slice]||'eMBB':'eMBB';g.fillStyle=SC[sl];g.beginPath();g.arc(X(P[k].x),Y(P[k].y),6,0,7);g.fill();
  if(st[k]=='LTE'){g.strokeStyle=css('--lte');g.lineWidth=2.5;g.stroke();g.lineWidth=1}g.fillStyle=css('--fg');g.fillText('UE'+k+(st[k]?' '+st[k]:''),X(P[k].x)+8,Y(P[k].y)-6)}}
function laneState(t){const s={};for(const k in R.pos)s[k]='c'+R.pos[k].cell;for(const e of R.events){if(e.t>t)break;if(e.imsi<=0)continue;
 if(e.ev=='EVAC_LTE'||e.ev=='PROBE_FAIL')s[e.imsi]='LTE';else if(['HO_NR','PROBE','RETURN'].includes(e.ev))s[e.imsi]='c'+e.to}return s}
function laneChart(){const c=$('cLane'),[g,W,H]=prep(c),ids=Object.keys(R.ues).map(Number).sort((a,b)=>a-b),tm=Math.max(R.tmax,1);
 const L=70,Rr=10,T=6,B=22,lh=(H-T-B)/Math.max(ids.length,1),X=v=>L+v/tm*(W-L-Rr);g.font='11px system-ui';
 const j0=+$('j0').value,j1=+$('j1').value;g.fillStyle=css('--jam');g.fillRect(X(j0),T,X(Math.min(j1,tm))-X(j0),H-T-B);
 ids.forEach((im,i)=>{const y=T+i*lh,sl=SN[R.ues[im].slice]||'eMBB';g.fillStyle=SC[sl];g.fillText('UE'+im+' '+sl.slice(0,4),4,y+lh/2+4);
  let cur=R.pos[im]?'c'+R.pos[im].cell:'c?',t0=0;const segs=[];for(const e of R.events){if(e.imsi!=im)continue;let nx=null;
   if(e.ev=='EVAC_LTE'||e.ev=='PROBE_FAIL')nx='LTE';else if(['HO_NR','PROBE','RETURN'].includes(e.ev))nx='c'+e.to;if(nx){segs.push([t0,e.t,cur]);t0=e.t;cur=nx}}
  segs.push([t0,tm,cur]);for(const[a,b,s]of segs){g.fillStyle=s=='LTE'?css('--lte'):'#4ea1ff';g.globalAlpha=s=='LTE'?.85:.35;g.fillRect(X(a),y+2,Math.max(X(b)-X(a),1),lh-4);g.globalAlpha=1;
   if(X(b)-X(a)>26){g.fillStyle=css('--fg');g.fillText(s,X(a)+3,y+lh/2+4)}}
  for(const e of R.events)if(e.imsi==im&&e.ev!='LOCALIZE'){g.fillStyle='#fff';g.fillRect(X(e.t)-1,y+1,2,lh-2)}});
 g.fillStyle=css('--mut');for(let t=0;t<=tm;t+=2)g.fillText(t+'s',X(t)-6,H-6)}
function kpis(){const j0=+$('j0').value,j1=+$('j1').value,ev=R.events;const d=ev.find(e=>e.ev=='DETECT'&&e.t>=j0);
 const fa=ev.filter(e=>e.ev=='DETECT'&&(e.t<j0||e.t>j1+0.5)).length,act=ev.filter(e=>['EVAC_LTE','HO_NR','PROBE','RETURN','PROBE_FAIL'].includes(e.ev)).length;
 const pk=ev.find(e=>e.ev=='PROBE_OK'&&e.t>=j1),loc=ev.filter(e=>e.ev=='LOCALIZE'&&e.t>=j0&&e.t<j1).pop();
 const win=(s)=>{const v=(R.slices[s]||[]).filter(p=>p[0]>j0&&p[0]<=j1&&p[2]!=null);return v.length?(v.reduce((a,p)=>a+p[2],0)/v.length).toFixed(1)+' ms':'–'};
 const pol=R.policy==null?'':['p0 monitor','p1 reactive','p2 localization'][R.policy]||('p'+R.policy);
 const k=[['run',R.name.split('/').pop()],['policy',pol||'–'],['jammer power',R.power!=null?R.power+' dBm':'–'],['seed',R.seed??'–'],
  ['detection',d?((d.t-j0)*1000).toFixed(0)+' ms':'–'],['false alarms',fa],['actions',act],['localization err',loc?Math.hypot(loc.ex-$('jx').value,loc.ey-$('jy').value).toFixed(0)+' m':'–'],
  ['jammer gone seen',pk?(pk.t-j1).toFixed(1)+' s after':'–'],['military delay (jam)',win('military')],['ambulance delay (jam)',win('ambulance')],['status',R.complete?'complete':'running / partial']];
 $('kpis').innerHTML=k.map(([a,b])=>`<div class="kpi"><span>${a}</span><b>${b}</b></div>`).join('')}
function table(){$('evt').innerHTML='<tr><th>t (s)</th><th>event</th><th>UE</th><th>from→to</th><th>SINR</th><th>drop</th><th>note</th></tr>'+
 R.events.filter(e=>e.ev!='LOCALIZE'||true).map(e=>`<tr><td>${e.t.toFixed(2)}</td><td class="ev-${e.ev}">${e.ev}</td><td>${e.imsi||''}</td><td>${e.imsi?e.from+'→'+e.to:''}</td><td>${e.imsi?e.sinr.toFixed(1):''}</td><td>${e.imsi?e.drop.toFixed(1):''}</td><td class="mut">${e.note}</td></tr>`).join('')}
function draw(){if(!R)return;$('tsl').max=Math.max(R.tmax,1).toFixed(1);kpis();lineChart('cThr','lg1',1,6);lineChart('cDly','lg2',2,60);mapChart();laneChart();table()}
async function loadRuns(){const r=await (await fetch('api/runs')).json(),s=$('run'),cur=s.value;s.innerHTML=r.map(x=>`<option value="${x.dir}">${x.name}</option>`).join('');
 if(cur&&r.some(x=>x.dir==cur))s.value=cur;else{const lastB=r.filter(x=>/expB2\/p2|expB\/p2/.test(x.name)).pop();if(lastB)s.value=lastB.dir}}
async function loadRun(){const d=$('run').value;if(!d)return;$('stat').textContent='loading…';R=await (await fetch('api/run?d='+encodeURIComponent(d))).json();
 if(+$('tsl').value>=+$('tsl').max-0.05||!R.complete)$('tsl').value=R.tmax;$('stat').textContent=(R.complete?'complete':'running')+' · t='+R.tmax.toFixed(1)+' s';draw()}
function live(){clearInterval(timer);if($('live').checked)timer=setInterval(()=>{if(R&&!R.complete)loadRun()},5000)}
$('run').onchange=()=>{$('tsl').value=99;loadRun()};['j0','j1','jx','jy'].forEach(i=>$(i).oninput=draw);$('tsl').oninput=()=>{mapChart()};$('live').onchange=live;
$('tRun').onclick=()=>{$('tRun').classList.add('on');$('tCamp').classList.remove('on');$('runView').style.display='';$('campView').style.display='none';$('runCtl').style.display='';$('campCtl').style.display='none'};
$('tCamp').onclick=()=>{$('tCamp').classList.add('on');$('tRun').classList.remove('on');$('runView').style.display='none';$('campView').style.display='';$('runCtl').style.display='none';$('campCtl').style.display=''};
$('cgo').onclick=async()=>{$('camp').textContent='running campaign_report.py …';$('camp').textContent=await (await fetch(`api/campaign?root=${encodeURIComponent($('croot').value)}&t0=${$('c0').value}&t1=${$('c1').value}`)).text()};
addEventListener('resize',draw);loadRuns().then(loadRun);live();setInterval(loadRuns,30000);
</script></body></html>'''

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, body, ctype='application/json'):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(200); self.send_header('Content-Type', ctype + '; charset=utf-8')
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
                root = safe(os.path.join(HOME, q.get('root', ['jamx_C'])[0]))
                if not root: return self.send('bad path', 'text/plain')
                return self.send(campaign(root, q.get('t0', ['4'])[0], q.get('t1', ['10'])[0]), 'text/plain')
            self.send_response(404); self.end_headers()
        except Exception as e:
            self.send('error: %s' % e, 'text/plain')

if __name__ == '__main__':
    print('JamGuard dashboard: http://localhost:%d   (Ctrl+C to stop)' % PORT)
    http.server.ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
