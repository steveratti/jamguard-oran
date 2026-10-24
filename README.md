# JamGuard

A slice-aware closed-loop xApp for jamming detection, localization and mitigation in O-RAN.

JamGuard runs on the near-real-time RAN Intelligent Controller and closes the whole loop over the
E2 interface: it detects jamming from the per-UE SINR together with a multi-link consistency test
that separates a jammer from a blocked link, localizes the jammer from the interference estimated
with the received power and SINR carried by the KPM report, moves affected UEs to a clean NR cell
or to the LTE anchor, protects mission-critical slices, and returns the UEs once the jammer is
gone. It is implemented twice from the same decision logic: as a C xApp on FlexRIC over a real E2
interface, and inside ns-O-RAN for campaigns.

This repository holds the code, the simulator patches, the analysis scripts, the derived data
behind every table and figure of the paper, and one complete sample run.

## Layout

| Path | Contents |
|---|---|
| `xapp/` | the FlexRIC xApp (`xapp_jam_guard.c`): detection, localization, mitigation, recovery |
| `scenario/` | the ns-3 scenario and the in-simulator copy of the decision logic |
| `ns-o-ran-patches/` | every patch applied to ns-3 / ns-O-RAN and to the xApp, as idempotent Python scripts |
| `scripts/` | the analysis: detection replay, localization replay, churn, per-slice report, campaign aggregation, figures |
| `configs/` | the job files that define each campaign (run directory, command line, environment) |
| `data/sample_run/` | one run of the main campaign, with the file formats the scripts expect |
| `figures/` | the figures of the paper, as produced by `scripts/make_figs.py` |

## Reproducing

The simulator is ns-O-RAN (ns-3.42 with the mmWave module) and the controller is FlexRIC. Apply
the patches in the order listed in `CHANGELOG.md`; each one checks its own anchors and refuses to
apply a partial change, so a patch that does not match your tree stops with the expected text
instead of corrupting a file.

```
cd <ns-3 tree>
for p in ns-o-ran-patches/patch_*.py; do python3 "$p"; done
./ns3 build
```

A campaign is a job file and a runner:

```
bash scripts/run_jobs.sh configs/jobs_final.txt 18
python3 scripts/campaign_report.py <campaign dir> [t0 t1]
```

Each job line is `run_dir|ns-3 options|environment`, and a finished run gets a `.done` marker, so
an interrupted campaign resumes where it stopped.

### Which script produces which result

| Result | Script |
|---|---|
| per-slice delivery, delay and actions | `scripts/slice_report.py`, aggregated by `scripts/campaign_report.py` |
| detection probability, false alarms, delay | `scripts/roc_replay.py` |
| localization error per estimator | `scripts/loc_replay.py` |
| handover churn and ping-pong | `scripts/ho_churn.py` |
| the figures | `scripts/make_figs.py` |

`scripts/roc_replay.py` and `scripts/loc_replay.py` are replays: they read the logged KPM stream of
a run and apply a detector or an estimator offline, so variants can be compared on identical
inputs. Neither ever reads the jammer power or position that the simulator knows; the ground truth
is used only to score the result.

## Data

The complete campaign is 58 directories and about 10.9 GB, which does not belong in a Git
repository. It is published as a separate archive with its own DOI (see the paper's data
availability statement). This repository carries the derived tables, which are what the paper's
numbers are computed from, and one sample run so that the file formats are self-evident.

## What we changed in ns-O-RAN

Stock ns-O-RAN has no jammer, no RAN slicing and no E2 control actions beyond its own
traffic-steering use case. Beyond adding those, five defects were found and fixed; two of them
appear only in a closed loop, that is, only because an xApp moves UEs between cells and between
radio access technologies:

- the gNB MAC never received its cell identifier, so per-cell logic in the scheduler saw a wrong cell;
- an unsigned 16-bit underflow in the RLC buffer update starved a UE after a very small transport block;
- in optimized builds, the `PacketSink` stream reassembly looped forever on a corrupted SDU around an LTE--NR switch;
- the same reassembly can lose a datagram boundary once at a data-path move and read a timestamp from inside a payload, which poisons the cumulative delay counter of that UE for the rest of the run;
- the per-UE measurements of the E2SM-KPM DU report — transport-block and error counts, resource blocks used, the modulation and SINR bins, twenty-one quantities — are silently zero unless the scenario enables file tracing, because the only code that updates them sits at the end of the callback that writes the per-transport-block trace file.

The KPM report itself was extended with the per-UE, per-cell received signal power, which stock
ns-O-RAN does not expose because the mmWave RRC keeps only the SINR map that drives its own
handover logic. The SINR alone cannot localize a jammer, since it couples the serving signal power
with the interference. `CHANGELOG.md` lists every patch and what it changes.

## Citing

If you use this code, please cite the paper (see the repository description for the current
reference) and ns-O-RAN and FlexRIC, on which it is built.

## License

The patches apply to ns-3 / ns-O-RAN (GPLv2) and to FlexRIC; the files in this repository that are
derived from those projects keep their original licences. See `LICENSE` for the terms that apply to
the original work here.
