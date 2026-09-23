#!/usr/bin/env bash
# Mutation test for the complete FPGA: break each guard on purpose and require
# hw/tb/tb_bob.v to FAIL. A mutant that passes means a guard nothing tests.
# (Same idea as sim/mutate_cfg.sh, which covers cfg_ctrl.v.)
#
#   sim/mutate_fabric.sh     exit 0 only if every mutant is killed
set -uo pipefail
cd "$(dirname "$0")/.."

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
sim/gen_vectors.py >/dev/null
sim/gen_bram_vectors.py >/dev/null
sim/gen_dsp_vectors.py >/dev/null
sim/gen_clb_vectors.py >/dev/null

survivors=0
# run <name> <file relative to hw/> <sed -E expression>
run_one() {
    local name=$1 file=$2 expr=$3
    local src="hw/$file" mut="$WORK/$name-$(basename "$file")"
    sed -E "$expr" "$src" > "$mut"
    if cmp -s "$src" "$mut"; then
        echo "  ERROR   $name: mutation did not apply (update the pattern)"; survivors=$((survivors+1)); return
    fi
    local SRC=()
    while read -r l; do
        if [[ "$l" == */$file ]]; then SRC+=("$mut"); else SRC+=("$l"); fi
    done < <(sim/hwfiles.sh)
    # M21: the element and the crossbar have the cluster unit bench (tb_clb, every mode,
    # every crossbar select, both flip-flops): seconds, where tb_bob takes minutes, so first
    if [[ "$file" == src/clb/ble.sv || "$file" == src/generated/bob_fabric.v ]]; then
        if iverilog -g2012 -DSIMULATION -Ihw/src/generated -Ihw/tb -s tb_clb -o "$WORK/$name-clb.vvp" \
                "${SRC[@]}" hw/tb/tb_clb.sv 2>/dev/null \
           && ! (cd "$WORK" && vvp "$name-clb.vvp" 2>&1 | grep -q 'ALL TESTS PASSED'); then
            echo "  killed  $name (tb_clb)"; return
        fi
    fi
    if ! iverilog -g2012 -DSIMULATION -Ihw/src/generated -Ihw/tb -s tb_bob -o "$WORK/$name.vvp" \
            "${SRC[@]}" hw/tb/tb_bob.v 2>"$WORK/$name.err"; then
        echo "  ERROR   $name: does not compile"; sed 's/^/          /' "$WORK/$name.err" | head -5
        survivors=$((survivors+1)); return
    fi
    if ! (cd "$WORK" && vvp "$name.vvp" 2>&1 | grep -q 'ALL TESTS PASSED'); then
        echo "  killed  $name"; return
    fi
    # bram_core.v / dsp_core.v also have exhaustive unit benches; a mutant must fail one
    local unit=""
    [[ "$file" == src/tiles/bram_core.v ]] && unit=tb_bram
    [[ "$file" == src/tiles/dsp_core.v  ]] && unit=tb_dsp
    if [[ -n "$unit" ]]; then
        if iverilog -g2012 -DSIMULATION -Ihw/tb -s "$unit" -o "$WORK/$name-unit.vvp" \
                "$mut" "hw/tb/$unit.v" 2>/dev/null \
           && ! (cd "$WORK" && vvp "$name-unit.vvp" 2>&1 | grep -q 'ALL TESTS PASSED'); then
            echo "  killed  $name ($unit)"; return
        fi
    fi
    echo "  SURVIVED $name"; survivors=$((survivors+1))
}

# M21: tb_bob takes minutes per run at 56k configuration bits, so mutants run in
# parallel (MUTATE_JOBS, default 4); each writes its verdict to $WORK/<name>.out
JOBS=${MUTATE_JOBS:-4}
run() {
    while [[ $(jobs -rp | wc -l) -ge $JOBS ]]; do sleep 2; done
    ( survivors=0; run_one "$@"; echo "$survivors" > "$WORK/$1.n" ) > "$WORK/$1.out" 2>&1 &
}

