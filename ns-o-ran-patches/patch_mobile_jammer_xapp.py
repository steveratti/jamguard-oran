# Mobile jammer for scratch/scenario_jam_xapp.cc (future work of ratti2026: "mobile jammers, which require a
# sliding-window or predictive localization stage")
#   --jammerVx, --jammerVy [m/s]: the jammer moves with constant velocity while it is ON (jammerStart..jammerStop)
#                                 and stands still otherwise. Default 0 0 = static jammer, exactly as before.
#   jammer_track.txt (t_s,x,y every 100 ms) is written only for a moving jammer; loc_replay.py uses it as
#   ground truth. jammer.txt keeps its format (initial position).
# The jammer model (MmWaveEnbPhy::AddJammer) reads the jammer position from its MobilityModel at every
# SINR computation, so a moving MobilityModel is enough; no library change is needed.
# Usage: cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && cp scratch/scenario_jam_xapp.cc scratch/scenario_jam_xapp.cc.static \
#        && python3 ~/patch_mobile_jammer_xapp.py && ./ns3 build
import sys
p = sys.argv[1] if len(sys.argv) > 1 else 'scratch/scenario_jam_xapp.cc'
t = open(p).read()
if 'JGMOB' in t:
    print('already patched'); sys.exit(0)

def rep(a, b):
    global t
    n = t.count(a)
    assert n == 1, 'anchor found %d times: %s' % (n, a[:90])
    t = t.replace(a, b)

rep('static ns3::GlobalValue g_handoverMode (', '''#include "ns3/constant-velocity-mobility-model.h" /* JGMOB */
#include <fstream>
static std::ofstream g_jtrack;                       /* JGMOB jammer ground-truth track */
static ns3::Ptr<ns3::MobilityModel> g_jmob;
static void JgTrack ()
{
  ns3::Vector q = g_jmob->GetPosition ();
  g_jtrack << ns3::Simulator::Now ().GetSeconds () << "," << q.x << "," << q.y << std::endl;
  ns3::Simulator::Schedule (ns3::MilliSeconds (100), &JgTrack);
}
static void JgTrackStart (ns3::Ptr<ns3::MobilityModel> m)
{
  g_jmob = m;
  g_jtrack.open ("jammer_track.txt", std::ios_base::out | std::ios_base::trunc);
  g_jtrack << "t_s,x,y" << std::endl;
  ns3::Simulator::Schedule (ns3::Seconds (0), &JgTrack);
}

static ns3::GlobalValue g_handoverMode (''')
rep('  double jammerX = 710.0, jammerY = 510.0, jammerZ = 1.5, jammerPowerDbm = 50.0;',
    '  double jammerX = 710.0, jammerY = 510.0, jammerZ = 1.5, jammerPowerDbm = 50.0;\n'
    '  double jammerVx = 0.0, jammerVy = 0.0; // JGMOB')
rep('  cmd.AddValue ("jammerY", "Jammer y [m]", jammerY);',
    '  cmd.AddValue ("jammerY", "Jammer y [m]", jammerY);\n'
    '  cmd.AddValue ("jammerVx", "Mobile jammer: x velocity while ON [m/s] (0 = static)", jammerVx); // JGMOB\n'
    '  cmd.AddValue ("jammerVy", "Mobile jammer: y velocity while ON [m/s] (0 = static)", jammerVy);')
rep('  jMob.SetMobilityModel ("ns3::ConstantPositionMobilityModel");',
    '  if (jammerVx != 0.0 || jammerVy != 0.0) // JGMOB\n'
    '    jMob.SetMobilityModel ("ns3::ConstantVelocityMobilityModel");\n'
    '  else\n'
    '    jMob.SetMobilityModel ("ns3::ConstantPositionMobilityModel");')
rep('      MmWaveEnbPhy::AddJammer (jammerNode.Get (0)->GetObject<MobilityModel> (), jammerPowerDbm, jPl);',
    '''      MmWaveEnbPhy::AddJammer (jammerNode.Get (0)->GetObject<MobilityModel> (), jammerPowerDbm, jPl);
      {
        /* JGMOB: the jammer moves only while it is ON */
        Ptr<ConstantVelocityMobilityModel> cv = jammerNode.Get (0)->GetObject<ConstantVelocityMobilityModel> ();
        if (cv)
          {
            cv->SetVelocity (Vector (0, 0, 0));
            Simulator::Schedule (Seconds (jammerStart), &ConstantVelocityMobilityModel::SetVelocity, cv,
                                 Vector (jammerVx, jammerVy, 0));
            Simulator::Schedule (Seconds (jammerStop), &ConstantVelocityMobilityModel::SetVelocity, cv,
                                 Vector (0, 0, 0));
            JgTrackStart (jammerNode.Get (0)->GetObject<MobilityModel> ());
            NS_LOG_UNCOND ("Mobile jammer: velocity (" << jammerVx << ", " << jammerVy << ") m/s from "
                           << jammerStart << " s to " << jammerStop << " s");
          }
      }''')
open(p, 'w').write(t)
print(p, ': mobile jammer added (--jammerVx --jammerVy), default static')
