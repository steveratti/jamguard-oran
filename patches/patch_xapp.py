# JamGuard live xApp upgrade (xapp_jam_guard.c), aligned with the emulated loop (jamguard_local.h)
#  1) slice-aware mitigation  (JG_SLICE=1, p3): LTE anchor reserved for critical slices, eMBB cap
#  2) slice-aware recovery    (JG_SREC=1,  p4): eMBB-only probes, sentinel check, critical UEs last
#  3) baselines B1 / B2       (JG_POLICY=6 / 5)
#  4) cell-level E2 control: E2SM-RC style 2 (Radio Resource Allocation Control)
#        action 6   slice-level PRB quota  value = cell*1e6 + slice*1e4 + ratio*1000
#        action 100 DL MCS cap (vendor)     value = cell*1e6 + (cap+1)   (0 = no cap)
#     the value travels in the gNB UE-ID field, the cell also in the target-cell field
#  5) latency log JG_LAT=file : KPM arrival, decision, E2 control call (wall clock, us)
#  6) same PROBE_OK threshold and NR-SINR return rule as the emulated loop
#  Slice membership: JG_SLICES="2:1,5:2,9:3"  (imsi:slice, 1 military 2 ambulance 3 IoT; operator/A1 policy)
#  Poll period of the decision loop: JG_POLL_US (default 20000 = as before)
# Usage:  cd ~/flexric/examples/xApp/c/orange && cp xapp_jam_guard.c xapp_jam_guard.c.v1 && python3 ~/patch_xapp.py
import sys
p = sys.argv[1] if len(sys.argv) > 1 else 'xapp_jam_guard.c'
t = open(p).read()
if 'JG_SLICES' in t:
    print('already patched'); sys.exit(0)

def rep(a, b, cnt=1):
    global t
    n = t.count(a)
    assert n == cnt, 'anchor found %d times (expected %d): %s' % (n, cnt, a[:80])
    t = t.replace(a, b)

# ---- 1. UE record: stability counter of critical UEs ----
rep('  int deg_cnt, ok_cnt, bad_cnt;\n', '  int deg_cnt, ok_cnt, bad_cnt, stab;\n')

# ---- 2. parameters and state ----
rep('static const char* P_CLOCK = NULL; /* JG_CLOCK file whose last line starts with the ns-3 time [s] */',
'''static const char* P_CLOCK = NULL; /* JG_CLOCK file whose last line starts with the ns-3 time [s] */
/* JamGuard v2: slice-aware mitigation/recovery, baselines, cell-level E2 control, latency log */
static int    P_SLICE = 0;          /* JG_SLICE 1: slice-aware mitigation (p3)                        */
static int    P_SREC = 0;           /* JG_SREC  1: slice-aware recovery + sentinel check (p4)         */
static int    P_LTE_EMBB_MAX = 2;   /* JG_LTE_EMBB_MAX eMBB UEs allowed on the LTE anchor at once     */
static double P_EMBB_Q = 0.5;       /* JG_EMBB_Q eMBB max ratio in NR cells that serve critical UEs   */
static double P_CRIT_MARGIN = 5.0;  /* JG_CRIT_MARGIN dB above S_ok before a critical UE leaves LTE   */
static int    P_CRIT_WAIT = 10;     /* JG_CRIT_WAIT reports after PROBE_OK before critical UEs return  */
static int    P_CRIT_STAB = 5;      /* JG_CRIT_STAB consecutive good reports of a critical UE          */
static double P_B2_Q = 0.2;         /* JG_B2_Q eMBB max ratio of baseline B2 (policy 5)               */
static int    P_B1_MCS = 2;         /* JG_B1_MCS DL MCS cap of baseline B1 (policy 6)                 */
static long   P_POLL_US = 20000;    /* JG_POLL_US period of the decision loop                         */
#define JG_MAX_CELL 16
static int    jg_slice[JG_MAX_UE];          /* imsi -> slice (0 eMBB), from JG_SLICES                 */
static int    jg_cell_seen[JG_MAX_CELL];    /* NR cells seen as serving cells in KPM                  */
static double jg_cap_now[JG_MAX_CELL];      /* cell -> eMBB ratio requested (1 = no cap)              */
static int    jg_mcs_now[JG_MAX_CELL];      /* cell -> MCS cap requested (-1 = none)                  */
static double jg_b2q = 1.0;
static long   jg_probe_ok_r = -1000;
static FILE*  jg_lat = NULL;                /* JG_LAT latency log                                     */
static uint64_t jg_kpm_us = 0;              /* wall clock of the last KPM indication                  */
typedef struct { int kind, cell, slice; double val; } jg_cact_t;   /* kind 0 slice quota, 1 MCS cap */
static jg_cact_t jg_cq[32];
static int jg_ncq = 0;
static void jg_cadd(int kind, int cell, int slice, double val)
{
  if (jg_ncq >= 32) return;
  jg_cq[jg_ncq].kind = kind; jg_cq[jg_ncq].cell = cell; jg_cq[jg_ncq].slice = slice; jg_cq[jg_ncq].val = val;
  jg_ncq++;
}''')

