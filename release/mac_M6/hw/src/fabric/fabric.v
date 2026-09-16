// -----------------------------------------------------------------------------
// fabric.v - a GRID_R x GRID_C mesh of tiles
//
// Coordinates: r increases to the North, c increases to the East. Tile index is
// idx = r*GRID_C + c, and that is also the order tiles appear in the fabric
// config bus - tile 0 occupies bits [TILE_W-1:0], tile 1 the next TILE_W, ...
//
// Tracks are point to point between neighbours. A track leaving a tile to the
// East arrives at its eastern neighbour as that tile's West input:
//
//     tile(r,c).in_n = tile(r+1,c).out_s        tile(r,c).in_s = tile(r-1,c).out_n
//     tile(r,c).in_e = tile(r,c+1).out_w        tile(r,c).in_w = tile(r,c-1).out_e
//
// At the four borders those inputs come from the edge ports instead, and the
// outgoing edge tracks are exposed the same way.
//
// The carry chain runs South to North up each column, so a column of four tiles
// is a four-bit adder (or counter). cin of the bottom row is the global carry in.
//
// M4: every flop is on one global clock `clk` (the board's sysclk) and changes
// only where the global enable `gce` allows; CE and SR are routed inside each
// tile. Sizes come from bob_params.vh (tools/bob/device.py).
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module fabric #(
    parameter integer GRID_R  = `BOB_GRID_R,
    parameter integer GRID_C  = `BOB_GRID_C,
    parameter integer NTRACK  = `BOB_NTRACK,
    parameter integer TILE_W  = `BOB_TILE_CFG_W
)(
    input  wire clk,
    input  wire gce,        // global clock enable (user clock)
    input  wire gsr,        // startup: flip-flops to INIT
    input  wire gwe,        // startup: flip-flop write enable
    input  wire cin,

    input  wire [GRID_R*GRID_C*TILE_W-1:0] cfg,

    // Edge tracks, indexed by row for the E/W edges and by column for N/S.
    input  wire [GRID_R*NTRACK-1:0] west_in,
    input  wire [GRID_R*NTRACK-1:0] east_in,
    input  wire [GRID_C*NTRACK-1:0] south_in,
    input  wire [GRID_C*NTRACK-1:0] north_in,

    output wire [GRID_R*NTRACK-1:0] west_out,
    output wire [GRID_R*NTRACK-1:0] east_out,
    output wire [GRID_C*NTRACK-1:0] south_out,
    output wire [GRID_C*NTRACK-1:0] north_out,

    // Every CLB output, so a testbench (or a status register) can see inside.
    output wire [GRID_R*GRID_C-1:0] clb_o,
    output wire [GRID_R*GRID_C-1:0] clb_o5,
    output wire [GRID_C-1:0]        carry_out   // top of each column's chain
);

    localparam integer NTILE = GRID_R * GRID_C;

    wire [NTRACK-1:0] o_n [0:NTILE-1];
    wire [NTRACK-1:0] o_e [0:NTILE-1];
    wire [NTRACK-1:0] o_s [0:NTILE-1];
    wire [NTRACK-1:0] o_w [0:NTILE-1];

    wire [NTRACK-1:0] i_n [0:NTILE-1];
    wire [NTRACK-1:0] i_e [0:NTILE-1];
    wire [NTRACK-1:0] i_s [0:NTILE-1];
    wire [NTRACK-1:0] i_w [0:NTILE-1];

    wire              cy  [0:NTILE-1];

    genvar r, c;
    generate
        for (r = 0; r < GRID_R; r = r + 1) begin : g_row
            for (c = 0; c < GRID_C; c = c + 1) begin : g_col

                localparam integer IDX = r*GRID_C + c;

                // --- neighbour or edge, per side -------------------------
                if (r == GRID_R-1) begin : g_n_edge
                    assign i_n[IDX] = north_in[c*NTRACK +: NTRACK];
                end else begin : g_n_tile
                    assign i_n[IDX] = o_s[(r+1)*GRID_C + c];
                end

                if (r == 0) begin : g_s_edge
                    assign i_s[IDX] = south_in[c*NTRACK +: NTRACK];
                end else begin : g_s_tile
                    assign i_s[IDX] = o_n[(r-1)*GRID_C + c];
                end

                if (c == GRID_C-1) begin : g_e_edge
                    assign i_e[IDX] = east_in[r*NTRACK +: NTRACK];
                end else begin : g_e_tile
                    assign i_e[IDX] = o_w[r*GRID_C + (c+1)];
                end

                if (c == 0) begin : g_w_edge
                    assign i_w[IDX] = west_in[r*NTRACK +: NTRACK];
                end else begin : g_w_tile
                    assign i_w[IDX] = o_e[r*GRID_C + (c-1)];
                end

                // --- carry chain, South to North up the column -----------
                wire tile_cin;
                if (r == 0) begin : g_cy_base
                    assign tile_cin = cin;
                end else begin : g_cy_link
                    assign tile_cin = cy[(r-1)*GRID_C + c];
                end

                tile u_tile (
                    .clk    (clk),
                    .gce    (gce),
                    .gsr    (gsr),
                    .gwe    (gwe),
                    .cin    (tile_cin),
                    .cfg    (cfg[IDX*TILE_W +: TILE_W]),
                    .in_n   (i_n[IDX]),
                    .in_e   (i_e[IDX]),
                    .in_s   (i_s[IDX]),
                    .in_w   (i_w[IDX]),
                    .out_n  (o_n[IDX]),
                    .out_e  (o_e[IDX]),
                    .out_s  (o_s[IDX]),
                    .out_w  (o_w[IDX]),
                    .clb_o  (clb_o[IDX]),
                    .clb_o5 (clb_o5[IDX]),
                    .cout   (cy[IDX])
                );
            end
        end

        // --- edge outputs ----------------------------------------------
        for (r = 0; r < GRID_R; r = r + 1) begin : g_ew_out
            assign west_out[r*NTRACK +: NTRACK] = o_w[r*GRID_C + 0];
            assign east_out[r*NTRACK +: NTRACK] = o_e[r*GRID_C + (GRID_C-1)];
        end
        for (c = 0; c < GRID_C; c = c + 1) begin : g_ns_out
            assign south_out[c*NTRACK +: NTRACK] = o_s[0*GRID_C + c];
            assign north_out[c*NTRACK +: NTRACK] = o_n[(GRID_R-1)*GRID_C + c];
            assign carry_out[c] = cy[(GRID_R-1)*GRID_C + c];
        end
    endgenerate

endmodule

`default_nettype wire
