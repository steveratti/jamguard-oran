# Fixes the cumulative-counter reset bug in ~/slice_report.py.
#
# ue_rx.txt carries CUMULATIVE counters (rx_bytes, dly_pkts, dly_sum_s). When the data path of a
# UE is moved (LTE fallback, NR handover) the sink is recreated and those counters restart at 0,
# so the plain .diff() of the old line 13 produced one large NEGATIVE increment per move. Summed
# over a window this can make the delay, the throughput and the delivery ratio negative, which is
# what produced the -3416 ms eMBB delay in the 22 s recovery runs.
#
# A reset is detected as a negative difference; the increment for that sample is then the new
# cumulative value itself. The script also prints how many resets it absorbed, so a run whose
# numbers depend on this correction is visible rather than silent.
#
# usage: python3 ~/patch_slice_delay.py            # patches ~/slice_report.py in place
#        python3 ~/patch_slice_delay.py <file>
# Idempotent: running it twice changes nothing.
import os, sys, shutil

F = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/slice_report.py')
src = open(F).read()

OLD = 'for c in ("rx_bytes","dly_pkts","dly_sum_s"): d["d_"+c]=d.groupby("imsi")[c].diff()'
NEW = ('_rst=0  # SRFIX: cumulative counters restart at 0 when a UE data path is moved\n'
       'for c in ("rx_bytes","dly_pkts","dly_sum_s"):\n'
       '    _v=d.groupby("imsi")[c].diff()\n'
       '    _rst+=int((_v<0).sum())\n'
       '    d["d_"+c]=_v.where(_v>=0, d[c])')

if 'SRFIX' in src:
    print('already patched:', F)
    sys.exit(0)
if OLD not in src:
    print('ERROR: line 13 not found as expected in', F)
    print('       expected exactly:')
    print('      ', OLD)
    sys.exit(1)

src = src.replace(OLD, NEW, 1)

# report the absorbed resets next to the window line, so the correction is never silent
OLDP = 'print(f"{R}  window ({t0},{t1}] s")'
NEWP = 'print(f"{R}  window ({t0},{t1}] s" + (f"  [{_rst} counter resets absorbed]" if _rst else ""))'
if OLDP in src:
    src = src.replace(OLDP, NEWP, 1)
else:
    print('warning: could not add the reset notice to the header line')

shutil.copy2(F, F + '.bak')
open(F, 'w').write(src)
print('patched:', F, '(backup at %s.bak)' % F)
