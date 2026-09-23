#!/usr/bin/env bash
# Print hw/sources.f as absolute paths, one per line, comments and blanks removed.
# Every Mac-side tool compiles exactly what Vivado compiles.
#   --sim  also the simulation models of the AMD primitives the RTL instantiates
#          (M22: CFGLUT5, hw/tb/prims/), which Vivado and yosys provide themselves
set -euo pipefail
HW="$(cd "$(dirname "${BASH_SOURCE[0]}")/../hw" && pwd)"
sed -e 's/#.*//' -e 's/[[:space:]]*$//' -e '/^[[:space:]]*$/d' "$HW/sources.f" |
while read -r f; do
    [[ -f "$HW/$f" ]] || { echo "hw/sources.f: missing $f" >&2; exit 1; }
    echo "$HW/$f"
done
if [[ "${1:-}" == "--sim" ]]; then
    for f in "$HW"/tb/prims/*.v; do echo "$f"; done
fi
