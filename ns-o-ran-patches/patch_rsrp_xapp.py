# JamGuard xApp: interference-power trilateration of ratti2026 over E2 (JG_LOC=2), on top of patch_v3_xapp.py
# Needs the ns-O-RAN KPM extension patch_rsrp_kpm.py (ns-3 run with JG_RSRP_KPM=1), which adds
#   L3servingRSRP_cell_<c>_UEID_<imsi>  (wideband received signal power S, dBm)
# Estimator (as in ratti2026, Sec. 4.3.3): per UE J^ = S / SINR - N (N known: -174 + 10log10 B + NF),
#   1-s windows (10 reports): median J^, mean UE position; a window is kept if J^/N >= JG_INR_DB (6 dB);
#   robust least squares of J^_k = Q - 10 n log10 d_k over (x, y, Q, n), soft-l1 loss (6 dB), n in [1.5, 5],
#   grid search JG_AREA_MIN..JG_AREA_MAX (25 m, then 5 m).
#   JG_LOC_WIN = 0: all windows since the alarm (static jammer); k > 0: last k windows (mobile jammer).
#   Until two windows are available the v3 centroid (JG_LOC=1 code) is used.
# No libm: logarithms and powers are computed with small helper functions.
# Usage: cd ~/flexric/examples/xApp/c/orange && cp xapp_jam_guard.c xapp_jam_guard.c.v3 \
#        && python3 ~/patch_rsrp_xapp.py && cd ~/flexric/build && make xapp_jam_guard 2>&1 | grep -E "error|Built target xapp"
import sys
p = sys.argv[1] if len(sys.argv) > 1 else 'xapp_jam_guard.c'
t = open(p).read()
if 'JGTRI' in t:
    print('already patched'); sys.exit(0)
assert 'JGV3' in t, 'apply patch_v3_xapp.py first'

def rep(a, b):
    global t
    n = t.count(a)
    assert n == 1, 'anchor found %d times: %s' % (n, a[:90])
    t = t.replace(a, b)

rep('  int prev_cell, pass_ok; long ho_round, pass_r;  /* JGV3 anti ping-pong, passive recovery */\n',
    '  int prev_cell, pass_ok; long ho_round, pass_r;  /* JGV3 anti ping-pong, passive recovery */\n'
    '  double rsrp; long rsrp_r;                       /* JGTRI serving RSRP-like power [dBm]   */\n'
    '  double wj[16]; int wn; double wx, wy;           /* JGTRI current 1-s window              */\n')

# ---- parameters, state, math helpers, estimator ----
rep('static double jg_lsw = 0, jg_lsx = 0, jg_lsy = 0; /* JGV3 smoothed localization sums                 */',
'''static double jg_lsw = 0, jg_lsx = 0, jg_lsy = 0; /* JGV3 smoothed localization sums                 */
/* JGTRI: interference-power trilateration (JG_LOC=2) */
static double P_NOISE_DBM = -92.0;  /* JG_NOISE_DBM -174 + 10log10(20 MHz) + NF 9 dB                    */
static double P_INR_DB = 6.0;       /* JG_INR_DB    window kept if J^/N >= this                          */
static int    P_LOC_WIN = 0;        /* JG_LOC_WIN   0: all windows since the alarm, k: last k windows    */
static double P_AREA_MIN = 0.0, P_AREA_MAX = 1000.0; /* JG_AREA_MIN / JG_AREA_MAX search area [m]      */
#define JG_TRI_MAX 400
static double jg_tx[JG_TRI_MAX], jg_ty[JG_TRI_MAX], jg_tj[JG_TRI_MAX]; static long jg_tw[JG_TRI_MAX];
static int jg_tn = 0, jg_tri_ok = 0; static long jg_twin = 0;''')

