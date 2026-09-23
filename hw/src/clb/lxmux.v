// -----------------------------------------------------------------------------
// lxmux.v - one crossbar multiplexer of the cluster as a tree of CFGLUT5 (M22)
//
// M21's crossbar mux was bob_mux: S inputs picked by a 5-bit select held in configuration
// flip-flops (~7 host LUTs + 5 FFs). Here the choice is the truth tables' contents
// (ZUMA-style): ceil(S/5) leaf CFGLUT5s over in[5g +: 5] and, when there is more than one
// leaf, a root CFGLUT5 over the leaf outputs. To pass source v (select 2 + v) the leaf
// v / 5 holds "output = address bit v % 5" and the root "address bit v / 5"; const1 is an
// all-ones root (or leaf), const0 all zeros, so an unloaded mux reads 0 (a dark fabric).
// The contents are expanded from the compact 5-bit select at load time (lut_expand.v), so
// the bitstream keeps its M21 meaning.
//
//   lcdi[g]  leaf g's shift data (g < L), lcdi[L] the root's (when L > 1)
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module lxmux #(
    parameter integer S = 24,                       // sources (excluding const0 / const1), <= 25
    parameter integer L = (S + 4) / 5,              // leaves
    parameter integer NL = (L > 1) ? L + 1 : 1      // CFGLUT5s
)(
    input  wire [S-1:0]  in,
    input  wire          lck,
    input  wire          lce,
    input  wire [NL-1:0] lcdi,
    output wire          o
);

    wire [5*L-1:0] pin;
    generate
        if (5 * L > S) begin : g_pad
            assign pin = {{(5 * L - S){1'b0}}, in};
        end else begin : g_nopad
            assign pin = in;
        end
    endgenerate

    wire [L-1:0] leaf;
    /* verilator lint_off PINCONNECTEMPTY */
    genvar g;
    generate
        for (g = 0; g < L; g = g + 1) begin : g_leaf
            CFGLUT5 u (.CDO(), .O5(), .O6(leaf[g]), .I4(pin[5*g+4]), .I3(pin[5*g+3]), .I2(pin[5*g+2]),
                       .I1(pin[5*g+1]), .I0(pin[5*g]), .CDI(lcdi[g]), .CE(lce), .CLK(lck));
        end
        if (L > 1) begin : g_root
            wire [4:0] r;
            if (L < 5) begin : g_rpad
                assign r = {{(5 - L){1'b0}}, leaf};
            end else begin : g_rfull
                assign r = leaf;
            end
            CFGLUT5 u (.CDO(), .O5(), .O6(o), .I4(r[4]), .I3(r[3]), .I2(r[2]), .I1(r[1]), .I0(r[0]),
                       .CDI(lcdi[L]), .CE(lce), .CLK(lck));
        end else begin : g_one
            assign o = leaf[0];
        end
    endgenerate
    /* verilator lint_on PINCONNECTEMPTY */

    initial begin
        if (S > 25) begin
            $display("lxmux: S = %0d > 25 needs a third level", S);
            $finish;
        end
    end

endmodule

`default_nettype wire
