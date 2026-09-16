// blinky.v - free-running 12-bit counter, top three bits on the LEDs (M8 example)
// Longer than a CLB column, so its carry chain crosses columns.
module blinky (
    input  wire       clk,
    output wire [2:0] led
);
    reg [11:0] q = 12'd0;
    always @(posedge clk)
        q <= q + 12'd1;
    assign led = q[11:9];
endmodule
