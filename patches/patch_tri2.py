# JamGuard xApp: make the live trilateration usable (on top of patch_rsrp_xapp.py)
# Live run showed only 4 observations per 1-s window, while the fit has 4 unknowns (x, y, Q, n):
# the problem is under-determined (synthetic check: 4 obs -> 163 m median, 8 obs -> 51 m, 24 obs -> 28 m).
# Two causes, both fixed here:
#   a) mitigation removes the best observers: UEs closest to the jammer are evacuated to LTE first and
#      were skipped (state != JG_NR). They still report their NR neighbours over E2, so they are kept as
#      observers through the neighbour RSRP (L3neighRSRP, emitted by patch_rsrp_kpm.py) and neighbour SINR
#      of their last NR cell.
#   b) an estimate from too few observations was published: the trilateration result is now used only with
#      at least JG_TRI_MIN observations (default 8); until then the weighted centroid is kept.
# Also fixes a bug of patch_rsrp_xapp.py: with JG_LOC=2 the old v2 centroid still ran after the
# trilateration and overwrote its estimate.
#   JG_TRI_MIN=8    observations needed before the trilateration estimate is used
#   JG_TRI_LTE=1    1: evacuated UEs stay observers (default), 0: only UEs on NR (old behaviour)
# Usage: cd ~/flexric/examples/xApp/c/orange && cp xapp_jam_guard.c xapp_jam_guard.c.tri1 \
#        && python3 ~/patch_tri2.py && cd ~/flexric/build && make xapp_jam_guard 2>&1 | grep -E "error|Built target xapp"
import sys
p = sys.argv[1] if len(sys.argv) > 1 else 'xapp_jam_guard.c'
t = open(p).read()
if 'JGTRI2' in t:
    print('already patched'); sys.exit(0)
assert 'JGTRI' in t, 'apply patch_rsrp_xapp.py first'

def rep(a, b):
    global t
    n = t.count(a)
    assert n == 1, 'anchor found %d times: %s' % (n, a[:90])
    t = t.replace(a, b)

# ---- per-cell RSRP in the UE record ----
rep('  double rsrp; long rsrp_r;                       /* JGTRI serving RSRP-like power [dBm]   */\n',
    '  double rsrp; long rsrp_r;                       /* JGTRI serving RSRP-like power [dBm]   */\n'
    '  double nb_rsrp[16]; long nb_rsrp_r[16];         /* JGTRI2 neighbour RSRP per cell [dBm]  */\n')

# ---- parameters ----
rep('static int    P_LOC_WIN = 0;', 'static int    P_TRI_MIN = 8;        /* JGTRI2 JG_TRI_MIN observations before the fit is used  */\n'
    'static int    P_TRI_LTE = 1;        /* JGTRI2 JG_TRI_LTE  keep evacuated UEs as observers     */\n'
    'static int    P_LOC_WIN = 0;')
rep('  P_LOC_WIN = (int)jg_envd("JG_LOC_WIN", P_LOC_WIN);',
    '  P_LOC_WIN = (int)jg_envd("JG_LOC_WIN", P_LOC_WIN);\n'
    '  P_TRI_MIN = (int)jg_envd("JG_TRI_MIN", P_TRI_MIN); P_TRI_LTE = (int)jg_envd("JG_TRI_LTE", P_TRI_LTE); /* JGTRI2 */')

# ---- parse the neighbour RSRP of the KPM extension ----
rep('''        jg_ue[imsi].rsrp = jg_rec(&dl->meas_record_lst[0]);
        jg_ue[imsi].rsrp_r = r;''', '''        jg_ue[imsi].rsrp = jg_rec(&dl->meas_record_lst[0]);
        jg_ue[imsi].rsrp_r = r;
        if (cell > 0 && cell < 16) { jg_ue[imsi].nb_rsrp[cell] = jg_ue[imsi].rsrp; jg_ue[imsi].nb_rsrp_r[cell] = r; }
      } else if (sscanf(nm, "L3neighRSRP_cell_%d_UEID_%d", &cell, &imsi) == 2 && imsi > 0 &&
                 imsi < JG_MAX_UE && cell > 0 && cell < 16) {  /* JGTRI2 */
        jg_ue[imsi].nb_rsrp[cell] = jg_rec(&dl->meas_record_lst[0]);
        jg_ue[imsi].nb_rsrp_r[cell] = r;''')

