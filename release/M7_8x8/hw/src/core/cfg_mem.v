// -----------------------------------------------------------------------------
// cfg_mem.v - the configuration memory: NTILE cfg_tile_sr cells in one chain
//
// The fabric only ever sees the flat `cfg` bus, laid out exactly as before
// (tile i at [i*TILE_W +: TILE_W]). How that bus is written - this scan chain,
// or frames at M13 - is this module's business alone; it is the one module the
// frame-based controller replaces.
//
// Chain: TDI -> tile NTILE-1 MSB ... tile NTILE-1 sr[0] -> tile NTILE-2 MSB ...
//        tile 0 sr[0] -> so. So chain bit k is the k-th bit shifted in, which is
//        bit k of the flat bus. See docs/bitstream-format.md section 4.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module cfg_mem #(
    parameter integer NTILE  = 4,
    parameter integer TILE_W = 16
)(
    input  wire                      tck,
    input  wire                      capture,
    input  wire                      shift,
    input  wire                      commit,
    input  wire                      clear,
    input  wire                      si,
    output wire                      so,
    output wire [NTILE*TILE_W-1:0]   cfg
);

    wire [NTILE:0] link;
    assign link[NTILE] = si;
    assign so          = link[0];

    genvar i;
    generate
        for (i = 0; i < NTILE; i = i + 1) begin : g_tile
            cfg_tile_sr #(.W(TILE_W)) u_tile (
                .tck     (tck),
                .capture (capture),
                .shift   (shift),
                .commit  (commit),
                .clear   (clear),
                .si      (link[i+1]),
                .so      (link[i]),
                .cfg     (cfg[i*TILE_W +: TILE_W])
            );
        end
    endgenerate

endmodule

`default_nettype wire
