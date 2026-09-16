// ============================================================================
// lut6.sv -- fracturable 6-input LUT, Xilinx LUT6_2 style
//
// Built as an explicit 63-transistor-style mux tree rather than an array index
// so the fracture point (O5) falls out naturally: O5 is the output of the
// 5-input sub-tree, i.e. the LUT5 formed by INIT[31:0] over i[4:0].
// ============================================================================
`timescale 1ns/1ps

module lut6 (
  input  wire [63:0] init,
  input  wire [5:0]  i,
  output wire        o6,   // full 6-input function
  output wire        o5    // lower LUT5: INIT[31:0] over i[4:0]
);

  wire [31:0] s0;
  wire [15:0] s1;
  wire [7:0]  s2;
  wire [3:0]  s3;
  wire [1:0]  s4;

  genvar g;
  generate
    for (g = 0; g < 32; g = g + 1) assign s0[g] = i[0] ? init[2*g+1] : init[2*g];
    for (g = 0; g < 16; g = g + 1) assign s1[g] = i[1] ? s0[2*g+1]   : s0[2*g];
    for (g = 0; g < 8;  g = g + 1) assign s2[g] = i[2] ? s1[2*g+1]   : s1[2*g];
    for (g = 0; g < 4;  g = g + 1) assign s3[g] = i[3] ? s2[2*g+1]   : s2[2*g];
    for (g = 0; g < 2;  g = g + 1) assign s4[g] = i[4] ? s3[2*g+1]   : s3[2*g];
  endgenerate

  assign o5 = s4[0];                  // fracture tap: LUT5 on INIT[31:0]
  assign o6 = i[5] ? s4[1] : s4[0];

endmodule
