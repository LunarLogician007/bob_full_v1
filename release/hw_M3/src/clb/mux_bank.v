// -----------------------------------------------------------------------------
// mux_bank.v - N configurable multiplexers sharing one source bus
//
// Both routing structures in a tile are the same thing with a different N:
//
//   connection box   N = 6    picks the six LUT inputs
//   switch box       N = 16   picks the four outgoing tracks on each of 4 edges
//
// Each mux has its own SELW-bit select field, packed little-end first, which is
// the layout clb_pkg.sv's mk_cb_cfg / sb_set produce.
//
// The source bus is padded to 32 so an out-of-range select - which a malformed
// bitstream can produce, since SELW=5 addresses 32 but only 20 sources exist -
// reads a hard zero instead of an X.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module mux_bank #(
    parameter integer N    = 6,
    parameter integer SELW = 5,
    parameter integer NSRC = 20
)(
    input  wire [N*SELW-1:0] cfg,
    input  wire [NSRC-1:0]   src,
    output wire [N-1:0]      o
);

    wire [31:0] src_padded = {{(32-NSRC){1'b0}}, src};

    genvar k;
    generate
        for (k = 0; k < N; k = k + 1) begin : g_mux
            assign o[k] = src_padded[cfg[k*SELW +: SELW]];
        end
    endgenerate

endmodule

`default_nettype wire