# ---- observer pair (RSRP, SINR) of the NR link, also for a UE parked on LTE ----
rep('static void jg_step(long r, jg_act_t* a, int* na)\n{', '''/* JGTRI2: RSRP and SINR of a UE's NR link; for a UE on the LTE anchor its last NR cell is used,
   which it still reports as a neighbour (EN-DC). Returns 0 when no fresh pair is available. */
static int jg_nr_pair(jg_ue_t const* v, long r, double* rsrp, double* sinr)
{
  if (v->state == JG_NR && v->cell != P_LTE_CELL) {
    if (!jg_fresh(v, r) || v->rsrp_r == 0 || r - v->rsrp_r > P_FRESH) return 0;
    *rsrp = v->rsrp; *sinr = v->sinr;
    return 1;
  }
  if (!P_TRI_LTE) return 0;
  int const c = v->last_nr_cell;
  if (c <= 0 || c >= 16 || c == P_LTE_CELL) return 0;
  if (v->nb_rsrp_r[c] == 0 || r - v->nb_rsrp_r[c] > P_FRESH || r - v->nb_round > P_FRESH) return 0;
  for (int k = 0; k < v->nb_n; k++)
    if (v->nb_cell[k] == c) { *rsrp = v->nb_rsrp[c]; *sinr = v->nb_sinr[k]; return 1; }
  return 0;
}

static void jg_step(long r, jg_act_t* a, int* na)
{''')

rep('''    for (int i = 1; i < JG_MAX_UE; i++) {
      jg_ue_t* v = &jg_ue[i];
      if (!v->has_pos || v->state != JG_NR || !jg_fresh(v, r) || r - v->rsrp_r > P_FRESH || v->rsrp_r == 0) continue;
      if (v->wn >= 16) continue;
      double const jl = jg_db2lin(v->rsrp) / jg_db2lin(v->sinr) - nlin;''', '''    for (int i = 1; i < JG_MAX_UE; i++) {
      jg_ue_t* v = &jg_ue[i];
      double vr, vs;
      if (!v->has_pos || v->wn >= 16 || !jg_nr_pair(v, r, &vr, &vs)) continue;   /* JGTRI2 */
      double const jl = jg_db2lin(vr) / jg_db2lin(vs) - nlin;''')

# ---- publish the fit only when it is well conditioned ----
rep('''      double ex, ey;
      int const m = jg_trilat(&ex, &ey);
      if (m >= 2) {''', '''      double ex, ey;
      int const m = jg_trilat(&ex, &ey);
      if (m >= P_TRI_MIN) {  /* JGTRI2: fewer observations than unknowns -> keep the centroid */''')
rep('''        snprintf(nt, sizeof nt, "%d windows (+%d), zone (%.0f, %.0f) r=%.0f m [trilat]", m, added, ex, ey, rr);
        jg_logev(r, "LOCALIZE", 0, 0, 0, nt);
      }''', '''        snprintf(nt, sizeof nt, "%d windows (+%d), zone (%.0f, %.0f) r=%.0f m [trilat]", m, added, ex, ey, rr);
        jg_logev(r, "LOCALIZE", 0, 0, 0, nt);
      } else if (added > 0 && r % 10 == 0) {
        snprintf(nt, sizeof nt, "%d/%d observations, centroid kept [trilat-wait]", m, P_TRI_MIN);
        jg_logev(r, "LOCALIZE", 0, 0, 0, nt);
      }''')

# ---- the old v2 centroid must not overwrite a published trilateration estimate ----
rep('  } else if (jg_alarm) {', '  } else if (jg_alarm && !(P_LOC == 2 && jg_tri_ok)) {  /* JGTRI2 */')

open(p, 'w').write(t)
print(p, ': trilateration conditioning fixed (JG_TRI_MIN, JG_TRI_LTE, neighbour RSRP)')
