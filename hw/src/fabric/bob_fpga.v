// -----------------------------------------------------------------------------
// bob_fpga.v - the complete bob FPGA (M7): generated fabric behind the
// scan-chain configuration plane, board-independent
//
// No BUFG, no pin assignments, no vendor primitives: the identical file runs in
// simulation and in synthesis. Sizes come from bob_params.vh (tools/bob/device.py).
//
// Configuration (docs/bitstream-format.md sections 4-11):
//   jtag_tap6    6-bit AMD 7-series IR (CFG_IN/CFG_OUT/USER1-4/JPROGRAM/JSTART/DSP,
//                private CHAIN_IN/CHAIN_OUT/INTEST)
//   cfg_frames   M13: UG470-style packets on CFG_IN/CFG_OUT - sync word, type-1/2
//                packets, FAR/FDRI/FDRO/CMD/STAT/IDCODE/CRC, frames of 4 words
//   cfg_ctrl     the chain's CRC-32C + length check (CHAIN_IN); GSR/GTS/GWE/DONE
//                startup after either path
//   u_store      the configuration memory: NFRAMES frames, written by the chain
//                (shift register + shadow) or frame by frame; both only while GWE = 0
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
    wire                sel_chain_in, sel_chain_out;
    wire                cfg_so, pkt_so, ctrl_so, cap_so, bram_so, dsp_so;
    wire                jprogram, jstart_tick;
    wire [3:0]          ir_status;
    wire                ce, sr, cin, step_pulse;
    wire [5:0]          ir_value;

    // configuration plane
    wire                cfg_capture, cfg_shift, cfg_commit, cfg_clear;
    wire                gsr, gts, gwe, done, committed;
    wire [CHAIN_W-1:0]  chain_cfg;                    // chain bit k = chain_cfg[k] = memory bit k
    localparam integer  FIDX_W = 8;
    wire                frame_we, frame_load, frames_ok, frames_error, frames_crc_error;
    wire [FIDX_W-1:0]   frame_idx, fdro_idx;
    wire [`BOB_FRAME_BITS-1:0] rd_frame;
    wire [`BOB_FRAME_BITS-1:0] frame_load_data;
    wire [31:0]         frames_stat;
    wire                freeze, frozen;               // M14: partial reconfiguration hold
    wire                bf_wr_t, bf_rd_t;             // M15: BRAM content frames
    wire [3:0]          bf_tgt;
    wire [9:0]          bf_addr;
    wire [71:0]         bf_data, bf_rdata;
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
        .sel_chain_in  (sel_chain_in),
        .sel_chain_out (sel_chain_out),
        .sel_ctrl    (sel_ctrl),
        .sel_capture (sel_capture),
        .sel_bram    (sel_bram),
        .sel_dsp     (sel_dsp),
        .cfg_so      (cfg_so),
        .pkt_so      (pkt_so),
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
        .sel_cfg_in  (sel_chain_in),          // M13: the chain lives on CHAIN_IN / CHAIN_OUT
        .sel_cfg_out (sel_chain_out),
        .sel_ctrl    (sel_ctrl),
        .jprogram    (jprogram),
        .jstart_tick (jstart_tick),
        .frames_ok        (frames_ok),
        .frames_error     (frames_error),
        .frames_crc_error (frames_crc_error),
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

    cfg_frames #(
        .IDCODE_VALUE (IDCODE_VALUE),
        .FW           (`BOB_FRAME_WORDS),
        .NFRAMES      (`BOB_NFRAMES),
        .NCOLS        (`BOB_FAR_NCOLS),
        .FAR_TABLE    (`BOB_FAR_TABLE),
        .FIDX_W       (FIDX_W),
        .NBRAM        (NBRAM)
    ) u_frames (
        .tck        (tck),
        .tdi        (tdi),
        .dr_capture (dr_capture),
        .dr_shift   (dr_shift),
        .sel_in     (sel_cfg_in),
        .sel_out    (sel_cfg_out),
        .jprogram   (jprogram),
        .gsr        (gsr),
        .gts        (gts),
        .gwe        (gwe),
        .done       (done),
        .frozen_ack (frozen),
        .freeze     (freeze),
        .rd_frame   (rd_frame),
        .rd_idx     (fdro_idx),
        .bf_wr_t    (bf_wr_t),
        .bf_rd_t    (bf_rd_t),
        .bf_tgt     (bf_tgt),
        .bf_addr    (bf_addr),
        .bf_data    (bf_data),
        .bf_rdata   (bf_rdata),
        .so         (pkt_so),
        .frame_load      (frame_load),
        .frame_load_data (frame_load_data),
        .frame_we   (frame_we),
        .frame_idx  (frame_idx),
        .start_ok   (frames_ok),
        .any_error  (frames_error),
        .crc_error  (frames_crc_error),
        .stat       (frames_stat)
    );

    // chain: TDI -> memory bit CHAIN_W-1 ... bit 0 -> TDO; frames: frame f = bits [FB*f +: FB]
    cfg_store #(.FB(`BOB_FRAME_BITS), .NFRAMES(`BOB_NFRAMES), .FIDX_W(FIDX_W)) u_store (
        .tck        (tck),
        .chain_in   (sel_chain_in),
        .chain_out  (sel_chain_out),
        .capture    (cfg_capture),
        .shift      (cfg_shift),
        .wen        (~gwe),                    // chain writes only before startup
        .clear      (cfg_clear),
        .si         (tdi),
        .so         (cfg_so),
        .load       (frame_load),
        .load_data  (frame_load_data),
        .frame_we   (frame_we),
        .frame_idx  (frame_idx),
        .fdro_idx   (fdro_idx),
        .rd_frame   (rd_frame),
        .cfg        (chain_cfg)
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
        .MIN_SHIFT (DIV_MIN_SHIFT),
        .GAP_SHIFT (DIV_MIN_SHIFT)            // M13: gce >= 2**8 sysclk cycles apart on the board
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
        .freeze   (freeze),
        .frozen   (frozen),
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
        .init_data  (bram_init_data),
        .bf_wr_t    (bf_wr_t),
        .bf_rd_t    (bf_rd_t),
        .bf_tgt     (bf_tgt),
        .bf_addr    (bf_addr),
        .bf_data    (bf_data),
        .bf_rdata   (bf_rdata)
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
    // The generated fabric (tools/bob/fabric_gen.py). Nothing in bob_top keeps its
    // hierarchy, as at M7: any keep_hierarchy (on u_fabric, or even on u_clk and
    // u_bram_jtag) made Vivado 2025.2 crash while breaking the unconfigured routing
    // loops (M13 builds 1 and 2). The XDC relaxes sysclk by clock, not by fabric names
    // (docs/bitstream-format.md section 11).
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
    wire _unused = &{1'b0, committed, cfg_commit, ir_value, sr, frames_stat,
                     ctrl_cfg[CTRL_W-1:`BOB_CTRL_CLK_DIV_LO + `BOB_CTRL_CLK_DIV_W]};

endmodule

`default_nettype wire
