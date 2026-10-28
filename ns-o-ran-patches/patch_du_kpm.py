# ns-O-RAN library fix: the E2 DU KPM report silently depends on the file-tracing subsystem.
#
# WHAT WE FOUND (by reading the library, confirmed by empty counters in 496 runs)
#   MmWaveEnbNetDevice::BuildRicIndicationMessageDu reads every per-UE DU measurement
#   (TB.TotNbrDl, TB.ErrTotalNbrDl, RRU.PrbUsedDl, CARR.PDSCHMCSDist.*, L1M.RS-SINR.*) from
#   m_e2DuCalculator, which is a MmWavePhyTrace. That object is fed in exactly one place:
#   MmWavePhyTrace::UpdateTraces(), called at the END of RxPacketTraceUeCallback. That callback
#   is attached to the PHY only by MmWaveHelper::EnableDlPhyTrace/EnableUlPhyTrace, which are
#   called only from MmWaveHelper::EnableTraces(). A scenario that does not call EnableTraces()
#   -- the normal choice for a campaign, because the per-transport-block trace file is huge --
#   therefore sends an E2 DU indication in which every per-UE counter is zero, with no warning.
#   Worse, measurement and logging are welded together: UpdateTraces() sits behind an
#   unconditional write of one line per transport block to RxPacketTrace.txt, flushed with
#   std::endl, so there is no way to obtain the KPMs without paying for the file.
#
# WHY IT MATTERS
#   Any xApp built on BLER, PRB usage or the MCS distribution -- the basis of the BLER-threshold
#   detector and MCS-capping mitigation in the literature -- cannot be reproduced on stock
#   ns-O-RAN unless the scenario happens to enable file traces.
#
# THE FIX (three parts, all in the library)
#   1. MmWavePhyTrace gains a static switch, set through SetWriteRxPacketTraceFile(), that
#      separates the measurement from the log file. Default true, so existing behaviour is
#      unchanged.
#   2. EnableDlPhyTrace/EnableUlPhyTrace take writeFile (default true) and become idempotent, so
#      connecting them twice can no longer double-count every transport block.
#   3. MmWaveHelper connects them with writeFile=false as soon as E2 is enabled for a gNB, so the
#      DU report is populated whether or not the scenario enables traces. A later explicit
#      EnableTraces() turns the file back on without reconnecting.
#
# usage: cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_du_kpm.py
#        then ./ns3 build     (NOT while a campaign is running)
# Idempotent. Every anchor is checked; on a mismatch nothing is written and the expected text is
# printed, because this edits the library and a half-applied patch is worse than none.
import os, sys, shutil

ROOT = sys.argv[1] if len(sys.argv) > 1 else '.'
PT_H = os.path.join(ROOT, 'src/mmwave/helper/mmwave-phy-trace.h')
PT_C = os.path.join(ROOT, 'src/mmwave/helper/mmwave-phy-trace.cc')
MH_H = os.path.join(ROOT, 'src/mmwave/helper/mmwave-helper.h')
MH_C = os.path.join(ROOT, 'src/mmwave/helper/mmwave-helper.cc')

for f in (PT_H, PT_C, MH_H, MH_C):
    if not os.path.exists(f):
        print('ERROR: not found:', f)
        print('       run this from the root of the ns-3 tree (mmwave-LENA-oran)')
        sys.exit(1)

src = {f: open(f).read() for f in (PT_H, PT_C, MH_H, MH_C)}

if 'E2DUFIX' in src[PT_C]:
    print('already patched')
    sys.exit(0)

edits = []   # (file, old, new, description)

# ---------------------------------------------------------------- 1. mmwave-phy-trace.h
edits.append((PT_H,
 '    Time GetLastResetTime(uint16_t rnti, uint16_t cellId);\n',
 '    Time GetLastResetTime(uint16_t rnti, uint16_t cellId);\n'
 '\n'
 '    /**\n'
 '     * E2DUFIX: enable or disable the per-transport-block reception trace file, without\n'
 '     * affecting the measurements that feed the E2 DU KPM report. Default: enabled.\n'
 '     */\n'
 '    static void SetWriteRxPacketTraceFile(bool writeFile);\n',
 'declare SetWriteRxPacketTraceFile'))

