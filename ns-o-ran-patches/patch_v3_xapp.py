# JamGuard v3 for the live xApp (FlexRIC examples/xApp/c/orange/xapp_jam_guard.c)
# Same features and environment variables as patch_v3_local.py (emulated loop), all OFF by default:
#   JG_SINR_CLIP=35  JG_PRO_MAX=10  JG_MLINK=1  JG_LOC=1  JG_PP_HOLD=30  JG_PASSIVE=1|2  JG_PASS_N=5  JG_PASS_MARGIN=5
# Only KPM quantities are used (serving + neighbour SINR, UE position), so this runs over real E2.
# No libm needed (10^(x/10) computed with a small table-free loop).
# Usage: cd ~/flexric/examples/xApp/c/orange && cp xapp_jam_guard.c xapp_jam_guard.c.v2 \
#        && python3 ~/patch_v3_xapp.py && cd ~/flexric/build && make xapp_jam_guard 2>&1 | grep -E "error|Built target xapp"
import sys
p = sys.argv[1] if len(sys.argv) > 1 else 'xapp_jam_guard.c'
t = open(p).read()
if 'JGV3' in t:
    print('already patched'); sys.exit(0)

def rep(a, b):
    global t
    n = t.count(a)
    assert n == 1, 'anchor found %d times: %s' % (n, a[:90])
    t = t.replace(a, b)

# ---- UE record ----
rep('''  int has_pos;
  double x, y;
} jg_ue_t;''', '''  int has_pos;
  double x, y;
  double nb_base[16]; int nb_base_n[16];          /* JGV3 neighbour baselines            */
  int prev_cell, pass_ok; long ho_round, pass_r;  /* JGV3 anti ping-pong, passive recovery */
} jg_ue_t;''')

# ---- parameters ----
rep('static long   P_POLL_US = 20000;', '''static double P_CLIP = 0;          /* JGV3 JG_SINR_CLIP dB, 0 = off                                  */
static double P_PRO_MAX = 0;       /* JGV3 JG_PRO_MAX   proactive evacuation only below this SINR     */
static int    P_MLINK = 0;         /* JGV3 JG_MLINK     multi-link consistency test                    */
static int    P_LOC = 0;           /* JGV3 JG_LOC       1: SINR-weighted, smoothed localization        */
static int    P_PP = 0;            /* JGV3 JG_PP_HOLD   reports without NR handover back to prev cell  */
static int    P_PASSIVE = 0;       /* JGV3 JG_PASSIVE   1 passive + probes, 2 passive only             */
static int    P_PASS_N = 5;        /* JGV3 JG_PASS_N                                                   */
static double P_PASS_MARGIN = 5.0; /* JGV3 JG_PASS_MARGIN dB                                           */
static double jg_lsw = 0, jg_lsx = 0, jg_lsy = 0; /* JGV3 smoothed localization sums                 */
static long   P_POLL_US = 20000;''')
rep('  P_POLL_US      = (long)jg_envd("JG_POLL_US", P_POLL_US);', '''  P_POLL_US      = (long)jg_envd("JG_POLL_US", P_POLL_US);
  P_CLIP = jg_envd("JG_SINR_CLIP", P_CLIP);  P_PRO_MAX = jg_envd("JG_PRO_MAX", P_PRO_MAX);   /* JGV3 */
  P_MLINK = (int)jg_envd("JG_MLINK", P_MLINK); P_LOC = (int)jg_envd("JG_LOC", P_LOC);
  P_PP = (int)jg_envd("JG_PP_HOLD", P_PP);   P_PASSIVE = (int)jg_envd("JG_PASSIVE", P_PASSIVE);
  P_PASS_N = (int)jg_envd("JG_PASS_N", P_PASS_N); P_PASS_MARGIN = jg_envd("JG_PASS_MARGIN", P_PASS_MARGIN);
  printf("[JamGuard] v3 clip=%.0f pro_max=%.0f mlink=%d loc=%d pp_hold=%d passive=%d pass_n=%d pass_margin=%.1f\\n",
         P_CLIP, P_PRO_MAX, P_MLINK, P_LOC, P_PP, P_PASSIVE, P_PASS_N, P_PASS_MARGIN);''')

# ---- SINR clip at KPM reception ----
rep('        u->sinr = jg_db(jg_rec(&dl->meas_record_lst[0]));',
    '        u->sinr = jg_db(jg_rec(&dl->meas_record_lst[0]));\n'
    '        if (P_CLIP > 0 && u->sinr > P_CLIP) u->sinr = P_CLIP; /* JGV3 */')
rep('          u->nb_sinr[u->nb_n] = jg_db(s);',
    '          u->nb_sinr[u->nb_n] = jg_db(s);\n'
    '          if (P_CLIP > 0 && u->nb_sinr[u->nb_n] > P_CLIP) u->nb_sinr[u->nb_n] = P_CLIP; /* JGV3 */')

