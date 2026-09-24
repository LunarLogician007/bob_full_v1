// -----------------------------------------------------------------------------
// bob_mux.v - one routing multiplexer of the generated fabric (M7)
//
// software/bob/fabric_gen.py instantiates one per routing-resource-graph node that
// VPR's edges drive (OpenFPGA builds its routing the same way). The select comes
// straight from the configuration chain:
//
//   sel 0              const 0     <- an all-zero chain is a dark, loop-free fabric
//   sel 1   (C1 = 1)   const 1     (connection-box muxes on block input pins)
//   sel BASE + i       in[i]       BASE = 1 + C1
//   anything larger    const 0
//
// M23: built from primitives instead of left to synthesis (Vivado made ~0.8 yosys LUT of each
// of M22's muxes, 18.5k LUTs for routing alone). The table below is cut into 4-entry leaves,
// each a LUT6 4:1 mux on sel[1:0] (the constants are tied inputs, which opt_design folds into
// the INIT); two leaves meet in a MUXF7 on sel[2] and two of those in a MUXF8 on sel[3], so a
// 16:1 mux is one slice (UG474, "Multiplexers"). Wider muxes pick among the 16:1 groups on
// sel[W-1:4] in ordinary logic. The value mapping is unchanged.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module bob_mux #(
    parameter integer N  = 2,      // inputs
    parameter integer W  = 2,      // select bits: 2**W >= N + 1 + C1
    parameter integer C1 = 0       // 1: value 1 selects const 1
)(
    input  wire [W-1:0] sel,
    input  wire [N-1:0] in,
    output wire         o
);

    // One spare bit on top, so the zero padding is never a zero replication.
    wire [(1<<W):0] tab;

    generate
        if (C1 != 0) begin : g_c1
            assign tab = {{((1<<W) + 1 - N - 2){1'b0}}, in, 1'b1, 1'b0};
        end else begin : g_c0
            assign tab = {{((1<<W) + 1 - N - 1){1'b0}}, in, 1'b0};
        end
    endgenerate

    localparam integer NV = N + 1 + C1;            // table entries that matter
    localparam integer L  = (NV + 3) / 4;          // LUT6 leaves
    localparam integer G  = (L + 3) / 4;           // 16:1 groups (MUXF8)
    localparam integer SW = (W > 4) ? W : 4;

    wire [4*L+(1<<W):0] tp = {{(4*L){1'b0}}, tab};
    wire [SW-1:0] s = {{(SW-W){1'b0}}, sel};

    wire [4*G-1:0] leaf;
    wire [2*G-1:0] f7;
    wire [G-1:0]   f8;

    genvar j;
    generate
        for (j = 0; j < 4 * G; j = j + 1) begin : g_leaf
            if (j < L) begin : g_lut
                // O = I[{I5,I4}] of I0..I3
                LUT6 #(.INIT(64'hFF00F0F0CCCCAAAA)) u (
                    .O(leaf[j]), .I0(tp[4*j]), .I1(tp[4*j+1]), .I2(tp[4*j+2]), .I3(tp[4*j+3]),
                    .I4(s[0]), .I5(s[1]));
            end else begin : g_none
                assign leaf[j] = 1'b0;
            end
        end
        if (L == 1) begin : g_l1
            assign o = leaf[0] & ~|s[SW-1:2];
            assign f7 = 2'b0;
            assign f8 = 1'b0;
        end else begin : g_tree
            for (j = 0; j < 2 * G; j = j + 1) begin : g_f7
                MUXF7 u (.O(f7[j]), .I0(leaf[2*j]), .I1(leaf[2*j+1]), .S(s[2]));
            end
            if (L == 2) begin : g_l2
                assign f8 = 1'b0;
                assign o = f7[0] & ~|s[SW-1:3];
            end else begin : g_f8s
                for (j = 0; j < G; j = j + 1) begin : g_f8
                    MUXF8 u (.O(f8[j]), .I0(f7[2*j]), .I1(f7[2*j+1]), .S(s[3]));
                end
                if (SW == 4) begin : g_l4
                    assign o = f8[0];
                end else begin : g_top
                    wire [(1<<(SW-4))-1:0] top = {{((1<<(SW-4))-G){1'b0}}, f8};
                    assign o = top[s[SW-1:4]];
                end
            end
        end
    endgenerate

    /* verilator lint_off UNUSEDSIGNAL */
    wire _unused = &{1'b0, tp[4*L+(1<<W):4*L], leaf, f7, f8};
    /* verilator lint_on UNUSEDSIGNAL */

endmodule

`default_nettype wire
