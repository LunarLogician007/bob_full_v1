// -----------------------------------------------------------------------------
// fpga4x4_top.v - PYNQ-Z2 board wrapper for the 4x4 fabric
//
// Same pads as the single-CLB build, so the same harness and the same XDC pin
// assignments apply: SW1/SW0 and BTN3..0 are the fabric's input pads, LD0..LD2
// its output pads, LD3 lights once a non-zero bitstream is loaded.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module fpga4x4_top #(
    // Set per build from hw/build.cfg by hw/scripts/build.tcl, so the version
    // nibble on the wire (and USERCODE) say which milestone build is in the PL.
    parameter [31:0] IDCODE_VALUE   = 32'h5BEEF093,
    parameter [31:0] USERCODE_VALUE = 32'h00000003
)(
    input  wire       tck,
    input  wire       tms,
    input  wire       tdi,
    output wire       tdo,

    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [3:0] led
);

    wire tck_g;
`ifdef SIMULATION
    assign tck_g = tck;
`else
    BUFG bufg_tck (.I(tck), .O(tck_g));
`endif

    wire [2:0] pad_o;
    wire [3:0] tap_state;
    wire       configured;

    fpga4x4 #(
        .IDCODE_VALUE   (IDCODE_VALUE),
        .USERCODE_VALUE (USERCODE_VALUE)
    ) u_core (
        .tck        (tck_g),
        .tms        (tms),
        .tdi        (tdi),
        .tdo        (tdo),
        .pad_i      ({btn[3:0], sw[1:0]}),
        .pad_o      (pad_o),
        .tap_state  (tap_state),
        .configured (configured)
    );

    assign led[0] = pad_o[0];
    assign led[1] = pad_o[1];
    assign led[2] = pad_o[2];
    assign led[3] = configured;      // DONE: configured, CRC checked, startup complete

    wire _unused = &{1'b0, tap_state};

endmodule

`default_nettype wire
