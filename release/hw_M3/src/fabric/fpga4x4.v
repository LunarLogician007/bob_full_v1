// -----------------------------------------------------------------------------
// fpga4x4.v - a 4x4 CLB fabric behind the scan-chain configuration plane
//
// Board-independent: no BUFG, no pin assignments, no vendor primitives, so the
// identical file runs in simulation and in synthesis.
//
// M3: the configuration now goes through the M2 plane, proven on silicon in
// cfg_test_top (docs/bitstream-format.md):
//   jtag_tap6    6-bit AMD 7-series IR (CFG_IN/CFG_OUT/USER1-3/JPROGRAM/JSTART)
//   cfg_ctrl     CRC-32C + length check before commit; GSR/GTS/GWE/DONE startup
//   cfg_mem      16 x 181-bit tiles, shift register + shadow each; the fabric
//                reads only the shadow bus, laid out exactly as before
//   capture      USER3 snapshots the 16 CLB outputs
//
// Startup signals in the fabric:
//   GSR  every CLB flip-flop held at its INIT (ff_rstval), regardless of FF_SR_EN
//   GWE  0 freezes every CLB flip-flop
//   GTS  fabric outputs forced to 0 before they reach the output boundary cells
//        (EXTEST still drives the pads; true hi-Z arrives with io_tile in M7)
//   DONE `configured` (LD3)
//
// Config chain: 16 tiles x 181 bits = 2896 bits, chain bit k = k-th bit shifted
// in. Tile 0 (row 0, col 0) at the low end; within a tile CLB, then connection
// box, then switch box - tools/bob/device.py is the authority, and
// tests/test_device.py checks these parameter defaults against it.
//
// ---------------------------------------------------------------------------
// Where the pads meet the fabric (unchanged)
// ---------------------------------------------------------------------------
//   inputs   every row's West edge carries pad_i[3:0] on tracks 0..3
//            every column's South edge carries pad_i[4] on track 0
//                                        and pad_i[5] on track 1
//   outputs  pad_o[k] is row k's East edge, track 0, for k = 0,1,2
//
// The 9-bit boundary ring is unchanged from the single-CLB build.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module fpga4x4 #(
    parameter [31:0] IDCODE_VALUE   = 32'h5BEEF093,
    parameter [31:0] USERCODE_VALUE = 32'h00000003,
    parameter integer GRID_R = 4,
    parameter integer GRID_C = 4,
    parameter integer NTRACK = 4,
    parameter integer TILE_W = 181
)(
    input  wire       tck,
    input  wire       tms,
    input  wire       tdi,
    output wire       tdo,

    input  wire [5:0] pad_i,
    output wire [2:0] pad_o,

    output wire [3:0] tap_state,
    output wire       configured     // DONE
);

    localparam integer NTILE = GRID_R * GRID_C;
    localparam integer CFG_W = NTILE * TILE_W;     // 2896

    // TAP
    wire                bsr_capture, bsr_shift, bsr_update, bsr_mode;
    wire                bsr_si, bsr_so, tlr;
    wire                dr_capture, dr_shift, dr_update;
    wire                sel_cfg_in, sel_cfg_out, sel_ctrl, sel_capture;
    wire                cfg_so, ctrl_so, cap_so;
    wire                jprogram, jstart_tick;
    wire [3:0]          ir_status;
    wire                ce, sr, cin, step_pulse;
    wire [5:0]          ir_value;

    // configuration plane
    wire                cfg_capture, cfg_shift, cfg_commit, cfg_clear;
    wire                gsr, gts, gwe, done, committed;
    wire [CFG_W-1:0]    cfg_out;

    // fabric
    wire [NTILE-1:0]    clb_o, clb_o5;
    wire [GRID_C-1:0]   carry_out;
    wire [5:0]          fab_i;      // fabric-side of the input boundary cells
    wire [2:0]          fab_o;      // fabric-side of the output boundary cells

    jtag_tap6 #(
        .IDCODE_VALUE   (IDCODE_VALUE),
        .USERCODE_VALUE (USERCODE_VALUE),
        .STATUS_W       (NTILE),           // USER1 returns every CLB's o
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
        .cfg_so      (cfg_so),
        .ctrl_so     (ctrl_so),
        .cap_so      (cap_so),
        .jprogram    (jprogram),
        .jstart_tick (jstart_tick),
        .ir_status   (ir_status),
        .ce          (ce),
        .sr          (sr),
        .cin         (cin),
        .step_pulse  (step_pulse),
        .user_status (clb_o),
        .tap_state   (tap_state),
        .ir_value    (ir_value)
    );

    cfg_ctrl #(.CHAIN_W(CFG_W)) u_ctrl (
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

    cfg_mem #(.NTILE(NTILE), .TILE_W(TILE_W)) u_mem (
        .tck     (tck),
        .capture (cfg_capture),
        .shift   (cfg_shift),
        .commit  (cfg_commit),
        .clear   (cfg_clear),
        .si      (tdi),
        .so      (cfg_so),
        .cfg     (cfg_out)
    );

    capture_chain #(.N(NTILE)) u_cap (
        .tck     (tck),
        .capture (sel_capture & dr_capture),
        .shift   (sel_capture & dr_shift),
        .tdi     (tdi),
        .d       (clb_o),
        .so      (cap_so)
    );

    // ---------------------------------------------------------------------
    // The boundary. Cell k is bit k of the scan register; cell 0 sits nearest
    // TDO, so the chain runs downwards from cell 8. The output cells see the
    // fabric only once GTS is released.
    // ---------------------------------------------------------------------
    wire [2:0] fab_o_gts = gts ? 3'b000 : fab_o;
    wire [8:0] cell_din  = {pad_i[5:0], fab_o_gts};
    wire [8:0] cell_dout;
    wire [8:0] cell_si;
    wire [8:0] cell_so;

    assign cell_si[8] = bsr_si;
    assign bsr_so     = cell_so[0];

    genvar k;
    generate
        for (k = 0; k < 9; k = k + 1) begin : g_bsr
            if (k < 8) begin : g_link
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

    assign fab_i = cell_dout[8:3];
    assign pad_o = cell_dout[2:0];

    // ---------------------------------------------------------------------
    // Edge buses. See the header for the mapping.
    // ---------------------------------------------------------------------
    wire [GRID_R*NTRACK-1:0] west_in, east_in, west_out, east_out;
    wire [GRID_C*NTRACK-1:0] south_in, north_in, south_out, north_out;

    genvar r, c;
    generate
        for (r = 0; r < GRID_R; r = r + 1) begin : g_west
            assign west_in[r*NTRACK +: NTRACK] = fab_i[3:0];
        end
        for (c = 0; c < GRID_C; c = c + 1) begin : g_south
            assign south_in[c*NTRACK +: NTRACK] = {{(NTRACK-2){1'b0}}, fab_i[5], fab_i[4]};
        end
    endgenerate

    assign north_in = {GRID_C*NTRACK{1'b0}};
    assign east_in  = {GRID_R*NTRACK{1'b0}};

    generate
        for (k = 0; k < 3; k = k + 1) begin : g_out
            assign fab_o[k] = east_out[k*NTRACK + 0];
        end
    endgenerate

    fabric #(
        .GRID_R (GRID_R),
        .GRID_C (GRID_C),
        .NTRACK (NTRACK),
        .TILE_W (TILE_W)
    ) u_fabric (
        .clk       (tck),
        .ce        (ce | step_pulse),
        .sr        (sr),
        .gsr       (gsr),
        .gwe       (gwe),
        .cin       (cin),
        .cfg       (cfg_out),
        .west_in   (west_in),
        .east_in   (east_in),
        .south_in  (south_in),
        .north_in  (north_in),
        .west_out  (west_out),
        .east_out  (east_out),
        .south_out (south_out),
        .north_out (north_out),
        .clb_o     (clb_o),
        .clb_o5    (clb_o5),
        .carry_out (carry_out)
    );

    assign configured = done;

    // Not every edge track leaves the chip; keep the unused ones from being
    // optimised into a warning.
    wire _unused = &{1'b0, west_out, north_out, south_out, east_out,
                     clb_o5, carry_out, committed, ir_value};

endmodule

`default_nettype wire
