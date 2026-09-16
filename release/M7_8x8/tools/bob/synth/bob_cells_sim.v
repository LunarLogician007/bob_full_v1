// -----------------------------------------------------------------------------
// bob_cells_sim.v - the bob cell library (M8): what yosys maps a design onto
//
// Every cell is exactly one thing the fabric can hold, and each model here is
// the fabric's own behaviour (the BRAM and DSP models instantiate the fabric's
// bram_core.v / dsp_core.v), so a synthesised netlist simulated with this file
// behaves as the loaded fabric does.
//
//   $lut / BOB_LUT  K-input LUT                  -> a CLB's LUT (O6)
//   BOB_FDRE        D FF, CE, sync reset,  INIT 0 -> a CLB's FF (FDRE, ff_rstval 0)
//   BOB_FDSE        D FF, CE, sync set,    INIT 1 -> a CLB's FF (FDSE, ff_rstval 1)
//   BOB_ADD         one adder bit                -> a CLB in carry mode: LUT
//                   S = A ^ B ^ INV_B, O = S ^ CI, CO = S ? CI : A   (XORCY/MUXCY,
//                   carry generate DI = i[0] = A)
//   BOB_BRAM18      1024 x 18 true dual port     -> a BRAM block (no output register)
//   BOB_DSP         25 x 18 signed multiplier    -> a DSP slice, opmode M, no registers
//
// One user clock drives every sequential cell (the fabric has one: sysclk + gce).
// Reset priority is UG474's: R/S beats CE. Flip-flops power up at INIT, which is
// the fabric's GSR value.
//
// Read with `read_verilog -lib` by tools/bob/synth.py (bodies ignored), and with
// the design's netlist by the equivalence simulation.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps

module BOB_LUT #(
    parameter integer K    = 6,
    parameter [63:0]  INIT = 64'h0
)(
    input  wire [K-1:0] I,
    output wire         O
);
    assign O = INIT[I];
endmodule

module BOB_FDRE #(
    parameter [0:0] INIT = 1'b0
)(
    input  wire C,
    input  wire CE,
    input  wire R,
    input  wire D,
    output reg  Q
);
    initial Q = INIT;
    always @(posedge C)
        if (R)       Q <= 1'b0;
        else if (CE) Q <= D;
endmodule

module BOB_FDSE #(
    parameter [0:0] INIT = 1'b1
)(
    input  wire C,
    input  wire CE,
    input  wire S,
    input  wire D,
    output reg  Q
);
    initial Q = INIT;
    always @(posedge C)
        if (S)       Q <= 1'b1;
        else if (CE) Q <= D;
endmodule

module BOB_ADD #(
    parameter [0:0] INV_B = 1'b0
)(
    input  wire A,
    input  wire B,
    input  wire CI,
    output wire O,
    output wire CO
);
    wire s = A ^ B ^ INV_B;
    assign O  = s ^ CI;
    assign CO = s ? CI : A;
endmodule

module BOB_BRAM18 #(
    parameter [1:0]           WMODE_A = 2'd1,     // 0 WRITE_FIRST, 1 READ_FIRST, 2 NO_CHANGE
    parameter [1:0]           WMODE_B = 2'd1,
    parameter [1024*18-1:0]   INIT    = {(1024*18){1'b0}}
)(
    input  wire        CLK,
    input  wire [9:0]  A_ADDR,
    input  wire [17:0] A_DI,
    input  wire        A_WE,
    input  wire        A_EN,
    input  wire        A_RST,
    output wire [17:0] A_DO,
    input  wire [9:0]  B_ADDR,
    input  wire [17:0] B_DI,
    input  wire        B_WE,
    input  wire        B_EN,
    input  wire        B_RST,
    output wire [17:0] B_DO
);
    wire [17:0] ram_a_q;
    bram_core #(.ADDR_W(10), .DATA_W(18)) u_core (
        .clk(CLK), .gce(1'b1), .gsr(1'b0), .gwe(1'b1),
        .wmode_a(WMODE_A), .wmode_b(WMODE_B), .reg_a(1'b0), .reg_b(1'b0),
        .addr_a(A_ADDR), .di_a(A_DI), .we_a(A_WE), .en_a(A_EN), .rst_a(A_RST), .regce_a(1'b0),
        .addr_b(B_ADDR), .di_b(B_DI), .we_b(B_WE), .en_b(B_EN), .rst_b(B_RST), .regce_b(1'b0),
        .init_go(1'b0), .init_wr(1'b0), .init_addr(10'd0), .init_data(18'd0),
        .do_a(A_DO), .do_b(B_DO), .ram_a_q(ram_a_q));
    integer i;
    initial for (i = 0; i < 1024; i = i + 1) u_core.mem[i] = INIT[i*18 +: 18];
endmodule

module BOB_DSP (
    input  wire [24:0] A,
    input  wire [17:0] B,
    output wire [47:0] P
);
    dsp_core u_core (
        .clk(1'b0), .gce(1'b0), .gsr(1'b0), .gwe(1'b0),
        .opmode(2'd0), .use_d(1'b0), .d_sub(1'b0),
        .areg(1'b0), .breg(1'b0), .creg(1'b0), .dreg(1'b0), .mreg(1'b0), .preg(1'b0),
        .a(A), .b(B), .c(48'd0), .d(25'd0),
        .ce_ad(1'b0), .ce_b(1'b0), .ce_m(1'b0), .ce_p(1'b0),
        .rst_ad(1'b0), .rst_b(1'b0), .rst_m(1'b0), .rst_p(1'b0),
        .pcin(48'd0), .p(P));
endmodule
