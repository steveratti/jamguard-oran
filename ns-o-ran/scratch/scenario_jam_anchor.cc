/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/*
 * Scenario A (revised): resource-exhaustion UE anomaly for SIEM-side detection.
 *
 * Same deployment as the jammer dataset (jammer_gnb3.cc): 1 LTE anchor + 4 gNBs at
 * (500,500), (700,500), (400,673.2), (400,326.8), 3.5 GHz / 20 MHz, gNB 44 dBm,
 * 3GPP UMi Street Canyon, RandomWalk2dOutdoor 3-7 m/s, E2 KPM every 50 ms.
 *
 * Every UE receives benign downlink traffic with a random profile (light / medium /
 * heavy, ON/OFF). In each run nAttackers UEs, chosen at random from the RngRun seed,
 * additionally receive a constant downlink UDP flood of attackRateMbps from attackStart
 * on (DL flooding of a victim UE / compromised UE pulling traffic). All random draws
 * are made in both the attack run and the control run (anomalyOn=false), so a control
 * run with the same RngRun has identical mobility, benign traffic and "would-be"
 * attackers; only the flood is not started.
 *
 * Ground truth is written to anomaly.txt.
 *
 * Example:
 *   ./ns3 run "scenario_anomaly_ue --RngRun=7 --anomalyOn=1 --attackRateMbps=20 \
 *              --enableE2FileLogging=1 --enableTraces=0"
 *
 * Based on scenario-zero (Orange Innovation / ns-O-RAN authors, GPLv2):
 * Andrea Lacava, Michele Polese, Argha Sen, Kamil Kociszewski, Mostafa Ashraf.
 * This program is free software; you can redistribute it and/or modify it under the
 * terms of the GNU General Public License version 2 as published by the Free Software
 * Foundation.
 */
#include <functional>
#include <memory>
#include <fstream>
#include "ns3/packet-sink.h"
#include "ns3/waveform-generator-helper.h"   // JGLTEJAM
#include "ns3/waveform-generator.h"
#include "ns3/non-communicating-net-device.h"
#include "ns3/lte-spectrum-value-helper.h"
#include "ns3/lte-enb-net-device.h"
#include "ns3/lte-enb-phy.h"
#include "ns3/lte-spectrum-phy.h"

#include <ns3/slice-registry.h>
#include "ns3/seq-ts-size-header.h"
#include "ns3/node-list.h"
#include "ns3/mmwave-enb-net-device.h"
#include "ns3/mmwave-enb-mac.h"
#include "ns3/lte-enb-rrc.h"
#include <sstream>
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/applications-module.h"
#include "ns3/point-to-point-helper.h"
#include <ns3/lte-ue-net-device.h>
#include "ns3/mmwave-helper.h"
#include "ns3/epc-helper.h"
#include "ns3/mmwave-point-to-point-epc-helper.h"
#include "../src/mmwave/model/node-container-manager.h"
#include "ns3/lte-helper.h"
#include "ns3/isotropic-antenna-model.h"
#include "ns3/mmwave-enb-phy.h"
#include "ns3/channel-condition-model.h"
#include "ns3/three-gpp-propagation-loss-model.h"
#include <sys/time.h>
#include <ctime>
#include <iostream>
#include <fstream>
#include <vector>
#include <algorithm>
#include <cmath>
#include "jamguard_local.h"

using namespace ns3;
using namespace mmwave;

int ue_assoc_list[64] = {0};
double maxXAxis;
double maxYAxis;

NS_LOG_COMPONENT_DEFINE ("ScenarioAnomalyUe");

void
PrintGnuplottableUeListToFile (std::string filename)
{
  std::ofstream outFile (filename.c_str (), std::ios_base::out | std::ios_base::trunc);
  if (!outFile.is_open ())
    {
      return;
    }
  for (NodeList::Iterator it = NodeList::Begin (); it != NodeList::End (); ++it)
    {
      Ptr<Node> node = *it;
      for (uint32_t j = 0; j < node->GetNDevices (); j++)
        {
          Ptr<McUeNetDevice> mcuedev = node->GetDevice (j)->GetObject<McUeNetDevice> ();
          if (mcuedev)
            {
              Vector pos = node->GetObject<MobilityModel> ()->GetPosition ();
              outFile << "set label \"" << mcuedev->GetImsi () << "\" at " << pos.x << "," << pos.y
                      << " left font \"Helvetica,8\" textcolor rgb \"black\" front point pt 1 ps "
                         "0.3 lc rgb \"black\" offset 0,0"
                      << std::endl;
            }
        }
    }
}

void
PrintGnuplottableEnbListToFile (uint64_t m_startTime)
{
  uint64_t timestamp = m_startTime + (uint64_t) Simulator::Now ().GetMilliSeconds ();
  for (NodeList::Iterator it = NodeList::Begin (); it != NodeList::End (); ++it)
    {
      Ptr<Node> node = *it;
      for (uint32_t j = 0; j < node->GetNDevices (); j++)
        {
          Ptr<LteEnbNetDevice> enbdev = node->GetDevice (j)->GetObject<LteEnbNetDevice> ();
          Ptr<MmWaveEnbNetDevice> mmdev = node->GetDevice (j)->GetObject<MmWaveEnbNetDevice> ();
          if (enbdev)
            {
              Vector pos = node->GetObject<MobilityModel> ()->GetPosition ();
              std::ofstream f ("enbs.txt", std::ios_base::out | std::ios_base::app);
              f << timestamp << "," << enbdev->GetCellId () << "," << pos.x << "," << pos.y << ","
                << m_startTime << ",0,30" << std::endl;
            }
          else if (mmdev)
            {
              Vector pos = node->GetObject<MobilityModel> ()->GetPosition ();
              auto ueMap = mmdev->GetUeMap ();
              for (const auto &ue : ueMap)
                {
                  uint64_t imsi_assoc = ue.second->GetImsi ();
                  if (imsi_assoc >= 1 && imsi_assoc <= 64)
                    {
                      ue_assoc_list[imsi_assoc - 1] = mmdev->GetCellId ();
                    }
                }
              std::ofstream f ("gnbs.txt", std::ios_base::out | std::ios_base::app);
              f << timestamp << "," << mmdev->GetCellId () << "," << pos.x << "," << pos.y << ","
                << m_startTime << ",0,0,0,0" << std::endl;
            }
        }
    }
}

void
ClearFile (std::string filename, uint64_t m_startTime)
{
  uint64_t timestamp = m_startTime + (uint64_t) Simulator::Now ().GetMilliSeconds ();
  std::ofstream f (filename.c_str (), std::ios_base::out | std::ios_base::trunc);
  if (filename == "ue_position.txt")
    {
      f << "timestamp,id,x,y,type,cell,simid" << std::endl;
    }
  else
    {
      f << "timestamp,id,x,y,simid,ESstate,currEC,maxEC,totalcurrEC" << std::endl;
      f << timestamp << ",0," << maxXAxis << "," << maxYAxis << std::endl;
    }
}