# ---- helpers ----
rep('static void jg_evac(long r, int i, jg_act_t* a, int* na, const char* why)\n{', '''/* JGV3 helpers */
static double jg_lin(double db) /* 10^(db/10) without libm, 0.1-dB steps, db in [0, 40] */
{
  double v = 1.0;
  int n = (int)(db * 10.0 + 0.5);
  if (n < 0) n = 0;
  if (n > 400) n = 400;
  for (int k = 0; k < n; k++) v *= 1.2589254117941673;
  return v;
}
static void jg_isort(double* k, double* w, int n)
{
  for (int i = 1; i < n; i++) {
    double a = k[i], b = w[i]; int j = i - 1;
    while (j >= 0 && k[j] > a) { k[j + 1] = k[j]; w[j + 1] = w[j]; j--; }
    k[j + 1] = a; w[j + 1] = b;
  }
}
/* multi-link test: a jammer near the UE lowers all its links, a blockage mostly one */
static int jg_mlink_ok(jg_ue_t const* u, long r)
{
  if (!P_MLINK || r - u->nb_round > P_FRESH) return 1;
  double d[JG_MAX_NB], w[JG_MAX_NB]; int n = 0;
  for (int k = 0; k < u->nb_n; k++) {
    int const c = u->nb_cell[k];
    if (c <= 0 || c >= 16 || c == P_LTE_CELL || u->nb_base_n[c] == 0) continue;
    d[n] = u->nb_base[c] - u->nb_sinr[k]; w[n] = 0; n++;
  }
  if (n == 0) return 1;
  jg_isort(d, w, n);
  double const med = (n % 2) ? d[n / 2] : 0.5 * (d[n / 2 - 1] + d[n / 2]);
  return med >= P_DROP / 2;
}

static void jg_evac(long r, int i, jg_act_t* a, int* na, const char* why)
{''')

# ---- detection: multi-link test + neighbour baselines ----
rep('      int const deg = (u->sinr < P_S_LOW && u->base - u->sinr >= P_DROP);',
    '      int const deg = (u->sinr < P_S_LOW && u->base - u->sinr >= P_DROP) && jg_mlink_ok(u, r); /* JGV3 */')
rep('''          u->base = (u->base_n < 10) ? (u->base * u->base_n + u->sinr) / (u->base_n + 1) : 0.9 * u->base + 0.1 * u->sinr;
          u->base_n++;''', '''          u->base = (u->base_n < 10) ? (u->base * u->base_n + u->sinr) / (u->base_n + 1) : 0.9 * u->base + 0.1 * u->sinr;
          u->base_n++;
          if (r - u->nb_round <= P_FRESH)
            for (int k = 0; k < u->nb_n; k++) { /* JGV3 neighbour baselines */
              int const c = u->nb_cell[k];
              if (c <= 0 || c >= 16) continue;
              u->nb_base[c] = (u->nb_base_n[c] < 10)
                                  ? (u->nb_base[c] * u->nb_base_n[c] + u->nb_sinr[k]) / (u->nb_base_n[c] + 1)
                                  : 0.9 * u->nb_base[c] + 0.1 * u->nb_sinr[k];
              u->nb_base_n[c]++;
            }''')
rep('    jg_alarm = 1; jg_quiet = 0;\n', '    jg_alarm = 1; jg_quiet = 0; jg_lsw = jg_lsx = jg_lsy = 0; /* JGV3 */\n')

# ---- localization v3 ----
rep('''  /* 3. localization: weighted centroid of degraded and evacuated UEs (weight = SINR drop) */
  if (jg_alarm) {''', '''  /* 3. localization */
  if (jg_alarm && P_LOC == 1) {
    /* JGV3: SINR-only weighted centroid, w = 10^(drop/10) - 1 ~ J/N, of UEs on NR with drop >= 3 dB,
       smoothed over the alarm (static jammer); radius = weighted 80th percentile */
    double sw = 0, sx = 0, sy = 0, px[JG_MAX_UE], py[JG_MAX_UE], pw[JG_MAX_UE];
    int m = 0;
    for (int i = 1; i < JG_MAX_UE; i++) {
      jg_ue_t const* v = &jg_ue[i];
      if (!v->has_pos || v->state != JG_NR || v->base_n == 0 || !jg_fresh(v, r)) continue;
      double const dr = v->base - v->sinr;
      if (dr < 3) continue;
      double const w = jg_lin(dr > 40 ? 40 : dr) - 1.0;
      sw += w; sx += w * v->x; sy += w * v->y;
      px[m] = v->x; py[m] = v->y; pw[m] = w; m++;
    }
    if (m > 0) {
      jg_lsw += sw; jg_lsx += sx; jg_lsy += sy;
      double const ex = jg_lsx / jg_lsw, ey = jg_lsy / jg_lsw;
      double dd[JG_MAX_UE];
      for (int k = 0; k < m; k++) dd[k] = jg_sqrt((px[k] - ex) * (px[k] - ex) + (py[k] - ey) * (py[k] - ey));
      jg_isort(dd, pw, m);
      double acc = 0, rr = dd[m - 1];
      for (int k = 0; k < m; k++) { acc += pw[k]; if (acc >= 0.8 * sw) { rr = dd[k]; break; } }
      if (rr < P_R_MIN) rr = P_R_MIN;
      int const moved = !jg_have_est || (ex - jg_ex) * (ex - jg_ex) + (ey - jg_ey) * (ey - jg_ey) > 25.0 ||
                        rr - jg_er > 5.0 || jg_er - rr > 5.0;
      jg_ex = ex; jg_ey = ey; jg_er = rr; jg_have_est = 1;
      if (moved) {
        snprintf(nt, sizeof nt, "%d UEs, zone (%.0f, %.0f) r=%.0f m [v3]", m, ex, ey, rr);
        jg_logev(r, "LOCALIZE", 0, 0, 0, nt);
      }
    }
  } else if (jg_alarm) {''')

