// -----------------------------------------------------------------------------
// lxpair.v - two crossbar multiplexers of the cluster over one set of sources (M23)
//
// M22's lxmux.v made each crossbar mux a CFGLUT5 tree: ceil(S/5) leaves and a CFGLUT5 root,
// 6 per mux and 152 per CLB, which filled 84% of the SLICEMs at 81 CLBs (the four LUTs of a
// SLICEM share one shift enable, so they only take CFGLUT5s of one CLB). Here two muxes, a and
// b, share their leaves. With I4 tied high a CFGLUT5 is two 4-input tables over the same
// inputs (UG953): O5 reads bits 15:0 and O6 bits 31:16. In a full crossbar every mux of the
// CLB sees the same sources, so leaf g over in[4g +: 4] serves mux a from its low half and
// mux b from its high half: ceil(S/4) CFGLUT5s for two muxes (6 for S = 24, 80 per CLB).
//
// The root is no longer a table. An unselected leaf holds zeros, so each mux output is the
// fixed OR of its leaves, one plain LUT6 (SLICEL). To pass source v (select 2 + v) leaf v / 4
// holds "output = address bit v % 4" in that mux's half and every other leaf zeros; const1 is
// an all-ones half in leaf 0, const0 all zeros, so an unloaded pair reads 0 (a dark fabric).
// The contents come from the compact 5-bit selects at load time (lut_expand.v), so the
// bitstream keeps its meaning.
//
//   lcdi[g]  leaf g's shift data: the first 16 bits shifted in are mux b's half (31:16)
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module lxpair #(
    parameter integer S = 24,                       // sources (excluding const0 / const1), <= 24
    parameter integer L = (S + 3) / 4               // leaves (CFGLUT5s)
)(
    input  wire [S-1:0] in,
    input  wire         lck,
    input  wire         lce,
    input  wire [L-1:0] lcdi,
    output wire         oa,
    output wire         ob
);

    wire [4*L-1:0] pin;
    generate
        if (4 * L > S) begin : g_pad
            assign pin = {{(4 * L - S){1'b0}}, in};
        end else begin : g_nopad
            assign pin = in;
        end
    endgenerate

    wire [L-1:0] la, lb;
    /* verilator lint_off PINCONNECTEMPTY */
    genvar g;
    generate
        for (g = 0; g < L; g = g + 1) begin : g_leaf
            CFGLUT5 u (.CDO(), .O5(la[g]), .O6(lb[g]), .I4(1'b1), .I3(pin[4*g+3]), .I2(pin[4*g+2]),
                       .I1(pin[4*g+1]), .I0(pin[4*g]), .CDI(lcdi[g]), .CE(lce), .CLK(lck));
        end
    endgenerate
    /* verilator lint_on PINCONNECTEMPTY */

    assign oa = |la;
    assign ob = |lb;

    initial begin
        if (L > 6) begin
            $display("lxpair: S = %0d > 24 needs a root wider than one LUT6", S);
            $finish;
        end
    end

endmodule

`default_nettype wire
