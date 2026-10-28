# FlexRIC xApp library fix (JamGuard): tolerate duplicate / late RIC CONTROL ACKNOWLEDGE
# With ns-O-RAN, an ACK can arrive twice for the same control request. FlexRIC then aborts in
#   assoc_rb_tree_extract ("Trying to extract a key not found in the tree")   or
#   e2ap_handle_control_ack_xapp ("ric_req_id not registered in the registry").
# The fix ignores an ACK whose request or pending event no longer exists (with a log line).
# Usage: cd ~/flexric && cp src/xApp/msg_handler_xapp.c src/xApp/msg_handler_xapp.c.orig && python3 ~/patch_flexric_ack.py
import sys
p = 'src/xApp/msg_handler_xapp.c'
t = open(p).read()
if 'JamGuard fix' in t:
    print('already patched'); sys.exit(0)

def rep(a, b):
    global t
    n = t.count(a)
    assert n == 1, 'anchor found %d times: %s' % (n, a[:80])
    t = t.replace(a, b)

rep('''  act_proc_ans_t rv = find_act_proc(&xapp->act_proc, ack->ric_id.ric_req_id);
  assert(rv.ok == true && "ric_req_id not registered in the registry");

  printf("[xApp]: CONTROL ACK rx\\n");''',
'''  act_proc_ans_t rv = find_act_proc(&xapp->act_proc, ack->ric_id.ric_req_id);
  if (rv.ok == false) { /* JamGuard fix: late or duplicate ACK of a finished control */
    printf("[xApp]: JamGuard fix: CONTROL ACK for unknown ric_req_id %d ignored\\n", (int)ack->ric_id.ric_req_id);
    e2ap_msg_t none = {.type = NONE_E2_MSG_TYPE};
    return none;
  }

  printf("[xApp]: CONTROL ACK rx\\n");''')

rep('''  // Stop the timer
  rm_pending_event_xapp(xapp, &ev);

  // Unblock UI thread''',
'''  // Stop the timer
  if (find_pending_event_ev(&xapp->pending, &ev) == false) { /* JamGuard fix: duplicate ACK */
    printf("[xApp]: JamGuard fix: duplicate CONTROL ACK for ric_req_id %d ignored\\n", (int)ack->ric_id.ric_req_id);
    e2ap_msg_t none = {.type = NONE_E2_MSG_TYPE};
    return none;
  }
  rm_pending_event_xapp(xapp, &ev);

  // Unblock UI thread''')

if '#include "pending_event_xapp.h"' not in t:
    t = '#include "pending_event_xapp.h" /* JamGuard fix: find_pending_event_ev */\n' + t
open(p, 'w').write(t)
print(p, ': duplicate/late CONTROL ACK tolerated')
