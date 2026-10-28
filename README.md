# JamGuard

Slice-aware closed-loop xApp for jamming detection, localization and mitigation in O-RAN,
running on FlexRIC and ns-O-RAN (ns-3 mmWave, EN-DC).

| folder | content |
|---|---|
| `xapp/` | FlexRIC xApp (C): detection, trilateration, mitigation, slicing, recovery |
| `ns3/scratch/` | EN-DC scenario with jammer, emulated RIC loop (`jamguard_local.h`), anchor-guard build |
| `patches/` | idempotent patch scripts applied to ns-O-RAN and FlexRIC (each keeps a `.bak_*` copy) |
| `scripts/` | campaign runner, live launcher, analysis and statistics |
| `results/` | campaign summaries and live-run logs |

Raw simulation output is archived separately (Zenodo, DOI to be added).
Licensing: see `docs/LICENSING.md`. The ns-3 parts are GPLv2 like the files they modify;
the xApp is subject to FlexRIC's licence terms.

## Dashboard

![JamGuard dashboard](docs/dashboard.png)

`scripts/jamguard_dash.py` is a local web dashboard (Python standard library only) for every run under `~/jamx*`:
per-slice throughput and delay, the map with the true jammer and JamGuard's estimate, the UE connection lanes,
the LTE-anchor state (canary test, `ANCHOR_BAD` / `ANCHOR_OK`) and the decision log. It reads emulated runs
(`jamguard_local.csv`) and live FlexRIC E2 runs (`jamguard_log.csv`), takes the jammer schedule from `jammer.txt`,
and refreshes running simulations every 2 s ("follow newest running" jumps to the newest one).

```bash
python3 scripts/jamguard_dash.py 8050      # then open http://localhost:8050
```
