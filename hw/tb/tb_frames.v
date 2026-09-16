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
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module tb_frames;

    `include "frame_vectors.vh"          // first: it sets TB_IDCODE for the harness
    `include "bob_harness.vh"

    localparam [5:0] IR_PKT_IN  = 6'b000101;     // CFG_IN
    localparam [5:0] IR_PKT_OUT = 6'b000100;     // CFG_OUT
    localparam integer SW = 16384;

    reg [SW-1:0]     big;
    reg [31:0]       statw;
    reg [SW-1:0]     want_rb;
    integer          k;

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

        $display("");
        $display("    %0d checks", checks);
        if (errors == 0) $display("=== ALL TESTS PASSED ===");
        else             $display("=== %0d CHECK(S) FAILED ===", errors);
        if (errors != 0) $fatal(1);
        $finish;
    end

endmodule

`default_nettype wire
