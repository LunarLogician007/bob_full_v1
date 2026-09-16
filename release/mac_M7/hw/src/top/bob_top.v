// -----------------------------------------------------------------------------
// bob_top.v - PYNQ-Z2 board wrapper for the complete bob FPGA (M7)
//
// The fabric has NPAD pads; the board provides six inputs and three LEDs for
// them, at the pad numbers tools/bob/device.py chose (bob_params.vh BOB_PAD_*):
// SW0, SW1, BTN0..3 on West-edge pads, LD0..LD2 on East-edge pads. Every other
// pad's input is 0 and its output goes nowhere - those pads are reachable
// through boundary scan (INTEST/SAMPLE) only. LD3 is DONE.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module bob_top #(
    // Set per build from hw/build.cfg by hw/scripts/build.tcl, so the version
    // nibble on the wire (and USERCODE) say which milestone build is in the PL.
    parameter [31:0] IDCODE_VALUE   = 32'h8BEEF093,
    parameter [31:0] USERCODE_VALUE = 32'h00000007
)(
    input  wire       sysclk,
    input  wire       tck,
    input  wire       tms,
    input  wire       tdi,
    output wire       tdo,

    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [3:0] led
);

    localparam integer NPAD = `BOB_NPAD;

    wire tck_g, sysclk_g;
`ifdef SIMULATION
    assign tck_g    = tck;
    assign sysclk_g = sysclk;
`else
    BUFG bufg_tck    (.I(tck),    .O(tck_g));
    BUFG bufg_sysclk (.I(sysclk), .O(sysclk_g));
`endif

    wire [NPAD-1:0] pad_i;
    wire [NPAD-1:0] pad_o;
    wire [3:0]      tap_state;
    wire            configured;

    genvar k;
    generate
        for (k = 0; k < NPAD; k = k + 1) begin : g_pad
            assign pad_i[k] = (k == `BOB_PAD_SW0)  ? sw[0]  :
                              (k == `BOB_PAD_SW1)  ? sw[1]  :
                              (k == `BOB_PAD_BTN0) ? btn[0] :
                              (k == `BOB_PAD_BTN1) ? btn[1] :
                              (k == `BOB_PAD_BTN2) ? btn[2] :
                              (k == `BOB_PAD_BTN3) ? btn[3] : 1'b0;
        end
    endgenerate

    bob_fpga #(
        .IDCODE_VALUE   (IDCODE_VALUE),
        .USERCODE_VALUE (USERCODE_VALUE)
    ) u_core (
        .sysclk     (sysclk_g),
        .tck        (tck_g),
        .tms        (tms),
        .tdi        (tdi),
        .tdo        (tdo),
        .pad_i      (pad_i),
        .pad_o      (pad_o),
        .tap_state  (tap_state),
        .configured (configured)
    );

    assign led[0] = pad_o[`BOB_PAD_LD0];
    assign led[1] = pad_o[`BOB_PAD_LD1];
    assign led[2] = pad_o[`BOB_PAD_LD2];
    assign led[3] = configured;      // DONE: configured, CRC checked, startup complete

    wire _unused = &{1'b0, tap_state, pad_o};

endmodule

`default_nettype wire
