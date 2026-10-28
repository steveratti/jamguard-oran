# Changelog

Every patch is an idempotent Python script: it verifies its anchors, refuses to apply a partial
change, prints the expected text on a mismatch, and keeps a `.bak*` copy of each file it edits.
Apply them in the order below. The three groups are independent of each other; within a group the
order matters.

## Group 1 — ns-3 / ns-O-RAN library

Run from the root of the ns-3 tree, then `./ns3 build`.

| Patch | Files | Change |
|---|---|---|
| `patch_rsrp_kpm.py` | `mmwave-enb-phy.{h,cc}`, `mmwave-enb-net-device.cc` | caches the per-UE, per-cell wideband received power at the PHY and exposes it through `GetLastRsrpDbm()`; gated on `JG_RSRP_KPM` |
| `patch_rsrp_kpm2.py` | `mmwave-indication-message-helper.{h,cc}` | adds `JgAddUeExtra()` and appends the extra items inside `AddCuCpUePmItem`, which is where the CU-CP indication is actually built. The `ueVal` list in `MmWaveEnbNetDevice::BuildRicIndicationMessageCuCp` is dead code and never reaches E2 — items added there are silently dropped |
| `patch_rsrp_gate.py` | `mmwave-enb-phy.cc` | gates the PHY-side recording behind the same environment variable, so the extension can be switched off for an isolation test |
| `patch_du_kpm.py` | `mmwave-phy-trace.{h,cc}`, `mmwave-helper.{h,cc}` | separates the DU KPM measurements from the per-transport-block trace file; makes `EnableDlPhyTrace`/`EnableUlPhyTrace` idempotent so a second connection cannot double-count; attaches the PHY sinks as soon as E2 is enabled, deferred to t=0 because the UE devices are installed after the gNBs |

## Group 2 — ns-3 scenario and the in-simulator decision logic

Run from the root of the ns-3 tree, then `./ns3 build`.

| Patch | Target | Change |
|---|---|---|
| `patch_v3_local.py` | `scratch/jamguard_local.h` | v3 decision logic: SINR clipping, protection cap, multi-link consistency, localization-guided target selection, ping-pong hold, passive recovery. Every feature is off unless its environment variable is set |
| `patch_a3.py` | `scratch/scenario_jam_xapp.cc` | the plain A3 handover baseline (policy 7): a neighbour above the serving cell by `JG_A3_HYST` for `JG_A3_TTT` consecutive reports, then a cool-down. Needed because the stock threshold handover never fires in this deployment, which leaves the monitor-only policy with zero handovers and no mobility baseline |
| `patch_passive2.py` | `scratch/jamguard_local.h` | guards against declaring the attack over too early: a hold before the first probe, a majority rule over the UEs still on the anchor, and a doubling of the hold after a wrong recovery |
| `patch_mobile_jammer_xapp.py` | `scratch/scenario_jam_xapp.cc` | `--jammerVx` / `--jammerVy`, a constant-velocity jammer active only while it transmits, and `jammer_track.txt` as ground truth for the localization replay |
| `patch_delay_guard.py` | `scratch/scenario_jam_xapp.cc` | rejects a non-physical application-delay sample (negative, NaN, or above `JG_DLY_MAX`), counts the rejections per UE and exports the count as a new last column of `ue_rx.txt` |

## Group 3 — FlexRIC xApp

Run from the FlexRIC tree, then rebuild the xApp. Apply in this order.

| Patch | Change |
|---|---|
| `patch_v3_xapp.py` | the same v3 features as `patch_v3_local.py`, in the C xApp |
| `patch_rsrp_xapp.py` | interference-power trilateration (`JG_LOC=2`): a robust soft-L1 least-squares fit over position, jammer power and path-loss exponent, with a coarse then fine grid. Includes libm-free helpers, because the xApp is not linked against libm |
| `patch_tri2.py` | keeps evacuated UEs as observers, gates the fit on `JG_TRI_MIN` observations, and stops the old centroid from overwriting a published trilateration estimate |
| `patch_passive2.py` | the same recovery guards as in group 2 — the script detects whether it is editing the C++ header or the C xApp |

Groups 2 and 3 must stay in step: the emulated loop and the live xApp implement the same decision
logic, and a change applied to only one of them silently breaks the equivalence that the two-tier
evaluation rests on.

## Not applied by default

| Patch | Why |
|---|---|
| `patch_x420_xapp.py` | sensor fusion with a USRP X420 front end (`JG_SENSOR`). The module is integrated and builds, but no result in the paper uses it |

## Notes on the environment variables

Every feature added to the decision logic is off unless its variable is set, so that an ablation is
a change of environment rather than a change of code, and so that a default build reproduces the
baseline behaviour. The job files in `configs/` record the exact environment of every run.
