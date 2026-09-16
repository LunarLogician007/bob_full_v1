// ============================================================================
// clb_pkg.sv -- architecture constants + bitstream construction helpers
//
// Everything about the bitstream layout lives here. The testbenches build
// config words with these functions so there are no magic numbers anywhere.
// ============================================================================
`timescale 1ns/1ps

package clb_pkg;

  // --------------------------------------------------------------------------
  // Fabric geometry
  // --------------------------------------------------------------------------
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
  // CLB config word (71 bits)
  //
  //   [63:0]  INIT       LUT6 truth table
  //   [64]    FF_EN      main out o = FF q (1) or combinational (0)
  //   [65]    FF_RSTVAL  value loaded on sync reset (FDRE=0 / FDSE=1)
  //   [66]    FF_CE_EN   1: FF honours global ce, 0: always enabled
  //   [67]    FF_SR_EN   1: FF honours global sr, 0: reset ignored
  //   [68]    CY_EN      carry-chain mode (XORCY sum on datapath, MUXCY cout)
  //   [69]    CY_DI_SEL  carry generate source: 0 = i[0], 1 = O5
  //   [70]    FF_D_SEL   datapath source: 0 = O6, 1 = O5   (ignored if CY_EN)
  // --------------------------------------------------------------------------
  localparam int CLB_CFG_W = 71;

  localparam int CLB_INIT_LO   = 0;
  localparam int CLB_FF_EN     = 64;
  localparam int CLB_FF_RSTVAL = 65;
  localparam int CLB_FF_CE_EN  = 66;
  localparam int CLB_FF_SR_EN  = 67;
  localparam int CLB_CY_EN     = 68;
  localparam int CLB_CY_DI_SEL = 69;
  localparam int CLB_FF_D_SEL  = 70;

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
    mk_clb_cfg[63:0]            = init;
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

  // Registered LUT output (FDRE with CE and sync reset wired to the globals).
  function automatic [CLB_CFG_W-1:0] mk_clb_reg(input [63:0] init);
    mk_clb_reg = mk_clb_cfg(init, 1'b1, 1'b0, 1'b1, 1'b1, 1'b0, 1'b0, 1'b0);
  endfunction

  // Full-adder bit: LUT computes propagate, carry chain does the rest.
  function automatic [CLB_CFG_W-1:0] mk_clb_addbit(input reg_out);
    mk_clb_addbit = mk_clb_cfg(init_xor2(), reg_out, 1'b0, 1'b0, 1'b0, 1'b1, 1'b0, 1'b0);
  endfunction

  // --------------------------------------------------------------------------
  // LUT6 INIT builders. Each walks all 64 addresses and evaluates the function
  // of the address bits, so the truth tables are readable rather than hex soup.
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

  // Fracturable pair: O6 sees f1 over i[5:0], O5 sees f0 over i[4:0].
  // Build INIT so the low 32 entries are f0 and the high 32 are f1's i5=1 half.
  function automatic [63:0] init_frac(input [31:0] lo5, input [31:0] hi5);
    init_frac = {hi5, lo5};
  endfunction

  // --------------------------------------------------------------------------
  // Connection box: 6 LUT input muxes, 5 bits each  = 30 bits
  // --------------------------------------------------------------------------
  localparam int CB_CFG_W = 6 * SELW;

  function automatic [CB_CFG_W-1:0] mk_cb_cfg(
      input [SELW-1:0] s0, s1, s2, s3, s4, s5);
    mk_cb_cfg = {s5, s4, s3, s2, s1, s0};
  endfunction

  // All six inputs tied to const0 -- the default / unused case.
  function automatic [CB_CFG_W-1:0] cb_off();
    cb_off = '0;
  endfunction

  // --------------------------------------------------------------------------
  // Switch box: one mux per (direction, track) output, 5 bits each
  //   index = dir*NTRACK + track,  dir in {N,E,S,W}
  //   4 * 4 * 5 = 80 bits
  // --------------------------------------------------------------------------
  localparam int SB_CFG_W = 4 * NTRACK * SELW;

  function automatic int sb_idx(input int dir, input int trk);
    sb_idx = dir*NTRACK + trk;
  endfunction

  // Set one switch box output mux inside an existing SB config word.
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
  // Tile config word = CLB | CB | SB = 71 + 30 + 80 = 181 bits
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
  /* verilator lint_on UNUSEDPARAM */

endpackage : clb_pkg
