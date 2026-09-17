// big.v - a design that does not fit the 36-CLB grid (M16 example): a 24-bit LFSR and a
// 16-bit counter, about 55 CLBs. BTN0 steps both, BTN1 resets them; the LEDs mix parity of
// the LFSR, parity of the counter and the two switches, so every register reaches an output.
module big (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    reg [23:0] lfsr = 24'h000001;
    reg [15:0] cnt  = 16'h0000;
    always @(posedge clk)
        if (btn[1]) begin
            lfsr <= 24'h000001;
            cnt  <= 16'h0000;
        end else if (btn[0]) begin
            lfsr <= {lfsr[22:0], lfsr[23] ^ lfsr[22] ^ lfsr[21] ^ lfsr[16]};
            cnt  <= cnt + 16'h1;
        end
    assign led = {^lfsr ^ sw[0], ^cnt ^ sw[1], lfsr[0] & cnt[0]};
endmodule
