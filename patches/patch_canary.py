#!/usr/bin/env python3
"""JGCANARY (on top of JGANCHOR): test the LTE anchor with ONE eMBB UE before any critical UE is sent there.
Off unless JG_CANARY=1 (needs JG_ANCHOR=1). While the anchor is unverified in this alarm episode:
  - the first UE that would be evacuated is an eMBB UE (the degraded one, or the eMBB UE with the lowest
    NR SINR when only critical UEs are degraded) -> EVAC_LTE "canary";
  - critical UEs are NOT sent to LTE: least-degraded NR neighbour if it is better, else HOLD_NR;
  - after JG_CANARY_W reports (default 8 = 0.8 s) the canary's delivered rate over the last 0.5 s decides:
    >= JG_ANCHOR_TH of its NR baseline -> ANCHOR_OK (LTE allowed for everyone in this episode),
    otherwise -> ANCHOR_BAD (the JGANCHOR guard takes over and brings UEs back to NR).
The verdict is reset at every new DETECT."""
import re, shutil, sys, os
H = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/ns-O-RAN-flexric/mmwave-LENA-oran/scratch/jamguard_local.h")
h = open(H).read()
if "JGCANARY" in h:
    sys.exit("already patched (JGCANARY found) -- nothing changed")
if "JGANCHOR" not in h:
    sys.exit("apply patch_anchor.py first -- nothing changed")
A = {
 "ue":    "  double rate = 0, rate_base = 0; int rate_n = 0; uint64_t rxh[10] = {0}; /* JGANCHOR Mb/s */\n",
 "glob":  "static int g_ancBad = 0, g_ancCnt = 0; static long g_ancUntil = 0, g_ancHold = 50;\n",
 "b2":    "static void ApplyB2 (double q)\n",
 "rate":  "          u.rate = (now >= u.rxh[k] ? (double) (now - u.rxh[k]) : 0.0) * 8.0 / 1e6;\n",
 "det":   "      alarm_ = 1; quiet = 0; g_lsw = g_lsx = g_lsy = 0; /* JGV3 */\n",
 "anc":   "  if (P_ANCHOR)\n    {\n      int nev = 0, nbad = 0;\n",
 "evac":  "      else { evac (r, i, a, why); n_lte++; }\n",
 "env":   "  printf (\"[JGL] anchor guard=%d th=%.2f q=%.2f hold=%d\\n\", P_ANCHOR, P_ANC_TH, P_ANC_Q, P_ANC_HOLD);\n",
}
for k, a in A.items():
    n = h.count(a)
    if n != 1:
        sys.exit("anchor %s found %d times, expected 1 -- nothing changed" % (k, n))
h = h.replace(A["ue"], A["ue"] + "  double rate5 = 0; /* JGCANARY delivered rate over the last 0.5 s, Mb/s */\n", 1)
h = h.replace(A["glob"], A["glob"] +
"static int P_CANARY = 0;   /* JG_CANARY    1 = test the anchor with one eMBB UE first (JGCANARY) */\n"
"static int P_CAN_W = 8;    /* JG_CANARY_W  reports the canary stays on LTE before the verdict   */\n"
"static int g_ancOk = 0, g_canary = -1; /* JGCANARY: anchor verified in this episode, canary UE */\n", 1)
h = h.replace(A["b2"],
"""/* JGCANARY: eMBB UE on NR with the lowest SINR, used as canary when only critical UEs are degraded */
static int CanaryPick (long r)
{
  int best = -1; double bs = 1e9;
  for (int i = 1; i < MAXUE; i++)
    {
      const Ue *u = &ue[i];
      if (!u->known || u->state != S_NR || SliceOf (i) != 0 || !fresh (u, r) || u->cool_until > r) continue;
      if (u->sinr < bs) { bs = u->sinr; best = i; }
    }
  return best;
}

""" + A["b2"], 1)
h = h.replace(A["rate"], A["rate"] +
"          { int const k5 = (int) ((r + 5) % 10); /* JGCANARY: value written 5 reports ago */\n"
"            u.rate5 = (now >= u.rxh[k5] ? (double) (now - u.rxh[k5]) : 0.0) * 8.0 / 0.5e6; }\n", 1)
h = h.replace(A["det"], A["det"] + "      g_ancOk = 0; g_canary = -1; /* JGCANARY: new episode, anchor unverified */\n", 1)
h = h.replace(A["anc"], A["anc"] +
"""      if (P_CANARY && g_canary > 0) /* JGCANARY: verdict on the canary */
        {
          Ue *c = &ue[g_canary];
          if (c->state != S_LTE) g_canary = -1;
          else if (r - c->t_evac >= P_CAN_W)
            {
              if (c->rate_n > 0 && c->rate_base >= 0.05 && c->rate5 < P_ANC_TH * c->rate_base)
                {
                  g_ancBad = 1; g_ancUntil = r + g_ancHold; g_ancCnt = 0;
                  snprintf (nt, sizeof nt, "canary UE %d gets %.2f of %.2f Mb/s on LTE, hold %ld", g_canary, c->rate5,
                            c->rate_base, g_ancHold);
                  logev (r, "ANCHOR_BAD", 0, P_LTE_CELL, P_LTE_CELL, nt);
                  g_ancHold = (2 * g_ancHold > 8 * P_ANC_HOLD) ? 8 * P_ANC_HOLD : 2 * g_ancHold;
                }
              else
                {
                  g_ancOk = 1;
                  snprintf (nt, sizeof nt, "canary UE %d gets %.2f of %.2f Mb/s on LTE", g_canary, c->rate5, c->rate_base);
                  logev (r, "ANCHOR_OK", 0, P_LTE_CELL, P_LTE_CELL, nt);
                }
              g_canary = -1;
            }
        }
""", 1)
h = h.replace(A["evac"],
"""      else if (P_ANCHOR && P_CANARY && !g_ancOk) /* JGCANARY: anchor not verified yet in this episode */
        {
          if (SliceOf (i) == 0 && g_canary < 0)
            { evac (r, i, a, "canary: eMBB UE tests the anchor"); n_lte++; g_canary = i; }
          else
            {
              if (g_canary < 0)
                {
                  int const c = CanaryPick (r);
                  if (c > 0) { evac (r, c, a, "canary: anchor tested before critical UEs"); n_lte++; g_canary = c; }
                }
              u->cool_until = r + 3;
              if (best && bs >= u->sinr + P_HYST)
                {
                  u->deg_cnt = 0; u->prev_cell = u->cell; u->ho_round = r;
                  a.push_back ({i, u->cell, best});
                  snprintf (nt, sizeof nt, "%s, anchor unverified, least-degraded NR %.1f dB", why, bs);
                  logev (r, "HO_NR", i, u->cell, best, nt);
                }
              else
                logev (r, "HOLD_NR", i, u->cell, u->cell, "anchor unverified, kept on NR");
            }
        }
""" + A["evac"], 1)
h = h.replace(A["env"], A["env"] +
"  P_CANARY = (int) envd (\"JG_CANARY\", P_CANARY); P_CAN_W = (int) envd (\"JG_CANARY_W\", P_CAN_W); /* JGCANARY */\n"
"  printf (\"[JGL] canary=%d window=%d reports\\n\", P_CANARY, P_CAN_W);\n", 1)
if not os.path.exists(H + ".bak_canary"):
    shutil.copy(H, H + ".bak_canary")
open(H, "w").write(h)
print("patched", H, "(backup .bak_canary)")
