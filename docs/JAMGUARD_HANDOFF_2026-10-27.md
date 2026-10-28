# JamGuard — handoff addendum, 2026-10-27 evening

Read this together with `JAMGUARD_HANDOFF.md` (older, still valid except where this file says otherwise)
and `CLAUDE_jamguard.md`. Working rules are unchanged: reply in Roman Urdu, one command at a time,
test before delivering (mock + stubs), never state an unmeasured number, never build ns-3 while a
simulation runs (`pgrep -x ns3.42-scenario`).

## 1. Residual BLER (`~/jamx_RB`, 5 attack + 5 attack-free, 50 dBm, p0) — NEGATIVE

`cat ~/rb_out.txt`. Counters are sane. Under the jammer all three TS 28.552 rates FALL, paired by seed
(pre-attack values of pos/neg match, same RNG until 4 s):

| seed | rBLER attack / free | iBLER attack / free |
|---|---|---|
| s1 | 0.0098 / 0.0198 | 0.1537 / 0.2321 |
| s2 | 0.0082 / 0.0116 | 0.1321 / 0.1815 |
| s3 | 0.0116 / 0.0264 | 0.1890 / 0.2502 |
| s4 | 0.0106 / 0.0166 | 0.1566 / 0.2090 |
| s5 | 0.0086 / 0.0172 | 0.1535 / 0.2329 |

No residual-rate detector reaches FA 0 (best 2.87/min at Pd 1, which is a trivially-on alarm). No onset.
Pre-attack iBLER is 0.18–0.26, NOT ~0.10, so the "LA target 0.10" hypothesis is not confirmed.
**Paper: drop the residual-BLER claim.** Keep the platform contribution (the three TS 28.552 counters,
and that the stock item counts retransmissions). Likely cause (MCS 22→16, LA over-compensates) is
NOT measured — do not state it as a cause.

## 2. Live FlexRIC validation — DONE (n = 1, seed 1)

Launcher: `~/live_val.sh <name> [XAPP_ENV=..]`, extra ns-3 flags via `NS_ARGS="..."`.
It starts RIC → ns-3 → xApp, waits for ns-3, kills the rest. Logs: `~/jamx_live/<name>/{log,ric,xapp}.txt`.
`jamguard_log.csv` is written at the end; live progress is in `xapp.txt`.
Progress in sim seconds = `wc -l ue_position.txt` / 100 (10 UEs × 10 Hz); the first column of
`ue_position.txt` is a wall-clock ms timestamp, not sim time.

`~/jamx_live/val_p4` (14 s, p4, RngRun=1, 50 dBm, default JG_LOC) vs emulated `~/jamx_T/pw50_p4_s1`:

| slice | live E2 | emulated |
|---|---|---|
| military | 99.1 % / 15.6 ms | 99.7 % / 22.9 ms |
| ambulance | 98.9 % / 14.0 ms | 99.8 % / 15.4 ms |
| IoT | 99.8 % / 14.9 ms | 100.0 % / 14.9 ms |
| eMBB | 91.4 % / 29.3 ms | 93.3 % / 41.5 ms |
| E2 actions | 23 | 36 |

Decision-level match is low: 10 of 41 live decisions match the emulated log (±1 s). Hypothesis (not
measured): live reads KPM over E2, emulated reads the RRC SINR map directly; once one decision differs
the trajectory diverges. **Paper claim = outcome equivalence (critical slices within 1 point), not
decision equivalence.** Live `t_rep_s` is offset by ~0.8 s from sim time (first apply at sim 4.30 s =
live rep 35); `compare_live.py` now takes `OFF=0.8` (backup `.bak_off`). `campaign_report.py` works on
live runs through symlinks in `~/jamx_valcmp/pw50_p4_s<n>` (detect_ms/actions columns are empty there
because it reads the emulated log).

Latency, idle machine, val_p4: decision 0.076 ms median (p95 0.19), KPM→decision 7.2 ms (p95 13.3),
E2 control→RIC ACK 1.48 ms (p95 2.34), E2 downlink 0.77 ms (p95 1.16), ns-3 apply 2.2 ms (p95 11.8).
n = 16/23. End-to-end ~12 ms vs 1 s budget.

`~/jamx_live/live60` — 60 s, 4 jamming episodes (keyed 12 s period, 50 % duty, 4–50 s: ON 4–10,
16–22, 28–34, 40–46), started 21:03, ~1 sim-s per wall-minute. Result: `cat ~/live60.out`, then
DETECT/PROBE_OK/RETURN counts per episode, campaign_report via `~/jamx_valcmp/pw50_p4_s60`, latency.

## 3. Things found in the code today

- `scenario_jam_xapp.cc` line ~290: `ThreeGppChannelModel::Blockage = true` → 3GPP stochastic blockage
  IS simulated. Paper says "no buildings, so blockage is injected" — fix: injected blockage is ON TOP.
