#!/usr/bin/env python3
"""Does the RESIDUAL block error rate detect a jammer, where the regulated one cannot?

Background. Link adaptation drives the INITIAL block error rate towards an operating point, so
that quantity is a controlled variable: under a sustained interferer the controller lowers the
modulation and the error rate returns to target. The RESIDUAL error rate -- blocks still
undecodable after the last permitted HARQ redundancy version -- is outside that loop. Nothing
regulates it. If interference defeats hybrid retransmission, it must rise.

Until now this platform could not be asked the question. MmWavePhyTrace::UpdateTraces classified
transport blocks by redundancy version alone and never read params.m_corrupt, so the item emitted
as TB.ErrTotalNbrDl carried a retransmission count, not an error count. The three counters of
3GPP TS 28.552 clause 5.1.1.7 are now emitted (patches/patch_rbler_kpm.py):

    TB.ErrNbrDlInitial.UEID     corrupt on the first transmission      (5.1.1.7.2)
    TB.ErrTotalNbrDlTrue.UEID   corrupt on any transmission            (5.1.1.7.4)
    TB.ResidErrNbrDl.UEID       corrupt at the last redundancy version (5.1.1.7.5)

This script reports four things, in the order in which they can falsify the idea:

  (1) SANITY. Counter relations that must hold by construction. If they do not, the counters are
      wrong and nothing below means anything.
  (2) LEVELS. The three rates, before and during the attack, against attack-free runs. The
      initial rate should sit near the loop's target and barely move; the residual rate is the
      one with room to move. This is also the first honest measurement of this platform's
      initial BLER, which the retransmission count could not give.
  (3) SEPARATION. A detector's worth is not a mean. Windowed per-UE residual rate, how many UEs
      exceed a threshold, and what that costs on attack-free runs -- the same shape of answer as
      the SINR detectors are scored with.
  (4) ONSET. Whether the residual rate moves when the jammer starts, at report resolution.

usage:
  python3 rbler_check.py --pos '~/jamx_RB/pos50_s*' --neg '~/jamx_RB/neg_s*'
                         [--t0 4] [--t1 10] [--win 10] [--beta 0.01,0.02,0.05,0.10] [--k 1,2,3]
"""
import argparse, glob, os, sys
import pandas as pd

TOT = 'TB.TotNbrDl.1.UEID'
INI = 'TB.TotNbrDlInitial.UEID'
EIN = 'TB.ErrNbrDlInitial.UEID'
ETO = 'TB.ErrTotalNbrDlTrue.UEID'
ERE = 'TB.ResidErrNbrDl.UEID'
NEED = [TOT, INI, EIN, ETO, ERE]


def sim_time(run):
    p = os.path.join(run, 'ue_rx.txt')
    try:
        with open(p, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400))
            return float(f.read().decode(errors='ignore').strip().splitlines()[-1].split(',')[0])
    except Exception:
        return None


def load(run):
    """-> long DataFrame: t, ue, tot, ini, ein, eto, ere (one row per UE per report instant)."""
    frames = []
    for f in sorted(glob.glob(os.path.join(run, 'du-cell-*.txt'))):
        try:
            d = pd.read_csv(f, encoding='latin-1', on_bad_lines='skip')
        except Exception:
            continue
        d.columns = [c.strip() for c in d.columns]
        miss = [c for c in NEED if c not in d.columns]
        if miss:
            return ('missing', miss)
        d['k'] = d.groupby('ueImsiComplete').cumcount()
        cols = {'k': d.k, 'ue': d.ueImsiComplete}
        for name, c in (('tot', TOT), ('ini', INI), ('ein', EIN), ('eto', ETO), ('ere', ERE)):
            cols[name] = pd.to_numeric(d[c], errors='coerce').fillna(0)
        frames.append(pd.DataFrame(cols))
    if not frames:
        return None
    a = pd.concat(frames).groupby(['k', 'ue'], as_index=False)[
        ['tot', 'ini', 'ein', 'eto', 'ere']].sum()
    T = sim_time(run)
    if not T or a.empty:
        return None
    per = T / (a.k.max() + 1)
    a = a[a.ini > 0].copy()
    a['t'] = (a.k + 1) * per
    a.attrs['per'] = per
    return a


