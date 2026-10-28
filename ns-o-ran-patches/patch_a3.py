# Baseline p7: standard, jammer-unaware A3 handover (emulated loop, scratch/jamguard_local.h, on top of v3)
# A UE on NR is handed over to its best NR neighbour if neighbour SINR > serving SINR + JG_A3_HYST (3 dB)
# for JG_A3_TTT consecutive reports (2 x 100 ms ~ TTT 160-256 ms of 3GPP), then cool-down JG_COOL.
# No detection, no LTE evacuation, no slicing: this is what a RAN with plain A3 does under jamming,
# and the reference for handover churn / ping-pong (ho_churn.py).
# Why needed: ns-O-RAN's own Threshold handover (LteEnbRrc) never fired in our runs (0 handovers in p0),
# so p0 is "no mobility management" and A3 must be added explicitly.
# Usage: cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_a3.py && ./ns3 build ; run with --jgPolicy=7
import sys
p = sys.argv[1] if len(sys.argv) > 1 else 'scratch/jamguard_local.h'
t = open(p).read()
if 'JGA3' in t:
    print('already patched'); sys.exit(0)
assert 'JGV3' in t, 'apply patch_v3_local.py first'

def rep(a, b):
    global t
    n = t.count(a)
    assert n == 1, 'anchor found %d times: %s' % (n, a[:90])
    t = t.replace(a, b)

rep('  int prev_cell = 0, pass_ok = 0; long ho_round = -1000;\n',
    '  int prev_cell = 0, pass_ok = 0; long ho_round = -1000;\n  int a3_cnt = 0; /* JGA3 */\n')
rep('static double P_CLIP = 0;', 'static double P_A3_HYST = 3.0; static int P_A3_TTT = 2; /* JGA3 */\nstatic double P_CLIP = 0;')
rep('''  if (P_POLICY == 0)
    {''', '''  if (P_POLICY == 7) /* JGA3 baseline: plain A3 handover, jammer-unaware */
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
    {''')
rep('  P_CLIP = envd ("JG_SINR_CLIP", P_CLIP);',
    '  P_A3_HYST = envd ("JG_A3_HYST", P_A3_HYST); P_A3_TTT = (int) envd ("JG_A3_TTT", P_A3_TTT); /* JGA3 */\n'
    '  P_CLIP = envd ("JG_SINR_CLIP", P_CLIP);')
open(p, 'w').write(t)
print(p, ': baseline p7 (plain A3 handover) added; run with --jgPolicy=7')