# ---- proactive guard ----
rep('      else if (jg_alarm && inzone && drop >= P_DROP / 2) why = "proactive";',
    '      else if (jg_alarm && inzone && drop >= P_DROP / 2 && (P_PRO_MAX <= 0 || u->sinr < P_PRO_MAX)) why = "proactive"; /* JGV3 */')

# ---- anti ping-pong ----
rep('        if (u->nb_cell[k] != P_LTE_CELL && u->nb_sinr[k] > bs) { bs = u->nb_sinr[k]; best = u->nb_cell[k]; }',
    '''        if (u->nb_cell[k] != P_LTE_CELL && u->nb_sinr[k] > bs &&
            !(P_PP > 0 && u->nb_cell[k] == u->prev_cell && r - u->ho_round < P_PP &&
              u->nb_sinr[k] < u->sinr + 2 * P_HYST)) /* JGV3 anti ping-pong */
          { bs = u->nb_sinr[k]; best = u->nb_cell[k]; }''')
rep('''    if (best && bs >= P_S_OK && bs >= u->sinr + P_HYST) {
      u->cool_until = r + P_COOL;
      u->deg_cnt = 0;
      jg_add(a, na, i, u->cell, best);''', '''    if (best && bs >= P_S_OK && bs >= u->sinr + P_HYST) {
      u->cool_until = r + P_COOL;
      u->deg_cnt = 0;
      u->prev_cell = u->cell; u->ho_round = r; /* JGV3 */
      jg_add(a, na, i, u->cell, best);''')
rep('''        u->deg_cnt = 0;
        jg_add(a, na, i, u->cell, best);
        snprintf(nt, sizeof nt, "%s, eMBB kept on NR''', '''        u->deg_cnt = 0;
        u->prev_cell = u->cell; u->ho_round = r; /* JGV3 */
        jg_add(a, na, i, u->cell, best);
        snprintf(nt, sizeof nt, "%s, eMBB kept on NR''')

# ---- passive recovery ----
rep('''  /* 5. recovery: probe one UE back to NR, exponential back-off if the jammer is still there */
  if (jg_probe > 0) {''', '''  /* 5a. JGV3 passive recovery: UEs on the LTE anchor keep reporting their NR SINR (EN-DC neighbour list);
         the jammer is declared gone when enough of them see a good NR link and no NR UE is degraded */
  if (P_PASSIVE && jg_probe < 0 && !jg_returning && n_lte > 0) {
    int const need = n_lte < 2 ? n_lte : 2;
    int okn = 0;
    for (int i = 1; i < JG_MAX_UE; i++) {
      jg_ue_t* v = &jg_ue[i];
      if (v->state != JG_LTE) continue;
      if (v->nb_round != v->pass_r) {   /* one count per new neighbour report */
        v->pass_r = v->nb_round;
        if (r - v->nb_round <= P_FRESH && jg_nr_last(v, r) >= P_S_OK + P_PASS_MARGIN && jg_nr_last(v, r) < 1e8) v->pass_ok++;
        else v->pass_ok = 0;
      }
      if (v->pass_ok >= P_PASS_N) okn++;
    }
    if (n_deg == 0 && okn >= need) {
      snprintf(nt, sizeof nt, "%d evacuated UEs see NR SINR >= %.0f dB", okn, P_S_OK + P_PASS_MARGIN);
      jg_logev(r, "PASSIVE_OK", 0, P_LTE_CELL, 0, nt);
      jg_probe_ok_r = r;
      jg_returning = 1; jg_alarm = 0; jg_alarm_cnt = 0; jg_have_est = 0; jg_hold = P_HOLD;
      for (int i = 1; i < JG_MAX_UE; i++) jg_ue[i].pass_ok = 0;
    }
  }

  /* 5. recovery: probe one UE back to NR, exponential back-off if the jammer is still there */
  if (jg_probe > 0) {''')
rep('  } else if (!jg_returning && n_lte > 0 && r >= jg_next_probe) {',
    '  } else if (!jg_returning && n_lte > 0 && r >= jg_next_probe && P_PASSIVE != 2) { /* JGV3 */')

open(p, 'w').write(t)
print(p, ': JamGuard v3 (live xApp) added, all features off unless JG_* set')
