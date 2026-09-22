// atspeed.v - a self-checking design for the user clock at speed (M20)
//
// a counts every user clock; b is last clock's a; err latches the first clock on which
// a != b + 1. A register that misses its setup time - the carry chain of a, or of b + 1,
// arriving after the enable - breaks that identity on the clock it happens, and err
// keeps it on LD0 however fast the fabric runs. LD1 and LD2 are a's top bits, so the
// counter is visibly alive. BTN1 clears everything (synchronous).
//
// M20's board checks run it at the rate software/bob/timing.py computes, then sweep the
// clock faster until err appears: the first failing rate must be above the computed one.
module atspeed #(parameter W = 12) (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    reg [W-1:0] a   = {W{1'b0}};
    reg [W-1:0] b   = {W{1'b1}};          // so a == b + 1 holds from the first clock
    reg         err = 1'b0;

    always @(posedge clk)
        if (btn[1]) begin
            a   <= {W{1'b0}};
            b   <= {W{1'b1}};
            err <= 1'b0;
        end else begin
            a   <= a + 1'b1;
            b   <= a;
            err <= err | (a != b + 1'b1);   // an OR, not "if () err <= 1": no constant D
        end

    assign led = {a[W-1], a[W-2], err};
endmodule
