// @ip slice
// @desc Bits HI..LO of a W_IN-bit bus (Vivado's xlslice).
// @param W_IN 3 width of the input
// @param HI 0 top bit taken
// @param LO 0 bottom bit taken
module ip_slice #(parameter W_IN = 3, parameter HI = 0, parameter LO = 0) (
    input  wire [W_IN-1:0]  d,
    output wire [HI-LO:0]   y
);
    assign y = d[HI:LO];
endmodule
