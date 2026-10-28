#!/usr/bin/env python3
"""JGLTEJAM: optional jammer on the LTE anchor's downlink carrier (scenario only, no library change).
--lteJam=1 adds a WaveformGenerator at the jammer node on the LTE DL spectrum channel, same EIRP
(--lteJamPowerDbm, default = --jammerPowerDbm) spread over the LTE DL bandwidth. It is switched with
the NR jammer, so the constant, keyed and multi-episode schedules apply to both carriers."""
import re, shutil, sys, os
p = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/ns-O-RAN-flexric/mmwave-LENA-oran/scratch/scenario_jam_xapp.cc")
s = open(p).read()
if "JGLTEJAM" in s:
    print("already patched"); sys.exit(0)

A_MAIN = "int\nmain (int argc, char *argv[])"
A_FLAG = 'cmd.AddValue ("jammerDuty", "Keyed jammer: fraction of each period the jammer is on (0..1)", jammerDuty);'
A_ATT = "  mmwaveHelper->AttachToClosestEnb (mcUeDevs, mmWaveEnbDevs, lteEnbDevs);"
A_SCH = "&MmWaveEnbPhy::SetJammersActive,"
for name, a, want in (("main", A_MAIN, 1), ("flag", A_FLAG, 1), ("attach", A_ATT, 1)):
    n = s.count(a)
    if n != want:
        sys.exit("anchor %s found %d times, expected %d -- nothing changed" % (name, n, want))
nsch = s.count(A_SCH)
if nsch < 2:
    sys.exit("expected >= 2 scheduled SetJammersActive calls, found %d -- nothing changed" % nsch)
first_inc = re.search(r'^#include "ns3/[^"]+"\s*$', s, re.M)
if not first_inc:
    sys.exit("no ns3 include found -- nothing changed")

inc = ('\n#include "ns3/waveform-generator-helper.h"   // JGLTEJAM\n'
       '#include "ns3/waveform-generator.h"\n'
       '#include "ns3/non-communicating-net-device.h"\n'
       '#include "ns3/lte-spectrum-value-helper.h"\n'
       '#include "ns3/lte-enb-net-device.h"\n'
       '#include "ns3/lte-enb-phy.h"\n'
       '#include "ns3/lte-spectrum-phy.h"\n')
fn = ('/* JGLTEJAM: the LTE-anchor jammer follows the NR jammer on/off schedule */\n'
      'static Ptr<WaveformGenerator> g_jgLteJam;\n'
      'static bool g_jgLteJamOn = false;\n'
      'static void\n'
      'JgSetAllJammers (bool on)\n'
      '{\n'
      '  MmWaveEnbPhy::SetJammersActive (on);\n'
      '  if (g_jgLteJam && on != g_jgLteJamOn)\n'
      '    {\n'
      '      if (on) g_jgLteJam->Start (); else g_jgLteJam->Stop ();\n'
      '      g_jgLteJamOn = on;\n'
      '    }\n'
      '}\n\n')
flag = (A_FLAG + '\n'
        '  bool lteJam = false; double lteJamPowerDbm = -1e9; // JGLTEJAM\n'
        '  cmd.AddValue ("lteJam", "Also jam the LTE anchor DL carrier (same position and schedule)", lteJam);\n'
        '  cmd.AddValue ("lteJamPowerDbm", "EIRP of the LTE-anchor jammer [dBm] (default: jammerPowerDbm)", lteJamPowerDbm);')
blk = (A_ATT + '\n'
       '  if (jammerOn && lteJam) // JGLTEJAM\n'
       '    {\n'
       '      Ptr<LteEnbNetDevice> lteEnb = lteEnbDevs.Get (0)->GetObject<LteEnbNetDevice> ();\n'
       '      NS_ABORT_MSG_IF (!lteEnb, "lteJam: LTE anchor is not an LteEnbNetDevice");\n'
       '      Ptr<SpectrumChannel> lteDl = lteEnb->GetPhy ()->GetDownlinkSpectrumPhy ()->GetChannel ();\n'
       '      NS_ABORT_MSG_IF (!lteDl, "lteJam: no LTE DL spectrum channel");\n'
       '      uint32_t const earfcn = lteEnb->GetDlEarfcn ();\n'
       '      uint8_t const nRb = lteEnb->GetDlBandwidth ();\n'
       '      double const pw = (lteJamPowerDbm > -1e8) ? lteJamPowerDbm : jammerPowerDbm;\n'
       '      std::vector<int> rbs;\n'
       '      for (int k = 0; k < nRb; ++k) rbs.push_back (k);\n'
       '      WaveformGeneratorHelper wg;\n'
       '      wg.SetChannel (lteDl);\n'
       '      wg.SetTxPowerSpectralDensity (LteSpectrumValueHelper::CreateTxPowerSpectralDensity (earfcn, nRb, pw, rbs));\n'
       '      wg.SetPhyAttribute ("Period", TimeValue (MilliSeconds (1)));\n'
       '      wg.SetPhyAttribute ("DutyCycle", DoubleValue (1.0));\n'
       '      NetDeviceContainer jd = wg.Install (jammerNode.Get (0));\n'
       '      g_jgLteJam = jd.Get (0)->GetObject<NonCommunicatingNetDevice> ()->GetPhy ()->GetObject<WaveformGenerator> ();\n'
       '      NS_ABORT_MSG_IF (!g_jgLteJam, "lteJam: WaveformGenerator not created");\n'
       '      if (jammerStart <= 0)\n'
       '        Simulator::ScheduleNow (&JgSetAllJammers, true);\n'
       '      NS_LOG_UNCOND ("JGLTEJAM: LTE anchor jammer EARFCN " << earfcn << ", " << (int) nRb\n'
       '                     << " RBs, " << pw << " dBm, same schedule as the NR jammer");\n'
       '    }')
s = s[:first_inc.end()] + inc + s[first_inc.end():]
s = s.replace(A_MAIN, fn + A_MAIN, 1)
s = s.replace(A_FLAG, flag, 1)
s = s.replace(A_ATT, blk, 1)
s = s.replace(A_SCH, "&JgSetAllJammers,")
bak = p + ".bak_ltejam"
if not os.path.exists(bak):
    shutil.copy(p, bak)
open(p, "w").write(s)
print("patched %s: %d scheduled jammer switches now drive both carriers; backup %s" % (p, nsch, bak))
