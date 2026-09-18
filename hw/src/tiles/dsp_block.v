// -----------------------------------------------------------------------------
// dsp_block.v - one DSP slice of the generated fabric (M7)
//
// A VPR `dsp` block, height 4 in the DSP column: a DSP48E1-style slice (UG479
// trimmed, hw/src/tiles/dsp_core.v). A, B, C, D and the eight CE/RST controls
// are rr-graph IPIN wires of hw/src/generated/bob_fabric.v; P is OPIN wires, and
// PCOUT (= P) reaches the slice above as its PCIN through a VPR direct.
//
// Config (software/bob/device.py 'dsp' fields):
//   [1:0] opmode  0 M, 1 M+C, 2 P+M, 3 (PCIN>>>17)+M
//   [2] use_d  [3] d_sub  [4] areg [5] breg [6] creg [7] dreg [8] mreg [9] preg
//   [10] jtag_a [11] jtag_b [12] jtag_c [13] jtag_d  bus from the drive word
//   [14] jtag_ctrl                                   controls from the drive word
//   [15] reserved
//
// drive (124 bits, the private DSP JTAG register, hw/src/tiles/dsp_jtag.v):
//   a[24:0] b[17:0] c[47:0] d[24:0], then ce_ad ce_b ce_m ce_p rst_ad rst_b rst_m rst_p
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module dsp_block (
    input  wire                      sysclk,
    input  wire                      gce,
    input  wire                      gsr,
    input  wire                      gwe,
    input  wire [`BOB_DSP_CFG_W-1:0] cfg,

    input  wire [24:0]               a,
    input  wire [17:0]               b,
    input  wire [47:0]               c,
    input  wire [24:0]               d,
    input  wire [7:0]                ctrl,     // ce_ad ce_b ce_m ce_p rst_ad rst_b rst_m rst_p
    input  wire [47:0]               pcin,
    input  wire [123:0]              drive,

    output wire [47:0]               p
);

    wire [24:0] a_v   = cfg[10] ? drive[24:0]    : a;
    wire [17:0] b_v   = cfg[11] ? drive[42:25]   : b;
    wire [47:0] c_v   = cfg[12] ? drive[90:43]   : c;
    wire [24:0] d_v   = cfg[13] ? drive[115:91]  : d;
    wire [7:0]  ctl   = cfg[14] ? drive[123:116] : ctrl;

    dsp_core u_core (
        .clk    (sysclk),
        .gce    (gce),
        .gsr    (gsr),
        .gwe    (gwe),
        .opmode (cfg[1:0]),
        .use_d  (cfg[2]),
        .d_sub  (cfg[3]),
        .areg   (cfg[4]),
        .breg   (cfg[5]),
        .creg   (cfg[6]),
        .dreg   (cfg[7]),
        .mreg   (cfg[8]),
        .preg   (cfg[9]),
        .a      (a_v),
        .b      (b_v),
        .c      (c_v),
        .d      (d_v),
        .ce_ad  (ctl[0]),
        .ce_b   (ctl[1]),
        .ce_m   (ctl[2]),
        .ce_p   (ctl[3]),
        .rst_ad (ctl[4]),
        .rst_b  (ctl[5]),
        .rst_m  (ctl[6]),
        .rst_p  (ctl[7]),
        .pcin   (pcin),
        .p      (p)
    );

    wire _unused = &{1'b0, cfg[15]};

endmodule

`default_nettype wire
