// ============================================================================
// clb_pkg.sv -- CLB constants + CLB configuration helpers
//
// M4: the LUT size K comes from hw/src/generated/bob_params.vh (tools/bob/
// device.py). Every width below is DERIVED from K here, independently of the
// generated widths, and tests/test_device.py elaborates this package next to
// bob_params.vh and compares every constant - so the two can never drift.
//
// M7: the routing constants (tracks, source bus, connection/switch box words)
// left with the hand-written 4x4 fabric; routing is now generated from VPR's
// rr graph and described only by tools/bob/device.json.
// ============================================================================
`timescale 1ns/1ps
`include "bob_params.vh"

package clb_pkg;

  // --------------------------------------------------------------------------
  // LUT size
  // --------------------------------------------------------------------------
  localparam int LUT_K      = `BOB_LUT_K;
  localparam int LUT_INIT_W = 1 << LUT_K;

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

endpackage : clb_pkg
