// -----------------------------------------------------------------------------
// cfg_store.v - the configuration memory with two write paths (M13)
//
// The memory the fabric reads (`cfg`) is NFRAMES frames of FB bits (docs/
// bitstream-format.md section 9). It is written two ways:
//
//   chain   (CHAIN_IN / CHAIN_OUT) - cfg_tile_sr's proven protocol, whole memory:
//             posedge  capture   sr  <= cfg
//             posedge  shift     sr  <= {si, sr[W-1:1]}
//             negedge  commit    cfg <= sr
//   frames  (CFG_IN, cfg_frames.v) - one frame at a time:
//             negedge  frame_we  cfg[frame_idx*FB +: FB] <= frame_data
//
//   negedge  clear (JPROGRAM) wins over both.
//
// frame_we / frame_idx / frame_data are registered by cfg_frames on the rising edge
// and held for the whole cycle, so the falling edge takes them cleanly. The chain
// and frame strobes come from different instructions and are never both active.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module cfg_store #(
    parameter integer FB      = 128,
    parameter integer NFRAMES = 4,
    parameter integer FIDX_W  = 8,
    parameter integer W       = FB * NFRAMES
)(
    input  wire              tck,
    // chain
    input  wire              capture,
    input  wire              shift,
    input  wire              commit,
    input  wire              clear,
    input  wire              si,
    output wire              so,
    // frames
    input  wire              frame_we,
    input  wire [FIDX_W-1:0] frame_idx,
    input  wire [FB-1:0]     frame_data,

    output reg  [W-1:0]      cfg
);

    reg [W-1:0] sr = {W{1'b0}};

    always @(posedge tck) begin
        if (capture)
            sr <= cfg;
        else if (shift)
            sr <= {si, sr[W-1:1]};
    end

    always @(negedge tck) begin
        if (clear)
            cfg <= {W{1'b0}};
        else if (commit)
            cfg <= sr;
        else if (frame_we && ({{(32-FIDX_W){1'b0}}, frame_idx} < NFRAMES))
            cfg[frame_idx*FB +: FB] <= frame_data;
    end

    assign so = sr[0];

    initial cfg = {W{1'b0}};

endmodule

`default_nettype wire