rep('static void jg_evac(long r, int i, jg_act_t* a, int* na, const char* why)\n{', '''/* JGTRI helpers (no libm) */
static double jg_fsqrt(double v) /* v >= 1: Newton from (1+v)/2, 8 steps */
{
  double x = 0.5 * (1.0 + v);
  for (int i = 0; i < 8; i++) x = 0.5 * (x + v / x);
  return x;
}
static double jg_ln(double x) /* natural log, x > 0, no libm */
{
  if (x <= 0) return -1e30;
  int e = 0;
  while (x >= 2.0) { x *= 0.5; e++; }
  while (x < 1.0) { x *= 2.0; e--; }
  double const z = (x - 1.0) / (x + 1.0), z2 = z * z;
  double s = 0, zp = z;
  for (int k = 1; k < 30; k += 2) { s += zp / k; zp *= z2; }
  return 2.0 * s + e * 0.69314718055994531;
}
static double jg_log10(double x) { return jg_ln(x) * 0.43429448190325182; }
static double jg_exp(double y) /* e^y, no libm */
{
  int k = 0;
  while (y > 0.5) { y -= 0.69314718055994531; k++; }
  while (y < -0.5) { y += 0.69314718055994531; k--; }
  double s = 1, term = 1;
  for (int i = 1; i < 25; i++) { term *= y / i; s += term; }
  while (k > 0) { s *= 2; k--; }
  while (k < 0) { s *= 0.5; k++; }
  return s;
}
static double jg_db2lin(double db) { return jg_exp(db * 0.23025850929940457); }
/* robust (soft-l1, 6 dB) fit of J = Q - n L for fixed position; returns the cost */
static double jg_fitqn(double const* L, double const* y, int m)
{
  double w[JG_TRI_MAX], rr[JG_TRI_MAX], n = 3.0, Q = 0;
  for (int k = 0; k < m; k++) w[k] = 1.0;
  for (int it = 0; it < 6; it++) {
    double sw = 0, sl = 0, sy = 0, sll = 0, sly = 0;
    for (int k = 0; k < m; k++) { sw += w[k]; sl += w[k] * L[k]; sy += w[k] * y[k]; sll += w[k] * L[k] * L[k]; sly += w[k] * L[k] * y[k]; }
    double const den = sw * sll - sl * sl;
    n = (den > 1e-9 || den < -1e-9) ? -(sw * sly - sl * sy) / den : 3.0;
    if (n < 1.5) n = 1.5;
    if (n > 5.0) n = 5.0;
    Q = (sy + n * sl) / sw;
    for (int k = 0; k < m; k++) { rr[k] = y[k] - (Q - n * L[k]); w[k] = 1.0 / jg_fsqrt(1.0 + rr[k] * rr[k] / 36.0); }
  }
  double c = 0;
  for (int k = 0; k < m; k++) c += 72.0 * (jg_fsqrt(1.0 + rr[k] * rr[k] / 36.0) - 1.0);
  return c;
}
static double jg_tri_cost(double gx, double gy, int const* idx, int m)
{
  double L[JG_TRI_MAX], y[JG_TRI_MAX];
  for (int k = 0; k < m; k++) {
    double const dx = jg_tx[idx[k]] - gx, dy = jg_ty[idx[k]] - gy;
    double d2 = dx * dx + dy * dy;
    if (d2 < 1.0) d2 = 1.0;
    L[k] = 5.0 * jg_log10(d2);  /* 10 log10 d */
    y[k] = jg_tj[idx[k]];
  }
  return jg_fitqn(L, y, m);
}
static int jg_trilat(double* ex, double* ey)
{
  int idx[JG_TRI_MAX], m = 0;
  for (int k = 0; k < jg_tn; k++)
    if (P_LOC_WIN <= 0 || jg_tw[k] > jg_twin - P_LOC_WIN) idx[m++] = k;
  if (m < 2) return 0;
  double bc = 1e30, bx = 0, by = 0;
  for (double gx = P_AREA_MIN; gx <= P_AREA_MAX + 1e-9; gx += 25.0)
    for (double gy = P_AREA_MIN; gy <= P_AREA_MAX + 1e-9; gy += 25.0) {
      double const c = jg_tri_cost(gx, gy, idx, m);
      if (c < bc) { bc = c; bx = gx; by = gy; }
    }
  double const cx = bx, cy = by;
  for (double gx = cx - 25.0; gx <= cx + 25.0 + 1e-9; gx += 5.0)
    for (double gy = cy - 25.0; gy <= cy + 25.0 + 1e-9; gy += 5.0) {
      double const c = jg_tri_cost(gx, gy, idx, m);
      if (c < bc) { bc = c; bx = gx; by = gy; }
    }
  *ex = bx; *ey = by;
  return m;
}

static void jg_evac(long r, int i, jg_act_t* a, int* na, const char* why)
{''')

rep('  P_PASS_N = (int)jg_envd("JG_PASS_N", P_PASS_N); P_PASS_MARGIN = jg_envd("JG_PASS_MARGIN", P_PASS_MARGIN);',
'''  P_PASS_N = (int)jg_envd("JG_PASS_N", P_PASS_N); P_PASS_MARGIN = jg_envd("JG_PASS_MARGIN", P_PASS_MARGIN);
  P_NOISE_DBM = jg_envd("JG_NOISE_DBM", P_NOISE_DBM); P_INR_DB = jg_envd("JG_INR_DB", P_INR_DB);  /* JGTRI */
  P_LOC_WIN = (int)jg_envd("JG_LOC_WIN", P_LOC_WIN);
  P_AREA_MIN = jg_envd("JG_AREA_MIN", P_AREA_MIN); P_AREA_MAX = jg_envd("JG_AREA_MAX", P_AREA_MAX);
  printf("[JamGuard] trilateration noise=%.1f dBm INR>=%.1f dB win=%d area %.0f..%.0f m\\n",
         P_NOISE_DBM, P_INR_DB, P_LOC_WIN, P_AREA_MIN, P_AREA_MAX);''')

