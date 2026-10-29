# Adds two detectors to roc_replay.py, inside the script that already scores D1-D4, so that every
# detector is measured with the same ground truth, the same blockage model, the same persistence
# and latch rules and the same definition of a false alarm. Scoring them in a separate script
# would make the comparison in the paper meaningless.
#
#   D5  the modulation and coding scheme falls DMCS indices below the UE's own baseline
#   D6  fusion: the SINR drop confirmed by EITHER the multi-link test OR the MCS drop
#
# Why the MCS and not the block error rate: measured on this platform, the windowed BLER of every
# UE is flat or falls slightly when a constant jammer starts (0.278 -> 0.239, against 0.278 ->
# 0.265 with no jammer), because outer-loop link adaptation regulates it back to its target. What
# the loop changes instead is the modulation, and that moves: 22.1 -> 16.3 mean MCS index. The
# error rate carries information only while the controller cannot follow, which is the keyed
# jammer of the literature, not the constant one.
#
# The MCS is read from CARR.PDSCHMCSDist.Bin1..6.UEID in the DU part of the E2SM-KPM report, which
# only carries usable values once the measurement is decoupled from the trace file
# (patches/patch_du_kpm.py). Report instants are 100 ms, the same tick as the replay.
#
# usage: python3 ~/patch_roc_mcs.py [path to roc_replay.py]   then: ~/roc_replay.py ... --dmcs 4
# Idempotent; keeps a .bak_mcs copy.
import os, re, sys, shutil

F = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/roc_replay.py')
if not os.path.exists(F):
    sys.exit('ERROR: not found: %s' % F)
s = open(F).read()
if 'ROCMCS' in s:
    sys.exit('already patched')


def need(ok, what):
    if not ok:
        sys.exit('ERROR: anchor not found: %s\n--- nothing changed. Send this message back.' % what)


# ---------------------------------------------------------------- 1. option and detector list
A = "BLOCK = float(opt('--block', 0))"
need(s.count(A) == 1, "BLOCK = float(opt('--block', 0))")
s = s.replace(A, A + "\nDMCS = float(opt('--dmcs', 4))   # ROCMCS: MCS indices below the UE's own baseline", 1)

m = re.search(r'(?m)^DET\s*=\s*.+$', s)
need(m is not None, 'the definition of DET')
s = s[:m.end()] + ("\nDET = list(DET) + [x for x in ('D5', 'D6') if x not in DET]   # ROCMCS") + s[m.end():]

# ---------------------------------------------------------------- 2. per-UE MCS, same 100 ms tick
A = "    ev = events(d)\n"
need(s.count(A) == 1, 'ev = events(d)')
MCSLOAD = '''    # ROCMCS: mean MCS index per UE per report, from the six PDSCH MCS bins of the DU report.
    # The DU trace has no decodable clock, but its rows are written one per report per UE in
    # order, so instant k is t = (k+1) * period and the replay tick is the same 100 ms.
    mcs = {}
    _bins = ['CARR.PDSCHMCSDist.Bin%d.UEID' % i for i in range(1, 7)]
    _mid = [2.0, 7.0, 12.0, 17.0, 22.0, 27.0]
    for _f in sorted(glob.glob(os.path.join(d, 'du-cell-*.txt'))):
        try:
            _h = open(_f, encoding='latin-1', errors='replace')
        except TypeError:
            _h = open(_f)
        _cols = _h.readline().strip().split(',')
        _cols = [c.strip() for c in _cols]
        try:
            _ix = [_cols.index(b) for b in _bins]
            _iu = _cols.index('ueImsiComplete')
        except ValueError:
            _h.close(); continue
        _k = {}
        for _line in _h:
            _p = _line.rstrip('\\n').split(',')
            if len(_p) <= _ix[-1]:
                continue
            try:
                _u = int(_p[_iu])
            except ValueError:
                continue
            _k[_u] = _k.get(_u, 0) + 1
            _n = _t = 0.0
            for _j, _c in zip(_ix, _mid):
                try:
                    _v = float(_p[_j])
                except ValueError:
                    _v = 0.0
                _n += _v * _c; _t += _v
            if _t > 0:
                mcs.setdefault(_k[_u], {})[_u] = _n / _t
    ev = events(d)
'''
s = s.replace(A, MCSLOAD, 1)

A = "            o[u] = [srv, m, jam_true[srv]]"
need(s.count(A) == 1, 'o[u] = [srv, m, jam_true[srv]]')
s = s.replace(A, "            o[u] = [srv, m, jam_true[srv], mcs.get(r, {}).get(u)]   # ROCMCS", 1)

