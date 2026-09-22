// @ip clkdiv
// @desc Clock-enable divider: tick is high for one clock in every 2**N. The fabric has
// @desc one clock, so slower logic is enabled by tick rather than clocked by it.
// @param N 3 log2 of the division
module ip_clkdiv #(parameter N = 3) (
    input  wire clk,
    output wire tick
);
    reg [N-1:0] c = {N{1'b0}};
    always @(posedge clk)
        c <= c + 1'b1;
    assign tick = &c;
endmodule
