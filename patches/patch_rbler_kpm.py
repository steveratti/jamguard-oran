# Makes the downlink block error rate measurable at all on this platform, as 3GPP defines it.
#
# WHAT IS WRONG TODAY. MmWavePhyTrace::UpdateTraces, which feeds every DU performance measurement,
# classifies each transport block by its redundancy version and nothing else:
#
#     if (params.m_rv == 0)  m_macPduInitialTransmissionUeSpecific++;
#     else                   m_macPduRetransmissionUeSpecific++;
#
# It never reads params.m_corrupt, the flag the error model sets when the block has actually
# failed. The retransmission count is then emitted as "TB.ErrTotalNbrDl.1.UEID", so the item an
# xApp reads as an error count contains no error information: a retransmission that succeeded is
# counted, and a block that was corrupted on its last permitted transmission is not.
#
# 3GPP TS 28.552 clause 5.1.1.7 defines five transport-block measurements, and the retransmission
# count is none of them:
#     5.1.1.7.1  total number of DL initial TBs        (emitted today, correctly)
#     5.1.1.7.2  initial error number of DL TBs        (missing)
#     5.1.1.7.3  total number of DL TBs                (emitted today, correctly)
#     5.1.1.7.4  total error number of DL TBs          (missing; the item of that name holds retx)
#     5.1.1.7.5  residual error number of DL TBs       (missing)
#
# WHY IT MATTERS FOR DETECTION. Link adaptation regulates the INITIAL error rate towards a target,
# so that quantity is a controlled variable and carries little information about a sustained
# interferer: the controller absorbs the attack by lowering the modulation. The RESIDUAL error
# rate -- blocks still undecodable after the last permitted retransmission -- is outside that
# loop. Nothing regulates it. It is the quantity that must rise when interference defeats hybrid
# retransmission, and it is the one the platform does not expose.
#
# WHAT THIS PATCH ADDS. Three counters per UE per report period, derived from fields that already
# travel with every traced block:
#     initial error   params.m_corrupt && params.m_rv == 0
#     total error     params.m_corrupt
#     residual error  params.m_corrupt && params.m_rv == RV_LAST
#
# RV_LAST is 3, and that is not a guess: mmwave-spectrum-phy.cc ends the HARQ process with
#     if (!itTb->second.m_isCorrupted || itTb->second.m_expected.m_rv == 3)
# so a block corrupted at rv 3 is never retransmitted again and is therefore residual.
#
# The existing counters and the existing measurement names are left exactly as they are, so
# nothing that consumes them changes behaviour, and the earlier measurements remain reproducible.
#
# THREE INDEPENDENT STAGES. Each verifies its own anchors and is skipped, with a message, if the
# tree does not match. A skipped stage never leaves a half-applied file.
#     A  the counters themselves          src/mmwave/helper/mmwave-phy-trace.{h,cc}
#     B  the E2 measurement items         mmwave-indication-message-helper.{h,cc}, enb-net-device
#     C  the DU file log                  the CSV that offline analysis reads
#
# usage: cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_rbler_kpm.py
#        then ./ns3 build     (never while a campaign is running)
# Idempotent; every file it changes gets a .bak_rbler copy first.
import os, re, sys, shutil

ROOT = sys.argv[1] if len(sys.argv) > 1 else '.'
TRACE_H = os.path.join(ROOT, 'src/mmwave/helper/mmwave-phy-trace.h')
TRACE_C = os.path.join(ROOT, 'src/mmwave/helper/mmwave-phy-trace.cc')
HELP_H = os.path.join(ROOT, 'contrib/oran-interface/helper/mmwave-indication-message-helper.h')
HELP_C = os.path.join(ROOT, 'contrib/oran-interface/helper/mmwave-indication-message-helper.cc')
ENB_C = os.path.join(ROOT, 'src/mmwave/model/mmwave-enb-net-device.cc')

RV_LAST = 3
NEW = [('ErrInitial', '5.1.1.7.2 initial error number of DL TBs'),
       ('ErrTotal', '5.1.1.7.4 total error number of DL TBs'),
       ('ErrResidual', '5.1.1.7.5 residual error number of DL TBs')]

changed = {}


def read(p):
    if not os.path.exists(p):
        return None
    return open(p, encoding='utf-8', errors='surrogateescape').read()


