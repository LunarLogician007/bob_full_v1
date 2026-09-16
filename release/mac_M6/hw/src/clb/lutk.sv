// ============================================================================
// lutk.sv -- fracturable K-input LUT, AMD LUT6_2 style, K a parameter (M4)
//
// Generalises lut6.sv (hardware-proven; kept in docs/reference/lut6.sv and
// checked equal to this at K=6 by tests/test_lutk.py). Built as an explicit mux
// tree so the fracture point falls out naturally:
//
//   level 0      INIT, 2**K leaves
//   level l      2**(K-l) muxes selected by i[l-1]
//   O5           level K-1, entry 0: the LUT(K-1) formed by INIT[2**(K-1)-1:0]
//                over i[K-2:0]            (UG474: O5 of a LUT6_2)
//   O6           level K: the full K-input function
//
// All levels live in one flat bus `t`, level l at offset OFF(l) =
// 2**(K+1) - 2**(K-l+1), so nothing refers into another generate scope
// (plain indexing synthesises identically everywhere).
// ============================================================================
`timescale 1ns/1ps

module lutk #(
  parameter integer K = 6              // 2..6
)(
  input  wire [(1<<K)-1:0] init,
  input  wire [K-1:0]      i,
  output wire              o6,
  output wire              o5
);

  localparam integer NODES = (2 << K) - 1;          // 2**(K+1) - 1

  wire [NODES-1:0] t;

  assign t[(1<<K)-1:0] = init;                      // level 0

  genvar l, g;
  generate
    for (l = 1; l <= K; l = l + 1) begin : g_lvl
      localparam integer OFF_IN  = (2 << K) - (2 << (K - l + 1));   // OFF(l-1)
      localparam integer OFF_OUT = (2 << K) - (2 << (K - l));       // OFF(l)
      for (g = 0; g < (1 << (K - l)); g = g + 1) begin : g_mux
        assign t[OFF_OUT + g] = i[l-1] ? t[OFF_IN + 2*g + 1] : t[OFF_IN + 2*g];
      end
    end
  endgenerate

  assign o6 = t[NODES - 1];                          // OFF(K)
  assign o5 = t[NODES - 3];                          // OFF(K-1), entry 0

endmodule
