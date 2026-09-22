// @ip concat
// @desc y = {a, b}: a on top (Vivado's xlconcat, two inputs).
// @param W_A 1 width of a
// @param W_B 1 width of b
module ip_concat #(parameter W_A = 1, parameter W_B = 1) (
    input  wire [W_A-1:0]     a,
    input  wire [W_B-1:0]     b,
    output wire [W_A+W_B-1:0] y
);
    assign y = {a, b};
endmodule
