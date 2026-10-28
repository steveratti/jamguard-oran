# JamGuard — project handoff

**Paper:** *JamGuard: A Slice-Aware Closed-Loop xApp for Jamming Detection, Localization, and
Mitigation in O-RAN* — target venue IEEE Access, submission **mid-November 2026**.

**Platform:** ns-O-RAN (ns-3.42 + mmWave-LENA) at `~/ns-O-RAN-flexric/mmwave-LENA-oran`, with
FlexRIC at `~/flexric`. Host: WSL, user `k3`, machine `DESKTOP-9C5OUC6`.

This document is written so a new session can continue without re-deriving anything. Every number
in it was measured; where something is unverified it says so.

---

## 1. How the user wants to work (follow these)

- **Reply in Roman Urdu.** Technical terms stay in English.
- **One command at a time.** Not a list of five commands to run in sequence.
- **Test before delivering.** Never hand over a command or script that has not been run. For
  patches, build a mock of the real code and apply the patch to it first. The user has said this
  explicitly and it has caught real bugs several times.
- **Never state an unverified number.** No estimates presented as measurements.
- **Long scripts go as files.** The user copies them from `/mnt/c/Users/steve/Downloads/` into
  `~/`. Short commands go inline as short-line heredocs.
- **No tokens, GitHub tokens, or passwords in chat, ever.** The user does `gh auth login` locally.
  (A token was pasted once in an earlier session; it was refused and the user was told to revoke
  it. Keep refusing.) HEC tokens stay disabled.
- **No inspection files written into Downloads** — print inspections to the terminal instead.
- The user's Claude usage limit is tight. Make each command high-value; do not spend turns on
  things that can be batched into one command.
- Own mistakes plainly when they happen. This has mattered: several of the best results in the
  paper came from correcting a wrong hypothesis out loud rather than defending it.

---

## 2. Scenario and configuration

EN-DC: LTE anchor is cell 1, NR gNBs are cells 2–5. FR1 at 3.5 GHz, 20 MHz, 10 UEs, CBR 5 Mb/s
downlink. Jammer at (710, 510) m, active 4–10 s, EIRP swept 30–50 dBm, full-band.

Slices are assigned by IMSI at attachment and never change: **military 2 UEs, ambulance 5 UEs,
IoT 9 UEs** (the flags are counts: `--militaryUes=2 --ambulanceUes=5 --iotUes=9`).

### Policies

| id | flags | what it is |
|---|---|---|
| p0 | `--jgPolicy=0` | monitor only, no action |
| p1 | `--jgPolicy=1` | reactive |
| p2 | `--jgPolicy=2` | localization-aware |
| **p4** | `--jgPolicy=2 --jgSlice=1 --jgSrec=1` | **slice-aware — the proposed policy** |
| p5 | — | baseline B2, PRB reservation (Delavari) |
| p6 | — | baseline B1, MCS cap (Hoffmann) |
| p7 / A3 | — | plain A3 handover baseline |

### Verified scenario flags

`--simTime --RngRun --jammerPowerDbm --jammerStart --jammerStop --jammerOn --jammerPeriodMs
--jammerDuty --jgPolicy --jgSlice --jgSrec --militaryUes --ambulanceUes --iotUes`
plus a jammer-position option (confirmed to exist — the geometry batch ran with it).

Attack-free runs use `--simTime=21 --jammerOn=0`. Attack runs use `--simTime=14
--jammerStart=4 --jammerStop=10`. The keyed jammer adds `--jammerPeriodMs=40 --jammerDuty=0.5`,
which is faster than the 100 ms KPM reporting period.

### Detectors

| id | rule |
|---|---|
| D1 | SINR drop only |
| D2 | + multi-link consistency (neighbour cells must also drop) |
| D3 | + RSRP divergence |
| D4 | both |
| D5 | **MCS falls ≥ Δ indices below the UE's own running baseline** |
| D6 | SINR AND (multi-link OR MCS) — **tested and rejected**, worse than D2 |
| **D7** | **alarm from the multi-link test; per-UE attribution from either indicator, gated by the alarm — adopted** |

---

## 3. Results — all measured

### 3.1 Power sweep (`~/jamx_P`, 15 seeds, window (4,10])

Military-slice delivery, mean ± std:

