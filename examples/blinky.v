// blinky.v - free-running 8-bit counter, top three bits on the LEDs (M8 example)
// Longer than a CLB column, so its carry chain crosses columns.
module blinky (
    input  wire       clk,
    output wire [2:0] led
);
    reg [7:0] q = 8'd0;
    always @(posedge clk)
        q <= q + 8'd1;
    assign led = q[7:5];
endmodule
