// @ip not
// @desc Bitwise inversion.
// @param W 1 width
module ip_not #(parameter W = 1) (
    input  wire [W-1:0] a,
    output wire [W-1:0] y
);
    assign y = ~a;
endmodule
