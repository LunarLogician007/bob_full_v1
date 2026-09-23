#!/usr/bin/env bash
# Mutation test for the M2 configuration plane: break cfg_ctrl.v on purpose in
# ways that matter, and require tb_cfg.v to FAIL for every mutant. A mutant that
# passes means a guard nothing tests. (The first run found exactly that: the
# length check could be deleted without any test noticing.)
#
#   sim/mutate_cfg.sh        exit 0 only if every mutant is killed
set -uo pipefail
cd "$(dirname "$0")/.."
source sim/mutate_lib.sh          # vvp_verdict: every simulation under a watchdog (M21)

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
sim/gen_cfg_vectors.py >/dev/null

SRC=(); while read -r l; do [[ "$l" == *cfg_ctrl.v ]] || SRC+=("$l"); done < <(sim/hwfiles.sh --sim)

survivors=0
run() {
    local name=$1 expr=$2
    skip "$name" && return
    sed -E "$expr" hw/src/core/cfg_ctrl.v > "$WORK/cfg_ctrl_$name.v"
    if cmp -s hw/src/core/cfg_ctrl.v "$WORK/cfg_ctrl_$name.v"; then
        echo "  ERROR   $name: mutation did not apply (update the pattern)"; survivors=$((survivors+1)); return
    fi
    if ! iverilog -g2012 -DSIMULATION -Ihw/src/generated -Ihw/tb -s tb_cfg -o "$WORK/$name.vvp" \
            "${SRC[@]}" "$WORK/cfg_ctrl_$name.v" hw/tb/tb_cfg.v 2>"$WORK/$name.err"; then
        echo "  ERROR   $name: does not compile"; survivors=$((survivors+1)); return
    fi
    local v; v=$(vvp_verdict "$WORK" "$name.vvp")
    if [[ $v == pass ]]; then
        echo "  SURVIVED $name"; survivors=$((survivors+1))
    else
        echo "  killed  $name$(killed_note "$v")"
    fi
}

run crc-poly       "s/32'h82F63B78/32'h82F63B79/"
run no-crc-guard   's/load_good = crc_good & len_good;/load_good = len_good;/'
run no-len-guard   's/load_good = crc_good & len_good;/load_good = crc_good;/'
run no-write-key   's/\(ctrl_sr\[63:56\] == CTRL_KEY\)/1'"'"'b1/'
run start-no-commit 's/if \(jstart_tick & \(committed \| frames_ok\) & /if (jstart_tick \& /'

if [[ $survivors -eq 0 ]]; then echo "all mutants killed"; else echo "$survivors mutant(s) not killed"; exit 1; fi
