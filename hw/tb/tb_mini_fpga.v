// -----------------------------------------------------------------------------
// tb_mini_fpga.v - self-checking testbench for the one-CLB mini FPGA
//
// Drives the TAP exactly the way a real probe does: TMS/TDI change while TCK is
// low, TDO is sampled at the rising edge having been launched by the DUT on the
// previous falling edge.
//
//   run with:  ./run_sim.sh
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module tb_mini_fpga;

    localparam        HALF   = 50;                // 100 ns TCK period
    localparam [31:0] IDCODE = 32'h2BEEF093;

    localparam [3:0] IR_EXTEST = 4'b0000;
    localparam [3:0] IR_SAMPLE = 4'b0001;
    localparam [3:0] IR_IDCODE = 4'b0010;
    localparam [3:0] IR_USER   = 4'b0011;
    localparam [3:0] IR_INTEST = 4'b0100;
    localparam [3:0] IR_CONFIG = 4'b0101;
    localparam [3:0] IR_BYPASS = 4'b1111;

    // USER control word
    localparam integer U_CE = 0, U_SR = 1, U_CIN = 2, U_STEP = 3, U_AUTOSTEP = 4;

    reg        tck = 1'b0;
    reg        tms = 1'b1;
    reg        tdi = 1'b0;
    wire       tdo;
    reg  [5:0] pad_i = 6'b000000;
    wire [2:0] pad_o;
    wire [3:0] tap_state;
    wire       configured;

    reg        tdo_s;
    integer    errors = 0;

    mini_fpga #(.IDCODE_VALUE(IDCODE)) dut (
        .tck(tck), .tms(tms), .tdi(tdi), .tdo(tdo),
        .pad_i(pad_i), .pad_o(pad_o),
        .tap_state(tap_state), .configured(configured)
    );

    // ---------------------------------------------------------------------
    // Probe model
    // ---------------------------------------------------------------------
    task tick(input v_tms, input v_tdi);
        begin
            tms = v_tms; tdi = v_tdi;
            #(HALF);
            tck = 1'b1;
            #1 tdo_s = tdo;
            #(HALF - 1);
            tck = 1'b0;
        end
    endtask

    task goto_reset_then_idle;
        integer i;
        begin
            for (i = 0; i < 5; i = i + 1) tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
        end
    endtask

    task shift_ir(input [3:0] value);
        integer i;
        begin
            tick(1'b1, 1'b0);                     // Select-DR
            tick(1'b1, 1'b0);                     // Select-IR
            tick(1'b0, 1'b0);                     // Capture-IR
            tick(1'b0, 1'b0);                     // -> Shift-IR
            for (i = 0; i < 3; i = i + 1) tick(1'b0, value[i]);
            tick(1'b1, value[3]);                 // last bit + exit
            tick(1'b1, 1'b0);                     // -> Update-IR
            tick(1'b0, 1'b0);                     // -> Run-Test/Idle
        end
    endtask

    task shift_dr(input integer n, input [127:0] din, output [127:0] dout);
        integer i;
        begin
            dout = 128'h0;
            tick(1'b1, 1'b0);                     // Select-DR
            tick(1'b0, 1'b0);                     // Capture-DR
            tick(1'b0, 1'b0);                     // -> Shift-DR
            for (i = 0; i < n - 1; i = i + 1) begin
                tick(1'b0, din[i]);
                dout[i] = tdo_s;
            end
            tick(1'b1, din[n-1]);
            dout[n-1] = tdo_s;
            tick(1'b1, 1'b0);                     // -> Update-DR
            tick(1'b0, 1'b0);                     // -> Run-Test/Idle
        end
    endtask

    // ---------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------
    reg [127:0] rx;

    task load_config(input [63:0] init, input [6:0] ctrl);
        begin
            shift_ir(IR_CONFIG);
            shift_dr(71, {ctrl, init}, rx);
        end
    endtask

    task write_user(input [31:0] value);
        begin
            shift_ir(IR_USER);
            shift_dr(32, value, rx);
        end
    endtask

    // One INTEST scan. Applies `vec` to the LUT inputs at Update-DR and returns
    // the {cout,o5,o} captured at Capture-DR - which answers the PREVIOUS vec.
    task intest(input [5:0] vec, output [2:0] prev_result);
        begin
            shift_dr(9, {vec, 3'b000}, rx);
            prev_result = rx[2:0];
        end
    endtask

    task check(input [511:0] name, input [63:0] got, input [63:0] exp);
        begin
            if (got === exp)
                $display("  PASS  %0s = 0x%0h", name, got);
            else begin
                $display("  FAIL  %0s = 0x%0h, expected 0x%0h", name, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    // Walk the four rows of a 2-input function on i[1:0] and check `o`.
    task check_2input(input [511:0] name, input [63:0] init, input [3:0] truth);
        integer r;
        reg [2:0] res;
        reg       ok;
        reg [3:0] seen;
        begin
            load_config(init, 7'b0000000);        // combinational
            shift_ir(IR_INTEST);
            intest(6'd0, res);                    // prime the pipeline
            ok = 1'b1;
            for (r = 0; r < 4; r = r + 1) begin
                intest((r + 1) % 4, res);         // apply next, read previous
                seen[r] = res[0];
                if (res[0] !== truth[r]) ok = 1'b0;
            end
            if (ok)
                $display("  PASS  %0s  truth=%b  o=%b", name, truth, seen);
            else begin
                $display("  FAIL  %0s  truth=%b  o=%b", name, truth, seen);
                errors = errors + 1;
            end
        end
    endtask

    // ---------------------------------------------------------------------
    integer i, r, bad;
    reg [2:0]   res;
    reg [63:0]  parity_init;
    reg [127:0] cfgword;

    initial begin
        $dumpfile("tb_mini_fpga.vcd");
        $dumpvars(0, tb_mini_fpga);

        $display("");
        $display("=== mini FPGA: one CLB behind an IEEE 1149.1 TAP ===");

        // -- 1. reset and identity -----------------------------------------
        goto_reset_then_idle;
        $display("");
        $display("[1] reset and IDCODE");
        shift_dr(32, 128'h0, rx);
        check("IDCODE", rx[31:0], IDCODE);

        // -- 2. BYPASS ------------------------------------------------------
        $display("");
        $display("[2] BYPASS");
        shift_ir(IR_BYPASS);
        shift_dr(32, 128'hD5A73C91, rx);
        check("BYPASS (delayed one TCK)", rx[31:0], 32'hAB4E7922);

        // -- 3. the configuration chain -------------------------------------
        $display("");
        $display("[3] CONFIG chain, 71 bits, read-write");
        load_config(64'h8888888888888888, 7'b0000000);
        check("configured flag", {63'b0, configured}, 64'h1);
        // CONFIG is read-modify-write like any capture/update register, so a
        // readback shifts the same word back in. Shifting zeros would read the
        // right answer and then commit zeros behind it.
        shift_ir(IR_CONFIG);
        shift_dr(71, {7'b0, 64'h8888888888888888}, rx);
        check("CONFIG readback [63:0]",  rx[63:0],  64'h8888888888888888);
        check("CONFIG readback [70:64]", {57'b0, rx[70:64]}, 64'h0);
        check("config survives readback", {63'b0, configured}, 64'h1);

        // -- 4. the point of the whole exercise -----------------------------
        $display("");
        $display("[4] two-input gates, walked over INTEST");
        $display("      rows are i[1:0] = 00, 01, 10, 11");
        check_2input("AND  ", 64'h8888888888888888, 4'b1000);
        check_2input("OR   ", 64'hEEEEEEEEEEEEEEEE, 4'b1110);
        check_2input("XOR  ", 64'h6666666666666666, 4'b0110);
        check_2input("NAND ", 64'h7777777777777777, 4'b0111);
        check_2input("NOR  ", 64'h1111111111111111, 4'b0001);
        check_2input("XNOR ", 64'h9999999999999999, 4'b1001);

        // -- 5. all 64 rows of a 6-input function ---------------------------
        $display("");
        $display("[5] full 64-row sweep, 6-input parity");
        for (i = 0; i < 64; i = i + 1) parity_init[i] = ^i[5:0];
        load_config(parity_init, 7'b0000000);
        shift_ir(IR_INTEST);
        intest(6'd0, res);
        bad = 0;
        for (r = 0; r < 64; r = r + 1) begin
            intest((r + 1) % 64, res);
            if (res[0] !== (^r[5:0])) bad = bad + 1;
        end
        if (bad == 0)
            $display("  PASS  all 64 rows match parity(i[5:0])");
        else begin
            $display("  FAIL  %0d of 64 rows wrong", bad);
            errors = errors + 1;
        end

        // -- 6. the fracture tap --------------------------------------------
        $display("");
        $display("[6] fracturable LUT: o5 is the LUT5 over INIT[31:0]");
        // INIT[31:0] = AND(i1,i0), INIT[63:32] = OR(i1,i0).
        // o6 therefore depends on i[5], o5 never does.
        load_config({32'hEEEEEEEE, 32'h88888888}, 7'b0000000);
        shift_ir(IR_INTEST);
        intest(6'd0, res);
        intest(6'b000011, res);                   // i=3, i5=0
        intest(6'b100011, res);                   // i=3, i5=1  (reads i5=0 row)
        check("o6 with i5=0 (AND, i1i0=11)", {63'b0, res[0]}, 64'h1);
        check("o5 with i5=0",                {63'b0, res[1]}, 64'h1);
        intest(6'b000000, res);                   // reads the i5=1 row
        check("o6 with i5=1 (OR, i1i0=11)",  {63'b0, res[0]}, 64'h1);

        // -- 7. EXTEST drives the pads --------------------------------------
        $display("");
        $display("[7] EXTEST: the boundary drives the output pads");
        shift_ir(IR_EXTEST);
        shift_dr(9, 9'b000000_101, rx);           // pad_o <= 3'b101
        check("pad_o driven from boundary", {61'b0, pad_o}, 64'h5);
        shift_dr(9, 9'b000000_010, rx);
        check("pad_o driven again",         {61'b0, pad_o}, 64'h2);

        // -- 8. SAMPLE observes the pins without touching them --------------
        $display("");
        $display("[8] SAMPLE: observe the pins, drive nothing");
        pad_i = 6'b101101;
        shift_ir(IR_SAMPLE);
        shift_dr(9, 128'h0, rx);
        check("pad_i observed in bits 8:3", {58'b0, rx[8:3]}, 64'h2D);
        pad_i = 6'b010010;
        shift_dr(9, 128'h0, rx);
        check("pad_i observed again",       {58'b0, rx[8:3]}, 64'h12);

        // -- 9. USER control and status -------------------------------------
        $display("");
        $display("[9] USER: control word in, control + live CLB outputs back");
        pad_i = 6'b000000;
        write_user(32'h0000000F);                 // ce,sr,cin,step all 1
        shift_ir(IR_USER);
        shift_dr(32, 128'h0, rx);
        check("USER control read back", {60'b0, rx[3:0]}, 64'hF);
        write_user(32'h00000000);

        // -- 10. the flip-flop, single-stepped ------------------------------
        $display("");
        $display("[10] flip-flop, advanced one clock at a time");
        // ctrl maps to cfg[70:64]: bit0 FF_EN, bit1 FF_RSTVAL, bit2 FF_CE_EN,
        // bit3 FF_SR_EN, bit4 CY_EN, bit5 CY_DI_SEL, bit6 FF_D_SEL.
        // FF_CE_EN makes the flop wait for a step; FF_SR_EN lets sr reach it.
        load_config(64'hEEEEEEEEEEEEEEEE, 7'b0001101);

        // No AUTOSTEP: applying a vector must NOT advance the flop.
        write_user(32'h00000000);
        shift_ir(IR_INTEST);
        intest(6'b000011, res);                   // apply i=3 (OR -> comb = 1)
        intest(6'b000011, res);
        check("q held with autostep off", {63'b0, res[0]}, 64'h0);

        // AUTOSTEP on: each INTEST scan applies its vector and clocks once.
        write_user(32'h00000010);
        shift_ir(IR_INTEST);
        intest(6'b000011, res);                   // apply i=3 and step
        intest(6'b000011, res);                   // capture q
        check("q after one step",         {63'b0, res[0]}, 64'h1);

        // sr is a level and is synchronous: one more step clears the flop.
        write_user(32'h00000012);                 // sr=1, autostep=1
        shift_ir(IR_INTEST);
        intest(6'b000011, res);
        intest(6'b000011, res);
        check("q cleared by sr",          {63'b0, res[0]}, 64'h0);
        write_user(32'h00000000);

        // -- 11. reset returns to IDCODE ------------------------------------
        $display("");
        $display("[11] reset restores the IDCODE instruction");
        shift_ir(IR_BYPASS);
        goto_reset_then_idle;
        shift_dr(32, 128'h0, rx);
        check("IDCODE after re-reset", rx[31:0], IDCODE);

        // -- summary --------------------------------------------------------
        $display("");
        if (errors == 0) $display("=== ALL TESTS PASSED ===");
        else             $display("=== %0d TEST(S) FAILED ===", errors);
        $display("");

        if (errors != 0) $fatal(1);
        $finish;
    end

    initial begin
        #200_000_000;
        $display("TIMEOUT");
        $fatal(1);
    end

endmodule

`default_nettype wire
