// -----------------------------------------------------------------------------
// cfg_test_top.v - M2: the configuration plane alone on the PYNQ-Z2
//
// Proves the new TAP (6-bit AMD IR) and the scan-chain configuration plane on
// silicon before M3 puts them under the 4x4 fabric. Same board ports as the
// fabric top, so hw/constr/pynq_z2.xdc applies unchanged.
//
//   config chain   4 tiles x 16 bits = 64 bits, through cfg_mem
//   LEDs           LD2..LD0 = cfg[2:0] once GTS is released, else off
//                  LD3      = DONE
//   CAPTURE (16)   [7:0] counter, [9:8] 0, [11:10] SW1..SW0, [15:12] BTN3..BTN0
//   counter        TCK-domain, held at 0 by GSR and by USER1 sr, counts while
//                  GWE and (USER1 ce or step)
//
// No boundary ring: SAMPLE/EXTEST/INTEST act as BYPASS on this top.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module cfg_test_top #(
    parameter [31:0] IDCODE_VALUE   = 32'h4BEEF093,
    parameter [31:0] USERCODE_VALUE = 32'h00000002
)(
    input  wire       tck,
    input  wire       tms,
    input  wire       tdi,
    output wire       tdo,

    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [3:0] led
);

    localparam integer NTILE   = 4;
    localparam integer TILE_W  = 16;
    localparam integer CHAIN_W = NTILE * TILE_W;

    wire tck_g;
`ifdef SIMULATION
    assign tck_g = tck;
`else
    BUFG bufg_tck (.I(tck), .O(tck_g));
`endif

    // TAP <-> data registers
    wire        dr_capture, dr_shift, dr_update;
    wire        sel_cfg_in, sel_cfg_out, sel_ctrl, sel_capture, sel_bram, sel_dsp;
    wire        sel_pkt_in, sel_pkt_out;
    wire        cfg_so, ctrl_so, cap_so;
    wire        jprogram, jstart_tick;
    wire [3:0]  ir_status;
    wire        ce, user_sr, cin, step_pulse;
    wire        bsr_capture, bsr_shift, bsr_update, bsr_mode, bsr_si, tlr;
    wire [3:0]  tap_state;
    wire [5:0]  ir_value;

    // configuration plane
    wire        cfg_capture, cfg_shift, cfg_commit, cfg_clear;
    wire        gsr, gts, gwe, done, committed;
    wire [CHAIN_W-1:0] cfg;

    reg  [7:0]  counter = 8'h0;

    jtag_tap6 #(
        .IDCODE_VALUE   (IDCODE_VALUE),
        .USERCODE_VALUE (USERCODE_VALUE),
        .STATUS_W       (8),
        .BSR_PRESENT    (0)
    ) u_tap (
        .tck         (tck_g),
        .tms         (tms),
        .tdi         (tdi),
        .tdo         (tdo),
        .bsr_capture (bsr_capture),
        .bsr_shift   (bsr_shift),
        .bsr_update  (bsr_update),
        .bsr_mode    (bsr_mode),
        .bsr_si      (bsr_si),
        .bsr_so      (1'b0),
        .tlr         (tlr),
        .dr_capture  (dr_capture),
        .dr_shift    (dr_shift),
        .dr_update   (dr_update),
        .sel_cfg_in  (sel_pkt_in),                // M13: packet port, unused by this top
        .sel_cfg_out (sel_pkt_out),
        .sel_chain_in  (sel_cfg_in),              // the chain moved to CHAIN_IN / CHAIN_OUT
        .sel_chain_out (sel_cfg_out),
        .sel_ctrl    (sel_ctrl),
        .sel_capture (sel_capture),
        .sel_bram    (sel_bram),
        .sel_dsp     (sel_dsp),
        .cfg_so      (cfg_so),
        .pkt_so      (1'b0),
        .ctrl_so     (ctrl_so),
        .cap_so      (cap_so),
        .bram_so     (1'b0),
        .dsp_so      (1'b0),
        .jprogram    (jprogram),
        .jstart_tick (jstart_tick),
        .ir_status   (ir_status),
        .ce          (ce),
        .sr          (user_sr),
        .cin         (cin),
        .step_pulse  (step_pulse),
        .user_status (counter),
        .tap_state   (tap_state),
        .ir_value    (ir_value)
    );

    cfg_ctrl #(.CHAIN_W(CHAIN_W)) u_ctrl (
        .tck         (tck_g),
        .tdi         (tdi),
        .dr_capture  (dr_capture),
        .dr_shift    (dr_shift),
        .dr_update   (dr_update),
        .sel_cfg_in  (sel_cfg_in),
        .sel_cfg_out (sel_cfg_out),
        .sel_ctrl    (sel_ctrl),
        .jprogram    (jprogram),
        .jstart_tick (jstart_tick),
        .frames_ok        (1'b0),
        .frames_error     (1'b0),
        .frames_crc_error (1'b0),
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
        .tck     (tck_g),
        .capture (cfg_capture),
        .shift   (cfg_shift),
        .commit  (cfg_commit),
        .clear   (cfg_clear),
        .si      (tdi),
        .so      (cfg_so),
        .cfg     (cfg)
    );

    capture_chain #(.N(16)) u_cap (
        .tck     (tck_g),
        .capture (sel_capture & dr_capture),
        .shift   (sel_capture & dr_shift),
        .tdi     (tdi),
        .d       ({btn, sw, 2'b00, counter}),
        .so      (cap_so)
    );

    // User logic stand-in: something with state for GSR/GWE and CAPTURE to act on.
    always @(posedge tck_g) begin
        if (gsr || user_sr)
            counter <= 8'h0;
        else if (gwe && (ce || step_pulse))
            counter <= counter + 8'h1;
    end

    assign led[2:0] = gts ? 3'b000 : cfg[2:0];
    assign led[3]   = done;

    wire _unused = &{1'b0, sel_pkt_in, sel_pkt_out, bsr_capture, bsr_shift, bsr_update, bsr_mode, bsr_si,
                     tlr, cin, tap_state, ir_value, committed, cfg[CHAIN_W-1:3], sel_bram, sel_dsp};

endmodule

`default_nettype wire
