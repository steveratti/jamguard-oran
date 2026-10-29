# ns-O-RAN modifications used by JamGuard

Exported from the working tree that produced the paper results.

| File | Content |
|---|---|
| `ns3-src.patch` | `git diff` of `src/` against mmwave-LENA-oran at `BASE_COMMIT_mmwave-LENA-oran.txt` |
| `oran-interface.patch` | `git diff` of `contrib/oran-interface` at `BASE_COMMIT_oran-interface.txt` |
| `full/` | full copies of every modified file, plus the new `slice-registry.h/.cc` |
| `scratch/` | `scenario_jam_anchor.cc` (campaigns), `scenario_jam_xapp.cc` (live FlexRIC runs), `jamguard_local.h` (emulated RIC loop) |

Apply: `cd mmwave-LENA-oran && git checkout $(cat BASE_COMMIT_mmwave-LENA-oran.txt) && git apply ns3-src.patch`,
then in `contrib/oran-interface`: `git apply oran-interface.patch` and copy `full/contrib/oran-interface/model/slice-registry.*`;
copy `scratch/*` to `scratch/` and build with `./ns3 build`.
The JamGuard xApp is `../xapp/xapp_jam_guard.c`; FlexRIC is used unmodified (`../xapp/flexric-CMakeLists.patch` only adds the xApp target).
