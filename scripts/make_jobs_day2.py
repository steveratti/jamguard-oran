# Next experiment batches, in priority order. Run them after jobs_day.txt finishes, because two of
# them need an ns-3 rebuild and linking a running executable fails.
#
# Before batch 1 and 2, apply the two patches that are still missing in the simulator:
#   cd ~/ns-O-RAN-flexric/mmwave-LENA-oran
#   python3 ~/patch_passive2.py scratch/jamguard_local.h     # guard, so far applied only to the xApp
#   python3 ~/patch_mobile_jammer_xapp.py                    # --jammerVx / --jammerVy
#   ./ns3 build
#
#   ~/jobs_d2a.txt  30 runs: mobile jammer + ablation re-run with the passive guard   (~1.5 h)
#   ~/jobs_d2b.txt  50 runs: seeds 6-15 of the main table at 50 dBm                   (~2.5 h)
# usage: python3 ~/make_jobs_day2.py
import os
H = os.path.expanduser('~')
BASE = '--simTime=14 --militaryUes=2 --ambulanceUes=5 --iotUes=9 --jammerStart=4 --jammerStop=10'
POL = {'p0': '--jgPolicy=0', 'p4': '--jgPolicy=2 --jgSlice=1 --jgSrec=1',
       'p5': '--jgPolicy=5', 'p6': '--jgPolicy=6', 'p7': '--jgPolicy=7'}
V3 = 'JG_SINR_CLIP=35 JG_PRO_MAX=10 JG_MLINK=1 JG_LOC=1 JG_PP_HOLD=30 JG_PASSIVE=1'

def job(d, s, pol, pw=50, extra='', env=''):
    o = '%s --RngRun=%d --jammerPowerDbm=%d %s %s' % (BASE, s, pw, POL[pol], extra)
    return '%s|%s|%s' % (d, ' '.join(o.split()), env)

# ---- batch 1: mobile jammer (ratti2026's declared future work) + ablation re-run ----
a = []
for s in range(1, 6):
    # mobile jammer at 8 and 15 m/s. p0 for the localization replay (no mitigation removes observers),
    # p4 and full v3 for mitigation under a moving jammer.
    a.append(job('%s/jamx_M/p0_v8_s%d' % (H, s), s, 'p0', extra='--jammerVx=-8'))
    a.append(job('%s/jamx_M/p0_v15_s%d' % (H, s), s, 'p0', extra='--jammerVx=-15'))
    a.append(job('%s/jamx_M/p4_v15_s%d' % (H, s), s, 'p4', extra='--jammerVx=-15'))
    a.append(job('%s/jamx_M/v3_v15_s%d' % (H, s), s, 'p4', extra='--jammerVx=-15', env=V3))
    # ablation re-run: the two configurations that the passive-recovery guard changes
    a.append(job('%s/jamx_V3g/v3_passive/pw50_p4_s%d' % (H, s), s, 'p4', env='JG_PASSIVE=1'))
    a.append(job('%s/jamx_V3g/v3_full/pw50_p4_s%d' % (H, s), s, 'p4', env=V3))

# ---- batch 2: seeds 6-15 of the main table, so the headline numbers rest on 15 seeds ----
b = []
for s in range(6, 16):
    for p in ('p0', 'p4', 'p5', 'p6', 'p7'):
        b.append(job('%s/jamx_F2/pw50_%s_s%d' % (H, p, s), s, p))

open(H + '/jobs_d2a.txt', 'w').write('\n'.join(a) + '\n')
open(H + '/jobs_d2b.txt', 'w').write('\n'.join(b) + '\n')
print('jobs_d2a.txt: %d runs (mobile jammer + guarded ablation)' % len(a))
print('jobs_d2b.txt: %d runs (seeds 6-15 of the main table)' % len(b))
print('example:', a[0])
