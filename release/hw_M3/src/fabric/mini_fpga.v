// -----------------------------------------------------------------------------
// mini_fpga.v - one CLB inside a boundary scan ring, configured over JTAG
//
// Board-independent: no BUFG, no pin assignments, no vendor primitives, so the
// identical file runs in simulation and in synthesis.
//
//        .----------------------- boundary -----------------------.
//        |                                                        |
//  pad_i[5:0] >-[ in_i5..in_i0 ]-> clb_i[5:0] --.                 |
//        |                                      |                 |
//        |                                   [  CLB  ]            |
//        |            cfg_out[70:0] --------->[ LUT6  ]           |
//        |            ce / sr / cin --------->[ +FF   ]           |
//        |                                    [+carry]            |
//        |                                      |                 |
//        |                   o, o5, cout -[ out cells ]-----------|--> pad_o
//        '--------------------------------------------------------'
//
//   scan chain:  TDI -> in_i5 -> ... -> in_i0 -> out_cout -> out_o5 -> out_o -> TDO
//
// The boundary register is 9 bits, shifted LSB first with the cell nearest TDO
// first, so the numbering is the same whether reading or writing:
//
//   bit  cell      captures     drives
//   0    out_o     clb o        pad_o[0]
//   1    out_o5    clb o5       pad_o[1]
//   2    out_cout  clb cout     pad_o[2]
//   3-8  in_i0..5  pad_i[0..5]  the LUT's i[0..5]
//
// Bits 8:3 are the input vector you apply; bits 2:0 are the answers you read.
//
// INTEST is pipelined by one scan: the outputs captured at Capture-DR reflect
// the vector committed at the PREVIOUS Update-DR. Walking a truth table is
// therefore one drscan per row plus one extra at the end to collect the last
// answer. host/minifpga.py does this for you.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module mini_fpga #(
    parameter [31:0] IDCODE_VALUE = 32'h2BEEF093
)(
    input  wire       tck,
    input  wire       tms,
    input  wire       tdi,
    output wire       tdo,

    input  wire [5:0] pad_i,       // system-side inputs  (switches, buttons)
    output wire [2:0] pad_o,       // system-side outputs {cout, o5, o}

    output wire [3:0] tap_state,   // debug
    output wire       configured   // 1 once a non-zero config has been loaded
);

    // Must match clb_pkg::CLB_CFG_W. clb_pkg.sv is the one place it is defined.
    localparam integer CFG_W = 71;

    wire                bsr_capture, bsr_shift, bsr_update, bsr_mode;
    wire                bsr_si, bsr_so, tlr;
    wire [CFG_W-1:0]    cfg_out;
    wire                ce, sr, cin, step_pulse;

    wire                clb_o, clb_o5, clb_cout;
    wire [5:0]          clb_i;

    jtag_tap #(
        .IDCODE_VALUE (IDCODE_VALUE),
        .CFG_W        (CFG_W)
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
        .cfg_out     (cfg_out),
        .ce          (ce),
        .sr          (sr),
        .cin         (cin),
        .step_pulse  (step_pulse),
        .clb_status  ({clb_cout, clb_o5, clb_o}),
        .tap_state   (tap_state)
    );

    // ---------------------------------------------------------------------
    // The boundary. Cell k is bit k of the scan register; cell 0 sits nearest
    // TDO, so the chain runs downwards from cell 8.
    // ---------------------------------------------------------------------
    wire [8:0] cell_din  = {pad_i[5:0], clb_cout, clb_o5, clb_o};
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
                .trst       (1'b0),          // no TRST pin on this device
                .rst        (tlr),           // consumed on a clock edge inside
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

    assign clb_i = cell_dout[8:3];
    assign pad_o = cell_dout[2:0];

    // ---------------------------------------------------------------------
    // The logic block.
    //
    // Its clock is TCK. That is deliberate: it keeps the entire design in one
    // clock domain, so there is no CDC to get wrong and no free-running core
    // clock to race a scan against. Set FF_CE_EN in the config word and the
    // flop then advances only on an explicit single-step from USER, which is
    // exact rather than approximate.
    // ---------------------------------------------------------------------
    clb u_clb (
        .clk  (tck),
        .ce   (ce | step_pulse),
        .sr   (sr),
        .gsr  (1'b0),        // the single-CLB build keeps the old TAP: no startup
        .gwe  (1'b1),
        .i    (clb_i),
        .cin  (cin),
        .cfg  (cfg_out),
        .o    (clb_o),
        .o5   (clb_o5),
        .cout (clb_cout)
    );

    assign configured = |cfg_out;

endmodule

`default_nettype wire
