// @ip counter
// @desc Up counter: counts while en is high, clr clears it on the next clock (clr wins).
// @param W 3 width of the count
module ip_counter #(parameter W = 3) (
    input  wire         clk,
    input  wire         en,
    input  wire         clr,
    output reg  [W-1:0] q = {W{1'b0}}
);
    always @(posedge clk)
        if (clr)     q <= {W{1'b0}};
        else if (en) q <= q + 1'b1;
endmodule