| EIRP | p0 | p4 | gap | p4 actions | p4 detect_ms |
|---|---|---|---|---|---|
| 30 dBm | 95.3±6.0 | 98.5±1.3 | **+3.2** | 7.4±7.5 | 400±0 |
| 40 dBm | 94.1±6.7 | 98.9±1.8 | **+4.8** | 21.9±9.7 | 856±1067 |
| 50 dBm | 93.7±5.9 | 99.2±1.1 | **+5.5** | 32.5 | ~320 |

Ambulance gap over the same sweep: +0.4 → +1.0 → +3.9. p0 takes 0 actions at every power.

**The claim this supports:** the policy's benefit grows with attack strength while its cost
(actions) stays proportionate — it barely acts at 30 dBm. This answers both "you evaluated one
operating point" and "it just churns handovers".

### 3.2 p1 and p2 at 15 seeds, 50 dBm (`~/jamx_F`)

| pol | n | military | ambulance | IoT | eMBB | detect_ms | FA | actions |
|---|---|---|---|---|---|---|---|---|
| p1 | 15 | 99.0±1.1 / 23.4±19.5 | 95.3±**10.9** / 18.1±4.1 | 99.5±0.5 | 97.1±1.5 | 306.7±25.8 | 0 | 20.6±3.4 |
| p2 | 15 | 96.5±**11.4** / 18.6±3.1 | 97.1±5.7 / 18.8±4.1 | 99.7±0.3 | 96.6±2.7 | 306.7±25.8 | 0 | 28.1±4.4 |

Note the large spreads (±10.9, ±11.4) against p4's ±1.1. **p4 is not only better, it is more
consistent** — worth a sentence in the paper, and worth checking whether one bad seed dominates.

### 3.3 Detector ROC, constant jammer (`~/jamx_D5`, 10 attack + 25 attack-free, blockage 2/UE/min, K=2)

| det | drop | Pd | delay_s | FA/min | UE recall | UE_FF/UE/min |
|---|---|---|---|---|---|---|
| D2 | 4 | **1.000** | 0.21 | **0.000** | 0.388 | 0.463 |
| D2 | 12 | 1.000 | 0.28 | 0.000 | 0.340 | 0.103 |
| D5 | any | 0.080 | 0.20 | 9.517 | 0.571 | 6.137 |
| **D7** | 4 | **1.000** | 0.21 | **0.000** | **0.591** | 2.966 |
| D7 | 12 | 1.000 | 0.28 | 0.000 | 0.572 | 2.383 |

D7 raises attribution **+52 %** over D2 with the alarm unchanged. This replicated: an earlier
5 attack + 5 free measurement gave 0.416 → 0.615, and the larger set gives 0.388 → 0.591. The
honest cost is UE false flags, 0.46 → 2.97.

### 3.4 Detector ROC, keyed jammer (40 ms period, 50 % duty) — the strongest result

| det | Pd constant | Pd keyed | recall constant | recall keyed | fraction of recall surviving |
|---|---|---|---|---|---|
| D1 | — | 0.005 | — | 0.061 | — |
| D2 | **1.000** | **0.001** | 0.388 | 0.027 | **7 %** |
| D3 | — | 0.000 | — | 0.001 | — |
| D4 | — | 0.000 | — | 0.000 | — |
| D5 | 0.080 | 0.001 | 0.571 | **0.428** | **75 %** |
| D6 | — | 0.005 | — | 0.050 | — |
| D7 | **1.000** | **0.001** | 0.591 | 0.038 | 6 % |

**Two findings here.** First, every SINR-based detector goes from a perfect alarm to no alarm at
all when the jammer keys faster than the reporting period — the L3 SINR average absorbs it.
Second, the two layers are *not* equally affected: the MCS indicator keeps three quarters of its
per-UE signal while the SINR indicator keeps 7 %. D7 collapses because its alarm gate is the
SINR multi-link test; when the alarm dies, the gated attribution dies with it.

Note also that D1 produces 2.7 false alarms per minute on benign channel while scoring Pd 0.005
on the real keyed attack — it barks at noise and stays silent at the intruder.

### 3.5 The BLER investigation — a four-way negative result, then its cause

The user pushed hard on "BLER must rise when a jammer is present". Four physically motivated
routes were measured, all on existing campaign data:

| test | result |
|---|---|
| window average | **falls**: 0.278 → 0.239 under attack, vs 0.278 → 0.265 attack-free |
| onset transient | **none**: peak/pre ratio 1.10; the benign per-report range is already 0.12–0.37 |
| saturation-conditioned | **no**: at MCS < 5 the rate is still ~0.23–0.31, i.e. still regulated |
| residual at equal MCS | **no, and inverted**: attack-free is higher in **6 of 6** MCS bands (e.g. band 0–5: 0.289 attack vs 0.624 attack-free) |

