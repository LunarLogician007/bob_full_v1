// -----------------------------------------------------------------------------
// clock_ctrl.v - the fabric's user clock (M4)
//
// Every fabric flop is clocked by the board's 125 MHz sysclk (PYNQ-Z2 H16,
// through a BUFG in the top) and may change only on a cycle where `gce` is
// high. `gce` is the user clock, realised as a one-cycle clock enable rather
// than a logic-generated clock (AMD UG949 recommends enables over derived
// clocks; Aegis docs/arch/clock.md uses a divider the same way):
//
//   clk_mode 0  JTAG-stepped   one gce pulse per TCK rising edge while USER1 ce
//                              is set, plus one per USER1 step / INTEST autostep
//                              pulse. Exactly the pre-M4 behaviour (flops
//                              advanced once per TCK), now as an enable.
//   clk_mode 1  free-running   one gce pulse every 2**(clk_div + MIN_SHIFT)
//                              sysclk cycles (MIN_SHIFT 8: at most 488 kHz).
//
// Everything arriving from the TCK domain (TCK itself as data, USER1 ce/step/
// cin, GSR, GWE, and the quasi-static clock config) goes through two-flop
// synchronisers marked ASYNC_REG. gsr powers up asserted, gwe de-asserted, so
// the fabric starts held in reset like the configuration plane says.
//
// Timing contract used by hw/constr/pynq_z2.xdc (M13, docs/bitstream-format.md
// section 11): consecutive gce pulses are at least 2**GAP_SHIFT sysclk cycles apart
// in BOTH modes, enforced here - a request arriving earlier waits (one is kept
// pending), so fabric flop-to-flop paths are a 2**GAP_SHIFT-cycle multicycle by
// construction, not by assumption about TCK. The board uses GAP_SHIFT = 8
// (256 cycles, 2048 ns); simulation may shorten it with the divider.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module clock_ctrl #(
    parameter integer DIV_W     = 5,
    parameter integer MIN_SHIFT = 8,
    parameter integer GAP_SHIFT = 8
)(
    input  wire             sysclk,

    // TCK domain - asynchronous to sysclk
    input  wire             tck,
    input  wire             clk_mode,
    input  wire [DIV_W-1:0] clk_div,
    input  wire             ce,
    input  wire             step,
    input  wire             cin,
    input  wire             gsr,
    input  wire             gwe,
    input  wire             freeze,          // M14: hold gce (partial reconfiguration)

    // sysclk domain
    output reg              gce,
    output reg              frozen,          // gce is held; to cfg_frames (synchronised there)
    output wire             gsr_s,
    output wire             gwe_s,
    output wire             cin_s
);

    (* ASYNC_REG = "TRUE" *) reg [1:0]       tck_m  = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0]       ce_m   = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0]       step_m = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0]       cin_m  = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0]       gsr_m  = 2'b11;
    (* ASYNC_REG = "TRUE" *) reg [1:0]       gwe_m  = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0]       mode_m = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0]       frz_m  = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [DIV_W-1:0] div_m0 = {DIV_W{1'b0}};
    (* ASYNC_REG = "TRUE" *) reg [DIV_W-1:0] div_m1 = {DIV_W{1'b0}};

    reg        tck_d  = 1'b0;
    reg        step_d = 1'b0;
    reg [31:0] cnt    = 32'h0;
    reg [31:0] gap    = 32'hFFFFFFFF;          // sysclk cycles since the last gce (saturating)
    reg        pend   = 1'b0;                  // a request that arrived too early

    always @(posedge sysclk) begin
        tck_m  <= {tck_m[0],  tck};
        ce_m   <= {ce_m[0],   ce};
        step_m <= {step_m[0], step};
        cin_m  <= {cin_m[0],  cin};
        gsr_m  <= {gsr_m[0],  gsr};
        gwe_m  <= {gwe_m[0],  gwe};
        mode_m <= {mode_m[0], clk_mode};
        frz_m  <= {frz_m[0],  freeze};
        div_m0 <= clk_div;
        div_m1 <= div_m0;
        tck_d  <= tck_m[1];
        step_d <= step_m[1];
    end

    wire tck_rise  = tck_m[1]  & ~tck_d;
    wire step_rise = step_m[1] & ~step_d;

    // period = 2**shift cycles, shift clamped to 31
    wire [6:0]  shift_w  = {2'b00, div_m1} + MIN_SHIFT[6:0];
    wire [4:0]  shift    = (shift_w > 7'd31) ? 5'd31 : shift_w[4:0];
    wire [31:0] last     = (32'h1 << shift) - 32'h1;

    wire [31:0] min_gap  = (32'h1 << GAP_SHIFT) - 32'h1;

    initial begin
        gce    = 1'b0;
        frozen = 1'b0;
    end

    reg req;
    always @(*) begin
        if (mode_m[1]) req = (cnt >= last);
        else           req = (tck_rise & ce_m[1]) | step_rise;
    end

    always @(posedge sysclk) begin
        if (mode_m[1])
            cnt <= (cnt >= last) ? 32'h0 : cnt + 32'h1;
        else
            cnt <= 32'h0;

        frozen <= frz_m[1];
        if (frz_m[1]) begin
            // M14: frozen. No enable, and requests that arrive now are dropped, so the
            // fabric is exactly as it was when the freeze arrived; frozen rises on the
            // same edge gce is forced low.
            gce  <= 1'b0;
            pend <= 1'b0;
            if (gap != 32'hFFFFFFFF) gap <= gap + 32'h1;
        end else if ((req | pend) && (gap >= min_gap)) begin
            gce  <= 1'b1;
            gap  <= 32'h0;
            pend <= 1'b0;
        end else begin
            gce <= 1'b0;
            if (gap != 32'hFFFFFFFF) gap <= gap + 32'h1;
            if (req) pend <= 1'b1;
        end
    end

    assign gsr_s = gsr_m[1];
    assign gwe_s = gwe_m[1];
    assign cin_s = cin_m[1];

endmodule

`default_nettype wire
