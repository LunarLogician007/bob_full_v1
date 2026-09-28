// @ip debounce
// @desc Two-flop synchroniser, then q follows the input only once it has held for 2**N clocks.
// @param N 2 log2 of the clocks the input must hold
module ip_debounce #(parameter N = 2) (
    input  wire clk,
    input  wire d,
    output reg  q = 1'b0
);
    reg [1:0]   s = 2'b00;
    reg [N-1:0] c = {N{1'b0}};
    always @(posedge clk) begin
        s <= {s[0], d};
        if (s[1] == q)
            c <= {N{1'b0}};
        else begin
            c <= c + 1'b1;
            if (&c) q <= s[1];
        end
    end
endmodule
