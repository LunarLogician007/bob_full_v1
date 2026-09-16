// -----------------------------------------------------------------------------
// tile.v - one fabric tile: a CLB, a connection box and a switch box
//
// The tile config word is defined by tools/bob/device.py (bob_params.vh) and
// laid out as
//
//     CLB    LUT INIT (2**K) and the flop/carry control bits      (71 for K=6)
//     CB     K LUT-input muxes + CE mux + SR mux, SELW bits each  (40 for K=6)
//     SB     16 outgoing-track muxes, SELW bits each              (80)
//
// Every mux in the tile chooses from the same 20-entry source bus:
//
//     0        const 0
//     1        const 1
//     2        this tile's CLB o
//     3        this tile's CLB o5        <- feedback, no routing needed
//     4..7     tracks arriving from the North
//     8..11    tracks arriving from the East
//     12..15   tracks arriving from the South
//     16..19   tracks arriving from the West
//
// A tile can therefore feed its own LUT (or its own CE/SR) from its own
// output, which is what makes a single tile able to hold a registered loop.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module tile (
    input  wire                        clk,
    input  wire                        gce,
    input  wire                        gsr,
    input  wire                        gwe,
    input  wire                        cin,

    input  wire [`BOB_TILE_CFG_W-1:0]  cfg,

    input  wire [`BOB_NTRACK-1:0]      in_n,
    input  wire [`BOB_NTRACK-1:0]      in_e,
    input  wire [`BOB_NTRACK-1:0]      in_s,
    input  wire [`BOB_NTRACK-1:0]      in_w,

    output wire [`BOB_NTRACK-1:0]      out_n,
    output wire [`BOB_NTRACK-1:0]      out_e,
    output wire [`BOB_NTRACK-1:0]      out_s,
    output wire [`BOB_NTRACK-1:0]      out_w,

    output wire                        clb_o,
    output wire                        clb_o5,
    output wire                        cout
);

    localparam integer NTRACK = `BOB_NTRACK;
    localparam integer SELW   = `BOB_SELW;
    localparam integer NSRC   = `BOB_NSRC;
    localparam integer K      = `BOB_LUT_K;
    localparam integer CB_N   = `BOB_CB_N;
    localparam integer CLB_W  = `BOB_CLB_CFG_W;
    localparam integer CB_W   = `BOB_CB_CFG_W;
    localparam integer SB_W   = `BOB_SB_CFG_W;

    localparam integer CB_LO = CLB_W;
    localparam integer SB_LO = CLB_W + CB_W;

    // The shared source bus, in clb_pkg.sv's order.
    wire [NSRC-1:0] src = {in_w, in_s, in_e, in_n, clb_o5, clb_o, 1'b1, 1'b0};

    // --- connection box: K LUT inputs, then CE, then SR -------------------
    wire [CB_N-1:0] cb_o;
    mux_bank #(.N(CB_N), .SELW(SELW), .NSRC(NSRC)) u_cb (
        .cfg (cfg[CB_LO +: CB_W]),
        .src (src),
        .o   (cb_o)
    );

    wire [K-1:0] lut_i = cb_o[K-1:0];
    wire         ce_l  = cb_o[K];
    wire         sr_l  = cb_o[K+1];

    // --- switch box: the sixteen outgoing tracks -------------------------
    // index = dir*NTRACK + track, with dir N=0, E=1, S=2, W=3
    wire [4*NTRACK-1:0] sb_o;
    mux_bank #(.N(4*NTRACK), .SELW(SELW), .NSRC(NSRC)) u_sb (
        .cfg (cfg[SB_LO +: SB_W]),
        .src (src),
        .o   (sb_o)
    );

    assign out_n = sb_o[0*NTRACK +: NTRACK];
    assign out_e = sb_o[1*NTRACK +: NTRACK];
    assign out_s = sb_o[2*NTRACK +: NTRACK];
    assign out_w = sb_o[3*NTRACK +: NTRACK];

    // --- the logic block -------------------------------------------------
    clb u_clb (
        .clk  (clk),
        .gce  (gce),
        .ce   (ce_l),
        .sr   (sr_l),
        .gsr  (gsr),
        .gwe  (gwe),
        .i    (lut_i),
        .cin  (cin),
        .cfg  (cfg[0 +: CLB_W]),
        .o    (clb_o),
        .o5   (clb_o5),
        .cout (cout)
    );

endmodule

`default_nettype wire
