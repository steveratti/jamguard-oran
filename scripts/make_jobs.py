# writes ~/jobs_short.txt (determinism, B1 MCS 6/10, keyed jammer, power profiles)
#    and ~/jobs_hl.txt    (high load, 20 UEs)
# usage: python3 ~/make_jobs.py
import os
H = os.path.expanduser('~')
POL = {'p0': '--jgPolicy=0', 'p2': '--jgPolicy=2', 'p4': '--jgPolicy=2 --jgSlice=1 --jgSrec=1',
       'p5': '--jgPolicy=5', 'p6': '--jgPolicy=6'}
BASE10 = '--simTime=14 --militaryUes=2 --ambulanceUes=5 --iotUes=9 --jammerStart=4 --jammerStop=10'
BASE20 = ('--simTime=14 --N_Ues=20 --militaryUes=2,8,14 --ambulanceUes=5,11,17 --iotUes=9,15,20 '
          '--jammerStart=4 --jammerStop=10')

def job(d, base, pw, s, pol, extra='', env=''):
    o = '%s --RngRun=%d --jammerPowerDbm=%d %s %s' % (base, s, pw, POL[pol], extra)
    return '%s|%s|%s' % (d, ' '.join(o.split()), env)

short = []
# 1) determinism check: identical to jamx_F/pw50_p4_s1 (all new features off)
short.append(job(H + '/jamx_T/pw50_p4_s1', BASE10, 50, 1, 'p4'))
for s in range(1, 6):
    # 2) B1 fairness: MCS cap 6 and 10
    for m in (6, 10):
        short.append(job('%s/jamx_B1/m%d/pw50_p6_s%d' % (H, m, s), BASE10, 50, s, 'p6', env='JG_B1_MCS=%d' % m))
    # 3) keyed jammer, period 10 / 50 / 200 ms, duty 0.5
    for T in (10, 50, 200):
        for p in ('p0', 'p4', 'p6'):
            short.append(job('%s/jamx_P/T%d/pw50_%s_s%d' % (H, T, p, s), BASE10, 50, s, p,
                             '--jammerPeriodMs=%d --jammerDuty=0.5' % T))
    # 4) time-varying power: 1 ramp-up, 3 random, depth 20 dB
    for prof in (1, 3):
        for p in ('p0', 'p4'):
            short.append(job('%s/jamx_R/prof%d/pw50_%s_s%d' % (H, prof, p, s), BASE10, 50, s, p,
                             '--jammerProfile=%d --jammerRampDb=20' % prof))

hl = []
for s in range(1, 6):
    for p in ('p0', 'p2', 'p4', 'p5'):
        hl.append(job('%s/jamx_H/pw50_%s_s%d' % (H, p, s), BASE20, 50, s, p))

open(H + '/jobs_short.txt', 'w').write('\n'.join(short) + '\n')
open(H + '/jobs_hl.txt', 'w').write('\n'.join(hl) + '\n')
print('jobs_short.txt: %d runs   jobs_hl.txt: %d runs' % (len(short), len(hl)))
print('first job:', short[0])
