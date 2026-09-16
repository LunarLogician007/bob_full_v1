// -----------------------------------------------------------------------------
// mini_fpga_top.v - PYNQ-Z2 board wrapper for the one-CLB mini FPGA
//
// Everything board-specific lives here: the global clock buffer and the mapping
// of the boundary's system side onto real switches, buttons and LEDs. The
// design proper is mini_fpga.v, which has no vendor primitives in it and is the
// module the testbench drives.
//
// With no test instruction selected the boundary is transparent, so the CLB
// runs from the physical switches and buttons and drives the LEDs directly:
// configure it as an AND gate over JTAG, then toggle SW0 and SW1 and watch LD0.
//
// This is a PL-only design. No Zynq PS, no AXI, no block design, no system
// clock - TCK from the probe clocks the entire chip.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module mini_fpga_top #(
    parameter [31:0] IDCODE_VALUE = 32'h2BEEF093
)(
    input  wire       tck,
    input  wire       tms,
    input  wire       tdi,
    output wire       tdo,

    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [3:0] led
);

    // TCK arrives on an MRCC pin (U18) and clocks every flip-flop in the
    // design, so put it on a global clock buffer explicitly rather than
    // relying on Vivado's automatic insertion.
    wire tck_g;
`ifdef SIMULATION
    assign tck_g = tck;
`else
    BUFG bufg_tck (.I(tck), .O(tck_g));
`endif

    wire [2:0] pad_o;
    wire [3:0] tap_state;
    wire       configured;

    mini_fpga #(
        .IDCODE_VALUE (IDCODE_VALUE)
    ) u_core (
        .tck        (tck_g),
        .tms        (tms),
        .tdi        (tdi),
        .tdo        (tdo),
        .pad_i      ({btn[3:0], sw[1:0]}),   // i[5:2] = btn, i[1:0] = sw
        .pad_o      (pad_o),                 // {cout, o5, o}
        .tap_state  (tap_state),
        .configured (configured)
    );

    assign led[0] = pad_o[0];    // CLB main output   o
    assign led[1] = pad_o[1];    // fractured LUT5    o5
    assign led[2] = pad_o[2];    // carry out         cout
    assign led[3] = configured;  // a non-zero config word has been loaded

    // tap_state is left unconnected on purpose; keep it reachable for debug by
    // temporarily driving the LEDs from it instead.
    wire _unused = &{1'b0, tap_state};

endmodule

`default_nettype wire
