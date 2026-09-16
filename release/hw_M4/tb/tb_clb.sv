// -----------------------------------------------------------------------------
// tb_clb.sv - M4 CLB flag sweep against tools/bob/model.py
//
// Drives clb.sv directly: every combination of its seven flags, random INITs,
// random LUT inputs / carry-in / routed CE and SR / gce / GSR / GWE, one clock
// edge per step. hw/tb/clb_vectors.vh (sim/gen_clb_vectors.py) holds the
// model's expected o/o5/cout before the edge and o after it.
//
//   sim/run_clb_sim.sh
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module tb_clb;
    import clb_pkg::*;

    reg                  clk = 1'b0;
    reg                  gce = 1'b0, ce = 1'b0, sr = 1'b0, gsr = 1'b0, gwe = 1'b0, cin = 1'b0;
    reg  [LUT_K-1:0]     i   = '0;
    reg  [CLB_CFG_W-1:0] cfg = '0;
    wire                 o, o5, cout;

    integer errors = 0;
    integer checks = 0;

    clb dut (
        .clk(clk), .gce(gce), .ce(ce), .sr(sr), .gsr(gsr), .gwe(gwe),
        .i(i), .cin(cin), .cfg(cfg), .o(o), .o5(o5), .cout(cout)
    );

    task automatic step(input [CLB_CFG_W-1:0] c, input [LUT_K-1:0] vi,
                        input vcin, input vce, input vsr, input vgce, input vgsr, input vgwe,
                        input eo_pre, input known_pre, input eo5, input ecout, input eo_post);
        begin
            cfg = c; i = vi; cin = vcin; ce = vce; sr = vsr;
            gce = vgce; gsr = vgsr; gwe = vgwe;
            #1;
            if (known_pre) begin
                checks = checks + 1;
                if (o !== eo_pre) begin
                    errors = errors + 1;
                    $display("  FAIL  o before edge: cfg=%h i=%b got %b exp %b", c, vi, o, eo_pre);
                end
            end
            checks = checks + 2;
            if (o5 !== eo5) begin
                errors = errors + 1;
                $display("  FAIL  o5: cfg=%h i=%b got %b exp %b", c, vi, o5, eo5);
            end
            if (cout !== ecout) begin
                errors = errors + 1;
                $display("  FAIL  cout: cfg=%h i=%b cin=%b got %b exp %b", c, vi, vcin, cout, ecout);
            end
            clk = 1'b1;
            #1;
            checks = checks + 1;
            if (o !== eo_post) begin
                errors = errors + 1;
                $display("  FAIL  o after edge: cfg=%h i=%b ce=%b sr=%b gce=%b gsr=%b gwe=%b got %b exp %b",
                         c, vi, vce, vsr, vgce, vgsr, vgwe, o, eo_post);
            end
            clk = 1'b0;
            #1;
        end
    endtask

    initial begin
        $display("");
        $display("=== M4 CLB flag sweep vs tools/bob/model.py: LUT K = %0d, %0d config bits ===",
                 LUT_K, CLB_CFG_W);
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
