# JamGuard v3 campaign (emulated loop inside ns-3, same runner ~/run_jobs.sh)
#   ~/jobs_v3a.txt  priority: v3 ablation (50 dBm) + no-jammer negatives for the ROC          (45 runs)
#   ~/jobs_v3b.txt  then:     eMBB trade-off + recovery / probe back-off with 3 jammer episodes (60 runs)
# usage: python3 ~/make_jobs_v3.py ; nohup ~/run_jobs.sh ~/jobs_v3a.txt 18 > ~/v3a.log 2>&1 &
import os
H = os.path.expanduser('~')
P4 = '--jgPolicy=2 --jgSlice=1 --jgSrec=1'
BASE = '--simTime=14 --militaryUes=2 --ambulanceUes=5 --iotUes=9 --jammerStart=4 --jammerStop=10'
# three 3-s episodes (4-7, 10-13, 16-19 s) to measure time-to-recover and the probe back-off
BASE3 = ('--simTime=22 --militaryUes=2 --ambulanceUes=5 --iotUes=9 --jammerStart=4 --jammerStop=20 '
         '--jammerPeriodMs=6000 --jammerDuty=0.5')
V3 = {   # ablation: each feature alone on top of p4 (v2), then all together
    'v3_clip':    'JG_SINR_CLIP=35 JG_PRO_MAX=10',
    'v3_mlink':   'JG_MLINK=1',
    'v3_loc':     'JG_LOC=1',
    'v3_pp':      'JG_PP_HOLD=30',
    'v3_passive': 'JG_PASSIVE=1',
    'v3_full':    'JG_SINR_CLIP=35 JG_PRO_MAX=10 JG_MLINK=1 JG_LOC=1 JG_PP_HOLD=30 JG_PASSIVE=1',
}
FULL = V3['v3_full']

def job(d, base, s, pol, pw=50, extra='', env=''):
    o = '%s --RngRun=%d --jammerPowerDbm=%d %s %s' % (base, s, pw, pol, extra)
    return '%s|%s|%s' % (d, ' '.join(o.split()), env)

a, b = [], []
for s in range(1, 6):
    for k, e in V3.items():
        a.append(job('%s/jamx_V3/%s/pw50_p4_s%d' % (H, k, s), BASE, s, P4, env=e))
    # negatives: jammer present but at -100 dBm (no effect; keeps all logs), long run, p0 monitor
    a.append(job('%s/jamx_N/pwm100_p0_s%d' % (H, s), BASE.replace('--simTime=14', '--simTime=20')
                 .replace('--jammerStart=4 --jammerStop=10', '--jammerStart=1 --jammerStop=19'),
                 s, '--jgPolicy=0', pw=-100))
    # v3 at low power (30 dBm) and 40 dBm: does v3 still protect without an alarm?
    a.append(job('%s/jamx_V3/v3_full/pw30_p4_s%d' % (H, s), BASE, s, P4, pw=30, env=FULL))
    a.append(job('%s/jamx_V3/v3_full/pw40_p4_s%d' % (H, s), BASE, s, P4, pw=40, env=FULL))

for s in range(1, 6):
    # eMBB trade-off curve: eMBB share in protected NR cells, and eMBB UEs allowed on LTE (p4 default 0.5 / 2)
    for q in (0.3, 0.7, 1.0):
        b.append(job('%s/jamx_E/q%.1f_m2/pw50_p4_s%d' % (H, q, s), BASE, s, P4, env='JG_EMBB_Q=%.1f' % q))
    for m in (1, 3):
        b.append(job('%s/jamx_E/q0.5_m%d/pw50_p4_s%d' % (H, m, s), BASE, s, P4, env='JG_LTE_EMBB_MAX=%d' % m))
    # recovery: 3 episodes; probe hold 10 / 20 / 40 reports, passive recovery, full v3, monitor
    for h in (10, 20, 40):
        b.append(job('%s/jamx_RC/hold%d/pw50_p4_s%d' % (H, h, s), BASE3, s, P4, env='JG_HOLD=%d' % h))
    b.append(job('%s/jamx_RC/passive1/pw50_p4_s%d' % (H, s), BASE3, s, P4, env='JG_PASSIVE=1'))
    b.append(job('%s/jamx_RC/passive2/pw50_p4_s%d' % (H, s), BASE3, s, P4, env='JG_PASSIVE=2'))
    b.append(job('%s/jamx_RC/v3_full/pw50_p4_s%d' % (H, s), BASE3, s, P4, env=FULL))
    b.append(job('%s/jamx_RC/p0/pw50_p0_s%d' % (H, s), BASE3, s, '--jgPolicy=0'))

open(H + '/jobs_v3a.txt', 'w').write('\n'.join(a) + '\n')
open(H + '/jobs_v3b.txt', 'w').write('\n'.join(b) + '\n')
print('jobs_v3a.txt: %d runs   jobs_v3b.txt: %d runs' % (len(a), len(b)))
print('example:', a[5])
