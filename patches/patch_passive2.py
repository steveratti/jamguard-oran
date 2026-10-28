# JamGuard: passive recovery guard (fixes a premature recovery seen in the v3 ablation)
# Ablation seed 4 (50 dBm): PASSIVE_OK at 5.6 s while the jammer ran 4-10 s. Two evacuated UEs saw their
# NR neighbour at >= 10 dB because that cell is far from the jammer, and n_deg was 0 because every degraded
# UE had already been evacuated, so nothing guarded the decision. Result: all UEs returned into the jammer,
# a second DETECT, and military delivery 95.8 +- 8.4 % instead of 99.4 +- 0.4 %.
# Three guards, same shape as the probe back-off:
#   1. passive recovery is allowed only after the hold has expired (r >= next_probe, set on every evacuation)
#   2. a majority of the evacuated UEs must see a good NR link, not just two
#   3. if the alarm comes back while UEs are returning, the hold doubles (exponential back-off)
# Usage (run twice, once per file):
#   cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_passive2.py scratch/jamguard_local.h && ./ns3 build
#   cd ~/flexric/examples/xApp/c/orange && python3 ~/patch_passive2.py xapp_jam_guard.c
import sys
p = sys.argv[1] if len(sys.argv) > 1 else 'scratch/jamguard_local.h'
t = open(p).read()
if 'JGPASS2' in t:
    print('already patched'); sys.exit(0)

def rep(a, b):
    global t
    n = t.count(a)
    assert n == 1, 'anchor found %d times: %s' % (n, a[:90])
    t = t.replace(a, b)

if p.endswith('.h'):          # emulated loop (ns-3)
    assert 'JGV3' in t, 'apply patch_v3_local.py first'
    rep('  if (P_PASSIVE && probe < 0 && !returning && n_lte > 0)',
        '  if (P_PASSIVE && probe < 0 && !returning && n_lte > 0 && r >= next_probe) /* JGPASS2 hold */')
    rep('      int need = n_lte < 2 ? n_lte : 2, okn = 0;',
        '      int need = n_lte < 2 ? n_lte : 2, okn = 0;\n'
        '      if (need < (n_lte + 1) / 2) need = (n_lte + 1) / 2; /* JGPASS2 majority of evacuated UEs */')
    rep('      if (alarm_) returning = 0;',
        '      if (alarm_)\n'
        '        { /* JGPASS2: recovery was wrong, back off before trying again */\n'
        '          returning = 0;\n'
        '          hold = (2 * hold > P_HOLD_MAX) ? P_HOLD_MAX : 2 * hold;\n'
        '          next_probe = r + hold;\n'
        '          logev (r, "RECOVER_FAIL", 0, 0, 0, "jammer still on after recovery, backing off");\n'
        '        }')
else:                          # live xApp (FlexRIC)
    assert 'JGV3' in t, 'apply patch_v3_xapp.py first'
    rep('  if (P_PASSIVE && jg_probe < 0 && !jg_returning && n_lte > 0) {',
        '  if (P_PASSIVE && jg_probe < 0 && !jg_returning && n_lte > 0 && r >= jg_next_probe) { /* JGPASS2 hold */')
    rep('    int const need = n_lte < 2 ? n_lte : 2;',
        '    int need = n_lte < 2 ? n_lte : 2;\n'
        '    if (need < (n_lte + 1) / 2) need = (n_lte + 1) / 2; /* JGPASS2 majority of evacuated UEs */')
    rep('    if (jg_alarm) jg_returning = 0;  /* jammer back: stop returning, step 4 takes over */',
        '''    if (jg_alarm) { /* JGPASS2: recovery was wrong, back off before trying again */
      jg_returning = 0;
      jg_hold = (2 * jg_hold > P_HOLD_MAX) ? P_HOLD_MAX : 2 * jg_hold;
      jg_next_probe = r + jg_hold;
      jg_logev(r, "RECOVER_FAIL", 0, 0, 0, "jammer still on after recovery, backing off");
    }''')

open(p, 'w').write(t)
print(p, ': passive recovery guarded (hold, majority of evacuated UEs, back-off on a wrong recovery)')
