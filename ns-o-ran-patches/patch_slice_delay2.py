# Makes ~/slice_report.py robust to a UE whose cumulative delay counter was poisoned by a
# corrupt SeqTsSizeHeader sample (see patch_delay_guard.py for the cause and the simulator fix).
#
# Such a UE is excluded from the DELAY statistics only; its rx_bytes are untouched, because the
# byte counter is unaffected (rx_bytes min = 0 in every run we scanned). The exclusion is printed,
# never silent, so any number that rests on it can be stated as such in the paper.
#
# If a run was produced by a patched simulator, ue_rx.txt carries a dly_bad column; its total is
# reported too, so the rejected samples are visible even though the counters are already clean.
#
# Requires patch_slice_delay.py to have been applied first (it anchors on its SRFIX block).
# usage: python3 ~/patch_slice_delay2.py
# Idempotent: running it twice changes nothing.
import os, sys, shutil

F = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/slice_report.py')
src = open(F).read()

if 'SRFIX2' in src:
    print('already patched:', F)
    sys.exit(0)
if 'SRFIX' not in src:
    print('ERROR: apply patch_slice_delay.py first:', F)
    sys.exit(1)

ANCHOR = 'w=d[(d.t_s>t0)&(d.t_s<=t1)]'
GUARD = '''_bad=sorted(set(d.loc[d.dly_sum_s<0,"imsi"]))   # SRFIX2: counter poisoned by a corrupt timestamp
if _bad: d.loc[d.imsi.isin(_bad),["d_dly_pkts","d_dly_sum_s"]]=float("nan")
_rej=int(d["dly_bad"].max()) if "dly_bad" in d.columns else 0
'''
if ANCHOR not in src:
    print('ERROR: the window line was not found in', F)
    sys.exit(1)
src = src.replace(ANCHOR, GUARD + ANCHOR, 1)

# extend the header notice written by patch_slice_delay.py
OLDP = ('print(f"{R}  window ({t0},{t1}] s" + '
        '(f"  [{_rst} counter resets absorbed]" if _rst else ""))')
NEWP = ('print(f"{R}  window ({t0},{t1}] s" + '
        '(f"  [{_rst} counter resets absorbed]" if _rst else "") + '
        '(f"  [UEs {_bad} excluded from the delay: corrupt timestamp]" if _bad else "") + '
        '(f"  [{_rej} samples rejected by the simulator]" if _rej else ""))')
if OLDP in src:
    src = src.replace(OLDP, NEWP, 1)
else:
    print('ERROR: the header print line from patch_slice_delay.py was not found')
    sys.exit(1)

shutil.copy2(F, F + '.bak2')
open(F, 'w').write(src)
print('patched:', F, '(backup at %s.bak2)' % F)