- Shadowing is ON for cellular and jammer links (lines 437, 543); trilateration fits log-distance with a
  free exponent → model mismatch is real (answers "observables synthesised with the estimator's model").
- Trilateration observation = one (UE, 1-s window) pair, accumulated since the alarm; `JG_TRI_MIN=8` can
  be met by 2 UEs × 4 windows (shown on a mock). Same criticism as "density = dwell time".
- Emulated loop tick is hard-coded 100 ms (`jamguard_local.h` line 626). `roc_replay.py` reads
  `MmWaveJammerRx.txt` at 1 ms, so a T_r × P detection-delay sweep can be done offline by re-binning.
- `jobs_day.txt` has `--RngRun=1--jammerPowerDbm=50` (missing space) in the `jamx_E` lines — verify the
  seed was parsed (compare two seeds' ue_position.txt) before trusting `jamx_E`.
- LTE anchor channel: `MmWaveHelper::m_downlinkChannel` is private; reach it with
  `LteEnbNetDevice::GetPhy()->GetDownlinkSpectrumPhy()->GetChannel()`. LTE EARFCN/bandwidth are defaults.

- **Slice flags are IMSI lists, not counts** (`cmd.AddValue ("militaryUes", "IMSIs in the military slice (1)", ...)`,
  a string). `--militaryUes=2 --ambulanceUes=5 --iotUes=9` = IMSI 2 military, IMSI 5 ambulance, IMSI 9 IoT,
  i.e. 1 + 1 + 1 critical UEs and 7 eMBB. Table IV of the paper is CORRECT; section 2 of the older
  `JAMGUARD_HANDOFF.md` ("the flags are counts") is WRONG.

## 4. Patches written today (tested on mocks, NOT yet applied — apply after live60 ends)

- `patch_ltejam.py` (scenario only): `--lteJam=1 [--lteJamPowerDbm=X]` adds a WaveformGenerator on the
  LTE DL channel at the jammer node, same schedule as the NR jammer (all `&MmWaveEnbPhy::SetJammersActive`
  schedules become `&JgSetAllJammers`). Mock: 4 switches rewired, idempotent, aborts cleanly on a missing
  anchor; C++ passes `g++ -fsyntax-only` against API stubs. Backup `.bak_ltejam`.
  Verified from ns-3.42 source: WaveformGenerator Start/Stop are idempotent, DutyCycle 1.0 = continuous,
  helper takes the node's mobility (moving jammer works), isotropic antenna by default.
- `patch_tri_umin.py` (xApp): `JG_TRI_UMIN` distinct-UE gate (default 0 = off, results reproducible);
  prints `[JGTRI] win W obs M ues U` every window. Mock: with the gate off a fit is published from 2 UEs;
  with `JG_TRI_UMIN=4` only once 4 distinct UEs contribute. Backup `.bak_triu`.

Queued command (waits for live60, applies both, builds `scenario_jam_xapp` and `xapp_jam_guard`) was
given to the user; its output has not been seen yet.

## 5. Plan, in order

1. Live60 result → latency subsection + multi-episode live table.
2. LTE-jam smoke run, then campaign p0 vs p4 with `--lteJam=1` (5 → 15 seeds). If p4 evacuates into the
   jammed anchor, add an **anchor-health guard** (stop LTE evacuation when the anchor is degraded; use NR
   handover + slice cap) and measure again. Report honestly whichever way it goes.
3. Hoffmann et al.'s BLER moving-average **detector** as a ROC row on `jamx_RB` (offline, no new runs).
4. Held-out threshold split on `jamx_D5` (choose Δ, K on half the seeds, report on the rest).
5. Detection-delay vs FA: re-bin `MmWaveJammerRx.txt` to T_r = 10/20/50/100 ms × P = 1/2/3 (needs
   `cat -n ~/roc_replay.py` first). Near-RT cannot detect in < 10 ms by design (that is dApp territory) —
   never claim it; claim the measured trade-off.
6. Scalability: 10/20/40 UEs, decision time and E2 messages per report.
7. Paper text: inconsistencies (5 vs 15 seeds; 3 vs 5 defects; duplicate
   "Statistical significance"; undefined p3; Table V still 10+5), blockage sentence, downlink threat model,
   LTE-not-jammed justification + experiment, rApp/A1 positioning, FL paragraph (training-free, no data
   shared), SON self-healing framing, architecture figure with E2 (+A1) only, related work: Hung 2025
   (E2 anomaly), Soltani BMP 2022, SCOPE, Xavier OpenIreland dataset; do NOT cite the RPL rank-attack paper.
   Table II: add columns "FA under benign impairment", "multi-seed statistics", "measured live E2 latency".
8. Repo + Zenodo.

Note on reviewer comments the user shared: they were for ratti2026 (already accepted) and are a checklist
of what reviewers ask, not obligations. Federated learning / self-healing: answer with a paragraph and the
SON framing; do not build a learned component before submission.
