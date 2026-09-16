// -----------------------------------------------------------------------------
// capture_chain.v - read-only snapshot of user state (USER3 = CAPTURE)
//
// AMD readback capture in scan form: Capture-DR copies the live user-state
// vector, Shift-DR shifts it out LSB first, Update-DR does nothing. Nothing in
// the design is disturbed. See docs/bitstream-format.md section 7.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module capture_chain #(
    parameter integer N = 16            // >= 2
)(
    input  wire         tck,
    input  wire         capture,
    input  wire         shift,
    input  wire         tdi,
    input  wire [N-1:0] d,
    output wire         so
);

    reg [N-1:0] sr = {N{1'b0}};

    always @(posedge tck) begin
        if (capture)
            sr <= d;
        else if (shift)
            sr <= {tdi, sr[N-1:1]};
    end

    assign so = sr[0];

endmodule

`default_nettype wire
