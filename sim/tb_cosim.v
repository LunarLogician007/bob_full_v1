// -----------------------------------------------------------------------------
// tb_cosim.v - golden co-simulation (M10)
//
// Every example (and pin variant) runs three ways at once, on the same inputs:
//   source   the example's own Verilog (work/examples/<top>.v)
//   golden   its synthesised netlist with every net named (software/bob/golden.py)
//   fabric   the complete bob FPGA RTL, loaded with the chain from the design's
//            .bit (software/bob/cli.py build) through CFG_IN, BRAM contents over USER4
//
// Per cycle: inputs applied (the source sees them as sw/btn, the fabric through
// the design's pins); before the edge the fabric LEDs must equal the source's,
// and the golden netlist's must too; one user clock (USER1 step) and one source
// clock; the LEDs again; then CAPTURE, where every CLB that holds a flip-flop
// must read the golden netlist's value of that register.
//
// Mac-only (needs work/examples/ and build/): sim/run_cosim_sim.sh
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module tb_cosim;

    `include "bob_harness.vh"

    reg  [5:0]                src_in = 6'b0;
    reg  [2:0]                exp_led, gld_led;
    reg  [`BOB_NCAP-1:0]      cap_exp, cap_mask;
    integer                   cur = -1;
    integer                   dcycles = 0;
    integer                   dcaps = 0;

    `include "cosim_designs.vh"

    task cos_vec(input [5:0] src_v, input [5:0] board_v);
        begin
            src_in = src_v;
            pad_i  = board_v;
            #20;
            checks = checks + 1;
            if (pad_o !== exp_led || gld_led !== exp_led) begin
                errors = errors + 1;
                if (errors < 20)
                    $display("  FAIL  %0s cycle %0d before edge: fabric %b source %b golden %b",
                             dname, dcycles, pad_o, exp_led, gld_led);
            end
            write_user1(32'h8);
            src_clock(1'b1);
            #1 src_clock(1'b0);
            write_user1(32'h0);
            #20;
            checks = checks + 1;
            if (pad_o !== exp_led || gld_led !== exp_led) begin
                errors = errors + 1;
                if (errors < 20)
                    $display("  FAIL  %0s cycle %0d after edge: fabric %b source %b golden %b",
                             dname, dcycles, pad_o, exp_led, gld_led);
            end
            if (cap_mask != 0) begin
                shift_ir(IR_CAPTURE, irc);
                shift_cap(capx);
                checks = checks + 1;
                if ((capx & cap_mask) !== (cap_exp & cap_mask)) begin
                    errors = errors + 1;
                    if (errors < 20)
                        $display("  FAIL  %0s cycle %0d CAPTURE %h golden %h (mask %h)",
                                 dname, dcycles, capx & cap_mask, cap_exp & cap_mask, cap_mask);
                end else
                    dcaps = dcaps + 1;
            end
            dcycles = dcycles + 1;
        end
    endtask

    task finish_design;
        begin
            $display("  PASS  %0s   (%0d cycles: LEDs == source == golden before and after each edge; %0d CAPTUREs == golden registers)",
                     dname, dcycles, dcaps);
            dcycles = 0;
            dcaps = 0;
        end
    endtask

    initial begin
        $display("");
        $display("=== golden co-simulation: source Verilog vs the fabric loaded from .bit (M10; VPR and Python PnR, M12) ===");
        tick(1'b1, 1'b0); tick(1'b1, 1'b0); tick(1'b1, 1'b0); tick(1'b1, 1'b0); tick(1'b1, 1'b0);
        tick(1'b0, 1'b0);
        run_cosim;
        $display("");
        $display("    %0d checks", checks);
        if (errors == 0) $display("=== ALL TESTS PASSED ===");
        else             $display("=== %0d CHECK(S) FAILED ===", errors);
        if (errors != 0) $fatal(1);
        $finish;
    end

endmodule

`default_nettype wire
