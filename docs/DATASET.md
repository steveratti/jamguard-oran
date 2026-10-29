# JamGuard dataset (dataset-v1)

Simulation results of the paper *JamGuard: A Slice-Aware Closed-Loop xApp for Jamming Detection,
Localization, and Mitigation in O-RAN* (ns-O-RAN + FlexRIC). One archive per campaign; each run is a
folder named after its configuration, e.g. `pw50_p4_s3` = jammer EIRP 50 dBm, policy p4, seed 3.
Archives larger than 2 GB are split (`*.part_00`, `*.part_01`): join with `cat f.part_* > f`.

| Archive | Paper section / table | Content | Runs | Size |
|---|---|---|---|---|
| jamguard_F.tar.gz | Main results (Table: jamming window), detection (tab:roc), localization (tab:loc), churn | 10 UEs, 40/50 dBm, policies p0 p1 p2 p4 p5(B2) p6(B1), seeds 1-5 (p1, p2 up to 15) | 80 | 359M |
| jamguard_F2.tar.gz | Main results, 15 seeds | seeds 6-15 at 50 dBm of p0, p4, p5 (B2), p6 (B1), p7 (A3) | 50 | 223M |
| jamguard_A3.tar.gz | Mobility cost (A3 baseline) | plain A3 handover, jammer-unaware | 5 | 23M |
| jamguard_N.tar.gz | Detection (attack-free set) | jammer attenuated to -100 dBm, 20 s, 5 runs | 5 | 33M |
| jamguard_D5.tar.gz | Detection vs. spatial clustering (tab:prior), keyed jammer | held-out set: pos40, pos50, neg (attack-free), keyed40, keyed50 | 90 | 386M |
| jamguard_LA.tar.gz | When the escape route is jammed (tab:anchor), Scenario A | NR jammed only; p0 p4 p8 p9, 15 seeds | 30 | 137M |
| jamguard_LJ.tar.gz | When the escape route is jammed (tab:anchor), Scenario B | NR and LTE anchor jammed; p0 p4 p8 p9, 15 seeds | 60 | 270M |
| jamguard_N20.tar.gz | Scaling (tab:scale) | 20 UEs, Scenario A (LA) and B (LJ), 5 seeds | 25 | 228M |
| jamguard_N40.tar.gz | Scaling (tab:scale) | 40 UEs, Scenario A (LA) and B (LJ), 3 seeds | 15 | 269M |
| jamguard_E.tar.gz | Effect of the E2 loop delay; what the slice cap buys | d<ms> = E2 loop delay 10-1000 ms; q<q>_m<L_e> = eMBB quota and eMBB budget on the anchor; p4, 50 dBm, 5 seeds | 55 | 248M |
| jamguard_RC.tar.gz | Recovery tuning, repeated attacks | probe hold (hold10/20/40), passive recovery (passive1/2), full configuration (v3_full), reference p0; 3 attack episodes, 4-20 s, 5 seeds | 35 | 247M |
| jamguard_E60.tar.gz | Repeated attacks, emulated counterpart of the 60 s live run | 60 s, keyed 12 s / 50 %, 4 episodes | 10 | 194M |
| jamguard_V3.tar.gz | Ablation (tab:abl) | refinements on top of p4, 50 dBm, 5 seeds | 40 | 180M |
| jamguard_B1.tar.gz | Baseline B1 and the choice of its cap | MCS cap 6 and 10 | 10 | 45M |
| jamguard_C.tar.gz | Supplementary: earlier power sweep | 30/40/50 dBm, p0-p5, 5 seeds (p3 = intermediate variant, not reported in the paper) | 75 | 313M |
| jamguard_P.tar.gz | Jammer power 30 dBm; keyed jammer | pw30_p0/p4, 15 seeds; T<ms> = keyed jammer, period <ms>, 50 % duty, 50 dBm | 105 | 466M |
| jamguard_R.tar.gz | Detection: time-varying jammer power | prof1 = ramp, prof3 = random EIRP profile | 20 | 90M |
| jamguard_X.tar.gz | Low-power, flooding and combined attacks | low = 20-35 dBm, flood = DL traffic flood without jammer, combo | 60 | 264M |
| jamguard_M.tar.gz | A moving jammer (tab:mobile) | jammer moving at 8 (v8) and 15 (v15) m/s, p0 | 20 | 90M |
| jamguard_T.tar.gz | Live E2 loop: emulated reference run | p4, 50 dBm, seed 1 | 1 | 4.6M |
| jamguard_live.tar.gz | The live E2 loop (FlexRIC): validation, latency, live Scenario A/B, canary | val_p4, live60, liveB_p4, liveB_p9 (first canary, defect), liveB_p9b, liveA_p9 | 11 | 81M |

## Files in a run folder
| File | Content |
|---|---|
| ue_rx.txt | per UE, every 100 ms: time, IMSI, cumulative received bytes, delay samples, delay sum |
| pkt_delay.txt | per-packet one-way delay (tail latency, deadlines) |
| jamguard_local.csv | emulated-loop decisions: time, event, UE, from/to cell, SINR, drop, position, jammer estimate and zone |
| jamguard_log.csv, xapp.txt | live xApp decisions (same columns, report time first) and console log |
| kpm_dump.csv, jg_latency.csv, e2_ctrl_rx.csv | live runs: every KPM item received over E2, per-step loop latency, control messages received by the RAN |
| MmWaveSinrTime.txt, MmWaveJammerRx.txt | per UE and cell, every 1 ms: SINR; signal, jammer and noise power (jammer power = ground truth only) |
| jammer.txt | ground truth: position, EIRP, on/off, seed, start/stop, keyed period and duty |
| ue_position.txt | UE positions, every 100 ms |
| cu-cp-cell-*.txt, cu-up-cell-*.txt, du-cell-*.txt | E2SM-KPM reports logged per cell (cell 1 = LTE anchor) |
| log.txt | simulator log, including the JamGuard parameters of the run |

Removed to save space (not used by any analysis): X2Stats, RlcAmBufferSize, PHY/HARQ/RX packet traces.
Code, ns-O-RAN patches and analysis scripts: https://github.com/steveratti/jamguard-oran
