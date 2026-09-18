// -----------------------------------------------------------------------------
// tb_dsp.v - two cascaded dsp_core.v slices against software/bob/model.py (M6)
//
// Slice 1's PCIN is slice 0's P, as the DSP tile wires them. Every opmode with
// every pre-adder setting, random register stages, full-scale signed inputs,
// random CE/RST/gce/GSR. Expected P of both slices after each clock come from
// sim/gen_dsp_vectors.py.
//
//   sim/run_dsp_sim.sh
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module tb_dsp;

    reg        clk = 1'b0, gce = 1'b0, gsr = 1'b0;
    reg [9:0]  cfg0 = 10'd0, cfg1 = 10'd0;
    reg [24:0] a0 = 0, d0 = 0, a1 = 0, d1 = 0;
    reg [17:0] b0 = 0, b1 = 0;
    reg [47:0] c0 = 0, c1 = 0;
    reg [7:0]  k0 = 0, k1 = 0;
    wire [47:0] p0, p1;

    integer errors = 0;
    integer checks = 0;

    // cfg bits: [1:0] opmode [2] use_d [3] d_sub [4] areg [5] breg [6] creg [7] dreg [8] mreg [9] preg
    // ctrl bits: ce_ad ce_b ce_m ce_p rst_ad rst_b rst_m rst_p
    dsp_core s0 (
        .clk(clk), .gce(gce), .gsr(gsr), .gwe(1'b1),
        .opmode(cfg0[1:0]), .use_d(cfg0[2]), .d_sub(cfg0[3]), .areg(cfg0[4]), .breg(cfg0[5]),
        .creg(cfg0[6]), .dreg(cfg0[7]), .mreg(cfg0[8]), .preg(cfg0[9]),
        .a(a0), .b(b0), .c(c0), .d(d0),
        .ce_ad(k0[0]), .ce_b(k0[1]), .ce_m(k0[2]), .ce_p(k0[3]),
        .rst_ad(k0[4]), .rst_b(k0[5]), .rst_m(k0[6]), .rst_p(k0[7]),
        .pcin(48'd0), .p(p0)
    );

    dsp_core s1 (
        .clk(clk), .gce(gce), .gsr(gsr), .gwe(1'b1),
        .opmode(cfg1[1:0]), .use_d(cfg1[2]), .d_sub(cfg1[3]), .areg(cfg1[4]), .breg(cfg1[5]),
        .creg(cfg1[6]), .dreg(cfg1[7]), .mreg(cfg1[8]), .preg(cfg1[9]),
        .a(a1), .b(b1), .c(c1), .d(d1),
        .ce_ad(k1[0]), .ce_b(k1[1]), .ce_m(k1[2]), .ce_p(k1[3]),
        .rst_ad(k1[4]), .rst_b(k1[5]), .rst_m(k1[6]), .rst_p(k1[7]),
        .pcin(p0), .p(p1)
    );

    task step(input [9:0] vc0, input [9:0] vc1,
              input [24:0] va0, input [17:0] vb0, input [47:0] vcc0, input [24:0] vd0, input [7:0] vk0,
              input [24:0] va1, input [17:0] vb1, input [47:0] vcc1, input [24:0] vd1, input [7:0] vk1,
              input vgce, input vgsr, input [47:0] ep0, input [47:0] ep1);
        begin
            cfg0 = vc0; cfg1 = vc1;
            a0 = va0; b0 = vb0; c0 = vcc0; d0 = vd0; k0 = vk0;
            a1 = va1; b1 = vb1; c1 = vcc1; d1 = vd1; k1 = vk1;
            gce = vgce; gsr = vgsr;
            #1 clk = 1'b1;
            #1;
            checks = checks + 2;
            if (p0 !== ep0 || p1 !== ep1) begin
                errors = errors + 1;
                $display("  FAIL  cfg %h/%h ctrl %b/%b gce=%b gsr=%b: p0=%h exp %h  p1=%h exp %h",
                         vc0, vc1, vk0, vk1, vgce, vgsr, p0, ep0, p1, ep1);
            end
            #1 clk = 1'b0;
            #1;
        end
    endtask

    initial begin
        $display("");
        $display("=== M6 dsp_core x2 (cascade) vs software/bob/model.py: every opmode x pre-adder ===");
        `include "dsp_vectors.vh"
        $display("    %0d checks", checks);
        if (errors == 0) $display("=== ALL TESTS PASSED ===");
        else             $display("=== %0d CHECK(S) FAILED ===", errors);
        $display("");
        if (errors != 0) $fatal(1);
        $finish;
    end

endmodule

`default_nettype wire
