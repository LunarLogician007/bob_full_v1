// phase_timer.v - counts a phase down in ticks: load takes len, then every tick takes
// one off until none is left. left is what the controller reads.
module phase_timer (
    input  wire       clk,
    input  wire       tick,
    input  wire       load,
    input  wire [3:0] len,
    output reg  [3:0] left = 4'd0
);
    always @(posedge clk)
        if (load)
            left <= len;
        else if (tick && left != 4'd0)
            left <= left - 1'b1;
endmodule
