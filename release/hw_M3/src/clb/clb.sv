// ============================================================================
// clb.sv -- one configurable logic block
//
//   LUT6 (fracturable)  ->  carry chain (MUXCY/XORCY)  ->  flop (FDRE/FDSE)
//
// Config word layout is documented in clb_pkg.sv.
// ============================================================================
`timescale 1ns/1ps

module clb
  import clb_pkg::*;
(
  input  wire                 clk,
  input  wire                 ce,      // global clock enable
  input  wire                 sr,      // global sync set/reset
  input  wire                 gsr,     // startup GSR (UG470): every FF to its INIT value
  input  wire                 gwe,     // startup GWE: 0 freezes every FF
  input  wire [5:0]           i,       // LUT inputs
  input  wire                 cin,     // carry in (from south neighbour)
  input  wire [CLB_CFG_W-1:0] cfg,
  output wire                 o,       // main output (comb or registered)
  output wire                 o5,      // secondary / fractured LUT5 output
  output wire                 cout     // carry out (to north neighbour)
);

  // ---- config field unpacking -----------------------------------------------
  wire [63:0] init      = cfg[CLB_INIT_LO +: 64];
  wire        ff_en     = cfg[CLB_FF_EN];
  wire        ff_rstval = cfg[CLB_FF_RSTVAL];
  wire        ff_ce_en  = cfg[CLB_FF_CE_EN];
  wire        ff_sr_en  = cfg[CLB_FF_SR_EN];
  wire        cy_en     = cfg[CLB_CY_EN];
  wire        cy_di_sel = cfg[CLB_CY_DI_SEL];
  wire        ff_d_sel  = cfg[CLB_FF_D_SEL];

  // ---- LUT ------------------------------------------------------------------
  wire lut_o6, lut_o5;
  lut6 u_lut (.init(init), .i(i), .o6(lut_o6), .o5(lut_o5));

  // ---- carry chain ----------------------------------------------------------
  // LUT6 output is the propagate term. The generate term (DI) is either a raw
  // input or the fractured LUT5, which is what lets one CLB do add/sub/compare.
  wire di      = cy_di_sel ? lut_o5 : i[0];
  wire prop    = lut_o6;
  wire cy_mux  = prop ? cin : di;   // MUXCY
  wire cy_sum  = prop ^ cin;        // XORCY

  assign cout = cy_en ? cy_mux : 1'b0;

  // ---- datapath -> flop -----------------------------------------------------
  wire comb = cy_en ? cy_sum : (ff_d_sel ? lut_o5 : lut_o6);

  wire ce_eff = ff_ce_en ? ce : 1'b1;
  wire sr_eff = ff_sr_en ? sr : 1'b0;

  // GSR and GWE come from the configuration startup sequence
  // (docs/bitstream-format.md s6). GSR resets every FF to ff_rstval whether or
  // not FF_SR_EN is set - that is what makes a freshly configured design start
  // in a known state. GWE low holds every FF, so user state cannot change until
  // startup says so.
  reg q;
  always @(posedge clk) begin
    if (gsr)         q <= ff_rstval;   // GSR: INIT value
    else if (!gwe)   q <= q;           // GWE low: frozen
    else if (sr_eff) q <= ff_rstval;   // synchronous, CE-independent (FDRE/FDSE)
    else if (ce_eff) q <= comb;
  end

  assign o  = ff_en ? q : comb;
  assign o5 = lut_o5;

endmodule