edits.append((PT_H,
 '    static std::ofstream m_rxPacketTraceFile;   //!< Output stream for the PHY reception trace\n',
 '    static bool m_writeRxPacketTraceFile;       //!< E2DUFIX: write the PHY reception trace file\n'
 '    static std::ofstream m_rxPacketTraceFile;   //!< Output stream for the PHY reception trace\n',
 'declare m_writeRxPacketTraceFile'))

# ---------------------------------------------------------------- 2. mmwave-phy-trace.cc
edits.append((PT_C,
 'std::ofstream MmWavePhyTrace::m_rxPacketTraceFile;\n',
 'bool MmWavePhyTrace::m_writeRxPacketTraceFile = true;   // E2DUFIX\n'
 'std::ofstream MmWavePhyTrace::m_rxPacketTraceFile;\n',
 'define m_writeRxPacketTraceFile'))

edits.append((PT_C,
 'TypeId\nMmWavePhyTrace::GetTypeId(void)\n',
 'void\n'
 'MmWavePhyTrace::SetWriteRxPacketTraceFile(bool writeFile)   // E2DUFIX\n'
 '{\n'
 '    m_writeRxPacketTraceFile = writeFile;\n'
 '}\n'
 '\n'
 'TypeId\n'
 'MmWavePhyTrace::GetTypeId(void)\n',
 'define SetWriteRxPacketTraceFile'))

# guard the DL file write; UpdateTraces() stays outside the guard, which is the whole point
OLD_DL = '''    if (!m_rxPacketTraceFile.is_open())
    {
        m_rxPacketTraceFile.open(m_rxPacketTraceFilename.c_str());
        m_rxPacketTraceFile << "DL/"
                               "UL\\ttime\\tframe\\tsubF\\tslot\\t1stSym\\tsymbol#"
                               "\\tcellId\\trnti\\tccId\\ttbSize\\tmcs\\trv\\tSINR(dB)\\tcorrupt\\tTBler"
                            << std::endl;
        if (!m_rxPacketTraceFile.is_open())
        {
            NS_FATAL_ERROR("Could not open tracefile");
        }
    }
    m_rxPacketTraceFile << "DL\\t" << Simulator::Now().GetSeconds() << "\\t" << params.m_frameNum
                        << "\\t" << +params.m_sfNum << "\\t" << +params.m_slotNum << "\\t"
                        << +params.m_symStart << "\\t" << +params.m_numSym << "\\t" << params.m_cellId
                        << "\\t" << params.m_rnti << "\\t" << +params.m_ccId << "\\t"
                        << params.m_tbSize << "\\t" << +params.m_mcs << "\\t" << +params.m_rv << "\\t"
                        << 10 * std::log10(params.m_sinr) << "\\t" << params.m_corrupt << "\\t"
                        << params.m_tbler << std::endl;
'''
NEW_DL = '''    if (m_writeRxPacketTraceFile)   // E2DUFIX: logging is now independent of the measurement
    {
        if (!m_rxPacketTraceFile.is_open())
        {
            m_rxPacketTraceFile.open(m_rxPacketTraceFilename.c_str());
            m_rxPacketTraceFile << "DL/"
                                   "UL\\ttime\\tframe\\tsubF\\tslot\\t1stSym\\tsymbol#"
                                   "\\tcellId\\trnti\\tccId\\ttbSize\\tmcs\\trv\\tSINR(dB)\\tcorrupt\\tTBler"
                                << std::endl;
            if (!m_rxPacketTraceFile.is_open())
            {
                NS_FATAL_ERROR("Could not open tracefile");
            }
        }
        m_rxPacketTraceFile << "DL\\t" << Simulator::Now().GetSeconds() << "\\t" << params.m_frameNum
                            << "\\t" << +params.m_sfNum << "\\t" << +params.m_slotNum << "\\t"
                            << +params.m_symStart << "\\t" << +params.m_numSym << "\\t"
                            << params.m_cellId << "\\t" << params.m_rnti << "\\t" << +params.m_ccId
                            << "\\t" << params.m_tbSize << "\\t" << +params.m_mcs << "\\t"
                            << +params.m_rv << "\\t" << 10 * std::log10(params.m_sinr) << "\\t"
                            << params.m_corrupt << "\\t" << params.m_tbler << std::endl;
    }
'''
edits.append((PT_C, OLD_DL, NEW_DL, 'guard the DL trace-file write'))

