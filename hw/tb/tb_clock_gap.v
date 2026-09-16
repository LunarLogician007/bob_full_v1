// -----------------------------------------------------------------------------
// tb_clock_gap.v - clock_ctrl's user-clock spacing guard (M13)
//
// gce pulses must be at least 2**GAP_SHIFT sysclk cycles apart in both modes, even
// when step requests arrive faster (docs/bitstream-format.md section 11): that is
// what makes the fabric's 256-cycle multicycle constraint true on the board.
//   [1] steps every 3 cycles (far faster than the gap): min spacing >= 2**GAP_SHIFT
//       and no request lost while the gap allows one per window
//   [2] slow steps (every 40 cycles): one gce per step, none delayed past the gap
//   [3] free-running with the shortest divider: spacing exactly 2**MIN_SHIFT
// -----------------------------------------------------------------------------
`timescale 1ns / 1ps
`default_nettype none

module tb_clock_gap;
    localparam integer GAP = 4;                   // 2**4 = 16 cycles
    reg sysclk = 1'b0, tck = 1'b0, mode = 1'b0, ce = 1'b0, step = 1'b0;
    reg [4:0] div = 5'd0;
    wire gce, gsr_s, gwe_s, cin_s;
    integer errors = 0, checks = 0, last = -1000, mingap = 1000000, pulses = 0, cyc = 0;

    always #2 sysclk = ~sysclk;
    always @(posedge sysclk) begin
        cyc = cyc + 1;
        if (gce) begin
            if (last >= 0 && cyc - last < mingap) mingap = cyc - last;
            last = cyc;
            pulses = pulses + 1;
        end
    end

    clock_ctrl #(.DIV_W(5), .MIN_SHIFT(GAP), .GAP_SHIFT(GAP)) dut (
        .sysclk(sysclk), .tck(tck), .clk_mode(mode), .clk_div(div), .ce(ce), .step(step),
        .cin(1'b0), .gsr(1'b0), .gwe(1'b1), .gce(gce), .gsr_s(gsr_s), .gwe_s(gwe_s), .cin_s(cin_s));

    task check(input [255:0] what, input integer got, input integer lo, input integer hi);
        begin
            checks = checks + 1;
            if (got < lo || got > hi) begin
                errors = errors + 1;
                $display("  FAIL  %0s = %0d, want %0d..%0d", what, got, lo, hi);
            end else
                $display("  PASS  %0s = %0d", what, got);
        end
    endtask

    integer i;
    initial begin
        $display("\n=== clock_ctrl: user-clock enables at least 2**GAP_SHIFT sysclk cycles apart (M13) ===");
        repeat (40) @(posedge sysclk);
        mingap = 1000000; pulses = 0;
        for (i = 0; i < 60; i = i + 1) begin                     // a step request every 6 cycles
            step = 1'b1; repeat (3) @(posedge sysclk);
            step = 1'b0; repeat (3) @(posedge sysclk);
        end
        repeat (60) @(posedge sysclk);
        check("[1] fast steps: min spacing", mingap, 16, 1000000);
        check("[1] fast steps: pulses", pulses, 360 / 16 - 1, 360 / 16 + 2);

        mingap = 1000000; pulses = 0;
        for (i = 0; i < 20; i = i + 1) begin                     // a step request every 40 cycles
            step = 1'b1; repeat (3) @(posedge sysclk);
            step = 1'b0; repeat (37) @(posedge sysclk);
        end
        check("[2] slow steps: one gce per step", pulses, 20, 20);
        check("[2] slow steps: spacing", mingap, 40, 40);

        mingap = 1000000; pulses = 0;
        mode = 1'b1;
        repeat (16 * 30) @(posedge sysclk);
        mode = 1'b0;
        check("[3] free-running div 0: spacing", mingap, 16, 16);

        $display("\n    %0d checks", checks);
        if (errors == 0) $display("=== ALL TESTS PASSED ===");
        else             $display("=== %0d CHECK(S) FAILED ===", errors);
        if (errors != 0) $fatal(1);
        $finish;
    end
endmodule
`default_nettype wire
