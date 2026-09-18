// -----------------------------------------------------------------------------
// bram_block.v - one BRAM block of the generated fabric (M7)
//
// A VPR `bram` block, height 4 in the BRAM column (a RAMB18 spans CLB rows the
// same way, UG473). Its 64 input pins and 36 output pins are rr-graph IPIN/OPIN
// wires of hw/src/generated/bob_fabric.v; the pins' connection-box muxes live
// there. This module only adds the choice made in M5 between fabric pins and
// the USER4 JTAG drive word, per port.
//
// Config (software/bob/device.py 'bram' fields):
//   [1:0] wmode_a  [3:2] wmode_b   0 WRITE_FIRST, 1 READ_FIRST, 2 NO_CHANGE
//   [4] reg_a  [5] reg_b           DOA_REG / DOB_REG
//   [6] jtag_a [7] jtag_b          port pins from the drive word, not the fabric
//
// pin / drive layout: port A [31:0], port B [63:32]; each addr[9:0], di[17:0],
// we, en, rst, regce.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module bram_block (
    input  wire                      sysclk,
    input  wire                      gce,
    input  wire                      gsr,
    input  wire                      gwe,
    input  wire [`BOB_BRAM_CFG_W-1:0] cfg,
    input  wire [63:0]               pin,
    input  wire [63:0]               drive,

    input  wire                      init_go,
    input  wire                      init_wr,
    input  wire [9:0]                init_addr,
    input  wire [17:0]               init_data,

    output wire [17:0]               do_a,
    output wire [17:0]               do_b,
    output wire [17:0]               ram_a_q
);

    wire [31:0] pa = cfg[6] ? drive[31:0]  : pin[31:0];
    wire [31:0] pb = cfg[7] ? drive[63:32] : pin[63:32];

    bram_core #(.ADDR_W(10), .DATA_W(18)) u_core (
        .clk       (sysclk),
        .gce       (gce),
        .gsr       (gsr),
        .gwe       (gwe),
        .wmode_a   (cfg[1:0]),
        .wmode_b   (cfg[3:2]),
        .reg_a     (cfg[4]),
        .reg_b     (cfg[5]),
        .addr_a    (pa[9:0]),
        .di_a      (pa[27:10]),
        .we_a      (pa[28]),
        .en_a      (pa[29]),
        .rst_a     (pa[30]),
        .regce_a   (pa[31]),
        .addr_b    (pb[9:0]),
        .di_b      (pb[27:10]),
        .we_b      (pb[28]),
        .en_b      (pb[29]),
        .rst_b     (pb[30]),
        .regce_b   (pb[31]),
        .init_go   (init_go),
        .init_wr   (init_wr),
        .init_addr (init_addr),
        .init_data (init_data),
        .do_a      (do_a),
        .do_b      (do_b),
        .ram_a_q   (ram_a_q)
    );

endmodule

`default_nettype wire
