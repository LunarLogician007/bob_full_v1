// -----------------------------------------------------------------------------
// tb_clock_gap.v - clock_ctrl's user-clock spacing guard (M13)
//
// gce pulses must be at least 2**GAP_SHIFT sysclk cycles apart in both modes, even
// when step requests arrive faster (docs/bitstream-format.md section 11): that is
// what makes the fabric's 2**GAP_SHIFT-cycle multicycle constraint true on the board
// (512 cycles from M16, 256 through M15).
//   [1] steps every 3 cycles (far faster than the gap): min spacing is EXACTLY
//       2**GAP_SHIFT and no request lost. Exactly, not at least: a request that
//       arrives during the gap is held pending and fires the instant the gap expires,
//       so the spacing is the gap itself. Drop the pending bit and the next request
//       only arrives on the following 6-cycle boundary, so the spacing becomes the
//       first multiple of 6 above the gap - 18 instead of 16, 516 instead of 512.
//       A >= bound cannot see that; the pulse count cannot either once the gap is
//       large (516/512 is a 0.8% error). This is what kills sim/mutate_frames.sh's
//       gce-pending-lost mutant.
//   [2] slow steps (every 40 cycles): one gce per step, none delayed past the gap
//   [3] free-running with the shortest divider: spacing exactly 2**MIN_SHIFT
//   [4] M14 freeze: while frozen no gce at all (free-running and steps), frozen rises
//       with gce held; after release pulses resume at the divider rate
//   [5] M20: clk_period / clk_gap - an integer period, the gap winning over a faster
//       period, the 2-cycle floor, the safe default when the gap is unset, steps at a gap
//
// GAP is a parameter of the check, not a constant of it: every window below is a
// multiple of G = 2**GAP, so the same four checks run at any gap. sim/run_frames_sim.sh
// runs it twice - at 4, which is quick, and at the value the board actually uses
// (`BOB_GCE_MIN_GAP_SHIFT`), because that is the number the XDC's multicycle is
// written against and it had never been simulated before M16.
// -----------------------------------------------------------------------------
`timescale 1ns / 1ps
`default_nettype none

module tb_clock_gap;
`ifdef TB_GAP
    localparam integer GAP = `TB_GAP;
