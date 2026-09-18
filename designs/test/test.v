// test.v - a bob design.
//
// The default pin convention is sw[1:0] -> SW1..0, btn[3:0] -> BTN3..0,
// led[2:0] -> LD2..0. Use the Pin Planner for anything else; it writes a .pcf
// and the next build picks it up.
//
// One clock only, no asynchronous resets, no latches: the fabric has one user
// clock and every flip-flop is enabled by it.
module test 
(
    input  wire [3:0]     a,
    input  wire [3:0]     b,
    output wire [5:0]   product
);
    assign product = a * b;
endmodule

