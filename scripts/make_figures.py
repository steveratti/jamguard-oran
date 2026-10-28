#!/usr/bin/env python3
"""JamGuard paper figures (PNG 300 dpi + PDF) from the campaign folders.
usage: python3 ~/make_figures.py [campaign_root ~/jamx_F] [sweep_root ~/jamx_E] [out ~/jamguard_figs] [power 50]"""
import sys, os, re, glob, math, statistics as st, collections
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
ROOT = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/jamx_F')
SWEEP = os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else '~/jamx_E')
OUT = os.path.expanduser(sys.argv[3] if len(sys.argv) > 3 else '~/jamguard_figs')
PW = int(sys.argv[4] if len(sys.argv) > 4 else 50)
J0, J1, JX, JY = 4.0, 10.0, 710.0, 510.0
os.makedirs(OUT, exist_ok=True)
# fixed policy order and colours (validated categorical palette; baseline in neutral grey)
POL = [('p0', 'Default RAN', '#8a8a85'), ('p6', 'B1: MCS cap', '#eda100'), ('p5', 'B2: PRB reservation', '#e87ba4'),
       ('p1', 'JamGuard reactive', '#1baf7a'), ('p2', 'JamGuard + localization', '#2a78d6'),
       ('p4', 'JamGuard full (slice-aware)', '#eb6834')]
HATCH = {'p0': '', 'p6': '//', 'p5': '\\\\', 'p1': '..', 'p2': 'xx', 'p4': ''}
SLICES = {2: ('Military', 50.0), 5: ('Ambulance', 100.0)}
INK, MUTED, GRID = '#1f1f1d', '#6b6b66', '#e6e6e2'
plt.rcParams.update({'font.size': 9, 'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'xtick.color': MUTED,
                     'ytick.color': MUTED, 'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.6,
                     'axes.axisbelow': True, 'axes.spines.top': False, 'axes.spines.right': False,
                     'legend.frameon': False, 'figure.dpi': 100, 'savefig.bbox': 'tight'})
def save(fig, name):
    for ext in ('png', 'pdf'):
        fig.savefig(os.path.join(OUT, name + '.' + ext), dpi=300)
    plt.close(fig); print('wrote', name)
def runs(pol, pw=PW, root=ROOT):
    out = []
    for d in sorted(glob.glob('%s/pw%d_%s_s*' % (root, pw, pol))):
        try:
            last = float(open(d + '/ue_rx.txt').read().strip().splitlines()[-1].split(',')[0])
        except Exception:
            continue
        if last >= 13.5: out.append(d)
    return out
def ue_rx(d):
    R = collections.defaultdict(dict)
    for line in open(d + '/ue_rx.txt'):
        x = line.split(',')
        try: R[int(x[1])][round(float(x[0]), 1)] = (float(x[2]), float(x[3]), float(x[4]))
        except (ValueError, IndexError): pass
    return R
def offered(R, im):
    a, b = R[im].get(1.0), R[im].get(4.0)
    return (b[0] - a[0]) / 3.0 if a and b else None
def window_stats(d, im, t0=J0, t1=J1):
    R = ue_rx(d); r = R.get(im, {})
    a = r.get(round(t0, 1)); b = r.get(round(t1, 1)) or r.get(max(k for k in r if k <= t1))
    off = offered(R, im)
    if not a or not b or not off: return None
    deliv = 100.0 * (b[0] - a[0]) / (t1 - t0) / off
    delay = (b[2] - a[2]) / (b[1] - a[1]) * 1000 if b[1] > a[1] else float('nan')
    return deliv, delay
def embb_imsis(d):
    return [im for im in ue_rx(d) if im not in SLICES and im != 9]
def pkt(d, ims, t0=J0, t1=J1):
    v = collections.defaultdict(list)
    f = d + '/pkt_delay.txt'
    if not os.path.exists(f): return v
    for line in open(f):
        x = line.split(',')
        try: t, im, dl = float(x[0]) / 1000, int(x[1]), float(x[2]) / 1000
        except (ValueError, IndexError): continue
        if im in ims and t0 < t <= t1: v[im].append(dl)
    return v
def ms(v): return (st.mean(v), st.stdev(v) if len(v) > 1 else 0.0) if v else (float('nan'), 0.0)