`else
    localparam integer GAP = 4;                   // quick default: 2**4 = 16 cycles
`endif
    localparam integer G = 1 << GAP;              // the guaranteed spacing, in sysclk cycles
    reg sysclk = 1'b0, tck = 1'b0, mode = 1'b0, ce = 1'b0, step = 1'b0, freeze = 1'b0;
    wire frozen;
    integer bad_frozen = 0;
    reg [4:0] div = 5'd0;
    reg [15:0] per = 16'd0, gp = 16'd0;           // M20: 0 = the old behaviour
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
        .sysclk(sysclk), .tck(tck), .clk_mode(mode), .clk_div(div), .clk_period(per), .clk_gap(gp), .ce(ce), .step(step),
        .cin(1'b0), .gsr(1'b0), .gwe(1'b1), .freeze(freeze), .gce(gce), .frozen(frozen),
        .gsr_s(gsr_s), .gwe_s(gwe_s), .cin_s(cin_s));

    always @(posedge sysclk) if (frozen && gce) bad_frozen = bad_frozen + 1;   // never both

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
        $display("\n=== clock_ctrl: user-clock enables at least 2**GAP_SHIFT sysclk cycles apart (M13), freeze (M14); GAP = %0d (%0d cycles) ===", GAP, G);
        repeat (40) @(posedge sysclk);
        mingap = 1000000; pulses = 0;
        // 20 gap-windows' worth of requests, arriving every 6 cycles: far faster than
        // the gap allows, so the guard decides the spacing, not the stimulus.
        for (i = 0; i < 20 * G / 6; i = i + 1) begin
            step = 1'b1; repeat (3) @(posedge sysclk);
            step = 1'b0; repeat (3) @(posedge sysclk);
        end
        repeat (2 * G) @(posedge sysclk);                       // let any pending request drain
        check("[1] fast steps: min spacing is exactly the gap", mingap, G, G);
        check("[1] fast steps: pulses", pulses, 20 - 2, 20 + 2);

        mingap = 1000000; pulses = 0; last = -1000;
        // one request every 2G cycles: slower than the gap, so every one gets its own
        // gce and none is delayed
        for (i = 0; i < 20; i = i + 1) begin
            step = 1'b1; repeat (3) @(posedge sysclk);
            step = 1'b0; repeat (2 * G - 3) @(posedge sysclk);
        end
        check("[2] slow steps: one gce per step", pulses, 20, 20);
        check("[2] slow steps: spacing", mingap, 2 * G, 2 * G);

        mingap = 1000000; pulses = 0; last = -1000;
        mode = 1'b1;
        repeat (G * 30) @(posedge sysclk);
        mode = 1'b0;
        check("[3] free-running div 0: spacing", mingap, G, G);

        // [4] freeze in free-running mode, with step requests on top
        mode = 1'b1;
        repeat (G * 4) @(posedge sysclk);
        freeze = 1'b1;
        repeat (4) @(posedge sysclk);                            // two-flop synchroniser + one edge
        check("[4] frozen acknowledged", frozen, 1, 1);
        pulses = 0;
        for (i = 0; i < 20; i = i + 1) begin
            step = 1'b1; repeat (3) @(posedge sysclk);
            step = 1'b0; repeat (G - 3) @(posedge sysclk);
        end
        check("[4] no gce while frozen", pulses, 0, 0);
        check("[4] never frozen and gce", bad_frozen, 0, 0);
        freeze = 1'b0;
        repeat (4) @(posedge sysclk);
        check("[4] released", frozen, 0, 0);
        mingap = 1000000; pulses = 0; last = -1000;
        repeat (G * 10) @(posedge sysclk);
        mode = 1'b0;
        check("[4] after release: pulses resume", pulses, 9, 11);
        check("[4] after release: spacing", mingap, G, G);

        // [5] M20: a design's own period and gap. Unset (0) is the safe default above;
        //     set, the spacing is exactly what the flow chose - an integer, not a power of 2.
        mingap = 1000000; pulses = 0; last = -1000;
        per = 16'd7; gp = 16'd7; mode = 1'b1;
        repeat (8) @(posedge sysclk);                            // synchronisers
        mingap = 1000000; last = -1000;
        repeat (7 * 40) @(posedge sysclk);
        check("[5] per 7 gap 7", mingap, 7, 7);
        // the period asks for more than the gap allows: the gap wins, requests are held
        per = 16'd3; gp = 16'd5;
        repeat (8) @(posedge sysclk);
        mingap = 1000000; last = -1000;
        repeat (5 * 40) @(posedge sysclk);
        check("[5] per 3 gap 5: gap wins", mingap, 5, 5);
        // clk_div prescales a set period: 3 x 2**2 = 12, an integer rate at any scale
        per = 16'd3; gp = 16'd2; div = 5'd2;
        repeat (8) @(posedge sysclk);
        mingap = 1000000; last = -1000;
        repeat (12 * 30) @(posedge sysclk);
        check("[5] per 3 div 2 = 12", mingap, 12, 12);
        div = 5'd0;
        // a gap below the hardware floor is raised to it
        per = 16'd1; gp = 16'd1;
        repeat (8) @(posedge sysclk);
        mingap = 1000000; last = -1000;
        repeat (100) @(posedge sysclk);
        check("[5] gap 1: floor 2", mingap, 2, 2);
        // gap unset with a fast period: the safe default 2**GAP_SHIFT still holds
        per = 16'd3; gp = 16'd0;
        repeat (8) @(posedge sysclk);
        mingap = 1000000; last = -1000;
        repeat (G * 10) @(posedge sysclk);
        check("[5] per 3 gap 0: safe G", mingap, G, G);
        // stepped requests at a set gap: exactly the gap, as [1] is at the default
        mode = 1'b0; per = 16'd0; gp = 16'd5;
        repeat (8) @(posedge sysclk);
        mingap = 1000000; last = -1000;
        for (i = 0; i < 40; i = i + 1) begin                    // a request every 4 cycles
            step = 1'b1; repeat (2) @(posedge sysclk);
            step = 1'b0; repeat (2) @(posedge sysclk);
        end
        repeat (20) @(posedge sysclk);
        check("[5] steps at gap 5", mingap, 5, 5);
        gp = 16'd0;

        $display("\n    %0d checks", checks);
        if (errors == 0) $display("=== ALL TESTS PASSED ===");
        else             $display("=== %0d CHECK(S) FAILED ===", errors);
        if (errors != 0) $fatal(1);
        $finish;
    end
endmodule
`default_nettype wire
