// counter.v - 6-bit counter, enable BTN0, sync reset BTN1, top bits on the LEDs (M8 example)
module counter (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    reg [5:0] q = 6'd0;
    always @(posedge clk)
        if (btn[1])      q <= 6'd0;
        else if (btn[0]) q <= q + 6'd1;
    assign led = q[5:3];
endmodule
