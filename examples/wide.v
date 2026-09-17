// wide.v - 12-bit counter + 8-bit LFSR: 20 flip-flops, more CLBs than the old 16-CLB grid
// had (M12b example). BTN0 steps both, BTN1 resets both; the LEDs mix counter, LFSR and
// switches so every register reaches an output.
module wide (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    reg [11:0] cnt  = 12'd0;
    reg [7:0]  lfsr = 8'h01;
    always @(posedge clk)
        if (btn[1]) begin
            cnt  <= 12'd0;
            lfsr <= 8'h01;
        end else if (btn[0]) begin
            cnt  <= cnt + 12'd1;
            lfsr <= {lfsr[6:0], lfsr[7] ^ lfsr[5] ^ lfsr[4] ^ lfsr[3]};
        end
    assign led = {^cnt[11:6] ^ lfsr[7], ^cnt[5:0] ^ sw[0], ^lfsr[6:0] ^ sw[1]};
endmodule