# ---------- Fig 1/2: delivery and mean delay per slice (jammer window) ----------
def fig_bars(metric, ylabel, name):
    groups = ['Military', 'Ambulance', 'eMBB (mean of 7)']
    fig, ax = plt.subplots(figsize=(7.0, 2.8))
    present = [p for p in POL if runs(p[0])]
    w = 0.8 / max(len(present), 1)
    for j, (pk, lab, col) in enumerate(present):
        vals = {g: [] for g in groups}
        for d in runs(pk):
            for im, (sl, _) in SLICES.items():
                s = window_stats(d, im)
                if s: vals[sl].append(s[metric])
            e = [window_stats(d, im) for im in embb_imsis(d)]
            e = [x[metric] for x in e if x and x[metric] == x[metric]]
            if e: vals[groups[2]].append(st.mean(e))
        for i, g in enumerate(groups):
            m, sd = ms(vals[g])
            ax.bar(i - 0.4 + w * (j + 0.5), m, w * 0.92, yerr=sd, color=col, hatch=HATCH[pk], edgecolor='white',
                   linewidth=0.6, error_kw={'elinewidth': 0.8, 'capsize': 2, 'ecolor': INK}, label=lab if i == 0 else None)
    ax.set_xticks(range(len(groups))); ax.set_xticklabels(groups)
    ax.set_ylabel(ylabel); ax.grid(axis='x', visible=False)
    if metric == 0:
        lo = min([b.get_height() for b in ax.patches if b.get_height() == b.get_height()] or [60])
        ax.set_ylim(max(0, 10 * math.floor((lo - 5) / 10)), 101)
    ax.legend(ncol=3, fontsize=7.5, loc='lower center', bbox_to_anchor=(0.5, 1.02))
    save(fig, name)

# ---------- Fig 3: per-packet delay CDF of the critical slices ----------
def fig_cdf():
    fig, axs = plt.subplots(1, 2, figsize=(7.0, 2.6), sharey=True)
    for ax, (im, (sl, ddl)) in zip(axs, SLICES.items()):
        for pk, lab, col in POL:
            v = []
            for d in runs(pk): v += pkt(d, [im])[im]
            if not v: continue
            v.sort(); n = len(v)
            ax.plot(v, [(i + 1) / n for i in range(n)], color=col, lw=1.6, label=lab)
        ax.axvline(ddl, color=MUTED, lw=0.8, ls='--'); ax.text(ddl * 1.08, 0.5, 'deadline\n%d ms' % ddl, color=MUTED, fontsize=7)
        ax.set_xscale('log'); ax.set_xlabel('one-way packet delay (ms)'); ax.set_title(sl, fontsize=9, color=INK)
    axs[0].set_ylabel('CDF')
    h, l = axs[0].get_legend_handles_labels()
    fig.legend(h, l, ncol=3, fontsize=7.5, loc='lower center', bbox_to_anchor=(0.5, 0.98))
    save(fig, 'fig3_delay_cdf')

# ---------- Fig 4: tail latency and deadline miss ----------
def fig_tail():
    fig, axs = plt.subplots(1, 2, figsize=(7.0, 2.6))
    present = [p for p in POL if runs(p[0])]
    for ax, what in zip(axs, ('p95', 'miss')):
        for i, (im, (sl, ddl)) in enumerate(SLICES.items()):
            w = 0.8 / max(len(present), 1)
            for j, (pk, lab, col) in enumerate(present):
                vals = []
                for d in runs(pk):
                    v = sorted(pkt(d, [im])[im])
                    if not v: continue
                    vals.append(v[int(0.95 * (len(v) - 1))] if what == 'p95' else 100.0 * sum(x > ddl for x in v) / len(v))
                m, sd = ms(vals)
                ax.bar(i - 0.4 + w * (j + 0.5), m, w * 0.92, yerr=sd, color=col, hatch=HATCH[pk], edgecolor='white',
                       linewidth=0.6, error_kw={'elinewidth': 0.8, 'capsize': 2}, label=lab if i == 0 else None)
        ax.set_xticks([0, 1]); ax.set_xticklabels([s[0] for s in SLICES.values()]); ax.grid(axis='x', visible=False)
        ax.set_ylabel('95th-percentile delay (ms)' if what == 'p95' else 'packets over deadline (%)')
    h, l = axs[0].get_legend_handles_labels()
    fig.legend(h, l, ncol=3, fontsize=7.5, loc='lower center', bbox_to_anchor=(0.5, 0.98))
    save(fig, 'fig4_tail_latency')