Meanwhile the MCS moves clearly: mean 22.14 → 16.26 under the jammer (22.31 → 21.85 attack-free),
with bin mass moving from Bin6 (51242 → 22070) to Bin1 (3800 → 11918). And `frac MCS<5` is
0.103–0.172 under attack versus 0.000–0.003 attack-free — a near-perfect separator, **but those
attack-free runs carry no injected blockage, so this must be re-measured with blockage before it
is called a detector.**

**Then the cause was found, and it changes the claim.** In
`src/mmwave/helper/mmwave-phy-trace.cc`, `MmWavePhyTrace::UpdateTraces` classifies each transport
block by redundancy version alone:

```cpp
if (params.m_rv == 0)  m_macPduInitialTransmissionUeSpecific++;
else                   m_macPduRetransmissionUeSpecific++;
```

It **never reads `params.m_corrupt`**, the flag the error model sets when a block has failed. The
value emitted as `TB.ErrTotalNbrDl.1.UEID` is `GetMacPduRetransmissionUeSpecific`, i.e. a count of
retransmitted PDUs. Verified arithmetically on real data: `TB.TotNbrDl − TB.TotNbrDlInitial`
equals `TB.ErrTotalNbrDl` exactly (177349 − 129609 = 47740; 248037 − 172458 = 75579).

So neither `err/total` nor `err/initial` is a block error rate, and `err/initial ≈ 0.4` cannot be
converted into one without the retransmission-depth distribution, which the report does not carry.
3GPP TS 28.552 clause 5.1.1.7 defines five TB measurements:

| clause | measurement | emitted by stock ns-O-RAN? |
|---|---|---|
| 5.1.1.7.1 | total number of DL **initial** TBs | yes, correctly |
| 5.1.1.7.2 | **initial** error number of DL TBs | no |
| 5.1.1.7.3 | total number of DL TBs | yes, correctly |
| 5.1.1.7.4 | total error number of DL TBs | no — the item of that name holds retransmissions |
| 5.1.1.7.5 | **residual** error number of DL TBs | no |

**The paper claim:** published BLER detectors disagree with each other across platforms because
"BLER" is not one quantity. Link adaptation regulates the *initial* rate towards a target, so it
is a controlled variable and carries little information about a sustained interferer. The
*residual* rate — blocks still undecodable after the last permitted redundancy version — is
outside that loop, and no platform in this line of work exposes it.

---

## 4. Library modifications (all applied and built)

| patch | what it does | state |
|---|---|---|
| `patch_du_kpm.py` / `e2du.py` (E2DUFIX) | decouples the DU KPM report from the trace file, so DU counters are usable in live mode; 11 edits in 4 files | applied |
| `patch_bler_kpm.py` (JGBLER) | emits `TBTotDl_UEID_<imsi>`, `TBErrDl_UEID_<imsi>` so a name-parsing xApp can attribute DU counters | applied, built |
| `patch_rbler_kpm.py` (JGRBLER) | **the TS 28.552 error counters**, three stages | applied, built 2026-10-25 |

### What `patch_rbler_kpm.py` added

Derived from fields already carried by every traced block (`RxPacketTraceParams` in
`src/mmwave/model/mmwave-phy-mac-common.h` has `m_rv`, `m_corrupt`, `m_tbler`, `m_mcs`, `m_sinr`):

| counter | condition |
|---|---|
| initial error (5.1.1.7.2) | `m_corrupt && m_rv == 0` |
| total error (5.1.1.7.4) | `m_corrupt` |
| **residual error (5.1.1.7.5)** | `m_corrupt && m_rv == 3` |

`rv == 3` is not a guess: `src/mmwave/model/mmwave-spectrum-phy.cc` ends the HARQ process at
`if (!itTb->second.m_isCorrupted || itTb->second.m_expected.m_rv == 3)`.

Three stages, each verifying its own anchors and skipping cleanly if the tree does not match:
**A** the counters in `mmwave-phy-trace.{h,cc}`; **B** the E2 items in
`mmwave-indication-message-helper.{h,cc}` and `mmwave-enb-net-device.cc` (new parameters are
defaulted to `-1`, so untouched call sites keep compiling); **C** the DU CSV file log — **two**
row sites and **two** header sites, because the DU message is built in a normal and an
energy-saving variant.

