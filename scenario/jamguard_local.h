/* jamguard_local.h
 * JamGuard decision logic (same as xapp_jam_guard.c, jg_step) run inside ns-3.
 * Emulated near-RT RIC loop: every 100 ms read serving + neighbour SINR
 * (the same map that feeds the E2 KPM report), decide, and apply the action
 * after jgLoopMs (E2 round trip) through MmWaveEnbNetDevice::XappE2Ho,
 * the same function the RC handler calls in live mode.
 * Enable with --jgLocal=1 ; --jgPolicy=0/1/2 ; --jgLoopMs=20 ; --jgLog=file
 * Thresholds: same JG_* environment variables as the xApp.            */
#pragma once
#include "ns3/core-module.h"
#include "ns3/mobility-module.h"
#include "ns3/node-list.h"
#include "ns3/lte-enb-net-device.h"
#include "ns3/lte-enb-rrc.h"
#include "ns3/mmwave-enb-net-device.h"
#include "ns3/mc-ue-net-device.h"
#include "ns3/mmwave-ue-net-device.h"
#include "ns3/slice-registry.h"
#include <set>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <vector>

namespace jgl
{
using namespace ns3;
using namespace ns3::mmwave;

static GlobalValue gvOn ("jgLocal", "1: run JamGuard inside ns-3 (emulated RIC loop)",
                         UintegerValue (0), MakeUintegerChecker<uint32_t> ());
static GlobalValue gvPol ("jgPolicy", "0 monitor only, 1 reactive, 2 localization-aware",
                          UintegerValue (2), MakeUintegerChecker<uint32_t> ());
static GlobalValue gvLoop ("jgLoopMs", "E2 loop delay in ms between decision and action",
                           UintegerValue (20), MakeUintegerChecker<uint32_t> ());
static GlobalValue gvSlice ("jgSlice", "1: slice-aware mitigation (LTE anchor reserved for critical slices, eMBB cap in cells hosting critical UEs)",
                            UintegerValue (0), MakeUintegerChecker<uint32_t> ());
static GlobalValue gvSrec ("jgSrec", "1: slice-aware recovery (probe with eMBB only, critical slices return last and only on a stable NR link)",
                           UintegerValue (0), MakeUintegerChecker<uint32_t> ());
static GlobalValue gvLog ("jgLog", "JamGuard action log", StringValue ("jamguard_local.csv"),
                          MakeStringChecker ());

const int MAXUE = 128, MAXNB = 8;
enum { S_NR = 0, S_LTE = 1, S_PROBE = 2 };

struct Ue
{
  int known = 0, cell = 0, last_nr_cell = 0, state = S_NR;
  double sinr = 0, base = 0;
  int base_n = 0;
  long upd = 0, eval = 0, nb_round = 0, cool_until = 0, t_evac = 0, probe_since = 0;
  int nb_n = 0, nb_cell[MAXNB] = {0};
  double nb_sinr[MAXNB] = {0};
  int deg_cnt = 0, ok_cnt = 0, bad_cnt = 0, stab = 0;
  double nb_base[16] = {0}; int nb_base_n[16] = {0};   /* JGV3: neighbour baselines */
  int prev_cell = 0, pass_ok = 0; long ho_round = -1000;
  int a3_cnt = 0; /* JGA3 */
  double jam_w = 0;
  int has_pos = 0;
  double x = 0, y = 0;
};
struct Act { int imsi, from, to; };

static Ue ue[MAXUE];
static long g_round = 0;
static FILE *g_log = nullptr;
static uint32_t g_loopMs = 20;
static Ptr<LteEnbRrc> g_rrc;
static std::vector<Ptr<MmWaveEnbNetDevice>> g_gnbs;
static std::map<uint64_t, Ptr<Node>> g_ueNode;
static long g_nAct = 0;

/* parameters (defaults identical to the xApp) */
static int P_POLICY = 2;  static double P_S_LOW = 0.0;  static double P_DROP = 8.0;
static int P_P = 3;       static int P_K = 2;           static double P_S_OK = 5.0;
static double P_HYST = 3.0; static int P_HOLD = 20;     static int P_HOLD_MAX = 160;
static int P_COOL = 10;   static int P_FRESH = 3;       static double P_R_MIN = 30.0;
static double P_R_MARGIN = 20.0; static int P_LTE_CELL = 1;
static int P_RET_GUARD = 1;
static int P_SLICE = 0;           /* jgSlice                                                    */
static int P_LTE_EMBB_MAX = 2;    /* JG_LTE_EMBB_MAX eMBB UEs allowed on the LTE anchor at once */
static double P_EMBB_Q = 0.5;
static int P_SREC = 0;            /* jgSrec                                                           */
static double P_CRIT_MARGIN = 5.0;/* JG_CRIT_MARGIN dB above S_ok before a critical UE leaves LTE      */
static int P_CRIT_WAIT = 10;      /* JG_CRIT_WAIT reports after PROBE_OK before critical UEs return     */
static int P_CRIT_STAB = 5;       /* JG_CRIT_STAB consecutive good reports needed by a critical UE      */
static double P_B2_Q = 0.2;       /* JG_B2_Q eMBB max ratio of baseline B2 (policy 5) during the alarm  */
static long g_probeOkR = -1000;
static double g_b2q = 1.0;
static double P_A3_HYST = 3.0; static int P_A3_TTT = 2; /* JGA3 */
static double P_CLIP = 0;      /* JGV3 JG_SINR_CLIP  dB, 0 = off */
static double P_PRO_MAX = 0;   /* JGV3 JG_PRO_MAX    dB, 0 = off */
static int P_MLINK = 0;        /* JGV3 JG_MLINK                  */
static int P_LOC = 0;          /* JGV3 JG_LOC        0 old, 1 v3 */
static int P_PP = 0;           /* JGV3 JG_PP_HOLD    reports     */
static int P_PASSIVE = 0;      /* JGV3 JG_PASSIVE    0/1/2       */
static int P_PASS_N = 5;       /* JGV3 JG_PASS_N                 */
static double P_PASS_MARGIN = 5.0; /* JGV3 JG_PASS_MARGIN dB     */
static double g_lsw = 0, g_lsx = 0, g_lsy = 0; /* JGV3 smoothed localization sums */
static int P_B1_MCS = 2;            /* JG_B1_MCS DL MCS cap of baseline B1 (policy 6) in affected cells */
static std::map<int, int> g_mcsNow; /* cell -> MCS cap currently requested (B1)                       */     /* JG_EMBB_Q eMBB max symbol ratio in NR cells with critical UEs */
static std::map<uint64_t, int> g_slice;          /* imsi -> slice (0 eMBB, 1 military, 2 ambulance, 3 IoT) */
static std::map<int, double> g_capNow;           /* cell -> eMBB ratio currently requested */
static int SliceOf (int imsi) { auto it = g_slice.find (imsi); return it == g_slice.end () ? 0 : it->second; } /* JG_RET_GUARD 1: return a UE to NR only when its NR SINR >= S_ok */

static int alarm_ = 0, alarm_cnt = 0, quiet = 0, have_est = 0, returning = 0, probe = -1;
static double ex_ = 0, ey_ = 0, er_ = 0;
static long hold = 20, next_probe = 0;

static double envd (const char *k, double d) { const char *v = getenv (k); return v ? atof (v) : d; }
static double clamp (double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }

static void logev (long r, const char *ev, int imsi, int from, int to, const char *note)
{
  double sinr = 0, drop = 0, x = -1, y = -1;
  if (imsi > 0 && imsi < MAXUE)
    {
      sinr = ue[imsi].sinr; drop = ue[imsi].base - ue[imsi].sinr;
      if (ue[imsi].has_pos) { x = ue[imsi].x; y = ue[imsi].y; }
    }
  double t = Simulator::Now ().GetSeconds ();
  if (g_log)
    {
      fprintf (g_log, "%.3f,%ld,%s,%d,%d,%d,%.2f,%.2f,%.1f,%.1f,%d,%.1f,%.1f,%.1f,%s\n", t, r, ev, imsi, from, to,
               sinr, drop, x, y, have_est, ex_, ey_, er_, note ? note : "");
      fflush (g_log);
    }
  printf ("[JGL] t=%.2f %-10s UE %d  %d -> %d  SINR %.1f dB (drop %.1f)  %s\n", t, ev, imsi, from, to, sinr, drop,
          note ? note : "");
  fflush (stdout);
}

static int fresh (const Ue *u, long r) { return u->known && r - u->upd <= P_FRESH; }
static double d2 (const Ue *u) { double dx = u->x - ex_, dy = u->y - ey_; return dx * dx + dy * dy; }
static double wgt (const Ue *u, long r)
{
  if (!u->has_pos) return 0;
  if (u->state == S_NR && u->deg_cnt > 0 && fresh (u, r)) return clamp (u->base - u->sinr, 1, 40);
  if (u->state == S_LTE) return u->jam_w;
  return 0;
}

static int LteEmbb ()
{
  int n = 0;
  for (int i = 1; i < MAXUE; i++) if ((ue[i].state == S_LTE || ue[i].state == S_PROBE) && SliceOf (i) == 0) n++;
  return n;
}

static void ApplyB2 (double q)
{
  SliceRegistry::Instance ().SetSliceMaxRatio (0, q);
  printf ("[JGL] t=%.3f APPLY B2 PRB reservation: eMBB max ratio %.2f in all cells\n", Simulator::Now ().GetSeconds (), q);
  fflush (stdout);
}

static void ApplyMcs (int cell, int cap)
{
  SliceRegistry::Instance ().SetCellMcsCap ((uint16_t) cell, cap);
  printf ("[JGL] t=%.3f APPLY B1 MCS cap cell %d -> %d\n", Simulator::Now ().GetSeconds (), cell, cap);
  fflush (stdout);
}

static void evac (long r, int i, std::vector<Act> &a, const char *why)
{
  Ue *u = &ue[i];
  int from = u->cell;
  u->jam_w = clamp (u->base - u->sinr, 1, 40);
  u->state = S_LTE; u->t_evac = r; u->cool_until = r + P_COOL; u->deg_cnt = 0;
  if (probe < 0 && next_probe <= r) next_probe = r + hold;
  a.push_back ({i, from, P_LTE_CELL});
  logev (r, "EVAC_LTE", i, from, P_LTE_CELL, why);
}

/* JGV3 multi-link test: a jammer near the UE lowers all its links, a blockage mostly one */
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

/* ---- jg_step of xapp_jam_guard.c, unchanged logic ---- */
static void step (long r, std::vector<Act> &a)
{
  char nt[96];
  int n_deg = 0, n_lte = 0;
  for (int i = 1; i < MAXUE; i++)
    {
      Ue *u = &ue[i];
      if (u->state == S_LTE) { n_lte++; continue; }
      if (u->state != S_NR || !fresh (u, r)) continue;
      if (u->upd > u->eval)
        {
          u->eval = u->upd;
          if (u->base_n == 0) { u->base = u->sinr; u->base_n = 1; }
          int deg = (u->sinr < P_S_LOW && u->base - u->sinr >= P_DROP) && MlinkOk (u); /* JGV3 */
          if (deg) u->deg_cnt++;
          else
            {
              u->deg_cnt = 0;
              if (!alarm_ || u->sinr >= P_S_OK)
                {
                  u->base = (u->base_n < 10) ? (u->base * u->base_n + u->sinr) / (u->base_n + 1)
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
                    }
                }
            }
        }
      if (u->deg_cnt > 0) n_deg++;
    }

