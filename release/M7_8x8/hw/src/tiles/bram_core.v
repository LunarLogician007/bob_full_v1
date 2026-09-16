// -----------------------------------------------------------------------------
// bram_core.v - true dual-port 1024 x 18 block RAM, AMD RAMB18E1 behaviour (M5)
//
// AMD UG473 semantics, trimmed to one width mode (READ_WIDTH = WRITE_WIDTH = 18):
//
//   write modes (per port, config)   WRITE_FIRST  output = data being written
//                                    READ_FIRST   output = old contents
//                                    NO_CHANGE    output holds during a write
//   output latch                     updated only when EN; RST (with EN) -> 0
//   DOx_REG (config)                 optional output register, REGCE enables it,
//                                    RST resets it (RSTREG_PRIORITY = "RSTREG")
//   clocking                         every change needs gce (the user clock
//                                    enable) and GWE; GSR resets latches and
//                                    registers to 0 (SRVAL/INIT = 0), never the
//                                    memory contents
//
// Synthesis: the memory is written in Vivado's true-dual-port READ_FIRST
// template (two processes, one per port), so it maps to one RAMB18 on the
// XC7Z020. WRITE_FIRST and NO_CHANGE are derived from READ_FIRST with a few
// registers after the RAM - which is what lets the mode be a configuration bit
// instead of a synthesis attribute.
//
// Contents are loaded through port A by bram_jtag.v (init_go) while GWE = 0.
//
// Divergences from RAMB18E1, deliberate: single 18-bit width mode (the 9/4/1-bit
// modes need bit-level addressing that would stop RAMB18 inference); one WE per
// port instead of per byte; RSTRAM and RSTREG share one RST pin.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module bram_core #(
    parameter integer ADDR_W = 10,
    parameter integer DATA_W = 18
)(
    input  wire              clk,
    input  wire              gce,
    input  wire              gsr,
    input  wire              gwe,

    input  wire [1:0]        wmode_a,
    input  wire [1:0]        wmode_b,
    input  wire              reg_a,
    input  wire              reg_b,

    input  wire [ADDR_W-1:0] addr_a,
    input  wire [DATA_W-1:0] di_a,
    input  wire              we_a,
    input  wire              en_a,
    input  wire              rst_a,
    input  wire              regce_a,

    input  wire [ADDR_W-1:0] addr_b,
    input  wire [DATA_W-1:0] di_b,
    input  wire              we_b,
    input  wire              en_b,
    input  wire              rst_b,
    input  wire              regce_b,

    // contents access for bram_jtag.v (only ever used while GWE = 0)
    input  wire              init_go,
    input  wire              init_wr,
    input  wire [ADDR_W-1:0] init_addr,
    input  wire [DATA_W-1:0] init_data,

    output wire [DATA_W-1:0] do_a,
    output wire [DATA_W-1:0] do_b,
    output wire [DATA_W-1:0] ram_a_q
);

    localparam [1:0] WRITE_FIRST = 2'd0;
    localparam [1:0] NO_CHANGE   = 2'd2;

    // ---------------------------------------------------------------------
    // The memory: Vivado true-dual-port READ_FIRST template
    // ---------------------------------------------------------------------
    (* ram_style = "block" *)
    reg [DATA_W-1:0] mem [0:(1<<ADDR_W)-1];

    reg [DATA_W-1:0] ram_a = {DATA_W{1'b0}};
    reg [DATA_W-1:0] ram_b = {DATA_W{1'b0}};

    wire user = gwe & gce & ~gsr;

    wire              ce_a  = init_go | (user & en_a);
    wire              wea_e = init_go ? init_wr   : we_a;
    wire [ADDR_W-1:0] ad_a  = init_go ? init_addr : addr_a;
    wire [DATA_W-1:0] d_a   = init_go ? init_data : di_a;
    wire              ce_b  = user & en_b;

    /* verilator lint_off MULTIDRIVEN */
    always @(posedge clk) begin
        if (ce_a) begin
            if (wea_e) mem[ad_a] <= d_a;
            ram_a <= mem[ad_a];
        end
    end

    always @(posedge clk) begin
        if (ce_b) begin
            if (we_b) mem[addr_b] <= di_b;
            ram_b <= mem[addr_b];
        end
    end
    /* verilator lint_on MULTIDRIVEN */

    assign ram_a_q = ram_a;

    // ---------------------------------------------------------------------
    // Output latch, write mode and output register, per port
    // ---------------------------------------------------------------------
    reg              we_qa = 1'b0, rst_qa = 1'b1;
    reg [DATA_W-1:0] din_qa = {DATA_W{1'b0}}, hold_qa = {DATA_W{1'b0}}, reg_qa = {DATA_W{1'b0}};
    reg              we_qb = 1'b0, rst_qb = 1'b1;
    reg [DATA_W-1:0] din_qb = {DATA_W{1'b0}}, hold_qb = {DATA_W{1'b0}}, reg_qb = {DATA_W{1'b0}};

    wire [DATA_W-1:0] latch_a = rst_qa                            ? {DATA_W{1'b0}} :
                                (we_qa && wmode_a == WRITE_FIRST) ? din_qa :
                                (we_qa && wmode_a == NO_CHANGE)   ? hold_qa : ram_a;
    wire [DATA_W-1:0] latch_b = rst_qb                            ? {DATA_W{1'b0}} :
                                (we_qb && wmode_b == WRITE_FIRST) ? din_qb :
                                (we_qb && wmode_b == NO_CHANGE)   ? hold_qb : ram_b;

    always @(posedge clk) begin
        if (gsr) begin
            rst_qa <= 1'b1;
            reg_qa <= {DATA_W{1'b0}};
        end else if (gwe & gce) begin
            if (en_a) begin
                we_qa   <= we_a;
                din_qa  <= di_a;
                rst_qa  <= rst_a;
                hold_qa <= latch_a;
            end
            if (rst_a)        reg_qa <= {DATA_W{1'b0}};
            else if (regce_a) reg_qa <= latch_a;
        end
    end

    always @(posedge clk) begin
        if (gsr) begin
            rst_qb <= 1'b1;
            reg_qb <= {DATA_W{1'b0}};
        end else if (gwe & gce) begin
            if (en_b) begin
                we_qb   <= we_b;
                din_qb  <= di_b;
                rst_qb  <= rst_b;
                hold_qb <= latch_b;
            end
            if (rst_b)        reg_qb <= {DATA_W{1'b0}};
            else if (regce_b) reg_qb <= latch_b;
        end
    end

    assign do_a = reg_a ? reg_qa : latch_a;
    assign do_b = reg_b ? reg_qb : latch_b;

endmodule

`default_nettype wire
