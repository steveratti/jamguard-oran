# JamGuard v3 for the emulated loop (scratch/jamguard_local.h). Every feature is OFF by default
# (old results stay reproducible) and is switched on by an environment variable (clean ablations):
#   JG_SINR_CLIP=35   clip SINR at 35 dB (receiver saturation; ns-3 reports up to ~70 dB near a gNB)
#   JG_PRO_MAX=10     proactive evacuation only if the UE SINR is below 10 dB
#   JG_MLINK=1        multi-link test: a UE is degraded only if its neighbour links dropped too
#                     (median neighbour drop >= DROP/2): jammer vs blockage/fading of one link
#   JG_LOC=1          localization: SINR-only weighted centroid, w = 10^(drop/10) - 1 (~ J/N),
#                     smoothed over the alarm (static jammer), radius = weighted 80th percentile
#   JG_PP_HOLD=30     anti ping-pong: no NR handover back to the previous cell for 30 reports
#                     unless it is 2*HYST better
#   JG_PASSIVE=1|2    passive recovery: evacuated UEs keep measuring NR; the jammer is declared gone
#                     when >= min(2, n_LTE) of them see NR SINR >= S_ok + JG_PASS_MARGIN for JG_PASS_N
#                     reports and no NR UE is degraded (1: plus active probes, 2: passive only)
# Usage: cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && cp scratch/jamguard_local.h scratch/jamguard_local.h.v2 \
#        && python3 ~/patch_v3_local.py && ./ns3 build
import sys
p = sys.argv[1] if len(sys.argv) > 1 else 'scratch/jamguard_local.h'
t = open(p).read()
if 'JGV3' in t:
    print('already patched'); sys.exit(0)

def rep(a, b):
    global t
    n = t.count(a)
    assert n == 1, 'anchor found %d times: %s' % (n, a[:90])
    t = t.replace(a, b)

rep('#include <set>\n', '#include <set>\n#include <algorithm>\n')

# ---- UE record ----
rep('  int deg_cnt = 0, ok_cnt = 0, bad_cnt = 0, stab = 0;\n',
    '  int deg_cnt = 0, ok_cnt = 0, bad_cnt = 0, stab = 0;\n'
    '  double nb_base[16] = {0}; int nb_base_n[16] = {0};   /* JGV3: neighbour baselines */\n'
    '  int prev_cell = 0, pass_ok = 0; long ho_round = -1000;\n')

# ---- parameters ----
rep('static int P_B1_MCS = 2;', '''static double P_CLIP = 0;      /* JGV3 JG_SINR_CLIP  dB, 0 = off */
static double P_PRO_MAX = 0;   /* JGV3 JG_PRO_MAX    dB, 0 = off */
static int P_MLINK = 0;        /* JGV3 JG_MLINK                  */
static int P_LOC = 0;          /* JGV3 JG_LOC        0 old, 1 v3 */
static int P_PP = 0;           /* JGV3 JG_PP_HOLD    reports     */
static int P_PASSIVE = 0;      /* JGV3 JG_PASSIVE    0/1/2       */
static int P_PASS_N = 5;       /* JGV3 JG_PASS_N                 */
static double P_PASS_MARGIN = 5.0; /* JGV3 JG_PASS_MARGIN dB     */
static double g_lsw = 0, g_lsx = 0, g_lsy = 0; /* JGV3 smoothed localization sums */
static int P_B1_MCS = 2;''')

# ---- helper: multi-link test ----
rep('/* ---- jg_step of xapp_jam_guard.c, unchanged logic ---- */', '''/* JGV3 multi-link test: a jammer near the UE lowers all its links, a blockage mostly one */
static int MlinkOk (const Ue *u)
{
  if (!P_MLINK) return 1;
  double d[MAXNB]; int n = 0;
  for (int k = 0; k < u->nb_n; k++)
    {
      int c = u->nb_cell[k];
      if (c <= 0 || c >= 16 || c == P_LTE_CELL || u->nb_base_n[c] == 0) continue;
      d[n++] = u->nb_base[c] - u->nb_sinr[k];
    }
  if (n == 0) return 1;
  std::sort (d, d + n);
  double med = (n % 2) ? d[n / 2] : 0.5 * (d[n / 2 - 1] + d[n / 2]);
  return med >= P_DROP / 2;
}

/* ---- jg_step of xapp_jam_guard.c, unchanged logic ---- */''')

# ---- degradation with the multi-link test; neighbour baselines ----
rep('          int deg = (u->sinr < P_S_LOW && u->base - u->sinr >= P_DROP);',
    '          int deg = (u->sinr < P_S_LOW && u->base - u->sinr >= P_DROP) && MlinkOk (u); /* JGV3 */')
