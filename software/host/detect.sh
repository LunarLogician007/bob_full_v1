#!/usr/bin/env bash
# Read the IDCODE out of the soft TAP on PMODA, via the Pico running DirtyJTAG.
#
#   ./detect.sh            run at 1 MHz
#   FREQ=100000 ./detect.sh   run slow (do this on first contact)
#
# Expected IDCODE: 0x1beef093
set -uo pipefail

FREQ="${FREQ:-1000000}"

echo "== probes on USB =="
openFPGALoader --scan-usb || true
echo

echo "== openFPGALoader --detect @ ${FREQ} Hz =="
openFPGALoader -c dirtyJtag --freq "$FREQ" --detect 2>&1 | tee /tmp/ofl-detect.$$
echo

echo "== urjtag detect @ ${FREQ} Hz =="
sed "s/@FREQ@/${FREQ}/" "$(dirname "$0")/urjtag-detect.jtag" > /tmp/urj-detect.$$
jtag -n -q /tmp/urj-detect.$$ 2>&1 | tee /tmp/urj-out.$$
echo

# The IDCODE's version nibble says which design is in the PL.
rc=1
if   grep -qiE "0x0b0[0-9]{2}093" /tmp/ofl-detect.$$ /tmp/urj-out.$$; then
    # From M20 the part field names the milestone in readable digits: 0x0B0<MM>093 (hw/build.cfg)
    mm=$(grep -hoiE "0x0b0[0-9]{2}093" /tmp/ofl-detect.$$ /tmp/urj-out.$$ | head -1 | cut -c6-7)
    echo "RESULT: IDCODE 0x0B0${mm}093 - bob M${mm} is alive (hw/build.cfg says idcode = $(grep -E '^idcode' "$(dirname "$0")/../../hw/build.cfg" | awk '{print $3}'))."
    echo "        test it with: make hwtest M=M${mm}"
    rc=0
elif grep -qi "6beef093" /tmp/ofl-detect.$$ /tmp/urj-out.$$; then
    echo "RESULT: IDCODE 0x6beef093 - the 4x4 fabric with user clock and routed CE/SR (M4) is alive."
    echo "        drive it with: ./host/fpga.py --load showcase   (6-bit AMD IR)"
    rc=0
elif grep -qi "5beef093" /tmp/ofl-detect.$$ /tmp/urj-out.$$; then
    echo "RESULT: IDCODE 0x5beef093 - the M3 fabric on the configuration plane (superseded by M4)."
    rc=0
elif grep -qi "4beef093" /tmp/ofl-detect.$$ /tmp/urj-out.$$; then
    echo "RESULT: IDCODE 0x4beef093 - the M2 configuration-plane test top."
    echo "        drive it with: ./host/cfgplane.py status"
    rc=0
elif grep -qi "3beef093" /tmp/ofl-detect.$$ /tmp/urj-out.$$; then
    echo "RESULT: IDCODE 0x3beef093 - the M0/M1 4x4 fabric with the old 4-bit TAP."
    echo "        superseded by M3; rebuild hw/ for the current tools"
    rc=0
elif grep -qi "2beef093" /tmp/ofl-detect.$$ /tmp/urj-out.$$; then
    echo "RESULT: IDCODE 0x2beef093 - the single-CLB build is alive."
    echo "        drive it with: ./host/minifpga.py"
    rc=0
elif grep -qi "1beef093" /tmp/ofl-detect.$$ /tmp/urj-out.$$; then
    echo "RESULT: IDCODE 0x1beef093 - the bare TAP build, superseded."
    echo "        rebuild: vivado -mode batch -source hw/scripts/build.tcl -tclargs all"
else
    echo "RESULT: no known IDCODE seen. See the debug ladder in ../README.md,"
    echo "        or run ./host/tap_probe.py for the raw TDO stream."
fi
rm -f /tmp/ofl-detect.$$ /tmp/urj-detect.$$ /tmp/urj-out.$$
exit $rc
