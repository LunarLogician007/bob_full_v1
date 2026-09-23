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
run_one() {                      # run <name> <file under hw/> <perl expression> [tb]
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

# M21: tb_bob takes minutes per run at 56k configuration bits, so mutants run in
# parallel (MUTATE_JOBS, default 4); each writes its verdict to $WORK/<name>.out
JOBS=${MUTATE_JOBS:-4}
run() {
    while [[ $(jobs -rp | wc -l) -ge $JOBS ]]; do sleep 2; done
    ( survivors=0; run_one "$@"; echo "$survivors" > "$WORK/$1.n" ) > "$WORK/$1.out" 2>&1 &
}

F=src/core/cfg_frames.v
run crc-never-fails     $F 's/if \(w == crc\) crc_ok <= 1.b1;/if (1) crc_ok <= 1'"'"'b1;/'
run crc-data-only       $F 's/v = \{r, d\};/v = {5'"'"'d0, d};/'
run idcode-not-checked  $F 's/if \(w == IDCODE_VALUE\) id_ok <= 1.b1;/if (1) id_ok <= 1'"'"'b1;/'
run fdri-ignores-gwe    $F 's/fdri_ok         = wcfg && id_ok && \(!gwe \|\| frozen\) && far_valid/fdri_ok         = wcfg \&\& id_ok \&\& far_valid/'
run fdri-without-wcfg   $F 's/fdri_ok         = wcfg && id_ok && \(!gwe/fdri_ok         = id_ok \&\& (!gwe/'
run far-no-increment    $F 's/far        <= far_next;/far        <= far;/'
run start-without-crc   $F 's/C_START:  if \(crc_ok && id_ok/C_START:  if (id_ok/'
run type2-without-type1 $F 's/pkt_err <= 1.b1; st <= ST_ERR;\n/pkt_err <= pkt_err; st <= ST_HDR;\n/ if /end else begin$/../end$/'
run fdro-without-rcfg   $F 's/\(rcfg && far_valid && fdro_in_range\) \? rd_frame_word/(far_valid \&\& fdro_in_range) ? rd_frame_word/'
run wrong-sync-word     $F "s/32'hAA995566/32'hAA995567/"
run readback-lsb-first  $F 's/assign so = out\[31\];/assign so = out[0];/'
run chain-writes-live   src/fabric/bob_fpga.v 's/\.wen        \(~gwe\),/.wen        (1'"'"'b1),/'
run startup-ignores-frames src/core/cfg_ctrl.v 's/\(committed \| frames_ok\) & \(phase/(committed) \& (phase/'
run frame-write-dropped src/core/cfg_store.v 's/ \|\| \(frame_we && frame_idx == f\[FIDX_W-1:0\]\);/;/'
run frame-load-dropped  src/core/cfg_store.v 's/end else if \(load\)/end else if (1'"'"'b0)/'
run chain-write-dropped src/core/cfg_store.v 's/wire we = \(cwe && cidx == f\[FIDX_W-1:0\]\) \|\| /wire we = /'
run chain-out-no-reload src/core/cfg_store.v 's/if \(chain_out && wrap && more\)/if (1'"'"'b0)/' tb_bob
# M21: the BRAM shadow readback
S=src/core/cfg_store.v
run shadow-no-rewrite   $S 's/if \(swe && wok && !clear\)/if (swe \&\& wok \&\& !clear \&\& !valid[waddr])/'   # a partial rewrite not mirrored
run shadow-wrong-frame  $S 's/rd_q <= shadow\[ridx\];/rd_q <= shadow[ridx ^ 1];/'
run shadow-not-cleared  $S 's/valid <= \{NFRAMES\{1.b0\}\};/valid <= valid;/'
run shadow-frames-only  $S 's/wire              swe   = cwe \|\| frame_we;/wire              swe   = frame_we;/' tb_bob
# M14 partial reconfiguration
run freeze-ignored      src/core/clock_ctrl.v 's/if \(frz_m\[1\]\) begin/if (1'"'"'b0) begin/'
run lfrm-ignores-crc    $F 's/if \(crc_ok && !any_error\) freeze <= 1.b0;/if (1'"'"'b1) freeze <= 1'"'"'b0;/'
run fdri-without-ack    $F 's/wire frozen = freeze & ack_m\[1\];/wire frozen = freeze;/'
run aghigh-without-id   $F 's/if \(id_ok\) freeze <= 1.b1;/if (1'"'"'b1) freeze <= 1'"'"'b1;/'
run ghigh-b-stuck       $F 's/3.b000, ~frozen, gwe,/3'"'"'b000, 1'"'"'b1, gwe,/'
# M15 BRAM content frames
run bram-frames-live    $F 's/if \(wcfg && id_ok && !gwe && !any_error\) begin/if (wcfg \&\& id_ok \&\& !any_error) begin/'
run bram-far-no-cross   $F 's/else if \(far_col \+ 32.d1 < NBRAM\)/else if (1'"'"'b0)/'
run bram-read-word0     src/tiles/bram_jtag.v 's/if \(brd2\) bf_rdata\[bk2\*DATA_W \+: DATA_W\]/if (brd2) bf_rdata[0 +: DATA_W]/'
run bram-no-prefetch    $F 's/                bf_rd_t <= ~bf_rd_t;//'
run bram-write-addr     src/tiles/bram_jtag.v 's/init_addr <= baddr \+ \{\{\(ADDR_W-2\)\{1.b0\}\}, bk\};/init_addr <= baddr;/'
run gce-gap-ignored     src/core/clock_ctrl.v 's/if \(\(req \| pend\) && \(gap >= min_gap\)\) begin/if (req | pend) begin/' tb_clock_gap
run gce-pending-lost    src/core/clock_ctrl.v 's/if \(req\) pend <= 1.b1;/if (req) pend <= 1'"'"'b0;/' tb_clock_gap
# M20: the per-design clock. clk_period / clk_gap must reach the divider and the guard,
# clk_div must prescale a set period, and the floor must hold whatever clk_gap says.
run period-ignored      src/core/clock_ctrl.v 's/wire \[31:0\] last     = \(per_m1 != \{PERIOD_W\{1.b0\}\}\) \? per32 - 32.h1/wire [31:0] last     = (1'"'"'b0) ? per32 - 32'"'"'h1/' tb_clock_gap
run gap-field-ignored   src/core/clock_ctrl.v 's/wire \[31:0\] want_gap = \(gp_m1 != \{PERIOD_W\{1.b0\}\}\) \? gp32/wire [31:0] want_gap = (1'"'"'b0) ? gp32/' tb_clock_gap
run gap-floor-dropped   src/core/clock_ctrl.v 's/wire \[31:0\] min_gap_c = \(\(want_gap < GAP_FLOOR\) \? GAP_FLOOR : want_gap\) - 32.h1;/wire [31:0] min_gap_c = want_gap - 32'"'"'h1;/' tb_clock_gap
run period-reg-stale    src/core/clock_ctrl.v 's/        last_q  <= last;/        last_q  <= last_q;/' tb_clock_gap
run period-no-prescale  src/core/clock_ctrl.v 's/wire \[31:0\] per32    = \{\{\(32-PERIOD_W\)\{1.b0\}\}, per_m1\} << psh;/wire [31:0] per32    = {{(32-PERIOD_W){1'"'"'b0}}, per_m1};/' tb_clock_gap

wait
cat "$WORK"/*.out
survivors=$(cat "$WORK"/*.n | awk '{s += $1} END {print s + 0}')
if [[ $survivors -eq 0 ]]; then echo "all mutants killed"; else echo "$survivors mutant(s) not killed"; exit 1; fi
