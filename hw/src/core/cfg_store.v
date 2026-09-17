// -----------------------------------------------------------------------------
// cfg_store.v - the configuration memory with two write paths (M13, M12b)
//
// The memory the fabric reads (`cfg`) is NFRAMES frames of FB bits (docs/
// bitstream-format.md section 9). Beside it there is ONE frame buffer `buf_q`
// (FB bits), and every write reaches `cfg` from it, so each memory bit is a plain
// clock-enabled flop with no data mux:
//
//   chain in  (CHAIN_IN, M12b streaming): bits shift into the buffer LSB first;
//             every FB-th bit completes frame n, which is written to cfg on the
//             next falling edge (only while `wen`, i.e. GWE = 0), n = 0, 1, ...
//   chain out (CHAIN_OUT): Capture-DR loads frame 0; every FB-th shift reloads
//             the next frame; after the last frame the buffer is a plain FB-bit
//             delay line from TDI. Non-destructive, never writes.
//   frames    (CFG_IN, cfg_frames.v):
//             posedge  load      buf_q <= load_data             (the 4th FDRI word)
//             negedge  frame_we  cfg[frame frame_idx] <= buf_q
//
//   negedge  clear (JPROGRAM) wins over everything.
//
// `rd_frame` is one frame-wide read mux over the memory, shared by CHAIN_OUT and
// cfg_frames' FDRO (different instructions, never active together).
//
// History:
//   M13 v1 wrote cfg[frame_idx*FB +: FB] <= frame_data over the whole memory: a
//          shifter (~12k LUTs, 1.7 GB in yosys); Vivado ran out of memory.
//   M13    kept cfg_tile_sr's full W-bit shift register beside the memory (commit
//          at Update-DR after the CRC): W FFs + W LUTs, 5.1k LUT / 10k FF in all.
//   M12b   streams the chain frame by frame through the one buffer, like the frame
//          path (UG470: frames are written as they arrive, the CRC gates START):
//          about W LUTs and W FFs less. A bad chain CRC now leaves the new bits in
//          memory but COMMITTED stays 0, so startup is refused (as for frames).
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
    input  wire              chain_in,       // CHAIN_IN selected
    input  wire              chain_out,      // CHAIN_OUT selected
    input  wire              capture,        // Capture-DR (with either chain instruction)
    input  wire              shift,          // Shift-DR   (with either chain instruction)
    input  wire              wen,            // chain writes allowed (GWE = 0)
    input  wire              clear,
    input  wire              si,
    output wire              so,
    // frames
    input  wire              load,
    input  wire [FB-1:0]     load_data,
    input  wire              frame_we,
    input  wire [FIDX_W-1:0] frame_idx,
    // FDRO read select (cfg_frames); CHAIN_OUT overrides while selected
    input  wire [FIDX_W-1:0] fdro_idx,
    output wire [FB-1:0]     rd_frame,

    output reg  [W-1:0]      cfg
);

    localparam integer CNT_W = $clog2(FB);

    reg [FB-1:0]     buf_q  = {FB{1'b0}};
    reg [CNT_W-1:0]  cnt    = {CNT_W{1'b0}};
    reg [FIDX_W-1:0] idx    = {FIDX_W{1'b0}};     // chain frame being shifted
    reg              cwe    = 1'b0;               // chain: write frame cidx on the next falling edge
    reg [FIDX_W-1:0] cidx   = {FIDX_W{1'b0}};

    wire wrap = ({{(32-CNT_W){1'b0}}, cnt} == FB - 1);
    wire [31:0] idx32 = {{(32-FIDX_W){1'b0}}, idx};
    wire more = (idx32 + 32'd1 < NFRAMES);        // a next frame exists

    // ---------------------------------------------------------------------
    // frame read mux (explicit per-frame array: never a computed part-select)
    // ---------------------------------------------------------------------
    // (all 2**FIDX_W entries, zeros past the last frame, so any index is in range)
    wire [FB-1:0] frame_arr [0:(1<<FIDX_W)-1];
    genvar f;
    generate
        for (f = 0; f < (1 << FIDX_W); f = f + 1) begin : g_rd
            if (f < NFRAMES) begin : g_mem
                assign frame_arr[f] = cfg[f*FB +: FB];
            end else begin : g_zero
                assign frame_arr[f] = {FB{1'b0}};
            end
        end
    endgenerate

    // CHAIN_OUT reads frame 0 at capture and frame idx+1 at each wrap
    wire [FIDX_W-1:0] chain_ridx = capture ? {FIDX_W{1'b0}} : idx + 1'b1;
    wire [FIDX_W-1:0] ridx       = chain_out ? chain_ridx : fdro_idx;
    assign rd_frame = frame_arr[ridx];

    // ---------------------------------------------------------------------
    // buffer, counters (rising edge)
    // ---------------------------------------------------------------------
    always @(posedge tck) begin
        cwe <= 1'b0;
        if (capture) begin
            cnt <= {CNT_W{1'b0}};
            idx <= {FIDX_W{1'b0}};
            if (chain_out) buf_q <= rd_frame;
        end else if (shift) begin
            cnt <= wrap ? {CNT_W{1'b0}} : cnt + 1'b1;
            if (chain_out && wrap && more)
                buf_q <= rd_frame;
            else
                buf_q <= {si, buf_q[FB-1:1]};
            if (wrap && (idx32 < NFRAMES)) begin
                idx <= idx + 1'b1;
                if (chain_in && wen) begin
                    cwe  <= 1'b1;
                    cidx <= idx;
                end
            end
        end else if (load)
            buf_q <= load_data;
    end

    // ---------------------------------------------------------------------
    // memory (falling edge)
    // ---------------------------------------------------------------------
    generate
        for (f = 0; f < NFRAMES; f = f + 1) begin : g_frame
            wire we = (cwe && cidx == f[FIDX_W-1:0]) || (frame_we && frame_idx == f[FIDX_W-1:0]);
            always @(negedge tck) begin
                if (clear)
                    cfg[f*FB +: FB] <= {FB{1'b0}};
                else if (we)
                    cfg[f*FB +: FB] <= buf_q;
            end
        end
    endgenerate

    assign so = buf_q[0];

    initial cfg = {W{1'b0}};

endmodule

`default_nettype wire