The stock `TB.ErrTotalNbrDl.1.UEID` item is **left untouched**, so every earlier result stays
reproducible. New measurement names:

- E2 and file log: `TB.ErrNbrDlInitial.UEID`, `TB.ErrTotalNbrDlTrue.UEID`, `TB.ResidErrNbrDl.UEID`
- UE-named, for the live xApp: `TBErrInitDl_UEID_<imsi>`, `TBErrTotTrueDl_UEID_<imsi>`,
  `TBErrResidDl_UEID_<imsi>`

Verified: compiled with g++ against stubs, and a behaviour test with a known rv/corrupt sequence
gave `initial_err=2 total_err=5 residual_err=1 retx=4` (retx unchanged). After the real build,
`du-cell-*.txt` carries the three new columns at header positions 39, 40, 41.

Every patched file has a `.bak_rbler` copy of the **pristine** original.

---

## 5. In flight right now

A 10-run verification campaign (`~/jamx_RB`, 5 attack + 5 attack-free at 50 dBm, p0) is running
with the new binary, and this is queued to analyse it when the runs finish:

```bash
nohup bash -c 'while [ "$(pgrep -c ns3.42-scenario)" -gt 0 ]; do sleep 60; done; python3 ~/rbler_check.py --pos "$HOME/jamx_RB/pos50_s*" --neg "$HOME/jamx_RB/neg_s*"' > ~/rb_out.txt 2>&1 &
```

Read it with `cat ~/rb_out.txt`. `rbler_check.py` reports four things in falsification order:
counter sanity; the three rates before/during attack; windowed per-UE residual rate scored as a
detector (Pd, delay, FA/min — the same shape the SINR detectors are scored with); and the onset
per report.

**A sanity target to watch for:** if the measured **iBLER lands near 0.10**, it confirms the
platform's link-adaptation target quantitatively and proves the old `≈0.39` was a wrong counter.

---

## 6. Pending work, in priority order

1. **Read `~/rb_out.txt`.** If residual BLER separates on the constant jammer (Pd high, FA low),
   immediately run the same test on the keyed jammer — that is where SINR scores Pd 0.001 and
   where a counter outside the control loop should survive. One result there gives the paper a
   detector for **both** threat models.
2. **Live FlexRIC validation.** The single largest reviewer risk. Two `\tbd{validation result}`
   placeholders in the paper (around lines 343 and 360 of the main file) wait on it, plus a
   latency table and `compare_live.py`. Needs an idle machine.
3. **D7 in the closed loop.** Port the D7 rule into `jamguard_local.h` (the emulated loop) behind
   an environment flag, then run p4+D7 and compare military delivery and action count against p4
   (99.2±1.1, 32.5 actions). Until this is measured, do **not** claim D7 is better in the loop —
   +52 % attribution costs 6× the UE false flags and the trade must be shown, not asserted.
   `~/overnight_results/local_h_detect.txt` already holds the relevant lines of that file.
   The xApp counterpart is `int const deg = (u->sinr < P_S_LOW && u->base - u->sinr >= P_DROP) && jg_mlink_ok(u, r);`
4. **MCS attribution for the live xApp.** DU KPM items do not carry the UE in the name, including
   `CARR.PDSCHMCSDist.Bin1..6.UEID`. Offline replay reads `ueImsiComplete` from the CSV, but the
   live xApp parses names — so **D5/D7 cannot run live until an MCS item with the UE in its name
   is emitted**, exactly as was done for the TB counters. Verify against the xApp parser first.
5. **Report-tool naming.** `~/overnight_results/geometry.txt` and `keyed_policy.txt` came out
   empty. The data is intact — 20 geometry runs in `~/jamx_G` (`g2_*`, `g3_*`) and 5 keyed-p4 runs
   in `~/jamx_D5` (`keyed50_p4_s*`) — but `campaign_report.py` parses directory names of the form
   `pw<dbm>_p<pol>_s<seed>` and these do not match. Fix with symlinks into new directories; do not
   re-run.
6. **Reconcile the main table's seed counts.** `~/jamx_F` shows 50 dBm p0 and p4 at **n=5**
   (89.3±5.7 and 99.4±0.4) while the 15-seed figures used in the paper (93.7±5.9 and 99.2±1.1)
   come from a different directory. One table must come from one consistent set, or a reviewer
   will catch it. Decide which set is canonical and state the seed count per row.
