// ============================================================================
// clb.sv -- one configurable logic block
//
//   LUTK (fracturable)  ->  carry chain (MUXCY/XORCY)  ->  flop (FDRE/FDSE)
//
// Config word layout is documented in clb_pkg.sv.
//
// Control inputs (M4):
//   ce, sr   ROUTED per tile through the connection box (UG474: CE and SR are
//            per-slice routable pins). FF_CE_EN / FF_SR_EN select whether the
//            flop honours them.
//   gce      global clock enable from clock_ctrl.v: the flop can only change
//            on a clock edge where gce is high (a divided or JTAG-stepped user
//            clock, realised as an enable on one global clock - UG949 prefers
//            clock enables to logic-generated clocks).
//   gsr/gwe  startup (docs/bitstream-format.md s6): GSR forces INIT regardless
//            of everything; GWE low freezes the flop.
// ============================================================================
`timescale 1ns/1ps

module clb
  import clb_pkg::*;
(
  input  wire                 clk,
  input  wire                 gce,     // global clock enable (user clock)
  input  wire                 ce,      // routed clock enable
  input  wire                 sr,      // routed synchronous set/reset
  input  wire                 gsr,     // startup GSR: every FF to its INIT value
  input  wire                 gwe,     // startup GWE: 0 freezes every FF
  input  wire [LUT_K-1:0]     i,       // LUT inputs
  input  wire                 cin,     // carry in (from south neighbour)
  input  wire [CLB_CFG_W-1:0] cfg,
  output wire                 o,       // main output (comb or registered)
  output wire                 o5,      // secondary / fractured LUT(K-1) output
  output wire                 cout     // carry out (to north neighbour)
);

  // ---- config field unpacking -----------------------------------------------
  wire [LUT_INIT_W-1:0] init = cfg[CLB_INIT_LO +: LUT_INIT_W];
  wire        ff_en     = cfg[CLB_FF_EN];
  wire        ff_rstval = cfg[CLB_FF_RSTVAL];
  wire        ff_ce_en  = cfg[CLB_FF_CE_EN];
  wire        ff_sr_en  = cfg[CLB_FF_SR_EN];
  wire        cy_en     = cfg[CLB_CY_EN];
  wire        cy_di_sel = cfg[CLB_CY_DI_SEL];
  wire        ff_d_sel  = cfg[CLB_FF_D_SEL];

  // ---- LUT ------------------------------------------------------------------
  wire lut_o6, lut_o5;
  lutk #(.K(LUT_K)) u_lut (.init(init), .i(i), .o6(lut_o6), .o5(lut_o5));

  // ---- carry chain ----------------------------------------------------------
  // O6 is the propagate term. The generate term (DI) is either a raw input or
  // the fractured O5, which is what lets one CLB do add/sub/compare.
  wire di      = cy_di_sel ? lut_o5 : i[0];
  wire prop    = lut_o6;
  wire cy_mux  = prop ? cin : di;   // MUXCY
  wire cy_sum  = prop ^ cin;        // XORCY

  assign cout = cy_en ? cy_mux : 1'b0;

  // ---- datapath -> flop -----------------------------------------------------
  wire comb = cy_en ? cy_sum : (ff_d_sel ? lut_o5 : lut_o6);

  wire ce_eff = ff_ce_en ? ce : 1'b1;
  wire sr_eff = ff_sr_en ? sr : 1'b0;

  reg q;
  always @(posedge clk) begin
    if (gsr)                  q <= ff_rstval;   // GSR: INIT value
    else if (gwe && gce) begin                  // GWE low or no enable: frozen
      if (sr_eff)             q <= ff_rstval;   // synchronous, CE-independent (FDRE/FDSE)
      else if (ce_eff)        q <= comb;
    end
  end

  assign o  = ff_en ? q : comb;
  assign o5 = lut_o5;

endmodule