  if (n_deg >= P_K) alarm_cnt++; else alarm_cnt = 0;
  if (!alarm_ && alarm_cnt >= P_P)
    {
      alarm_ = 1; quiet = 0; g_lsw = g_lsx = g_lsy = 0; /* JGV3 */
      snprintf (nt, sizeof nt, "%d degraded UEs", n_deg);
      logev (r, "DETECT", 0, 0, 0, nt);
    }

  if (alarm_ && P_LOC == 1)
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
      double sw = 0, sx = 0, sy = 0; int m = 0;
      for (int i = 1; i < MAXUE; i++)
        {
          double w = wgt (&ue[i], r);
          if (w <= 0) continue;
          sw += w; sx += w * ue[i].x; sy += w * ue[i].y; m++;
        }
      if (m > 0)
        {
          double ex = sx / sw, ey = sy / sw, rr = 0;
          for (int i = 1; i < MAXUE; i++)
            {
              if (wgt (&ue[i], r) <= 0) continue;
              double d = std::sqrt ((ue[i].x - ex) * (ue[i].x - ex) + (ue[i].y - ey) * (ue[i].y - ey));
              if (d > rr) rr = d;
            }
          rr += P_R_MARGIN;
          if (rr < P_R_MIN) rr = P_R_MIN;
          int moved = !have_est || (ex - ex_) * (ex - ex_) + (ey - ey_) * (ey - ey_) > 25.0 || rr - er_ > 5.0 ||
                      er_ - rr > 5.0;
          ex_ = ex; ey_ = ey; er_ = rr; have_est = 1;
          if (moved)
            {
              snprintf (nt, sizeof nt, "%d UEs, zone (%.0f, %.0f) r=%.0f m", m, ex, ey, rr);
              logev (r, "LOCALIZE", 0, 0, 0, nt);
            }
        }
    }

  if (P_POLICY == 6)
    {
      /* baseline B1 (MCS capping, as in Hoffmann et al.): same detector, DL MCS capped in the cells
         that serve a degraded UE while the alarm is on; no mobility, no slicing */
      std::set<int> want;
      if (alarm_)
        for (int i = 1; i < MAXUE; i++)
          if (ue[i].known && ue[i].deg_cnt > 0 && ue[i].cell != P_LTE_CELL) want.insert (ue[i].cell);
      for (auto &g : g_gnbs)
        {
          int c = g->GetCellId ();
          int cap = alarm_ ? (want.count (c) || (g_mcsNow.count (c) && g_mcsNow[c] >= 0) ? P_B1_MCS : -1) : -1;
          int cur = g_mcsNow.count (c) ? g_mcsNow[c] : -1;
          if (cap == cur) continue;
          g_mcsNow[c] = cap;
          snprintf (nt, sizeof nt, "B1 cell %d MCS cap %d", c, cap);
          logev (r, cap >= 0 ? "MCS_CAP" : "MCS_FREE", 0, c, c, nt);
          Simulator::Schedule (MilliSeconds (g_loopMs), &ApplyMcs, c, cap);
        }
      if (alarm_ && n_deg == 0 && ++quiet >= 20) { alarm_ = 0; have_est = 0; logev (r, "CLEAR", 0, 0, 0, ""); }
      return;
    }
  if (P_POLICY == 5)
    {
      /* baseline B2 (PRB reservation, as in Delavari & Farooq): same detector, eMBB capped in all cells while the alarm is on */
      double q = alarm_ ? P_B2_Q : 1.0;
      if (q != g_b2q)
        {
          g_b2q = q;
          snprintf (nt, sizeof nt, "B2 eMBB max %.2f", q);
          logev (r, q < 1.0 ? "SLICE_CAP" : "SLICE_FREE", 0, 0, 0, nt);
          Simulator::Schedule (MilliSeconds (g_loopMs), &ApplyB2, q);
        }
      if (alarm_ && n_deg == 0 && ++quiet >= 20) { alarm_ = 0; have_est = 0; logev (r, "CLEAR", 0, 0, 0, ""); }
      return;
    }
  if (P_POLICY == 7) /* JGA3 baseline: plain A3 handover, jammer-unaware */
    {
      for (int i = 1; i < MAXUE; i++)
        {
          Ue *u = &ue[i];
          if (u->state != S_NR || !fresh (u, r) || u->cell == P_LTE_CELL) { u->a3_cnt = 0; continue; }
          int best = 0; double bs = -1e9;
          for (int k = 0; k < u->nb_n; k++)
            if (u->nb_cell[k] != P_LTE_CELL && u->nb_sinr[k] > bs) { bs = u->nb_sinr[k]; best = u->nb_cell[k]; }
          if (best && bs > u->sinr + P_A3_HYST) u->a3_cnt++; else u->a3_cnt = 0;
          if (u->a3_cnt >= P_A3_TTT && u->cool_until <= r)
            {
              char nt2[64]; snprintf (nt2, sizeof nt2, "A3, neighbour %.1f dB > serving %.1f dB", bs, u->sinr);
              u->a3_cnt = 0; u->cool_until = r + P_COOL;
              u->prev_cell = u->cell; u->ho_round = r;
              a.push_back ({i, u->cell, best});
              logev (r, "HO_NR", i, u->cell, best, nt2);
            }
        }
      if (alarm_ && n_deg == 0 && ++quiet >= 20) { alarm_ = 0; have_est = 0; logev (r, "CLEAR", 0, 0, 0, ""); }
      return;
    }
  if (P_POLICY == 0)
    {
      if (alarm_ && n_deg == 0 && ++quiet >= 20) { alarm_ = 0; have_est = 0; logev (r, "CLEAR", 0, 0, 0, ""); }
      return;
    }

  for (int i = 1; i < MAXUE; i++)
    {
      Ue *u = &ue[i];
      if (u->state != S_NR || !fresh (u, r) || u->cool_until > r || u->base_n == 0) continue;
      double drop = u->base - u->sinr;
      int inzone = (P_POLICY == 2 && have_est && u->has_pos && d2 (u) <= er_ * er_);
      const char *why = nullptr;
      if (P_POLICY == 1) { if (u->deg_cnt >= P_P) why = "reactive"; }
      else
        {
          if (u->deg_cnt >= P_P && (inzone || !have_est)) why = "in zone";
          else if (u->deg_cnt >= 2 * P_P) why = "persistent";
          else if (alarm_ && inzone && drop >= P_DROP / 2 && (P_PRO_MAX <= 0 || u->sinr < P_PRO_MAX)) why = "proactive"; /* JGV3 */
        }
      if (!why) continue;
      int best = 0; double bs = -1e9;
      if (r - u->nb_round <= P_FRESH)
        for (int k = 0; k < u->nb_n; k++)
          if (u->nb_cell[k] != P_LTE_CELL && u->nb_sinr[k] > bs &&
              !(P_PP > 0 && u->nb_cell[k] == u->prev_cell && r - u->ho_round < P_PP &&
                u->nb_sinr[k] < u->sinr + 2 * P_HYST)) /* JGV3 anti ping-pong */
            { bs = u->nb_sinr[k]; best = u->nb_cell[k]; }
      if (best && bs >= P_S_OK && bs >= u->sinr + P_HYST)
        {
          u->cool_until = r + P_COOL; u->deg_cnt = 0;
          u->prev_cell = u->cell; u->ho_round = r; /* JGV3 */
          a.push_back ({i, u->cell, best});
          snprintf (nt, sizeof nt, "%s, neighbour %.1f dB", why, bs);
          logev (r, "HO_NR", i, u->cell, best, nt);
        }
      else if (P_SLICE && SliceOf (i) == 0 && LteEmbb () >= P_LTE_EMBB_MAX)
        {
          /* LTE anchor reserved for critical slices: keep eMBB on NR (best neighbour if better, else stay) */
          u->cool_until = r + P_COOL;
          if (best && bs >= u->sinr + P_HYST)
            {
              u->deg_cnt = 0;
              u->prev_cell = u->cell; u->ho_round = r; /* JGV3 */
              a.push_back ({i, u->cell, best});
              snprintf (nt, sizeof nt, "%s, eMBB kept on NR, neighbour %.1f dB", why, bs);
              logev (r, "HO_NR", i, u->cell, best, nt);
            }
          else
            logev (r, "HOLD_NR", i, u->cell, u->cell, "eMBB, LTE anchor reserved for critical slices");
        }
      else { evac (r, i, a, why); n_lte++; }
    }

  if (P_PASSIVE && probe < 0 && !returning && n_lte > 0 && r >= next_probe) /* JGPASS2 hold */
    {
      /* JGV3 passive recovery: evacuated UEs keep measuring NR (EN-DC); no UE is used as a probe */
      int need = n_lte < 2 ? n_lte : 2, okn = 0;
      if (need < (n_lte + 1) / 2) need = (n_lte + 1) / 2; /* JGPASS2 majority of evacuated UEs */
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
      Ue *u = &ue[probe];
      if (u->upd > u->eval && u->upd > u->probe_since + 1)
        {
          u->eval = u->upd;
          double ok_th = (u->base - P_DROP / 2 < P_S_OK) ? u->base - P_DROP / 2 : P_S_OK;
          if (u->sinr >= ok_th) u->ok_cnt++;
          else if (u->sinr < P_S_LOW && u->base - u->sinr >= P_DROP) u->bad_cnt++;
        }
      /* sentinel check (jgSrec): UEs still on NR that are degraded show that the jammer is still there */
      if (P_SREC && n_deg > 0 && u->ok_cnt >= 5)
        {
          u->ok_cnt = 0;
          if (r % 10 == 0) logev (r, "PROBE_HOLD", probe, P_LTE_CELL, u->cell, "sentinel UEs on NR still degraded");
        }
      if (u->ok_cnt >= 5)
        {
          u->state = S_NR; u->deg_cnt = 0; u->cool_until = r + P_COOL;
          logev (r, "PROBE_OK", probe, P_LTE_CELL, u->cell, "jammer gone, returning UEs");
          g_probeOkR = r;
          probe = -1; returning = 1; alarm_ = 0; alarm_cnt = 0; have_est = 0; hold = P_HOLD;
        }
      else if (u->bad_cnt >= 2 || r - u->probe_since > 20)
        {
          hold = (2 * hold > P_HOLD_MAX) ? P_HOLD_MAX : 2 * hold;
          u->state = S_LTE; u->t_evac = r; u->cool_until = r + P_COOL;
          a.push_back ({probe, u->cell, P_LTE_CELL});
          snprintf (nt, sizeof nt, "jammer still on, next probe in %ld reports", hold);
          logev (r, "PROBE_FAIL", probe, u->cell, P_LTE_CELL, nt);
          next_probe = r + hold; probe = -1;
        }
    }
  else if (!returning && n_lte > 0 && r >= next_probe && P_PASSIVE != 2) /* JGV3 */
    {
      int p = -1; double bd = 1e18; long bt = 1L << 60;
      for (int i = 1; i < MAXUE; i++)
        {
          const Ue *u = &ue[i];
          if (u->state != S_LTE) continue;
          if (P_SREC && SliceOf (i) != 0 && LteEmbb () > 0) continue;
          if (P_POLICY == 2 && have_est && u->has_pos) { if (d2 (u) < bd) { bd = d2 (u); p = i; } }
          else if (bd >= 1e18 && u->t_evac < bt) { bt = u->t_evac; p = i; }
        }
      if (p > 0)
        {
          Ue *u = &ue[p];
          u->state = S_PROBE; u->probe_since = r; u->ok_cnt = 0; u->bad_cnt = 0; u->eval = u->upd;
          a.push_back ({p, P_LTE_CELL, u->last_nr_cell});
          logev (r, "PROBE", p, P_LTE_CELL, u->last_nr_cell,
                 (P_POLICY == 2 && bd < 1e18) ? "UE nearest to the jammer estimate" : "first evacuated UE");
          probe = p;
        }
    }

  if (returning)
    {
      if (alarm_)
        { /* JGPASS2: recovery was wrong, back off before trying again */
          returning = 0;
          hold = (2 * hold > P_HOLD_MAX) ? P_HOLD_MAX : 2 * hold;
          next_probe = r + hold;
          logev (r, "RECOVER_FAIL", 0, 0, 0, "jammer still on after recovery, backing off");
        }
      else
        {
          int done = 1, embbLeft = 0;
          if (P_SREC)
            for (int j = 1; j < MAXUE; j++)
              {
                if (ue[j].state != S_LTE) continue;
                if (SliceOf (j) == 0) embbLeft++;
                else ue[j].stab = (ue[j].sinr >= P_S_OK + P_CRIT_MARGIN) ? ue[j].stab + 1 : 0;
              }
          for (int i = 1; i < MAXUE; i++)
            {
              Ue *u = &ue[i];
              if (u->state != S_LTE) continue;
              done = 0;
              if (P_SREC && SliceOf (i) != 0 &&
                  (embbLeft > 0 || r - g_probeOkR < P_CRIT_WAIT || u->stab < P_CRIT_STAB)) continue; /* critical last */
              if (P_RET_GUARD && u->sinr < P_S_OK) continue; /* NR link still poor: keep on LTE */
              u->state = S_NR; u->deg_cnt = 0; u->cool_until = r + P_COOL; u->eval = u->upd;
              a.push_back ({i, P_LTE_CELL, u->last_nr_cell});
              logev (r, "RETURN", i, P_LTE_CELL, u->last_nr_cell, "");
              break;
            }
          if (done) returning = 0;
        }
    }

  if (alarm_ && n_deg == 0 && n_lte == 0 && probe < 0)
    { if (++quiet >= 20) { alarm_ = 0; have_est = 0; logev (r, "CLEAR", 0, 0, 0, ""); } }
  else quiet = 0;
}

