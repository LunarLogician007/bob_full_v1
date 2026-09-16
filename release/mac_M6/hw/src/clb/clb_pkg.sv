// ============================================================================
// clb_pkg.sv -- architecture constants + bitstream construction helpers
//
// M4: the LUT size K comes from hw/src/generated/bob_params.vh (tools/bob/
// device.py). Every width below is DERIVED from K here, independently of the
// generated widths, and tests/test_device.py elaborates this package next to
// bob_params.vh and compares every constant - so the two can never drift.
// ============================================================================
`timescale 1ns/1ps
`include "bob_params.vh"

package clb_pkg;

  // --------------------------------------------------------------------------
  // LUT size and fabric geometry
  // --------------------------------------------------------------------------
  localparam int LUT_K      = `BOB_LUT_K;
  localparam int LUT_INIT_W = 1 << LUT_K;

  localparam int NTRACK  = 4;   // routing tracks per tile edge
  localparam int GRID_R  = 4;   // fabric rows
  localparam int GRID_C  = 4;   // fabric cols

  // --------------------------------------------------------------------------
  // Routing mux source encoding (shared by connection box and switch box)
  //
  //   0            const 0        <-- all-zero bitstream = dark fabric, no loops
  //   1            const 1
  //   2            CLB main out   (o)
  //   3            CLB O5 out     (o5)
  //   4  .. 4+T-1  north  in[t]
  //   4+T.. 4+2T-1 east   in[t]
  //   4+2T..4+3T-1 south  in[t]
  //   4+3T..4+4T-1 west   in[t]
  // --------------------------------------------------------------------------
  localparam int NSRC  = 4 + 4*NTRACK;   // 20 with NTRACK=4
  localparam int SELW  = $clog2(NSRC);   // 5 with NTRACK=4

  localparam int SRC_C0     = 0;
  localparam int SRC_C1     = 1;
  localparam int SRC_CLB_O  = 2;
  localparam int SRC_CLB_O5 = 3;

  function automatic [SELW-1:0] src_n(input int t); src_n = SELW'(4 + 0*NTRACK + t); endfunction
  function automatic [SELW-1:0] src_e(input int t); src_e = SELW'(4 + 1*NTRACK + t); endfunction
  function automatic [SELW-1:0] src_s(input int t); src_s = SELW'(4 + 2*NTRACK + t); endfunction
  function automatic [SELW-1:0] src_w(input int t); src_w = SELW'(4 + 3*NTRACK + t); endfunction

  // Direction ids, used for switch box output indexing
  localparam int DIR_N = 0;
  localparam int DIR_E = 1;
  localparam int DIR_S = 2;
  localparam int DIR_W = 3;

  // Human readable name for a mux select value (debug printing)
  function automatic string src_name(input [SELW-1:0] s);
    int v; v = int'(s);
    if      (v == SRC_C0)     src_name = "const0";
    else if (v == SRC_C1)     src_name = "const1";
    else if (v == SRC_CLB_O)  src_name = "clb_o ";
    else if (v == SRC_CLB_O5) src_name = "clb_o5";
    else if (v <  4+1*NTRACK) src_name = $sformatf("N[%0d]  ", v-4-0*NTRACK);
    else if (v <  4+2*NTRACK) src_name = $sformatf("E[%0d]  ", v-4-1*NTRACK);
    else if (v <  4+3*NTRACK) src_name = $sformatf("S[%0d]  ", v-4-2*NTRACK);
    else if (v <  4+4*NTRACK) src_name = $sformatf("W[%0d]  ", v-4-3*NTRACK);
    else                      src_name = "??????";
  endfunction

  // --------------------------------------------------------------------------
  // CLB config word (2**K + 7 bits; 71 for K=6)
  //
  //   [2**K-1:0]  INIT       LUTK truth table
  //   [+0]        FF_EN      main out o = FF q (1) or combinational (0)
  //   [+1]        FF_RSTVAL  INIT / sync reset value (FDRE=0 / FDSE=1)
  //   [+2]        FF_CE_EN   1: FF honours the routed CE, 0: always enabled
  //   [+3]        FF_SR_EN   1: FF honours the routed SR, 0: reset ignored
  //   [+4]        CY_EN      carry-chain mode (XORCY sum on datapath, MUXCY cout)
  //   [+5]        CY_DI_SEL  carry generate source: 0 = i[0], 1 = O5
  //   [+6]        FF_D_SEL   datapath source: 0 = O6, 1 = O5   (ignored if CY_EN)
  // --------------------------------------------------------------------------
  localparam int CLB_CFG_W = LUT_INIT_W + 7;

  localparam int CLB_INIT_LO   = 0;
  localparam int CLB_FF_EN     = LUT_INIT_W;
  localparam int CLB_FF_RSTVAL = LUT_INIT_W + 1;
  localparam int CLB_FF_CE_EN  = LUT_INIT_W + 2;
  localparam int CLB_FF_SR_EN  = LUT_INIT_W + 3;
  localparam int CLB_CY_EN     = LUT_INIT_W + 4;
  localparam int CLB_CY_DI_SEL = LUT_INIT_W + 5;
  localparam int CLB_FF_D_SEL  = LUT_INIT_W + 6;

  function automatic [CLB_CFG_W-1:0] mk_clb_cfg(
      input [63:0] init,
      input        ff_en,
      input        ff_rstval,
      input        ff_ce_en,
      input        ff_sr_en,
      input        cy_en,
      input        cy_di_sel,
      input        ff_d_sel);
    mk_clb_cfg = '0;
    mk_clb_cfg[CLB_INIT_LO +: LUT_INIT_W] = init[LUT_INIT_W-1:0];
    mk_clb_cfg[CLB_FF_EN]       = ff_en;
    mk_clb_cfg[CLB_FF_RSTVAL]   = ff_rstval;
    mk_clb_cfg[CLB_FF_CE_EN]    = ff_ce_en;
    mk_clb_cfg[CLB_FF_SR_EN]    = ff_sr_en;
    mk_clb_cfg[CLB_CY_EN]       = cy_en;
    mk_clb_cfg[CLB_CY_DI_SEL]   = cy_di_sel;
    mk_clb_cfg[CLB_FF_D_SEL]    = ff_d_sel;
  endfunction

  // Pure combinational LUT, no FF, no carry -- the common case.
  function automatic [CLB_CFG_W-1:0] mk_clb_comb(input [63:0] init);
    mk_clb_comb = mk_clb_cfg(init, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0);
  endfunction

  // Registered LUT output (FDRE with CE and sync reset honoured).
  function automatic [CLB_CFG_W-1:0] mk_clb_reg(input [63:0] init);
    mk_clb_reg = mk_clb_cfg(init, 1'b1, 1'b0, 1'b1, 1'b1, 1'b0, 1'b0, 1'b0);
  endfunction

  // Full-adder bit: LUT computes propagate, carry chain does the rest.
  function automatic [CLB_CFG_W-1:0] mk_clb_addbit(input reg_out);
    mk_clb_addbit = mk_clb_cfg(init_xor2(), reg_out, 1'b0, 1'b0, 1'b0, 1'b1, 1'b0, 1'b0);
  endfunction

  // --------------------------------------------------------------------------
  // INIT builders over 64 addresses (a LUTK uses the low 2**K entries, so
  // functions of inputs below K are correct at any K).
  // --------------------------------------------------------------------------
  function automatic [63:0] init_const0(); init_const0 = 64'd0;      endfunction
  function automatic [63:0] init_const1(); init_const1 = {64{1'b1}}; endfunction

  function automatic [63:0] init_buf();       // o = i0
    for (int k = 0; k < 64; k++) init_buf[k] = k[0];
  endfunction
  function automatic [63:0] init_not();       // o = ~i0
    for (int k = 0; k < 64; k++) init_not[k] = ~k[0];
  endfunction
  function automatic [63:0] init_and2();      // o = i0 & i1
    for (int k = 0; k < 64; k++) init_and2[k] = k[0] & k[1];
  endfunction
  function automatic [63:0] init_or2();       // o = i0 | i1
    for (int k = 0; k < 64; k++) init_or2[k] = k[0] | k[1];
  endfunction
  function automatic [63:0] init_xor2();      // o = i0 ^ i1
    for (int k = 0; k < 64; k++) init_xor2[k] = k[0] ^ k[1];
  endfunction
  function automatic [63:0] init_nand2();
    for (int k = 0; k < 64; k++) init_nand2[k] = ~(k[0] & k[1]);
  endfunction
  function automatic [63:0] init_nor2();
    for (int k = 0; k < 64; k++) init_nor2[k] = ~(k[0] | k[1]);
  endfunction
  function automatic [63:0] init_xnor2();
    for (int k = 0; k < 64; k++) init_xnor2[k] = ~(k[0] ^ k[1]);
  endfunction
  function automatic [63:0] init_and6();      // o = &i[5:0]
    for (int k = 0; k < 64; k++) init_and6[k] = &k[5:0];
  endfunction
  function automatic [63:0] init_or6();
    for (int k = 0; k < 64; k++) init_or6[k] = |k[5:0];
  endfunction
  function automatic [63:0] init_xor6();      // 6-input parity
    for (int k = 0; k < 64; k++) init_xor6[k] = ^k[5:0];
  endfunction
  function automatic [63:0] init_mux2();      // o = i2 ? i1 : i0
    for (int k = 0; k < 64; k++) init_mux2[k] = k[2] ? k[1] : k[0];
  endfunction
  function automatic [63:0] init_pass(input int k);   // o = i[k], a routed wire
    for (int a = 0; a < 64; a++) init_pass[a] = (((a >> k) & 1) != 0);
  endfunction
  function automatic [63:0] init_maj3();      // majority of i0,i1,i2
    for (int k = 0; k < 64; k++)
      init_maj3[k] = (k[0]&k[1]) | (k[1]&k[2]) | (k[0]&k[2]);
  endfunction

  // Fracturable pair (K=6): O6 sees f1 over i[5:0], O5 sees f0 over i[4:0].
  function automatic [63:0] init_frac(input [31:0] lo5, input [31:0] hi5);
    init_frac = {hi5, lo5};
  endfunction

  // --------------------------------------------------------------------------
  // Connection box: K LUT-input muxes + CE + SR, SELW bits each
  //   (8 x 5 = 40 bits for K=6)
  // --------------------------------------------------------------------------
  localparam int CB_N     = LUT_K + 2;
  localparam int CB_CFG_W = CB_N * SELW;

  function automatic [CB_CFG_W-1:0] mk_cb_cfg(
      input [SELW-1:0] s0, s1, s2, s3, s4, s5);
    mk_cb_cfg = '0;
    mk_cb_cfg[6*SELW-1:0] = {s5, s4, s3, s2, s1, s0};
  endfunction

  function automatic [CB_CFG_W-1:0] cb_off();
    cb_off = '0;
  endfunction

  // --------------------------------------------------------------------------
  // Switch box: one mux per (direction, track) output, SELW bits each
  //   index = dir*NTRACK + track,  dir in {N,E,S,W}
  //   4 * 4 * 5 = 80 bits
  // --------------------------------------------------------------------------
  localparam int SB_CFG_W = 4 * NTRACK * SELW;

  function automatic int sb_idx(input int dir, input int trk);
    sb_idx = dir*NTRACK + trk;
  endfunction

  function automatic [SB_CFG_W-1:0] sb_set(
      input [SB_CFG_W-1:0] cur,
      input int            dir,
      input int            trk,
      input [SELW-1:0]     sel);
    int base;
    sb_set = cur;
    base   = sb_idx(dir, trk) * SELW;
    for (int b = 0; b < SELW; b++) sb_set[base+b] = sel[b];
  endfunction

  // --------------------------------------------------------------------------
  // Tile config word = CLB | CB | SB  (71 + 40 + 80 = 191 bits for K=6)
  // --------------------------------------------------------------------------
  localparam int TILE_CFG_W = CLB_CFG_W + CB_CFG_W + SB_CFG_W;

  localparam int TILE_CLB_LO = 0;
  localparam int TILE_CB_LO  = CLB_CFG_W;
  localparam int TILE_SB_LO  = CLB_CFG_W + CB_CFG_W;

  function automatic [TILE_CFG_W-1:0] mk_tile_cfg(
      input [CLB_CFG_W-1:0] clb,
      input [CB_CFG_W-1:0]  cb,
      input [SB_CFG_W-1:0]  sb);
    mk_tile_cfg = {sb, cb, clb};
  endfunction

  // Used by the testbench / bitstream tooling rather than by the RTL itself.
  /* verilator lint_off UNUSEDPARAM */
  localparam int FABRIC_CFG_W = TILE_CFG_W * GRID_R * GRID_C;
  localparam int CTRL_W       = 8;                   // clock mode + divider
  // M5 BRAM tile: mode byte + 2 ports x 32 pin selects x 5 bits + 16 x 6-bit outputs
  localparam int BRAM_W       = 8 + 2*32*5 + 16*6;   // 424
  // M6 DSP tile: 2 slices x 18 mode bits + 4 reserved + 16 x 5-bit controls + 16 x 7-bit outputs
  localparam int DSP_W        = 2*18 + 4 + 16*5 + 16*7;   // 232
  localparam int CHAIN_W      = CTRL_W + FABRIC_CFG_W + BRAM_W + DSP_W;
  /* verilator lint_on UNUSEDPARAM */

endpackage : clb_pkg