# ---------------------------------------------------------------- 3. blockage drops the MCS too
A = '''                        srv, m, jt = obs[q][u]
                        m = dict(m); m[srv] = (m[srv][0] - depth, m[srv][1] - depth)
                        obs[q][u] = [srv, m, jt]'''
need(s.count(A) == 1, 'the blockage injection')
B = '''                        srv, m, jt, mc = obs[q][u]
                        m = dict(m); m[srv] = (m[srv][0] - depth, m[srv][1] - depth)
                        # ROCMCS: a 15-30 dB loss on the serving link forces the lowest
                        # modulation, so blockage must move the MCS as well; otherwise the
                        # benign baseline is easier for the MCS detector than for the others
                        # and the comparison is rigged in its favour.
                        obs[q][u] = [srv, m, jt, (2.0 if mc is not None else None)]'''
s = s.replace(A, B, 1)

# ---------------------------------------------------------------- 4. the two detectors
A = "def detect(obs, drop, det, K):\n    base = {}; nbase = defaultdict(dict); cnt = defaultdict(int)"
need(s.count(A) == 1, 'the header of detect()')
s = s.replace(A, A + "\n    mbase = {}   # ROCMCS: per-UE MCS baseline, reset on handover like the SINR one", 1)

A = "        for u, (srv, m, jt) in obs[r].items():\n            rs, s = m[srv]"
need(s.count(A) == 1, 'the per-UE loop of detect()')
s = s.replace(A, "        for u, (srv, m, jt, mc) in obs[r].items():   # ROCMCS\n            rs, s = m[srv]", 1)

A = "                base[u] = [s, rs, srv, 1]; cnt[u] = 0; continue"
need(s.count(A) == 1, 'the baseline reset')
s = s.replace(A, "                base[u] = [s, rs, srv, 1]; cnt[u] = 0\n"
                 "                mbase[u] = [mc, srv, 1] if mc is not None else None   # ROCMCS\n"
                 "                continue", 1)

A = "            deg = s < S_LOW and b[0] - s >= drop\n"
need(s.count(A) == 1, 'the degraded test')
NEW = '''            deg = s < S_LOW and b[0] - s >= drop
            # ROCMCS: the modulation the scheduler actually used, against this UE's own baseline
            mb = mbase.get(u)
            degm = (mc is not None and mb is not None and mb[1] == srv and (mb[0] - mc) >= DMCS)
            if det == 'D5':
                deg = degm
'''
s = s.replace(A, NEW, 1)

A = "            if deg and det in ('D3', 'D4'):\n                deg = b[1] - rs < 3.0\n"
need(s.count(A) == 1, 'the RSRP branch')
s = s.replace(A, A + '''            if det == 'D6':   # ROCMCS: SINR drop, confirmed by the multi-link test or by the MCS
                degs = s < S_LOW and b[0] - s >= drop
                ml = False
                if degs:
                    dd = sorted(nbase[u][c] - m[c][1] for c in m if c != srv and c in nbase[u])
                    if dd:
                        med = dd[len(dd) // 2] if len(dd) % 2 else 0.5 * (dd[len(dd) // 2 - 1] + dd[len(dd) // 2])
                        ml = med >= drop / 2
                deg = degs and (ml or degm)
''', 1)

A = "                    b[3] += 1\n"
need(s.count(A) == 1, 'the baseline update')
s = s.replace(A, "                    b[3] += 1\n"
                 "                    if mc is not None:   # ROCMCS: track the MCS baseline too\n"
                 "                        if mb is None:\n"
                 "                            mbase[u] = [mc, srv, 1]\n"
                 "                        else:\n"
                 "                            mb[0] = (mb[0] * mb[2] + mc) / (mb[2] + 1) if mb[2] < 10 \\\n"
                 "                                    else 0.9 * mb[0] + 0.1 * mc\n"
                 "                            mb[2] += 1\n", 1)

# glob is needed by the loader
if re.search(r'(?m)^import .*\bglob\b', s) is None and re.search(r'(?m)^import glob', s) is None:
    m = re.search(r'(?m)^import .+$', s)
    need(m is not None, 'any import line')
    s = s[:m.end()] + '\nimport glob   # ROCMCS' + s[m.end():]

shutil.copy2(F, F + '.bak_mcs')
open(F, 'w').write(s)
print('patched:', F, '(backup at %s.bak_mcs)' % F)
print('new detectors: D5 (MCS drop), D6 (SINR confirmed by multi-link or MCS)')
print('new option: --dmcs <indices>   default 4')
