// -----------------------------------------------------------------------------
// tb_frames.v - the frame configuration path on the complete bob FPGA (M13)
//
// UG470-style packet streams on CFG_IN / CFG_OUT (docs/bitstream-format.md section
// 10), built by tools/bob/packets.py; every expected STAT, memory and LED value
// comes from its Controller model, host/bitstream.py and model.py (frame_vectors.vh,
// sim/gen_frame_vectors.py), never from this RTL.
//
//   [1] a good frame load: STAT, memory == chain word, CHAIN_OUT readback of the
//       same memory, JSTART -> DONE, LEDs == model
//   [2] FDRO readback of every frame while running
//   [3] garbage before the sync word, the stream split over three DR scans
//   [4] one flipped frame bit: CRC_ERROR, START refused, JSTART cannot finish
//   [5] wrong IDCODE: ID_ERROR, nothing written
//   [6] frames sent while the design runs (GWE = 1): WR_ERROR, memory unchanged
//   [7] a type-2 header without a type-1: PKT_ERROR
//   [8] FDRI without WCFG: WR_ERROR
//   [9] the chain path still loads after the frame path (both write one memory)
//  [10] a good chain sent while the design runs (GWE = 1) does not commit
//  [11] frames with no CRC write: written, but START refused and DONE never rises
//  [12] FDRO without RCFG: zeros and WR_ERROR
//  [13] M14 partial reconfiguration of a running design (free-running counter + a
//       gate): AGHIGH -> STAT GHIGH_B = 0 -> changed frames only -> CRC -> LFRM.
//       No user-clock enable while frozen, the counter continues from where it was,
//       the gate is now OR, memory == the new design
//  [14] a partial with no CRC write: WR_ERROR at LFRM, the fabric stays frozen
//  [15] AGHIGH without a matched IDCODE: WR_ERROR, nothing frozen
//  [16] a partial with a bad CRC: CRC_ERROR, the fabric stays frozen
//  [17] frames sent before the freeze is acknowledged: WR_ERROR, nothing written
//  [18] M15 BRAM contents as frames (FAR block type 1) before startup: bram0 and, by FAR
//       auto-increment past bram0's last frame, bram1; FDRO readback of the same frames
//  [19] a BRAM content frame while the design runs: WR_ERROR, contents unchanged
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module tb_frames;

    `include "frame_vectors.vh"          // first: it sets TB_IDCODE for the harness
    `include "bob_harness.vh"

    localparam [5:0] IR_PKT_IN  = 6'b000101;     // CFG_IN
    localparam [5:0] IR_PKT_OUT = 6'b000100;     // CFG_OUT
    localparam integer SW = 40960;

    reg [SW-1:0]     big;
    reg [31:0]       statw;
    reg [SW-1:0]     want_rb;
    integer          k;
    wire [3:0]       prq = `PR_Q;
    reg  [3:0]       prq0;
    integer          pulses = 0, p_rel = -1;
    reg              count_en = 1'b0;
    always @(posedge sysclk) if (count_en && dut.gce) pulses = pulses + 1;
    always @(negedge dut.freeze) if (count_en) p_rel = pulses;

    task check(input [1023:0] what, input [63:0] got, input [63:0] want);
        begin
            checks = checks + 1;
            if (got !== want) begin
                errors = errors + 1;
                $display("  FAIL  %0s: got %h, want %h", what, got, want);
            end else
                $display("  PASS  %0s = 0x%0h", what, got);
        end
    endtask

    task shift_stream(input integer n, input [SW-1:0] v);
        integer i;
        begin
            tick(1'b1, 1'b0); tick(1'b0, 1'b0); tick(1'b0, 1'b0);          // Select-DR, Capture-DR, Shift-DR
            clk_on = 1'b0;
            for (i = 0; i < n - 1; i = i + 1) tick(1'b0, v[i]);
            clk_on = 1'b1;
            tick(1'b1, v[n-1]);                                              // Exit1-DR
            tick(1'b1, 1'b0); tick(1'b0, 1'b0);                              // Update-DR, Run-Test/Idle
        end
    endtask

    // M15: the BRAM side runs on sysclk, so these scans keep it running
    task shift_stream_clk(input integer n, input [SW-1:0] v);
        integer i;
        begin
            tick(1'b1, 1'b0); tick(1'b0, 1'b0); tick(1'b0, 1'b0);
            for (i = 0; i < n - 1; i = i + 1) tick(1'b0, v[i]);
            tick(1'b1, v[n-1]);
            tick(1'b1, 1'b0); tick(1'b0, 1'b0);
        end
    endtask

    task read_out_clk(input integer n, output [SW-1:0] v);
        integer i;
        begin
            v = {SW{1'b0}};
            tick(1'b1, 1'b0); tick(1'b0, 1'b0); tick(1'b0, 1'b0);
            for (i = 0; i < n - 1; i = i + 1) begin
                tick(1'b0, 1'b0);
                v[i] = tdo_s;
            end
            tick(1'b1, 1'b0);
            v[n-1] = tdo_s;
            tick(1'b1, 1'b0); tick(1'b0, 1'b0);
        end
    endtask

    task read_out(input integer n, output [SW-1:0] v);
        integer i;
        begin
            v = {SW{1'b0}};
            tick(1'b1, 1'b0); tick(1'b0, 1'b0); tick(1'b0, 1'b0);
            clk_on = 1'b0;
            for (i = 0; i < n - 1; i = i + 1) begin
                tick(1'b0, 1'b0);
                v[i] = tdo_s;
            end
            clk_on = 1'b1;
            tick(1'b1, 1'b0);
            v[n-1] = tdo_s;
            tick(1'b1, 1'b0); tick(1'b0, 1'b0);
        end
    endtask

    // STAT: nothing queued -> CFG_OUT returns STAT (MSB first)
    task read_stat(output [31:0] s);
        integer i;
        begin
            shift_ir(IR_PKT_OUT, irc);
            read_out(32, big);
            for (i = 0; i < 32; i = i + 1) s[31 - i] = big[i];
        end
    endtask

    task send(input integer n, input [SW-1:0] v);
        begin
            shift_ir(IR_PKT_IN, irc);
            shift_stream(n, v);
        end
    endtask

    task jprogram;
        begin
            write_user1(32'h0);
            shift_ir(IR_JPROGRAM, irc);
        end
    endtask

    initial begin
        $display("");
        $display("=== frame configuration path on the complete bob FPGA (M13) ===");
        tick(1'b1, 1'b0); tick(1'b1, 1'b0); tick(1'b1, 1'b0); tick(1'b1, 1'b0); tick(1'b1, 1'b0);
        tick(1'b0, 1'b0);

        $display("[1] good frame load (showcase)");
        jprogram;
        send(`GOOD_N, `GOOD_V);
        read_stat(statw);
        check("STAT after the load (START accepted, no error)", {32'h0, statw}, {32'h0, `GOOD_STAT});
        check("memory == the chain word", {63'h0, dut.chain_cfg === `SHOW_W}, 64'h1);
        shift_ir(IR_CHAIN_OUT, irc);
        shift_chain({CFG_W{1'b0}});
        check("CHAIN_OUT scan leaves the memory untouched", {63'h0, dut.chain_cfg === `SHOW_W}, 64'h1);
        start;
        check("DONE after JSTART", {63'h0, configured}, 64'h1);
        read_stat(statw);
        check("STAT after startup", {32'h0, statw}, {32'h0, `GOOD_STAT_DONE});
        pad_i = 6'b000000; #40; check("showcase LEDs, SW1..0 = 00", {61'h0, pad_o}, {61'h0, `SHOW_PAD0});
        pad_i = 6'b000001; #40; check("showcase LEDs, SW1..0 = 01", {61'h0, pad_o}, {61'h0, `SHOW_PAD1});
        pad_i = 6'b000010; #40; check("showcase LEDs, SW1..0 = 10", {61'h0, pad_o}, {61'h0, `SHOW_PAD2});
        pad_i = 6'b000011; #40; check("showcase LEDs, SW1..0 = 11", {61'h0, pad_o}, {61'h0, `SHOW_PAD3});

        $display("[2] FDRO readback of every frame, design running");
        send(`RB_N, `RB_V);
        shift_ir(IR_PKT_OUT, irc);
        read_out(32 * `RB_WORDS, big);
        check("FDRO readback == the frames loaded", {63'h0, big[32*`RB_WORDS-1:0] === `RB_EXP}, 64'h1);
        want_rb = `RB_EXP;
        if (big[32*`RB_WORDS-1:0] !== want_rb)
            $display("        got  %h\n        want %h", big[255:0], want_rb[255:0]);

        $display("[6] frames while the design runs (GWE = 1)");
        send(`LIVE_N, `LIVE_V);
        read_stat(statw);
        check("STAT: WR_ERROR, START not accepted", {32'h0, statw}, {32'h0, `LIVE_STAT});
        check("memory unchanged", {63'h0, dut.chain_cfg === `SHOW_W}, 64'h1);
        check("still DONE", {63'h0, configured}, 64'h1);

        $display("[3] garbage before sync, stream split over three scans (counter)");
        jprogram;
        send(`SPLIT0_N, `SPLIT0_V);
        send(`SPLIT1_N, `SPLIT1_V);
        send(`SPLIT2_N, `SPLIT2_V);
        read_stat(statw);
        check("STAT after the split load", {32'h0, statw}, {32'h0, `SPLIT_STAT});
        check("memory == counter chain word", {63'h0, dut.chain_cfg === `CNT_W}, 64'h1);

        $display("[4] one flipped frame bit");
        jprogram;
        send(`BADCRC_N, `BADCRC_V);
        read_stat(statw);
        check("STAT: CRC_ERROR", {32'h0, statw}, {32'h0, `BADCRC_STAT});
        check("memory as the model wrote it before the CRC check", {63'h0, dut.chain_cfg === `BADCRC_MEM}, 64'h1);
        shift_ir(IR_JSTART, irc);
        idle(12);
        check("JSTART cannot finish: DONE stays 0", {63'h0, configured}, 64'h0);
        check("IR capture: INIT_B low, CRC_ERR", {58'h0, irc}, {58'h0, 6'b000101});
        shift_ir(IR_BYPASS, irc);

        $display("[5] wrong IDCODE");
        jprogram;
        send(`BADID_N, `BADID_V);
        read_stat(statw);
        check("STAT: ID_ERROR", {32'h0, statw}, {32'h0, `BADID_STAT});
        check("nothing written", {63'h0, dut.chain_cfg === {CFG_W{1'b0}}}, 64'h1);

        $display("[7] packet error");
        jprogram;
        send(`PKT_N, `PKT_V);
        read_stat(statw);
        check("STAT: PKT_ERROR", {32'h0, statw}, {32'h0, `PKT_STAT});

        $display("[8] FDRI without WCFG");
        jprogram;
        send(`NOWCFG_N, `NOWCFG_V);
        read_stat(statw);
        check("STAT: WR_ERROR", {32'h0, statw}, {32'h0, `NOWCFG_STAT});
        check("nothing written", {63'h0, dut.chain_cfg === {CFG_W{1'b0}}}, 64'h1);

        $display("[9] the chain path after the frame path");
        cfgw = `CNT_W; cfgcrc = `CNT_CRC; dname = "counter over the chain";
        commit_config;
        check("chain commit", {63'h0, dut.chain_cfg === `CNT_W}, 64'h1);
        start;
        check("DONE", {63'h0, configured}, 64'h1);

        $display("[10] a good chain while the design runs (GWE = 1)");
        shift_ir(IR_CFG_CTRL, irc);
        shift_dr(64, {64'h0, 8'hC5, 24'h0, `SHOW_CRC}, rx);
        shift_ir(IR_CHAIN_IN, irc);
        shift_chain(`SHOW_W);
        check("not committed: memory still the counter", {63'h0, dut.chain_cfg === `CNT_W}, 64'h1);
        check("still DONE", {63'h0, configured}, 64'h1);

        $display("[11] frames with no CRC write");
        jprogram;
        send(`NOCRC_N, `NOCRC_V);
        read_stat(statw);
        check("STAT: frames in, START not accepted, no error", {32'h0, statw}, {32'h0, `NOCRC_STAT});
        check("memory written", {63'h0, dut.chain_cfg === `SHOW_W}, 64'h1);
        shift_ir(IR_JSTART, irc);
        idle(12);
        check("JSTART does nothing: DONE stays 0", {63'h0, configured}, 64'h0);
        shift_ir(IR_BYPASS, irc);

        $display("[12] FDRO without RCFG");
        send(`NORCFG_N, `NORCFG_V);
        shift_ir(IR_PKT_OUT, irc);
        read_out(32 * `RB_WORDS, big);
        check("reads zeros", {63'h0, big[32*`RB_WORDS-1:0] === {(32*`RB_WORDS){1'b0}}}, 64'h1);
        read_stat(statw);
        check("STAT: WR_ERROR", {32'h0, statw}, {32'h0, `NORCFG_STAT});

        $display("[13] M14: partial reconfiguration of a running design");
        jprogram;
        send(`PRLOAD_N, `PRLOAD_V);
        start;
        write_user1(32'h4);                                   // USER1 cin = 1: the counter counts
        pad_i = 6'b000001; #40;
        check("design A: LD1 = SW0 AND SW1 (01)", {63'h0, pad_o[1]}, 64'h0);
        prq0 = prq; #400;
        check("design A: the counter runs", {63'h0, prq !== prq0}, 64'h1);
        send(`PRFRZ_N, `PRFRZ_V);
        read_stat(statw);
        check("STAT after AGHIGH: GHIGH_B = 0 (frozen), no error", {32'h0, statw}, {32'h0, `PRFRZ_STAT});
        prq0 = prq; pulses = 0; p_rel = -1; count_en = 1'b1;
        #400;
        check("frozen: no gce in 400 ns", pulses, 0);
        check("frozen: counter holds", {60'h0, prq}, {60'h0, prq0});
        send(`PRFRM_N, `PRFRM_V);
        count_en = 1'b0;
        check("no gce between the freeze and LFRM (whole partial write)", p_rel, 0);
        check("memory == design B", {63'h0, dut.chain_cfg === `PRB_W}, 64'h1);
        count_en = 1'b1;
        #400;
        count_en = 1'b0;
        check("counter continued from its frozen value", {60'h0, prq}, {60'h0, prq0 + pulses[3:0]});
        check("  (enables after release)", {63'h0, pulses > 10}, 64'h1);
        read_stat(statw);
        check("STAT after LFRM: released (GHIGH_B = 1), no error", {32'h0, statw}, {32'h0, `PRFRM_STAT});
        check("still DONE", {63'h0, configured}, 64'h1);
        pad_i = 6'b000001; #40;
        check("design B: LD1 = SW0 OR SW1 (01)", {63'h0, pad_o[1]}, 64'h1);
        pad_i = 6'b000000; #40;
        check("design B: LD1 (00)", {63'h0, pad_o[1]}, 64'h0);
        $display("        %0d changed frame(s) written", `PR_NFRAMES);

        $display("[14] partial with no CRC write: LFRM refused, stays frozen");
        send(`PRNCF_N, `PRNCF_V);
        read_stat(statw);
        send(`PRNC_N, `PRNC_V);
        read_stat(statw);
        check("STAT: WR_ERROR, GHIGH_B = 0", {32'h0, statw}, {32'h0, `PRNC_STAT});
        check("frames landed: memory == design A", {63'h0, dut.chain_cfg === `PRA_W}, 64'h1);
        prq0 = prq; pulses = 0; count_en = 1'b1;
        #400;
        count_en = 1'b0;
        check("still frozen: no gce", pulses, 0);
        check("still frozen: counter holds", {60'h0, prq}, {60'h0, prq0});
        check("DONE kept", {63'h0, configured}, 64'h1);

        $display("[15] AGHIGH without IDCODE");
        jprogram;
        write_user1(32'h0);
        send(`PRNOID_N, `PRNOID_V);
        read_stat(statw);
        check("STAT: WR_ERROR, GHIGH_B = 1", {32'h0, statw}, {32'h0, `PRNOID_STAT});
        check("freeze not requested", {63'h0, dut.freeze}, 64'h0);

        $display("[16] partial with a bad CRC: stays frozen");
        jprogram;
        send(`PRLOAD_N, `PRLOAD_V);
        start;
        write_user1(32'h4);
        send(`PRBADF_N, `PRBADF_V);
        read_stat(statw);
        send(`PRBAD_N, `PRBAD_V);
        read_stat(statw);
        check("STAT: CRC_ERROR, GHIGH_B = 0", {32'h0, statw}, {32'h0, `PRBAD_STAT});
        prq0 = prq; pulses = 0; count_en = 1'b1;
        #400;
        count_en = 1'b0;
        check("still frozen: no gce", pulses, 0);
        check("still frozen: counter holds", {60'h0, prq}, {60'h0, prq0});

        $display("[17] frames before the freeze is acknowledged (one scan, sysclk stopped)");
        jprogram;
        send(`PRLOAD_N, `PRLOAD_V);
        start;
        send(`PRONE_N, `PRONE_V);
        read_stat(statw);
        check("STAT: WR_ERROR", {32'h0, statw}, {32'h0, `PRONE_STAT});
        check("memory unchanged: design A", {63'h0, dut.chain_cfg === `PRA_W}, 64'h1);

        $display("[18] M15: BRAM contents as frames, before startup");
        jprogram;
        write_user1(32'h0);
        shift_ir(IR_PKT_IN, irc);
        shift_stream_clk(`BRW_N, `BRW_V);
        idle(4);
        read_stat(statw);
        check("STAT after the BRAM frames: CRC_OK, no error", {32'h0, statw}, {32'h0, `BRW_STAT});
        check("bram0[12]", {46'h0, dut.u_fabric.u_bram0.u_core.mem[12]}, {46'h0, `BR0_0});
        check("bram0[17]", {46'h0, dut.u_fabric.u_bram0.u_core.mem[17]}, {46'h0, `BR0_5});
        check("bram0[23]", {46'h0, dut.u_fabric.u_bram0.u_core.mem[23]}, {46'h0, `BR0_11});
        check("bram0[1020] (last frame)", {46'h0, dut.u_fabric.u_bram0.u_core.mem[1020]}, {46'h0, `BR1_0});
        check("bram0[1023]", {46'h0, dut.u_fabric.u_bram0.u_core.mem[1023]}, {46'h0, `BR1_3});
        check("bram1[0] (FAR crossed into bram1)", {46'h0, dut.u_fabric.u_bram1.u_core.mem[0]}, {46'h0, `BR1_4});
        check("bram1[3]", {46'h0, dut.u_fabric.u_bram1.u_core.mem[3]}, {46'h0, `BR1_7});
        shift_ir(IR_PKT_IN, irc);
        shift_stream_clk(`BRRB_N, `BRRB_V);
        shift_ir(IR_PKT_OUT, irc);
        read_out_clk(32 * 8, big);
        check("FDRO readback of 2 BRAM frames (bram0 1020..1023, bram1 0..3)", {63'h0, big[255:0] === `BRRB_EXP}, 64'h1);
        if (big[255:0] !== `BRRB_EXP) $display("        got  %h\n        want %h", big[255:0], `BRRB_EXP);
        read_stat(statw);
        check("STAT after the BRAM readback", {32'h0, statw}, {32'h0, `BRRB_STAT});

        $display("[19] a BRAM content frame while running");
        jprogram;
        send(`PRLOAD_N, `PRLOAD_V);
        start;
        shift_ir(IR_PKT_IN, irc);
        shift_stream_clk(`BRLIVE_N, `BRLIVE_V);
        idle(4);
        read_stat(statw);
        check("STAT: WR_ERROR", {32'h0, statw}, {32'h0, `BRLIVE_STAT});
        check("bram0[12] unchanged", {46'h0, dut.u_fabric.u_bram0.u_core.mem[12]}, {46'h0, `BR0_0});

        $display("");
        $display("    %0d checks", checks);
        if (errors == 0) $display("=== ALL TESTS PASSED ===");
        else             $display("=== %0d CHECK(S) FAILED ===", errors);
        if (errors != 0) $fatal(1);
        $finish;
    end

endmodule

`default_nettype wire
