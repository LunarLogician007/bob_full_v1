// fir16.v - a 16-tap FIR filter in logic (M21 example), several times the whole 100-LUT
// M16 fabric. The 4-bit sample x = {BTN3, BTN2, SW1, SW0} shifts into a 16-deep delay line
// on every clock while BTN0 is held; BTN1 clears the line and the output (synchronous).
// The taps are a symmetric low-pass kernel (sum 100), so y = sum h[i] * x[n-i] is
// 0..1500 and needs 11 bits; y is registered. Every product is a shift-add of the
// constant tap (no DSP slice: all of it is fabric). LD0 is the parity of y (every bit of
// y reaches an output), LD1 its top bit, LD2 bit 5.
module fir16 (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    localparam [63:0] H = {4'd1, 4'd2, 4'd3, 4'd5, 4'd7, 4'd9, 4'd11, 4'd12,
                           4'd12, 4'd11, 4'd9, 4'd7, 4'd5, 4'd3, 4'd2, 4'd1};
    wire [3:0]  x  = {btn[3], btn[2], sw};
    reg  [63:0] dl = 64'd0;                  // x[n-i] at dl[4i +: 4]
    reg  [10:0] y  = 11'd0;

    // term i = h[i] * x[n-i], as shift-adds of the constant; acc[i+1] = acc[i] + term i
    wire [10:0] acc [0:16];
    assign acc[0] = 11'd0;
    genvar i;
    generate
        for (i = 0; i < 16; i = i + 1) begin : g_tap
            wire [3:0]  h = H[4*i +: 4];
            wire [3:0]  s = dl[4*i +: 4];
            wire [10:0] t = (s[0] ? {7'd0, h} : 11'd0) + (s[1] ? {6'd0, h, 1'b0} : 11'd0)
                          + (s[2] ? {5'd0, h, 2'b0} : 11'd0) + (s[3] ? {4'd0, h, 3'b0} : 11'd0);
            assign acc[i+1] = acc[i] + t;
        end
    endgenerate

    always @(posedge clk) begin
        if (btn[1]) begin
            dl <= 64'd0;
            y  <= 11'd0;
        end else begin
            if (btn[0])
                dl <= {dl[59:0], x};
            y <= acc[16];
        end
    end
    assign led = {y[5], y[10], ^y};
endmodule
