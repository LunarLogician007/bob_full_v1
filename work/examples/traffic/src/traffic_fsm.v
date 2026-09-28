// traffic_fsm.v - the traffic light's controller: which lamp is lit and how long each
// phase lasts. It keeps no time itself: it loads phase_timer with a phase's length in
// ticks and moves to the next phase when the timer has none left.
//
//   green (T_GREEN) -> yellow (T_YELLOW) -> red (T_RED) -> green ...
//
// walk (the crossing button) during green cuts what is left of it to T_CUT ticks. night
// holds the light at red; the block design's night flasher then drives the lamps, and
// when night ends the light runs one red phase before going green.
module traffic_fsm #(
    parameter T_GREEN  = 8,
    parameter T_YELLOW = 2,
    parameter T_RED    = 5,
    parameter T_CUT    = 2
) (
    input  wire       clk,
    input  wire [3:0] left,     // ticks left in this phase, from phase_timer
    input  wire       walk,
    input  wire       night,
    output wire [2:0] lamps,    // {red, yellow, green}
    output wire       load,     // phase_timer takes len on this clock
    output reg  [3:0] len
);
    localparam GREEN = 2'd0, YELLOW = 2'd1, RED = 2'd2;

    reg [1:0] state = RED;      // the timer starts empty, so the first clock goes green
    reg [1:0] next;

    always @* begin
        next = state;
        if (night)
            next = RED;
        else if (left == 4'd0)
            case (state)
                GREEN:   next = YELLOW;
                YELLOW:  next = RED;
                default: next = GREEN;
            endcase
    end

    wire cut = !night && state == GREEN && walk && left > T_CUT;
    assign load = night || next != state || cut;

    always @*
        if (cut)                  len = T_CUT;
        else if (next == GREEN)   len = T_GREEN;
        else if (next == YELLOW)  len = T_YELLOW;
        else                      len = T_RED;

    always @(posedge clk)
        state <= next;

    assign lamps = {state == RED, state == YELLOW, state == GREEN};
endmodule