# M3 startup signals (M21: the element, ble.sv, holds the flip-flops clb.sv held)
run no-gsr          src/clb/ble.sv        's/if \(gsr\)                          q <= ff_rstval;/if (1'"'"'b0)                         q <= ff_rstval;/'
run no-gwe-freeze   src/clb/ble.sv        's/else if \(gwe && gce\) begin/else if (gce) begin/'
run no-gts          src/fabric/bob_fpga.v 's/gts \? \{NPAD\{1'"'"'b0\}\} : fab_pad_out/fab_pad_out/'
run done-is-commit  src/fabric/bob_fpga.v 's/assign configured = done;/assign configured = committed;/'
# M4 user clock and routed CE
run no-gce          src/clb/ble.sv        's/else if \(gwe && gce\) begin/else if (gwe) begin/'
run ce-not-routed   src/clb/ble.sv        's/else if \(!ff_ce_en \|\| ce\)       q <= comb;/else if (1'"'"'b1)       q <= comb;/'
# M21 the autostep clock a TCK after the new pad inputs (M20's bob-fir race)
run autostep-same-edge  src/core/jtag_tap6.v 's/autostep_arm <= autostep_req;/autostep_arm <= (state == UPDATE_DR) \&\& (ir == IR_INTEST) \&\& bsr_on \&\& user_out[USER_AUTOSTEP];/'
# M21 the cluster: crossbar, fracturable LUT, carry through the elements, second flip-flop
run xbar-sel-off-by-one src/generated/bob_fabric.v 's/m0_0 \(\.sel\(cfg\[([0-9]+) \+: ([0-9]+)\]\)/m0_0 (.sel(cfg[\1 +: \2] + 1'"'"'b1)/'
run lut5-halves-swapped src/clb/ble.sv    's/wire \[K-1:0\] li = \{i\[K-1\] \| frac, i\[K-2:0\]\};/wire [K-1:0] li = {i[K-1] \& ~frac, i[K-2:0]};/'
run carry-broken-e1     src/generated/bob_fabric.v 's/u_e1 (.*)\.cin\(cy\[1\]\)/u_e1 \1.cin(1'"'"'b0)/'
run ff2-ce-ignored      src/clb/ble.sv    's/else if \(!ff2_ce_en \|\| ce\)      q2 <= comb2;/else if (1'"'"'b1)      q2 <= comb2;/'
run ff2-is-ff1          src/clb/ble.sv    's/assign o2 = ff2_en \? q2 : comb2;/assign o2 = ff2_en ? q : comb2;/'
run xbar-no-feedback    src/generated/bob_fabric.v 's/m0_0 \(\.sel\(cfg\[([0-9]+) \+: ([0-9]+)\]\), \.in\(\{o\[19\]/m0_0 (.sel(cfg[\1 +: \2]), .in({1'"'"'b0/'
run step-ignores-ce src/core/clock_ctrl.v 's/else           req = \(tck_rise & ce_m\[1\]\) \| step_rise;/else           req = tck_rise | step_rise;/'
run divider-off-by-1 src/core/clock_ctrl.v 's/cnt >= last/cnt > last/g'
# M5 BRAM
run bram-no-write-first src/tiles/bram_core.v 's/\(we_qa && wmode_a == WRITE_FIRST\) \? din_qa :/1'"'"'b0 ? din_qa :/'
run bram-no-no-change   src/tiles/bram_core.v 's/\(we_qa && wmode_a == NO_CHANGE\)   \? hold_qa :/1'"'"'b0 ? hold_qa :/'
run bram-en-ignored     src/tiles/bram_core.v 's/ce_a  = init_go \| \(user & en_a\);/ce_a  = init_go | user;/'
run bram-reg-no-regce   src/tiles/bram_core.v 's/else if \(regce_b\) reg_qb <= latch_b;/else reg_qb <= latch_b;/'
run bram-rega-no-regce  src/tiles/bram_core.v 's/else if \(regce_a\) reg_qa <= latch_a;/else reg_qa <= latch_a;/'
run bram-init-unlocked  src/tiles/bram_jtag.v 's/if \(!gwe_s\) begin/if (1'"'"'b1) begin/'
# M6 DSP
run dsp-no-d-sub        src/tiles/dsp_core.v  's/\(d_sub \? \(d_v - a_v\) : \(d_v \+ a_v\)\)/(d_v + a_v)/'
run dsp-shift-16        src/tiles/dsp_core.v  's/\(pcin >>> 17\)/(pcin >>> 16)/'
run dsp-no-mreg         src/tiles/dsp_core.v  's/m_v = mreg \? m_q : m_c;/m_v = m_c;/'
run dsp-cep-ignored     src/tiles/dsp_core.v  's/else if \(ce_p\)  p_q <= p_c;/else p_q <= p_c;/'
run dsp-no-cascade      src/tiles/dsp_block.v 's/\.pcin   \(pcin\),/.pcin   (48'"'"'h0),/'
# M7 generated fabric
run mux-no-const1       src/fabric/bob_mux.v  's/in, 1'"'"'b1, 1'"'"'b0\}/in, 1'"'"'b0, 1'"'"'b0}/'
run mux-inputs-shifted  src/fabric/bob_mux.v  's/N - 1\)\{1'"'"'b0\}\}, in, 1'"'"'b0\}/N - 1){1'"'"'b0}}, 1'"'"'b0, in}/'
run carry-direct-cut    src/generated/bob_fabric.v 's/= r[0-9]+;   \/\/ clb_x8y2\.cin\[0\]/= 1'"'"'b0;   \/\/ clb_x8y2.cin[0]/'   # the counter crossing CLBs (designs.FULL_COL_X)
run bram-select-ignored src/tiles/bram_jtag.v 's/assign tgt_onehot\[gi\] = \(tgt_q == IDX\);/assign tgt_onehot[gi] = (IDX == 4'"'"'d0);/'
run bram-port-a-no-jtag src/tiles/bram_block.v 's/cfg\[6\] \? drive\[31:0\]  : pin\[31:0\]/pin[31:0]/'
run dsp-b-no-jtag       src/tiles/dsp_block.v 's/cfg\[11\] \? drive\[42:25\]   : b/b/'

wait
cat "$WORK"/*.out
survivors=$(cat "$WORK"/*.n | awk '{s += $1} END {print s + 0}')
if [[ $survivors -eq 0 ]]; then echo "all mutants killed"; else echo "$survivors mutant(s) not killed"; exit 1; fi