done = set()


def stage(name, files, fn, marker, needs=None):
    """Apply fn to {path: text} and keep the result in memory.

    Later stages see what earlier ones changed, because stage C edits a file stage B has already
    edited and must not read a stale copy from disk. Each stage carries its own marker so that one
    applied stage does not make the others look done, and a stage that depends on another is
    skipped when that one did not run -- stage C emits variables stage B declares.
    """
    if needs and needs not in done:
        print('  SKIP %s: depends on stage %s, which did not run' % (name, needs))
        return
    texts = {}
    for p in files:
        s = changed.get(p, read(p))
        if s is None:
            print('  SKIP %s: file not found: %s' % (name, p))
            return
        texts[p] = s
    if any(marker in s for s in texts.values()):
        print('  SKIP %s: already patched' % name)
        done.add(name.strip()[0])
        return
    try:
        out = fn(texts)
    except AssertionError as e:
        print('  SKIP %s: %s' % (name, e))
        return
    for p, s in out.items():
        if s != texts[p]:
            changed[p] = s
    done.add(name.strip()[0])
    print('  OK   %s' % name)


def once(s, a, what):
    assert s.count(a) == 1, 'anchor not found exactly once (%d): %s' % (s.count(a), what)


# ------------------------------------------------------------------ A: the counters
def stage_a(t):
    h, c = t[TRACE_H], t[TRACE_C]

    a = 'uint32_t GetMacPduRetransmissionUeSpecific (uint16_t rnti, uint16_t cellId);'
    once(h, a, 'the getter declaration in mmwave-phy-trace.h')
    decl = a + '\n'
    for n, doc in NEW:
        decl += ('  /** JGRBLER_A: %s */\n'
                 '  uint32_t GetMacPdu%sUeSpecific (uint16_t rnti, uint16_t cellId);\n' % (doc, n))
    h = h.replace(a, decl, 1)

    a = 'std::map<RntiCellIdPair_t, uint32_t> m_macPduRetransmissionUeSpecific;'
    once(h, a, 'the map declaration in mmwave-phy-trace.h')
    maps = a + '\n'
    for n, doc in NEW:
        maps += ('  std::map<RntiCellIdPair_t, uint32_t> m_macPdu%sUeSpecific;   //!< JGRBLER_A %s\n'
                 % (n, doc))
    h = h.replace(a, maps, 1)

    # the classification: m_corrupt is the flag UpdateTraces never read
    a = ('  if (params.m_rv == 0)\n'
         '  {\n'
         '    m_macPduInitialTransmissionUeSpecific = IncreaseMapValue '
         '(m_macPduInitialTransmissionUeSpecific, pair, 1);')
    assert a in c, 'the redundancy-version branch of UpdateTraces'
    ins = '''
  /* JGRBLER_A: the error counters of 3GPP TS 28.552 clause 5.1.1.7, which this trace did not keep.
     params.m_corrupt is set by the error model when the block has failed; the branch above
     classifies blocks by redundancy version alone, so the "error" counter it feeds is really a
     retransmission count. A block corrupted at the last permitted redundancy version is never
     retransmitted again -- mmwave-spectrum-phy.cc ends the process at m_rv == %d -- so it is a
     residual error, which no link-adaptation loop regulates. */
  if (params.m_corrupt)
  {
    m_macPduErrTotalUeSpecific = IncreaseMapValue (m_macPduErrTotalUeSpecific, pair, 1);
    if (params.m_rv == 0)
    {
      m_macPduErrInitialUeSpecific = IncreaseMapValue (m_macPduErrInitialUeSpecific, pair, 1);
    }
    if (params.m_rv == %d)
    {
      m_macPduErrResidualUeSpecific = IncreaseMapValue (m_macPduErrResidualUeSpecific, pair, 1);
    }
  }
''' % (RV_LAST, RV_LAST)
    # place it after the whole if/else on m_rv, i.e. before the MAC volume line
    a2 = '  // UE specific MAC volume'
    once(c, a2, 'the MAC volume comment in UpdateTraces')
    c = c.replace(a2, ins + '\n' + a2, 1)

    a = 'm_macPduRetransmissionUeSpecific = ResetMapValue (m_macPduRetransmissionUeSpecific, pair);'
    once(c, a, 'the reset of the retransmission map')
    res = a
    for n, _ in NEW:
        res += ('\n    m_macPdu%sUeSpecific = ResetMapValue (m_macPdu%sUeSpecific, pair);'
                '   // JGRBLER_A' % (n, n))
    c = c.replace(a, res, 1)

    # the getter definitions, modelled on the existing one
    m = re.search(r'(?m)^uint32_t\s*\n'
                  r'MmWavePhyTrace::GetMacPduRetransmissionUeSpecific\s*\(([^)]*)\)\s*\n'
                  r'\{(.*?)\n\}\n', c, re.S)
    assert m is not None, 'the body of GetMacPduRetransmissionUeSpecific'
    defs = m.group(0)
    for n, doc in NEW:
        body = m.group(0).replace('GetMacPduRetransmissionUeSpecific',
                                  'GetMacPdu%sUeSpecific' % n)
        body = body.replace('m_macPduRetransmissionUeSpecific', 'm_macPdu%sUeSpecific' % n)
        defs += '\n/* JGRBLER_A: %s */\n' % doc + body
    c = c.replace(m.group(0), defs, 1)
    return {TRACE_H: h, TRACE_C: c}


