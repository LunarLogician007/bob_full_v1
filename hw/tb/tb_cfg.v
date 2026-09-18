// -----------------------------------------------------------------------------
// tb_cfg.v - self-checking testbench for the M2 configuration plane
//
// Drives cfg_test_top through its JTAG pins only, with the probe tasks from
// tb_fpga4x4.v widened to a 6-bit IR. Expected CRCs come from
// sim/gen_cfg_vectors.py (software/bob/chainbits.py) via cfg_vectors.vh.
// Checks every "done when" item of M2 in PLAN.md.
//
//   sim/run_cfg_sim.sh
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module tb_cfg;

    localparam        HALF     = 50;
    localparam [31:0] IDCODE   = 32'h4BEEF093;
    localparam [31:0] USERCODE = 32'h00000002;
    localparam integer W       = 64;

    localparam [5:0] IR_USER1    = 6'b000010;
    localparam [5:0] IR_CFG_CTRL = 6'b000011;
    localparam [5:0] IR_CHAIN_OUT = 6'b110100;   // M13: the chain (private); CFG_OUT is the packet port
    localparam [5:0] IR_CHAIN_IN  = 6'b110101;   // M13: the chain (private); CFG_IN is the packet port
    localparam [5:0] IR_USERCODE = 6'b001000;
    localparam [5:0] IR_IDCODE   = 6'b001001;
    localparam [5:0] IR_JPROGRAM = 6'b001011;
    localparam [5:0] IR_JSTART   = 6'b001100;
    localparam [5:0] IR_CAPTURE  = 6'b100010;
    localparam [5:0] IR_BYPASS   = 6'b111111;

    // CFG_CTRL fields (docs/bitstream-format.md section 5)
    localparam integer B_CRC_OK = 48, B_CRC_ERR = 49, B_LEN_ERR = 50, B_COMMITTED = 51;
    localparam integer B_GSR = 52, B_GTS = 53, B_GWE = 54, B_DONE = 55;

    reg        tck = 1'b0;
    reg        tms = 1'b1;
    reg        tdi = 1'b0;
    wire       tdo;
    reg  [1:0] sw  = 2'b00;
    reg  [3:0] btn = 4'b0000;
    wire [3:0] led;

    reg          tdo_s = 1'b0;
    integer      errors = 0;
    integer      checks = 0;
    integer      i;
    reg [127:0]  rx;
    reg [5:0]    irc;
    reg [63:0]   st;
    reg [63:0]   prev;
    reg [7:0]    cnt1;

    cfg_test_top #(.IDCODE_VALUE(IDCODE), .USERCODE_VALUE(USERCODE)) dut (
        .tck(tck), .tms(tms), .tdi(tdi), .tdo(tdo),
        .sw(sw), .btn(btn), .led(led)
    );

    wire [W-1:0] cfg = dut.u_mem.cfg;

    // ---------------------------------------------------------------------
    // Probe model (tb_fpga4x4.v, IR widened to 6)
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
        begin
            for (i = 0; i < 5; i = i + 1) tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
        end
    endtask

    task shift_ir(input [5:0] value, output [5:0] cap);
        integer k;
        begin
            tick(1'b1, 1'b0);
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
            tick(1'b0, 1'b0);
            for (k = 0; k < 5; k = k + 1) begin
                tick(1'b0, value[k]);
                cap[k] = tdo_s;
            end
            tick(1'b1, value[5]);
            cap[5] = tdo_s;
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
        end
    endtask

    task shift_dr(input integer n, input [127:0] din, output [127:0] dout);
        integer k;
        begin
            dout = 128'h0;
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
            tick(1'b0, 1'b0);
            for (k = 0; k < n - 1; k = k + 1) begin
                tick(1'b0, din[k]);
                dout[k] = tdo_s;
            end
            tick(1'b1, din[n-1]);
            dout[n-1] = tdo_s;
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
        end
    endtask

    // Shift n bits and stop in Pause-DR, so the caller can look at the design
    // with a full scan in the shift registers but no Update-DR yet.
    task shift_dr_to_pause(input integer n, input [127:0] din);
        integer k;
        begin
            tick(1'b1, 1'b0);                 // Select-DR
            tick(1'b0, 1'b0);                 // Capture-DR
            tick(1'b0, 1'b0);                 // -> Shift-DR
            for (k = 0; k < n - 1; k = k + 1) tick(1'b0, din[k]);
            tick(1'b1, din[n-1]);             // -> Exit1-DR
            tick(1'b0, 1'b0);                 // -> Pause-DR
            tick(1'b0, 1'b0);                 // stay
        end
    endtask

    task pause_to_idle;
        begin
            tick(1'b1, 1'b0);                 // -> Exit2-DR
            tick(1'b1, 1'b0);                 // -> Update-DR
            tick(1'b0, 1'b0);                 // -> Run-Test/Idle
        end
    endtask

    task check(input [511:0] name, input [63:0] got, input [63:0] exp);
        begin
            checks = checks + 1;
            if (got !== exp) begin
                $display("  FAIL  %0s = 0x%0h, expected 0x%0h", name, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    task check_loud(input [511:0] name, input [63:0] got, input [63:0] exp);
        begin
            check(name, got, exp);
            if (got === exp) $display("  PASS  %0s = 0x%0h", name, got);
        end
    endtask

    // ---------------------------------------------------------------------
    // Configuration-plane helpers
    // ---------------------------------------------------------------------
    task read_ctrl(output [63:0] v);
        begin
            shift_ir(IR_CFG_CTRL, irc);
            shift_dr(64, 128'h0, rx);
            v = rx[63:0];
        end
    endtask

    task write_expected(input [31:0] crc);
        begin
            shift_ir(IR_CFG_CTRL, irc);
            shift_dr(64, {64'h0, 8'hC5, 24'h0, crc}, rx);
        end
    endtask

    task load(input [63:0] word, input [31:0] crc);
        begin
            write_expected(crc);
            shift_ir(IR_CHAIN_IN, irc);
            shift_dr(W, {64'h0, word}, rx);
        end
    endtask

    task readback(output [63:0] v);
        begin
            shift_ir(IR_CHAIN_OUT, irc);
            shift_dr(W, 128'h0, rx);
            v = rx[63:0];
        end
    endtask

    // ---------------------------------------------------------------------
    // Vector tasks, called from cfg_vectors.vh
    // ---------------------------------------------------------------------
    task vec_key_guard(input [63:0] word, input [31:0] crc);
        begin
            write_expected(crc);
            read_ctrl(st);                    // shifts zeros: no key, must not overwrite
            read_ctrl(st);
            shift_ir(IR_CHAIN_IN, irc);
            shift_dr(W, {64'h0, word}, rx);
            read_ctrl(st);
            check_loud("key guard: expected CRC survived two keyless CFG_CTRL reads (commit)",
                       {63'b0, st[B_COMMITTED]}, 64'h1);
            check("key guard: cfg", cfg, word);
        end
    endtask

    task vec_good(input [63:0] word, input [31:0] crc);
        reg [63:0] rb;
        begin
            load(word, crc);
            read_ctrl(st);
            check("good: chip CRC == chainbits.py", {32'h0, st[31:0]}, {32'h0, crc});
            check("good: bit count",               {48'h0, st[47:32]}, W);
            check("good: CRC_OK",                  {63'b0, st[B_CRC_OK]}, 64'h1);
            check("good: CRC_ERR clear",           {63'b0, st[B_CRC_ERR]}, 64'h0);
            check("good: LEN_ERR clear",           {63'b0, st[B_LEN_ERR]}, 64'h0);
            check("good: COMMITTED",               {63'b0, st[B_COMMITTED]}, 64'h1);
            check("good: cfg committed",           cfg, word);
            readback(rb);
            check("good: CFG_OUT readback",        rb, word);
            readback(rb);
            check("good: second readback",         rb, word);
            check("good: cfg unchanged by readback", cfg, word);
            $display("  PASS  load + 2x readback  %h  crc %h", word, crc);
        end
    endtask

    task vec_corrupt(input [63:0] bad_word, input [31:0] crc_of_good);
        reg [63:0] rb;
        begin
            prev = cfg;
            load(bad_word, crc_of_good);
            read_ctrl(st);
            check("corrupt: CRC_ERR set",       {63'b0, st[B_CRC_ERR]}, 64'h1);
            check("corrupt: CRC_OK clear",      {63'b0, st[B_CRC_OK]}, 64'h0);
            check("corrupt: LEN_ERR clear",     {63'b0, st[B_LEN_ERR]}, 64'h0);
            check("corrupt: still COMMITTED",   {63'b0, st[B_COMMITTED]}, 64'h1);
            check("corrupt: cfg kept",          cfg, prev);
            readback(rb);
            check("corrupt: readback is previous config", rb, prev);
            shift_ir(IR_BYPASS, irc);
            check("corrupt: IR capture CRC_ERR / INIT_B",
                  {60'h0, irc[5:2]}, {60'h0, 1'b0, 1'b0, 1'b1, 1'b1});
            $display("  PASS  one-bit-corrupted chain rejected, config kept");
        end
    endtask

    // crc63 / crc65 are correct for the bits actually shifted, so the CRC
    // passes and only the length guard can refuse the commit.
    task vec_len(input [63:0] word, input [31:0] crc63, input [31:0] crc65);
        begin
            prev = cfg;
            write_expected(crc63);
            shift_ir(IR_CHAIN_IN, irc);
            shift_dr(W - 1, {64'h0, word}, rx);
            read_ctrl(st);
            check("63-bit scan: CRC matched (isolates the length guard)",
                  {63'b0, st[B_CRC_ERR]}, 64'h0);
            check_loud("63-bit scan with valid CRC: LEN_ERR", {63'b0, st[B_LEN_ERR]}, 64'h1);
            check("63-bit scan: count",        {48'h0, st[47:32]}, W - 1);
            check("63-bit scan: cfg kept",     cfg, prev);

            write_expected(crc65);
            shift_ir(IR_CHAIN_IN, irc);
            shift_dr(W + 1, {63'h0, word, 1'b0}, rx);
            read_ctrl(st);
            check("65-bit scan: CRC matched (isolates the length guard)",
                  {63'b0, st[B_CRC_ERR]}, 64'h0);
            check_loud("65-bit scan with valid CRC: LEN_ERR", {63'b0, st[B_LEN_ERR]}, 64'h1);
            check("65-bit scan: count",        {48'h0, st[47:32]}, W + 1);
            check("65-bit scan: cfg kept",     cfg, prev);
        end
    endtask

    task vec_hold(input [63:0] word, input [31:0] crc);
        reg [3:0] led_before;
        begin
            prev = cfg;
            led_before = led;
            write_expected(crc);
            shift_ir(IR_CHAIN_IN, irc);
            shift_dr_to_pause(W, {64'h0, word});
            check_loud("mid-scan (Pause-DR): cfg unchanged", cfg, prev);
            check("mid-scan: LEDs unchanged", {60'h0, led}, {60'h0, led_before});
            pause_to_idle;
            check_loud("after Update-DR: cfg committed", cfg, word);
        end
    endtask

    // ---------------------------------------------------------------------
    initial begin
        $dumpfile("tb_cfg.vcd");
        $dumpvars(1, tb_cfg);

        $display("");
        $display("=== M2 configuration plane: 6-bit AMD IR, %0d-bit scan chain ===", W);

        goto_reset_then_idle;

        $display("");
        $display("[1] identity, IR capture, BYPASS");
        shift_dr(32, 128'h0, rx);
        check_loud("IDCODE after reset", rx[31:0], IDCODE);
        shift_ir(IR_USERCODE, irc);
        shift_dr(32, 128'h0, rx);
        check_loud("USERCODE", rx[31:0], USERCODE);
        check_loud("IR capture at power-up {DONE,INIT_B,COMMITTED,CRC_ERR,01}",
                   {58'h0, irc}, {58'h0, 6'b010001});
        shift_ir(IR_BYPASS, irc);
        shift_dr(32, 128'hD5A73C91, rx);
        check_loud("BYPASS (delayed one TCK)", rx[31:0], 32'hAB4E7922);

        $display("");
        $display("[2] power-up state");
        read_ctrl(st);
        check_loud("CFG_CTRL version", {56'h0, st[63:56]}, 64'h02);
        check_loud("GSR,GTS,GWE,DONE,COMMITTED = 1,1,0,0,0",
                   {59'h0, st[B_GSR], st[B_GTS], st[B_GWE], st[B_DONE], st[B_COMMITTED]},
                   {59'h0, 5'b11000});
        check_loud("LEDs dark", {60'h0, led}, 64'h0);
        check_loud("cfg all zero", cfg, 64'h0);

        $display("");
        $display("[3] load, readback, CRC and length rejection (vectors from chainbits.py)");
        `include "cfg_vectors.vh"

        $display("");
        $display("[4] JPROGRAM and JSTART");
        shift_ir(IR_JPROGRAM, irc);
        check_loud("JPROGRAM clears cfg", cfg, 64'h0);
        read_ctrl(st);
        check_loud("after JPROGRAM: GSR,GTS,GWE,DONE,COMMITTED = 1,1,0,0,0",
                   {59'h0, st[B_GSR], st[B_GTS], st[B_GWE], st[B_DONE], st[B_COMMITTED]},
                   {59'h0, 5'b11000});
        shift_ir(IR_JSTART, irc);
        for (i = 0; i < 12; i = i + 1) tick(1'b0, 1'b0);
        read_ctrl(st);
        check_loud("JSTART without a commit: DONE stays 0, GSR stays 1",
                   {62'h0, st[B_DONE], st[B_GSR]}, {62'h0, 2'b01});

        load(`STARTUP_WORD, `STARTUP_CRC);
        check("startup word committed", cfg, `STARTUP_WORD);
        check_loud("committed but not started: LEDs dark", {60'h0, led}, 64'h0);
        shift_ir(IR_JSTART, irc);
        tick(1'b0, 1'b0);
        check_loud("JSTART tck 1: GSR released, GTS held",
                   {62'h0, dut.u_ctrl.gsr, dut.u_ctrl.gts}, {62'h0, 2'b01});
        tick(1'b0, 1'b0);
        check_loud("JSTART tck 2: GTS released, GWE still 0",
                   {62'h0, dut.u_ctrl.gts, dut.u_ctrl.gwe}, {62'h0, 2'b00});
        check_loud("GTS released: LD2..0 show cfg[2:0]", {61'h0, led[2:0]}, {61'h0, 3'b101});
        tick(1'b0, 1'b0);
        check_loud("JSTART tck 3: GWE set, DONE still 0",
                   {62'h0, dut.u_ctrl.gwe, dut.u_ctrl.done}, {62'h0, 2'b10});
        tick(1'b0, 1'b0);
        check_loud("JSTART tck 4: DONE, LD3 lit", {62'h0, dut.u_ctrl.done, led[3]}, {62'h0, 2'b11});
        for (i = 0; i < 8; i = i + 1) tick(1'b0, 1'b0);
        shift_ir(IR_BYPASS, irc);
        check_loud("IR capture after startup {DONE,INIT_B,COMMITTED,CRC_ERR,01}",
                   {58'h0, irc}, {58'h0, 6'b111001});

        $display("");
        $display("[5] Test-Logic-Reset keeps configuration and startup");
        goto_reset_then_idle;
        check_loud("cfg after TLR", cfg, `STARTUP_WORD);
        check_loud("DONE after TLR", {63'h0, dut.u_ctrl.done}, 64'h1);
        shift_dr(32, 128'h0, rx);
        check_loud("TLR selected IDCODE", rx[31:0], IDCODE);

        $display("");
        $display("[6] CAPTURE: user state snapshot");
        sw = 2'b10; btn = 4'b0101;
        shift_ir(IR_USER1, irc);
        shift_dr(32, 128'h1, rx);                         // ce = 1: counter runs
        for (i = 0; i < 20; i = i + 1) tick(1'b0, 1'b0);
        shift_ir(IR_CAPTURE, irc);
        shift_dr(16, 128'h0, rx);
        check_loud("CAPTURE SW/BTN fields", {48'h0, rx[15:8]}, {48'h0, 4'b0101, 2'b10, 2'b00});
        cnt1 = rx[7:0];
        check("counter running", {63'h0, (cnt1 != 8'h0)}, 64'h1);
        for (i = 0; i < 20; i = i + 1) tick(1'b0, 1'b0);
        shift_ir(IR_CAPTURE, irc);
        shift_dr(16, 128'h0, rx);
        check_loud("second CAPTURE: counter advanced", {63'h0, (rx[7:0] != cnt1)}, 64'h1);
        $display("        counter %0d -> %0d", cnt1, rx[7:0]);
        check("CAPTURE is read-only: cfg unchanged", cfg, `STARTUP_WORD);

        $display("");
        $display("[7] JPROGRAM from a running design");
        shift_ir(IR_JPROGRAM, irc);
        for (i = 0; i < 4; i = i + 1) tick(1'b0, 1'b0);
        shift_ir(IR_CAPTURE, irc);
        shift_dr(16, 128'h0, rx);
        check_loud("counter held at 0 by GSR", {56'h0, rx[7:0]}, 64'h0);
        check_loud("cfg cleared", cfg, 64'h0);
        check_loud("LEDs dark, DONE off", {60'h0, led}, 64'h0);
        shift_ir(IR_USER1, irc);
        shift_dr(32, 128'h0, rx);

        $display("");
        $display("    %0d checks", checks);
        if (errors == 0) $display("=== ALL TESTS PASSED ===");
        else             $display("=== %0d CHECK(S) FAILED ===", errors);
        $display("");

        if (errors != 0) $fatal(1);
        $finish;
    end

    initial begin
        #2_000_000_000;
        $display("TIMEOUT");
        $fatal(1);
    end

endmodule

`default_nettype wire
