# Rejects non-physical application-delay samples in the ns-3 scenario.
#
# WHY. The delay of each downlink packet is taken from the SeqTsSizeHeader that PacketSink parses.
# PacketSink reassembles the byte stream before parsing that header, so when the data path of a UE
# is moved (LTE fallback or NR handover) the datagram boundary can be lost once and the next header
# is parsed from inside a payload. The timestamp is then payload bytes: in one of 496 runs this gave
# a single sample of about -1.13e6 s (2^50 ns), which poisoned the cumulative delay counter of that
# UE for the rest of the run (eMBB mean delay -17153 ms in jamx_RC/v3_full/pw50_p4_s2).
#
# WHAT. XappDelayRx now rejects a sample that is negative, NaN, or larger than JG_DLY_MAX (10 s by
# default), counts it per UE, and logs it to delay_rejected.txt. ue_rx.txt gets a new LAST column
# dly_bad, so a poisoned run can never again pass unnoticed. Rejected samples are also kept out of
# pkt_delay.txt, which feeds the tail-latency and deadline-miss analysis.
#
# The guard is deliberately not configurable away: a non-physical delay is never valid data.
# JG_DLY_MAX only moves the upper bound, for scenarios with longer simulated times.
#
# usage: cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_delay_guard.py
#        (then ./ns3 build -- NOT while a campaign is running, linking a running binary fails)
# Idempotent: running it twice changes nothing.
import os, sys, shutil

F = sys.argv[1] if len(sys.argv) > 1 else 'scratch/scenario_jam_xapp.cc'
if not os.path.exists(F):
    print('ERROR: not found:', F)
    print('       run this from ~/ns-O-RAN-flexric/mmwave-LENA-oran')
    sys.exit(1)
src = open(F).read()

if 'DLYGUARD' in src:
    print('already patched:', F)
    sys.exit(0)

# ---------------------------------------------------------------- 1. the callback
OLD_FN = '''  auto& e = g_ueDelay[imsi];
  e.first += (ns3::Simulator::Now () - h.GetTs ()).GetSeconds ();
  e.second++;
  // LATENCY PATCH: per-packet one-way delay for p50/p95/p99 and deadline-miss analysis
  static std::ofstream s_pkt ("pkt_delay.txt");
  s_pkt << (long long) ns3::Simulator::Now ().GetMilliSeconds () << "," << imsi << ","
        << (long long) (ns3::Simulator::Now () - h.GetTs ()).GetMicroSeconds () << "," << h.GetSeq () << "\\n";'''

NEW_FN = '''  // DLYGUARD: PacketSink reassembles the stream before parsing SeqTsSizeHeader. When a UE data path
  // is moved the datagram boundary can be lost once and the next header is read from inside a
  // payload, giving a non-physical timestamp (observed: 2^50 ns). Count and drop such a sample so
  // that the cumulative counters stay usable.
  const double jgDly = (ns3::Simulator::Now () - h.GetTs ()).GetSeconds ();
  if (!(jgDly >= 0.0) || jgDly > g_dlyMax)
    {
      g_ueDelayBad[imsi]++;
      static std::ofstream s_bad ("delay_rejected.txt");
      s_bad << ns3::Simulator::Now ().GetSeconds () << "," << imsi << "," << jgDly << ","
            << h.GetSeq () << "\\n";
      s_bad.flush ();
      return;
    }
  auto& e = g_ueDelay[imsi];
  e.first += jgDly;
  e.second++;
  // LATENCY PATCH: per-packet one-way delay for p50/p95/p99 and deadline-miss analysis
  static std::ofstream s_pkt ("pkt_delay.txt");
  s_pkt << (long long) ns3::Simulator::Now ().GetMilliSeconds () << "," << imsi << ","
        << (long long) (jgDly * 1e6) << "," << h.GetSeq () << "\\n";'''

if OLD_FN not in src:
    print('ERROR: the body of XappDelayRx does not look as expected in', F)
    sys.exit(1)
src = src.replace(OLD_FN, NEW_FN, 1)

# ---------------------------------------------------------------- 2. the two globals
OLD_G = 'static std::map<uint64_t, std::pair<double, uint64_t>> g_ueDelay; // imsi -> (sum of delays [s], packets)'
NEW_G = (OLD_G + '\n'
         'static std::map<uint64_t, uint64_t> g_ueDelayBad;   // DLYGUARD: imsi -> rejected samples\n'
         'static const double g_dlyMax =                      // DLYGUARD: upper bound [s]\n'
         '  (std::getenv ("JG_DLY_MAX") != nullptr) ? std::atof (std::getenv ("JG_DLY_MAX")) : 10.0;')
if OLD_G not in src:
    print('ERROR: g_ueDelay declaration not found in', F)
    sys.exit(1)
src = src.replace(OLD_G, NEW_G, 1)

# cstdlib for getenv/atof, right before the block that uses them
if '#include <cstdlib>' not in src:
    src = src.replace('// SLICE PATCH: application-level one-way delay per UE',
                      '#include <cstdlib>   // DLYGUARD: getenv, atof\n'
                      '// SLICE PATCH: application-level one-way delay per UE', 1)

# ---------------------------------------------------------------- 3. the ue_rx.txt writer
OLD_H = '*rxOut << "t_s,imsi,rx_bytes,dly_pkts,dly_sum_s\\n";'
NEW_H = '*rxOut << "t_s,imsi,rx_bytes,dly_pkts,dly_sum_s,dly_bad\\n";   // DLYGUARD: new last column'
if OLD_H not in src:
    print('ERROR: the ue_rx.txt header line was not found in', F)
    sys.exit(1)
src = src.replace(OLD_H, NEW_H, 1)

OLD_R = ('*rxOut << Simulator::Now ().GetSeconds () << "," << p.first << "," << p.second->GetTotalRx () '
         '<< "," << g_ueDelay[p.first].second << "," << g_ueDelay[p.first].first << "\\n";')
NEW_R = ('*rxOut << Simulator::Now ().GetSeconds () << "," << p.first << "," << p.second->GetTotalRx () '
         '<< "," << g_ueDelay[p.first].second << "," << g_ueDelay[p.first].first '
         '<< "," << g_ueDelayBad[p.first] << "\\n";')
if OLD_R not in src:
    print('ERROR: the ue_rx.txt row line was not found in', F)
    sys.exit(1)
src = src.replace(OLD_R, NEW_R, 1)

shutil.copy2(F, F + '.bak_dlyguard')
open(F, 'w').write(src)
print('patched:', F, '(backup at %s.bak_dlyguard)' % F)
print('next: ./ns3 build     # only when no campaign is running')