void
PrintPosition (Ptr<Node> node, std::string filename, uint64_t m_startTime)
{
  uint64_t timestamp = m_startTime + (uint64_t) Simulator::Now ().GetMilliSeconds ();
  for (uint32_t j = 0; j < node->GetNDevices (); j++)
    {
      Ptr<McUeNetDevice> mcuedev = node->GetDevice (j)->GetObject<McUeNetDevice> ();
      if (mcuedev)
        {
          int imsi = int (mcuedev->GetImsi ());
          int serving_cell = (imsi >= 1 && imsi <= 64) ? ue_assoc_list[imsi - 1] : 0;
          Vector position = node->GetObject<MobilityModel> ()->GetPosition ();
          std::ofstream f (filename.c_str (), std::ios_base::out | std::ios_base::app);
          f << timestamp << "," << imsi << "," << position.x << "," << position.y << ",mc,"
            << serving_cell << "," << m_startTime << std::endl;
        }
    }
}

static ns3::GlobalValue g_bufferSize ("bufferSize", "RLC tx buffer size (MB)",
                                      ns3::UintegerValue (10), ns3::MakeUintegerChecker<uint32_t> ());
static ns3::GlobalValue g_enableTraces ("enableTraces", "If true, generate ns-3 traces",
                                        ns3::BooleanValue (true), ns3::MakeBooleanChecker ());
static ns3::GlobalValue g_e2lteEnabled ("e2lteEnabled", "If true, send LTE E2 reports",
                                        ns3::BooleanValue (true), ns3::MakeBooleanChecker ());
static ns3::GlobalValue g_e2nrEnabled ("e2nrEnabled", "If true, send NR E2 reports",
                                       ns3::BooleanValue (true), ns3::MakeBooleanChecker ());
static ns3::GlobalValue g_e2du ("e2du", "If true, send DU reports", ns3::BooleanValue (true),
                                ns3::MakeBooleanChecker ());
static ns3::GlobalValue g_e2cuUp ("e2cuUp", "If true, send CU-UP reports", ns3::BooleanValue (true),
                                  ns3::MakeBooleanChecker ());
static ns3::GlobalValue g_e2cuCp ("e2cuCp", "If true, send CU-CP reports", ns3::BooleanValue (true),
                                  ns3::MakeBooleanChecker ());
static ns3::GlobalValue g_reducedPmValues ("reducedPmValues", "If true, use a subset of the pm containers",
                                           ns3::BooleanValue (false), ns3::MakeBooleanChecker ());
static ns3::GlobalValue g_hoSinrDifference ("hoSinrDifference",
                                            "The value for which an handover between MmWave eNB is triggered",
                                            ns3::DoubleValue (0.0), ns3::MakeDoubleChecker<double> ());
static ns3::GlobalValue g_indicationPeriodicity ("indicationPeriodicity",
                                                 "E2 Indication Periodicity reports (value in seconds)",
                                                 ns3::DoubleValue (0.05),
                                                 ns3::MakeDoubleChecker<double> (0.01, 2.0));
#include <cstdlib>   // DLYGUARD: getenv, atof
// SLICE PATCH: application-level one-way delay per UE (SeqTsSizeHeader written by OnOff, read by PacketSink)
static std::map<uint64_t, std::pair<double, uint64_t>> g_ueDelay; // imsi -> (sum of delays [s], packets)
static std::map<uint64_t, uint64_t> g_ueDelayBad;   // DLYGUARD: imsi -> rejected samples
static const double g_dlyMax =                      // DLYGUARD: upper bound [s]
  (std::getenv ("JG_DLY_MAX") != nullptr) ? std::atof (std::getenv ("JG_DLY_MAX")) : 10.0;
static void
XappDelayRx (uint64_t imsi, ns3::Ptr<const ns3::Packet> p, const ns3::Address& from, const ns3::Address& to,
             const ns3::SeqTsSizeHeader& h)
{
  // DLYGUARD: PacketSink reassembles the stream before parsing SeqTsSizeHeader. When a UE data path
  // is moved the datagram boundary can be lost once and the next header is read from inside a
  // payload, giving a non-physical timestamp (observed: 2^50 ns). Count and drop such a sample so
  // that the cumulative counters stay usable.
  const double jgDly = (ns3::Simulator::Now () - h.GetTs ()).GetSeconds ();
  if (!(jgDly >= 0.0) || jgDly > g_dlyMax)
    {
      g_ueDelayBad[imsi]++;
      static std::ofstream s_bad ("delay_rejected.txt");
      s_bad << ns3::Simulator::Now ().GetSeconds () << "," << imsi << "," << jgDly << ","
            << h.GetSeq () << "\n";
      s_bad.flush ();
      return;
    }
  auto& e = g_ueDelay[imsi];
  e.first += jgDly;
  e.second++;
  // LATENCY PATCH: per-packet one-way delay for p50/p95/p99 and deadline-miss analysis
  static std::ofstream s_pkt ("pkt_delay.txt");
  s_pkt << (long long) ns3::Simulator::Now ().GetMilliSeconds () << "," << imsi << ","
        << (long long) (jgDly * 1e6) << "," << h.GetSeq () << "\n";
}

static ns3::GlobalValue g_simTime ("simTime", "Simulation time in seconds", ns3::DoubleValue (60.0),
                                   ns3::MakeDoubleChecker<double> (0.1, 100000.0));
static ns3::GlobalValue g_outageThreshold ("outageThreshold", "SNR threshold for outage events [dB]",
                                           ns3::DoubleValue (-15.0), ns3::MakeDoubleChecker<double> ());
static ns3::GlobalValue g_numberOfRaPreambles ("numberOfRaPreambles",
                                               "how many random access preambles are available",
                                               ns3::UintegerValue (40),
                                               ns3::MakeUintegerChecker<uint8_t> ());
#include "ns3/constant-velocity-mobility-model.h" /* JGMOB */
#include <fstream>
static std::ofstream g_jtrack;                       /* JGMOB jammer ground-truth track */
static ns3::Ptr<ns3::MobilityModel> g_jmob;
static void JgTrack ()
{
  ns3::Vector q = g_jmob->GetPosition ();
  g_jtrack << ns3::Simulator::Now ().GetSeconds () << "," << q.x << "," << q.y << std::endl;
  ns3::Simulator::Schedule (ns3::MilliSeconds (100), &JgTrack);
}
static void JgTrackStart (ns3::Ptr<ns3::MobilityModel> m)
{
  g_jmob = m;
  g_jtrack.open ("jammer_track.txt", std::ios_base::out | std::ios_base::trunc);
  g_jtrack << "t_s,x,y" << std::endl;
  ns3::Simulator::Schedule (ns3::Seconds (0), &JgTrack);
}

static ns3::GlobalValue g_handoverMode ("handoverMode", "HO euristic to be used",
                                        ns3::StringValue ("Threshold"), ns3::MakeStringChecker ());
static ns3::GlobalValue g_e2TermIp ("e2TermIp", "The IP address of the RIC E2 termination",
                                    ns3::StringValue ("127.0.0.1"), ns3::MakeStringChecker ());
static ns3::GlobalValue g_enableE2FileLogging ("enableE2FileLogging",
                                               "If true, generate offline file logging instead of connecting to RIC",
                                               ns3::BooleanValue (false), ns3::MakeBooleanChecker ());
static ns3::GlobalValue g_e2_func_id ("KPM_E2functionID", "Function ID to subscribe",
                                      ns3::DoubleValue (2), ns3::MakeDoubleChecker<double> ());
static ns3::GlobalValue g_rc_e2_func_id ("RC_E2functionID", "Function ID to subscribe",
                                         ns3::DoubleValue (3), ns3::MakeDoubleChecker<double> ());