def rates(df):
    """(initial, total, residual) error rates, each over the denominator the clause implies."""
    i = df.ini.sum()
    t = df.tot.sum()
    if i <= 0 or t <= 0:
        return (float('nan'),) * 3
    return (df.ein.sum() / i, df.eto.sum() / t, df.ere.sum() / i)


def fmt(x):
    return '%.4f' % x if x == x else '--'


# ------------------------------------------------------------------ (1) sanity
def sanity(runs):
    print('\n(1) SANITY -- relations that hold by construction\n')
    print('    %-14s %-10s %-10s %-9s %-9s %-9s %s'
          % ('run', 'initial', 'total', 'errInit', 'errTot', 'errResid', 'all hold?'))
    ok_all = True
    for run in runs:
        a = load(run)
        if isinstance(a, tuple):
            print('    %-14s columns missing: %s' % (os.path.basename(run)[:14], ', '.join(a[1])))
            print('\n    the run was produced by a binary without the patch, or before the build.')
            return False
        if a is None:
            continue
        i, t = a.ini.sum(), a.tot.sum()
        ein, eto, ere = a.ein.sum(), a.eto.sum(), a.ere.sum()
        checks = [ein <= i,          # a first transmission can fail at most once per block
                  ere <= eto,        # a residual error is one of the total errors
                  ein <= eto,        # so is an initial error
                  t >= i]            # total transmissions include the initial ones
        ok_all &= all(checks)
        print('    %-14s %-10.0f %-10.0f %-9.0f %-9.0f %-9.0f %s'
              % (os.path.basename(run)[:14], i, t, ein, eto, ere,
                 'yes' if all(checks) else 'NO ' + str([int(c) for c in checks])))
    print('\n    checks: errInit<=initial, errResid<=errTot, errInit<=errTot, total>=initial')
    if not ok_all:
        print('    a failed check means the counters are wrong; stop and fix them before reading on.')
    return ok_all


# ------------------------------------------------------------------ (2) levels
def levels(pos, neg, t0, t1):
    print('\n(2) LEVELS -- the three rates, before and during the attack\n')
    print('    %-14s %-6s %-10s %-10s %-10s %s'
          % ('run', 'window', 'iBLER', 'totBLER', 'rBLER', 'rBLER/iBLER'))
    for kind, runs in (('atk', pos), ('free', neg)):
        for run in runs:
            a = load(run)
            if a is None or isinstance(a, tuple):
                continue
            for lab, w in (('pre', a[a.t < t0]), ('attack', a[(a.t > t0) & (a.t <= t1)])):
                if w.empty:
                    continue
                i, t, r = rates(w)
                ratio = (r / i) if (i == i and i > 0 and r == r) else float('nan')
                print('    %-14s %-6s %-10s %-10s %-10s %s'
                      % (os.path.basename(run)[:14] if lab == 'pre' else '', lab,
                         fmt(i), fmt(t), fmt(r), ('%.3f' % ratio) if ratio == ratio else '--'))
    print('\n    iBLER is what link adaptation regulates: it should sit near the loop target and')
    print('    move little. rBLER is outside the loop. If rBLER rises under the jammer while')
    print('    iBLER does not, the residual counter carries the signal the regulated one cannot.')
    print('    If neither moves, the error path is not where this jammer shows up at all.')


