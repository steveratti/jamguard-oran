#!/bin/bash
[ -n "$1" ] || { echo "usage: live_val.sh <name> [VAR=val ...]"; exit 1; }
D=$HOME/jamx_live/$1; shift
rm -rf "$D"; mkdir -p "$D"; cd "$D" || exit 1
B=$(ls ~/ns-O-RAN-flexric/mmwave-LENA-oran/build/scratch/*scenario_jam_xapp*-optimized)
X=$(find ~/flexric/build -name xapp_jam_guard -type f | head -1)
~/flexric/build/examples/ric/nearRT-RIC > ric.txt 2>&1 & RIC=$!
sleep 3
JG_RSRP_KPM=1 $B --anomalyOn=0 --enableE2FileLogging=0 --e2TermIp=127.0.0.1 --e2HoViaAnchor=1 \
  --indicationPeriodicity=0.1 --enableTraces=0 --cbrMbps=5 --jammerDataPath=1 --jammerOn=1 --jgLocal=0 \
  --simTime=14 --jammerStart=4 --jammerStop=10 --RngRun=1 --jammerPowerDbm=50 \
  --militaryUes=2 --ambulanceUes=5 --iotUes=9 $NS_ARGS > log.txt 2>&1 & NS=$!
sleep 5
env JG_POLICY=2 JG_SLICE=1 JG_SREC=1 JG_SLICES="2:1,5:2,9:3" JG_POS="$D/ue_position.txt" JG_POS_COLS=1,2,3 \
  JG_KPM_DUMP=kpm_dump.csv JG_LAT=jg_latency.csv "$@" $X > xapp.txt 2>&1 & XA=$!
wait $NS; echo "ns-3 exit $?"
sleep 2; kill $XA $RIC 2>/dev/null
wc -l jamguard_log.csv e2_ctrl_rx.csv jg_latency.csv
