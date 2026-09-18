// fir.v - a 2-tap FIR filter on the two DSP slices (M11 example)
// Sample x = {SW1, SW0} is registered every clock into a two-stage delay line;
// y = x[n] * h0 + x[n-1] * h1 with coefficients h0 = {BTN3, BTN2, 1} and
// h1 = {BTN2, BTN3, 1} from the buttons, so each product is a real multiplier
// (one per DSP slice). y is registered; LD2..0 = y[4:2]. Sized for the 16-CLB
// board profile (a 3-bit sample needs 17 CLBs).
module fir (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    reg  [1:0] x0 = 2'd0, x1 = 2'd0;
    reg  [5:0] y  = 6'd0;
    wire [2:0] h0 = {btn[3], btn[2], 1'b1};
    wire [2:0] h1 = {btn[2], btn[3], 1'b1};
    always @(posedge clk) begin
        x0 <= sw;
        x1 <= x0;
        y  <= x0 * h0 + x1 * h1;
    end
    assign led = y[4:2];
endmodule