OLD_UL = '''    if (!m_rxPacketTraceFile.is_open())
    {
        m_rxPacketTraceFile.open(m_rxPacketTraceFilename.c_str());
        m_rxPacketTraceFile << "DL/"
                               "UL\\ttime\\tframe\\tsubF\\tslot\\t1stSym\\tsymbol#"
                               "\\tcellId\\trnti\\tccId\\ttbSize\\tmcs\\trv\\tSINR(dB)\\tcorrupt\\tTBler"
                            << std::endl;
        if (!m_rxPacketTraceFile.is_open())
        {
            NS_FATAL_ERROR("Could not open tracefile");
        }
    }
    m_rxPacketTraceFile << "UL\\t" << Simulator::Now().GetSeconds() << "\\t" << params.m_frameNum
                        << "\\t" << +params.m_sfNum << "\\t" << +params.m_slotNum << "\\t"
                        << +params.m_symStart << "\\t" << +params.m_numSym << "\\t" << params.m_cellId
                        << "\\t" << params.m_rnti << "\\t" << +params.m_ccId << "\\t"
                        << params.m_tbSize << "\\t" << +params.m_mcs << "\\t" << +params.m_rv << "\\t"
                        << 10 * std::log10(params.m_sinr) << " \\t" << params.m_corrupt << "\\t"
                        << params.m_tbler << std::endl;
'''
NEW_UL = '''    if (m_writeRxPacketTraceFile)   // E2DUFIX
    {
        if (!m_rxPacketTraceFile.is_open())
        {
            m_rxPacketTraceFile.open(m_rxPacketTraceFilename.c_str());
            m_rxPacketTraceFile << "DL/"
                                   "UL\\ttime\\tframe\\tsubF\\tslot\\t1stSym\\tsymbol#"
                                   "\\tcellId\\trnti\\tccId\\ttbSize\\tmcs\\trv\\tSINR(dB)\\tcorrupt\\tTBler"
                                << std::endl;
            if (!m_rxPacketTraceFile.is_open())
            {
                NS_FATAL_ERROR("Could not open tracefile");
            }
        }
        m_rxPacketTraceFile << "UL\\t" << Simulator::Now().GetSeconds() << "\\t" << params.m_frameNum
                            << "\\t" << +params.m_sfNum << "\\t" << +params.m_slotNum << "\\t"
                            << +params.m_symStart << "\\t" << +params.m_numSym << "\\t"
                            << params.m_cellId << "\\t" << params.m_rnti << "\\t" << +params.m_ccId
                            << "\\t" << params.m_tbSize << "\\t" << +params.m_mcs << "\\t"
                            << +params.m_rv << "\\t" << 10 * std::log10(params.m_sinr) << " \\t"
                            << params.m_corrupt << "\\t" << params.m_tbler << std::endl;
    }
'''
edits.append((PT_C, OLD_UL, NEW_UL, 'guard the UL trace-file write'))

# ---------------------------------------------------------------- 3. mmwave-helper.h
edits.append((MH_H,
 '    void EnableDlPhyTrace();\n    void EnableUlPhyTrace();\n',
 '    void EnableDlPhyTrace(bool writeFile = true);   // E2DUFIX: writeFile=false -> KPMs only\n'
 '    void EnableUlPhyTrace(bool writeFile = true);   // E2DUFIX\n',
 'add the writeFile parameter'))

edits.append((MH_H,
 '    Ptr<MmWavePhyTrace> m_phyStats;\n',
 '    Ptr<MmWavePhyTrace> m_phyStats;\n'
 '    bool m_dlPhyTraceConnected{false};   //!< E2DUFIX: guards against connecting twice\n'
 '    bool m_ulPhyTraceConnected{false};   //!< E2DUFIX\n'
 '    bool m_e2PhyTraceScheduled{false};   //!< E2DUFIX: connection scheduled for t=0\n',
 'add the idempotency flags'))

