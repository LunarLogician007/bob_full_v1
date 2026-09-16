// -----------------------------------------------------------------------------
// tb_bram.v - bram_core.v against tools/bob/model.py (M5)
//
// All 3 x 3 write-mode and 2 x 2 output-register combinations: GSR, preload and
// readback through the init port, then random two-port operations. Expected
// DO_A / DO_B / port-A RAM read come from sim/gen_bram_vectors.py.
//
//   sim/run_bram_sim.sh
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module tb_bram;

    reg        clk = 1'b0;
    reg        gce = 1'b0, gsr = 1'b0, gwe = 1'b0;
    reg [1:0]  wmode_a = 2'd0, wmode_b = 2'd0;
    reg        reg_a = 1'b0, reg_b = 1'b0;
    reg [9:0]  addr_a = 10'd0, addr_b = 10'd0;
    reg [17:0] di_a = 18'd0, di_b = 18'd0;
    reg        we_a = 1'b0, en_a = 1'b0, rst_a = 1'b0, regce_a = 1'b0;
    reg        we_b = 1'b0, en_b = 1'b0, rst_b = 1'b0, regce_b = 1'b0;
    reg        init_go = 1'b0, init_wr = 1'b0;
    wire [17:0] do_a, do_b, ram_a_q;

    integer errors = 0;
    integer checks = 0;

    bram_core #(.ADDR_W(10), .DATA_W(18)) dut (
        .clk(clk), .gce(gce), .gsr(gsr), .gwe(gwe),
        .wmode_a(wmode_a), .wmode_b(wmode_b), .reg_a(reg_a), .reg_b(reg_b),
        .addr_a(addr_a), .di_a(di_a), .we_a(we_a), .en_a(en_a), .rst_a(rst_a), .regce_a(regce_a),
        .addr_b(addr_b), .di_b(di_b), .we_b(we_b), .en_b(en_b), .rst_b(rst_b), .regce_b(regce_b),
        .init_go(init_go), .init_wr(init_wr), .init_addr(addr_a), .init_data(di_a),
        .do_a(do_a), .do_b(do_b), .ram_a_q(ram_a_q)
    );

    task step(input [1:0] wma, input [1:0] wmb, input ra, input rb,
              input [9:0] aa, input [17:0] da, input wea, input ena, input rsta, input rcea,
              input [9:0] ab, input [17:0] db, input web, input enb, input rstb, input rceb,
              input vgce, input vgsr, input vgwe, input vgo, input vwr,
              input [17:0] eda, input [17:0] edb, input [17:0] era);
        begin
            wmode_a = wma; wmode_b = wmb; reg_a = ra; reg_b = rb;
            addr_a = aa; di_a = da; we_a = wea; en_a = ena; rst_a = rsta; regce_a = rcea;
            addr_b = ab; di_b = db; we_b = web; en_b = enb; rst_b = rstb; regce_b = rceb;
            gce = vgce; gsr = vgsr; gwe = vgwe; init_go = vgo; init_wr = vwr;
            #1 clk = 1'b1;
            #1;
            checks = checks + 3;
            // port-A RAM output is compared on init READs only: a WRITE's
            // read-first value is the old contents, X before the first preload
            if (do_a !== eda || do_b !== edb || (vgo && !vwr && ram_a_q !== era)) begin
                errors = errors + 1;
                $display("  FAIL  modes %0d/%0d reg %0d/%0d  A a=%0d we=%b en=%b rst=%b rce=%b  B a=%0d we=%b en=%b rst=%b rce=%b  gce=%b gsr=%b gwe=%b go=%b",
                         wma, wmb, ra, rb, aa, wea, ena, rsta, rcea, ab, web, enb, rstb, rceb, vgce, vgsr, vgwe, vgo);
                $display("        do_a=%h exp %h   do_b=%h exp %h   ram_a=%h exp %h", do_a, eda, do_b, edb, ram_a_q, era);
            end
            #1 clk = 1'b0;
            #1;
        end
    endtask

    initial begin
        $display("");
        $display("=== M5 bram_core vs tools/bob/model.py: WRITE_FIRST/READ_FIRST/NO_CHANGE x DOx_REG ===");
        `include "bram_vectors.vh"
        $display("    %0d checks", checks);
        if (errors == 0) $display("=== ALL TESTS PASSED ===");
        else             $display("=== %0d CHECK(S) FAILED ===", errors);
        $display("");
        if (errors != 0) $fatal(1);
        $finish;
    end

endmodule

`default_nettype wire
