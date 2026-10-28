# JamGuard library patch 2 (apply ONLY after the running campaigns finish)
#  A) time-varying jammer power: MmWaveEnbPhy::SetJammerPowerOffsetDb (dB offset added to the
#     EIRP of every registered jammer) + scenario options --jammerProfile / --jammerRampDb
#       profile 0 fixed (default, unchanged), 1 ramp-up (-R dB -> 0), 2 ramp-down (0 -> -R dB),
#       3 random (uniform in [-R, 0] dB, redrawn every 100 ms, ns-3 seeded)
#  B) per-UE downlink HARQ ACK/NACK counters in the gNB MAC, written every 100 ms to
#     DlHarqStats.txt (t_s cell rnti ack nack) -> BLER and E[attempts] KPI
# Usage:  cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_lib2.py
import sys

def patch(path, edits, tag):
    t = open(path).read()
    if tag in t:
        print(path, ': already patched'); return
    for a, b in edits:
        n = t.count(a)
        assert n == 1, '%s: anchor found %d times: %s' % (path, n, a[:70])
        t = t.replace(a, b)
    open(path, 'w').write(t)
    print(path, ': patched')

# ---------------- A1) mmwave-enb-phy.h : public setter ----------------
patch('src/mmwave/model/mmwave-enb-phy.h', [
    ('static void SetJammersActive(bool on);',
     'static void SetJammersActive(bool on);\n'
     '    // JAMMER PATCH (JamGuard): dB offset added to the EIRP of every jammer (time-varying power)\n'
     '    static void SetJammerPowerOffsetDb(double db);'),
], 'SetJammerPowerOffsetDb')

# ---------------- A2) mmwave-enb-phy.cc : offset applied everywhere ----------------
p = 'src/mmwave/model/mmwave-enb-phy.cc'
t = open(p).read()
if 'g_jamOffsetDb' not in t:
    a = 'bool MmWaveEnbPhy::s_jammersActive = true;'
    assert t.count(a) == 1, 'anchor s_jammersActive'
    t = t.replace(a, a + '''
static double g_jamOffsetDb = 0.0; // JAMMER PATCH (JamGuard): time-varying jammer power

void
MmWaveEnbPhy::SetJammerPowerOffsetDb(double db)
{
    g_jamOffsetDb = db;
}''')
    n = t.count('jam.txPowerDbm')
    assert n >= 1, 'jam.txPowerDbm not found'
    t = t.replace('jam.txPowerDbm', '(jam.txPowerDbm + g_jamOffsetDb)')
    open(p, 'w').write(t)
    print(p, ': patched, offset applied at', n, 'place(s) (expect 2: data path + SINR)')
else:
    print(p, ': already patched')

# ---------------- B) mmwave-enb-mac.cc : HARQ counters ----------------
p = 'src/mmwave/model/mmwave-enb-mac.cc'
t = open(p).read()
if 'DlHarqStats' not in t:
    t = '#include <fstream>\n#include <map>\n' + t
    a = 'if (params.m_harqStatus == DlHarqInfo::ACK)'
    assert t.count(a) == 1, 'anchor ACK'
    t = t.replace(a, '''{
        /* JamGuard: per-UE DL HARQ ACK/NACK counters, flushed every 100 ms to DlHarqStats.txt */
        static std::ofstream s_jgHarq;
        static std::map<std::pair<uint16_t, uint16_t>, std::pair<uint32_t, uint32_t>> s_jgCnt;
        static double s_jgLast = 0.0;
        auto& c = s_jgCnt[std::make_pair(m_cellId, params.m_rnti)];
        if (params.m_harqStatus == DlHarqInfo::ACK) c.first++; else c.second++;
        double now = Simulator::Now().GetSeconds();
        if (now - s_jgLast >= 0.1)
        {
            if (!s_jgHarq.is_open())
            {
                s_jgHarq.open("DlHarqStats.txt", std::ios_base::out | std::ios_base::trunc);
                s_jgHarq << "t_s cell rnti ack nack" << std::endl;
            }
            for (auto& e : s_jgCnt)
                if (e.second.first + e.second.second > 0)
                    s_jgHarq << now << " " << e.first.first << " " << e.first.second << " "
                             << e.second.first << " " << e.second.second << "\\n";
            s_jgHarq.flush();
            s_jgCnt.clear();
            s_jgLast = now;
        }
    }
    ''' + a, 1)
    open(p, 'w').write(t)
    print(p, ': patched (DlHarqStats.txt)')
else:
    print(p, ': already patched')

# ---------------- A3) scenario : --jammerProfile / --jammerRampDb ----------------
patch('scratch/scenario_jam_xapp.cc', [
    ('cmd.AddValue ("jammerStop", "Jammer switch-off time [s] (>= simTime: never)", jammerStop);',
     'cmd.AddValue ("jammerStop", "Jammer switch-off time [s] (>= simTime: never)", jammerStop);\n'
     '  uint32_t jammerProfile = 0; double jammerRampDb = 20.0; // JamGuard: time-varying power\n'
     '  cmd.AddValue ("jammerProfile", "Jammer power profile: 0 fixed, 1 ramp-up, 2 ramp-down, 3 random", jammerProfile);\n'
     '  cmd.AddValue ("jammerRampDb", "Depth of the power profile [dB] (EIRP varies in [EIRP-R, EIRP])", jammerRampDb);'),
    ('NS_LOG_UNCOND ("Jammer ON at (" << jammerX << ", " << jammerY << ") EIRP " << jammerPowerDbm << " dBm");',
     'NS_LOG_UNCOND ("Jammer ON at (" << jammerX << ", " << jammerY << ") EIRP " << jammerPowerDbm << " dBm");\n'
     '''      if (jammerProfile > 0 && jammerStop > jammerStart)
        {
          /* JamGuard: time-varying jammer power, updated every 100 ms */
          Ptr<UniformRandomVariable> jr = CreateObject<UniformRandomVariable> ();
          for (double ts = jammerStart; ts < jammerStop - 1e-9; ts += 0.1)
            {
              double f = (ts - jammerStart) / (jammerStop - jammerStart);
              double off = jammerProfile == 1 ? -jammerRampDb * (1.0 - f)
                         : jammerProfile == 2 ? -jammerRampDb * f
                         : -jr->GetValue (0.0, jammerRampDb);
              Simulator::Schedule (Seconds (ts), &MmWaveEnbPhy::SetJammerPowerOffsetDb, off);
            }
          Simulator::Schedule (Seconds (jammerStop), &MmWaveEnbPhy::SetJammerPowerOffsetDb, 0.0);
          NS_LOG_UNCOND ("Jammer power profile " << jammerProfile << ", depth " << jammerRampDb << " dB");
        }'''),
], 'jammerProfile')

print('done. Build later with: ./ns3 build')