rep('''                  u->base = (u->base_n < 10) ? (u->base * u->base_n + u->sinr) / (u->base_n + 1)
                                             : 0.9 * u->base + 0.1 * u->sinr;
                  u->base_n++;''', '''                  u->base = (u->base_n < 10) ? (u->base * u->base_n + u->sinr) / (u->base_n + 1)
                                             : 0.9 * u->base + 0.1 * u->sinr;
                  u->base_n++;
                  for (int k = 0; k < u->nb_n; k++) /* JGV3 neighbour baselines */
                    {
                      int c = u->nb_cell[k];
                      if (c <= 0 || c >= 16) continue;
                      u->nb_base[c] = (u->nb_base_n[c] < 10)
                                          ? (u->nb_base[c] * u->nb_base_n[c] + u->nb_sinr[k]) / (u->nb_base_n[c] + 1)
                                          : 0.9 * u->nb_base[c] + 0.1 * u->nb_sinr[k];
                      u->nb_base_n[c]++;
                    }''')

# ---- reset smoothing at a new alarm ----
rep('      alarm_ = 1; quiet = 0;', '      alarm_ = 1; quiet = 0; g_lsw = g_lsx = g_lsy = 0; /* JGV3 */')

# ---- localization v3 ----
rep('''  if (alarm_)
    {
      double sw = 0, sx = 0, sy = 0; int m = 0;''', '''  if (alarm_ && P_LOC == 1)
    {
      /* JGV3 localization: SINR-only weighted centroid (w = 10^(drop/10) - 1 ~ J/N), smoothed over the
         alarm because the jammer is static; radius = weighted 80th percentile of the contributors */
      double sw = 0, sx = 0, sy = 0; int m = 0;
      std::vector<double> ww; std::vector<std::pair<double, double>> pp;
      for (int i = 1; i < MAXUE; i++)
        {
          Ue *v = &ue[i];
          if (!v->known || !v->has_pos || v->base_n == 0 || !fresh (v, r)) continue;
          double dr = v->base - v->sinr;
          if (dr < 3) continue;
          double w = std::pow (10.0, (dr > 40 ? 40 : dr) / 10.0) - 1.0;
          sw += w; sx += w * v->x; sy += w * v->y; m++;
          ww.push_back (w); pp.push_back ({v->x, v->y});
        }
      if (m > 0)
        {
          g_lsw += sw; g_lsx += sx; g_lsy += sy;
          double ex = g_lsx / g_lsw, ey = g_lsy / g_lsw;
          std::vector<std::pair<double, double>> dw;
          for (size_t k = 0; k < pp.size (); k++)
            dw.push_back ({std::sqrt ((pp[k].first - ex) * (pp[k].first - ex) + (pp[k].second - ey) * (pp[k].second - ey)), ww[k]});
          std::sort (dw.begin (), dw.end ());
          double acc = 0, rr = dw.back ().first;
          for (auto &q : dw) { acc += q.second; if (acc >= 0.8 * sw) { rr = q.first; break; } }
          if (rr < P_R_MIN) rr = P_R_MIN;
          int moved = !have_est || (ex - ex_) * (ex - ex_) + (ey - ey_) * (ey - ey_) > 25.0 || rr - er_ > 5.0 ||
                      er_ - rr > 5.0;
          ex_ = ex; ey_ = ey; er_ = rr; have_est = 1;
          if (moved)
            {
              snprintf (nt, sizeof nt, "%d UEs, zone (%.0f, %.0f) r=%.0f m [v3]", m, ex, ey, rr);
              logev (r, "LOCALIZE", 0, 0, 0, nt);
            }
        }
    }
  else if (alarm_)
    {
      double sw = 0, sx = 0, sy = 0; int m = 0;''')

# ---- proactive guard ----
rep('          else if (alarm_ && inzone && drop >= P_DROP / 2) why = "proactive";',
    '          else if (alarm_ && inzone && drop >= P_DROP / 2 && (P_PRO_MAX <= 0 || u->sinr < P_PRO_MAX)) why = "proactive"; /* JGV3 */')

# ---- anti ping-pong in the neighbour choice ----
rep('''          if (u->nb_cell[k] != P_LTE_CELL && u->nb_sinr[k] > bs) { bs = u->nb_sinr[k]; best = u->nb_cell[k]; }''',
'''          if (u->nb_cell[k] != P_LTE_CELL && u->nb_sinr[k] > bs &&
              !(P_PP > 0 && u->nb_cell[k] == u->prev_cell && r - u->ho_round < P_PP &&
                u->nb_sinr[k] < u->sinr + 2 * P_HYST)) /* JGV3 anti ping-pong */
            { bs = u->nb_sinr[k]; best = u->nb_cell[k]; }''')
