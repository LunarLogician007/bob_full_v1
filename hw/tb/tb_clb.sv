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

    integer errors = 0;
    integer checks = 0;

    bob_clb dut (
        .clk(clk), .gce(gce), .gsr(gsr), .gwe(gwe), .ce(ce), .sr(sr), .cin(cin),
        .i(i), .cfg(cfg), .o(o), .cout(cout)
    );

    task automatic step(input [W-1:0] c, input [NI-1:0] vi,
                        input vcin, input vce, input vsr, input vgce, input vgsr, input vgwe,
                        input [NO-1:0] eo_pre, input known_pre, input ecout, input [NO-1:0] eo_post);
        begin
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
        $display("=== M21 cluster vs software/bob/model.py: %0d elements, LUT K = %0d, %0d inputs, %0d config bits ===",
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