# ------------------------------------------------------------------ (3) separation
def separation(pos, neg, t0, t1, win, betas, ks):
    print('\n(3) SEPARATION -- windowed per-UE residual rate as a detector\n')
    print('    window: %d reports   attack runs: %d   attack-free runs: %d'
          % (win, len(pos), len(neg)))

    def flags(run, beta):
        """-> (max UEs over beta during the attack window, max over an attack-free run)."""
        a = load(run)
        if a is None or isinstance(a, tuple):
            return None
        p = a.pivot_table(index='k', columns='ue', values=['ere', 'ini'], aggfunc='sum')
        e = p['ere'].rolling(win, min_periods=max(1, win // 2)).sum()
        n = p['ini'].rolling(win, min_periods=max(1, win // 2)).sum()
        r = (e / n).where(n > 0)
        per = a.attrs['per']
        r.index = [(k + 1) * per for k in r.index]
        return r

    print('\n    %-7s %-3s  %-7s %-9s %-9s %s' % ('beta', 'K', 'Pd', 'delay_s', 'FA/min', 'benign_s'))
    for beta in betas:
        for K in ks:
            det, dly, nrun = 0, [], 0
            for run in pos:
                r = flags(run, beta)
                if r is None:
                    continue
                nrun += 1
                hot = (r >= beta).sum(axis=1)
                w = hot[(hot.index > t0) & (hot.index <= t1)]
                hit = w[w >= K]
                if len(hit):
                    det += 1
                    dly.append(max(0.0, hit.index[0] - t0))
            fa, secs = 0, 0.0
            for run in neg:
                r = flags(run, beta)
                if r is None:
                    continue
                hot = (r >= beta).sum(axis=1)
                secs += float(hot.index[-1]) if len(hot) else 0.0
                on = False
                for v in hot.values:
                    if v >= K and not on:
                        fa += 1
                        on = True
                    elif v < K:
                        on = False
            print('    %-7.3f %-3d  %-7.3f %-9s %-9.2f %.0f'
                  % (beta, K, det / max(1, nrun),
                     ('%.2f' % (sum(dly) / len(dly))) if dly else '--',
                     fa / (secs / 60.0) if secs else 0.0, secs))
    print('\n    comparable with the SINR detectors on the constant jammer: D2 reaches Pd 1.00 at')
    print('    0.00 false alarms per minute. A residual-rate detector is only interesting if it')
    print('    does that too, or if it does it where the SINR detectors score Pd near zero.')


# ------------------------------------------------------------------ (4) onset
def onset(pos, t0, horizon=1.5, pre=1.5):
    print('\n(4) ONSET -- residual rate per report around the jammer start\n')
    for run in pos:
        a = load(run)
        if a is None or isinstance(a, tuple):
            continue
        per = a.attrs['per']
        g = a[(a.t >= t0 - pre) & (a.t <= t0 + horizon)].copy()
        if g.empty:
            continue
        g['rel'] = ((g.t - t0) / per).round().astype(int)
        s = g.groupby('rel').apply(lambda x: x.ere.sum() / max(1.0, x.ini.sum()),
                                   include_groups=False)
        offs = [o for o in sorted(s.index) if o >= -3]
        print('    %-14s %s' % (os.path.basename(run)[:14],
                                ' '.join('%.3f' % s[o] for o in offs)))
    print('    (columns are reports; the first three precede the jammer)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pos', required=True)
    ap.add_argument('--neg', required=True)
    ap.add_argument('--t0', type=float, default=4.0)
    ap.add_argument('--t1', type=float, default=10.0)
    ap.add_argument('--win', type=int, default=10)
    ap.add_argument('--beta', default='0.005,0.01,0.02,0.05,0.10')
    ap.add_argument('--k', default='1,2,3')
    ap.add_argument('--runs', type=int, default=5)
    a = ap.parse_args()
    pos = sorted(glob.glob(os.path.expanduser(a.pos)))[:a.runs]
    neg = sorted(glob.glob(os.path.expanduser(a.neg)))[:a.runs]
    if not pos or not neg:
        sys.exit('no runs matched: pos=%d neg=%d' % (len(pos), len(neg)))
    print('attack runs: %s' % ', '.join(os.path.basename(r) for r in pos))
    print('attack-free: %s' % ', '.join(os.path.basename(r) for r in neg))
    if not sanity(pos[:2] + neg[:2]):
        sys.exit(1)
    levels(pos, neg, a.t0, a.t1)
    separation(pos, neg, a.t0, a.t1, a.win,
               [float(x) for x in a.beta.split(',')], [int(x) for x in a.k.split(',')])
    onset(pos, a.t0)


if __name__ == '__main__':
    main()
