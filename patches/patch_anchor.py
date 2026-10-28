#!/usr/bin/env python3
"""JGANCHOR: anchor-health guard for the emulated JamGuard loop (Scenario B: LTE anchor also jammed).
Off unless JG_ANCHOR=1, so every earlier result stays reproducible.
Signal: delivered DL rate of each UE over the last second (the scenario's PacketSink counters, the
emulated counterpart of KPM DRB.UEThpDl.UEID), against the UE's own rate while it was healthy on NR.
If a majority of UEs that have been on the LTE anchor for >= 1.5 s get < JG_ANCHOR_TH of their
baseline for P reports, the anchor is declared jammed for JG_ANCHOR_HOLD reports (doubling if it is
declared again): no new LTE evacuation (best NR neighbour if it is better, else hold), UEs on LTE go
back to their NR cell, and the eMBB cap in cells hosting critical UEs tightens to JG_ANCHOR_Q."""
import re, shutil, sys, os
base = os.path.expanduser("~/ns-O-RAN-flexric/mmwave-LENA-oran/scratch")
H = sys.argv[1] if len(sys.argv) > 1 else os.path.join(base, "jamguard_local.h")
S = sys.argv[2] if len(sys.argv) > 2 else os.path.join(base, "scenario_jam_xapp.cc")
h = open(H).read(); s = open(S).read()
if "JGANCHOR" in h or "JGANCHOR" in s:
    sys.exit("already patched (JGANCHOR found) -- nothing changed")

def one(txt, a, name):
    n = txt.count(a)
    if n != 1:
        sys.exit("anchor %s found %d times, expected 1 -- nothing changed" % (name, n))

A_UE    = "  double jam_w = 0;\n"
A_GLOB  = "static long hold = 20, next_probe = 0;\n"
A_LOOP  = ("  for (int i = 1; i < MAXUE; i++)\n    {\n      Ue *u = &ue[i];\n"
           "      if (u->state != S_NR || !fresh (u, r) || u->cool_until > r || u->base_n == 0) continue;\n")
A_EVAC  = "      else { evac (r, i, a, why); n_lte++; }\n"
A_CAP   = "      double q = want.count (c) ? P_EMBB_Q : 1.0;\n"
A_TICK  = "  std::vector<Act> acts;\n  step (r, acts);\n"
A_ENV   = '  P_PASS_N = (int) envd ("JG_PASS_N", P_PASS_N); P_PASS_MARGIN = envd ("JG_PASS_MARGIN", P_PASS_MARGIN);\n'
for nm, a in (("ue", A_UE), ("glob", A_GLOB), ("loop", A_LOOP), ("evac", A_EVAC), ("cap", A_CAP), ("tick", A_TICK), ("env", A_ENV)):
    one(h, a, nm)
RX = re.compile(r"(      for \(auto &p : rxSinks\)\n)(        \*rxOut << [^\n]*\n)")
if len(RX.findall(s)) != 1:
    sys.exit("anchor rxSinks loop not found exactly once in the scenario -- nothing changed")

h = h.replace(A_UE, A_UE + "  double rate = 0, rate_base = 0; int rate_n = 0; uint64_t rxh[10] = {0}; /* JGANCHOR Mb/s */\n", 1)
h = h.replace(A_GLOB, A_GLOB +
"""/* JGANCHOR: anchor-health guard (Scenario B) */
static std::map<uint64_t, uint64_t> g_rxTot;   /* imsi -> delivered DL bytes, set by the scenario every 100 ms */
static int P_ANCHOR = 0;          /* JG_ANCHOR       1 = guard on                                        */
static double P_ANC_TH = 0.5;     /* JG_ANCHOR_TH    rate / baseline below which a UE on LTE is starved  */
static double P_ANC_Q = 0.2;      /* JG_ANCHOR_Q     eMBB cap in cells with critical UEs while jammed   */
static int P_ANC_HOLD = 50;       /* JG_ANCHOR_HOLD  reports the anchor stays marked jammed (doubles)   */
static int g_ancBad = 0, g_ancCnt = 0; static long g_ancUntil = 0, g_ancHold = 50;
""", 1)

