// -----------------------------------------------------------------------------
// tile.v - one fabric tile: a CLB, a connection box and a switch box
//
// The 181-bit tile config word is defined by clb_pkg.sv and laid out as
//
//     [70:0]     CLB    LUT INIT and the flop/carry control bits
//     [100:71]   CB     6 LUT-input muxes, 5 bits each
//     [180:101]  SB     16 outgoing-track muxes, 5 bits each
//
// Every mux in the tile chooses from the same 20-entry source bus, in the
// order clb_pkg.sv fixes:
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
// A tile can therefore feed its own LUT from its own output, which is what
// makes a single tile able to hold a registered feedback loop.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module tile #(
    parameter integer NTRACK = 4,
    parameter integer SELW   = 5,
    parameter integer NSRC   = 20,
    parameter integer CLB_W  = 71,
    parameter integer CB_W   = 30,
    parameter integer SB_W   = 80
)(
    input  wire                    clk,
    input  wire                    ce,
    input  wire                    sr,
    input  wire                    gsr,
    input  wire                    gwe,
    input  wire                    cin,

    input  wire [CLB_W+CB_W+SB_W-1:0] cfg,

    input  wire [NTRACK-1:0]       in_n,
    input  wire [NTRACK-1:0]       in_e,
    input  wire [NTRACK-1:0]       in_s,
    input  wire [NTRACK-1:0]       in_w,

    output wire [NTRACK-1:0]       out_n,
    output wire [NTRACK-1:0]       out_e,
    output wire [NTRACK-1:0]       out_s,
    output wire [NTRACK-1:0]       out_w,

    output wire                    clb_o,
    output wire                    clb_o5,
    output wire                    cout
);

    localparam integer CB_LO = CLB_W;
    localparam integer SB_LO = CLB_W + CB_W;

    // The shared source bus, in clb_pkg.sv's order.
    wire [NSRC-1:0] src = {in_w, in_s, in_e, in_n, clb_o5, clb_o, 1'b1, 1'b0};

    // --- connection box: the six LUT inputs ------------------------------
    wire [5:0] lut_i;
    mux_bank #(.N(6), .SELW(SELW), .NSRC(NSRC)) u_cb (
        .cfg (cfg[CB_LO +: CB_W]),
        .src (src),
        .o   (lut_i)
    );

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
        .ce   (ce),
        .sr   (sr),
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
