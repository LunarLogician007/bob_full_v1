// ram.v - a block RAM written from the switches and read back (M8 example)
// BTN0 writes {btn3, btn2, sw1} into address {sw1, sw0}; the LEDs show the word read.
module ram (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    (* ram_style = "block" *)
    reg [2:0] mem [0:1023];
    reg [2:0] q = 3'd0;
    initial begin
        mem[0] = 3'b001; mem[1] = 3'b010; mem[2] = 3'b100; mem[3] = 3'b111;
    end
    always @(posedge clk) begin
        if (btn[0]) mem[{8'd0, sw}] <= {btn[3], btn[2], sw[1]};
        q <= mem[{8'd0, sw}];
    end
    assign led = q;
endmodule
