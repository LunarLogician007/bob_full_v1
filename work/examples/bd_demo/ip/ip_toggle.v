// @ip toggle
// @desc Toggle flip-flop: q flips on every clock that t is high.
module ip_toggle (
    input  wire clk,
    input  wire t,
    output reg  q = 1'b0
);
    always @(posedge clk)
        if (t) q <= ~q;
endmodule
