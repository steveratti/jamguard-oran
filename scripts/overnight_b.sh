#!/bin/bash
# JamGuard overnight: canary patch + build + Scenario A/B campaign (15 seeds) + report
exec > ~/overnight_b.log 2>&1
echo "start $(date)"
NS=~/ns-O-RAN-flexric/mmwave-LENA-oran
if ! grep -q JGCANARY $NS/scratch/jamguard_local.h; then
  python3 ~/patch_canary.py || { echo "PATCH FAILED - stop"; exit 1; }
fi
# canary implies the anchor guard, so each job needs only ONE env variable
grep -q "JGCANARY_IMPLIES" $NS/scratch/jamguard_local.h || sed -i 's|^\(  P_CANARY = (int) envd ("JG_CANARY", P_CANARY);.*\)$|\1\n  if (P_CANARY) P_ANCHOR = 1; /* JGCANARY_IMPLIES */|' $NS/scratch/jamguard_local.h
[ "$(grep -c JGCANARY_IMPLIES $NS/scratch/jamguard_local.h)" -eq 1 ] || { echo "IMPLIES EDIT FAILED - stop"; exit 1; }
cd $NS && cmake --build cmake-cache -j 8 --target scratch_scenario_jam_anchor 2>&1 | grep -E " error|Built target scratch"
BIN=$NS/build/scratch/ns3.42-scenario_jam_anchor-optimized
[ "$(strings $BIN | grep -c 'canary=%d')" -ge 1 ] || { echo "BUILD WITHOUT CANARY - stop"; exit 1; }
J=~/jobs_b15.txt; : > $J
A="--simTime=14 --militaryUes=2 --ambulanceUes=5 --iotUes=9 --jammerStart=4 --jammerStop=10 --jammerPowerDbm=50"
P4="--jgPolicy=2 --jgSlice=1 --jgSrec=1"
for s in $(seq 1 15); do
  echo "$HOME/jamx_LJ/pw50_p0_s$s|$A --RngRun=$s --lteJam=1 --jgPolicy=0|" >> $J
  echo "$HOME/jamx_LJ/pw50_p4_s$s|$A --RngRun=$s --lteJam=1 $P4|" >> $J
  echo "$HOME/jamx_LJ/pw50_p8_s$s|$A --RngRun=$s --lteJam=1 $P4|JG_ANCHOR=1" >> $J
  echo "$HOME/jamx_LJ/pw50_p9_s$s|$A --RngRun=$s --lteJam=1 $P4|JG_CANARY=1" >> $J
  echo "$HOME/jamx_LA/pw50_p8_s$s|$A --RngRun=$s $P4|JG_ANCHOR=1" >> $J
  echo "$HOME/jamx_LA/pw50_p9_s$s|$A --RngRun=$s $P4|JG_CANARY=1" >> $J
done
echo "jobs: $(wc -l < $J)"
cd ~ && ~/run_jobs_anchor.sh $J 5
echo "campaign end $(date)"
{
  echo "######## $(date)"
  echo "=== SCENARIO B: NR + LTE jammed. p0 none | p4 JamGuard | p8 +anchor guard | p9 +canary"
  python3 ~/campaign_report.py ~/jamx_LJ
  echo "=== SCENARIO A: NR only. p8 / p9 with guard (compare with p4 in jamx_F, 15 seeds)"
  python3 ~/campaign_report.py ~/jamx_LA
  echo "=== E60: 4 episodes, 60 s, window 4-50"
  python3 ~/campaign_report.py ~/jamx_E60 4 50
  echo "=== canary verdicts per run (Scenario B / A)"
  for d in ~/jamx_LJ/pw50_p9_s* ~/jamx_LA/pw50_p9_s*; do echo "$d: $(grep -oE 'ANCHOR_(OK|BAD)' $d/jamguard_local.csv 2>/dev/null | sort | uniq -c | tr '\n' ' ')"; done
} > ~/overnight_report.txt 2>&1
echo "all done $(date)"
