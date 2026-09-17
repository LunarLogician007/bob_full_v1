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
        iverilog -g2012 -DSIMULATION -Ihw/src/generated -Ihw/tb -s "$tb" -o "$WORK/$name.vvp" \
            "${SRC[@]}" "hw/tb/$tb.v" 2>"$WORK/$name.err" || {
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
run fdri-ignores-gwe    $F 's/fdri_ok         = wcfg && id_ok && !gwe && far_valid/fdri_ok         = wcfg \&\& id_ok \&\& far_valid/'
run fdri-without-wcfg   $F 's/fdri_ok         = wcfg && id_ok && !gwe/fdri_ok         = id_ok \&\& !gwe/'
run far-no-increment    $F 's/far        <= far_next;/far        <= far;/'
run start-without-crc   $F 's/C_START:  if \(crc_ok && id_ok/C_START:  if (id_ok/'
run type2-without-type1 $F 's/pkt_err <= 1.b1; st <= ST_ERR;\n/pkt_err <= pkt_err; st <= ST_HDR;\n/ if /end else begin$/../end$/'
run fdro-without-rcfg   $F 's/R_FDRO:   rword = \(rcfg && far_valid && fdro_in_range\)/R_FDRO:   rword = (far_valid \&\& fdro_in_range)/'
run wrong-sync-word     $F "s/32'hAA995566/32'hAA995567/"
run readback-lsb-first  $F 's/assign so = out\[31\];/assign so = out[0];/'
run chain-writes-live   src/fabric/bob_fpga.v 's/\.wen        \(~gwe\),/.wen        (1'"'"'b1),/'
run startup-ignores-frames src/core/cfg_ctrl.v 's/\(committed \| frames_ok\) & \(phase/(committed) \& (phase/'
run frame-write-dropped src/core/cfg_store.v 's/ \|\| \(frame_we && frame_idx == f\[FIDX_W-1:0\]\);/;/'
run frame-load-dropped  src/core/cfg_store.v 's/end else if \(load\)/end else if (1'"'"'b0)/'
run chain-write-dropped src/core/cfg_store.v 's/wire we = \(cwe && cidx == f\[FIDX_W-1:0\]\) \|\| /wire we = /'
run chain-out-no-reload src/core/cfg_store.v 's/if \(chain_out && wrap && more\)/if (1'"'"'b0)/' tb_bob
run gce-gap-ignored     src/core/clock_ctrl.v 's/if \(\(req \| pend\) && \(gap >= min_gap\)\) begin/if (req | pend) begin/' tb_clock_gap
run gce-pending-lost    src/core/clock_ctrl.v 's/if \(req\) pend <= 1.b1;/if (req) pend <= 1'"'"'b0;/' tb_clock_gap

if [[ $survivors -eq 0 ]]; then echo "all mutants killed"; else echo "$survivors mutant(s) not killed"; exit 1; fi
