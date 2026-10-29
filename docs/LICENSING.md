# Licensing

| Part | Licence | Why |
|---|---|---|
| `xapp/xapp_jam_guard.c`, `xapp/flexric-CMakeLists.patch` | CSSL-1.0 (OpenAirInterface Collaborative Standards Software License), text in `LICENSES/CSSL-1.0.txt` | built on the FlexRIC xApp API and derived from the FlexRIC xApp examples; FlexRIC itself is used unmodified |
| `ns-o-ran/` (patches, full copies of modified ns-3 / ns-O-RAN files, scenarios, `jamguard_local.h`), `patches/` | GNU GPL v2, text in `LICENSES/GPL-2.0.txt` | derived from ns-3 / ns-O-RAN, which are GPLv2 |
| everything else (analysis scripts, dashboard, campaign runner, docs) | MIT, see `LICENSE` | original code of this repository |
| simulation data (release `dataset-v1`) | CC0 1.0, like the dataset of our previous work | |

Third-party software is not redistributed here: obtain FlexRIC from https://gitlab.eurecom.fr/mosaic5g/flexric
and ns-O-RAN (mmwave-LENA-oran, base commit in `ns-o-ran/BASE_COMMIT_mmwave-LENA-oran.txt`) from its repository.
