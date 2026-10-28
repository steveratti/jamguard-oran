#!/usr/bin/env python3
"""JGTRIU: trilateration also needs observations from >= JG_TRI_UMIN distinct UEs (default 0 = off,
so earlier results stay reproducible). Every window prints '[JGTRI] win W obs M ues U' to stdout,
so the number of distinct UEs behind each fit can be reported."""
import re, shutil, sys, os
p = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/flexric/examples/xApp/c/orange/xapp_jam_guard.c")
s = open(p).read()
if "JGTRIU" in s:
    print("already patched"); sys.exit(0)
A = {
 "decl":  re.compile(r"static int\s+P_TRI_LTE = 1;[^\n]*\n"),
 "env":   re.compile(r"P_TRI_LTE = \(int\)jg_envd\(\"JG_TRI_LTE\", P_TRI_LTE\);[^\n]*\n"),
 "fn":    re.compile(r"static int jg_trilat\(double\* ex, double\* ey\)\n\{\n"),
 "idx":   re.compile(r"(    if \(P_LOC_WIN <= 0 \|\| jg_tw\[k\] > jg_twin - P_LOC_WIN\) idx\[m\+\+\] = k;\n)(  if \(m < 2\) return 0;\n)"),
 "store": re.compile(r"jg_tj\[jg_tn\] = 10\.0 \* jg_log10\(jm\); jg_tw\[jg_tn\] = jg_twin; jg_tn\+\+;"),
 "call":  re.compile(r"(      int const m = jg_trilat\(&ex, &ey\);\n)"),
 "gate":  re.compile(r"if \(m >= P_TRI_MIN\) \{"),
}
pos = {}
for k, rx in A.items():
    found = rx.findall(s)
    if len(found) != 1:
        sys.exit("anchor %s found %d times, expected 1 -- nothing changed" % (k, len(found)))
    pos[k] = rx.search(s).start()
if not (pos["decl"] < pos["env"] and pos["fn"] < pos["store"] and pos["fn"] < pos["call"]):
    sys.exit("unexpected order of anchors -- nothing changed")
s = A["decl"].sub(lambda m: m.group(0) +
      "static int    P_TRI_UMIN = 0;       /* JGTRIU JG_TRI_UMIN distinct UEs before the fit is used (0 = off) */\n", s, 1)
s = A["env"].sub(lambda m: m.group(0) +
      "  P_TRI_UMIN = (int)jg_envd(\"JG_TRI_UMIN\", P_TRI_UMIN); /* JGTRIU */\n", s, 1)
s = A["fn"].sub(lambda m: "/* JGTRIU: UE behind each observation, distinct UEs in the last fit */\n"
      "static int jg_tu[JG_TRI_MAX];\nstatic int jg_tri_nue = 0;\n\n" + m.group(0), s, 1)
s = A["idx"].sub(lambda m: m.group(1) +
      "  { int seen[JG_MAX_UE] = {0}; jg_tri_nue = 0;   /* JGTRIU */\n"
      "    for (int k = 0; k < m; k++) { int const u = jg_tu[idx[k]];\n"
      "      if (u > 0 && u < JG_MAX_UE && !seen[u]) { seen[u] = 1; jg_tri_nue++; } } }\n" + m.group(2), s, 1)
s = A["store"].sub(lambda m: "jg_tu[jg_tn] = i; " + m.group(0), s, 1)
s = A["call"].sub(lambda m: m.group(1) +
      "      printf(\"[JGTRI] win %d obs %d ues %d\\n\", jg_twin, m, jg_tri_nue); fflush(stdout); /* JGTRIU */\n", s, 1)
s = A["gate"].sub("if (m >= P_TRI_MIN && jg_tri_nue >= P_TRI_UMIN) {  /* JGTRIU */", s, 1)
bak = p + ".bak_triu"
if not os.path.exists(bak):
    shutil.copy(p, bak)
open(p, "w").write(s)
print("patched", p, "backup", bak)
