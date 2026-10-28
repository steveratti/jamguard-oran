# ns-O-RAN library extension (JamGuard): RSRP-like received signal power in the E2SM-KPM CU-CP report
# Stock ns-O-RAN reports only the L3 SINR of the serving and neighbour cells. The SINR alone cannot separate
# a jammer from the UE's own path-loss change (SINR-only trilateration: 152 m error, with RSRP: 41 m).
#   1) MmWaveEnbPhy keeps, per UE and NR cell, the last wideband received signal power S [dBm] that the
#      jammer patch already computes for the DL SINR (same quantity as S_dBm in MmWaveJammerRx.txt).
#   2) MmWaveEnbNetDevice adds, per UE, one KPM item per NR cell in its L3 report:
#        L3servingRSRP_cell_<c>_UEID_<imsi>   and   L3neighRSRP_cell_<c>_UEID_<imsi>     (value in dBm)
#      only when the environment variable JG_RSRP_KPM is set (default: report unchanged, old runs identical).
# Usage: cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_rsrp_kpm.py && ./ns3 build
import sys

def edit(path, pairs, tag, allow_multi=()):
    t = open(path).read()
    if tag in t:
        print(path, ': already patched'); return
    for a, b in pairs:
        n = t.count(a)
        ok = n >= 1 if a in allow_multi else n == 1
        assert ok, '%s: anchor found %d times: %s' % (path, n, a[:80])
        t = t.replace(a, b)
    open(path, 'w').write(t)
    print(path, ': patched')

edit('src/mmwave/model/mmwave-enb-phy.h', [
    ('    static void ClearJammers();', '''    static void ClearJammers();
    // JGRSRP: last wideband received signal power [dBm] per UE and NR cell (NaN if unknown)
    static double GetLastRsrpDbm(uint64_t imsi, uint16_t cellId);
    static std::map<uint64_t, std::map<uint16_t, double>> s_lastRsrpDbm;'''),
], 'JGRSRP')

edit('src/mmwave/model/mmwave-enb-phy.cc', [
    ('std::vector<MmWaveEnbPhy::JammerInfo> MmWaveEnbPhy::s_jammers;', '''std::vector<MmWaveEnbPhy::JammerInfo> MmWaveEnbPhy::s_jammers;
std::map<uint64_t, std::map<uint16_t, double>> MmWaveEnbPhy::s_lastRsrpDbm; // JGRSRP
double
MmWaveEnbPhy::GetLastRsrpDbm(uint64_t imsi, uint16_t cellId)
{
    auto a = s_lastRsrpDbm.find(imsi);
    if (a == s_lastRsrpDbm.end())
        return std::nan("");
    auto b = a->second.find(cellId);
    return b == a->second.end() ? std::nan("") : b->second;
}'''),
    ('                double sW = Integral(dlSignal);', '''                double sW = Integral(dlSignal);
                s_lastRsrpDbm[imsi][m_cellId] = 10.0 * std::log10(sW > 0 ? sW : 1e-30) + 30.0; // JGRSRP'''),
], 'JGRSRP')

edit('src/mmwave/model/mmwave-enb-net-device.cc', [
    ('      // For the neighbors\n      // TODO create double map, imsi -> cell -> sinr', '''      /* JGRSRP: RSRP-like received power of the serving and neighbour NR cells (JG_RSRP_KPM set) */
      static const bool jgRsrpKpm = std::getenv ("JG_RSRP_KPM") != nullptr;
      if (jgRsrpKpm)
        for (auto &jgc : m_l3sinrMap[imsi])
          {
            double jgS = MmWaveEnbPhy::GetLastRsrpDbm (imsi, jgc.first);
            if (std::isnan (jgS))
              continue;
            std::string jgName = std::string (jgc.first == m_cellId ? "L3servingRSRP" : "L3neighRSRP") +
                                 "_cell_" + std::to_string (jgc.first) + "_UEID_" + std::to_string (imsi);
            ueVal->AddItem<double> (jgName, jgS);
          }

      // For the neighbors
      // TODO create double map, imsi -> cell -> sinr'''),
], 'JGRSRP', allow_multi=('      // For the neighbors\n      // TODO create double map, imsi -> cell -> sinr',))

t = open('src/mmwave/model/mmwave-enb-net-device.cc').read()
if '#include <ns3/mmwave-enb-phy.h> // JGRSRP' not in t:
    t = '#include <ns3/mmwave-enb-phy.h> // JGRSRP\n#include <cmath>\n#include <cstdlib>\n' + t
    open('src/mmwave/model/mmwave-enb-net-device.cc', 'w').write(t)
print('done: build with ./ns3 build; set JG_RSRP_KPM=1 in the ns-3 environment of live runs')