7. **Fill the prepared tables** with the new numbers: `tab:sweep`, `tab:keyed`, the D5/D7 rows of
   `tab:roc`, and the `sec:det` paragraph. See section 7.
8. **Repo and artifact:** `LICENSE` per directory (see `LICENSING.md` — the ns-3 patches are GPLv2
   because the files they modify are; the xApp is subject to FlexRIC's terms, which **must be read
   from `~/flexric/LICENSE` before publishing**, since the OAI licence page does not mention
   FlexRIC and several OAI components use a modified Apache 2.0 restricted to non-commercial and
   academic research), the four figure PDFs into `figures/`, derived CSVs into `data/`, a Zenodo
   deposit for the ~10.9 GB of raw output with a reserved DOI, and make the repo public before
   submission.
9. **Recount** "about 550 added lines in 15 source files" in `sec:nsoran-ext` from
   `git diff --stat` — it has grown since.
10. **`slice_report.py` returns non-zero on `~/jamx_F`** — unresolved.
11. **Scenario figure** (`\tbd{scenario figure}`, around line 170) from `gnbs.txt`, `enbs.txt`,
    `jammer.txt`, `ue_position.txt` in `~/jamx_F/pw50_p0_s1`.
12. **Tail-latency subsection** still rests on 5 seeds (the "259 → 21 ms worst-100 ms" claim) —
    either re-run at 15 seeds or state the seed count in the text.
13. **Unresolved question from the professor:** the "UE3 at 67 dB" data-validity check. Note that
    `jamguard_local.csv` is a 15-column event log, not per-round, so the check must use
    `MmWaveSinrTime.txt` or the KPM dump.

---

## 7. LaTeX assets already written and compile-tested

All compile with 0 errors and 0 overfull boxes at IEEE single-column width.

