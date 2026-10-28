# Gate the RSRP recording in the PHY behind JG_RSRP_KPM as well (isolation test / safety).
# patch_rsrp_kpm.py gated the KPM items but not the PHY-side recording, so every run wrote into the static
# map s_lastRsrpDbm. After that build, no campaign run completed (they abort at about t = 1 s), while the
# 45 runs of jobs_v3a, built before it, all finished. This makes the RSRP code the prime suspect, so it is
# now disabled completely unless JG_RSRP_KPM is set:
#   campaign runs (no JG_RSRP_KPM): not one line of RSRP code executes -> if they still abort, RSRP is innocent
#   live runs (JG_RSRP_KPM=1): unchanged behaviour
# Usage: cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_rsrp_gate.py && ./ns3 build
import sys
p = 'src/mmwave/model/mmwave-enb-phy.cc'
t = open(p).read()
if 'JGRSRP3' in t:
    print('already patched'); sys.exit(0)

old = '                s_lastRsrpDbm[imsi][m_cellId] = 10.0 * std::log10(sW > 0 ? sW : 1e-30) + 30.0; // JGRSRP'
n = t.count(old)
assert n == 1, 'anchor found %d times (apply patch_rsrp_kpm.py first)' % n
new = ('                static const bool jgRsrpOn = std::getenv("JG_RSRP_KPM") != nullptr; // JGRSRP3\n'
       '                if (jgRsrpOn)\n'
       '                    s_lastRsrpDbm[imsi][m_cellId] = 10.0 * std::log10(sW > 0 ? sW : 1e-30) + 30.0; // JGRSRP')
t = t.replace(old, new)
if '#include <cstdlib> // JGRSRP3' not in t:
    t = '#include <cstdlib> // JGRSRP3\n' + t
open(p, 'w').write(t)
print(p, ': RSRP recording now also requires JG_RSRP_KPM')
