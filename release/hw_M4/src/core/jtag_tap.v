// -----------------------------------------------------------------------------
// jtag_tap.v - IEEE 1149.1 Test Access Port controller
//
// Drives a one-CLB mini FPGA: a boundary scan register around the block, a
// 71-bit configuration chain into it, and a control/status word beside it.
//
// The whole thing lives in the TCK clock domain. There is no system clock, no
// PS and no reset pin - the probe clocks everything, which is what a TAP is
// supposed to do and what keeps this design free of clock-domain crossings.
//
// Timing contract (IEEE 1149.1):
//   - TMS and TDI are sampled on the RISING edge of TCK
//   - the state machine advances on the RISING edge of TCK
//   - TDO is launched on the FALLING edge of TCK
//   - the IR and DR update latches fire on the FALLING edge of TCK
//   - all shift registers are LSB-first
//
// Reset: there is deliberately no TRST pin. FPGA flip-flops power up from
// their bitstream INIT values (state = Test-Logic-Reset, ir = IDCODE), and the
// IEEE-guaranteed "five TCKs with TMS high" sequence always returns here.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module jtag_tap #(
    parameter [31:0]  IDCODE_VALUE = 32'h2BEEF093,
    parameter integer CFG_W        = 71,
    // How many bits of live status USER returns alongside the control word.
    // 3 for the single CLB ({cout,o5,o}); 16 for the 4x4 fabric (every CLB o).
    parameter integer STATUS_W     = 3
)(
    input  wire        tck,
    input  wire        tms,
    input  wire        tdi,
    output reg         tdo,

    // --- boundary scan register ---------------------------------------------
    // The cells themselves live in the top level as a chain of bsc_cell. These
    // strobes are already qualified by the selected instruction, so the cells
    // need no opcode decode of their own.
    output wire        bsr_capture,
    output wire        bsr_shift,
    output wire        bsr_update,
    output wire        bsr_mode,     // 1 = cells drive, 0 = transparent
    output wire        bsr_si,       // into the cell nearest TDI
    input  wire        bsr_so,       // out of the cell nearest TDO

    // Test-Logic-Reset. MUST be used synchronously - see the note below.
    output wire        tlr,

    // --- CLB configuration word ---------------------------------------------
    output reg [CFG_W-1:0] cfg_out,

    // --- USER control and status --------------------------------------------
    output wire        ce,
    output wire        sr,
    output wire        cin,
    output wire        step_pulse,   // one TCK-wide pulse per rising edge of step
    input  wire [STATUS_W-1:0] clb_status,  // sampled into USER at Capture-DR

    output wire [3:0]  tap_state
);

    // ---------------------------------------------------------------------
    // TAP state encoding. Conventional 4-bit JTAG numbering, chosen so that
    // TEST_LOGIC_RESET == 4'hF: all-ones is also the natural power-up value.
    //
    // NOTE on `tlr`: a combinational decode of this state register can glitch
    // to 4'hF during three of the transitions below, because source and
    // destination between them have every bit set:
    //
    //     RUN_TEST_IDLE 1100 -> SELECT_DR 0111
    //     CAPTURE_IR    1110 -> EXIT1_IR  1001
    //     UPDATE_IR     1101 -> SELECT_DR 0111
    //
    // Nothing constrains the four bits to change together, so `tlr` must only
    // ever be consumed on a clock edge. bsc_cell.v does exactly that, and its
    // header explains what happens when a design gets this wrong: the boundary
    // silently commits zeros at Update-DR, EXTEST and INTEST both fail, and
    // capture and shift still look perfect.
    // ---------------------------------------------------------------------
    localparam [3:0] EXIT2_DR          = 4'd0;
    localparam [3:0] EXIT1_DR          = 4'd1;
    localparam [3:0] SHIFT_DR          = 4'd2;
    localparam [3:0] PAUSE_DR          = 4'd3;
    localparam [3:0] SELECT_IR         = 4'd4;
    localparam [3:0] UPDATE_DR         = 4'd5;
    localparam [3:0] CAPTURE_DR        = 4'd6;
    localparam [3:0] SELECT_DR         = 4'd7;
    localparam [3:0] EXIT2_IR          = 4'd8;
    localparam [3:0] EXIT1_IR          = 4'd9;
    localparam [3:0] SHIFT_IR          = 4'd10;
    localparam [3:0] PAUSE_IR          = 4'd11;
    localparam [3:0] RUN_TEST_IDLE     = 4'd12;
    localparam [3:0] UPDATE_IR         = 4'd13;
    localparam [3:0] CAPTURE_IR        = 4'd14;
    localparam [3:0] TEST_LOGIC_RESET  = 4'd15;

    // ---------------------------------------------------------------------
    // Instruction set. IR is 4 bits.
    //
    //   EXTEST  the boundary drives the output pads; the CLB is isolated
    //   SAMPLE  the boundary observes the pins without touching them
    //   IDCODE  32-bit device identification
    //   USER    32-bit control word in; control in [3:0] and STATUS_W bits of
    //           live CLB output back above it
    //   INTEST  the boundary drives the CLB inputs and captures its outputs
    //   CONFIG  the 71-bit CLB configuration word, readable and writable
    //   BYPASS  one flop
    // ---------------------------------------------------------------------
    localparam [3:0] IR_EXTEST  = 4'b0000;
    localparam [3:0] IR_SAMPLE  = 4'b0001;
    localparam [3:0] IR_IDCODE  = 4'b0010;
    localparam [3:0] IR_USER    = 4'b0011;
    localparam [3:0] IR_INTEST  = 4'b0100;
    localparam [3:0] IR_CONFIG  = 4'b0101;
    localparam [3:0] IR_BYPASS  = 4'b1111;

    // USER control word bit positions
    localparam integer USER_CE       = 0;
    localparam integer USER_SR       = 1;
    localparam integer USER_CIN      = 2;
    localparam integer USER_STEP     = 3;
    localparam integer USER_AUTOSTEP = 4;

    reg [3:0]        state     = TEST_LOGIC_RESET;
    reg [3:0]        ir        = IR_IDCODE;
    reg [3:0]        ir_shift  = 4'b0001;
    reg [31:0]       idcode_dr = 32'h0;
    reg [31:0]       user_dr   = 32'h0;
    reg [CFG_W-1:0]  cfg_dr    = {CFG_W{1'b0}};
    reg              bypass_dr = 1'b0;
    reg [31:0]       user_out  = 32'h0;

    assign tap_state = state;
    assign tlr       = (state == TEST_LOGIC_RESET);

    assign ce  = user_out[USER_CE];
    assign sr  = user_out[USER_SR];
    assign cin = user_out[USER_CIN];

    // ---------------------------------------------------------------------
    // State machine. Explicit transition table, no encoding tricks.
    // ---------------------------------------------------------------------
    always @(posedge tck) begin
        case (state)
            TEST_LOGIC_RESET: state <= tms ? TEST_LOGIC_RESET : RUN_TEST_IDLE;
            RUN_TEST_IDLE:    state <= tms ? SELECT_DR        : RUN_TEST_IDLE;
            SELECT_DR:        state <= tms ? SELECT_IR        : CAPTURE_DR;
            CAPTURE_DR:       state <= tms ? EXIT1_DR         : SHIFT_DR;
            SHIFT_DR:         state <= tms ? EXIT1_DR         : SHIFT_DR;
            EXIT1_DR:         state <= tms ? UPDATE_DR        : PAUSE_DR;
            PAUSE_DR:         state <= tms ? EXIT2_DR         : PAUSE_DR;
            EXIT2_DR:         state <= tms ? UPDATE_DR        : SHIFT_DR;
            UPDATE_DR:        state <= tms ? SELECT_DR        : RUN_TEST_IDLE;
            SELECT_IR:        state <= tms ? TEST_LOGIC_RESET : CAPTURE_IR;
            CAPTURE_IR:       state <= tms ? EXIT1_IR         : SHIFT_IR;
            SHIFT_IR:         state <= tms ? EXIT1_IR         : SHIFT_IR;
            EXIT1_IR:         state <= tms ? UPDATE_IR        : PAUSE_IR;
            PAUSE_IR:         state <= tms ? EXIT2_IR         : PAUSE_IR;
            EXIT2_IR:         state <= tms ? UPDATE_IR        : SHIFT_IR;
            UPDATE_IR:        state <= tms ? SELECT_DR        : RUN_TEST_IDLE;
            default:          state <= TEST_LOGIC_RESET;
        endcase
    end

    // ---------------------------------------------------------------------
    // Instruction shift register.
    // Capture-IR loads 4'b0001: IEEE mandates that the two LSBs read back as
    // 01, which is exactly what lets a probe auto-discover the IR length.
    // ---------------------------------------------------------------------
    always @(posedge tck) begin
        if (state == CAPTURE_IR)
            ir_shift <= 4'b0001;
        else if (state == SHIFT_IR)
            ir_shift <= {tdi, ir_shift[3:1]};
    end

    // ---------------------------------------------------------------------
    // Boundary scan strobes, qualified by the instruction so that scanning
    // IDCODE or CONFIG cannot disturb what the boundary is driving.
    // ---------------------------------------------------------------------
    wire bsr_selected = (ir == IR_EXTEST) || (ir == IR_SAMPLE) || (ir == IR_INTEST);

    assign bsr_capture = bsr_selected && (state == CAPTURE_DR);
    assign bsr_shift   = bsr_selected && (state == SHIFT_DR);
    assign bsr_update  = bsr_selected && (state == UPDATE_DR);
    assign bsr_mode    = (ir == IR_EXTEST) || (ir == IR_INTEST);
    assign bsr_si      = tdi;

    // ---------------------------------------------------------------------
    // Internal data registers. They all shift in parallel and only the
    // selected one reaches TDO - cheaper than a shift-enable mux, and safe
    // because every one of them re-captures at Capture-DR and only commits at
    // an Update-DR that is qualified by the instruction.
    // ---------------------------------------------------------------------
    always @(posedge tck) begin
        if (state == CAPTURE_DR) begin
            idcode_dr <= IDCODE_VALUE;
            cfg_dr    <= cfg_out;                      // CONFIG reads back
            user_dr   <= {{(28-STATUS_W){1'b0}}, clb_status, user_out[3:0]};
            bypass_dr <= 1'b0;
        end else if (state == SHIFT_DR) begin
            idcode_dr <= {tdi, idcode_dr[31:1]};
            cfg_dr    <= {tdi, cfg_dr[CFG_W-1:1]};
            user_dr   <= {tdi, user_dr[31:1]};
            bypass_dr <= tdi;
        end
    end

    // Which register drives TDO for the currently latched instruction.
    reg dr_tdo;
    always @(*) begin
        case (ir)
            IR_IDCODE:                     dr_tdo = idcode_dr[0];
            IR_USER:                       dr_tdo = user_dr[0];
            IR_CONFIG:                     dr_tdo = cfg_dr[0];
            IR_EXTEST, IR_SAMPLE, IR_INTEST: dr_tdo = bsr_so;
            default:                       dr_tdo = bypass_dr;
        endcase
    end

    // ---------------------------------------------------------------------
    // Falling-edge domain: update latches and the TDO launch register.
    // ---------------------------------------------------------------------
    always @(negedge tck) begin
        if (state == TEST_LOGIC_RESET)
            ir <= IR_IDCODE;                // IEEE: reset selects IDCODE
        else if (state == UPDATE_IR)
            ir <= ir_shift;

        if (state == UPDATE_DR) begin
            if (ir == IR_USER)   user_out <= user_dr;
            if (ir == IR_CONFIG) cfg_out  <= cfg_dr;
        end

        case (state)
            SHIFT_IR: tdo <= ir_shift[0];
            SHIFT_DR: tdo <= dr_tdo;
            default:  tdo <= 1'b0;
        endcase
    end

    // ---------------------------------------------------------------------
    // Single-step, two ways.
    //
    // MANUAL: user_out[USER_STEP] moves on a falling edge at Update-DR, and a
    // 0->1 transition of it becomes exactly one TCK-wide pulse in the
    // rising-edge domain, which is where the CLB's flop lives. Two scans per
    // step: write the bit 1, then write it 0 again before the next one.
    // Holding it high does not free-run the CLB.
    //
    // AUTO: manual stepping cannot drive a flop through INTEST, and the reason
    // is structural rather than a detail. bsr_mode is decoded from the current
    // instruction - as IEEE requires - so the instant a USER scan is loaded to
    // issue the step, the boundary goes transparent and the CLB stops seeing
    // the vector INTEST applied. It would clock in whatever the real pins
    // happen to be. So with USER_AUTOSTEP set, an INTEST Update-DR raises the
    // clock enable itself, on the very next rising edge, while INTEST is still
    // selected and the boundary is still driving the vector.
    //
    // One INTEST scan then means: apply this vector, advance the flop one
    // clock with it. The answer appears in the next scan, exactly like the
    // combinational path.
    // ---------------------------------------------------------------------
    reg step_d = 1'b0;
    always @(posedge tck) step_d <= user_out[USER_STEP];
    wire manual_step = user_out[USER_STEP] & ~step_d;

    reg autostep_arm = 1'b0;
    always @(negedge tck)
        autostep_arm <= (state == UPDATE_DR) && (ir == IR_INTEST)
                        && user_out[USER_AUTOSTEP];

    assign step_pulse = manual_step | autostep_arm;

    initial cfg_out = {CFG_W{1'b0}};
    initial tdo     = 1'b0;

endmodule

`default_nettype wire