static ns3::GlobalValue g_controlFileName ("controlFileName", "The path to the control file",
                                           ns3::StringValue (""), ns3::MakeStringChecker ());
static ns3::GlobalValue mmWave_nodes ("N_MmWaveEnbNodes", "Number of mmWaveNodes",
                                      ns3::UintegerValue (4), ns3::MakeUintegerChecker<uint8_t> ());
static ns3::GlobalValue ue_s ("N_Ues", "Number of User Equipments", ns3::UintegerValue (10),
                              ns3::MakeUintegerChecker<uint32_t> ());
static ns3::GlobalValue center_freq ("CenterFrequency", "Center Frequency Value",
                                     ns3::DoubleValue (3.5e9), ns3::MakeDoubleChecker<double> ());
static ns3::GlobalValue bandwidth_value ("Bandwidth", "Bandwidth Value", ns3::DoubleValue (20e6),
                                         ns3::MakeDoubleChecker<double> ());
static ns3::GlobalValue interside_distance_value_cell ("IntersideDistanceCells", "Interside Distance Value",
                                                       ns3::DoubleValue (200),
                                                       ns3::MakeDoubleChecker<double> ());

/* JGLTEJAM: the LTE-anchor jammer follows the NR jammer on/off schedule */
static Ptr<WaveformGenerator> g_jgLteJam;
static bool g_jgLteJamOn = false;
static void
JgSetAllJammers (bool on)
{
  MmWaveEnbPhy::SetJammersActive (on);
  if (g_jgLteJam && on != g_jgLteJamOn)
    {
      if (on) g_jgLteJam->Start (); else g_jgLteJam->Stop ();
      g_jgLteJamOn = on;
    }
}

