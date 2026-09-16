// -----------------------------------------------------------------------------
// bram_tile.v - the BRAM tile: pin connection box, output box, core, JTAG (M5)
//
// Sits on the fabric's East edge and spans all 4 rows, like a RAMB18 spans 4
// CLB rows (UG473; the VPR `memory` block height in OpenFPGA's k6_frac_N10
// dpram arch). Until M7 gives it real routing columns it connects through the
// fabric's 16 East edge tracks:
//
//   trk_in[r*4+t]   fabric tile (r,3) out_E[t]  ->  BRAM pin sources
//   trk_out[r*4+t]  BRAM output box             ->  fabric tile (r,3) in_E[t]
//
// Config (tools/bob/device.py 'bram' tile type):
//   [1:0] wmode_a  [3:2] wmode_b   0 WRITE_FIRST, 1 READ_FIRST, 2 NO_CHANGE
//   [4] reg_a  [5] reg_b           DOA_REG / DOB_REG
//   [7:6] reserved
//   64 pin selects, 5 bits each:   port A pins 0..31, port B pins 32..63, each
//                                  addr[9:0], di[17:0], we, en, rst, regce
//       source  0 const0 | 1 const1 | 2 JTAG drive bit | 3..18 trk_in[0..15]
//   16 output selects, 6 bits each, one per trk_out:
//       source  0 const0 | 1..18 do_a[0..17] | 19..36 do_b[0..17]
//
// An all-zero config is inert: every pin const0 (EN low), every output const0.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module bram_tile (
    input  wire                     sysclk,
    input  wire                     gce,
    input  wire                     gsr,
    input  wire                     gwe,

    input  wire [`BOB_BRAM_W-1:0]   cfg,
    input  wire [15:0]              trk_in,
    output wire [15:0]              trk_out,

    // JTAG USER4
    input  wire                     tck,
    input  wire                     tdi,
    input  wire                     sel,
    input  wire                     dr_capture,
    input  wire                     dr_shift,
    input  wire                     dr_update,
    output wire                     so
);

    localparam integer ADDR_W   = `BOB_BRAM_ADDR_W;
    localparam integer DATA_W   = `BOB_BRAM_DATA_W;
    localparam integer NPIN     = 2 * `BOB_BRAM_PORT_PINS;
    localparam integer PIN_LO   = `BOB_BRAM_PIN_LO;
    localparam integer PIN_SELW = `BOB_BRAM_PIN_SELW;
    localparam integer OUT_LO   = `BOB_BRAM_OUT_LO;
    localparam integer OUT_SELW = `BOB_BRAM_OUT_SELW;

    wire [NPIN-1:0]   drive;
    wire [NPIN-1:0]   pin;
    wire [DATA_W-1:0] do_a, do_b, ram_a_q;
    wire              init_go, init_wr;
    wire [ADDR_W-1:0] init_addr;
    wire [DATA_W-1:0] init_data;

    // ---------------------------------------------------------------------
    // Pin connection box
    // ---------------------------------------------------------------------
    genvar k;
    generate
        for (k = 0; k < NPIN; k = k + 1) begin : g_pin
            wire [31:0] srcs = {13'b0, trk_in, drive[k], 1'b1, 1'b0};
            assign pin[k] = srcs[cfg[PIN_LO + k*PIN_SELW +: PIN_SELW]];
        end
    endgenerate

    // port pin order: addr[ADDR_W-1:0], di[DATA_W-1:0], we, en, rst, regce
    localparam integer P_WE = ADDR_W + DATA_W;
    localparam integer PB   = `BOB_BRAM_PORT_PINS;

    bram_core #(.ADDR_W(ADDR_W), .DATA_W(DATA_W)) u_core (
        .clk       (sysclk),
        .gce       (gce),
        .gsr       (gsr),
        .gwe       (gwe),
        .wmode_a   (cfg[1:0]),
        .wmode_b   (cfg[3:2]),
        .reg_a     (cfg[4]),
        .reg_b     (cfg[5]),
        .addr_a    (pin[0 +: ADDR_W]),
        .di_a      (pin[ADDR_W +: DATA_W]),
        .we_a      (pin[P_WE]),
        .en_a      (pin[P_WE + 1]),
        .rst_a     (pin[P_WE + 2]),
        .regce_a   (pin[P_WE + 3]),
        .addr_b    (pin[PB +: ADDR_W]),
        .di_b      (pin[PB + ADDR_W +: DATA_W]),
        .we_b      (pin[PB + P_WE]),
        .en_b      (pin[PB + P_WE + 1]),
        .rst_b     (pin[PB + P_WE + 2]),
        .regce_b   (pin[PB + P_WE + 3]),
        .init_go   (init_go),
        .init_wr   (init_wr),
        .init_addr (init_addr),
        .init_data (init_data),
        .do_a      (do_a),
        .do_b      (do_b),
        .ram_a_q   (ram_a_q)
    );

    // ---------------------------------------------------------------------
    // Output box
    // ---------------------------------------------------------------------
    wire [63:0] obus = {{(64 - 1 - 2*DATA_W){1'b0}}, do_b, do_a, 1'b0};
    generate
        for (k = 0; k < 16; k = k + 1) begin : g_out
            assign trk_out[k] = obus[cfg[OUT_LO + k*OUT_SELW +: OUT_SELW]];
        end
    endgenerate

    bram_jtag #(.ADDR_W(ADDR_W), .DATA_W(DATA_W), .NPIN(NPIN)) u_jtag (
        .tck        (tck),
        .tdi        (tdi),
        .sel        (sel),
        .dr_capture (dr_capture),
        .dr_shift   (dr_shift),
        .dr_update  (dr_update),
        .so         (so),
        .drive      (drive),
        .sysclk     (sysclk),
        .gwe_s      (gwe),
        .do_a       (do_a),
        .do_b       (do_b),
        .ram_a_q    (ram_a_q),
        .init_go    (init_go),
        .init_wr    (init_wr),
        .init_addr  (init_addr),
        .init_data  (init_data)
    );

    wire _unused = &{1'b0, cfg[7:6]};

endmodule

`default_nettype wire
