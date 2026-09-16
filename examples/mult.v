// mult.v - registered 4 x 4 multiplier on a DSP slice (M8 example)
module mult (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    reg  [3:0] a = 4'd0;
    reg  [7:0] p = 8'd0;
    always @(posedge clk) begin
        a <= {btn[1:0], sw};
        p <= a * {btn[3:2], sw};
    end
    assign led = p[7:5];
endmodule
