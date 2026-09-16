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
// Timing contract used by hw/constr/pynq_z2.xdc: consecutive gce pulses are at
// least 120 sysclk cycles apart (free-running: >= 256; JTAG-stepped: TCK <= 1 MHz
// is >= 125 cycles), so fabric flop-to-flop paths get a 120-cycle multicycle.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module clock_ctrl #(
    parameter integer DIV_W     = 5,
    parameter integer MIN_SHIFT = 8
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

    // sysclk domain
    output reg              gce,
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
    (* ASYNC_REG = "TRUE" *) reg [DIV_W-1:0] div_m0 = {DIV_W{1'b0}};
    (* ASYNC_REG = "TRUE" *) reg [DIV_W-1:0] div_m1 = {DIV_W{1'b0}};

    reg        tck_d  = 1'b0;
    reg        step_d = 1'b0;
    reg [31:0] cnt    = 32'h0;

    always @(posedge sysclk) begin
        tck_m  <= {tck_m[0],  tck};
        ce_m   <= {ce_m[0],   ce};
        step_m <= {step_m[0], step};
        cin_m  <= {cin_m[0],  cin};
        gsr_m  <= {gsr_m[0],  gsr};
        gwe_m  <= {gwe_m[0],  gwe};
        mode_m <= {mode_m[0], clk_mode};
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

    initial gce = 1'b0;

    always @(posedge sysclk) begin
        if (mode_m[1]) begin
            if (cnt >= last) begin
                cnt <= 32'h0;
                gce <= 1'b1;
            end else begin
                cnt <= cnt + 32'h1;
                gce <= 1'b0;
            end
        end else begin
            cnt <= 32'h0;
            gce <= (tck_rise & ce_m[1]) | step_rise;
        end
    end

    assign gsr_s = gsr_m[1];
    assign gwe_s = gwe_m[1];
    assign cin_s = cin_m[1];

endmodule

`default_nettype wire