rep('  P_CLOCK = getenv("JG_CLOCK");\n',
'''  P_CLOCK = getenv("JG_CLOCK");
  P_SLICE        = (int)jg_envd("JG_SLICE", P_SLICE);
  P_SREC         = (int)jg_envd("JG_SREC", P_SREC);
  P_LTE_EMBB_MAX = (int)jg_envd("JG_LTE_EMBB_MAX", P_LTE_EMBB_MAX);
  P_EMBB_Q       = jg_envd("JG_EMBB_Q", P_EMBB_Q);
  P_CRIT_MARGIN  = jg_envd("JG_CRIT_MARGIN", P_CRIT_MARGIN);
  P_CRIT_WAIT    = (int)jg_envd("JG_CRIT_WAIT", P_CRIT_WAIT);
  P_CRIT_STAB    = (int)jg_envd("JG_CRIT_STAB", P_CRIT_STAB);
  P_B2_Q         = jg_envd("JG_B2_Q", P_B2_Q);
  P_B1_MCS       = (int)jg_envd("JG_B1_MCS", P_B1_MCS);
  P_POLL_US      = (long)jg_envd("JG_POLL_US", P_POLL_US);
  for (int c = 0; c < JG_MAX_CELL; c++) { jg_cap_now[c] = 1.0; jg_mcs_now[c] = -1; jg_cell_seen[c] = 0; }
  {
    const char* s = getenv("JG_SLICES");   /* "imsi:slice,imsi:slice,..." */
    while (s && *s) {
      int im = 0, sl = 0, n = 0;
      if (sscanf(s, "%d:%d%n", &im, &sl, &n) == 2 && im > 0 && im < JG_MAX_UE) jg_slice[im] = sl;
      const char* c = strchr(s, ',');
      s = c ? c + 1 : NULL;
    }
  }
  printf("[JamGuard] v2 slice=%d srec=%d lte_embb_max=%d embb_q=%.2f crit=%.1f/%d/%d b2_q=%.2f b1_mcs=%d poll=%ld us slices:",
         P_SLICE, P_SREC, P_LTE_EMBB_MAX, P_EMBB_Q, P_CRIT_MARGIN, P_CRIT_WAIT, P_CRIT_STAB, P_B2_Q, P_B1_MCS, P_POLL_US);
  for (int i = 1; i < JG_MAX_UE; i++) if (jg_slice[i]) printf(" %d:%d", i, jg_slice[i]);
  printf("\\n");
''')

# ---- 3. KPM: wall clock of arrival, NR cells seen ----
rep('''  pthread_mutex_lock(&mtx);
  jg_node_cnt[node]++;''', '''  pthread_mutex_lock(&mtx);
  jg_kpm_us = time_now_us();
  jg_node_cnt[node]++;''')
rep('        if (cell != P_LTE_CELL) u->last_nr_cell = cell;\n',
    '        if (cell != P_LTE_CELL) u->last_nr_cell = cell;\n'
    '        if (cell != P_LTE_CELL && cell > 0 && cell < JG_MAX_CELL) jg_cell_seen[cell] = 1;\n')

