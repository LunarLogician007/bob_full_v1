// mult.v - registered 8 x 6 multiplier on a DSP slice (M8 example)
module mult (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    reg  [7:0]  a = 8'd0;
    reg  [13:0] p = 14'd0;
    always @(posedge clk) begin
        a <= {btn, sw, 2'b01};
        p <= a * {btn[1:0], sw, btn[3:2]};
    end
    assign led = p[13:11] ^ p[2:0];
endmodule
