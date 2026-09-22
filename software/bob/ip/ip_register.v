// @ip register
// @desc W-bit register with clock enable: q takes d on every clock that en is high.
// @param W 1 width
module ip_register #(parameter W = 1) (
    input  wire         clk,
    input  wire         en,
    input  wire [W-1:0] d,
    output reg  [W-1:0] q = {W{1'b0}}
);
    always @(posedge clk)
        if (en) q <= d;
endmodule
