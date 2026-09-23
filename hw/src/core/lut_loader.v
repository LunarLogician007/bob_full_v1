// -----------------------------------------------------------------------------
// lut_loader.v - shifts each written frame into the CFGLUT5s that own it (M22)
//
// Every configuration write, chain or frames, reaches memory from cfg_store's one frame
// buffer on a falling TCK edge. On that same edge this module copies the buffer and the
// frame index, then runs for 32 TCK cycles: `busy` is the shift enable, and on each rising
// edge every CFGLUT5 of the frame (CE = busy and the CLB owns frame `idx`, compared in
// bob_fabric.v) takes the next bit from the shared expander (lut_expand.v, over `lbuf` and
// `cnt`). Frames that are not L-frames also run a (harmless) cycle: no CLB claims them.
//
//   timing  a frame needs at least 128 TCK cycles to arrive (4 FDRI words, or 128 chain
//           bits), so a load always finishes before the next frame is written. JSTART
//           ticks are held while busy (bob_fpga.v), so startup never sees a half-shifted
//           table.
//   JPROGRAM  `clear` restarts the loader as a sweep: every CFGLUT5 of every CLB (clr),
//           with an all-zero buffer, i.e. const0 everywhere - a dark, loop-free fabric, as
//           the cleared configuration flip-flops are.
//   clocks  falling-edge state, rising-edge CFGLUT5 shifts: half a TCK period (5 us) for
//           the expander and the CE compare.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module lut_loader #(
    parameter integer FB     = 128,
    parameter integer FIDX_W = 9
)(
    input  wire              tck,
    input  wire              clear,       // JPROGRAM (cfg_ctrl), sampled on the falling edge
    input  wire              wr,          // a frame is written on this falling edge
    input  wire [FIDX_W-1:0] wr_idx,
    input  wire [FB-1:0]     wr_data,
    output reg               busy = 1'b0,
    output reg               clr  = 1'b0, // the sweep: every CLB's CFGLUT5s shift zeros
    output reg  [FIDX_W-1:0] idx  = {FIDX_W{1'b0}},
    output reg  [FB-1:0]     lbuf = {FB{1'b0}},
    output reg  [4:0]        cnt  = 5'd0
);

    always @(negedge tck) begin
        if (clear) begin
            busy <= 1'b1;
            clr  <= 1'b1;
            cnt  <= 5'd0;
            lbuf <= {FB{1'b0}};
        end else if (wr) begin
            busy <= 1'b1;
            clr  <= 1'b0;
            cnt  <= 5'd0;
            lbuf <= wr_data;
            idx  <= wr_idx;
        end else if (busy) begin
            if (cnt == 5'd31) begin
                busy <= 1'b0;
                clr  <= 1'b0;
            end
            cnt <= cnt + 5'd1;
        end
    end

endmodule

`default_nettype wire