# ---- KPM parsing ----
rep('      } else if (sscanf(nm, "L3neighSINRListOf_UEID_%d_of_Cell_%d", &imsi, &cell) == 2 && imsi > 0 &&',
    '''      } else if (sscanf(nm, "L3servingRSRP_cell_%d_UEID_%d", &cell, &imsi) == 2 && imsi > 0 &&
                 imsi < JG_MAX_UE) {  /* JGTRI: ns-O-RAN KPM extension (patch_rsrp_kpm.py) */
        jg_ue[imsi].rsrp = jg_rec(&dl->meas_record_lst[0]);
        jg_ue[imsi].rsrp_r = r;
      } else if (sscanf(nm, "L3neighSINRListOf_UEID_%d_of_Cell_%d", &imsi, &cell) == 2 && imsi > 0 &&''')

# ---- reset at a new alarm ----
rep('    jg_alarm = 1; jg_quiet = 0; jg_lsw = jg_lsx = jg_lsy = 0; /* JGV3 */',
    '    jg_alarm = 1; jg_quiet = 0; jg_lsw = jg_lsx = jg_lsy = 0; /* JGV3 */\n'
    '    jg_tn = 0; jg_tri_ok = 0; jg_twin = 0; for (int q = 1; q < JG_MAX_UE; q++) jg_ue[q].wn = 0; /* JGTRI */')

# ---- trilateration stage, before the v3 centroid; the centroid is the fall-back ----
rep('''  /* 3. localization */
  if (jg_alarm && P_LOC == 1) {''', '''  /* 3. localization */
  if (jg_alarm && P_LOC == 2) {
    /* JGTRI: collect J^ = S/SINR - N of UEs on NR with a fresh RSRP report */
    double const nlin = jg_db2lin(P_NOISE_DBM);
    for (int i = 1; i < JG_MAX_UE; i++) {
      jg_ue_t* v = &jg_ue[i];
      if (!v->has_pos || v->state != JG_NR || !jg_fresh(v, r) || r - v->rsrp_r > P_FRESH || v->rsrp_r == 0) continue;
      if (v->wn >= 16) continue;
      double const jl = jg_db2lin(v->rsrp) / jg_db2lin(v->sinr) - nlin;
      if (v->wn == 0) { v->wx = 0; v->wy = 0; }
      v->wj[v->wn] = jl; v->wx += v->x; v->wy += v->y; v->wn++;
    }
    if (r % 10 == 0) {  /* end of a 1-s window */
      jg_twin++;
      int added = 0;
      for (int i = 1; i < JG_MAX_UE; i++) {
        jg_ue_t* v = &jg_ue[i];
        if (v->wn >= 5 && jg_tn < JG_TRI_MAX) {
          double tmp[16], dummy[16];
          for (int k = 0; k < v->wn; k++) { tmp[k] = v->wj[k]; dummy[k] = 0; }
          jg_isort(tmp, dummy, v->wn);
          double const jm = tmp[v->wn / 2];
          if (jm > 0 && jm >= nlin * jg_db2lin(P_INR_DB)) {
            jg_tx[jg_tn] = v->wx / v->wn; jg_ty[jg_tn] = v->wy / v->wn;
            jg_tj[jg_tn] = 10.0 * jg_log10(jm); jg_tw[jg_tn] = jg_twin; jg_tn++; added++;
          }
        }
        v->wn = 0;
      }
      double ex, ey;
      int const m = jg_trilat(&ex, &ey);
      if (m >= 2) {
        /* zone radius: 80th percentile of the distances of the current victim UEs, at least R_min */
        double dd[JG_MAX_UE], ww[JG_MAX_UE]; int nv = 0;
        for (int i = 1; i < JG_MAX_UE; i++) {
          jg_ue_t const* v = &jg_ue[i];
          if (!v->has_pos || v->state != JG_NR || !jg_fresh(v, r) || v->base_n == 0 || v->base - v->sinr < 3) continue;
          dd[nv] = jg_sqrt((v->x - ex) * (v->x - ex) + (v->y - ey) * (v->y - ey)); ww[nv] = 1; nv++;
        }
        double rr = P_R_MIN;
        if (nv > 0) { jg_isort(dd, ww, nv); double const q = dd[(int)(0.8 * (nv - 1))]; if (q > rr) rr = q; }
        jg_ex = ex; jg_ey = ey; jg_er = rr; jg_have_est = 1; jg_tri_ok = 1;
        snprintf(nt, sizeof nt, "%d windows (+%d), zone (%.0f, %.0f) r=%.0f m [trilat]", m, added, ex, ey, rr);
        jg_logev(r, "LOCALIZE", 0, 0, 0, nt);
      }
    }
  }
  if (jg_alarm && (P_LOC == 1 || (P_LOC == 2 && !jg_tri_ok))) {''')

open(p, 'w').write(t)
print(p, ': interference-power trilateration added (JG_LOC=2, needs JG_RSRP_KPM=1 in ns-3)')