/* ---- RAN side: action = same call the E2 RC handler makes ---- */
static void Apply (int imsi, int from, int to)
{
  Ptr<MmWaveEnbNetDevice> dev;
  for (auto &g : g_gnbs) if (from != P_LTE_CELL && g->GetCellId () == from) dev = g;
  if (!dev) for (auto &g : g_gnbs) if (g->GetCellId () == to) dev = g;
  if (!dev && !g_gnbs.empty ()) dev = g_gnbs[0];
  if (!dev) return;
  g_nAct++;
  printf ("[JGL] t=%.3f APPLY UE %d -> cell %d via cell %d (loop %u ms)\n", Simulator::Now ().GetSeconds (), imsi, to,
          (int) dev->GetCellId (), g_loopMs);
  fflush (stdout);
  dev->JglHo (imsi, to);
}

static void ApplyCap (int cell, double q)
{
  SliceRegistry::Instance ().SetCellSliceMaxRatio ((uint16_t) cell, 0, q);
  printf ("[JGL] t=%.3f APPLY SLICE cell %d eMBB max ratio %.2f\n", Simulator::Now ().GetSeconds (), cell, q);
  fflush (stdout);
}

/* eMBB cap in NR cells that serve a critical UE while the alarm is on */
static void SliceStep (long r)
{
  std::set<int> want;
  if (alarm_)
    for (int i = 1; i < MAXUE; i++)
      if (ue[i].known && SliceOf (i) != 0 && ue[i].state != S_LTE && ue[i].cell != P_LTE_CELL) want.insert (ue[i].cell);
  for (auto &g : g_gnbs)
    {
      int c = g->GetCellId ();
      double q = want.count (c) ? P_EMBB_Q : 1.0;
      auto it = g_capNow.find (c);
      double cur = it == g_capNow.end () ? 1.0 : it->second;
      if (q == cur) continue;
      g_capNow[c] = q;
      char nt[64]; snprintf (nt, sizeof nt, "cell %d eMBB max %.2f", c, q);
      logev (r, q < 1.0 ? "SLICE_CAP" : "SLICE_FREE", 0, c, c, nt);
      Simulator::Schedule (MilliSeconds (g_loopMs), &ApplyCap, c, q);
    }
}

