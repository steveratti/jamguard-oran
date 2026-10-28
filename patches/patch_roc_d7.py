# D7: separate the two decisions a closed-loop xApp actually makes.
#
# The measurements say two different things. The multi-link test raises the alarm perfectly
# (Pd 1.00, no false alarm over the benign time) but identifies only 0.42 of the jammed UE-rounds.
# The MCS drop identifies 0.59 of them -- the best of any indicator here -- but its own alarm is
# useless, because mobility moves the modulation all the time (10.3 false alarms per minute).
#
# They are answering different questions. The alarm answers WHETHER to act, and must be specific,
# because acting without a jammer costs handovers. The per-UE flag answers WHOM to move, and must
# be sensitive, because a jammed UE that is not flagged is not protected. D7 therefore takes the
# alarm from the multi-link test and the per-UE flag from either indicator, with the MCS consulted
# only while the alarm is up. The gate is what makes the MCS usable: its false flags can only
# occur during an alarm, and the alarm is raised only when a jammer is present.
#
# usage: python3 patch_roc_d7.py [path to roc_replay.py]   (apply after patch_roc_mcs.py)
import os, sys, shutil

F = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/roc_replay.py')
s = open(F).read()
if 'ROCD7' in s:
    print('already patched'); sys.exit(0)
if 'ROCMCS' not in s:
    sys.exit('ERROR: apply patch_roc_mcs.py first')

def need(ok, what):
    if not ok:
        sys.exit('ERROR: anchor not found: %s\n--- nothing changed.' % what)

A = "DET = list(DET) + [x for x in ('D5', 'D6') if x not in DET]   # ROCMCS"
need(s.count(A) == 1, 'the DET extension')
s = s.replace(A, A + "\nDET = list(DET) + ['D7']   # ROCD7", 1)

# a second per-UE counter, so the alarm and the attribution can differ
A = "    mbase = {}   # ROCMCS: per-UE MCS baseline, reset on handover like the SINR one"
need(s.count(A) == 1, 'the mbase line')
s = s.replace(A, A + "\n    cntA = defaultdict(int)   # ROCD7: counter that drives the alarm", 1)

A = """            if det == 'D6':   # ROCMCS: SINR drop, confirmed by the multi-link test or by the MCS"""
need(s.count(A) == 1, 'the D6 branch')
D7 = '''            degA = deg   # ROCD7: by default the alarm and the per-UE flag are the same test
            if det == 'D7':
                degs = s < S_LOW and b[0] - s >= drop
                ml = False
                if degs:
                    dd = sorted(nbase[u][c] - m[c][1] for c in m if c != srv and c in nbase[u])
                    if dd:
                        med = dd[len(dd) // 2] if len(dd) % 2 else 0.5 * (dd[len(dd) // 2 - 1] + dd[len(dd) // 2])
                        ml = med >= drop / 2
                degA = degs and ml                      # alarm: specific, as in D2
                deg = degA or (alarm and degm)          # attribution: sensitive, gated by the alarm
'''
s = s.replace(A, D7 + A, 1)

A = """            if cnt[u] > 0:
                ndeg += 1"""
need(s.count(A) == 1, 'the ndeg accumulation')
s = s.replace(A, """            cntA[u] = cntA[u] + 1 if degA else 0   # ROCD7
            if (cntA[u] if det == 'D7' else cnt[u]) > 0:
                ndeg += 1""", 1)

shutil.copy2(F, F + '.bak_d7')
open(F, 'w').write(s)
print('patched:', F, '(backup at %s.bak_d7)' % F)
print('new detector: D7 (alarm from the multi-link test, per-UE flag from either indicator)')
