// -----------------------------------------------------------------------------
// bob_fpga.v - the complete bob FPGA (M7): generated fabric behind the
// scan-chain configuration plane, board-independent
//
// No BUFG, no pin assignments, no vendor primitives: the identical file runs in
// simulation and in synthesis. Sizes come from bob_params.vh (tools/bob/device.py).
//
// Configuration (docs/bitstream-format.md):
//   jtag_tap6    6-bit AMD 7-series IR (CFG_IN/CFG_OUT/USER1-4/JPROGRAM/JSTART/DSP)
//   cfg_ctrl     CRC-32C + length check before commit; GSR/GTS/GWE/DONE startup
//   u_chain      the whole configuration chain (ctrl tile, grid tiles, tail) as
//                one shift register + shadow register; the tile boundaries are
//                device.json's, the RTL does not need them
//   capture      USER3 snapshots every CLB output; USER1 returns the first 16
//
// User clock (clock_ctrl.v): the fabric runs on sysclk with gce as its enable -
// one pulse per TCK edge while USER1 ce (clk_mode 0) or a divider (clk_mode 1).
//
// Boundary scan: two cells per pad. Cell k < NPAD is pad k's output cell (the
// fabric's pad_out, forced 0 while GTS, to the world); cell NPAD + k is pad k's
// input cell (the world to the fabric's pad_in). Cell 0 is nearest TDO.
//
// BRAM contents / test access: USER4 (bram_jtag.v). DSP test drive: private
// DSP instruction (dsp_jtag.v).
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module bob_fpga #(
    parameter [31:0]  IDCODE_VALUE   = 32'h8BEEF093,
    parameter [31:0]  USERCODE_VALUE = 32'h00000007,
    // Simulation may shorten the free-running divider; the board uses 8.
    parameter integer DIV_MIN_SHIFT  = `BOB_DIV_MIN_SHIFT
)(
    input  wire                  sysclk,        // 125 MHz board clock (already on a BUFG)
    input  wire                  tck,
    input  wire                  tms,
    input  wire                  tdi,
    output wire                  tdo,

    input  wire [`BOB_NPAD-1:0]  pad_i,         // the world side of every pad
    output wire [`BOB_NPAD-1:0]  pad_o,

    output wire [3:0]            tap_state,
    output wire                  configured     // DONE
);

    localparam integer NPAD    = `BOB_NPAD;
    localparam integer NCLB    = `BOB_NCLB;
    localparam integer NBRAM   = `BOB_NBRAM;
    localparam integer NDSP    = `BOB_NDSP;
    localparam integer CHAIN_W = `BOB_CHAIN_W;
    localparam integer CTRL_W  = `BOB_CTRL_W;
    localparam integer BSR_W   = `BOB_BSR_W;
    localparam integer DATA_W  = `BOB_BRAM_DATA_W;

    // TAP
    wire                bsr_capture, bsr_shift, bsr_update, bsr_mode;
    wire                bsr_si, bsr_so, tlr;
    wire                dr_capture, dr_shift, dr_update;
    wire                sel_cfg_in, sel_cfg_out, sel_ctrl, sel_capture, sel_bram, sel_dsp;
    wire                cfg_so, ctrl_so, cap_so, bram_so, dsp_so;
    wire                jprogram, jstart_tick;
    wire [3:0]          ir_status;
    wire                ce, sr, cin, step_pulse;
    wire [5:0]          ir_value;

    // configuration plane
    wire                cfg_capture, cfg_shift, cfg_commit, cfg_clear;
    wire                gsr, gts, gwe, done, committed;
    wire [CHAIN_W-1:0]  chain_cfg;                    // chain bit k = chain_cfg[k]
    wire [CTRL_W-1:0]   ctrl_cfg = chain_cfg[CTRL_W-1:0];

    // user clock
    wire                gce, gsr_s, gwe_s, cin_s;

    // fabric
    wire [NCLB-1:0]         clb_o;
    wire [NPAD-1:0]         fab_pad_in, fab_pad_out;
    wire [NBRAM*64-1:0]     bram_drive;
    wire [NBRAM-1:0]        bram_init_go;
    wire                    bram_init_wr;
    wire [`BOB_BRAM_ADDR_W-1:0] bram_init_addr;
    wire [DATA_W-1:0]       bram_init_data;
    wire [NBRAM*DATA_W-1:0] bram_do_a, bram_do_b, bram_ram_a_q;
    wire [NDSP*124-1:0]     dsp_drive;
    wire [NDSP*48-1:0]      dsp_p;

    jtag_tap6 #(
        .IDCODE_VALUE   (IDCODE_VALUE),
        .USERCODE_VALUE (USERCODE_VALUE),
        .STATUS_W       (`BOB_STATUS_W),   // USER1 returns the first 16 CLB outputs
        .BSR_PRESENT    (1)
    ) u_tap (
        .tck         (tck),
        .tms         (tms),
        .tdi         (tdi),
        .tdo         (tdo),
        .bsr_capture (bsr_capture),
        .bsr_shift   (bsr_shift),
        .bsr_update  (bsr_update),
        .bsr_mode    (bsr_mode),
        .bsr_si      (bsr_si),
        .bsr_so      (bsr_so),
        .tlr         (tlr),
        .dr_capture  (dr_capture),
        .dr_shift    (dr_shift),
        .dr_update   (dr_update),
        .sel_cfg_in  (sel_cfg_in),
        .sel_cfg_out (sel_cfg_out),
        .sel_ctrl    (sel_ctrl),
        .sel_capture (sel_capture),
        .sel_bram    (sel_bram),
        .sel_dsp     (sel_dsp),
        .cfg_so      (cfg_so),
        .ctrl_so     (ctrl_so),
        .cap_so      (cap_so),
        .bram_so     (bram_so),
        .dsp_so      (dsp_so),
        .jprogram    (jprogram),
        .jstart_tick (jstart_tick),
        .ir_status   (ir_status),
        .ce          (ce),
        .sr          (sr),
        .cin         (cin),
        .step_pulse  (step_pulse),
        .user_status (clb_o[`BOB_STATUS_W-1:0]),
        .tap_state   (tap_state),
        .ir_value    (ir_value)
    );

    cfg_ctrl #(.CHAIN_W(CHAIN_W)) u_ctrl (
        .tck         (tck),
        .tdi         (tdi),
        .dr_capture  (dr_capture),
        .dr_shift    (dr_shift),
        .dr_update   (dr_update),
        .sel_cfg_in  (sel_cfg_in),
        .sel_cfg_out (sel_cfg_out),
        .sel_ctrl    (sel_ctrl),
        .jprogram    (jprogram),
        .jstart_tick (jstart_tick),
        .cfg_capture (cfg_capture),
        .cfg_shift   (cfg_shift),
        .cfg_commit  (cfg_commit),
        .cfg_clear   (cfg_clear),
        .ctrl_so     (ctrl_so),
        .gsr         (gsr),
        .gts         (gts),
        .gwe         (gwe),
        .done        (done),
        .committed   (committed),
        .ir_status   (ir_status)
    );

    // TDI -> chain_cfg[CHAIN_W-1] ... chain_cfg[0] -> TDO
    cfg_tile_sr #(.W(CHAIN_W)) u_chain (
        .tck     (tck),
        .capture (cfg_capture),
        .shift   (cfg_shift),
        .commit  (cfg_commit),
        .clear   (cfg_clear),
        .si      (tdi),
        .so      (cfg_so),
        .cfg     (chain_cfg)
    );

    capture_chain #(.N(NCLB)) u_cap (
        .tck     (tck),
        .capture (sel_capture & dr_capture),
        .shift   (sel_capture & dr_shift),
        .tdi     (tdi),
        .d       (clb_o),
        .so      (cap_so)
    );

    clock_ctrl #(
        .DIV_W     (`BOB_CTRL_CLK_DIV_W),
        .MIN_SHIFT (DIV_MIN_SHIFT)
    ) u_clk (
        .sysclk   (sysclk),
        .tck      (tck),
        .clk_mode (ctrl_cfg[`BOB_CTRL_CLK_MODE]),
        .clk_div  (ctrl_cfg[`BOB_CTRL_CLK_DIV_LO +: `BOB_CTRL_CLK_DIV_W]),
        .ce       (ce),
        .step     (step_pulse),
        .cin      (cin),
        .gsr      (gsr),
        .gwe      (gwe),
        .gce      (gce),
        .gsr_s    (gsr_s),
        .gwe_s    (gwe_s),
        .cin_s    (cin_s)
    );

    // ---------------------------------------------------------------------
    // The boundary: output cells 0..NPAD-1, input cells NPAD..2*NPAD-1.
    // ---------------------------------------------------------------------
    wire [NPAD-1:0]  out_gts   = gts ? {NPAD{1'b0}} : fab_pad_out;
    wire [BSR_W-1:0] cell_din  = {pad_i, out_gts};
    wire [BSR_W-1:0] cell_dout;
    wire [BSR_W-1:0] cell_si;
    wire [BSR_W-1:0] cell_so;

    assign cell_si[BSR_W-1] = bsr_si;
    assign bsr_so           = cell_so[0];

    genvar k;
    generate
        for (k = 0; k < BSR_W; k = k + 1) begin : g_bsr
            if (k < BSR_W - 1) begin : g_link
                assign cell_si[k] = cell_so[k+1];
            end
            bsc_cell u_cell (
                .tck        (tck),
                .trst       (1'b0),
                .rst        (tlr),
                .capture_dr (bsr_capture),
                .shift_dr   (bsr_shift),
                .update_dr  (bsr_update),
                .mode       (bsr_mode),
                .data_in    (cell_din[k]),
                .data_out   (cell_dout[k]),
                .scan_in    (cell_si[k]),
                .scan_out   (cell_so[k])
            );
        end
    endgenerate

    assign pad_o      = cell_dout[NPAD-1:0];
    assign fab_pad_in = cell_dout[BSR_W-1:NPAD];

    // ---------------------------------------------------------------------
    // BRAM contents / drive (USER4) and DSP drive (private DSP instruction)
    // ---------------------------------------------------------------------
    bram_jtag #(.ADDR_W(`BOB_BRAM_ADDR_W), .DATA_W(DATA_W), .NPIN(64), .NBRAM(NBRAM)) u_bram_jtag (
        .tck        (tck),
        .tdi        (tdi),
        .sel        (sel_bram),
        .dr_capture (dr_capture),
        .dr_shift   (dr_shift),
        .dr_update  (dr_update),
        .so         (bram_so),
        .drive      (bram_drive),
        .sysclk     (sysclk),
        .gwe_s      (gwe_s),
        .do_a       (bram_do_a),
        .do_b       (bram_do_b),
        .ram_a_q    (bram_ram_a_q),
        .init_go    (bram_init_go),
        .init_wr    (bram_init_wr),
        .init_addr  (bram_init_addr),
        .init_data  (bram_init_data)
    );

    dsp_jtag #(.NDSP(NDSP)) u_dsp_jtag (
        .tck        (tck),
        .tdi        (tdi),
        .sel        (sel_dsp),
        .dr_capture (dr_capture),
        .dr_shift   (dr_shift),
        .dr_update  (dr_update),
        .so         (dsp_so),
        .drive      (dsp_drive),
        .p          (dsp_p)
    );

    // ---------------------------------------------------------------------
    // The generated fabric (tools/bob/fabric_gen.py)
    // ---------------------------------------------------------------------
    bob_fabric u_fabric (
        .clk            (sysclk),
        .gce            (gce),
        .gsr            (gsr_s),
        .gwe            (gwe_s),
        .cin            (cin_s),
        .cfg            (chain_cfg),
        .pad_in         (fab_pad_in),
        .pad_out        (fab_pad_out),
        .clb_o          (clb_o),
        .bram_drive     (bram_drive),
        .bram_init_go   (bram_init_go),
        .bram_init_wr   (bram_init_wr),
        .bram_init_addr (bram_init_addr),
        .bram_init_data (bram_init_data),
        .bram_do_a      (bram_do_a),
        .bram_do_b      (bram_do_b),
        .bram_ram_a_q   (bram_ram_a_q),
        .dsp_drive      (dsp_drive),
        .dsp_p          (dsp_p)
    );

    assign configured = done;

    // USER1 sr is superseded by the routed per-CLB SR (M4).
    wire _unused = &{1'b0, committed, ir_value, sr,
                     ctrl_cfg[CTRL_W-1:`BOB_CTRL_CLK_DIV_LO + `BOB_CTRL_CLK_DIV_W]};

endmodule

`default_nettype wire
