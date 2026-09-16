// -----------------------------------------------------------------------------
// dsp_core.v - one DSP slice, AMD DSP48E1 behaviour trimmed (M6)
//
// AMD UG479, the parts that matter for arithmetic, with static (configuration)
// modes instead of the dynamic OPMODE/INMODE/ALUMODE pins:
//
//   inputs        A 25, B 18, C 48, D 25 (two's complement)
//   pre-adder     AD = use_d ? (d_sub ? D - A : D + A) : A        (25 bits, wraps)
//   multiplier    M  = AD * B                                      (43 bits)
//   output        opmode 0  P = M
//                 opmode 1  P = M + C
//                 opmode 2  P = P + M        (accumulator; always fed back from
//                                             the P register, so no loop with PREG=0)
//                 opmode 3  P = (PCIN >>> 17) + M   (cascade, UG479's 17-bit shift)
//   registers     AREG DREG BREG CREG MREG PREG, each 0 or 1 stage (config)
//   control pins  ce_ad/rst_ad (A and D), ce_b/rst_b, ce_m/rst_m, ce_p/rst_p
//                 (C and P share ce_p/rst_p - a trim of CEC/RSTC). Reset beats
//                 enable, as UG479's synchronous resets do.
//   clocking      gce (user clock enable) and GWE gate every register; GSR
//                 clears them all.
//
// The P register is always clocked (with ce_p); PREG only selects whether P
// leaves the slice registered or combinational, as UG479 describes.
// Written so Vivado maps the multiplier and registers to a DSP48E1.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module dsp_core (
    input  wire               clk,
    input  wire               gce,
    input  wire               gsr,
    input  wire               gwe,

    input  wire [1:0]         opmode,
    input  wire               use_d,
    input  wire               d_sub,
    input  wire               areg,
    input  wire               breg,
    input  wire               creg,
    input  wire               dreg,
    input  wire               mreg,
    input  wire               preg,

    input  wire signed [24:0] a,
    input  wire signed [17:0] b,
    input  wire signed [47:0] c,
    input  wire signed [24:0] d,

    input  wire               ce_ad,
    input  wire               ce_b,
    input  wire               ce_m,
    input  wire               ce_p,
    input  wire               rst_ad,
    input  wire               rst_b,
    input  wire               rst_m,
    input  wire               rst_p,

    input  wire signed [47:0] pcin,
    output wire signed [47:0] p
);

    wire en = gwe & gce;

    reg signed [24:0] a_q = 25'sd0;
    reg signed [24:0] d_q = 25'sd0;
    reg signed [17:0] b_q = 18'sd0;
    reg signed [47:0] c_q = 48'sd0;
    reg signed [42:0] m_q = 43'sd0;
    reg signed [47:0] p_q = 48'sd0;

    wire signed [24:0] a_v = areg ? a_q : a;
    wire signed [24:0] d_v = dreg ? d_q : d;
    wire signed [17:0] b_v = breg ? b_q : b;
    wire signed [47:0] c_v = creg ? c_q : c;

    wire signed [24:0] ad  = use_d ? (d_sub ? (d_v - a_v) : (d_v + a_v)) : a_v;
    (* use_dsp = "yes" *)
    wire signed [42:0] m_c = ad * b_v;
    wire signed [42:0] m_v = mreg ? m_q : m_c;
    wire signed [47:0] m_x = {{5{m_v[42]}}, m_v};

    reg signed [47:0] p_c;
    always @(*) begin
        case (opmode)
            2'd0:    p_c = m_x;
            2'd1:    p_c = m_x + c_v;
            2'd2:    p_c = p_q + m_x;
            default: p_c = (pcin >>> 17) + m_x;
        endcase
    end

    always @(posedge clk) begin
        if (gsr) begin
            a_q <= 25'sd0; d_q <= 25'sd0; b_q <= 18'sd0;
            c_q <= 48'sd0; m_q <= 43'sd0; p_q <= 48'sd0;
        end else if (en) begin
            if (rst_ad)     begin a_q <= 25'sd0; d_q <= 25'sd0; end
            else if (ce_ad) begin a_q <= a;      d_q <= d;      end
            if (rst_b)      b_q <= 18'sd0;
            else if (ce_b)  b_q <= b;
            if (rst_p)      c_q <= 48'sd0;
            else if (ce_p)  c_q <= c;
            if (rst_m)      m_q <= 43'sd0;
            else if (ce_m)  m_q <= m_c;
            if (rst_p)      p_q <= 48'sd0;
            else if (ce_p)  p_q <= p_c;
        end
    end

    assign p = preg ? p_q : p_c;

endmodule

`default_nettype wire