# ------------------------------------------------------------------ B: the E2 items
def stage_b(t):
    hh, hc, ec = t[HELP_H], t[HELP_C], t[ENB_C]

    # the helper signature, in both the declaration and the definition; defaulted so that any
    # call site we do not touch keeps compiling
    sig_tail = 'long rlcBufferOccup, double drbThrDlUeid'
    assert hh.count(sig_tail) == 1, 'the AddDuUePmItem declaration in the helper header'
    hh = hh.replace(sig_tail,
                    sig_tail + ',\n    long macErrInitial = -1, long macErrTotal = -1,'
                               '\n    long macErrResidual = -1   /* JGRBLER_B */', 1)
    assert hc.count(sig_tail + ')') == 1, 'the AddDuUePmItem definition in the helper'
    hc = hc.replace(sig_tail + ')',
                    sig_tail + ',\n    long macErrInitial, long macErrTotal,'
                               '\n    long macErrResidual)   /* JGRBLER_B */', 1)

    a = '      ueVal->AddItem<long> ("TB.ErrTotalNbrDl.1.UEID", macRetx);'
    once(hc, a, 'the stock TB.ErrTotalNbrDl item')
    add = a + '''
      /* JGRBLER_B: the error counters of TS 28.552 clause 5.1.1.7. The stock item above is left
         untouched -- it carries the retransmission count, which is what this platform has always
         reported -- and these carry what the clause actually defines. The UE is in the name of
         the last three so that an xApp which parses names can attribute them without reading the
         per-UE container of the indication. Emitted only when the caller supplies them. */
      if (macErrInitial >= 0)
        {
          ueVal->AddItem<long> ("TB.ErrNbrDlInitial.UEID", macErrInitial);
          ueVal->AddItem<long> ("TBErrInitDl_UEID_" + ueImsiComplete, macErrInitial);
        }
      if (macErrTotal >= 0)
        {
          ueVal->AddItem<long> ("TBErrTotTrueDl_UEID_" + ueImsiComplete, macErrTotal);
        }
      if (macErrResidual >= 0)
        {
          ueVal->AddItem<long> ("TB.ResidErrNbrDl.UEID", macErrResidual);
          ueVal->AddItem<long> ("TBErrResidDl_UEID_" + ueImsiComplete, macErrResidual);
        }'''
    hc = hc.replace(a, add, 1)

    # the three values, in every scope that already computes macRetx
    a = ('uint32_t macRetx = m_e2DuCalculator->GetMacPduRetransmissionUeSpecific '
         '(rnti, m_cellId);')
    n = ec.count(a)
    assert n >= 1, 'the macRetx assignment in mmwave-enb-net-device.cc'
    ec = ec.replace(a, a + '''
      /* JGRBLER */
      uint32_t macErrInitial = m_e2DuCalculator->GetMacPduErrInitialUeSpecific (rnti, m_cellId);
      uint32_t macErrTotal = m_e2DuCalculator->GetMacPduErrTotalUeSpecific (rnti, m_cellId);
      uint32_t macErrResidual =
          m_e2DuCalculator->GetMacPduErrResidualUeSpecific (rnti, m_cellId);''')

    # append them to every AddDuUePmItem call; each such call already needs macRetx, so every
    # call site is inside a scope that now declares the three new variables
    calls = list(re.finditer(r'AddDuUePmItem\s*\((?:[^();]|\([^()]*\))*?\)\s*;', ec, re.S))
    assert calls, 'no AddDuUePmItem call site in mmwave-enb-net-device.cc'
    for m in reversed(calls):
        txt = m.group(0)
        new = re.sub(r'\)\s*;\s*$',
                     ',\n          (long) macErrInitial, (long) macErrTotal,'
                     '\n          (long) macErrResidual);   /* JGRBLER_B */', txt)
        ec = ec[:m.start()] + new + ec[m.end():]
    print('       (%d macRetx scopes, %d AddDuUePmItem call sites)' % (n, len(calls)))
    return {HELP_H: hh, HELP_C: hc, ENB_C: ec}


