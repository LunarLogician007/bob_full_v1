// -----------------------------------------------------------------------------
// tb_clb.sv - the M21 cluster against software/bob/model.py
//
// Drives one bob_clb (generated into bob_fabric.v: N elements of ble.sv behind the
// crossbar) directly: random configurations of every element and every crossbar
// select, random CLB inputs / carry-in / CE / SR / gce / GSR / GWE, one clock edge
// per step. hw/tb/clb_vectors.vh (sim/gen_clb_vectors.py) holds the model's expected
// outputs (all 2N) and cout before the edge and the outputs after it. The M4 flag
// sweep of the single-element clb.sv ran here until M20.
//
// M22: the LUT contents and the crossbar are CFGLUT5s. Every new configuration is loaded
// the way the chip loads it: each of the CLB's L-frames through lut_expand.v, 32 shift
// clocks with that frame's CE (lut_loader.v's sequence); the flags drive cfg directly.
//
//   sim/run_clb_sim.sh
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module tb_clb;
    localparam integer W  = `BOB_CLB_CFG_W;
    localparam integer NI = `BOB_CLB_I;
    localparam integer NO = 2 * `BOB_CLB_N;

    reg           clk = 1'b0;
    reg           gce = 1'b0, ce = 1'b0, sr = 1'b0, gsr = 1'b0, gwe = 1'b0, cin = 1'b0;
    reg  [NI-1:0] i   = '0;
    reg  [W-1:0]  cfg = '0;
    wire [NO-1:0] o;
    wire          cout;

    // M22: the loader's side, driven by the task `load` below
    localparam integer FB  = `BOB_FRAME_BITS;
    localparam integer LFN = `BOB_LF_N;
    localparam integer NS  = `BOB_XBAR_N;
    localparam integer NL  = (NS + 3) / 4;                 // M23: leaves per crossbar pair (lxpair.v)
    reg           lck = 1'b0;
    reg  [LFN-1:0] lce = '0;
    reg  [FB-1:0] lbuf = '0;
    reg  [4:0]    lcnt = '0;
    reg  [W-1:0]  loaded = '0;
    reg           ever = 1'b0;
    wire [2*`BOB_LF_INIT_PER-1:0]  cdi_init;
    wire [`BOB_LF_XBAR_PER/2*NL-1:0] cdi_x;
    integer lf, c;

    lut_expand #(.FB(FB), .K(`BOB_LUT_K), .NI(`BOB_LF_INIT_PER), .XW(`BOB_XBAR_W),
                 .NX(`BOB_LF_XBAR_PER), .S(NS)) u_exp (
        .lbuf(lbuf), .cnt(lcnt), .cdi_init(cdi_init), .cdi_x(cdi_x));

    // one L-frame through the expander: 32 shift clocks with its CE
    task automatic shift_frame(input integer f, input [FB-1:0] data);
        begin
            lbuf = data;
            lce = '0;
            lce[f] = 1'b1;
            for (c = 0; c < 32; c = c + 1) begin
                lcnt = c[4:0];
                #1 lck = 1'b1;
                #1 lck = 1'b0;
            end
            lce = '0;
        end
    endtask

    // A new configuration: the crossbar goes dark first (every select const0, as JPROGRAM
    // leaves it), then the flags, the truth tables and the crossbar. No step between two
    // configurations can then close a combinational loop through the feedback.
    reg [LFN*FB-1:0] cpad;
    task automatic load(input [W-1:0] c_new);
        begin
            cpad = '0;
            cpad[W-1:0] = c_new;                      // the tile's last frame goes on into routing
            shift_frame(0, '0);                       // crossbar frames: tile frame 0 ...
            for (lf = 1 + `BOB_LF_INIT; lf < LFN; lf = lf + 1)
                shift_frame(lf, '0);                  // ... and the tail frames
            cfg = c_new;
            for (lf = 0; lf < LFN; lf = lf + 1)
                shift_frame(lf, cpad[lf*FB +: FB]);
            loaded = c_new;
            ever = 1'b1;
        end
    endtask


    integer errors = 0;
    integer checks = 0;

    bob_clb dut (
        .clk(clk), .gce(gce), .gsr(gsr), .gwe(gwe), .ce(ce), .sr(sr), .cin(cin),
        .i(i), .cfg(cfg[`BOB_CLB_FLAGS_LO +: `BOB_CLB_N * `BOB_ELE_W]),
        .lck(lck), .lce(lce), .lcdi_init(cdi_init), .lcdi_x(cdi_x),
        .o(o), .cout(cout)
    );

    task automatic step(input [W-1:0] c, input [NI-1:0] vi,
                        input vcin, input vce, input vsr, input vgce, input vgsr, input vgwe,
                        input [NO-1:0] eo_pre, input known_pre, input ecout, input [NO-1:0] eo_post);
        begin
            if (!ever || c !== loaded) load(c);
            cfg = c; i = vi; cin = vcin; ce = vce; sr = vsr;
            gce = vgce; gsr = vgsr; gwe = vgwe;
            #1;
            if (known_pre) begin
                checks = checks + 2;
                if (o !== eo_pre) begin
                    errors = errors + 1;
                    if (errors < 20)
                        $display("  FAIL  outputs before edge: cfg=%h i=%h got %h exp %h", c, vi, o, eo_pre);
                end
                if (cout !== ecout) begin
                    errors = errors + 1;
                    if (errors < 20)
                        $display("  FAIL  cout: cfg=%h i=%h cin=%b got %b exp %b", c, vi, vcin, cout, ecout);
                end
            end
            clk = 1'b1;
            #1;
            checks = checks + 1;
            if (o !== eo_post) begin
                errors = errors + 1;
                if (errors < 20)
                    $display("  FAIL  outputs after edge: cfg=%h i=%h ce=%b sr=%b gce=%b gsr=%b gwe=%b got %h exp %h",
                             c, vi, vce, vsr, vgce, vgsr, vgwe, o, eo_post);
            end
            clk = 1'b0;
            #1;
        end
    endtask

    initial begin
        $display("");
        $display("=== M22 CFGLUT5 cluster vs software/bob/model.py: %0d elements, LUT K = %0d, %0d inputs, %0d config bits ===",
                 `BOB_CLB_N, `BOB_LUT_K, NI, W);
        `include "clb_vectors.vh"
        $display("    %0d checks", checks);
        if (errors == 0) $display("=== ALL TESTS PASSED ===");
        else             $display("=== %0d CHECK(S) FAILED ===", errors);
        $display("");
        if (errors != 0) $fatal(1);
        $finish;
    end

endmodule

`default_nettype wire
