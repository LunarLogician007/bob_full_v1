// night_flash.v - the lamps at night: yellow on for one tick, off for the next.
module night_flash (
    input  wire       clk,
    input  wire       tick,
    output wire [2:0] lamps     // {red, yellow, green}
);
    reg on = 1'b0;
    always @(posedge clk)
        if (tick) on <= ~on;
    assign lamps = {1'b0, on, 1'b0};
endmodule