int
main (int argc, char *argv[])
{
  Config::SetDefault ("ns3::MmWaveUePhy::NoiseFigure", DoubleValue (9.0));
  Config::SetDefault ("ns3::ThreeGppChannelModel::Blockage", BooleanValue (true));
  maxXAxis = 1000;
  maxYAxis = 1000;

  // ---------------- anomaly parameters (command line) ----------------
  bool anomalyOn = true;          // false = attack-free control run (same seed, same draws)
  uint32_t nAttackers = 2;        // UEs that receive the flood
  double attackRateMbps = 20.0;   // DL flood rate per attacked UE
  double attackStart = 10.0;      // s; the first seconds are attack-free in every run
  bool jammerOn = false;
  double jammerX = 710.0, jammerY = 510.0, jammerZ = 1.5, jammerPowerDbm = 50.0;
  double jammerVx = 0.0, jammerVy = 0.0; // JGMOB
  std::string attackDir = "dl";   // "dl": flood towards the UE; "ul": flood from the UE
  uint32_t pktSize = 1000;        // bytes, all applications
  CommandLine cmd;
  cmd.AddValue ("anomalyOn", "Start the flood (false = control run)", anomalyOn);
  cmd.AddValue ("nAttackers", "Number of anomalous UEs", nAttackers);
  cmd.AddValue ("attackRateMbps", "Flood rate per anomalous UE [Mb/s]", attackRateMbps);
  cmd.AddValue ("attackStart", "Flood start time [s]", attackStart);
  cmd.AddValue ("attackDir", "dl (towards the UE) or ul (from the UE)", attackDir);
  cmd.AddValue ("jammerOn", "Enable the downlink jammer", jammerOn);
  cmd.AddValue ("jammerX", "Jammer x [m]", jammerX);
  cmd.AddValue ("jammerY", "Jammer y [m]", jammerY);
  cmd.AddValue ("jammerVx", "Mobile jammer: x velocity while ON [m/s] (0 = static)", jammerVx); // JGMOB
  cmd.AddValue ("jammerVy", "Mobile jammer: y velocity while ON [m/s] (0 = static)", jammerVy);
  cmd.AddValue ("jammerPowerDbm", "Jammer EIRP [dBm]", jammerPowerDbm);
  double jammerStart = 10.0, jammerStop = 40.0, cbrMbps = 0.0;
  cmd.AddValue ("jammerStart", "Jammer switch-on time [s]", jammerStart);
  cmd.AddValue ("jammerStop", "Jammer switch-off time [s] (>= simTime: never)", jammerStop);
  uint32_t jammerProfile = 0; double jammerRampDb = 20.0; // JamGuard: time-varying power
  cmd.AddValue ("jammerProfile", "Jammer power profile: 0 fixed, 1 ramp-up, 2 ramp-down, 3 random", jammerProfile);
  cmd.AddValue ("jammerRampDb", "Depth of the power profile [dB] (EIRP varies in [EIRP-R, EIRP])", jammerRampDb);
  double jammerPeriodMs = 0.0, jammerDuty = 0.5; // JamGuard: keyed jammer
  cmd.AddValue ("jammerPeriodMs", "Keyed jammer: on/off period [ms] (0 = constant jammer)", jammerPeriodMs);
  cmd.AddValue ("jammerDuty", "Keyed jammer: fraction of each period the jammer is on (0..1)", jammerDuty);
  bool lteJam = false; double lteJamPowerDbm = -1e9; // JGLTEJAM
  cmd.AddValue ("lteJam", "Also jam the LTE anchor DL carrier (same position and schedule)", lteJam);
  cmd.AddValue ("lteJamPowerDbm", "EIRP of the LTE-anchor jammer [dBm] (default: jammerPowerDbm)", lteJamPowerDbm);
  cmd.AddValue ("cbrMbps", "If > 0, every UE receives a constant downlink stream of this rate", cbrMbps);
  std::string criticalUes = ""; double embbQuota = -1.0;
  cmd.AddValue ("criticalUes", "Comma-separated IMSIs placed in the protected (critical) slice", criticalUes);
  std::string schedType = "rr";
  cmd.AddValue ("scheduler", "MAC scheduler: rr (MmWaveFlexTtiMacScheduler) or pf (MmWaveFlexTtiPfMacScheduler)", schedType);
  std::string militaryUes = "", ambulanceUes = "", iotUes = ""; bool sliceTraffic = true;
  cmd.AddValue ("militaryUes", "IMSIs in the military slice (1)", militaryUes);
  cmd.AddValue ("ambulanceUes", "IMSIs in the ambulance slice (2)", ambulanceUes);
  cmd.AddValue ("iotUes", "IMSIs in the critical-IoT slice (3)", iotUes);
  cmd.AddValue ("sliceTraffic", "Use per-slice traffic profiles for slice members", sliceTraffic);
  cmd.AddValue ("embbQuota", "Max DL symbol ratio for the eMBB slice under congestion (<0 disables slicing)", embbQuota);
  cmd.Parse (argc, argv); // --RngRun=<n> for independent runs
  if (embbQuota >= 0.0)
    {
      std::stringstream ss (criticalUes); std::string tok;
      while (std::getline (ss, tok, ',')) if (!tok.empty ()) SliceRegistry::Instance ().SetUeSlice ((uint64_t) std::stoul (tok), 1);
      SliceRegistry::Instance ().SetSliceMaxRatio (0, embbQuota);
      std::cout << "SLICE: eMBB quota " << embbQuota << ", critical UEs [" << criticalUes << "]" << std::endl;
    }
  // SLICE PATCH: slice membership (0 eMBB, 1 military, 2 ambulance, 3 critical IoT)
  std::map<uint64_t, int> ueSliceProfile;
  {
    auto addList = [&ueSliceProfile] (const std::string& lst, int sl) {
      std::stringstream ss (lst);
      std::string tok;
      while (std::getline (ss, tok, ','))
        if (!tok.empty ())
          {
            uint64_t im = (uint64_t) std::stoul (tok);
            ueSliceProfile[im] = sl;
            SliceRegistry::Instance ().SetUeSlice (im, (uint8_t) sl);
          }
    };
    addList (criticalUes, 1);
    addList (militaryUes, 1);
    addList (ambulanceUes, 2);
    addList (iotUes, 3);
    std::cout << "SLICES: military [" << militaryUes << criticalUes << "] ambulance [" << ambulanceUes
              << "] iot [" << iotUes << "] sliceTraffic " << sliceTraffic << std::endl;
  }

  bool harqEnabled = true;
  UintegerValue uintegerValue;
  BooleanValue booleanValue;
  StringValue stringValue;
  DoubleValue doubleValue;

  GlobalValue::GetValueByName ("hoSinrDifference", doubleValue);
  double hoSinrDifference = doubleValue.Get ();
  GlobalValue::GetValueByName ("bufferSize", uintegerValue);
  uint32_t bufferSize = uintegerValue.Get ();
  GlobalValue::GetValueByName ("enableTraces", booleanValue);
  bool enableTraces = booleanValue.Get ();
  GlobalValue::GetValueByName ("outageThreshold", doubleValue);
  double outageThreshold = doubleValue.Get ();
  GlobalValue::GetValueByName ("e2TermIp", stringValue);
  std::string e2TermIp = stringValue.Get ();
  GlobalValue::GetValueByName ("enableE2FileLogging", booleanValue);
  bool enableE2FileLogging = booleanValue.Get ();
  GlobalValue::GetValueByName ("KPM_E2functionID", doubleValue);
  double kpmFuncId = doubleValue.Get ();
  GlobalValue::GetValueByName ("RC_E2functionID", doubleValue);
  double rcFuncId = doubleValue.Get ();
  GlobalValue::GetValueByName ("numberOfRaPreambles", uintegerValue);
  uint8_t numberOfRaPreambles = uintegerValue.Get ();
  GlobalValue::GetValueByName ("e2lteEnabled", booleanValue);
  bool e2lteEnabled = booleanValue.Get ();
  GlobalValue::GetValueByName ("e2nrEnabled", booleanValue);
  bool e2nrEnabled = booleanValue.Get ();
  GlobalValue::GetValueByName ("e2du", booleanValue);
  bool e2du = booleanValue.Get ();
  GlobalValue::GetValueByName ("e2cuUp", booleanValue);
  bool e2cuUp = booleanValue.Get ();
  GlobalValue::GetValueByName ("e2cuCp", booleanValue);
  bool e2cuCp = booleanValue.Get ();
  GlobalValue::GetValueByName ("reducedPmValues", booleanValue);
  bool reducedPmValues = booleanValue.Get ();
  GlobalValue::GetValueByName ("indicationPeriodicity", doubleValue);
  double indicationPeriodicity = doubleValue.Get ();
  GlobalValue::GetValueByName ("controlFileName", stringValue);
  std::string controlFilename = stringValue.Get ();

  Config::SetDefault ("ns3::LteEnbNetDevice::ControlFileName", StringValue (controlFilename));
  Config::SetDefault ("ns3::LteEnbNetDevice::E2Periodicity", DoubleValue (indicationPeriodicity));
  Config::SetDefault ("ns3::MmWaveEnbNetDevice::E2Periodicity", DoubleValue (indicationPeriodicity));
  Config::SetDefault ("ns3::MmWaveHelper::E2ModeLte", BooleanValue (e2lteEnabled));
  Config::SetDefault ("ns3::MmWaveHelper::E2ModeNr", BooleanValue (e2nrEnabled));
  Config::SetDefault ("ns3::MmWaveEnbNetDevice::EnableDuReport", BooleanValue (e2du));
  Config::SetDefault ("ns3::MmWaveEnbNetDevice::EnableCuUpReport", BooleanValue (e2cuUp));
  Config::SetDefault ("ns3::LteEnbNetDevice::EnableCuUpReport", BooleanValue (e2cuUp));
  Config::SetDefault ("ns3::MmWaveEnbNetDevice::EnableCuCpReport", BooleanValue (e2cuCp));
  Config::SetDefault ("ns3::LteEnbNetDevice::EnableCuCpReport", BooleanValue (e2cuCp));
  Config::SetDefault ("ns3::MmWaveEnbNetDevice::ReducedPmValues", BooleanValue (reducedPmValues));
  Config::SetDefault ("ns3::LteEnbNetDevice::ReducedPmValues", BooleanValue (reducedPmValues));
  Config::SetDefault ("ns3::LteEnbNetDevice::EnableE2FileLogging", BooleanValue (enableE2FileLogging));
  Config::SetDefault ("ns3::MmWaveEnbNetDevice::EnableE2FileLogging", BooleanValue (enableE2FileLogging));
  Config::SetDefault ("ns3::LteEnbNetDevice::KPM_E2functionID", DoubleValue (kpmFuncId));
  Config::SetDefault ("ns3::MmWaveEnbNetDevice::KPM_E2functionID", DoubleValue (kpmFuncId));
  Config::SetDefault ("ns3::LteEnbNetDevice::RC_E2functionID", DoubleValue (rcFuncId));
  Config::SetDefault ("ns3::MmWaveEnbMac::NumberOfRaPreambles", UintegerValue (numberOfRaPreambles));
  Config::SetDefault ("ns3::MmWaveHelper::HarqEnabled", BooleanValue (harqEnabled));
  Config::SetDefault ("ns3::MmWaveHelper::UseIdealRrc", BooleanValue (true));
  Config::SetDefault ("ns3::MmWaveHelper::E2TermIp", StringValue (e2TermIp));
  Config::SetDefault ("ns3::MmWaveFlexTtiMacScheduler::HarqEnabled", BooleanValue (harqEnabled));
  Config::SetDefault ("ns3::MmWavePhyMacCommon::NumHarqProcess", UintegerValue (100));
  Config::SetDefault ("ns3::PhasedArrayModel::AntennaElement",
                      PointerValue (CreateObject<IsotropicAntennaModel> ()));
  Config::SetDefault ("ns3::ThreeGppChannelModel::UpdatePeriod", TimeValue (MilliSeconds (100.0)));
  Config::SetDefault ("ns3::ThreeGppChannelConditionModel::UpdatePeriod", TimeValue (MilliSeconds (100)));
  Config::SetDefault ("ns3::LteRlcAm::ReportBufferStatusTimer", TimeValue (MilliSeconds (10.0)));
  Config::SetDefault ("ns3::LteRlcUmLowLat::ReportBufferStatusTimer", TimeValue (MilliSeconds (10.0)));
  Config::SetDefault ("ns3::LteRlcUm::MaxTxBufferSize", UintegerValue (bufferSize * 1024 * 1024));
  Config::SetDefault ("ns3::LteRlcUmLowLat::MaxTxBufferSize", UintegerValue (bufferSize * 1024 * 1024));
  Config::SetDefault ("ns3::LteRlcAm::MaxTxBufferSize", UintegerValue (bufferSize * 1024 * 1024));
  Config::SetDefault ("ns3::LteEnbRrc::OutageThreshold", DoubleValue (outageThreshold));
  Config::SetDefault ("ns3::LteEnbRrc::SecondaryCellHandoverMode", StringValue ("Threshold"));
  Config::SetDefault ("ns3::LteEnbRrc::HoSinrDifference", DoubleValue (hoSinrDifference));
  Config::SetDefault ("ns3::ThreeGppPropagationLossModel::Frequency", DoubleValue (3.5e9));
  Config::SetDefault ("ns3::ThreeGppPropagationLossModel::ShadowingEnabled", BooleanValue (true));
  Config::SetDefault ("ns3::MmWaveEnbPhy::TxPower", DoubleValue (44.0));
  Config::SetDefault ("ns3::MmWaveEnbPhy::DlSinrWithJammers", BooleanValue (jammerOn));

  GlobalValue::GetValueByName ("Bandwidth", doubleValue);
  double bandwidth = doubleValue.Get ();
  GlobalValue::GetValueByName ("CenterFrequency", doubleValue);
  double centerFrequency = doubleValue.Get ();
  GlobalValue::GetValueByName ("IntersideDistanceCells", doubleValue);
  double isd_cell = doubleValue.Get ();

  Config::SetDefault ("ns3::McUeNetDevice::AntennaNum", UintegerValue (1));
  Config::SetDefault ("ns3::MmWaveNetDevice::AntennaNum", UintegerValue (1));
  Config::SetDefault ("ns3::MmWavePhyMacCommon::Bandwidth", DoubleValue (bandwidth));
  Config::SetDefault ("ns3::MmWavePhyMacCommon::CenterFreq", DoubleValue (centerFrequency));
  Ptr<MmWaveHelper> mmwaveHelper = CreateObject<MmWaveHelper> ();
  if (schedType == "pf")
    mmwaveHelper->SetSchedulerType ("ns3::MmWaveFlexTtiPfMacScheduler");
  std::cout << "SCHEDULER: " << mmwaveHelper->GetSchedulerType () << std::endl;
  mmwaveHelper->SetPathlossModelType ("ns3::ThreeGppUmiStreetCanyonPropagationLossModel");
  mmwaveHelper->SetChannelConditionModelType ("ns3::ThreeGppUmiStreetCanyonChannelConditionModel");
  Ptr<MmWavePointToPointEpcHelper> epcHelper = CreateObject<MmWavePointToPointEpcHelper> ();
  mmwaveHelper->SetEpcHelper (epcHelper);

  GlobalValue::GetValueByName ("N_MmWaveEnbNodes", uintegerValue);
  uint8_t nMmWaveEnbNodes = uintegerValue.Get ();
  uint8_t nLteEnbNodes = 1;
  GlobalValue::GetValueByName ("N_Ues", uintegerValue);
  uint32_t nUeNodes = uintegerValue.Get ();
  if (nAttackers > nUeNodes)
    {
      nAttackers = nUeNodes;
    }

  Ptr<Node> pgw = epcHelper->GetPgwNode ();
  NodeContainer remoteHostContainer;
  remoteHostContainer.Create (1);
  Ptr<Node> remoteHost = remoteHostContainer.Get (0);
  InternetStackHelper internet;
  internet.Install (remoteHostContainer);
  PointToPointHelper p2ph;
  p2ph.SetDeviceAttribute ("DataRate", DataRateValue (DataRate ("100Gb/s")));
  p2ph.SetDeviceAttribute ("Mtu", UintegerValue (2500));
  p2ph.SetChannelAttribute ("Delay", TimeValue (Seconds (0.010)));
  NetDeviceContainer internetDevices = p2ph.Install (pgw, remoteHost);
  Ipv4AddressHelper ipv4h;
  ipv4h.SetBase ("1.0.0.0", "255.0.0.0");
  Ipv4InterfaceContainer internetIpIfaces = ipv4h.Assign (internetDevices);
  Ipv4Address remoteHostAddr = internetIpIfaces.GetAddress (1);
  Ipv4StaticRoutingHelper ipv4RoutingHelper;
  Ptr<Ipv4StaticRouting> remoteHostStaticRouting =
      ipv4RoutingHelper.GetStaticRouting (remoteHost->GetObject<Ipv4> ());
  remoteHostStaticRouting->AddNetworkRouteTo (Ipv4Address ("7.0.0.0"), Ipv4Mask ("255.0.0.0"), 1);

  NodeContainer ueNodes, mmWaveEnbNodes, lteEnbNodes, allEnbNodes;
  mmWaveEnbNodes.Create (nMmWaveEnbNodes);
  lteEnbNodes.Create (nLteEnbNodes);
  ueNodes.Create (nUeNodes);
  allEnbNodes.Add (lteEnbNodes);
  allEnbNodes.Add (mmWaveEnbNodes);
  NodeContainerManager::GetInstance ().SetMmWaveEnbNodes (mmWaveEnbNodes);

  Vector centerPosition = Vector (maxXAxis / 2, maxYAxis / 2, 10);
  Ptr<ListPositionAllocator> enbPositionAlloc = CreateObject<ListPositionAllocator> ();
  enbPositionAlloc->Add (centerPosition);
  enbPositionAlloc->Add (centerPosition);
  double nConstellation = nMmWaveEnbNodes - 1;
  for (int8_t i = 0; i < nConstellation; ++i)
    {
      double x = isd_cell * cos ((2 * M_PI * i) / (nConstellation));
      double y = isd_cell * sin ((2 * M_PI * i) / (nConstellation));
      enbPositionAlloc->Add (Vector (centerPosition.x + x, centerPosition.y + y, 10));
    }
  MobilityHelper enbmobility;
  enbmobility.SetMobilityModel ("ns3::ConstantPositionMobilityModel");
  enbmobility.SetPositionAllocator (enbPositionAlloc);
  enbmobility.Install (allEnbNodes);

  MobilityHelper uemobility;
  Ptr<UniformDiscPositionAllocator> uePositionAlloc = CreateObject<UniformDiscPositionAllocator> ();
  uePositionAlloc->SetX (centerPosition.x);
  uePositionAlloc->SetY (centerPosition.y);
  uePositionAlloc->SetZ (1.5);
  uePositionAlloc->SetRho (450.0);
  Ptr<UniformRandomVariable> speed = CreateObject<UniformRandomVariable> ();
  speed->SetAttribute ("Min", DoubleValue (3.0));
  speed->SetAttribute ("Max", DoubleValue (7.0));
  uemobility.SetMobilityModel ("ns3::RandomWalk2dOutdoorMobilityModel", "Speed", PointerValue (speed),
                               "Bounds", RectangleValue (Rectangle (0, maxXAxis, 0, maxYAxis)));
  uemobility.SetPositionAllocator (uePositionAlloc);
  uemobility.Install (ueNodes);
  NodeContainer jammerNode;
  jammerNode.Create (1);
  Ptr<ListPositionAllocator> jAlloc = CreateObject<ListPositionAllocator> ();
  jAlloc->Add (Vector (jammerX, jammerY, jammerZ));
  MobilityHelper jMob;
  if (jammerVx != 0.0 || jammerVy != 0.0) // JGMOB
    jMob.SetMobilityModel ("ns3::ConstantVelocityMobilityModel");
  else
    jMob.SetMobilityModel ("ns3::ConstantPositionMobilityModel");
  jMob.SetPositionAllocator (jAlloc);
  jMob.Install (jammerNode);
  Ptr<ThreeGppUmiStreetCanyonChannelConditionModel> jCond = CreateObject<ThreeGppUmiStreetCanyonChannelConditionModel> ();
  jCond->SetAttribute ("UpdatePeriod", TimeValue (MilliSeconds (100)));
  Ptr<ThreeGppUmiStreetCanyonPropagationLossModel> jPl = CreateObject<ThreeGppUmiStreetCanyonPropagationLossModel> ();
  jPl->SetAttribute ("Frequency", DoubleValue (3.5e9));
  jPl->SetAttribute ("ShadowingEnabled", BooleanValue (true));
  jPl->SetChannelConditionModel (jCond);
  if (jammerOn)
    {
      MmWaveEnbPhy::AddJammer (jammerNode.Get (0)->GetObject<MobilityModel> (), jammerPowerDbm, jPl);
      {
        /* JGMOB: the jammer moves only while it is ON */
        Ptr<ConstantVelocityMobilityModel> cv = jammerNode.Get (0)->GetObject<ConstantVelocityMobilityModel> ();
        if (cv)
          {
            cv->SetVelocity (Vector (0, 0, 0));
            Simulator::Schedule (Seconds (jammerStart), &ConstantVelocityMobilityModel::SetVelocity, cv,
                                 Vector (jammerVx, jammerVy, 0));
            Simulator::Schedule (Seconds (jammerStop), &ConstantVelocityMobilityModel::SetVelocity, cv,
                                 Vector (0, 0, 0));
            JgTrackStart (jammerNode.Get (0)->GetObject<MobilityModel> ());
            NS_LOG_UNCOND ("Mobile jammer: velocity (" << jammerVx << ", " << jammerVy << ") m/s from "
                           << jammerStart << " s to " << jammerStop << " s");
          }
      }
      if (jammerStart > 0)
        {
          MmWaveEnbPhy::SetJammersActive (false);
          Simulator::Schedule (Seconds (jammerStart), &JgSetAllJammers, true);
        }
      if (jammerStop > jammerStart)
        {
          Simulator::Schedule (Seconds (jammerStop), &JgSetAllJammers, false);
        }
      NS_LOG_UNCOND ("Jammer ON at (" << jammerX << ", " << jammerY << ") EIRP " << jammerPowerDbm << " dBm");
      if (jammerProfile > 0 && jammerStop > jammerStart)
        {
          /* JamGuard: time-varying jammer power, updated every 100 ms */
          Ptr<UniformRandomVariable> jr = CreateObject<UniformRandomVariable> ();
          for (double ts = jammerStart; ts < jammerStop - 1e-9; ts += 0.1)
            {
              double f = (ts - jammerStart) / (jammerStop - jammerStart);
              double off = jammerProfile == 1 ? -jammerRampDb * (1.0 - f)
                         : jammerProfile == 2 ? -jammerRampDb * f
                         : -jr->GetValue (0.0, jammerRampDb);
              Simulator::Schedule (Seconds (ts), &MmWaveEnbPhy::SetJammerPowerOffsetDb, off);
            }
          Simulator::Schedule (Seconds (jammerStop), &MmWaveEnbPhy::SetJammerPowerOffsetDb, 0.0);
          NS_LOG_UNCOND ("Jammer power profile " << jammerProfile << ", depth " << jammerRampDb << " dB");
        }
      if (jammerPeriodMs > 0 && jammerStop > jammerStart && jammerDuty > 0 && jammerDuty < 1)
        {
          /* JamGuard: keyed jammer, ON for Duty*Period then OFF, until jammerStop */
          double T = jammerPeriodMs / 1000.0;
          double on = T * jammerDuty;
          uint32_t n = 0;
          for (double ts = jammerStart; ts < jammerStop - 1e-9; ts += T)
            {
              Simulator::Schedule (Seconds (ts), &JgSetAllJammers, true);
              if (ts + on < jammerStop)
                Simulator::Schedule (Seconds (ts + on), &JgSetAllJammers, false);
              n++;
            }
          NS_LOG_UNCOND ("Keyed jammer: period " << jammerPeriodMs << " ms, duty " << jammerDuty
                         << ", " << n << " pulses");
        }
    }
  {
    std::ofstream jf ("jammer.txt", std::ios_base::out | std::ios_base::trunc);
    jf << "x,y,z,power_dbm,jammer_on,rng_run,start_s,stop_s,period_ms,duty" << std::endl;
    jf << jammerX << "," << jammerY << "," << jammerZ << "," << jammerPowerDbm << ","
       << (jammerOn ? 1 : 0) << "," << RngSeedManager::GetRun () << "," << jammerStart << ","
       << jammerStop << "," << jammerPeriodMs << "," << jammerDuty << std::endl;
  }

  double minDistance = 10.0;
  for (uint32_t i = 0; i < ueNodes.GetN (); ++i)
    {
      Ptr<MobilityModel> ueMobility = ueNodes.Get (i)->GetObject<MobilityModel> ();
      bool tooClose;
      do
        {
          tooClose = false;
          for (uint32_t j = 0; j < allEnbNodes.GetN (); ++j)
            {
              if (ueMobility->GetDistanceFrom (allEnbNodes.Get (j)->GetObject<MobilityModel> ()) < minDistance)
                {
                  ueMobility->SetPosition (uePositionAlloc->GetNext ());
                  tooClose = true;
                  break;
                }
            }
        }
      while (tooClose);
    }

  NetDeviceContainer lteEnbDevs = mmwaveHelper->InstallLteEnbDevice (lteEnbNodes);
  NetDeviceContainer mmWaveEnbDevs = mmwaveHelper->InstallEnbDevice (mmWaveEnbNodes);
  NetDeviceContainer mcUeDevs = mmwaveHelper->InstallMcUeDevice (ueNodes);
  internet.Install (ueNodes);
  Ipv4InterfaceContainer ueIpIface = epcHelper->AssignUeIpv4Address (NetDeviceContainer (mcUeDevs));
  for (uint32_t u = 0; u < ueNodes.GetN (); ++u)
    {
      Ptr<Ipv4StaticRouting> ueStaticRouting =
          ipv4RoutingHelper.GetStaticRouting (ueNodes.Get (u)->GetObject<Ipv4> ());
      ueStaticRouting->SetDefaultRoute (epcHelper->GetUeDefaultGatewayAddress (), 1);
    }
  mmwaveHelper->AddX2Interface (lteEnbNodes, mmWaveEnbNodes);
  mmwaveHelper->AttachToClosestEnb (mcUeDevs, mmWaveEnbDevs, lteEnbDevs);
  if (jammerOn && lteJam) // JGLTEJAM
    {
      Ptr<LteEnbNetDevice> lteEnb = lteEnbDevs.Get (0)->GetObject<LteEnbNetDevice> ();
      NS_ABORT_MSG_IF (!lteEnb, "lteJam: LTE anchor is not an LteEnbNetDevice");
      Ptr<SpectrumChannel> lteDl = lteEnb->GetPhy ()->GetDownlinkSpectrumPhy ()->GetChannel ();
      NS_ABORT_MSG_IF (!lteDl, "lteJam: no LTE DL spectrum channel");
      uint32_t const earfcn = lteEnb->GetDlEarfcn ();
      uint8_t const nRb = lteEnb->GetDlBandwidth ();
      double const pw = (lteJamPowerDbm > -1e8) ? lteJamPowerDbm : jammerPowerDbm;
      std::vector<int> rbs;
      for (int k = 0; k < nRb; ++k) rbs.push_back (k);
      WaveformGeneratorHelper wg;
      wg.SetChannel (lteDl);
      wg.SetTxPowerSpectralDensity (LteSpectrumValueHelper::CreateTxPowerSpectralDensity (earfcn, nRb, pw, rbs));
      wg.SetPhyAttribute ("Period", TimeValue (MilliSeconds (1)));
      wg.SetPhyAttribute ("DutyCycle", DoubleValue (1.0));
      NetDeviceContainer jd = wg.Install (jammerNode.Get (0));
      g_jgLteJam = jd.Get (0)->GetObject<NonCommunicatingNetDevice> ()->GetPhy ()->GetObject<WaveformGenerator> ();
      NS_ABORT_MSG_IF (!g_jgLteJam, "lteJam: WaveformGenerator not created");
      if (jammerStart <= 0)
        Simulator::ScheduleNow (&JgSetAllJammers, true);
      NS_LOG_UNCOND ("JGLTEJAM: LTE anchor jammer EARFCN " << earfcn << ", " << (int) nRb
                     << " RBs, " << pw << " dBm, same schedule as the NR jammer");
    }

  GlobalValue::GetValueByName ("simTime", doubleValue);
  double simTime = doubleValue.Get ();

  // ---------------- traffic: random draws are identical in attack and control runs ----------------
  Ptr<UniformRandomVariable> draw = CreateObject<UniformRandomVariable> ();
  draw->SetStream (1000); // fixed stream; the values still change with --RngRun

  // benign profile per UE: light 0.1-0.5, medium 0.5-2, heavy 2-6 Mb/s while ON
  std::vector<std::string> profile (nUeNodes);
  std::vector<double> benignMbps (nUeNodes);
  for (uint32_t u = 0; u < nUeNodes; ++u)
    {
      double c = draw->GetValue (0.0, 1.0);
      if (c < 0.5)
        {
          profile[u] = "light";
          benignMbps[u] = draw->GetValue (0.1, 0.5);
        }
      else if (c < 0.85)
        {
          profile[u] = "medium";
          benignMbps[u] = draw->GetValue (0.5, 2.0);
        }
      else
        {
          profile[u] = "heavy";
          benignMbps[u] = draw->GetValue (2.0, 6.0);
        }
    }
  // anomalous UEs: partial Fisher-Yates shuffle
  std::vector<uint32_t> idx (nUeNodes);
  for (uint32_t u = 0; u < nUeNodes; ++u)
    {
      idx[u] = u;
    }
  for (uint32_t k = 0; k < nAttackers; ++k)
    {
      uint32_t j = draw->GetInteger (k, nUeNodes - 1);
      std::swap (idx[k], idx[j]);
    }
  std::vector<bool> isAttacker (nUeNodes, false);
  for (uint32_t k = 0; k < nAttackers; ++k)
    {
      isAttacker[idx[k]] = true;
    }

  ApplicationContainer sinkApp, benignApps, attackApps;
  PacketSinkHelper sinkUl ("ns3::UdpSocketFactory", InetSocketAddress (Ipv4Address::GetAny (), 60000));
  sinkApp.Add (sinkUl.Install (remoteHost));
  int64_t stream = 2000;
  for (uint32_t u = 0; u < nUeNodes; ++u)
    {
      PacketSinkHelper dlSink ("ns3::UdpSocketFactory", InetSocketAddress (Ipv4Address::GetAny (), 1234));
      sinkApp.Add (dlSink.Install (ueNodes.Get (u)));
      PacketSinkHelper dlSinkAtk ("ns3::UdpSocketFactory", InetSocketAddress (Ipv4Address::GetAny (), 1235));
      sinkApp.Add (dlSinkAtk.Install (ueNodes.Get (u)));

      // benign ON/OFF downlink traffic
      OnOffHelper onoff ("ns3::UdpSocketFactory", InetSocketAddress (ueIpIface.GetAddress (u), 1234));
      if (cbrMbps > 0)
        {
          onoff.SetConstantRate (DataRate ((uint64_t) (cbrMbps * 1e6)), pktSize);
          onoff.SetAttribute ("OnTime", StringValue ("ns3::ConstantRandomVariable[Constant=1000]"));
          onoff.SetAttribute ("OffTime", StringValue ("ns3::ConstantRandomVariable[Constant=0]"));
        }
      else
        {
          onoff.SetConstantRate (DataRate ((uint64_t) (benignMbps[u] * 1e6)), pktSize);
          onoff.SetAttribute ("OnTime", StringValue ("ns3::ExponentialRandomVariable[Mean=3.0]"));
          onoff.SetAttribute ("OffTime", StringValue ("ns3::ExponentialRandomVariable[Mean=1.0]"));
        }
      onoff.SetAttribute ("EnableSeqTsSizeHeader", BooleanValue (true));
      // SLICE PATCH: per-slice traffic profile (replaces cbr/benign for slice members)
      {
        uint64_t imsiS = mcUeDevs.Get (u)->GetObject<McUeNetDevice> ()->GetImsi ();
        auto sp = ueSliceProfile.find (imsiS);
        if (sliceTraffic && sp != ueSliceProfile.end ())
          {
            auto cbr = [] (OnOffHelper& h, double bps, uint32_t size) {
              h.SetConstantRate (DataRate ((uint64_t) bps), size);
              h.SetAttribute ("OnTime", StringValue ("ns3::ConstantRandomVariable[Constant=1000]"));
              h.SetAttribute ("OffTime", StringValue ("ns3::ConstantRandomVariable[Constant=0]"));
            };
            OnOffHelper extra = onoff;
            if (sp->second == 1) { cbr (onoff, 64e3, 160); cbr (extra, 500e3, 500); }       // military: voice + command data
            else if (sp->second == 2) { cbr (onoff, 3e6, 1200); cbr (extra, 100e3, 200); } // ambulance: video + vital signs
            else if (sp->second == 3) { cbr (onoff, 80e3, 100); }                         // critical IoT: 100 B every 10 ms
            if (sp->second == 1 || sp->second == 2)
              {
                ApplicationContainer x = extra.Install (remoteHost);
                stream += DynamicCast<OnOffApplication> (x.Get (0))->AssignStreams (stream);
                benignApps.Add (x);
              }
          }
      }
      ApplicationContainer a = onoff.Install (remoteHost);
      stream += DynamicCast<OnOffApplication> (a.Get (0))->AssignStreams (stream);
      benignApps.Add (a);

      // flood application: created for every attacker in both runs, started only if anomalyOn
      if (isAttacker[u])
        {
          double interval = pktSize * 8.0 / (attackRateMbps * 1e6);
          ApplicationContainer f;
          if (attackDir == "ul")
            {
              UdpClientHelper ul (remoteHostAddr, 60000);
              ul.SetAttribute ("Interval", TimeValue (Seconds (interval)));
              ul.SetAttribute ("MaxPackets", UintegerValue (UINT32_MAX));
              ul.SetAttribute ("PacketSize", UintegerValue (pktSize));
              f = ul.Install (ueNodes.Get (u));
            }
          else
            {
              UdpClientHelper dl (ueIpIface.GetAddress (u), 1235);
              dl.SetAttribute ("Interval", TimeValue (Seconds (interval)));
              dl.SetAttribute ("MaxPackets", UintegerValue (UINT32_MAX));
              dl.SetAttribute ("PacketSize", UintegerValue (pktSize));
              f = dl.Install (remoteHost);
            }
          f.Start (anomalyOn ? Seconds (attackStart) : Seconds (simTime + 10.0));
          f.Stop (Seconds (simTime - 0.1));
          attackApps.Add (f);
        }
    }
  sinkApp.Start (Seconds (0));
  benignApps.Start (MilliSeconds (100));
  benignApps.Stop (Seconds (simTime - 0.1));

  // ---------------- ground truth ----------------
  {
    std::ofstream gt ("anomaly.txt", std::ios_base::out | std::ios_base::trunc);
    gt << "imsi,attacker,profile,benign_mbps,attack_mbps,attack_dir,attack_start_s,anomaly_on,rng_run"
       << std::endl;
    for (uint32_t u = 0; u < nUeNodes; ++u)
      {
        uint64_t imsi = mcUeDevs.Get (u)->GetObject<McUeNetDevice> ()->GetImsi ();
        gt << imsi << "," << (isAttacker[u] ? 1 : 0) << "," << profile[u] << "," << benignMbps[u] << ","
           << (isAttacker[u] ? attackRateMbps : 0.0) << "," << attackDir << "," << attackStart << ","
           << (anomalyOn ? 1 : 0) << "," << RngSeedManager::GetRun () << std::endl;
      }
  }
  for (uint32_t u = 0; u < nUeNodes; ++u)
    {
      if (isAttacker[u])
        {
          NS_LOG_UNCOND ("Anomalous UE IMSI "
                         << mcUeDevs.Get (u)->GetObject<McUeNetDevice> ()->GetImsi () << " flood "
                         << attackRateMbps << " Mb/s " << attackDir << " from t=" << attackStart
                         << " s" << (anomalyOn ? "" : " (control run: flood not started)"));
        }
    }

  // ---------------- position and gNB logs ----------------
  struct timeval time_now{};
  gettimeofday (&time_now, nullptr);
  uint64_t t_start = (time_now.tv_sec * 1000) + (time_now.tv_usec / 1000);
  // XAPP PATCH: application-level delivered DL bytes per UE every 100 ms -> ue_rx.txt
  {
    std::vector<std::pair<uint64_t, Ptr<PacketSink>>> rxSinks;
    for (uint32_t u = 0; u < ueNodes.GetN (); ++u)
      {
        uint64_t imsiU = mcUeDevs.Get (u)->GetObject<McUeNetDevice> ()->GetImsi ();
        Ptr<Node> nd = ueNodes.Get (u);
        for (uint32_t k = 0; k < nd->GetNApplications (); ++k)
          {
            Ptr<PacketSink> ps = DynamicCast<PacketSink> (nd->GetApplication (k));
            if (!ps)
              continue;
            AddressValue local;
            ps->GetAttribute ("Local", local);
            if (InetSocketAddress::IsMatchingType (local.Get ()) &&
                InetSocketAddress::ConvertFrom (local.Get ()).GetPort () == 1234)
              {
                rxSinks.push_back (std::make_pair (imsiU, ps));
                ps->SetAttribute ("EnableSeqTsSizeHeader", BooleanValue (true));
                ps->TraceConnectWithoutContext ("RxWithSeqTsSize", MakeBoundCallback (&XappDelayRx, imsiU));
              }
          }
      }
    auto rxOut = std::make_shared<std::ofstream> ("ue_rx.txt");
    *rxOut << "t_s,imsi,rx_bytes,dly_pkts,dly_sum_s,dly_bad\n";   // DLYGUARD: new last column
    auto rxTick = std::make_shared<std::function<void ()>> ();
    *rxTick = [rxOut, rxSinks, rxTick] () {
      for (auto &p : rxSinks)
        {
          jgl::g_rxTot[p.first] = p.second->GetTotalRx (); /* JGANCHOR */
          *rxOut << Simulator::Now ().GetSeconds () << "," << p.first << "," << p.second->GetTotalRx () << "," << g_ueDelay[p.first].second << "," << g_ueDelay[p.first].first << "," << g_ueDelayBad[p.first] << "\n";
        }
      rxOut->flush ();
      Simulator::Schedule (MilliSeconds (100), *rxTick);
    };
    Simulator::Schedule (MilliSeconds (100), *rxTick);
  }
  // SLICE PATCH: keep (cell, rnti) -> imsi up to date for the scheduler; print lookup stats every 1 s
  {
    std::vector<Ptr<MmWaveEnbNetDevice>> gnbs;
    for (NodeList::Iterator it = NodeList::Begin (); it != NodeList::End (); ++it)
      for (uint32_t i = 0; i < (*it)->GetNDevices (); ++i)
        {
          Ptr<MmWaveEnbNetDevice> g = DynamicCast<MmWaveEnbNetDevice> ((*it)->GetDevice (i));
          if (g)
            gnbs.push_back (g);
        }
    auto slTick = std::make_shared<std::function<void ()>> ();
    auto slCount = std::make_shared<int> (0);
    *slTick = [gnbs, slTick, slCount] () {
      for (auto &g : gnbs)
        g->GetMac ()->SetCellId (g->GetCellId ()); // SLICE PATCH: MAC cellId is never set by the helper
      for (auto &g : gnbs)
        for (auto &ue : g->GetUeMap ())
          SliceRegistry::Instance ().RegisterRnti (g->GetCellId (), ue.first, ue.second->GetImsi ());
      if (++(*slCount) % 100 == 0)
        {
          std::cout << "SLICE stats t=" << Simulator::Now ().GetSeconds () << " " << SliceRegistry::Instance ().Stats () << std::endl;
          std::cout << "SLICE dbg t=" << Simulator::Now ().GetSeconds () << SliceRegistry::Instance ().DebugStr () << std::endl;
        }
      Simulator::Schedule (MilliSeconds (10), *slTick);
    };
    Simulator::Schedule (MilliSeconds (10), *slTick);
  }
  std::string ue_pos_out = "ue_position.txt";
  ClearFile (ue_pos_out, t_start);
  ClearFile ("enbs.txt", t_start);
  ClearFile ("gnbs.txt", t_start);
  PrintGnuplottableUeListToFile ("ues.txt");
  int numPrints = simTime / 0.1;
  for (int i = 0; i < numPrints; i++)
    {
      Simulator::Schedule (Seconds (i * simTime / numPrints), &PrintGnuplottableEnbListToFile, t_start);
      for (uint32_t j = 0; j < ueNodes.GetN (); j++)
        {
          Simulator::Schedule (Seconds (i * simTime / numPrints), &PrintPosition, ueNodes.Get (j),
                               ue_pos_out, t_start);
        }
    }

  if (enableTraces)
    {
      mmwaveHelper->EnableTraces ();
    }
  else
    {
      mmwaveHelper->EnableMcTraces ();
    }
  Ptr<LteHelper> lteHelper = CreateObject<LteHelper> ();
  lteHelper->Initialize ();
  lteHelper->EnablePhyTraces ();
  lteHelper->EnableMacTraces ();

  NS_LOG_UNCOND ("Simulation time is " << simTime << " seconds");
  Simulator::Stop (Seconds (simTime));
  jgl::Start ();
  Simulator::Run ();
  MmWaveEnbPhy::ClearJammers ();
  Simulator::Destroy ();
  return 0;
}
