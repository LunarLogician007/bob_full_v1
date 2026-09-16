#!/usr/bin/env bash
# M13 mutation test: break each frame-path and timing guard on purpose; tb_frames (or
# tb_clock_gap for the clock guard) must FAIL. A surviving mutant is a guard nothing tests.
#   sim/mutate_frames.sh      exit 0 only if every mutant is killed
set -uo pipefail
cd "$(dirname "$0")/.."
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
sim/gen_frame_vectors.py >/dev/null

survivors=0
run() {                      # run <name> <file under hw/> <perl expression> [tb]
    local name=$1 file=$2 expr=$3 tb=${4:-tb_frames}
    local src="hw/$file" mut="$WORK/$name-$(basename "$file")"
    perl -pe "$expr" "$src" > "$mut"
    if cmp -s "$src" "$mut"; then echo "  ERROR   $name: mutation did not apply"; survivors=$((survivors+1)); return; fi
    if [[ $tb == tb_clock_gap ]]; then
        iverilog -g2012 -s tb_clock_gap -o "$WORK/$name.vvp" "$mut" hw/tb/tb_clock_gap.v 2>"$WORK/$name.err" || {
            echo "  ERROR   $name: does not compile"; head -3 "$WORK/$name.err"; survivors=$((survivors+1)); return; }
    else
        local SRC=()
        while read -r l; do if [[ "$l" == */$file ]]; then SRC+=("$mut"); else SRC+=("$l"); fi; done < <(sim/hwfiles.sh)
        iverilog -g2012 -DSIMULATION -Ihw/src/generated -Ihw/tb -s tb_frames -o "$WORK/$name.vvp" \
            "${SRC[@]}" hw/tb/tb_frames.v 2>"$WORK/$name.err" || {
            echo "  ERROR   $name: does not compile"; head -3 "$WORK/$name.err"; survivors=$((survivors+1)); return; }
    fi
    if (cd "$WORK" && vvp "$name.vvp" 2>&1 | grep -q 'ALL TESTS PASSED'); then
        echo "  SURVIVED $name"; survivors=$((survivors+1))
    else
        echo "  killed  $name"
    fi
}

F=src/core/cfg_frames.v
run crc-never-fails     $F 's/if \(w == crc\) crc_ok <= 1.b1;/if (1) crc_ok <= 1'"'"'b1;/'
run crc-data-only       $F 's/v = \{r, d\};/v = {5'"'"'d0, d};/'
run idcode-not-checked  $F 's/if \(w == IDCODE_VALUE\) id_ok <= 1.b1;/if (1) id_ok <= 1'"'"'b1;/'
run fdri-ignores-gwe    $F 's/if \(wcfg && id_ok && !gwe && far_valid && !any_error\) begin/if (wcfg \&\& id_ok \&\& far_valid \&\& !any_error) begin/'
run fdri-without-wcfg   $F 's/if \(wcfg && id_ok && !gwe && far_valid && !any_error\) begin/if (id_ok \&\& !gwe \&\& far_valid \&\& !any_error) begin/'
run far-no-increment    $F 's/far        <= far_next;/far        <= far;/'
run start-without-crc   $F 's/C_START:  if \(crc_ok && id_ok/C_START:  if (id_ok/'
run type2-without-type1 $F 's/pkt_err <= 1.b1; st <= ST_ERR;\n/pkt_err <= pkt_err; st <= ST_HDR;\n/ if /end else begin$/../end$/'
run fdro-without-rcfg   $F 's/R_FDRO:   rword = \(rcfg && far_valid\)/R_FDRO:   rword = (far_valid)/'
run wrong-sync-word     $F "s/32'hAA995566/32'hAA995567/"
run readback-lsb-first  $F 's/assign so = out\[31\];/assign so = out[0];/'
run chain-commits-live  src/core/cfg_ctrl.v 's/assign cfg_commit = sel_cfg_in & dr_update & load_good & ~gwe;/assign cfg_commit = sel_cfg_in \& dr_update \& load_good;/'
run startup-ignores-frames src/core/cfg_ctrl.v 's/\(committed \| frames_ok\) & \(phase/(committed) \& (phase/'
run frame-write-dropped src/core/cfg_store.v 's/cfg\[frame_idx\*FB \+: FB\] <= frame_data;/cfg[frame_idx*FB +: FB] <= cfg[frame_idx*FB +: FB];/'
run gce-gap-ignored     src/core/clock_ctrl.v 's/if \(\(req \| pend\) && \(gap >= min_gap\)\) begin/if (req | pend) begin/' tb_clock_gap
run gce-pending-lost    src/core/clock_ctrl.v 's/if \(req\) pend <= 1.b1;/if (req) pend <= 1'"'"'b0;/' tb_clock_gap

if [[ $survivors -eq 0 ]]; then echo "all mutants killed"; else echo "$survivors mutant(s) not killed"; exit 1; fi