# ---- 4. helpers used by jg_step (placed before jg_evac) ----
rep('static void jg_evac(long r, int i, jg_act_t* a, int* na, const char* why)',
'''static int jg_sl(int imsi) { return (imsi > 0 && imsi < JG_MAX_UE) ? jg_slice[imsi] : 0; }
static int jg_lte_embb(void)
{
  int n = 0;
  for (int i = 1; i < JG_MAX_UE; i++)
    if ((jg_ue[i].state == JG_LTE || jg_ue[i].state == JG_PROBE) && jg_sl(i) == 0) n++;
  return n;
}
/* NR SINR of a UE as seen by the emulated loop: SINR on its last NR cell (serving if on NR) */
static double jg_nr_last(jg_ue_t const* u, long r)
{
  if (u->cell != P_LTE_CELL) return u->sinr;
  if (r - u->nb_round <= P_FRESH)
    for (int k = 0; k < u->nb_n; k++)
      if (u->nb_cell[k] == u->last_nr_cell) return u->nb_sinr[k];
  return jg_nr_sinr(u, r);
}
/* eMBB cap in NR cells that serve a critical UE while the alarm is on (same rule as the emulated loop) */
static void jg_slice_step(long r)
{
  int want[JG_MAX_CELL] = {0};
  if (jg_alarm)
    for (int i = 1; i < JG_MAX_UE; i++)
      if (jg_ue[i].known && jg_sl(i) != 0 && jg_ue[i].state != JG_LTE && jg_ue[i].cell != P_LTE_CELL &&
          jg_ue[i].cell > 0 && jg_ue[i].cell < JG_MAX_CELL) want[jg_ue[i].cell] = 1;
  for (int c = 1; c < JG_MAX_CELL; c++) {
    if (!jg_cell_seen[c]) continue;
    double const q = want[c] ? P_EMBB_Q : 1.0;
    if (q == jg_cap_now[c]) continue;
    jg_cap_now[c] = q;
    char nt[64];
    snprintf(nt, sizeof nt, "cell %d eMBB max %.2f", c, q);
    jg_logev(r, q < 1.0 ? "SLICE_CAP" : "SLICE_FREE", 0, c, c, nt);
    jg_cadd(0, c, 0, q);
  }
}

static void jg_evac(long r, int i, jg_act_t* a, int* na, const char* why)''')

# ---- 5. baselines B1 / B2 before the monitor-only branch ----
rep('  if (P_POLICY == 0) {  /* monitor only: the RAN\'s own outage logic acts */',
'''  if (P_POLICY == 6) {  /* baseline B1: MCS cap in cells that serve a degraded UE while the alarm is on */
    int want[JG_MAX_CELL] = {0};
    if (jg_alarm)
      for (int i = 1; i < JG_MAX_UE; i++)
        if (jg_ue[i].known && jg_ue[i].deg_cnt > 0 && jg_ue[i].cell != P_LTE_CELL && jg_ue[i].cell > 0 &&
            jg_ue[i].cell < JG_MAX_CELL) want[jg_ue[i].cell] = 1;
    for (int c = 1; c < JG_MAX_CELL; c++) {
      if (!jg_cell_seen[c]) continue;
      int const cap = jg_alarm ? ((want[c] || jg_mcs_now[c] >= 0) ? P_B1_MCS : -1) : -1;
      if (cap == jg_mcs_now[c]) continue;
      jg_mcs_now[c] = cap;
      snprintf(nt, sizeof nt, "B1 cell %d MCS cap %d", c, cap);
      jg_logev(r, cap >= 0 ? "MCS_CAP" : "MCS_FREE", 0, c, c, nt);
      jg_cadd(1, c, 0, (double)cap);
    }
    if (jg_alarm && n_deg == 0 && ++jg_quiet >= 20) { jg_alarm = 0; jg_have_est = 0; jg_logev(r, "CLEAR", 0, 0, 0, ""); }
    return;
  }
  if (P_POLICY == 5) {  /* baseline B2: eMBB capped in all cells while the alarm is on */
    double const q = jg_alarm ? P_B2_Q : 1.0;
    if (q != jg_b2q) {
      jg_b2q = q;
      snprintf(nt, sizeof nt, "B2 eMBB max %.2f", q);
      jg_logev(r, q < 1.0 ? "SLICE_CAP" : "SLICE_FREE", 0, 0, 0, nt);
      jg_cadd(0, 0, 0, q);  /* cell 0 = all cells */
    }
    if (jg_alarm && n_deg == 0 && ++jg_quiet >= 20) { jg_alarm = 0; jg_have_est = 0; jg_logev(r, "CLEAR", 0, 0, 0, ""); }
    return;
  }
  if (P_POLICY == 0) {  /* monitor only: the RAN's own outage logic acts */''')

# ---- 6. slice-aware evacuation ----
rep('''    } else {
      jg_evac(r, i, a, na, why);
      n_lte++;
    }''', '''    } else if (P_SLICE && jg_sl(i) == 0 && jg_lte_embb() >= P_LTE_EMBB_MAX) {
      /* LTE anchor reserved for critical slices: keep eMBB on NR (best neighbour if better, else stay) */
      u->cool_until = r + P_COOL;
      if (best && bs >= u->sinr + P_HYST) {
        u->deg_cnt = 0;
        jg_add(a, na, i, u->cell, best);
        snprintf(nt, sizeof nt, "%s, eMBB kept on NR, neighbour %.1f dB", why, bs);
        jg_logev(r, "HO_NR", i, u->cell, best, nt);
      } else
        jg_logev(r, "HOLD_NR", i, u->cell, u->cell, "eMBB, LTE anchor reserved for critical slices");
    } else {
      jg_evac(r, i, a, na, why);
      n_lte++;
    }''')

