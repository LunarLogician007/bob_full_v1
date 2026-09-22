// @ip xor
// @desc Bitwise xor of two W-bit inputs.
// @param W 1 width
module ip_xor #(parameter W = 1) (
    input  wire [W-1:0] a,
    input  wire [W-1:0] b,
    output wire [W-1:0] y
);
    assign y = a ^ b;
endmodule
