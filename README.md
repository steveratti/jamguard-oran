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
