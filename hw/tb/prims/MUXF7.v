// -----------------------------------------------------------------------------
// MUXF7.v - simulation model of AMD's MUXF7 (UG953), for iverilog and verilator only (M23)
//
// Not in hw/sources.f (sim/hwfiles.sh --sim adds it). O = S ? I1 : I0; with S unknown, the
// inputs' common value when they agree.
// -----------------------------------------------------------------------------
`timescale 1ns / 1ps
`ifndef SYNTHESIS
module MUXF7 (
    output wire O,
    input  wire I0, I1, S
);
    assign O = (S === 1'b1) ? I1 : (S === 1'b0) ? I0 : (I0 === I1) ? I0 : 1'bx;
endmodule
`endif