blk = """  /* JGANCHOR: is the LTE anchor itself delivering? (UEs on LTE for >= 1.5 s, against their NR rate) */
  if (P_ANCHOR)
    {
      int nev = 0, nbad = 0;
      for (int i = 1; i < MAXUE; i++)
        {
          Ue *v = &ue[i];
          if (v->state != S_LTE || r - v->t_evac < 15 || v->rate_n == 0 || v->rate_base < 0.05) continue;
          nev++;
          if (v->rate < P_ANC_TH * v->rate_base) nbad++;
        }
      if (nev > 0 && 2 * nbad > nev) g_ancCnt++; else g_ancCnt = 0;
      if (!g_ancBad && g_ancCnt >= P_P)
        {
          g_ancBad = 1; g_ancUntil = r + g_ancHold;
          snprintf (nt, sizeof nt, "%d of %d UEs on LTE below %.0f%% of their NR rate, hold %ld", nbad, nev,
                    100 * P_ANC_TH, g_ancHold);
          logev (r, "ANCHOR_BAD", 0, P_LTE_CELL, P_LTE_CELL, nt);
          g_ancHold = (2 * g_ancHold > 8 * P_ANC_HOLD) ? 8 * P_ANC_HOLD : 2 * g_ancHold;
        }
      else if (g_ancBad && r >= g_ancUntil)
        {
          g_ancBad = 0; g_ancCnt = 0;
          logev (r, "ANCHOR_RETRY", 0, P_LTE_CELL, P_LTE_CELL, "anchor hold expired, LTE allowed again");
        }
      if (g_ancBad)
        for (int i = 1; i < MAXUE; i++)
          {
            Ue *v = &ue[i];
            if (v->state != S_LTE || v->cool_until > r || v->last_nr_cell <= 0) continue;
            v->state = S_NR; v->deg_cnt = 0; v->cool_until = r + P_COOL; v->eval = v->upd;
            a.push_back ({i, P_LTE_CELL, v->last_nr_cell});
            logev (r, "RETURN", i, P_LTE_CELL, v->last_nr_cell, "anchor jammed, back to NR");
            n_lte--;
          }
    }

"""
h = h.replace(A_LOOP, blk + A_LOOP, 1)
h = h.replace(A_EVAC,
"""      else if (P_ANCHOR && g_ancBad) /* JGANCHOR: no escape to a jammed anchor */
        {
          u->cool_until = r + P_COOL;
          if (best && bs >= u->sinr + P_HYST)
            {
              u->deg_cnt = 0; u->prev_cell = u->cell; u->ho_round = r;
              a.push_back ({i, u->cell, best});
              snprintf (nt, sizeof nt, "%s, anchor jammed, least-degraded NR %.1f dB", why, bs);
              logev (r, "HO_NR", i, u->cell, best, nt);
            }
          else
            logev (r, "HOLD_NR", i, u->cell, u->cell, "anchor jammed, no better NR cell");
        }
""" + A_EVAC, 1)
h = h.replace(A_CAP, "      double q = want.count (c) ? ((P_ANCHOR && g_ancBad) ? P_ANC_Q : P_EMBB_Q) : 1.0; /* JGANCHOR */\n", 1)
h = h.replace(A_TICK,
"""  /* JGANCHOR: delivered rate over the last second, and the UE's healthy NR baseline */
  for (auto &kv : g_ueNode)
    {
      uint64_t imsi = kv.first;
      if (imsi == 0 || imsi >= (uint64_t) MAXUE) continue;
      Ue &u = ue[imsi];
      uint64_t const now = g_rxTot.count (imsi) ? g_rxTot[imsi] : 0;
      int const k = (int) (r % 10);
      if (r > 10)
        {
          u.rate = (now >= u.rxh[k] ? (double) (now - u.rxh[k]) : 0.0) * 8.0 / 1e6;
          if (u.state == S_NR && u.cell != P_LTE_CELL && u.deg_cnt == 0 && !alarm_)
            {
              u.rate_base = (u.rate_n < 10) ? (u.rate_base * u.rate_n + u.rate) / (u.rate_n + 1)
                                            : 0.9 * u.rate_base + 0.1 * u.rate;
              u.rate_n++;
            }
        }
      u.rxh[k] = now;
    }
""" + A_TICK, 1)
h = h.replace(A_ENV, A_ENV +
"""  P_ANCHOR = (int) envd ("JG_ANCHOR", P_ANCHOR); P_ANC_TH = envd ("JG_ANCHOR_TH", P_ANC_TH); /* JGANCHOR */
  P_ANC_Q = envd ("JG_ANCHOR_Q", P_ANC_Q); P_ANC_HOLD = (int) envd ("JG_ANCHOR_HOLD", P_ANC_HOLD); g_ancHold = P_ANC_HOLD;
  printf ("[JGL] anchor guard=%d th=%.2f q=%.2f hold=%d\\n", P_ANCHOR, P_ANC_TH, P_ANC_Q, P_ANC_HOLD);
""", 1)
s = RX.sub(lambda m: m.group(1) + "        {\n          jgl::g_rxTot[p.first] = p.second->GetTotalRx (); /* JGANCHOR */\n  "
           + m.group(2) + "        }\n", s, 1)
for f, txt, tag in ((H, h, ".bak_anchor"), (S, s, ".bak_anchor")):
    if not os.path.exists(f + tag):
        shutil.copy(f, f + tag)
    open(f, "w").write(txt)
print("patched", H, "and", S, "(backups .bak_anchor)")
