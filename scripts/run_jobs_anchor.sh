#!/bin/bash
# usage: ~/run_jobs.sh <jobfile> [parallel]
# job line:  run_dir|ns-3 options|environment (VAR=val ...)
# a finished run gets a .done marker and is skipped on restart
J=$1
NP=${2:-10}
NS=~/ns-O-RAN-flexric/mmwave-LENA-oran
B=$(ls $NS/build/scratch/*scenario_jam_anchor*-optimized)
C="--anomalyOn=0"
C="$C --enableE2FileLogging=1"
C="$C --enableTraces=0"
C="$C --cbrMbps=5"
C="$C --jammerDataPath=1"
C="$C --jammerOn=1"
C="$C --embbQuota=1.0"
C="$C --jgLocal=1"
C="$C --jgLoopMs=20"
C="$C --rlcRxSyncOnFirstPdu=0"
export B C
echo "start $(date) jobs=$(grep -c . $J) np=$NP"
grep . $J | xargs -P $NP -I{} bash -c '
 IFS="|" read d o e <<< "{}"
 eval d=$d
 [ -f $d/.done ] && exit 0
 rm -rf $d; mkdir -p $d; cd $d
 env $e $B $C $o > log.txt 2>&1
 x=$?
 [ $x -eq 0 ] && touch .done
 echo "$(date +%T) finished $d exit=$x"'
echo "end $(date)"
