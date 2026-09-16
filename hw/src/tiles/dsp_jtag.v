// -----------------------------------------------------------------------------
// dsp_jtag.v - the DSP test register (private instruction DSP, 101000) (M6, M7)
//
// Moved out of M6's dsp_tile.v unchanged in function; the slices now live in
// the generated fabric (hw/src/tiles/dsp_block.v).
//
// 256-bit register:
//   capture  [48*s +: 48] P of slice s, then 0, [255:248] version 0x07
//   update   [255:252] == 4 (SET_DRIVE): drive <- [NDSP*124-1:0]; otherwise nothing
//   drive    slice s at [124*s +: 124]: a[24:0] b[17:0] c[47:0] d[24:0] then
//            ce_ad ce_b ce_m ce_p rst_ad rst_b rst_m rst_p. A slice uses its
//            part only where its jtag_* config bits say so.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module dsp_jtag #(
    parameter integer NDSP = 2            // 1..2: 124 drive bits per slice fit in 248
)(
    input  wire                    tck,
    input  wire                    tdi,
    input  wire                    sel,
    input  wire                    dr_capture,
    input  wire                    dr_shift,
    input  wire                    dr_update,
    output wire                    so,
    output reg  [NDSP*124-1:0]     drive,
    input  wire [NDSP*48-1:0]      p
);

    localparam [7:0] VERSION = 8'h07;

    reg [255:0] sr = 256'h0;

    always @(posedge tck) begin
        if (sel & dr_capture)
            sr <= {VERSION, {(248 - NDSP*48){1'b0}}, p};
        else if (sel & dr_shift)
            sr <= {tdi, sr[255:1]};
    end

    always @(negedge tck)
        if (sel & dr_update & (sr[255:252] == 4'h4))
            drive <= sr[NDSP*124-1:0];

    assign so = sr[0];

    initial drive = {(NDSP*124){1'b0}};

    /* verilator lint_off UNUSEDSIGNAL */
    wire _unused = &{1'b0, sr[251:NDSP*124]};
    /* verilator lint_on UNUSEDSIGNAL */

endmodule

`default_nettype wire
