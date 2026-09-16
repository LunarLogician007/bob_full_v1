// -----------------------------------------------------------------------------
// bob_harness.vh - the complete bob FPGA driven over JTAG, for testbenches that
// load chains through the configuration plane (tb_synth M8/M9, sim/tb_cosim.v M10).
// Included inside a module: the DUT (bob_fpga), pads (pad_i -> SW/BTN pads,
// pad_o = LD2..0), and the JTAG tasks proven in tb_synth: tick, idle, shift_ir,
// shift_dr, shift_chain, commit_config (JPROGRAM, CRC, CFG_IN, status), start
// (JSTART), write_user1, bram_dr, bram_poke. Needs `include "bob_params.vh" first.
// -----------------------------------------------------------------------------

    localparam        HALF   = 50;
    localparam integer CFG_W = `BOB_CHAIN_W;
    localparam integer NPAD  = `BOB_NPAD;

    localparam [5:0] IR_USER1    = 6'b000010;
    localparam [5:0] IR_CFG_CTRL = 6'b000011;
    localparam [5:0] IR_CFG_IN   = 6'b000101;
    localparam [5:0] IR_JPROGRAM = 6'b001011;
    localparam [5:0] IR_JSTART   = 6'b001100;
    localparam [5:0] IR_BRAM     = 6'b100011;
    localparam [5:0] IR_CAPTURE  = 6'b100010;
    localparam [5:0] IR_BYPASS   = 6'b111111;
    localparam integer B_CRC_OK = 48, B_COMMITTED = 51;

    reg        sysclk = 1'b0;
    reg        tck = 1'b0;
    reg        tms = 1'b1;
    reg        tdi = 1'b0;
    wire       tdo;
    wire [3:0] tap_state;
    wire       configured;

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

    reg clk_on = 1'b1;
    always #2 sysclk = clk_on ? ~sysclk : 1'b0;

    bob_fpga #(.DIV_MIN_SHIFT(3)) dut (
        .sysclk(sysclk), .tck(tck), .tms(tms), .tdi(tdi), .tdo(tdo),
        .pad_i(pads_i), .pad_o(pads_o), .tap_state(tap_state), .configured(configured));

    integer          errors = 0;
    integer          checks = 0;
    integer          dchecks = 0;
    reg [1023:0]     dname;
    reg [CFG_W-1:0]  cfgw;
    reg [31:0]       cfgcrc;
    reg [127:0]      rx;
    reg [5:0]        irc;
    reg [63:0]       st;
    reg              tdo_s = 1'b0;

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

    task shift_ir(input [5:0] value, output [5:0] cap);
        integer k;
        begin
            tick(1'b1, 1'b0); tick(1'b1, 1'b0); tick(1'b0, 1'b0); tick(1'b0, 1'b0);
            for (k = 0; k < 5; k = k + 1) begin
                tick(1'b0, value[k]);
                cap[k] = tdo_s;
            end
            tick(1'b1, value[5]);
            cap[5] = tdo_s;
            tick(1'b1, 1'b0); tick(1'b0, 1'b0);
        end
    endtask

    task shift_dr(input integer len, input [127:0] din, output [127:0] dout);
        integer k;
        begin
            dout = 128'h0;
            tick(1'b1, 1'b0); tick(1'b0, 1'b0); tick(1'b0, 1'b0);
            for (k = 0; k < len - 1; k = k + 1) begin
                tick(1'b0, din[k]);
                dout[k] = tdo_s;
            end
            tick(1'b1, din[len-1]);
            dout[len-1] = tdo_s;
            tick(1'b1, 1'b0); tick(1'b0, 1'b0);
        end
    endtask

    task shift_chain(input [CFG_W-1:0] din);
        integer k;
        begin
            tick(1'b1, 1'b0); tick(1'b0, 1'b0); tick(1'b0, 1'b0);
            clk_on = 1'b0;
            for (k = 0; k < CFG_W - 1; k = k + 1) tick(1'b0, din[k]);
            clk_on = 1'b1;
            tick(1'b1, din[CFG_W-1]);
            tick(1'b1, 1'b0); tick(1'b0, 1'b0);
        end
    endtask

    task commit_config;
        begin
            write_user1(32'h0);
            shift_ir(IR_JPROGRAM, irc);
            shift_ir(IR_CFG_CTRL, irc);
            shift_dr(64, {64'h0, 8'hC5, 24'h0, cfgcrc}, rx);
            shift_ir(IR_CFG_IN, irc);
            shift_chain(cfgw);
            shift_ir(IR_CFG_CTRL, irc);
            shift_dr(64, 128'h0, rx);
            st = rx[63:0];
            checks = checks + 1;
            if (!st[B_COMMITTED] || !st[B_CRC_OK]) begin
                errors = errors + 1;
                $display("  FAIL  %0s: chain not committed", dname);
            end
            dchecks = 0;
        end
    endtask

    task start;
        begin
            shift_ir(IR_JSTART, irc);
            idle(12);
            shift_ir(IR_BYPASS, irc);
        end
    endtask

    task write_user1(input [31:0] v);
        begin
            shift_ir(IR_USER1, irc);
            shift_dr(32, {96'h0, v}, rx);
        end
    endtask

    task bram_dr(input [3:0] cmd, input [63:0] payload);
        begin
            shift_ir(IR_BRAM, irc);
            shift_dr(96, {32'h0, cmd, 28'h0, payload}, rx);
        end
    endtask

    task bram_poke(input [3:0] b, input [9:0] addr, input [17:0] word);
        begin
            bram_dr(4'h5, {60'h0, b});
            bram_dr(4'h1, {54'h0, addr});
            bram_dr(4'h2, {46'h0, word});
        end
    endtask

