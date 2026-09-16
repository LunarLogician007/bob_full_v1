#!/usr/bin/env bash
# Teach urjtag about our soft TAP so that 'detect' recognises it and the
# 'instruction' / 'shift' / 'dr' commands work against named registers.
#
#   ./install_urjtag_part.sh              install
#   ./install_urjtag_part.sh --uninstall  remove it again
#
# urjtag identifies parts from a plain-text database keyed on the IDCODE:
#
#   IDCODE 0x?BEEF093
#     version [31:28] = the build          -> STEPPINGS entry
#     part    [27:12] = 1011111011101111   -> PARTS entry (0xBEEF)
#     mfr     [11:1]  = 00001001001        -> Xilinx, which already exists
#
# The version nibble tracks the design, and both current builds are declared:
#
#     0001   the bare TAP           (superseded, not declared)
#     0010   single CLB             CONFIG is 71 bits
#     0011   4x4 fabric             CONFIG is 2896 bits
#
# They share an instruction set but not a CONFIG width, so they get a stepping
# and a declaration file each. Loading a bitstream urjtag does not know about
# shows up immediately as an unknown stepping.
#
# Only the Xilinx PARTS file is touched, and a .bak is left beside it.
# Nothing here is required for the plain IDCODE read - see urjtag-detect.jtag.
set -euo pipefail

PART_ID="1011111011101111"
PART_DIR="pynqz2-softtap"
PART_DESC="PYNQ-Z2 CLB fabric"
STEPPING="0010"

# urjtag prints its own data directory in the help banner - ask it rather
# than guessing at prefixes.
DATA_DIR="$(jtag --help 2>&1 | sed -n 's/^Data directory: //p' | head -1)"
if [[ -z "$DATA_DIR" || ! -d "$DATA_DIR/xilinx" ]]; then
    echo "error: could not locate the urjtag data directory (got '$DATA_DIR')" >&2
    exit 1
fi

PARTS="$DATA_DIR/xilinx/PARTS"
TARGET="$DATA_DIR/xilinx/$PART_DIR"

if [[ "${1:-}" == "--uninstall" ]]; then
    if [[ -f "$PARTS" ]]; then
        grep -v "$PART_ID" "$PARTS" > "$PARTS.tmp" && mv "$PARTS.tmp" "$PARTS"
    fi
    rm -rf "$TARGET"
    echo "removed $PART_DESC from $DATA_DIR"
    exit 0
fi

echo "urjtag data directory: $DATA_DIR"

if grep -q "^$PART_ID" "$PARTS" 2>/dev/null; then
    echo "PARTS entry already present, leaving it alone"
else
    cp -n "$PARTS" "$PARTS.bak" || true
    printf '%s\t%s\t\t%s\n' "$PART_ID" "$PART_DIR" "$PART_DESC" >> "$PARTS"
    echo "added PARTS entry (backup at $PARTS.bak)"
fi

mkdir -p "$TARGET"

{
    printf '0010\t%s-clb1\t2\n' "$PART_DIR"
    printf '0011\t%s-4x4\t3\n'  "$PART_DIR"
} > "$TARGET/STEPPINGS"

# Shared preamble: both builds run the same TAP and the same instruction map.
write_decl() {
    local file="$1" cfgbits="$2" what="$3"
    cat > "$TARGET/$file" <<DECL
# PYNQ-Z2 $what - see rtl/jtag_tap.v
#
# BR  is urjtag's conventional name for the bypass register
# DIR is urjtag's conventional name for the device identification register
# BSR is the 9-bit boundary: bits 8:3 are the input pads, bits 2:0 the outputs
register	BR	1
register	DIR	32
register	BSR	9
register	USERREG	32
register	CFGREG	$cfgbits

instruction length 4
instruction EXTEST         0000 BSR
instruction SAMPLE/PRELOAD 0001 BSR
instruction IDCODE         0010 DIR
instruction USER           0011 USERREG
instruction INTEST         0100 BSR
instruction CONFIG         0101 CFGREG
instruction BYPASS         1111 BR
DECL
}

write_decl "$PART_DIR-clb1" 71   "single CLB"
write_decl "$PART_DIR-4x4"  2896 "4x4 CLB fabric"

echo "installed $PART_DESC:"
echo "  $TARGET/STEPPINGS"
echo "  $TARGET/$PART_DIR-clb1   (71-bit CONFIG)"
echo "  $TARGET/$PART_DIR-4x4    (2896-bit CONFIG)"
echo
echo "verify with:  jtag -n -q host/urjtag-detect.jtag"
