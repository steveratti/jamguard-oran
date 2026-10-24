# usage: python3 ~/slice_report.py <run_dir> [t_start] [t_end] [eMBB_cbr_Mbps]
# per-slice delivered throughput, one-way delay (app level) and delivered share of the offered rate
import sys, re, pandas as pd
R=sys.argv[1]; t0=float(sys.argv[2]) if len(sys.argv)>2 else 0.0
t1=float(sys.argv[3]) if len(sys.argv)>3 else 1e9; cbr=float(sys.argv[4]) if len(sys.argv)>4 else 5.0
log=open(f"{R}/log.txt",errors="ignore").read(); sl={}
m=re.search(r"SLICES: military \[([^\]]*)\] ambulance \[([^\]]*)\] iot \[([^\]]*)\]",log)
if m:
    for k,grp in zip((1,2,3),m.groups()):
        for x in re.split(r"[^0-9]+",grp):
            if x: sl[int(x)]=k
d=pd.read_csv(f"{R}/ue_rx.txt").sort_values(["imsi","t_s"])
_rst=0  # SRFIX: cumulative counters restart at 0 when a UE data path is moved
for c in ("rx_bytes","dly_pkts","dly_sum_s"):
    _v=d.groupby("imsi")[c].diff()
    _rst+=int((_v<0).sum())
    d["d_"+c]=_v.where(_v>=0, d[c])
_bad=sorted(set(d.loc[d.dly_sum_s<0,"imsi"]))   # SRFIX2: counter poisoned by a corrupt timestamp
if _bad: d.loc[d.imsi.isin(_bad),["d_dly_pkts","d_dly_sum_s"]]=float("nan")
_rej=int(d["dly_bad"].max()) if "dly_bad" in d.columns else 0
w=d[(d.t_s>t0)&(d.t_s<=t1)]
g=w.groupby("imsi").agg(b=("d_rx_bytes","sum"),n=("d_dly_pkts","sum"),s=("d_dly_sum_s","sum"),k=("t_s","size"))
g["slice"]=[sl.get(i,0) for i in g.index]; g["Mbps"]=g.b*8/1e6/(g.k*0.1)
off={0:cbr,1:0.564,2:3.1,3:0.08}; g["deliv"]=g.Mbps/g.slice.map(off)*100
r=g.groupby("slice").agg(ues=("Mbps","size"),Mbps_per_UE=("Mbps","mean"),n=("n","sum"),s=("s","sum"),deliv_pct=("deliv","mean"))
r["delay_ms"]=r.s/r.n.clip(lower=1)*1000
r.index=[{0:"eMBB",1:"military",2:"ambulance",3:"IoT"}.get(i,i) for i in r.index]
print(f"{R}  window ({t0},{t1}] s" + (f"  [{_rst} counter resets absorbed]" if _rst else "") + (f"  [UEs {_bad} excluded from the delay: corrupt timestamp]" if _bad else "") + (f"  [{_rej} samples rejected by the simulator]" if _rej else ""))
print(r[["ues","Mbps_per_UE","deliv_pct","delay_ms"]].round(2).to_string())
