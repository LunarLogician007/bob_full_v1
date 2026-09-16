// -----------------------------------------------------------------------------
// tb_fpga4x4.v - self-checking testbench for the 4x4 fabric (M4)
//
// Everything goes through the JTAG pins and the configuration plane, the way
// the board is driven: JPROGRAM -> expected CRC -> CFG_IN -> status -> JSTART.
// The fabric runs on sysclk with the user clock as an enable (clock_ctrl.v).
//
// hw/tb/vectors.vh (sim/gen_vectors.py) supplies the bitstreams from
// host/bitstream.py, expected outputs from its software model and from
// tools/bob/model.py, and CRCs from tools/bob/chainbits.py.
//
//   sim/run_fabric_sim.sh
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module tb_fpga4x4;

    localparam        HALF     = 50;
    localparam [31:0] IDCODE   = 32'h6BEEF093;
    localparam [31:0] USERCODE = 32'h00000004;
    localparam integer CFG_W   = `BOB_CHAIN_W;

    localparam [5:0] IR_SAMPLE   = 6'b000001;
    localparam [5:0] IR_USER1    = 6'b000010;
    localparam [5:0] IR_CFG_CTRL = 6'b000011;
    localparam [5:0] IR_CFG_OUT  = 6'b000100;
    localparam [5:0] IR_CFG_IN   = 6'b000101;
    localparam [5:0] IR_INTEST   = 6'b000111;
    localparam [5:0] IR_USERCODE = 6'b001000;
    localparam [5:0] IR_IDCODE   = 6'b001001;
    localparam [5:0] IR_JPROGRAM = 6'b001011;
    localparam [5:0] IR_JSTART   = 6'b001100;
    localparam [5:0] IR_CAPTURE  = 6'b100010;
    localparam [5:0] IR_EXTEST   = 6'b100110;
    localparam [5:0] IR_BYPASS   = 6'b111111;

    localparam integer B_CRC_OK = 48, B_CRC_ERR = 49, B_LEN_ERR = 50, B_COMMITTED = 51;
    localparam integer B_GSR = 52, B_GTS = 53, B_GWE = 54, B_DONE = 55;
    localparam [31:0]  MARKER = 32'hA5C35A3C;

    reg        sysclk = 1'b0;
    reg        tck = 1'b0;
    reg        tms = 1'b1;
    reg        tdi = 1'b0;
    wire       tdo;
    reg  [5:0] pad_i = 6'b000000;
    wire [2:0] pad_o;
    wire [3:0] tap_state;
    wire       configured;

    reg                tdo_s = 1'b0;
    integer            errors = 0;
    integer            checks = 0;
    integer            dchecks = 0;
    integer            n;
    integer            k0;
    integer            pulses;
    reg                count_en = 1'b0;
    reg [1023:0]       dname;
    reg [CFG_W-1:0]    cfgw;
    reg [CFG_W-1:0]    cfgrx;
    reg [31:0]         cfgcrc;
    reg [127:0]        rx;
    reg [127:0]        ux;
    reg [5:0]          irc;
    reg [63:0]         st;
    reg [3:0]          cnt_state [0:15];
    reg [2:0]          cnt_pad   [0:15];
    reg [3:0]          cstate, cstate0, cexp;

    // 250 MHz in simulation; the board's is 125 MHz. The free-running divider
    // is shortened to 2**3 cycles here (DIV_MIN_SHIFT), 2**8 on the board.
    // clk_on is dropped only while chain bits are being shifted: the fabric has
    // nothing to do then, and a 250 MHz clock across 3064 TCK periods is most
    // of the simulation time.
    reg clk_on = 1'b1;
    always #2 sysclk = clk_on ? ~sysclk : 1'b0;

    always @(posedge sysclk)
        if (count_en && dut.u_clk.gce) pulses = pulses + 1;

    fpga4x4 #(.IDCODE_VALUE(IDCODE), .USERCODE_VALUE(USERCODE), .DIV_MIN_SHIFT(3)) dut (
        .sysclk(sysclk),
        .tck(tck), .tms(tms), .tdi(tdi), .tdo(tdo),
        .pad_i(pad_i), .pad_o(pad_o),
        .tap_state(tap_state), .configured(configured)
    );

    wire [CFG_W-1:0] cfg = dut.chain_cfg;
    wire [3:0] counter = {dut.clb_o[12], dut.clb_o[8], dut.clb_o[4], dut.clb_o[0]};

    // bitstreams, CRCs, run_designs, check_showcase, run_ce_sr, init_cnt_seq
    `include "vectors.vh"

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

    task idle(input integer count);
        integer k;
        begin
            for (k = 0; k < count; k = k + 1) tick(1'b0, 1'b0);
        end
    endtask

    task goto_reset_then_idle;
        integer k;
        begin
            for (k = 0; k < 5; k = k + 1) tick(1'b1, 1'b0);
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

    task shift_dr(input integer len, input [127:0] din, output [127:0] dout);
        integer k;
        begin
            dout = 128'h0;
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
            tick(1'b0, 1'b0);
            for (k = 0; k < len - 1; k = k + 1) begin
                tick(1'b0, din[k]);
                dout[k] = tdo_s;
            end
            tick(1'b1, din[len-1]);
            dout[len-1] = tdo_s;
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
        end
    endtask

    // The config chain is far too wide for the 128-bit helper above.
    task shift_chain(input [CFG_W-1:0] din);
        integer k;
        begin
            cfgrx = {CFG_W{1'b0}};
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
            tick(1'b0, 1'b0);
            clk_on = 1'b0;
            for (k = 0; k < CFG_W - 1; k = k + 1) begin
                tick(1'b0, din[k]);
                cfgrx[k] = tdo_s;
            end
            clk_on = 1'b1;
            tick(1'b1, din[CFG_W-1]);
            cfgrx[CFG_W-1] = tdo_s;
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
        end
    endtask

    // Shift CFG_W + 32 bits: a 32-bit marker first, then zeros. Returns the
    // 32 bits that come out after the first CFG_W, which is the marker iff
    // the chain is exactly CFG_W long.
    task shift_marker(output [31:0] tail);
        integer k;
        begin
            tail = 32'h0;
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
            tick(1'b0, 1'b0);
            clk_on = 1'b0;
            for (k = 0; k < CFG_W + 31; k = k + 1) begin
                tick(1'b0, (k < 32) ? MARKER[k] : 1'b0);
                if (k >= CFG_W) tail[k - CFG_W] = tdo_s;
            end
            clk_on = 1'b1;
            tick(1'b1, 1'b0);
            tail[31] = tdo_s;
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
        end
    endtask

    task check(input [511:0] name, input [63:0] got, input [63:0] exp);
        begin
            checks = checks + 1;
            if (got === exp)
                $display("  PASS  %0s = 0x%0h", name, got);
            else begin
                $display("  FAIL  %0s = 0x%0h, expected 0x%0h", name, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    // ---------------------------------------------------------------------
    // Configuration plane (docs/bitstream-format.md section 8)
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

    task jstart;
        begin
            shift_ir(IR_JSTART, irc);
            idle(12);
        end
    endtask

    task write_user1(input [31:0] v);
        begin
            shift_ir(IR_USER1, irc);
            shift_dr(32, {96'h0, v}, rx);
        end
    endtask

    // JPROGRAM, CRC, CFG_IN, check commit - but no startup
    task commit_config;
        begin
            shift_ir(IR_JPROGRAM, irc);
            write_expected(cfgcrc);
            shift_ir(IR_CFG_IN, irc);
            shift_chain(cfgw);
            read_ctrl(st);
            checks = checks + 1;
            if (!st[B_COMMITTED] || !st[B_CRC_OK] || st[47:32] != CFG_W) begin
                errors = errors + 1;
                $display("  FAIL  %0s: not committed (crc_err=%b len_err=%b count=%0d)",
                         dname, st[B_CRC_ERR], st[B_LEN_ERR], st[47:32]);
            end
        end
    endtask

    // Vector harness, used by the generated file
    task load_config;
        begin
            commit_config;
            jstart;
            shift_ir(IR_BYPASS, irc);      // boundary transparent: pads drive the fabric
            dchecks = 0;
        end
    endtask

    task check_vec(input [5:0] pi, input [2:0] exp);
        begin
            pad_i = pi;
            #20;                           // let the mesh settle
            checks = checks + 1;
            if (pad_o !== exp) begin
                errors = errors + 1;
                $display("  FAIL  %0s", dname);
                $display("        pad_i=%b  pad_o=%b  expected %b", pi, pad_o, exp);
            end else begin
                dchecks = dchecks + 1;
            end
        end
    endtask

    task finish_design;
        begin
            $display("  PASS  %0s   (%0d vectors)", dname, dchecks);
        end
    endtask

    // M4: apply pads, let 4 TCK edges (= 4 fabric clocks with USER1 ce) pass
    task ce_sr_step(input [5:0] pi, input [2:0] exp);
        begin
            pad_i = pi;
            idle(4);
            checks = checks + 1;
            if (pad_o !== exp) begin
                errors = errors + 1;
                $display("  FAIL  ce_sr: SW1..0=%b pad_o=%b model %b", pi[1:0], pad_o, exp);
            end else
                $display("  PASS  ce_sr: SW1(SR)=%b SW0(CE)=%b -> q=%b (model %b)", pi[1], pi[0], pad_o[0], exp[0]);
        end
    endtask

    // ---------------------------------------------------------------------
    reg [31:0] tail;

    initial begin
        // Opt-in (sim/run_fabric_sim.sh --wave): with a 250 MHz sysclk the VCD
        // grows by gigabytes and dominates the run time.
        if ($test$plusargs("wave")) begin
            $dumpfile("tb_fpga4x4.vcd");
            $dumpvars(1, tb_fpga4x4);
        end

        $display("");
        $display("=== 4x4 fabric: config plane, user clock, routed CE/SR, LUT K=%0d (M4) ===", `BOB_LUT_K);
        $display("    config chain: %0d bits (ctrl %0d + 16 tiles x %0d)", CFG_W, `BOB_CTRL_W, `BOB_TILE_CFG_W);

        goto_reset_then_idle;

        $display("");
        $display("[1] identity, IR capture and BYPASS through the 6-bit TAP");
        shift_dr(32, 128'h0, rx);
        check("IDCODE", rx[31:0], IDCODE);
        shift_ir(IR_USERCODE, irc);
        check("IR capture at power-up {DONE,INIT_B,COMMITTED,CRC_ERR,01}", {58'h0, irc}, 64'h11);
        shift_dr(32, 128'h0, rx);
        check("USERCODE", rx[31:0], USERCODE);
        shift_ir(IR_BYPASS, irc);
        shift_dr(32, 128'hD5A73C91, rx);
        check("BYPASS (delayed one TCK)", rx[31:0], 32'hAB4E7922);

        $display("");
        $display("[2] the %0d-bit chain: CRC-checked commit, readback, length, GTS", CFG_W);
        check("power-up: DONE (LD3) off", {63'h0, configured}, 64'h0);
        write_expected(`RT_CRC);
        shift_ir(IR_CFG_IN, irc);
        shift_chain(`RT_WORD);
        read_ctrl(st);
        check("random chain committed", {63'h0, st[B_COMMITTED]}, 64'h1);
        check("chip CRC == chainbits.py", {32'h0, st[31:0]}, {32'h0, `RT_CRC});
        check("bit count", {48'h0, st[47:32]}, CFG_W);
        check("shadow bus == chain", {63'h0, (cfg === `RT_WORD)}, 64'h1);
        shift_ir(IR_CFG_OUT, irc);
        shift_chain({CFG_W{1'b0}});
        check("CFG_OUT readback == chain", {63'h0, (cfgrx === `RT_WORD)}, 64'h1);
        shift_ir(IR_CFG_OUT, irc);
        shift_chain({CFG_W{1'b1}});
        check("second readback unchanged (CFG_OUT never commits)",
              {63'h0, (cfgrx === `RT_WORD) && (cfg === `RT_WORD)}, 64'h1);
        shift_ir(IR_CFG_OUT, irc);
        shift_marker(tail);
        check("marker emerges after exactly the chain width", {32'h0, tail}, {32'h0, MARKER});
        check("GTS: committed but not started, pads forced 0", {61'h0, pad_o}, 64'h0);
        check("GSR/GTS still asserted",
              {62'h0, dut.u_ctrl.gsr, dut.u_ctrl.gts}, {62'h0, 2'b11});
        check("committed but not started: DONE (LD3) still off",
              {62'h0, dut.u_ctrl.committed, configured}, {62'h0, 2'b10});

        $display("");
        $display("[3] designs from host/bitstream.py, each loaded with CRC + JSTART");
        run_designs;

        $display("");
        $display("[4] a corrupted chain is refused and the running design keeps working");
        check("showcase is running", {63'h0, (cfg === `SHOW_WORD)}, 64'h1);
        write_expected(`BAD_CRC);
        shift_ir(IR_CFG_IN, irc);
        shift_chain(`BAD_WORD);
        read_ctrl(st);
        check("corrupt chain: CRC_ERR", {63'h0, st[B_CRC_ERR]}, 64'h1);
        check("corrupt chain: config kept", {63'h0, (cfg === `SHOW_WORD)}, 64'h1);
        check("corrupt chain: DONE kept", {63'h0, configured}, 64'h1);
        dname = "showcase still correct after the rejected chain";
        dchecks = 0;
        check_showcase;
        finish_design;

        $display("");
        $display("[5] the boundary still works on the fabric build");
        shift_ir(IR_EXTEST, irc);
        shift_dr(9, 9'b000000_101, rx);
        check("EXTEST drives pad_o", {61'b0, pad_o}, 64'h5);
        shift_dr(9, 9'b000000_010, rx);
        check("EXTEST drives pad_o again", {61'b0, pad_o}, 64'h2);
        pad_i = 6'b101101;
        shift_ir(IR_SAMPLE, irc);
        shift_dr(9, 128'h0, rx);
        check("SAMPLE observes pad_i", {58'b0, rx[8:3]}, 64'h2D);

        $display("");
        $display("[6] USER1 status and CAPTURE both show the 16 CLB outputs");
        cfgw = `SHOW_WORD; cfgcrc = `SHOW_CRC; dname = "showcase";
        load_config;
        pad_i = 6'b000011;                 // SW1=SW0=1: AND=1 at t0, OR=1 at t5, XOR=0 at t10
        #20;
        shift_ir(IR_USER1, irc);
        shift_dr(32, 128'h0, ux);
        shift_ir(IR_CAPTURE, irc);
        shift_dr(16, 128'h0, rx);
        check("CAPTURE == USER1 status [19:4]", {48'h0, rx[15:0]}, {48'h0, ux[19:4]});
        check("CAPTURE t0 AND, t5 OR, t10 XOR", {61'h0, rx[10], rx[5], rx[0]}, {61'h0, 3'b011});

        $display("");
        $display("[7] GSR holds flip-flops at INIT until JSTART; GWE lets them clock");
        cfgw = `GSR_WORD; cfgcrc = `GSR_CRC; dname = "gsr probe";
        pad_i = 6'b000000;
        commit_config;
        check("GSR probe committed, not started: DONE (LD3) off", {63'h0, configured}, 64'h0);
        write_user1(32'h1);                // ce: one fabric clock per TCK edge
        idle(8);
        shift_ir(IR_CAPTURE, irc);
        shift_dr(16, 128'h0, rx);
        check("under GSR, tile(0,0) q = INIT (1)", {63'h0, rx[0]}, 64'h1);
        check("GTS: pad_o[0] forced 0 even though q = 1", {63'h0, pad_o[0]}, 64'h0);
        // Step startup one TCK at a time. GSR drops on edge 1, GWE rises on
        // edge 3. The fabric clock from edge 2 sees GSR=0 with GWE=0 and must
        // leave q frozen at INIT; the one from edge 3 already sees GWE=1
        // (GWE synchronises faster than the TCK-edge enable).
        shift_ir(IR_JSTART, irc);
        tick(1'b0, 1'b0);
        check("JSTART edge 1: GSR released, GWE still 0",
              {62'h0, dut.u_ctrl.gsr, dut.u_ctrl.gwe}, {62'h0, 2'b00});
        tick(1'b0, 1'b0);
        check("edge 2 clocked with GSR=0, GWE=0: q frozen at INIT (1)", {63'h0, dut.clb_o[0]}, 64'h1);
        tick(1'b0, 1'b0);
        check("edge 3 sets GWE and clocks: q = D (0)", {63'h0, dut.clb_o[0]}, 64'h0);
        tick(1'b0, 1'b0);
        check("DONE (LD3) on after edge 4", {63'h0, configured}, 64'h1);
        idle(8);
        shift_ir(IR_CAPTURE, irc);
        shift_dr(16, 128'h0, rx);
        check("after JSTART, CAPTURE shows q = D (0)", {63'h0, rx[0]}, 64'h0);
        write_user1(32'h0);

        $display("");
        $display("[8] Test-Logic-Reset keeps configuration; JPROGRAM clears it");
        cfgw = `SHOW_WORD; cfgcrc = `SHOW_CRC;
        load_config;
        goto_reset_then_idle;
        check("TLR: config kept", {63'h0, (cfg === `SHOW_WORD)}, 64'h1);
        check("TLR: DONE kept", {63'h0, configured}, 64'h1);
        shift_dr(32, 128'h0, rx);
        check("TLR selected IDCODE", rx[31:0], IDCODE);
        dname = "showcase after Test-Logic-Reset";
        dchecks = 0;
        check_showcase;
        finish_design;
        shift_ir(IR_JPROGRAM, irc);
        pad_i = 6'b000011;
        #20;
        check("JPROGRAM: config cleared", {63'h0, (cfg === {CFG_W{1'b0}})}, 64'h1);
        check("JPROGRAM: pads dark", {61'h0, pad_o}, 64'h0);
        check("JPROGRAM: DONE off", {63'h0, configured}, 64'h0);

        $display("");
        $display("[9] routed CE and SR (UG474 FDRE): tile(0,0) D=1, CE<-SW0, SR<-SW1");
        cfgw = `CE_SR_WORD; cfgcrc = `CE_SR_CRC; dname = "ce_sr";
        pad_i = 6'b000000;
        load_config;
        write_user1(32'h1);
        run_ce_sr;
        write_user1(32'h0);

        $display("");
        $display("[10] 4-bit counter on the carry chain, JTAG-stepped: one count per TCK edge");
        cfgw = `CNTJ_WORD; cfgcrc = `CNTJ_CRC; dname = "counter (jtag)";
        pad_i = 6'b000000;
        init_cnt_seq;
        load_config;
        write_user1(32'h5);                // ce + cin
        cstate = counter;
        k0 = -1;
        for (n = 0; n < 16; n = n + 1) if (cnt_state[n] === cstate) k0 = n;
        check("counter state is one the model produces", {63'h0, (k0 >= 0)}, 64'h1);
        dchecks = 0;
        for (n = 1; n <= 20; n = n + 1) begin
            tick(1'b0, 1'b0);
            checks = checks + 1;
            if (counter !== cnt_state[(k0 + n) % 16] || pad_o !== cnt_pad[(k0 + n) % 16]) begin
                errors = errors + 1;
                $display("  FAIL  TCK edge %0d: counter=%b pad_o=%b, model %b / %b", n, counter, pad_o,
                         cnt_state[(k0 + n) % 16], cnt_pad[(k0 + n) % 16]);
            end else
                dchecks = dchecks + 1;
        end
        $display("  PASS  counter matches model.py on %0d consecutive TCK edges", dchecks);
        write_user1(32'h4);                // cin only: USER1 ce off
        cstate0 = counter;
        idle(10);
        check("USER1 ce off: TCK edges no longer clock the fabric", {60'h0, counter}, {60'h0, cstate0});

        $display("");
        $display("[11] free-running user clock: the counter runs with TCK stopped");
        cfgw = `CNTR_WORD; cfgcrc = `CNTR_CRC; dname = "counter (run, div 0)";
        load_config;                       // USER1 still ce + cin
        @(negedge sysclk);
        cstate0 = counter;
        pulses = 0;
        count_en = 1'b1;
        #3200;
        count_en = 1'b0;
        cstate = counter;
        check("gce pulses in 3200 ns (one per 2**3 cycles of 4 ns = 100)",
              {63'h0, (pulses >= 99 && pulses <= 101)}, 64'h1);
        $display("        pulses = %0d", pulses);
        cexp = (cstate0 + pulses) % 16;
        check("counter advanced by exactly the pulse count", {60'h0, cstate}, {60'h0, cexp});
        write_user1(32'h0);

        $display("");
        $display("[12] reset restores IDCODE");
        goto_reset_then_idle;
        shift_dr(32, 128'h0, rx);
        check("IDCODE after re-reset", rx[31:0], IDCODE);

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