# ---------- Fig 5: timeline of one run (military UE): SINR, then throughput (p0 vs p4) ----------
def fig_timeline(seed=1, im=2):
    d0 = '%s/pw%d_p0_s%d' % (ROOT, PW, seed); d4 = '%s/pw%d_p4_s%d' % (ROOT, PW, seed)
    if not (os.path.exists(d0 + '/ue_rx.txt') and os.path.exists(d4 + '/ue_rx.txt')): return
    fig, axs = plt.subplots(3, 1, figsize=(7.0, 5.2), sharex=True, gridspec_kw={'height_ratios': [1, 1, 0.45]})
    t, s = [], []
    f = d4 + '/MmWaveJammerRx.txt'
    if os.path.exists(f):
        acc = collections.defaultdict(list)
        for line in open(f):
            x = line.split()
            if len(x) > 6 and x[1].isdigit() and int(x[1]) == im: acc[round(float(x[0]), 1)].append(float(x[6]))
        t = sorted(acc); s = [st.mean(acc[k]) for k in t]
    axs[0].plot(t, s, color='#2a78d6', lw=1.2); axs[0].set_ylabel('NR SINR (dB)')
    axs[0].axhline(0, color=MUTED, lw=0.6, ls=':')
    for dd, lab, col in ((d0, 'Default RAN', '#8a8a85'), (d4, 'JamGuard full', '#eb6834')):
        r = ue_rx(dd)[im]; ks = sorted(r)
        tt = [k for a, k in zip(ks, ks[1:])]; th = [(r[k][0] - r[a][0]) * 8 / (k - a) / 1e6 for a, k in zip(ks, ks[1:])]
        axs[1].plot(tt, th, color=col, lw=1.3, label=lab)
    axs[1].set_ylabel('throughput (Mb/s)'); axs[1].legend(fontsize=7.5, loc='lower left')
    # lane: data path of the military UE under JamGuard (LTE anchor vs NR), from the switch traces
    ev = []
    for fn in ('LteSwitchStats.txt', 'MmWaveSwitchStats.txt'):
        p = d4 + '/' + fn
        if not os.path.exists(p): continue
        for line in open(p):
            x = line.replace('=', ' ').split()
            if 'imsi' in x and int(x[x.index('imsi') + 1]) == im and x[0].startswith('SwitchTo'):
                ev.append((float(x[1]), x[0].startswith('SwitchToLte')))
    ev.sort(); state, t0 = False, 0.0
    for te, lte in ev + [(14.0, None)]:
        axs[2].barh(0, te - t0, left=t0, height=0.6, color='#eb6834' if state else '#cde2fb', edgecolor='white')
        if lte is None: break
        state, t0 = lte, te
    axs[2].set_yticks([0]); axs[2].set_yticklabels(['data path']); axs[2].grid(False)
    axs[2].set_title('military data path: light = NR, orange = LTE anchor (JamGuard full)', fontsize=7.5, color=MUTED, loc='left')
    for ax in axs[:2]:
        ax.axvspan(J0, J1, color='#e87ba4', alpha=0.10, lw=0)
    jg = d4 + '/jamguard_local.csv'
    if os.path.exists(jg):
        for line in list(open(jg))[1:]:
            x = line.split(',', 14)
            if x[2] in ('DETECT', 'PROBE_OK'):
                for ax in axs[:2]: ax.axvline(float(x[0]), color=INK, lw=0.7, ls='--')
                axs[0].text(float(x[0]) + 0.08, axs[0].get_ylim()[1] * 0.85, x[2], fontsize=7, color=INK)
    axs[0].text((J0 + J1) / 2, axs[0].get_ylim()[1] * 0.85, 'jammer on', fontsize=7, color=MUTED, ha='center')
    axs[2].set_xlabel('time (s)'); axs[2].set_xlim(1, 14)
    axs[0].set_title('Military UE, %d dBm jammer, seed %d' % (PW, seed), fontsize=8.5, color=MUTED)
    save(fig, 'fig5_timeline')

