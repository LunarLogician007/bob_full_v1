// switches.v - the switches and buttons live on the LEDs (M11 example)
// LD0 = SW0 xor SW1; LD1 = BTN0 or (BTN1 and SW0); LD2 toggles on every BTN3 press
// (two-flop synchroniser, rising-edge detector, toggle register). Built with
// --clock run, it is what a user sees when flipping switches on the board.
module switches (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    reg [1:0] s = 2'b00;
    reg       t = 1'b0;
    always @(posedge clk) begin
        s <= {s[0], btn[3]};
        if (s[0] & ~s[1]) t <= ~t;
    end
    assign led = {t, btn[0] | (btn[1] & sw[0]), sw[0] ^ sw[1]};
endmodule
