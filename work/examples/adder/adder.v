// adder.v - {sw1,sw0} + btn[1:0] on the carry chain (M8 example)
module adder (
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    assign led = sw + btn[1:0];
endmodule
