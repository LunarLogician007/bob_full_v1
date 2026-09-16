// gates.v - combinational logic of the board inputs (M8 example)
module gates (
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    assign led[0] = sw[0] & sw[1];
    assign led[1] = ^{sw, btn};               // parity of all six inputs
    assign led[2] = btn[0] ? sw[1] : (sw[0] | btn[3]);
endmodule
