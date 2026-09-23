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
// Readback (M21): the BRAM shadow. Every frame written into `cfg` is written, on the
// same falling edge and from the same `buf_q`, into a block RAM `shadow` (NFRAMES x FB,
// one or two RAMB36 on the XC7Z020). CHAIN_OUT and cfg_frames' FDRO read that copy:
// one synchronous read port, clocked on the rising edge, continuously reading the frame
// the next load will want. Until M20 the read was a 256:1 x 128-bit mux over the flops
// themselves (`frame_arr`, ~11 800 LUTs, a third of the design; M20 showed a tree does
// not help), so the shadow is where M21's cluster fabric finds its room.
//
//   what readback now proves: the frames that were WRITTEN (the shadow is written by the
//   same enable and data as the flops), not what the configuration flops HOLD. The flops
//   stay covered by golden co-simulation, CAPTURE and the board's model checks
//   (docs/bitstream-format.md section 12).
//   JPROGRAM: `clear` zeroes the flops at once; the shadow cannot be, so a per-frame
//   `valid` bit (cleared with the flops, set by each write) makes an unwritten frame
//   read back as zeros, exactly as the flops would.
//   timing: the read is registered, so its address must be stable the cycle before it
//   is used. FDRO's frame changes only on a word load, at least 32 TCK edges before the
//   next one; CHAIN_OUT reads frame idx+1, where idx rests at all-ones between DR scans
//   (set at Update-DR), so frame 0 is waiting at Capture-DR.
//
// M22: L-frames (LMASK) keep no flip-flops: their bits live in the fabric's CFGLUT5s,
// which lut_loader.v fills from the same write (wr / wr_idx / wr_data, the falling edge
// that writes the shadow). Their `cfg` bits read 0 and nothing uses them.
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
    parameter integer W       = FB * NFRAMES,
    parameter [NFRAMES-1:0] LMASK = {NFRAMES{1'b0}}     // M22: frames held only in CFGLUT5s
)(
    input  wire              tck,
    // chain
    input  wire              chain_in,       // CHAIN_IN selected
    input  wire              chain_out,      // CHAIN_OUT selected
    input  wire              capture,        // Capture-DR (with either chain instruction)
    input  wire              shift,          // Shift-DR   (with either chain instruction)
    input  wire              update,         // Update-DR  (with either chain instruction)
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
    // M22: every frame write, for lut_loader.v (sample on the falling edge)
    output wire              wr,
    output wire [FIDX_W-1:0] wr_idx,
    output wire [FB-1:0]     wr_data,

    output reg  [W-1:0]      cfg
);

    localparam integer CNT_W = $clog2(FB);

    reg [FB-1:0]     buf_q  = {FB{1'b0}};
    reg [CNT_W-1:0]  cnt    = {CNT_W{1'b0}};
    reg [FIDX_W-1:0] idx    = {FIDX_W{1'b1}};     // chain frame being shifted (all-ones: none)
    reg              cwe    = 1'b0;               // chain: write frame cidx on the next falling edge
    reg [FIDX_W-1:0] cidx   = {FIDX_W{1'b0}};

    wire wrap = ({{(32-CNT_W){1'b0}}, cnt} == FB - 1);
    wire [31:0] idx32 = {{(32-FIDX_W){1'b0}}, idx};
    wire more = (idx32 + 32'd1 < NFRAMES);        // a next frame exists

    // ---------------------------------------------------------------------
    // the BRAM shadow (write on the falling edge beside cfg, read on the rising edge)
    // ---------------------------------------------------------------------
    (* ram_style = "block" *) reg [FB-1:0] shadow [0:NFRAMES-1];
    reg  [NFRAMES-1:0] valid = {NFRAMES{1'b0}};
    reg  [FB-1:0]      rd_q  = {FB{1'b0}};
    reg                rv_q  = 1'b0;

    wire              swe   = cwe || frame_we;
    wire [FIDX_W-1:0] waddr = cwe ? cidx : frame_idx;
    wire              wok   = ({{(32-FIDX_W){1'b0}}, waddr} < NFRAMES);

    always @(negedge tck)
        if (swe && wok && !clear)
            shadow[waddr] <= buf_q;

    assign wr      = swe && wok && !clear;
    assign wr_idx  = waddr;
    assign wr_data = buf_q;

    always @(negedge tck)
        if (clear)
            valid <= {NFRAMES{1'b0}};
        else if (swe && wok)
            valid[waddr] <= 1'b1;

    // CHAIN_OUT reads frame 0 at capture and frame idx+1 at each wrap
    wire [FIDX_W-1:0] chain_ridx = capture ? {FIDX_W{1'b0}} : idx + 1'b1;
    wire [FIDX_W-1:0] ridx       = chain_out ? chain_ridx : fdro_idx;
    wire              rok        = ({{(32-FIDX_W){1'b0}}, ridx} < NFRAMES);

    always @(posedge tck) begin
        if (rok)
            rd_q <= shadow[ridx];
        rv_q <= rok && valid[ridx];
    end
    assign rd_frame = rv_q ? rd_q : {FB{1'b0}};

    // ---------------------------------------------------------------------
    // buffer, counters (rising edge)
    // ---------------------------------------------------------------------
    always @(posedge tck) begin
        cwe <= 1'b0;
        if (update)
            idx <= {FIDX_W{1'b1}};                    // between scans: frame 0 is next
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
    genvar f;
    generate
        for (f = 0; f < NFRAMES; f = f + 1) begin : g_frame
            if (!LMASK[f]) begin : g_ff
                wire we = (cwe && cidx == f[FIDX_W-1:0]) || (frame_we && frame_idx == f[FIDX_W-1:0]);
                always @(negedge tck) begin
                    if (clear)
                        cfg[f*FB +: FB] <= {FB{1'b0}};
                    else if (we)
                        cfg[f*FB +: FB] <= buf_q;
                end
            end
        end
    endgenerate

    assign so = buf_q[0];

`ifdef SIMULATION
    // M22, simulation only: what was written into the L-frames (whose bits have no
    // flip-flops here). Testbenches compare `cfg | sim_lmem` with whole configuration words,
    // as they compared `cfg` before; the CFGLUT5 contents themselves are checked directly.
    /* verilator lint_off UNUSEDSIGNAL */
    reg [W-1:0] sim_lmem = {W{1'b0}};             // read by the testbenches
    /* verilator lint_on UNUSEDSIGNAL */
    always @(negedge tck)
        if (clear)
            sim_lmem <= {W{1'b0}};
        else if (swe && wok && LMASK[waddr])
            sim_lmem[waddr*FB +: FB] <= buf_q;
`endif

    initial cfg = {W{1'b0}};

endmodule

`default_nettype wire