rep('''          u->cool_until = r + P_COOL; u->deg_cnt = 0;
          a.push_back ({i, u->cell, best});''', '''          u->cool_until = r + P_COOL; u->deg_cnt = 0;
          u->prev_cell = u->cell; u->ho_round = r; /* JGV3 */
          a.push_back ({i, u->cell, best});''')
rep('''              u->deg_cnt = 0;
              a.push_back ({i, u->cell, best});''', '''              u->deg_cnt = 0;
              u->prev_cell = u->cell; u->ho_round = r; /* JGV3 */
              a.push_back ({i, u->cell, best});''')

# ---- passive recovery ----
rep('''  if (probe > 0)
    {
      Ue *u = &ue[probe];''', '''  if (P_PASSIVE && probe < 0 && !returning && n_lte > 0)
    {
      /* JGV3 passive recovery: evacuated UEs keep measuring NR (EN-DC); no UE is used as a probe */
      int need = n_lte < 2 ? n_lte : 2, okn = 0;
      for (int i = 1; i < MAXUE; i++)
        {
          Ue *v = &ue[i];
          if (v->state != S_LTE) continue;
          if (fresh (v, r) && v->sinr >= P_S_OK + P_PASS_MARGIN) v->pass_ok++; else v->pass_ok = 0;
          if (v->pass_ok >= P_PASS_N) okn++;
        }
      if (n_deg == 0 && okn >= need)
        {
          snprintf (nt, sizeof nt, "%d evacuated UEs see NR SINR >= %.0f dB", okn, P_S_OK + P_PASS_MARGIN);
          logev (r, "PASSIVE_OK", 0, P_LTE_CELL, 0, nt);
          g_probeOkR = r;
          returning = 1; alarm_ = 0; alarm_cnt = 0; have_est = 0; hold = P_HOLD;
          for (int i = 1; i < MAXUE; i++) ue[i].pass_ok = 0;
        }
    }

  if (probe > 0)
    {
      Ue *u = &ue[probe];''')
rep('  else if (!returning && n_lte > 0 && r >= next_probe)',
    '  else if (!returning && n_lte > 0 && r >= next_probe && P_PASSIVE != 2) /* JGV3 */')

# ---- SINR clip at the observation ----
rep('      u.sinr = Db (s->second);', '      u.sinr = Db (s->second);\n      if (P_CLIP > 0 && u.sinr > P_CLIP) u.sinr = P_CLIP; /* JGV3 */')
rep('          { u.nb_cell[u.nb_n] = c.first; u.nb_sinr[u.nb_n] = Db (c.second); u.nb_n++; }',
    '          { u.nb_cell[u.nb_n] = c.first; u.nb_sinr[u.nb_n] = Db (c.second);\n'
    '            if (P_CLIP > 0 && u.nb_sinr[u.nb_n] > P_CLIP) u.nb_sinr[u.nb_n] = P_CLIP; /* JGV3 */\n'
    '            u.nb_n++; }')

# ---- parameters from the environment, printed ----
rep('  P_B1_MCS = (int) envd ("JG_B1_MCS", P_B1_MCS);', '''  P_B1_MCS = (int) envd ("JG_B1_MCS", P_B1_MCS);
  P_CLIP = envd ("JG_SINR_CLIP", P_CLIP);  P_PRO_MAX = envd ("JG_PRO_MAX", P_PRO_MAX);   /* JGV3 */
  P_MLINK = (int) envd ("JG_MLINK", P_MLINK); P_LOC = (int) envd ("JG_LOC", P_LOC);
  P_PP = (int) envd ("JG_PP_HOLD", P_PP);   P_PASSIVE = (int) envd ("JG_PASSIVE", P_PASSIVE);
  P_PASS_N = (int) envd ("JG_PASS_N", P_PASS_N); P_PASS_MARGIN = envd ("JG_PASS_MARGIN", P_PASS_MARGIN);
  printf ("[JGL] v3 clip=%.0f pro_max=%.0f mlink=%d loc=%d pp_hold=%d passive=%d pass_n=%d pass_margin=%.1f\\n",
          P_CLIP, P_PRO_MAX, P_MLINK, P_LOC, P_PP, P_PASSIVE, P_PASS_N, P_PASS_MARGIN);''')

open(p, 'w').write(t)
print(p, ': JamGuard v3 (emulated loop) added, all features off unless JG_* set')
