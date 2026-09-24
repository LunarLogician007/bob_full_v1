// ============================================================================
// ble.sv -- one logic element of the cluster (OpenFPGA k6_frac_N10's fle)
//
//   LUTK (fracturable)  ->  carry chain (MUXCY/XORCY)  ->  two flops (FDRE/FDSE)
//   M24: or the carry chain on two bypass inputs beside a LUT(K-2) (Double Duty)
//
// Grown from clb.sv (M4-M20, one element per CLB), which stays as the reference:
//   * FRAC: input K-1 reads 1, so the LUT is two LUT(K-1)s over i[K-2:0] sharing
//     their inputs: O6 = INIT[2**K-1:2**(K-1)], O5 = INIT[2**(K-1)-1:0] (AMD LUT6_2
//     with A6 tied high, UG474).
//   * a second flip-flop on O5 (a slice has two FFs per LUT), so both halves of a
//     fractured LUT can be registered: out[1] = FF2 q or O5.
//
// M22: the truth table lives in two CFGLUT5 (AMD UG953: a LUT5 whose 32 bits are shifted
// in on CLK while CE, CDI first into bit 0 and out at bit 31), not in 2**K configuration
// flip-flops and a 2**K:1 mux. lo holds INIT[2**(K-1)-1:0], hi the upper half, both
// addressed by i[K-2:0] (upper address bits 0 when K < 6); O6 = (i[K-1] | frac) ? hi : lo
// is a MUXF7 in the slice, O5 = lo. hw/src/core/lut_loader.v shifts the contents in while
// the frame holding them is written (lck = TCK, lce = this element's INIT frame,
// lcdi = the shared expander's bits for its slot). ZUMA (Brant & Lemieux, FCCM 2012) keeps
// an overlay's LUTs in host LUTRAM the same way.
//
// Config word (cfg): the element's flags only, bits BOB_ELE_* (software/bob/device.py
// ELEMENT_FIELDS). The crossbar in front of it is the cluster's (bob_clb, bob_fabric.v).
//
// Control inputs: ce, sr are the CLB's routed pins, shared by every flop of the
// cluster (UG474: one CE and one SR per slice); gce/gsr/gwe as in clb.sv.
// ============================================================================
`timescale 1ns/1ps
`include "bob_params.vh"

module ble #(
  parameter integer K = `BOB_LUT_K
)(
  input  wire                  clk,
  input  wire                  gce,
  input  wire                  ce,
  input  wire                  sr,
  input  wire                  gsr,
  input  wire                  gwe,
  input  wire [K-1:0]          i,
  input  wire                  cin,
  input  wire [`BOB_ELE_W-1:0] cfg,
  input  wire                  lck,      // M22: CFGLUT5 shift clock (TCK)
  input  wire                  lce,      // M22: shift enable (this element's INIT frame loading)
  input  wire [1:0]            lcdi,     // M22: shift data, [0] lo half, [1] hi half
  output wire                  o,        // out[0]: FF q or O6 / carry sum
  output wire                  o2,       // out[1]: FF2 q or O5
  output wire                  cout
);

  // ---- config field unpacking -----------------------------------------------
  wire frac       = cfg[`BOB_ELE_FRAC];
  wire ff_en      = cfg[`BOB_ELE_FF_EN];
  wire ff_rstval  = cfg[`BOB_ELE_FF_RSTVAL];
  wire ff_ce_en   = cfg[`BOB_ELE_FF_CE_EN];
  wire ff_sr_en   = cfg[`BOB_ELE_FF_SR_EN];
  wire cy_en      = cfg[`BOB_ELE_CY_EN];
  wire cy_di_sel  = cfg[`BOB_ELE_CY_DI_SEL];
  wire ff_d_sel   = cfg[`BOB_ELE_FF_D_SEL];
  wire ff2_en     = cfg[`BOB_ELE_FF2_EN];
  wire ff2_rstval = cfg[`BOB_ELE_FF2_RSTVAL];
  wire ff2_ce_en  = cfg[`BOB_ELE_FF2_CE_EN];
  wire ff2_sr_en  = cfg[`BOB_ELE_FF2_SR_EN];
  wire dd         = cfg[`BOB_ELE_DD];

  // ---- LUT ------------------------------------------------------------------
  wire [4:0] la;                                   // CFGLUT5 address: i[K-2:0]
  generate
    if (K == 6) begin : g_a6
      assign la = i[4:0];
    end else begin : g_ak
      assign la = {{(6 - K){1'b0}}, i[K-2:0]};
    end
  endgenerate
  wire lo6, hi6;
  /* verilator lint_off PINCONNECTEMPTY */
  CFGLUT5 u_lo (.CDO(), .O5(), .O6(lo6), .I4(la[4]), .I3(la[3]), .I2(la[2]), .I1(la[1]), .I0(la[0]),
                .CDI(lcdi[0]), .CE(lce), .CLK(lck));
  CFGLUT5 u_hi (.CDO(), .O5(), .O6(hi6), .I4(la[4]), .I3(la[3]), .I2(la[2]), .I1(la[1]), .I0(la[0]),
                .CDI(lcdi[1]), .CE(lce), .CLK(lck));
  /* verilator lint_on PINCONNECTEMPTY */
  wire lut_o6 = (i[K-1] | frac) ? hi6 : lo6;        // MUXF7
  wire lut_o5 = lo6;

  // ---- carry chain (clb.sv) ---------------------------------------------------
  // M24 Double Duty (Pun, Dai, Zgheib, Iyer, Boutros, Betz, Abdelfattah, FPL 2025): with dd
  // the adder's operands bypass the LUT, A = i[K-2] (also the generate input DI) and
  // B = i[K-1], prop = A ^ B ^ INV_B (cy_di_sel, unused as a DI select in this mode). The LUT
  // is then free for independent logic on out[1]: O5, a LUT(K-2) over i[K-3:0] (the
  // bitstream repeats its table over A). The paper bypasses 4 inputs into an ALM's 2 adders;
  // bob's element has one adder, so 2.
  wire di      = dd ? i[K-2] : (cy_di_sel ? lut_o5 : i[0]);
  wire prop    = dd ? (i[K-2] ^ i[K-1] ^ cy_di_sel) : lut_o6;
  wire cy_mux  = prop ? cin : di;   // MUXCY
  wire cy_sum  = prop ^ cin;        // XORCY

  assign cout = cy_en ? cy_mux : 1'b0;

  // ---- datapaths -> flops -----------------------------------------------------
  wire comb  = cy_en ? cy_sum : (ff_d_sel ? lut_o5 : lut_o6);
  wire comb2 = lut_o5;

  reg q  = 1'b0;
  reg q2 = 1'b0;
  always @(posedge clk) begin
    if (gsr)                          q <= ff_rstval;    // GSR: INIT value
    else if (gwe && gce) begin                           // GWE low or no enable: frozen
      if (ff_sr_en && sr)             q <= ff_rstval;    // synchronous, CE-independent
      else if (!ff_ce_en || ce)       q <= comb;
    end
  end
  always @(posedge clk) begin
    if (gsr)                          q2 <= ff2_rstval;
    else if (gwe && gce) begin
      if (ff2_sr_en && sr)            q2 <= ff2_rstval;
      else if (!ff2_ce_en || ce)      q2 <= comb2;
    end
  end

  assign o  = ff_en  ? q  : comb;
  assign o2 = ff2_en ? q2 : comb2;

endmodule
