// -----------------------------------------------------------------------------
// cfg_store.v - the configuration memory with two write paths (M13)
//
// The memory the fabric reads (`cfg`) is NFRAMES frames of FB bits (docs/
// bitstream-format.md section 9). There is one shift register `sr` beside it, and
// every write reaches `cfg` from `sr`, so each memory bit is a plain clock-enabled
// flop with no data mux:
//
//   chain   (CHAIN_IN / CHAIN_OUT) - cfg_tile_sr's proven protocol:
//             posedge  capture   sr  <= cfg
//             posedge  shift     sr  <= {si, sr[W-1:1]}
//             negedge  commit    cfg <= sr                       (all frames)
//   frames  (CFG_IN, cfg_frames.v):
//             posedge  load      sr[frame load_idx] <= load_data  (the 4th FDRI word)
//             negedge  frame_we  cfg[frame frame_idx] <= sr[frame frame_idx]
//
//   negedge  clear (JPROGRAM) wins over both.
//
// `sr` is don't-care outside a CHAIN scan (Capture-DR reloads it from cfg), so using
// it as the frame buffer costs nothing. load / load_idx / load_data are decoded by
// cfg_frames from its state and TDI and taken on the same rising edge; frame_we /
// frame_idx are registered on that edge and taken on the following falling edge.
// The chain and frame strobes come from different instructions, never both active.
//
// History: the first M13 version wrote `cfg[frame_idx*FB +: FB] <= frame_data`
// over the whole memory; that synthesised as a shifter (~12k LUTs, 1.7 GB in yosys)
// and Vivado ran out of memory. A per-bit 3:1 data mux (second version) still cost
// ~5k LUT3; this one costs no LUT per memory bit.
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
    input  wire              load,
    input  wire [FIDX_W-1:0] load_idx,
    input  wire [FB-1:0]     load_data,
    input  wire              frame_we,
    input  wire [FIDX_W-1:0] frame_idx,

    output reg  [W-1:0]      cfg
);

    reg [W-1:0] sr = {W{1'b0}};

    genvar f;
    generate
        for (f = 0; f < NFRAMES; f = f + 1) begin : g_frame
            wire top = (f == NFRAMES - 1) ? si : sr[(f+1)*FB];      // the bit shifting into this frame
            wire ld  = load     && (load_idx  == f[FIDX_W-1:0]);
            wire we  = frame_we && (frame_idx == f[FIDX_W-1:0]);

            always @(posedge tck) begin
                if (capture)
                    sr[f*FB +: FB] <= cfg[f*FB +: FB];
                else if (shift)
                    sr[f*FB +: FB] <= {top, sr[f*FB+1 +: FB-1]};
                else if (ld)
                    sr[f*FB +: FB] <= load_data;
            end

            always @(negedge tck) begin
                if (clear)
                    cfg[f*FB +: FB] <= {FB{1'b0}};
                else if (commit || we)
                    cfg[f*FB +: FB] <= sr[f*FB +: FB];
            end
        end
    endgenerate

    assign so = sr[0];

    initial cfg = {W{1'b0}};

endmodule

`default_nettype wire