static double Db (double lin) { return 10.0 * std::log10 (lin > 1e-20 ? lin : 1e-20); }

/* ---- KPM-equivalent observation, every 100 ms ---- */
static void Tick ()
{
  long r = ++g_round;
  const auto &sm = g_rrc->XappGetImsiCellSinrMap ();
  for (auto &kv : g_ueNode)
    {
      uint64_t imsi = kv.first;
      if (imsi == 0 || imsi >= (uint64_t) MAXUE) continue;
      auto it = sm.find (imsi);
      if (it == sm.end ()) continue;
      int nr = (int) g_rrc->XappLastMmWaveCell (imsi);
      auto s = it->second.find (nr);
      if (nr <= 0 || s == it->second.end ()) continue;
      Ue &u = ue[imsi];
      u.known = 1;
      u.last_nr_cell = nr;
      u.cell = g_rrc->XappIsUsingLte (imsi) ? P_LTE_CELL : nr;
      u.sinr = Db (s->second);
      if (P_CLIP > 0 && u.sinr > P_CLIP) u.sinr = P_CLIP; /* JGV3 */
      u.upd = r;
      u.nb_round = r; u.nb_n = 0;
      for (auto &c : it->second)
        if ((int) c.first != nr && u.nb_n < MAXNB)
          { u.nb_cell[u.nb_n] = c.first; u.nb_sinr[u.nb_n] = Db (c.second);
            if (P_CLIP > 0 && u.nb_sinr[u.nb_n] > P_CLIP) u.nb_sinr[u.nb_n] = P_CLIP; /* JGV3 */
            u.nb_n++; }
      Ptr<MobilityModel> mm = kv.second->GetObject<MobilityModel> ();
      if (mm) { u.x = mm->GetPosition ().x; u.y = mm->GetPosition ().y; u.has_pos = 1; }
      if (r == 1)
        printf ("[JGL] sanity UE %d serving cell %d raw %.4g -> %.1f dB, %d neighbours, pos (%.0f,%.0f)\n",
                (int) imsi, nr, s->second, u.sinr, u.nb_n, u.x, u.y);
    }
  if (P_SLICE || P_SREC || P_POLICY == 5)
    for (auto &g : g_gnbs)
      for (auto &x : g->GetUeMap ())
        g_slice[x.second->GetImsi ()] = SliceRegistry::Instance ().SliceOf (g->GetCellId (), x.first);
  std::vector<Act> acts;
  step (r, acts);
  if (P_SLICE && P_POLICY > 0) SliceStep (r);
  for (auto &a : acts)
    Simulator::Schedule (MilliSeconds (g_loopMs), &Apply, a.imsi, a.from, a.to);
  Simulator::Schedule (MilliSeconds (100), &Tick);
}

