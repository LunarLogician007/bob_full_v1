// -----------------------------------------------------------------------------
// tb_bob.v - self-checking testbench for the complete bob FPGA (M7)
//
// Everything goes through the JTAG pins and the configuration plane, the way
// the board is driven: JPROGRAM -> expected CRC -> CFG_IN -> status -> JSTART.
// The fabric is hw/src/generated/bob_fabric.v, generated from VPR's routing-
// resource graph; it runs on sysclk with the user clock as an enable.
//
// hw/tb/vectors.vh (sim/gen_vectors.py) supplies bitstreams routed by
// host/bitstream.py, expected values from tools/bob/model.py, and CRCs from
// tools/bob/chainbits.py. Sections [1]-[19] are tb_fpga4x4.v's (M3-M6) on the
// new fabric; [20]-[23] are M7's.
//
//   sim/run_fabric_sim.sh
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module tb_bob;

    localparam        HALF     = 50;
    localparam [31:0] IDCODE   = 32'hABEEF093;
    localparam [31:0] USERCODE = 32'h00000007;
    localparam integer CFG_W   = `BOB_CHAIN_W;
    localparam integer NPAD    = `BOB_NPAD;
    localparam integer NCLB    = `BOB_NCLB;
    localparam integer BSR_W   = `BOB_BSR_W;

    localparam [5:0] IR_SAMPLE   = 6'b000001;
    localparam [5:0] IR_USER1    = 6'b000010;
    localparam [5:0] IR_CFG_CTRL = 6'b000011;
    localparam [5:0] IR_CHAIN_OUT = 6'b110100;   // M13: the chain (private); CFG_OUT is the packet port
    localparam [5:0] IR_CHAIN_IN  = 6'b110101;   // M13: the chain (private); CFG_IN is the packet port
    localparam [5:0] IR_INTEST   = 6'b000111;
    localparam [5:0] IR_USERCODE = 6'b001000;
    localparam [5:0] IR_IDCODE   = 6'b001001;
    localparam [5:0] IR_JPROGRAM = 6'b001011;
    localparam [5:0] IR_JSTART   = 6'b001100;
    localparam [5:0] IR_CAPTURE  = 6'b100010;
    localparam [5:0] IR_BRAM     = 6'b100011;
    localparam [5:0] IR_DSP      = 6'b101000;
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
    wire [3:0] tap_state;
    wire       configured;

    // Board view: pad_i = {BTN3..0, SW1, SW0}, pad_o = LD2..0, as every host tool
    // numbers them. They sit on fabric pads BOB_PAD_*; the rest read 0.
    reg  [5:0]      pad_i = 6'b000000;
    wire [NPAD-1:0] pads_i;
    wire [NPAD-1:0] pads_o;
    wire [2:0]      pad_o = {pads_o[`BOB_PAD_LD2], pads_o[`BOB_PAD_LD1], pads_o[`BOB_PAD_LD0]};

    genvar g;
    generate
        for (g = 0; g < NPAD; g = g + 1) begin : g_pad
            assign pads_i[g] = (g == `BOB_PAD_SW0)  ? pad_i[0] :
                               (g == `BOB_PAD_SW1)  ? pad_i[1] :
                               (g == `BOB_PAD_BTN0) ? pad_i[2] :
                               (g == `BOB_PAD_BTN1) ? pad_i[3] :
                               (g == `BOB_PAD_BTN2) ? pad_i[4] :
                               (g == `BOB_PAD_BTN3) ? pad_i[5] : 1'b0;
        end
    endgenerate

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
    reg [31:0]         c8, c8_0;
    reg [95:0]         bcap;
    integer            bchecks;
    reg [255:0]        dcap;
    integer            dchecks6;
    integer            acc_pulses;
    reg [47:0]         acc_p;

    // M6 accumulator: count user-clock enables while the drive word says A=1, B=1
    always @(posedge sysclk)
        if (dut.u_dsp_jtag.drive[0] && dut.u_dsp_jtag.drive[25] && dut.u_clk.gce)
            acc_pulses = acc_pulses + 1;

    // 250 MHz in simulation; the board's is 125 MHz. The free-running divider
    // is shortened to 2**3 cycles here (DIV_MIN_SHIFT), 2**9 on the board.
    // clk_on is dropped only while chain bits are being shifted.
    reg clk_on = 1'b1;
    always #2 sysclk = clk_on ? ~sysclk : 1'b0;

    always @(posedge sysclk)
        if (count_en && dut.u_clk.gce) pulses = pulses + 1;

    // GAP_SHIFT follows the shortened divider here: these are two knobs now
    // (bob_fpga.v), and a 3-cycle divider under the board's 512-cycle gap would
    // never pulse twice. The board's own value is simulated by tb_clock_gap.
    bob_fpga #(.IDCODE_VALUE(IDCODE), .USERCODE_VALUE(USERCODE),
               .DIV_MIN_SHIFT(3), .GCE_MIN_GAP_SHIFT(3)) dut (
        .sysclk(sysclk),
        .tck(tck), .tms(tms), .tdi(tdi), .tdo(tdo),
        .pad_i(pads_i), .pad_o(pads_o),
        .tap_state(tap_state), .configured(configured)
    );

    wire [CFG_W-1:0] cfg = dut.chain_cfg;

    `include "vectors.vh"

    wire [3:0] counter  = `CNT_Q;
    wire [`CNT8_BITS-1:0] counter8 = `CNT8_Q;

    // board vector -> boundary scan word: input cells sit at NPAD + pad
    function [127:0] bsr_in(input [5:0] v);
        begin
            bsr_in = 128'h0;
            bsr_in[NPAD + `BOB_PAD_SW0]  = v[0];
            bsr_in[NPAD + `BOB_PAD_SW1]  = v[1];
            bsr_in[NPAD + `BOB_PAD_BTN0] = v[2];
            bsr_in[NPAD + `BOB_PAD_BTN1] = v[3];
            bsr_in[NPAD + `BOB_PAD_BTN2] = v[4];
            bsr_in[NPAD + `BOB_PAD_BTN3] = v[5];
        end
    endfunction

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

    task shift_marker(output [31:0] tail);
        integer k;
        begin
            tail = 32'h0;
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
            tick(1'b0, 1'b0);
            clk_on = 1'b0;
            for (k = 0; k < CFG_W + 31; k = k + 1) begin
                tick(1'b0, MARKER[k % 32]);      // M12b: repeated; CHAIN_OUT is an FB-bit delay after the last frame
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

    task commit_config;
        begin
            shift_ir(IR_JPROGRAM, irc);
            write_expected(cfgcrc);
            shift_ir(IR_CHAIN_IN, irc);
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
            #20;
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

    // hwtest's ce-sr check: INTEST scan 1 applies the vector (autostep clock),
    // scan 2 captures the result (and clocks again). LD0 is output cell PAD_LD0.
    task intest_step(input [5:0] v, input exp_q);
        begin
            shift_dr(BSR_W, bsr_in(v), rx);
            shift_dr(BSR_W, bsr_in(v), rx);
            checks = checks + 1;
            if (rx[`BOB_PAD_LD0] !== exp_q) begin
                errors = errors + 1;
                $display("  FAIL  ce_sr via INTEST: vector SW1..0=%b q=%b model %b (real SW=%b)",
                         v[1:0], rx[`BOB_PAD_LD0], exp_q, pad_i[1:0]);
            end else
                $display("  PASS  ce_sr via INTEST autostep: vector SW1..0=%b -> q=%b, real SW1..0=%b ignored",
                         v[1:0], rx[`BOB_PAD_LD0], pad_i[1:0]);
        end
    endtask

    // ---------------------------------------------------------------------
    // BRAM over USER4
    // ---------------------------------------------------------------------
    task bram_dr(input [3:0] cmd, input [63:0] payload, output [95:0] cap);
        begin
            shift_ir(IR_BRAM, irc);
            shift_dr(96, {32'h0, cmd, 28'h0, payload}, rx);
            cap = rx[95:0];
        end
    endtask

    task bram_poke(input [9:0] addr, input [17:0] word);
        begin
            bram_dr(4'h1, {54'h0, addr}, bcap);
            bram_dr(4'h2, {46'h0, word}, bcap);
        end
    endtask

    task bram_peek(input [9:0] addr, output [17:0] word);
        begin
            bram_dr(4'h1, {54'h0, addr}, bcap);
            bram_dr(4'h3, 64'h0, bcap);
            bram_dr(4'h0, 64'h0, bcap);
            word = bcap[17:0];
        end
    endtask

    task step_once;
        begin
            write_user1(32'h8);
            write_user1(32'h0);
        end
    endtask

    task bram_op(input [63:0] drv, input [17:0] eda, input [17:0] edb);
        begin
            bram_dr(4'h4, drv, bcap);
            step_once;
            bram_dr(4'h0, 64'h0, bcap);
            checks = checks + 1;
            if (bcap[45:28] !== eda || bcap[63:46] !== edb) begin
                errors = errors + 1;
                $display("  FAIL  %0s: drive %h -> do_a %h (model %h)  do_b %h (model %h)",
                         dname, drv, bcap[45:28], eda, bcap[63:46], edb);
            end else
                bchecks = bchecks + 1;
        end
    endtask

    // ---------------------------------------------------------------------
    // DSP over the private DSP instruction (256-bit register)
    // ---------------------------------------------------------------------
    task dsp_dr(input [3:0] cmd, input [247:0] payload, output [255:0] cap);
        integer k;
        begin
            shift_ir(IR_DSP, irc);
            cap = 256'h0;
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
            tick(1'b0, 1'b0);
            for (k = 0; k < 255; k = k + 1) begin
                tick(1'b0, (k < 248) ? payload[k] : ((k >= 252) ? cmd[k - 252] : 1'b0));
                cap[k] = tdo_s;
            end
            tick(1'b1, cmd[3]);
            cap[255] = tdo_s;
            tick(1'b1, 1'b0);
            tick(1'b0, 1'b0);
        end
    endtask

    task dsp_op(input [247:0] drv, input [47:0] ep0, input [47:0] ep1);
        begin
            dsp_dr(4'h4, drv, dcap);
            step_once;
            dsp_dr(4'h0, 248'h0, dcap);
            checks = checks + 1;
            if (dcap[47:0] !== ep0 || dcap[95:48] !== ep1) begin
                errors = errors + 1;
                $display("  FAIL  %0s: P0 %h (model %h)  P1 %h (model %h)", dname, dcap[47:0], ep0, dcap[95:48], ep1);
            end else
                dchecks6 = dchecks6 + 1;
        end
    endtask

    task mult_vec(input [5:0] pi, input [2:0] exp);
        begin
            pad_i = pi;
            #20;
            checks = checks + 1;
            if (pad_o !== exp) begin
                errors = errors + 1;
                $display("  FAIL  DSP multiplier: SW1..0=%b pad_o=%b model %b", pi[1:0], pad_o, exp);
            end else
                $display("  PASS  DSP multiplier: {SW1,SW0}=%0d x 3 -> LD2..0=%b (model)", pi[1:0], pad_o);
        end
    endtask

    task rom_vec(input [5:0] pi, input [2:0] exp);
        begin
            pad_i = pi;
            #200;
            checks = checks + 1;
            if (pad_o !== exp) begin
                errors = errors + 1;
                $display("  FAIL  BRAM ROM: SW1..0=%b pad_o=%b model %b", pi[1:0], pad_o, exp);
            end else
                $display("  PASS  BRAM ROM: SW1..0=%b -> LD2..0=%b (model)", pi[1:0], pad_o);
        end
    endtask

    // ---------------------------------------------------------------------
    // M7
    // ---------------------------------------------------------------------
    task pipe_vec(input [5:0] pi, input [2:0] exp);
        begin
            pad_i = pi;
            #400;                          // FF, BRAM read and PREG: several user clocks
            checks = checks + 1;
            if (pad_o !== exp) begin
                errors = errors + 1;
                $display("  FAIL  pipeline: SW1..0=%b LD2..0=%b model %b", pi[1:0], pad_o, exp);
            end else
                $display("  PASS  pipeline: SW1..0=%b -> FF -> bram%0d -> dsp0 (x3, PREG) -> LD2..0=%b (model)",
                         pi[1:0], `PIPE_BRAM, pad_o);
        end
    endtask

    // one clock, then every CLB output and the LEDs against the model
    task rnd_step(input [5:0] pi, input [NCLB-1:0] eclb, input [2:0] epo);
        begin
            pad_i = pi;
            #20;
            step_once;
            #20;
            checks = checks + 1;
            if (dut.clb_o !== eclb || pad_o !== epo) begin
                errors = errors + 1;
                $display("  FAIL  %0s: pad_i=%b  clb_o=%h (model %h)  LD2..0=%b (model %b)",
                         dname, pi, dut.clb_o, eclb, pad_o, epo);
            end else
                dchecks = dchecks + 1;
        end
    endtask

    // ---------------------------------------------------------------------
    reg [31:0] tail;
    reg [17:0] bword;

    initial begin
        if ($test$plusargs("wave")) begin
            $dumpfile("tb_bob.vcd");
            $dumpvars(1, tb_bob);
        end

        $display("");
        $display("=== bob (M7): %0dx%0d grid, W=%0d, %0d CLBs (LUT%0d), %0d BRAMs, %0d DSPs, %0d pads ===",
                 `BOB_GRID_W, `BOB_GRID_H, `BOB_CHAN_W, NCLB, `BOB_LUT_K, `BOB_NBRAM, `BOB_NDSP, NPAD);
        $display("    config chain: %0d bits", CFG_W);

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
        shift_ir(IR_CHAIN_IN, irc);
        shift_chain(`RT_WORD);
        read_ctrl(st);
        check("random chain committed", {63'h0, st[B_COMMITTED]}, 64'h1);
        check("chip CRC == chainbits.py", {32'h0, st[31:0]}, {32'h0, `RT_CRC});
        check("bit count", {48'h0, st[47:32]}, CFG_W);
        check("shadow bus == chain", {63'h0, (cfg === `RT_WORD)}, 64'h1);
        shift_ir(IR_CHAIN_OUT, irc);
        shift_chain({CFG_W{1'b0}});
        check("CFG_OUT readback == chain", {63'h0, (cfgrx === `RT_WORD)}, 64'h1);
        shift_ir(IR_CHAIN_OUT, irc);
        shift_chain({CFG_W{1'b1}});
        check("second readback unchanged (CFG_OUT never commits)",
              {63'h0, (cfgrx === `RT_WORD) && (cfg === `RT_WORD)}, 64'h1);
        shift_ir(IR_CHAIN_OUT, irc);
        shift_marker(tail);
        check("repeated marker emerges from exactly the chain width on", {32'h0, tail}, {32'h0, MARKER});
        check("GTS: committed but not started, every pad forced 0", {63'h0, (pads_o === {NPAD{1'b0}})}, 64'h1);
        check("GSR/GTS still asserted",
              {62'h0, dut.u_ctrl.gsr, dut.u_ctrl.gts}, {62'h0, 2'b11});
        check("committed but not started: DONE (LD3) still off",
              {62'h0, dut.u_ctrl.committed, configured}, {62'h0, 2'b10});

        $display("");
        $display("[3] designs routed by host/bitstream.py, each loaded with CRC + JSTART");
        run_designs;

        $display("");
        $display("[4] a corrupted chain is refused and the running design keeps working");
        cfgw = `SHOW_WORD; cfgcrc = `SHOW_CRC; dname = "showcase";
        load_config;
        check("showcase is running", {63'h0, (cfg === `SHOW_WORD)}, 64'h1);
        write_expected(`BAD_CRC);
        shift_ir(IR_CHAIN_IN, irc);
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
        $display("[5] the boundary: %0d cells, output cells 0..%0d, input cells %0d..%0d", BSR_W, NPAD-1, NPAD, BSR_W-1);
        shift_ir(IR_EXTEST, irc);
        shift_dr(BSR_W, (128'h1 << `BOB_PAD_LD0) | (128'h1 << `BOB_PAD_LD2), rx);
        check("EXTEST drives LD2..0", {61'b0, pad_o}, 64'h5);
        shift_dr(BSR_W, 128'h1 << `BOB_PAD_LD1, rx);
        check("EXTEST drives LD2..0 again", {61'b0, pad_o}, 64'h2);
        check("EXTEST: only the addressed pads", {63'h0, (pads_o === ({{(NPAD-1){1'b0}}, 1'b1} << `BOB_PAD_LD1))}, 64'h1);
        pad_i = 6'b101101;
        shift_ir(IR_SAMPLE, irc);
        shift_dr(BSR_W, 128'h0, rx);
        check("SAMPLE observes the board inputs on their pads",
              {58'b0, rx[NPAD + `BOB_PAD_BTN3], rx[NPAD + `BOB_PAD_BTN2], rx[NPAD + `BOB_PAD_BTN1],
               rx[NPAD + `BOB_PAD_BTN0], rx[NPAD + `BOB_PAD_SW1], rx[NPAD + `BOB_PAD_SW0]}, 64'h2D);

        $display("");
        $display("[6] USER1 status and CAPTURE: every CLB output");
        cfgw = `SHOW_WORD; cfgcrc = `SHOW_CRC; dname = "showcase";
        load_config;
        pad_i = 6'b000011;
        #20;
        shift_ir(IR_USER1, irc);
        shift_dr(32, 128'h0, ux);
        shift_ir(IR_CAPTURE, irc);
        shift_dr(NCLB, 128'h0, rx);
        check("CAPTURE[15:0] == USER1 status [19:4]", {48'h0, rx[15:0]}, {48'h0, ux[19:4]});
        check("CAPTURE == model.py (all CLBs, SW1=SW0=1)", {63'h0, (rx[NCLB-1:0] === `SHOW_CAP_11)}, 64'h1);

        $display("");
        $display("[7] GSR holds flip-flops at INIT until JSTART; GWE lets them clock");
        cfgw = `GSR_WORD; cfgcrc = `GSR_CRC; dname = "gsr probe";
        pad_i = 6'b000000;
        commit_config;
        check("GSR probe committed, not started: DONE (LD3) off", {63'h0, configured}, 64'h0);
        write_user1(32'h1);
        idle(8);
        shift_ir(IR_CAPTURE, irc);
        shift_dr(NCLB, 128'h0, rx);
        check("under GSR, clb(1,1) q = INIT (1)", {63'h0, rx[0]}, 64'h1);
        check("GTS: LD0 forced 0 even though q = 1", {63'h0, pad_o[0]}, 64'h0);
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
        shift_dr(NCLB, 128'h0, rx);
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
        check("JPROGRAM: pads dark", {63'h0, (pads_o === {NPAD{1'b0}})}, 64'h1);
        check("JPROGRAM: DONE off", {63'h0, configured}, 64'h0);

        $display("");
        $display("[9] routed CE and SR (UG474 FDRE): clb(1,1) D=1, CE<-SW0, SR<-SW1");
        cfgw = `CE_SR_WORD; cfgcrc = `CE_SR_CRC; dname = "ce_sr";
        pad_i = 6'b000000;
        load_config;
        write_user1(32'h1);
        run_ce_sr;
        write_user1(32'h0);

        pad_i = 6'b000001;
        load_config;
        write_user1(32'h10);
        shift_ir(IR_INTEST, irc);
        run_ce_sr_intest;
        write_user1(32'h0);
        pad_i = 6'b000000;

        $display("");
        $display("[10] 4-bit counter on the carry chain, JTAG-stepped: one count per TCK edge");
        cfgw = `CNTJ_WORD; cfgcrc = `CNTJ_CRC; dname = "counter (jtag)";
        pad_i = 6'b000000;
        init_cnt_seq;
        load_config;
        write_user1(32'h5);
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
        write_user1(32'h4);
        cstate0 = counter;
        idle(10);
        check("USER1 ce off: TCK edges no longer clock the fabric", {60'h0, counter}, {60'h0, cstate0});

        $display("");
        $display("[11] free-running user clock: the counter runs with TCK stopped");
        cfgw = `CNTR_WORD; cfgcrc = `CNTR_CRC; dname = "counter (run, div 0)";
        load_config;
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
        $display("[12] BRAM contents over USER4: written and read back before startup");
        cfgw = `ROM_WORD; cfgcrc = `ROM_CRC; dname = "bram rom";
        pad_i = 6'b000000;
        commit_config;
        bram_dr(4'h0, 64'h0, bcap);
        check("USER4 version", {56'h0, bcap[95:88]}, 64'h07);
        check("USER4 target after power-up: bram0", {60'h0, bcap[69:66]}, 64'h0);
        bram_poke(10'd0, `ROM0);
        bram_dr(4'h2, {46'h0, `ROM1}, bcap);
        bram_dr(4'h2, {46'h0, `ROM2}, bcap);
        bram_dr(4'h2, {46'h0, `ROM3}, bcap);
        bram_dr(4'h0, 64'h0, bcap);
        check("pointer after 4 writes", {54'h0, bcap[27:18]}, 64'd4);
        check("no error while GWE = 0", {63'h0, bcap[64]}, 64'h0);
        bram_peek(10'd0, bword); check("readback mem[0]", {46'h0, bword}, {46'h0, `ROM0});
        bram_peek(10'd1, bword); check("readback mem[1]", {46'h0, bword}, {46'h0, `ROM1});
        bram_peek(10'd2, bword); check("readback mem[2]", {46'h0, bword}, {46'h0, `ROM2});
        bram_peek(10'd3, bword); check("readback mem[3]", {46'h0, bword}, {46'h0, `ROM3});
        jstart;
        shift_ir(IR_BYPASS, irc);

        $display("");
        $display("[13] BRAM as a ROM through the fabric: SW1..0 address it, LD2..0 show it");
        rom_check;

        $display("");
        $display("[14] after startup the contents are locked");
        bram_dr(4'h1, 64'h0, bcap);
        bram_dr(4'h2, 64'h3FFFF, bcap);
        bram_dr(4'h0, 64'h0, bcap);
        check("WRITE with GWE = 1 refused (err)", {62'h0, bcap[65], bcap[64]}, {62'h0, 2'b11});
        dname = "rom unchanged";
        rom_check;

        $display("");
        $display("[15] write modes and output registers, one BRAM clock per USER1 step");
        write_user1(32'h0);
        bchecks = 0;
        cfgw = `JT0_WORD; cfgcrc = `JT0_CRC; dname = "JT0 WRITE_FIRST/READ_FIRST";
        commit_config; jt0_run;
        cfgw = `JT1_WORD; cfgcrc = `JT1_CRC; dname = "JT1 NO_CHANGE+DOA_REG/WRITE_FIRST";
        commit_config; jt1_run;
        cfgw = `JT2_WORD; cfgcrc = `JT2_CRC; dname = "JT2 READ_FIRST/NO_CHANGE+DOB_REG";
        commit_config; jt2_run;
        $display("  PASS  %0d stepped BRAM operations match model.py", bchecks);

        $display("");
        $display("[16] DSP: every opmode, pre-adder, register stages, PCIN cascade - one clock per USER1 step");
        dchecks6 = 0;
        cfgw = `DJ0_WORD; cfgcrc = `DJ0_CRC; dname = "DJ0 M+C/cascade";
        commit_config; dj0_run;
        cfgw = `DJ1_WORD; cfgcrc = `DJ1_CRC; dname = "DJ1 accumulate/D-A";
        commit_config; dj1_run;
        cfgw = `DJ2_WORD; cfgcrc = `DJ2_CRC; dname = "DJ2 D-A with MREG/cascade";
        commit_config; dj2_run;
        dsp_dr(4'h0, 248'h0, dcap);
        check("DSP register version", {56'h0, dcap[255:248]}, 64'h07);
        $display("  PASS  %0d stepped DSP operations (2 cascaded slices) match model.py", dchecks6);

        $display("");
        $display("[17] DSP multiplier through the fabric: A <- {SW1,SW0}, B = 3, P[2:0] -> LD2..0");
        cfgw = `MULT_WORD; cfgcrc = `MULT_CRC; dname = "dsp mult";
        pad_i = 6'b000000;
        load_config;
        dsp_dr(4'h4, `MULT_DRIVE, dcap);
        shift_ir(IR_BYPASS, irc);
        mult_check;

        $display("");
        $display("[18] DSP accumulator on the free-running user clock: P counts enables");
        cfgw = `ACC_WORD; cfgcrc = `ACC_CRC; dname = "dsp accum";
        load_config;
        acc_pulses = 0;
        dsp_dr(4'h4, `ACC_DRIVE, dcap);
        #3200;
        dsp_dr(4'h4, 248'h0, dcap);
        dsp_dr(4'h0, 248'h0, dcap);
        acc_p = dcap[47:0];
        $display("        enables while A*B = 1: %0d, P0 = %0d", acc_pulses, acc_p);
        check("accumulator ran (> 500 enables)", {63'h0, (acc_pulses > 500)}, 64'h1);
        check("P0 == enables counted (+-1 at the drive edges)",
              {63'h0, (acc_p + 1 >= acc_pulses && acc_p <= acc_pulses + 1)}, 64'h1);
        dsp_dr(4'h4, 248'h0, dcap);

        $display("");
        $display("[19] M7: two BRAMs behind one USER4 register (SELECT)");
        cfgw = `PIPE_WORD; cfgcrc = `PIPE_CRC; dname = "pipeline";
        pad_i = 6'b000000;
        write_user1(32'h0);
        commit_config;
        bram_dr(4'h5, {60'h0, `PIPE_BRAM}, bcap);
        bram_dr(4'h0, 64'h0, bcap);
        check("SELECT: target", {60'h0, bcap[69:66]}, {60'h0, `PIPE_BRAM});
        bram_poke(10'd0, `PIPE0);
        bram_dr(4'h2, {46'h0, `PIPE1}, bcap);
        bram_dr(4'h2, {46'h0, `PIPE2}, bcap);
        bram_dr(4'h2, {46'h0, `PIPE3}, bcap);
        bram_peek(10'd0, bword); check("bram1 readback mem[0]", {46'h0, bword}, {46'h0, `PIPE0});
        bram_peek(10'd3, bword); check("bram1 readback mem[3]", {46'h0, bword}, {46'h0, `PIPE3});
        bram_dr(4'h5, 64'h0, bcap);
        bram_peek(10'd0, bword); check("bram0 mem[0] untouched by the bram1 writes", {46'h0, bword}, {46'h0, `BRAM0_MEM0});
        bram_dr(4'h5, 64'hF, bcap);
        bram_dr(4'h0, 64'h0, bcap);
        check("SELECT beyond NBRAM ignored", {60'h0, bcap[69:66]}, 64'h0);
        jstart;
        shift_ir(IR_BYPASS, irc);

        $display("");
        $display("[20] M7: pad -> LUT -> FF -> BRAM -> DSP -> pad, all through generated routing");
        pipe_check;

        $display("");
        $display("[21] M7: %0d-bit counter up the whole last CLB column (every carry direct in it)", `CNT8_BITS);
        cfgw = `CNT8_WORD; cfgcrc = `CNT8_CRC; dname = "counter8";
        load_config;
        write_user1(32'h5);
        c8_0 = counter8;
        dchecks = 0;
        for (n = 1; n <= 300; n = n + 1) begin
            tick(1'b0, 1'b0);
            checks = checks + 1;
            c8 = (c8_0 + n) & {{(32-`CNT8_BITS){1'b0}}, `CNT8_MASK};
            if (counter8 !== c8) begin
                errors = errors + 1;
                $display("  FAIL  TCK edge %0d: counter8=%0d, expected %0d", n, counter8, c8);
            end else
                dchecks = dchecks + 1;
        end
        $display("  PASS  full-column counter counted %0d consecutive TCK edges, wrapping every %0d", dchecks, `CNT8_MASK + 1);
        write_user1(32'h0);

        $display("");
        $display("[22] M7: random routed netlists, every CLB output and LED == model.py after every clock");
        run_random;

        $display("");
        $display("[23] reset restores IDCODE");
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
