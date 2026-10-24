# JamGuard: keyed (pulsed) jammer for scenario_jam_xapp.cc
# Adds --jammerPeriodMs (0 = constant jammer, as before) and --jammerDuty (0..1).
# Between jammerStart and jammerStop the jammer is ON for Duty*Period, then OFF.
# Scenario-only change (no library change). Default behaviour is unchanged.
# Usage (ONLY after the running campaigns have finished):
#   cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_pulse.py
import sys
p = sys.argv[1] if len(sys.argv) > 1 else 'scratch/scenario_jam_xapp.cc'
t = open(p).read()
if 'jammerPeriodMs' in t:
    print('already patched'); sys.exit(0)

def rep(a, b):
    global t
    assert t.count(a) == 1, 'anchor not unique/not found: ' + a[:70]
    t = t.replace(a, b)

# 1) options
rep('cmd.AddValue ("jammerStop", "Jammer switch-off time [s] (>= simTime: never)", jammerStop);',
    'cmd.AddValue ("jammerStop", "Jammer switch-off time [s] (>= simTime: never)", jammerStop);\n'
    '  double jammerPeriodMs = 0.0, jammerDuty = 0.5; // JamGuard: keyed jammer\n'
    '  cmd.AddValue ("jammerPeriodMs", "Keyed jammer: on/off period [ms] (0 = constant jammer)", jammerPeriodMs);\n'
    '  cmd.AddValue ("jammerDuty", "Keyed jammer: fraction of each period the jammer is on (0..1)", jammerDuty);')

# 2) schedule the pulses (after the existing start/stop scheduling and log line)
anchor = 'NS_LOG_UNCOND ("Jammer ON at (" << jammerX << ", " << jammerY << ") EIRP " << jammerPowerDbm << " dBm");'
rep(anchor, anchor + '''
      if (jammerPeriodMs > 0 && jammerStop > jammerStart && jammerDuty > 0 && jammerDuty < 1)
        {
          /* JamGuard: keyed jammer, ON for Duty*Period then OFF, until jammerStop */
          double T = jammerPeriodMs / 1000.0;
          double on = T * jammerDuty;
          uint32_t n = 0;
          for (double ts = jammerStart; ts < jammerStop - 1e-9; ts += T)
            {
              Simulator::Schedule (Seconds (ts), &MmWaveEnbPhy::SetJammersActive, true);
              if (ts + on < jammerStop)
                Simulator::Schedule (Seconds (ts + on), &MmWaveEnbPhy::SetJammersActive, false);
              n++;
            }
          NS_LOG_UNCOND ("Keyed jammer: period " << jammerPeriodMs << " ms, duty " << jammerDuty
                         << ", " << n << " pulses");
        }''')

# 3) record the jammer pattern in jammer.txt
rep('"x,y,z,power_dbm,jammer_on,rng_run,start_s,stop_s"',
    '"x,y,z,power_dbm,jammer_on,rng_run,start_s,stop_s,period_ms,duty"')
rep('<< jammerStop << std::endl;',
    '<< jammerStop << "," << jammerPeriodMs << "," << jammerDuty << std::endl;')

open(p, 'w').write(t)
print('keyed jammer added: --jammerPeriodMs --jammerDuty')