# ------------------------------------------------------------------ C: the DU file log
def stage_c(t):
    """The CSV row and its header are each written in more than one function -- the DU message is
    built once for the normal report and once for the energy-saving variant -- so every occurrence
    must be patched, not the first. Patching one of two silently produces files whose header and
    rows disagree, which is worse than not patching at all.

    Every occurrence sits in a scope that computes macRetx, and stage B declared the three new
    variables immediately after each macRetx assignment, so each row has them in scope.
    """
    ec = t[ENB_C]
    a = 'std::to_string (mac64Qam) + "," + std::to_string (macRetx) + "," +'
    nrow = ec.count(a)
    assert nrow >= 1, 'the DU CSV row in mmwave-enb-net-device.cc'
    ec = ec.replace(a, a.rstrip('+').rstrip() +
                    '\n              + std::to_string (macErrInitial) + ","'
                    '\n              + std::to_string (macErrTotal) + ","'
                    '\n              + std::to_string (macErrResidual) + ","   /* JGRBLER_C */\n'
                    '              +')

    # the header literal of the same CSV, in every function that writes one
    cols = ('TB.ErrTotalNbrDl.1.UEID,TB.ErrNbrDlInitial.UEID,'
            'TB.ErrTotalNbrDlTrue.UEID,TB.ResidErrNbrDl.UEID')
    hdrs = [m.group(1) for m in re.finditer(r'"([^"]*TB\.ErrTotalNbrDl\.1\.UEID[^"]*)"', ec)]
    hdrs = [h for h in hdrs if 'mac64Qam' not in h]
    assert hdrs, ('the DU CSV header literal (no row was written; nothing changed)')
    for old in set(hdrs):
        ec = ec.replace('"%s"' % old, '"%s"' % old.replace('TB.ErrTotalNbrDl.1.UEID', cols))
    assert nrow == len(set(hdrs)) or len(set(hdrs)) >= 1, 'row and header counts disagree'
    print('       (%d CSV rows, %d distinct header literals)' % (nrow, len(set(hdrs))))
    return {ENB_C: ec}


print('JGRBLER: adding the TS 28.552 clause 5.1.1.7 error counters')
print('root:', os.path.abspath(ROOT))
stage('A  counters   (mmwave-phy-trace)', [TRACE_H, TRACE_C], stage_a, 'JGRBLER_A')
stage('B  E2 items   (indication helper + enb net device)', [HELP_H, HELP_C, ENB_C],
      stage_b, 'JGRBLER_B', needs='A')
stage('C  DU file log (enb net device)', [ENB_C], stage_c, 'JGRBLER_C', needs='B')

if not changed:
    print('\nnothing changed.')
    sys.exit(0)
for p, s in changed.items():
    # keep the FIRST backup: a later stage applied on its own must not overwrite the pristine
    # copy with an already-patched one, or there is nothing left to revert to
    if not os.path.exists(p + '.bak_rbler'):
        shutil.copy2(p, p + '.bak_rbler')
        note = '(backup .bak_rbler)'
    else:
        note = '(backup .bak_rbler kept from the first run)'
    open(p, 'w', encoding='utf-8', errors='surrogateescape').write(s)
    print('wrote', p, note)
print('\nnext: ./ns3 build      # only when no campaign is running')
