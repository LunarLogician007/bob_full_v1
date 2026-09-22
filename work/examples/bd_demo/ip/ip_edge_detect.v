// @ip edge_detect
// @desc Two-flop synchroniser and edge detector: rise/fall are high for one clock.
module ip_edge_detect (
    input  wire clk,
    input  wire d,
    output wire rise,
    output wire fall
);
    reg [1:0] s = 2'b00;
    always @(posedge clk)
        s <= {s[0], d};
    assign rise = s[0] & ~s[1];
    assign fall = ~s[0] & s[1];
endmodule