# ---------- Fig 6: localization of one run ----------
def fig_localization(seed=1):
    d = '%s/pw%d_p4_s%d' % (ROOT, PW, seed)
    if not os.path.exists(d + '/jamguard_local.csv'): return
    pos = {}
    for line in open(d + '/log.txt', errors='ignore'):
        m = re.match(r'\[JGL\] sanity UE (\d+) .*pos \(([-\d.]+),([-\d.]+)\)', line)
        if m: pos[int(m.group(1))] = (float(m.group(2)), float(m.group(3)))
    est = []
    for line in list(open(d + '/jamguard_local.csv'))[1:]:
        x = line.split(',', 14)
        if x[2] == 'LOCALIZE' and J0 <= float(x[0]) <= J1: est.append((float(x[0]), float(x[11]), float(x[12]), float(x[13])))
    fig, ax = plt.subplots(figsize=(3.6, 3.4))
    for im, (x, y) in pos.items():
        col = '#2a78d6' if im not in SLICES else '#eb6834'
        ax.plot(x, y, 'o', ms=6, color=col, mec='white', mew=1.2)
        ax.text(x + 12, y + 10, 'UE%d' % im, fontsize=6.5, color=MUTED)
    if est:
        ax.plot([e[1] for e in est], [e[2] for e in est], '-', color=MUTED, lw=0.8)
        ax.plot(est[0][1], est[0][2], 's', ms=6, color=INK, label='first estimate')
        ax.plot(est[-1][1], est[-1][2], 'D', ms=6, color=INK, mfc='white', label='last estimate')
        ax.add_patch(Circle((est[-1][1], est[-1][2]), est[-1][3], fill=False, ls='--', lw=0.9, color=MUTED))
        err = math.hypot(est[0][1] - JX, est[0][2] - JY)
        ax.set_title('first-estimate error %.0f m' % err, fontsize=8.5, color=MUTED)
    ax.plot(JX, JY, '*', ms=13, color='#e87ba4', mec=INK, mew=0.6, label='true jammer')
    ax.set_xlim(0, 1000); ax.set_ylim(0, 1000); ax.set_aspect('equal'); ax.set_xlabel('x (m)'); ax.set_ylabel('y (m)')
    ax.plot([], [], 'o', color='#eb6834', label='critical UE'); ax.plot([], [], 'o', color='#2a78d6', label='eMBB UE')
    ax.legend(fontsize=7, loc='upper left', bbox_to_anchor=(1.02, 1.0))
    save(fig, 'fig6_localization')

# ---------- Fig 7: E2 loop-delay sweep ----------
def fig_sweep():
    ds = sorted(int(re.sub(r'\D', '', os.path.basename(p))) for p in glob.glob(SWEEP + '/d*'))
    if not ds: return
    fig, axs = plt.subplots(1, 2, figsize=(7.0, 2.5))
    for im, (sl, ddl) in SLICES.items():
        col = '#eb6834' if im == 2 else '#2a78d6'
        dv, mv = [], []
        for dl in ds:
            rr = runs('p4', root='%s/d%d' % (SWEEP, dl))
            dv.append(ms([s[0] for s in (window_stats(d, im) for d in rr) if s]))
            vals = []
            for d in rr:
                v = pkt(d, [im])[im]
                if v: vals.append(100.0 * sum(x > ddl for x in v) / len(v))
            mv.append(ms(vals))
        axs[0].errorbar(ds, [m for m, _ in dv], yerr=[s for _, s in dv], color=col, marker='o', ms=4, lw=1.6, capsize=2, label=sl)
        axs[1].errorbar(ds, [m for m, _ in mv], yerr=[s for _, s in mv], color=col, marker='o', ms=4, lw=1.6, capsize=2, label=sl)
    for ax in axs: ax.set_xscale('log'); ax.set_xlabel('E2 control-loop delay (ms)'); ax.axvline(1000, color=MUTED, lw=0.6, ls=':')
    axs[0].set_ylabel('delivery in jammer window (%)'); axs[1].set_ylabel('packets over deadline (%)')
    axs[0].legend(fontsize=7.5)
    save(fig, 'fig7_e2_delay_sweep')

fig_bars(0, 'delivery ratio (%)', 'fig1_delivery')
fig_bars(1, 'mean packet delay (ms)', 'fig2_mean_delay')
fig_cdf(); fig_tail(); fig_timeline(); fig_localization(); fig_sweep()
print('figures in', OUT)