# ---------------------------------------------------------------- 4. mmwave-helper.cc
edits.append((MH_C,
 'MmWaveHelper::EnableDlPhyTrace(void)\n{\n',
 'MmWaveHelper::EnableDlPhyTrace(bool writeFile)\n'
 '{\n'
 '    // E2DUFIX: an explicit call re-enables the trace file; connect the sinks only once, because\n'
 '    // a second connection would count every transport block twice in the DU measurements.\n'
 '    if (writeFile)\n'
 '    {\n'
 '        MmWavePhyTrace::SetWriteRxPacketTraceFile(true);\n'
 '    }\n'
 '    if (m_dlPhyTraceConnected)\n'
 '    {\n'
 '        return;\n'
 '    }\n'
 '    m_dlPhyTraceConnected = true;\n',
 'guard EnableDlPhyTrace'))

edits.append((MH_C,
 'MmWaveHelper::EnableUlPhyTrace(void)\n{\n    NS_LOG_FUNCTION_NOARGS();\n',
 'MmWaveHelper::EnableUlPhyTrace(bool writeFile)\n'
 '{\n'
 '    NS_LOG_FUNCTION_NOARGS();\n'
 '    // E2DUFIX\n'
 '    if (writeFile)\n'
 '    {\n'
 '        MmWavePhyTrace::SetWriteRxPacketTraceFile(true);\n'
 '    }\n'
 '    if (m_ulPhyTraceConnected)\n'
 '    {\n'
 '        return;\n'
 '    }\n'
 '    m_ulPhyTraceConnected = true;\n',
 'guard EnableUlPhyTrace'))

edits.append((MH_C,
 '        device->SetAttribute("E2DuCalculator", PointerValue(m_phyStats));\n',
 '        device->SetAttribute("E2DuCalculator", PointerValue(m_phyStats));\n'
 '        // E2DUFIX: BuildRicIndicationMessageDu reads every per-UE counter from m_phyStats, which\n'
 '        // is fed only by the PHY trace sinks connected in EnableDlPhyTrace/EnableUlPhyTrace.\n'
 '        // Without this, a scenario that does not call EnableTraces() reports an E2 DU message\n'
 '        // whose per-UE values are all zero. The connection is deferred to t=0 because the Config\n'
 '        // paths match only objects that already exist, and the UE devices -- which carry the\n'
 '        // downlink RxPacketTraceUe source -- are installed after the gNBs. writeFile is false so\n'
 '        // that enabling E2 does not also start the per-transport-block trace file; a later\n'
 '        // explicit EnableTraces() turns that file on without reconnecting the sinks.\n'
 '        if (!m_e2PhyTraceScheduled)\n'
 '        {\n'
 '            m_e2PhyTraceScheduled = true;\n'
 '            Simulator::Schedule(Seconds(0.0), &MmWaveHelper::EnableDlPhyTrace, this, false);\n'
 '            Simulator::Schedule(Seconds(0.0), &MmWaveHelper::EnableUlPhyTrace, this, false);\n'
 '        }\n',
 'connect the DU measurement sinks when E2 is enabled'))

# Simulator::Schedule is used by the edit above; Seconds() already appears in this file, but
# simulator.h is only reached transitively, so make the dependency explicit.
if '<ns3/simulator.h>' not in src[MH_C]:
    if '#include <ns3/string.h>\n' in src[MH_C]:
        src[MH_C] = src[MH_C].replace('#include <ns3/string.h>\n',
                                      '#include <ns3/simulator.h>   // E2DUFIX\n'
                                      '#include <ns3/string.h>\n', 1)
    else:
        src[MH_C] = src[MH_C].replace('#include "mmwave-helper.h"\n',
                                      '#include "mmwave-helper.h"\n'
                                      '\n#include <ns3/simulator.h>   // E2DUFIX\n', 1)

# ---------------------------------------------------------------- apply
for f, old, new, what in edits:
    if src[f].count(old) != 1:
        print('ERROR: anchor for "%s" found %d times in %s (expected 1)'
              % (what, src[f].count(old), os.path.relpath(f, ROOT)))
        print('--- expected exactly this text:')
        print(old)
        print('--- nothing has been changed. Send this message back.')
        sys.exit(1)

for f, old, new, what in edits:
    src[f] = src[f].replace(old, new, 1)

for f in src:
    shutil.copy2(f, f + '.bak_e2du')
    open(f, 'w').write(src[f])
    print('patched:', os.path.relpath(f, ROOT))
print()
print('%d edits applied. Backups: *.bak_e2du' % len(edits))
print('next: ./ns3 build     # only when no campaign is running')
