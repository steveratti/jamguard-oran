# ns-O-RAN: E2SM-RC style 2 (Radio Resource Allocation Control) handler for JamGuard
#   action 6   slice-level PRB quota : value = cell*1e6 + slice*1e4 + ratio*1000  (cell 0 = all cells)
#   action 100 DL MCS cap (vendor)   : value = cell*1e6 + (cap+1)               (0 = remove the cap)
#   value is read from the gNB UE-ID field of the control header (same field as the IMSI of a handover)
# Also logs every RIC control message received (wall clock, us) and when it is applied (sim time)
#   -> e2_ctrl_rx.csv : side,wall_us,sim_s,style,action,cell,value
# Usage (after the campaigns):  cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_e2_rra.py
import sys
p = 'src/mmwave/model/mmwave-enb-net-device.cc'
t = open(p).read()
if 'JglRraApply' in t:
    print('already patched'); sys.exit(0)

def rep(a, b):
    global t
    n = t.count(a)
    assert n == 1, 'anchor found %d times: %s' % (n, a[:80])
    t = t.replace(a, b)

# 1) includes
t = '#include <chrono>\n#include <fstream>\n#include <mutex>\n#include <algorithm>\n' + t
rep('#include "E2SM-RC-ControlMessage-Format1-Item.h"',
    '#include "E2SM-RC-ControlMessage-Format1-Item.h"\n#include "ns3/slice-registry.h" // JamGuard: RC style 2')

# 2) helpers, inserted before the definition of ControlMessageReceivedCallback
key = '\nMmWaveEnbNetDevice::ControlMessageReceivedCallback (E2AP_PDU_t *sub_req_pdu)'
i = t.find(key)
assert i > 0 and t.count(key) == 1, 'ControlMessageReceivedCallback definition not found'
j = t.rfind('\n', 0, i)          # start of the line with the return type ("void")
helpers = '''
/* JamGuard: log of RIC control messages (E2 thread: wall clock only; sim thread: sim time) */
static std::mutex g_jgE2Mtx;
static std::ofstream g_jgE2Log;
static void
JglE2Log (const char *side, double simS, int style, long action, int cell, unsigned long long value)
{
  std::lock_guard<std::mutex> lk (g_jgE2Mtx);
  if (!g_jgE2Log.is_open ())
    {
      g_jgE2Log.open ("e2_ctrl_rx.csv", std::ios_base::out | std::ios_base::trunc);
      g_jgE2Log << "side,wall_us,sim_s,style,action,cell,value" << std::endl;
    }
  long long us = std::chrono::duration_cast<std::chrono::microseconds> (
                     std::chrono::system_clock::now ().time_since_epoch ()).count ();
  g_jgE2Log << side << "," << us << "," << simS << "," << style << "," << action << "," << cell << ","
            << value << std::endl;
}

/* JamGuard: apply a style-2 action inside the simulator thread */
static void
JglRraApply (int action, uint16_t cell, uint32_t rest)
{
  if (action == 6)
    {
      uint32_t slice = rest / 10000;
      double q = (rest % 10000) / 1000.0;
      if (cell == 0)
        SliceRegistry::Instance ().SetSliceMaxRatio (slice, q);
      else
        SliceRegistry::Instance ().SetCellSliceMaxRatio (cell, slice, q);
      std::cout << Simulator::Now ().GetSeconds () << " s xApp E2: RC slice quota cell " << cell << " slice "
                << slice << " max ratio " << q << std::endl;
    }
  else if (action == 100)
    {
      int cap = (int) rest - 1;
      SliceRegistry::Instance ().SetCellMcsCap (cell, cap);
      std::cout << Simulator::Now ().GetSeconds () << " s xApp E2: RC MCS cap cell " << cell << " -> " << cap
                << std::endl;
    }
  else
    std::cout << "xApp E2: RC style 2 action " << action << " not supported" << std::endl;
  JglE2Log ("apply", Simulator::Now ().GetSeconds (), 2, action, cell, rest);
}

/* JamGuard: handover applied (sim time) */
static void
JglHoMark (uint64_t imsi, uint16_t target)
{
  JglE2Log ("apply", Simulator::Now ().GetSeconds (), 3, 1, target, imsi);
}
'''
t = t[:j] + helpers + t[j:]

# 3) style 2 handler
rep('''      case RicControlMessage::ControlMessageServiceStyle::Radio_Resource_Allocation_Control: {
        NS_LOG_UNCOND ("Unsupported RIC Style Type ");
        break;
      }''', '''      case RicControlMessage::ControlMessageServiceStyle::Radio_Resource_Allocation_Control: {
        /* JamGuard: slice-level PRB quota (action 6) and DL MCS cap (vendor action 100) */
        UEID_GNB_t *g = controlMessage->m_e2SmRcControlHeaderFormat1->ueID.choice.gNB_UEID;
        unsigned long long v = 0;
        if (g != nullptr && g->ran_UEID != nullptr)
          memcpy (&v, g->ran_UEID->buf, std::min<size_t> (g->ran_UEID->size, sizeof (v)));
        long act = controlMessage->m_e2SmRcControlHeaderFormat1->ric_ControlAction_ID;
        uint16_t cell = (uint16_t) (v / 1000000ULL);
        uint32_t rest = (uint32_t) (v % 1000000ULL);
        std::cout << "xApp E2: RC style 2 action " << act << " value " << v << std::endl;
        JglE2Log ("rx", -1.0, 2, act, cell, rest);
        if (!m_forceE2FileLogging)
          Simulator::ScheduleWithContext (1, Seconds (0), &JglRraApply, (int) act, cell, rest);
        else
          Simulator::Schedule (Seconds (0), &JglRraApply, (int) act, cell, rest);
        break;
      }''')

# 4) handover: log reception (E2 thread, wall clock) and application (sim thread)
rep('''              std::cout << "xApp E2: RC Handover_Control received, UE " << imsi << " target " << targetCellId << std::endl;''',
'''              std::cout << "xApp E2: RC Handover_Control received, UE " << imsi << " target " << targetCellId << std::endl;
              JglE2Log ("rx", -1.0, 3, 1, targetCellId, imsi);
              if (!m_forceE2FileLogging)
                Simulator::ScheduleWithContext (1, Seconds (0), &JglHoMark, imsi, targetCellId);
              else
                Simulator::Schedule (Seconds (0), &JglHoMark, imsi, targetCellId);''')

open(p, 'w').write(t)
print(p, ': RC style 2 handler + E2 control log added (e2_ctrl_rx.csv)')