static void Start ()
{
  UintegerValue on; gvOn.GetValue (on);
  if (on.Get () == 0) return;
  P_S_LOW = envd ("JG_S_LOW", P_S_LOW);   P_DROP = envd ("JG_DROP", P_DROP);
  P_P = (int) envd ("JG_P", P_P);         P_K = (int) envd ("JG_K", P_K);
  P_S_OK = envd ("JG_S_OK", P_S_OK);      P_HYST = envd ("JG_HYST", P_HYST);
  P_HOLD = (int) envd ("JG_HOLD", P_HOLD); P_HOLD_MAX = (int) envd ("JG_HOLD_MAX", P_HOLD_MAX);
  P_COOL = (int) envd ("JG_COOL", P_COOL); P_FRESH = (int) envd ("JG_FRESH", P_FRESH);
  P_R_MIN = envd ("JG_R_MIN", P_R_MIN);   P_R_MARGIN = envd ("JG_R_MARGIN", P_R_MARGIN);
  hold = P_HOLD;
  P_RET_GUARD = (int) envd ("JG_RET_GUARD", P_RET_GUARD);
  UintegerValue pol; gvPol.GetValue (pol); P_POLICY = (int) pol.Get ();
  UintegerValue lp; gvLoop.GetValue (lp); g_loopMs = lp.Get ();
  UintegerValue sv; gvSlice.GetValue (sv); P_SLICE = (int) sv.Get ();
  P_LTE_EMBB_MAX = (int) envd ("JG_LTE_EMBB_MAX", P_LTE_EMBB_MAX);
  P_EMBB_Q = envd ("JG_EMBB_Q", P_EMBB_Q);
  UintegerValue rv; gvSrec.GetValue (rv); P_SREC = (int) rv.Get ();
  P_CRIT_MARGIN = envd ("JG_CRIT_MARGIN", P_CRIT_MARGIN);
  P_CRIT_WAIT = (int) envd ("JG_CRIT_WAIT", P_CRIT_WAIT);
  P_CRIT_STAB = (int) envd ("JG_CRIT_STAB", P_CRIT_STAB);
  P_B2_Q = envd ("JG_B2_Q", P_B2_Q);
  P_B1_MCS = (int) envd ("JG_B1_MCS", P_B1_MCS);
  P_A3_HYST = envd ("JG_A3_HYST", P_A3_HYST); P_A3_TTT = (int) envd ("JG_A3_TTT", P_A3_TTT); /* JGA3 */
  P_CLIP = envd ("JG_SINR_CLIP", P_CLIP);  P_PRO_MAX = envd ("JG_PRO_MAX", P_PRO_MAX);   /* JGV3 */
  P_MLINK = (int) envd ("JG_MLINK", P_MLINK); P_LOC = (int) envd ("JG_LOC", P_LOC);
  P_PP = (int) envd ("JG_PP_HOLD", P_PP);   P_PASSIVE = (int) envd ("JG_PASSIVE", P_PASSIVE);
  P_PASS_N = (int) envd ("JG_PASS_N", P_PASS_N); P_PASS_MARGIN = envd ("JG_PASS_MARGIN", P_PASS_MARGIN);
  printf ("[JGL] v3 clip=%.0f pro_max=%.0f mlink=%d loc=%d pp_hold=%d passive=%d pass_n=%d pass_margin=%.1f\n",
          P_CLIP, P_PRO_MAX, P_MLINK, P_LOC, P_PP, P_PASSIVE, P_PASS_N, P_PASS_MARGIN);
  StringValue lg; gvLog.GetValue (lg);

  for (uint32_t n = 0; n < NodeList::GetNNodes (); n++)
    {
      Ptr<Node> nd = NodeList::GetNode (n);
      for (uint32_t d = 0; d < nd->GetNDevices (); d++)
        {
          Ptr<NetDevice> dev = nd->GetDevice (d);
          if (Ptr<LteEnbNetDevice> l = DynamicCast<LteEnbNetDevice> (dev))
            { if (!g_rrc) { g_rrc = l->GetRrc (); P_LTE_CELL = l->GetCellId (); } }
          else if (Ptr<MmWaveEnbNetDevice> m = DynamicCast<MmWaveEnbNetDevice> (dev))
            g_gnbs.push_back (m);
          else if (Ptr<McUeNetDevice> u = DynamicCast<McUeNetDevice> (dev))
            g_ueNode[u->GetImsi ()] = nd;
        }
    }
  if (!g_rrc) { printf ("[JGL] no LTE eNB found, JamGuard-local disabled\n"); return; }
  g_log = fopen (lg.Get ().c_str (), "w");
  if (g_log)
    fprintf (g_log, "t_s,rep,event,imsi,from_cell,to_cell,sinr_db,drop_db,ue_x,ue_y,est_ok,est_x,est_y,est_r,note\n");
  printf ("[JGL] JamGuard-local ON policy=%d loop=%u ms LTE cell=%d gNBs=%zu UEs=%zu S_low=%.1f drop=%.1f P=%d K=%d "
          "S_ok=%.1f hyst=%.1f hold=%d..%d ret_guard=%d slice=%d lte_embb_max=%d embb_q=%.2f srec=%d b2_q=%.2f log=%s\n",
          P_POLICY, g_loopMs, P_LTE_CELL, g_gnbs.size (), g_ueNode.size (), P_S_LOW, P_DROP, P_P, P_K, P_S_OK,
          P_HYST, P_HOLD, P_HOLD_MAX, P_RET_GUARD, P_SLICE, P_LTE_EMBB_MAX, P_EMBB_Q, P_SREC, P_B2_Q, lg.Get ().c_str ());
  fflush (stdout);
  Simulator::Schedule (Seconds (0.5), &Tick);
}
} // namespace jgl
