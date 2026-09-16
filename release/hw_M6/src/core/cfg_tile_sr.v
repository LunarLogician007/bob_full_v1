// -----------------------------------------------------------------------------
// cfg_tile_sr.v - one tile's configuration memory: shift register + shadow
//
// OpenFPGA's scan_chain protocol threads the chain through every tile's
// configuration flops; Aegis (docs/arch/configuration.md) separates a shift
// register from the config register the tile logic reads, so the logic never
// sees bits moving past. This is that cell, with bob's JTAG timing:
//
//   posedge  capture   sr  <= cfg              (readback starts from the live config)
//   posedge  shift     sr  <= {si, sr[W-1:1]}  (LSB-first; si enters the MSB)
//   negedge  clear     cfg <= 0                (JPROGRAM; wins over commit)
//   negedge  commit    cfg <= sr               (CFG_IN Update-DR, length+CRC ok)
//
// so = sr[0] feeds the next-lower tile's si (or TDO for tile 0).
// See docs/bitstream-format.md section 4.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module cfg_tile_sr #(
    parameter integer W = 16            // >= 2
)(
    input  wire         tck,
    input  wire         capture,
    input  wire         shift,
    input  wire         commit,
    input  wire         clear,
    input  wire         si,
    output wire         so,
    output reg  [W-1:0] cfg
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
    end

    assign so = sr[0];

    initial cfg = {W{1'b0}};

endmodule

`default_nettype wire
