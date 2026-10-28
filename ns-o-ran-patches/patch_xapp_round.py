# JamGuard xApp: one control round per KPM reporting period without JG_CLOCK
# ns-O-RAN sends several KPM indications per period and E2 node (CU-CP, CU-UP, DU), so counting
# every indication made the xApp's 100-ms rounds run 3-4x faster than the RAN.
# A round now advances only on indications that carry the serving-cell SINR (one per period).
# Usage: cd ~/flexric/examples/xApp/c/orange && python3 ~/patch_xapp_round.py
import sys
p = 'xapp_jam_guard.c'
t = open(p).read()
if 'JGROUND' in t:
    print('already patched'); sys.exit(0)

def rep(a, b):
    global t
    n = t.count(a)
    assert n == 1, 'anchor found %d times: %s' % (n, a[:80])
    t = t.replace(a, b)

rep('''  jg_kpm_us = time_now_us();
  jg_node_cnt[node]++;
  if (P_CLOCK == NULL && jg_node_cnt[node] > jg_round) jg_round = jg_node_cnt[node];
  long const r = jg_round;
''', '''  uint64_t const jg_t_arr = time_now_us();
  /* JGROUND: a round advances only on indications with the serving-cell SINR (one per period) */
  long const r_cand = jg_node_cnt[node] + 1;
  long const r = (P_CLOCK == NULL && r_cand > jg_round) ? r_cand : jg_round;
  int jg_has_srv = 0;
''')
rep('''        u->upd = r;
''', '''        u->upd = r;
        jg_has_srv = 1;
''')
rep('''  if (jg_kpm) fflush(jg_kpm);
''', '''  if (jg_has_srv) {
    jg_kpm_us = jg_t_arr;  /* arrival of the report that starts the round */
    jg_node_cnt[node] = r_cand;
    if (P_CLOCK == NULL && r_cand > jg_round) jg_round = r_cand;
  }
  if (jg_kpm) fflush(jg_kpm);
''')
open(p, 'w').write(t)
print(p, ': rounds follow the KPM reporting period (serving SINR indications only)')
