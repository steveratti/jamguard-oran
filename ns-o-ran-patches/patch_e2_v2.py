# JamGuard E2 fix v2
# Problem: e2sim never sends a RIC CONTROL ACK (disabled in e2ap_message_handler.cpp), so the
# acknowledgement seen by the xApp comes from the RIC; for E2SM-RC style 2 it did not match a
# pending request and the FlexRIC xApp aborted (assoc_rb_tree_extract assertion).
# Fix: carry the cell-level commands (slice quota, MCS cap) in the Connected-Mode-Mobility /
# Handover_Control format that already works end to end, with a reserved UE identifier:
#   ueid = 100000000 + kind*10000000 + cell*1000000 + rest
#   kind 0 slice quota (rest = slice*10000 + ratio*1000), kind 1 MCS cap (rest = cap+1)
# Usage:
#   cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_e2_v2.py ns3
#   cd ~/flexric/examples/xApp/c/orange && python3 ~/patch_e2_v2.py xapp
import sys
which = sys.argv[1] if len(sys.argv) > 1 else ''

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

if which == 'ns3':
    edit('src/mmwave/model/mmwave-enb-net-device.cc', [(
'''              std::cout << "xApp E2: RC Handover_Control received, UE " << imsi << " target " << targetCellId << std::endl;''',
'''              if (imsi >= 100000000ULL) /* JGCMD2: JamGuard cell-level command in the mobility format */
                {
                  uint64_t w = imsi - 100000000ULL;
                  int act = (w / 10000000ULL) == 0 ? 6 : 100;
                  uint16_t cell = (uint16_t) ((w / 1000000ULL) % 10ULL);
                  uint32_t rest = (uint32_t) (w % 1000000ULL);
                  std::cout << "xApp E2: RC cell command action " << act << " cell " << cell << " value " << rest << std::endl;
                  JglE2Log ("rx", -1.0, 2, act, cell, rest);
                  if (!m_forceE2FileLogging)
                    Simulator::ScheduleWithContext (1, Seconds (0), &JglRraApply, act, cell, rest);
                  else
                    Simulator::Schedule (Seconds (0), &JglRraApply, act, cell, rest);
                  break;
                }
              std::cout << "xApp E2: RC Handover_Control received, UE " << imsi << " target " << targetCellId << std::endl;''')],
        'JGCMD2')
elif which == 'xapp':
    edit('xapp_jam_guard.c', [
('''  if (kind == 0) { act = 6;   v = (long long)cell * 1000000LL + (long long)slice * 10000LL + (long long)(val * 1000.0 + 0.5); }
  else           { act = 100; v = (long long)cell * 1000000LL + (long long)((int)val + 1); }''',
'''  /* JGCMD2: reserved UE id in the Connected-Mode-Mobility format (style 2 is not acknowledged by e2sim) */
  if (kind == 0) { act = 6;   v = 100000000LL + (long long)cell * 1000000LL + (long long)slice * 10000LL + (long long)(val * 1000.0 + 0.5); }
  else           { act = 100; v = 110000000LL + (long long)cell * 1000000LL + (long long)((int)val + 1); }'''),
('''  rc.hdr = gen_rc_ctrl_hdr(FORMAT_1_E2SM_RC_CTRL_HDR, uid, 2 /* Radio Resource Allocation Control */, act);''',
'''  rc.hdr = gen_rc_ctrl_hdr(FORMAT_1_E2SM_RC_CTRL_HDR, uid, CONNECTED_MODE_MOBILITY, HANDOVER_CONTROL_7_6_4_1);'''),
('''  printf("[JamGuard] RC style 2 action %u cell %d %s %.2f (value %lld) via E2 node %d: %s\\n", act, cell,''',
'''  printf("[JamGuard] RC cell command %u cell %d %s %.2f (value %lld) via E2 node %d: %s\\n", act, cell,'''),
], 'JGCMD2')
else:
    print('usage: patch_e2_v2.py ns3|xapp')
