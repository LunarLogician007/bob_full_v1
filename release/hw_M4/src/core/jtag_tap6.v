// -----------------------------------------------------------------------------
// jtag_tap6.v - IEEE 1149.1 TAP with the AMD 7-series 6-bit instruction set
//
// Copy of jtag_tap.v (hardware-proven on the PYNQ-Z2) with:
//   - a 6-bit IR using the 7-series codes (docs/bitstream-format.md section 2)
//   - USERCODE added
//   - the CONFIG shift register moved OUT: the configuration chain (CFG_IN /
//     CFG_OUT), CFG_CTRL and CAPTURE are external data registers, fed by the
//     strobes and selects this module exports and returned through *_so inputs
//   - Capture-IR returns status: {DONE, INIT_B, COMMITTED, CRC_ERR, 0, 1}
//
// Kept exactly: the state machine and its encoding, rising-edge sampling,
// falling-edge TDO and update latches, IDCODE/BYPASS, the USER control word
// (now USER1) with manual and INTEST auto-step, and the synchronous-tlr rule.
//
// Timing contract (IEEE 1149.1):
//   - TMS and TDI are sampled on the RISING edge of TCK
//   - the state machine advances on the RISING edge of TCK
//   - TDO is launched on the FALLING edge of TCK
//   - the IR and DR update latches fire on the FALLING edge of TCK
//   - all shift registers are LSB-first
//
// The exported state decodes (dr_capture, dr_shift, dr_update, jprogram,
// jstart_tick) are combinational decodes of the state register. Like tlr they
// can glitch between edges and MUST only be consumed on a TCK edge.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module jtag_tap6 #(
    parameter [31:0]  IDCODE_VALUE   = 32'h4BEEF093,
    parameter [31:0]  USERCODE_VALUE = 32'h00000000,
    // Live status bits USER1 returns above its control bits.
    parameter integer STATUS_W       = 3,
    // 0: this top has no boundary ring; SAMPLE/EXTEST/INTEST act as BYPASS.
    parameter integer BSR_PRESENT    = 1
)(
    input  wire        tck,
    input  wire        tms,
    input  wire        tdi,
    output reg         tdo,

    // --- boundary scan register (cells live in the top) ---------------------
    output wire        bsr_capture,
    output wire        bsr_shift,
    output wire        bsr_update,
    output wire        bsr_mode,     // 1 = cells drive, 0 = transparent
    output wire        bsr_si,
    input  wire        bsr_so,

    // Test-Logic-Reset. MUST be used synchronously.
    output wire        tlr,

    // --- external data registers ----------------------------------------------
    output wire        dr_capture,   // state == Capture-DR
    output wire        dr_shift,     // state == Shift-DR
    output wire        dr_update,    // state == Update-DR
    output wire        sel_cfg_in,
    output wire        sel_cfg_out,
    output wire        sel_ctrl,     // USER2 = CFG_CTRL
    output wire        sel_capture,  // USER3 = CAPTURE
    input  wire        cfg_so,
    input  wire        ctrl_so,
    input  wire        cap_so,

    // --- configuration commands --------------------------------------------------
    output wire        jprogram,     // Update-IR with JPROGRAM being loaded
    output wire        jstart_tick,  // Run-Test/Idle with JSTART loaded
    input  wire [3:0]  ir_status,    // {DONE, INIT_B, COMMITTED, CRC_ERR}

    // --- USER1 control and status -------------------------------------------------
    output wire        ce,
    output wire        sr,
    output wire        cin,
    output wire        step_pulse,   // one TCK-wide pulse per rising edge of step
    input  wire [STATUS_W-1:0] user_status,

    output wire [3:0]  tap_state,
    output wire [5:0]  ir_value
);

    // ---------------------------------------------------------------------
    // TAP state encoding - identical to jtag_tap.v. TEST_LOGIC_RESET == 4'hF.
    //
    // A combinational decode of this register can glitch to 4'hF during
    //     RUN_TEST_IDLE 1100 -> SELECT_DR 0111
    //     CAPTURE_IR    1110 -> EXIT1_IR  1001
    //     UPDATE_IR     1101 -> SELECT_DR 0111
    // so every decode leaving this module is consumed only on a clock edge.
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
    // Instruction set - AMD 7-series codes; see docs/bitstream-format.md.
    // ---------------------------------------------------------------------
    localparam [5:0] IR_SAMPLE   = 6'b000001;
    localparam [5:0] IR_USER1    = 6'b000010;
    localparam [5:0] IR_USER2    = 6'b000011;   // CFG_CTRL
    localparam [5:0] IR_CFG_OUT  = 6'b000100;
    localparam [5:0] IR_CFG_IN   = 6'b000101;
    localparam [5:0] IR_INTEST   = 6'b000111;   // private, not an AMD code
    localparam [5:0] IR_USERCODE = 6'b001000;
    localparam [5:0] IR_IDCODE   = 6'b001001;
    localparam [5:0] IR_JPROGRAM = 6'b001011;
    localparam [5:0] IR_JSTART   = 6'b001100;
    localparam [5:0] IR_USER3    = 6'b100010;   // CAPTURE
    localparam [5:0] IR_EXTEST   = 6'b100110;
    localparam [5:0] IR_BYPASS   = 6'b111111;

    // USER1 control word bit positions (as USER in jtag_tap.v)
    localparam integer USER_CE       = 0;
    localparam integer USER_SR       = 1;
    localparam integer USER_CIN      = 2;
    localparam integer USER_STEP     = 3;
    localparam integer USER_AUTOSTEP = 4;

    reg [3:0]   state       = TEST_LOGIC_RESET;
    reg [5:0]   ir          = IR_IDCODE;
    reg [5:0]   ir_shift    = 6'b000001;
    reg [31:0]  idcode_dr   = 32'h0;
    reg [31:0]  usercode_dr = 32'h0;
    reg [31:0]  user_dr     = 32'h0;
    reg         bypass_dr   = 1'b0;
    reg [31:0]  user_out    = 32'h0;

    assign tap_state = state;
    assign ir_value  = ir;
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
    // Instruction shift register. Capture-IR loads status with the IEEE-
    // mandated 01 in the two LSBs; 7-series reports DONE in bit 5 and INIT_B in
    // bit 4 the same way.
    // ---------------------------------------------------------------------
    always @(posedge tck) begin
        if (state == CAPTURE_IR)
            ir_shift <= {ir_status, 2'b01};
        else if (state == SHIFT_IR)
            ir_shift <= {tdi, ir_shift[5:1]};
    end

    // ---------------------------------------------------------------------
    // Boundary scan strobes, qualified by the instruction.
    // ---------------------------------------------------------------------
    wire bsr_on       = (BSR_PRESENT != 0);
    wire bsr_selected = bsr_on &&
                        ((ir == IR_EXTEST) || (ir == IR_SAMPLE) || (ir == IR_INTEST));

    assign bsr_capture = bsr_selected && (state == CAPTURE_DR);
    assign bsr_shift   = bsr_selected && (state == SHIFT_DR);
    assign bsr_update  = bsr_selected && (state == UPDATE_DR);
    assign bsr_mode    = bsr_on && ((ir == IR_EXTEST) || (ir == IR_INTEST));
    assign bsr_si      = tdi;

    // ---------------------------------------------------------------------
    // External data registers and configuration commands.
    // ---------------------------------------------------------------------
    assign dr_capture  = (state == CAPTURE_DR);
    assign dr_shift    = (state == SHIFT_DR);
    assign dr_update   = (state == UPDATE_DR);
    assign sel_cfg_in  = (ir == IR_CFG_IN);
    assign sel_cfg_out = (ir == IR_CFG_OUT);
    assign sel_ctrl    = (ir == IR_USER2);
    assign sel_capture = (ir == IR_USER3);

    // JPROGRAM takes effect as it is loaded (UG470: the instruction itself is
    // the command), not on a later DR scan.
    assign jprogram    = (state == UPDATE_IR) && (ir_shift == IR_JPROGRAM);
    assign jstart_tick = (state == RUN_TEST_IDLE) && (ir == IR_JSTART);

    // ---------------------------------------------------------------------
    // Internal data registers.
    // ---------------------------------------------------------------------
    always @(posedge tck) begin
        if (state == CAPTURE_DR) begin
            idcode_dr   <= IDCODE_VALUE;
            usercode_dr <= USERCODE_VALUE;
            user_dr     <= {{(28-STATUS_W){1'b0}}, user_status, user_out[3:0]};
            bypass_dr   <= 1'b0;
        end else if (state == SHIFT_DR) begin
            idcode_dr   <= {tdi, idcode_dr[31:1]};
            usercode_dr <= {tdi, usercode_dr[31:1]};
            user_dr     <= {tdi, user_dr[31:1]};
            bypass_dr   <= tdi;
        end
    end

    reg dr_tdo;
    always @(*) begin
        case (ir)
            IR_IDCODE:                       dr_tdo = idcode_dr[0];
            IR_USERCODE:                     dr_tdo = usercode_dr[0];
            IR_USER1:                        dr_tdo = user_dr[0];
            IR_USER2:                        dr_tdo = ctrl_so;
            IR_USER3:                        dr_tdo = cap_so;
            IR_CFG_IN, IR_CFG_OUT:           dr_tdo = cfg_so;
            IR_EXTEST, IR_SAMPLE, IR_INTEST: dr_tdo = bsr_selected ? bsr_so : bypass_dr;
            default:                         dr_tdo = bypass_dr;
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

        if (state == UPDATE_DR && ir == IR_USER1)
            user_out <= user_dr;

        case (state)
            SHIFT_IR: tdo <= ir_shift[0];
            SHIFT_DR: tdo <= dr_tdo;
            default:  tdo <= 1'b0;
        endcase
    end

    // ---------------------------------------------------------------------
    // Single-step, two ways - unchanged from jtag_tap.v, see its notes.
    // ---------------------------------------------------------------------
    reg step_d = 1'b0;
    always @(posedge tck) step_d <= user_out[USER_STEP];
    wire manual_step = user_out[USER_STEP] & ~step_d;

    reg autostep_arm = 1'b0;
    always @(negedge tck)
        autostep_arm <= (state == UPDATE_DR) && (ir == IR_INTEST) && bsr_on
                        && user_out[USER_AUTOSTEP];

    assign step_pulse = manual_step | autostep_arm;

    initial tdo = 1'b0;

endmodule

`default_nettype wire
