// -----------------------------------------------------------------------------
// dsp_tile.v - the DSP tile: two cascaded DSP48E1-style slices (M6)
//
// Sits on the fabric's North edge and spans its 4 columns. Until M7 gives it a
// real DSP column it connects through the fabric's 16 North edge tracks:
//
//   trk_in[c*4+t]   fabric tile (3,c) out_N[t]   ->  DSP inputs
//   trk_out[c*4+t]  DSP output box               ->  fabric tile (3,c) in_N[t]
//
// Slice 1's PCIN is slice 0's P (UG479 PCOUT -> PCIN cascade); slice 0's is 0.
//
// Config (tools/bob/device.py 'dsp' tile type), per slice s at [18*s +: 18]:
//   [1:0] opmode  0 M, 1 M+C, 2 P+M, 3 (PCIN>>>17)+M
//   [2] use_d  [3] d_sub  [4] areg [5] breg [6] creg [7] dreg [8] mreg [9] preg
//   [11:10] bus_a  [13:12] bus_b  [15:14] bus_c  [17:16] bus_d
//            bus source 0 const0 | 1 JTAG drive | 2 fabric (bit k <- trk_in[k],
//            k < 16; higher bits 0) | 3 const0
//   [39:36] reserved
//   [119:40] 16 control selects, 5 bits: slice 0 then slice 1, each
//            ce_ad ce_b ce_m ce_p rst_ad rst_b rst_m rst_p
//            source 0 const0 | 1 const1 | 2 JTAG drive bit | 3..18 trk_in[0..15]
//   [231:120] 16 output selects, 7 bits, output k drives trk_out[k]:
//            0 const0 | 1..48 P0[0..47] | 49..96 P1[0..47]
//
// JTAG (private instruction DSP, 101000 - not an AMD code), 256-bit register:
//   capture  [47:0] P0, [95:48] P1, [247:96] 0, [255:248] version 0x06
//   update   [255:252] == 4 (SET_DRIVE): drive <- [247:0]; otherwise nothing
//   drive    slice s at [124*s +: 124]: a[24:0] b[17:0] c[47:0] d[24:0] then the
//            8 controls in the order above
//
// An all-zero config is inert: buses const0, controls const0 (no CE), outputs 0.
// Written with flat buses only (no references into generate scopes, no
// functions inside generate) so every tool elaborates it the same way.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none
`include "bob_params.vh"

module dsp_tile (
    input  wire                   sysclk,
    input  wire                   gce,
    input  wire                   gsr,
    input  wire                   gwe,

    input  wire [`BOB_DSP_W-1:0]  cfg,
    input  wire [15:0]            trk_in,
    output wire [15:0]            trk_out,

    // JTAG, private DSP instruction
    input  wire                   tck,
    input  wire                   tdi,
    input  wire                   sel,
    input  wire                   dr_capture,
    input  wire                   dr_shift,
    input  wire                   dr_update,
    output wire                   so
);

    localparam integer CTRL_LO   = `BOB_DSP_CTRL_LO;
    localparam integer CTRL_SELW = `BOB_DSP_CTRL_SELW;
    localparam integer OUT_LO    = `BOB_DSP_OUT_LO;
    localparam integer OUT_SELW  = `BOB_DSP_OUT_SELW;
    localparam [7:0]   VERSION   = 8'h06;

    wire [95:0] p_flat;                 // P0 at [47:0], P1 at [95:48]

    // ---------------------------------------------------------------------
    // JTAG drive register (TCK domain)
    // ---------------------------------------------------------------------
    reg [255:0] sr    = 256'h0;
    reg [247:0] drive = 248'h0;

    always @(posedge tck) begin
        if (sel & dr_capture)
            sr <= {VERSION, 152'h0, p_flat};
        else if (sel & dr_shift)
            sr <= {tdi, sr[255:1]};
    end

    always @(negedge tck)
        if (sel & dr_update & (sr[255:252] == 4'h4))
            drive <= sr[247:0];

    assign so = sr[0];

    // ---------------------------------------------------------------------
    // Slices
    // ---------------------------------------------------------------------
    wire [47:0] trk48 = {32'h0, trk_in};

    genvar s, k;
    generate
        for (s = 0; s < 2; s = s + 1) begin : g_slice
            wire [17:0]  sc  = cfg[18*s +: 18];
            wire [123:0] drv = drive[124*s +: 124];

            // bus source: 1 JTAG drive, 2 fabric tracks, else const0
            wire [47:0] a48 = (sc[11:10] == 2'd1) ? {23'h0, drv[24:0]}   : (sc[11:10] == 2'd2) ? trk48 : 48'h0;
            wire [47:0] b48 = (sc[13:12] == 2'd1) ? {30'h0, drv[42:25]}  : (sc[13:12] == 2'd2) ? trk48 : 48'h0;
            wire [47:0] c48 = (sc[15:14] == 2'd1) ? drv[90:43]           : (sc[15:14] == 2'd2) ? trk48 : 48'h0;
            wire [47:0] d48 = (sc[17:16] == 2'd1) ? {23'h0, drv[115:91]} : (sc[17:16] == 2'd2) ? trk48 : 48'h0;

            wire [7:0] ctl;
            for (k = 0; k < 8; k = k + 1) begin : g_ctl
                wire [31:0] srcs = {13'b0, trk_in, drv[116 + k], 1'b1, 1'b0};
                assign ctl[k] = srcs[cfg[CTRL_LO + (8*s + k)*CTRL_SELW +: CTRL_SELW]];
            end

            wire [47:0] pcin;
            if (s == 0) begin : g_first
                assign pcin = 48'h0;
            end else begin : g_casc
                assign pcin = p_flat[47:0];
            end

            dsp_core u_core (
                .clk    (sysclk),
                .gce    (gce),
                .gsr    (gsr),
                .gwe    (gwe),
                .opmode (sc[1:0]),
                .use_d  (sc[2]),
                .d_sub  (sc[3]),
                .areg   (sc[4]),
                .breg   (sc[5]),
                .creg   (sc[6]),
                .dreg   (sc[7]),
                .mreg   (sc[8]),
                .preg   (sc[9]),
                .a      (a48[24:0]),
                .b      (b48[17:0]),
                .c      (c48),
                .d      (d48[24:0]),
                .ce_ad  (ctl[0]),
                .ce_b   (ctl[1]),
                .ce_m   (ctl[2]),
                .ce_p   (ctl[3]),
                .rst_ad (ctl[4]),
                .rst_b  (ctl[5]),
                .rst_m  (ctl[6]),
                .rst_p  (ctl[7]),
                .pcin   (pcin),
                .p      (p_flat[48*s +: 48])
            );

            wire _unused_s = &{1'b0, a48[47:25], b48[47:18], d48[47:25]};
        end
    endgenerate

    // ---------------------------------------------------------------------
    // Output box
    // ---------------------------------------------------------------------
    wire [127:0] obus = {31'h0, p_flat, 1'b0};
    generate
        for (k = 0; k < 16; k = k + 1) begin : g_out
            assign trk_out[k] = obus[cfg[OUT_LO + k*OUT_SELW +: OUT_SELW]];
        end
    endgenerate

    wire _unused = &{1'b0, cfg[39:36], sr[251:248]};

endmodule

`default_nettype wire
