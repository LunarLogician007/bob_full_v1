// @ip mux2
// @desc Two-way multiplexer: y = sel ? b : a.
// @param W 1 width
module ip_mux2 #(parameter W = 1) (
    input  wire [W-1:0] a,
    input  wire [W-1:0] b,
    input  wire         sel,
    output wire [W-1:0] y
);
    assign y = sel ? b : a;
endmodule