# ---- 7. probe: same threshold as the emulated loop, sentinel check ----
rep('      double const ok_th = u->base - P_DROP / 2;  /* back within DROP/2 of the UE\'s own baseline */',
    '      double const ok_th = (u->base - P_DROP / 2 < P_S_OK) ? u->base - P_DROP / 2 : P_S_OK; /* as emulated loop */')
rep('    if (u->ok_cnt >= 5) {\n',
'''    /* sentinel check (JG_SREC): UEs still on NR that are degraded show that the jammer is still there */
    if (P_SREC && n_deg > 0 && u->ok_cnt >= 5) {
      u->ok_cnt = 0;
      if (r % 10 == 0) jg_logev(r, "PROBE_HOLD", jg_probe, P_LTE_CELL, u->cell, "sentinel UEs on NR still degraded");
    }
    if (u->ok_cnt >= 5) {
''')
rep('      jg_logev(r, "PROBE_OK", jg_probe, P_LTE_CELL, u->cell, "jammer gone, returning UEs");\n',
    '      jg_logev(r, "PROBE_OK", jg_probe, P_LTE_CELL, u->cell, "jammer gone, returning UEs");\n      jg_probe_ok_r = r;\n')
# probe candidate: eMBB only while eMBB UEs are on LTE
rep('''      if (u->state != JG_LTE) continue;
      if (P_POLICY == 2 && jg_have_est && u->has_pos) {''', '''      if (u->state != JG_LTE) continue;
      if (P_SREC && jg_sl(i) != 0 && jg_lte_embb() > 0) continue;  /* probe with eMBB only */
      if (P_POLICY == 2 && jg_have_est && u->has_pos) {''')

# ---- 8. return: eMBB first, critical last on a stable NR link ----
rep('''      int done = 1;
      for (int i = 1; i < JG_MAX_UE; i++) {
        jg_ue_t* u = &jg_ue[i];
        if (u->state != JG_LTE) continue;
        done = 0;
        if (P_RET_GUARD && jg_nr_sinr(u, r) < P_S_OK) continue;  /* NR link still poor: keep on LTE */''',
'''      int done = 1, embb_left = 0;
      if (P_SREC)
        for (int j = 1; j < JG_MAX_UE; j++) {
          if (jg_ue[j].state != JG_LTE) continue;
          if (jg_sl(j) == 0) embb_left++;
          else jg_ue[j].stab = (jg_nr_last(&jg_ue[j], r) >= P_S_OK + P_CRIT_MARGIN) ? jg_ue[j].stab + 1 : 0;
        }
      for (int i = 1; i < JG_MAX_UE; i++) {
        jg_ue_t* u = &jg_ue[i];
        if (u->state != JG_LTE) continue;
        done = 0;
        if (P_SREC && jg_sl(i) != 0 &&
            (embb_left > 0 || r - jg_probe_ok_r < P_CRIT_WAIT || u->stab < P_CRIT_STAB)) continue; /* critical last */
        if (P_RET_GUARD && jg_nr_last(u, r) < P_S_OK) continue;  /* NR link still poor: keep on LTE */''')

# ---- 9. slice step at the end of jg_step ----
rep('  } else jg_quiet = 0;\n}', '  } else jg_quiet = 0;\n  if (P_SLICE && P_POLICY > 0 && P_POLICY < 5) jg_slice_step(r);\n}')

# ---- 10. latency around the handover control call ----
rep('  sm_ans_xapp_t ans = control_sm_xapp_api(&jg_nodes.n[idx].id, SM_RC_ID, &rc);',
'''  uint64_t const t0 = time_now_us();
  sm_ans_xapp_t ans = control_sm_xapp_api(&jg_nodes.n[idx].id, SM_RC_ID, &rc);
  uint64_t const t1 = time_now_us();
  if (jg_lat) {
    fprintf(jg_lat, "%ld,HO,%d,%d,%llu,%llu,%llu,%d\\n", jg_round, imsi, to, (unsigned long long)jg_kpm_us,
            (unsigned long long)t0, (unsigned long long)t1, ans.success ? 1 : 0);
    fflush(jg_lat);
  }''')

