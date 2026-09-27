// initval.v - flip-flops that start at one value and reset to the other (M26 example)
// Since M26 a bob flip-flop keeps INIT (the value it starts at, and the value GSR and
// GRESTORE load) apart from SRVAL (the value its synchronous reset loads), as UG474's
// FDRE / FDSE do. Built with --clock run:
//   LD0  starts lit (INIT 1); BTN0 clears it (reset to 0), BTN1 sets it again
//   LD1  starts dark (INIT 0); BTN0 sets it (reset to 1), BTN2 clears it again
//   LD2  starts lit (INIT 1, no reset); BTN3 loads SW0 into it
// Every bob before M26 started LD1..0 at their reset values instead: LD0 dark, LD1 lit.
module initval (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    reg a = 1'b1, b = 1'b0, c = 1'b1;
    always @(posedge clk) begin
        if (btn[0]) a <= 1'b0; else if (btn[1]) a <= 1'b1;
        if (btn[0]) b <= 1'b1; else if (btn[2]) b <= 1'b0;
        if (btn[3]) c <= sw[0];
    end
    assign led = {c, b, a};
endmodule
