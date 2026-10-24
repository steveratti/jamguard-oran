# Fix of patch_rsrp_kpm.py: put the RSRP items in the list that is really sent over E2.
# In ns-O-RAN the ueVal list built in MmWaveEnbNetDevice is not sent: the E2 message is built by
# MmWaveIndicationMessageHelper::AddCuCpUePmItem, which creates its own per-UE item list. So:
#   helper: JgAddUeExtra (ue, name, value) stores items; AddCuCpUePmItem appends them to the UE's list
#   device: the RSRP items go to indicationMessageHelper->JgAddUeExtra instead of the unused ueVal
# Still only with JG_RSRP_KPM set (default: report unchanged).
# Usage: cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_rsrp_kpm2.py && ./ns3 build
import sys

def edit(path, pairs, tag):
    t = open(path).read()
    if tag in t:
        print(path, ': already patched'); return
    for a, b in pairs:
        n = t.count(a)
        assert n == 1, '%s: anchor found %d times: %s' % (path, n, a[:80])
        t = t.replace(a, b)
    open(path, 'w').write(t)
    print(path, ': patched')

H = 'contrib/oran-interface/helper/mmwave-indication-message-helper'
edit(H + '.h', [
    ('  void AddCuCpUePmItem (std::string ueImsiComplete, long numDrb, long drbRelAct,',
     '  // JGRSRP2: extra per-UE items (e.g. RSRP), appended to the UE list of the next AddCuCpUePmItem\n'
     '  void JgAddUeExtra (std::string ueImsiComplete, std::string name, double value);\n'
     '  void AddCuCpUePmItem (std::string ueImsiComplete, long numDrb, long drbRelAct,'),
], 'JGRSRP2')

edit(H + '.cc', [
    ('MmWaveIndicationMessageHelper::~MmWaveIndicationMessageHelper ()',
     '''/* JGRSRP2 */
static std::map<std::string, std::vector<std::pair<std::string, double>>> g_jgUeExtra;

void
MmWaveIndicationMessageHelper::JgAddUeExtra (std::string ueImsiComplete, std::string name, double value)
{
  g_jgUeExtra[ueImsiComplete].push_back ({name, value});
}

MmWaveIndicationMessageHelper::~MmWaveIndicationMessageHelper ()'''),
    ('''  ueVal->AddItem<Ptr<L3RrcMeasurements>> ("HO.TrgtCellQual.RS-SINR.UEID", l3RrcMeasurementNeigh);

  m_msgValues.m_ueIndications.insert (ueVal);''',
     '''  ueVal->AddItem<Ptr<L3RrcMeasurements>> ("HO.TrgtCellQual.RS-SINR.UEID", l3RrcMeasurementNeigh);

  auto jgIt = g_jgUeExtra.find (ueImsiComplete); // JGRSRP2
  if (jgIt != g_jgUeExtra.end ())
    {
      for (auto &jgItem : jgIt->second)
        ueVal->AddItem<double> (jgItem.first, jgItem.second);
      g_jgUeExtra.erase (jgIt);
    }

  m_msgValues.m_ueIndications.insert (ueVal);'''),
], 'JGRSRP2')

t = open(H + '.cc').read()
if '#include <map> // JGRSRP2' not in t:
    t = '#include <map> // JGRSRP2\n#include <string>\n#include <utility>\n#include <vector>\n' + t
    open(H + '.cc', 'w').write(t)

edit('src/mmwave/model/mmwave-enb-net-device.cc', [
    ('            ueVal->AddItem<double> (jgName, jgS);',
     '            indicationMessageHelper->JgAddUeExtra (ueImsiComplete, jgName, jgS); // JGRSRP2'),
], 'JGRSRP2')
print('done: ./ns3 build, then run ns-3 with JG_RSRP_KPM=1 and check kpm_dump.csv for L3servingRSRP')