# ---- 11. cell-level E2 control sender (before jg_sig) ----
rep('static void jg_sig(int s)', '''/* cell-level control over E2SM-RC style 2 (Radio Resource Allocation Control)
   kind 0: slice-level PRB quota (action 6), kind 1: DL MCS cap (vendor-specific action 100) */
static void jg_send_cell(int kind, int cell, int slice, double val)
{
  long long v;
  uint16_t act;
  if (kind == 0) { act = 6;   v = (long long)cell * 1000000LL + (long long)slice * 10000LL + (long long)(val * 1000.0 + 0.5); }
  else           { act = 100; v = (long long)cell * 1000000LL + (long long)((int)val + 1); }
  int idx = -1;
  for (int k = 0; k < (int)jg_nodes.len && k < JG_MAX_NODES; k++)
    if (cell > 0 && jg_node_cell[k] == cell) { idx = k; break; }
  if (idx < 0)
    for (int k = 0; k < (int)jg_nodes.len && k < JG_MAX_NODES; k++)
      if (jg_node_cell[k] >= 1 && jg_node_cell[k] != P_LTE_CELL) { idx = k; break; }
  if (idx < 0) idx = 0;
  rc_ctrl_req_data_t rc = {0};
  ue_id_e2sm_t uid = gen_rc_ue_id(GNB_UE_ID_E2SM, (int)v);
  rc.hdr = gen_rc_ctrl_hdr(FORMAT_1_E2SM_RC_CTRL_HDR, uid, 2 /* Radio Resource Allocation Control */, act);
  rc.msg = gen_handover_rc_ctrl_msg(FORMAT_1_E2SM_RC_CTRL_MSG, (uint8_t)('0' + ((cell >= 0 && cell <= 9) ? cell : 0)));
  uint64_t const t0 = time_now_us();
  sm_ans_xapp_t ans = control_sm_xapp_api(&jg_nodes.n[idx].id, SM_RC_ID, &rc);
  uint64_t const t1 = time_now_us();
  printf("[JamGuard] RC style 2 action %u cell %d %s %.2f (value %lld) via E2 node %d: %s\\n", act, cell,
         kind == 0 ? "eMBB ratio" : "MCS cap", val, v, idx, ans.success ? "sent" : "FAILED");
  fflush(stdout);
  if (jg_lat) {
    fprintf(jg_lat, "%ld,%s,%d,%lld,%llu,%llu,%llu,%d\\n", jg_round, kind == 0 ? "SLICE" : "MCS", cell, v,
            (unsigned long long)jg_kpm_us, (unsigned long long)t0, (unsigned long long)t1, ans.success ? 1 : 0);
    fflush(jg_lat);
  }
}

static void jg_sig(int s)''')

# ---- 12. main: latency file, poll period, decision timing, cell actions ----
rep('  if (getenv("JG_KPM_DUMP")) {', '''  if (getenv("JG_LAT")) {
    jg_lat = fopen(getenv("JG_LAT"), "w");
    if (jg_lat) fprintf(jg_lat, "rep,kind,ue_or_cell,target_or_value,t_kpm_us,t_start_us,t_end_us,ok\\n");
    printf("[JamGuard] latency log to %s\\n", getenv("JG_LAT"));
  }
  if (getenv("JG_KPM_DUMP")) {''')
rep('    usleep(20000);\n', '    usleep((useconds_t)P_POLL_US);\n')
rep('    if (r > last) { last = r; jg_step(r, acts, &na); }',
'''    jg_cact_t cacts[32];
    int nca = 0;
    uint64_t td0 = 0, td1 = 0, tk = 0;
    if (r > last) {
      last = r;
      jg_ncq = 0;
      tk = jg_kpm_us;
      td0 = time_now_us();
      jg_step(r, acts, &na);
      td1 = time_now_us();
      nca = jg_ncq;
      for (int k = 0; k < nca; k++) cacts[k] = jg_cq[k];
      jg_ncq = 0;
    }''')
rep('    for (int k = 0; k < na; k++) jg_send(acts[k].imsi, acts[k].from, acts[k].to);',
'''    if (jg_lat && td1 > 0 && (na > 0 || nca > 0)) {
      fprintf(jg_lat, "%ld,DECIDE,%d,%d,%llu,%llu,%llu,1\\n", r, na, nca, (unsigned long long)tk,
              (unsigned long long)td0, (unsigned long long)td1);
      fflush(jg_lat);
    }
    for (int k = 0; k < na; k++) jg_send(acts[k].imsi, acts[k].from, acts[k].to);
    for (int k = 0; k < nca; k++) jg_send_cell(cacts[k].kind, cacts[k].cell, cacts[k].slice, cacts[k].val);''')

open(p, 'w').write(t)
print('xApp upgraded: JG_SLICE JG_SREC JG_SLICES JG_POLICY=5/6 JG_LAT JG_POLL_US')
