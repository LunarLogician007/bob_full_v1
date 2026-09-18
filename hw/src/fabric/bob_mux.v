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

    assign o = tab[{1'b0, sel}];

    /* verilator lint_off UNUSEDSIGNAL */
    wire _unused = tab[1<<W];
    /* verilator lint_on UNUSEDSIGNAL */

endmodule

`default_nettype wire
