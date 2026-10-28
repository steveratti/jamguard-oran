# Makes the per-UE downlink block error rate attributable in the E2SM-KPM DU report.
#
# THE PROBLEM. The DU report does reach the xApp: a live capture carries 7800 TB.* rows. But its
# measurement names are fixed strings -- "TB.TotNbrDl.1.UEID", "TB.ErrTotalNbrDl.1.UEID" -- and the
# UE they belong to is carried by the per-UE container of the indication, not by the name. The
# CU-CP items solve this by putting the UE in the name ("L3servingSINR3gpp_cell_5_UEID_00002"), so
# an xApp that parses names, as ours does, can attribute them. The DU items cannot be attributed
# that way, and an xApp that guessed the container order would silently assign a UE's block error
# rate to a different UE.
#
# THE FIX. Emit two additional items from the same function, with the UE in the name, exactly as
# the received-power extension does. The stock items are left untouched, so nothing that already
# consumes them changes; what we add is a name an xApp can attribute without reading the container.
#
#   TBTotDl_UEID_<imsi>   transport blocks sent to this UE in the report period
#   TBErrDl_UEID_<imsi>   of those, how many were retransmissions (HARQ NACKs)
#
# Their ratio is the block error rate per UE per report, which is the quantity a BLER-threshold
# detector averages.
#
# usage: cd ~/ns-O-RAN-flexric/mmwave-LENA-oran && python3 ~/patch_bler_kpm.py
#        then ./ns3 build   (not while a campaign is running)
# Idempotent. The name of the IMSI parameter is read from the signature rather than assumed.
import os, re, sys, shutil

F = sys.argv[1] if len(sys.argv) > 1 else 'contrib/oran-interface/helper/mmwave-indication-message-helper.cc'
if not os.path.exists(F):
    sys.exit('ERROR: not found: %s\n       run from the root of the ns-3 tree' % F)
s = open(F).read()
if 'JGBLER' in s:
    sys.exit('already patched')

# the first parameter of AddDuUePmItem is the IMSI string; read its name instead of assuming it
m = re.search(r'MmWaveIndicationMessageHelper::AddDuUePmItem\s*\(\s*(?:std::)?string\s+(\w+)', s)
if not m:
    m = re.search(r'AddDuUePmItem\s*\(\s*(?:std::)?string\s+(\w+)', s)
if not m:
    sys.exit('ERROR: could not find the signature of AddDuUePmItem in %s\n'
             '--- nothing changed. Send this message back.' % F)
imsi = m.group(1)

ANCH = 'ueVal->AddItem<long> ("TB.ErrTotalNbrDl.1.UEID", macRetx);'
if s.count(ANCH) != 1:
    sys.exit('ERROR: expected exactly one\n    %s\n--- found %d. Nothing changed.'
             % (ANCH, s.count(ANCH)))

ADD = (ANCH + '\n'
       '      /* JGBLER: the same two counters, with the UE in the measurement name, so that an\n'
       '         xApp can attribute them without reading the per-UE container of the indication.\n'
       '         The stock items above are left untouched. */\n'
       '      ueVal->AddItem<long> ("TBTotDl_UEID_" + %s, macPduUe);\n'
       '      ueVal->AddItem<long> ("TBErrDl_UEID_" + %s, macRetx);' % (imsi, imsi))
s = s.replace(ANCH, ADD, 1)

shutil.copy2(F, F + '.bak_bler')
open(F, 'w').write(s)
print('patched:', F, '(backup at %s.bak_bler)' % F)
print('IMSI parameter read from the signature:', imsi)
print('new items: TBTotDl_UEID_<imsi>, TBErrDl_UEID_<imsi>')
print('next: ./ns3 build     # only when no campaign is running')
