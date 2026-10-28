# usage: python3 ~/slice_report.py <run_dir> [t_start] [t_end] [eMBB_cbr_Mbps]
# per-slice delivered throughput, one-way delay (app level) and delivered share of the offered rate
import sys, re
from pathlib import Path
import pandas as pd


def parse_slice_map(log_text):
    sl = {}
    m = re.search(r"SLICES: military \[([^\]]*)\] ambulance \[([^\]]*)\] iot \[([^\]]*)\]", log_text)
    if not m:
        return sl
    for k, grp in zip((1, 2, 3), m.groups()):
        for x in re.split(r"[^0-9]+", grp):
            if x:
                sl[int(x)] = k
    return sl


def main():
    if len(sys.argv) < 2:
        print("usage: python3 ~/slice_report.py <run_dir> [t_start] [t_end] [eMBB_cbr_Mbps]", file=sys.stderr)
        return 2

    R = sys.argv[1]
    t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    t1 = float(sys.argv[3]) if len(sys.argv) > 3 else 1e9
    cbr = float(sys.argv[4]) if len(sys.argv) > 4 else 5.0
    base = Path(R)

    log_path = base / "log.txt"
    rx_path = base / "ue_rx.txt"
    if not log_path.exists() or not rx_path.exists():
        print(f"{R}  missing log.txt or ue_rx.txt; nothing to report", file=sys.stderr)
        return 0

    log = log_path.read_text(errors="ignore")
    sl = parse_slice_map(log)

    try:
        d = pd.read_csv(rx_path, on_bad_lines="skip").sort_values(["imsi", "t_s"])
    except Exception as exc:  # pragma: no cover - defensive for malformed campaign output
        print(f"{R}  unable to read ue_rx.txt: {exc}", file=sys.stderr)
        return 1

    if d.empty:
        print(f"{R}  window ({t0},{t1}] s  [no UE RX samples]")
        return 0

    for c in ("rx_bytes", "dly_pkts", "dly_sum_s"):
        if c not in d.columns:
            d[c] = 0.0

    _rst = 0
    for c in ("rx_bytes", "dly_pkts", "dly_sum_s"):
        _v = d.groupby("imsi")[c].diff().fillna(0.0)
        _rst += int((_v < 0).sum())
        d[f"d_{c}"] = _v.where(_v >= 0, d[c]).fillna(0.0)

    _bad = sorted(set(d.loc[d["dly_sum_s"] < 0, "imsi"]))
    if _bad:
        d.loc[d.imsi.isin(_bad), ["d_dly_pkts", "d_dly_sum_s"]] = float("nan")

    _rej = int(d["dly_bad"].max()) if "dly_bad" in d.columns else 0
    w = d[(d.t_s > t0) & (d.t_s <= t1)]

    if w.empty:
        print(f"{R}  window ({t0},{t1}] s  [no samples in selected interval]")
        return 0

    g = w.groupby("imsi").agg(b=("d_rx_bytes", "sum"), n=("d_dly_pkts", "sum"), s=("d_dly_sum_s", "sum"), k=("t_s", "size"))
    g["slice"] = [sl.get(i, 0) for i in g.index]
    g["Mbps"] = g.b * 8 / 1e6 / (g.k * 0.1)
    off = {0: cbr, 1: 0.564, 2: 3.1, 3: 0.08}
    g["deliv"] = g.Mbps / g.slice.map(off) * 100

    r = g.groupby("slice").agg(
        ues=("Mbps", "size"),
        Mbps_per_UE=("Mbps", "mean"),
        n=("n", "sum"),
        s=("s", "sum"),
        deliv_pct=("deliv", "mean"),
    )
    r["delay_ms"] = r.s / r.n.clip(lower=1) * 1000
    r.index = [{0: "eMBB", 1: "military", 2: "ambulance", 3: "IoT"}.get(i, i) for i in r.index]

    print(
        f"{R}  window ({t0},{t1}] s"
        + (f"  [{_rst} counter resets absorbed]" if _rst else "")
        + (f"  [UEs {_bad} excluded from the delay: corrupt timestamp]" if _bad else "")
        + (f"  [{_rej} samples rejected by the simulator]" if _rej else "")
    )
    print(r[["ues", "Mbps_per_UE", "deliv_pct", "delay_ms"]].round(2).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