| file | contents |
|---|---|
| `jamguard_main_v7.tex` | the assembled paper (1063+ lines) |
| `jamguard_limits.tex` | **BLOCK JM** threat model (one `\tbd{}`: whether the jammer is a transmitting device or an added interference term — resolve with `grep -n "jammer" scratch/scenario_jam_xapp.cc`; both candidate sentences are written in the file's comments) and **BLOCK LIM** limitations |
| `jamguard_newtabs.tex` | `tab:sweep`, `tab:keyed`, the `tab:roc` additions, and **BLOCK DET** — the paragraph carrying the alarm/attribution design claim |
| `jamguard_churn.tex` | `tab:churn` — RAN-executed vs xApp-commanded changes and ping-pong |
| `jamguard_e2du.tex` | the ns-O-RAN defects and lessons blocks |
| `jamguard_rw.tex` | related work, including the xApp-conflict subsection |
| `jamguard_sig15.tex` | the statistical-significance subsection |
| `jamguard_mobile_tradeoff.tex` | the mobility/trade-off block |
| `LICENSING.md` | per-directory licensing for the repo |

Each table in `jamguard_newtabs.tex` has, in its comments, the result file each number comes from
**and what to write if the numbers go the other way**. Use those — they were written before the
numbers were known, deliberately.

### Permutation tests (10⁵ Monte-Carlo permutations, n=15/15)

p4 vs p0: military +5.54 (p=0.00057), ambulance delivery +3.93 (p=0.00042), ambulance delay
−36.26 ms (p=0.01756). vs p5: +5.09 / +5.57 / −97.13 ms. vs p6: +16.70 / +53.76 / −1292 ms.
vs p7: +3.05 (p=0.00008) / +3.44 (p=0.00001) / −39.20 ms (p=0.00989).
At 15 vs 15 the exact test is infeasible (C(30,15) ≈ 1.55×10⁸), hence 10⁵ random permutations;
resolution 10⁻⁵ against the 0.008 floor at 5 seeds.

**An honest correction already written into the paper:** going from 5 to 15 seeds raised p0's
military delivery from 89.3 to 93.7 while p4 held, narrowing the claimable gap from +10.1 to
+5.5 points. The ordering, every baseline comparison and the spreads are unchanged. Keep this
paragraph — it is why the statistics section is credible.

---

## 8. Traps already paid for — do not repeat these

- **`pgrep -f <pattern>` matches the asking process's own command line.** A wait loop built on it
  deadlocks forever. Use `pgrep -c ns3.42-scenario` (comm name, no `-f`). Also do **not** write
  `pgrep -c X || echo 0`: `pgrep -c` prints `0` *and* exits 1, so the fallback fires too and the
  output becomes two lines, which breaks `[ "$n" -gt 0 ]`.
- **Never analyse a campaign that is still running.** Directories are created at launch, so their
  existence proves nothing. Reading in-progress runs gave two different answers from the same
  script minutes apart, which is how this was discovered. Use only completed seeds.
- **Never build ns-3 while a campaign is running** — the binary changes under the running
  simulations.
- **`campaign_report.py` parses directory names** of the form `pw<dbm>_p<pol>_s<seed>`. Anything
  else yields an empty report with a header and no rows (this silently cost the geometry and
  keyed-policy reports).
- **`du-cell-*.txt` needs `encoding='latin-1', on_bad_lines='skip'`** — `plmId` contains byte
  `0xf1` and pandas raises `UnicodeDecodeError` otherwise.
- **`roc_replay.py` hardcodes `DET`**; `--det` is ignored. The D5/D6/D7 patches append to that
  list. `--dmcs` takes a single float, not a list.
- **`campaign_report.py`'s default window is (4,10]**, not (4,20] — the recovery row needs
  explicit arguments.
- **Patch anchors:** verify, never assume, and check how **many** times an anchor occurs. Stage C
  of the rBLER patch failed first time because the DU CSV row exists twice. Also
  `Config::Connect` only matches objects that already exist, so PHY sinks must be attached with
  `Simulator::Schedule(Seconds(0.0), ...)` rather than at install time.
- **The DU report's `EnableDuReport` defaults to true**, and the indication is sent over E2
  whenever `m_forceE2FileLogging` is false.
- A live capture exists at `~/jamx_live/rsrp/kpm_dump.csv` with 7800 `TB.*` rows.

---

## 9. Key file locations

| | |
|---|---|
| ns-3 tree | `~/ns-O-RAN-flexric/mmwave-LENA-oran` |
| FlexRIC | `~/flexric`; xApp at `~/flexric/examples/xApp/c/orange/xapp_jam_guard.c` |
| emulated loop | `scratch/jamguard_local.h` in the ns-3 tree |
| scenario | `scratch/scenario_jam_xapp.cc` |
| overnight results | `~/overnight_results/` |
| campaigns | `~/jamx_F` (main), `~/jamx_P` (power sweep), `~/jamx_D5` (detector ROC, 90 runs), `~/jamx_G` (geometry), `~/jamx_RB` (residual BLER) |
| analysis scripts | `~/campaign_report.py`, `~/roc_replay.py`, `~/slice_report.py`, `~/ho_churn.py`, `~/bler_dynamics.py`, `~/rbler_check.py` |
| job runner | `~/run_jobs.sh <jobfile> <parallel>`; job line format `outdir|args|` |
| overnight launcher | `~/overnight.sh` (has the `|| echo 0` bug described above) |

---

## 10. The novelty, stated for a reviewer

1. **Which indicator works is a property of the attack's time structure, not of the detector.**
   Measured: every SINR-based detector goes from Pd 1.00 to Pd 0.001 when the jammer keys faster
   than the KPM reporting period, while the modulation indicator keeps 75 % of its per-UE signal
   against the SINR indicator's 7 %. Since the O-RAN reporting period is not under the defender's
   control, this is a platform limit, not an algorithm choice.
2. **Raising an alarm and attributing it to UEs are different decisions** and should be driven by
   indicators from different layers: the alarm must be specific, the attribution sensitive. D7
   gives +52 % attribution at an unchanged alarm (Pd 1.00, FA 0.00), replicated on two seed sets.
3. **"BLER" is not one quantity, and the one this family of platforms exposes is not an error
   rate at all.** Four independent tests found no jamming signal in it; the cause is that
   `UpdateTraces` never reads the corruption flag, and TS 28.552's error counters are absent. The
   initial rate is regulated by link adaptation; the residual rate is not. This is now
   implemented and measurable.
4. **False alarms measured under a benign impairment** (blockage at 2 episodes per UE per
   minute). Prior work in this line reports no false-alarm rate and evaluates on a quiet channel.
5. **Closed-loop slice-aware mitigation** against four baselines reimplemented on the same
   platform, 15 seeds, permutation tests, and a power sweep showing the benefit grows with attack
   strength while the action count stays proportionate.
6. **Platform contributions:** the DU KPM decoupling fix, UE-attributable TB counters, and the
   three TS 28.552 error counters.
