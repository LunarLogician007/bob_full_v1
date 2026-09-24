// -----------------------------------------------------------------------------
// lxor.v - one crossbar multiplexer of the cluster: CFGLUT5 leaves, a fixed OR root (M23)
//
// M22's lxmux.v made each crossbar mux a CFGLUT5 tree: ceil(S/5) leaves and a CFGLUT5 root,
// 6 per mux and 152 per CLB, which filled 84% of the SLICEMs at 81 CLBs (the four LUTs of a
// SLICEM share one shift enable, so they only take CFGLUT5s of one CLB). The root needs no
// table: an unselected leaf holds zeros, so the mux output is the OR of its leaves, a plain
// LUT (SLICEL). 5 CFGLUT5 per mux, 128 per CLB.
//
// Each leaf uses O6 only. A CFGLUT5 that also drives O5 (two 4-input tables, UG953) looked
// cheaper still, but Vivado maps it to an SRL16E + SRLC32E pair, two LUT sites, where a
// single-output CFGLUT5 is one SRLC32E (the first M23 build: weighted LUTRAM > 100%).
//
// To pass source v (select 2 + v) leaf v / 5 holds "output = address bit v % 5" and every
// other leaf zeros; const1 is an all-ones leaf 0, const0 all zeros, so an unloaded mux reads
// 0 (a dark fabric). The contents come from the compact 5-bit select at load time
// (lut_expand.v), so the bitstream keeps its meaning.
//
//   lcdi[g]  leaf g's shift data
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module lxor #(
    parameter integer S = 24,                       // sources (excluding const0 / const1)
    parameter integer L = (S + 4) / 5               // leaves (CFGLUT5s), at most 6: one LUT6 root
)(
    input  wire [S-1:0] in,
    input  wire         lck,
    input  wire         lce,
    input  wire [L-1:0] lcdi,
    output wire         o
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
    endgenerate
    /* verilator lint_on PINCONNECTEMPTY */

    assign o = |leaf;

    initial begin
        if (L > 6) begin
            $display("lxor: S = %0d > 30 needs a root wider than one LUT6", S);
            $finish;
        end
    end

endmodule

`default_nettype wire
