// -----------------------------------------------------------------------------
// LUT6.v - simulation model of AMD's LUT6 (UG953), for iverilog and verilator only (M23)
//
// Not in hw/sources.f (sim/hwfiles.sh --sim adds it); Vivado and yosys have their own. O =
// INIT[{I5..I0}]; an unknown address reads known when every entry it could be agrees (as
// UNISIM's model), so a mux whose unselected inputs are X still passes the selected one.
// -----------------------------------------------------------------------------
`timescale 1ns / 1ps
`ifndef SYNTHESIS
module LUT6 #(
    parameter [63:0] INIT = 64'h0
)(
    output wire O,
    input  wire I0, I1, I2, I3, I4, I5
);
    function lut_read(input [5:0] a);
        integer k, b;
        reg seen, val, bad, match;
        if (^a !== 1'bx)
            lut_read = INIT[a];
        else begin
            seen = 1'b0; val = 1'b0; bad = 1'b0;
            for (k = 0; k < 64; k = k + 1) begin
                match = 1'b1;
                for (b = 0; b < 6; b = b + 1)
                    if ((a[b] === 1'b0 && k[b]) || (a[b] === 1'b1 && !k[b]))
                        match = 1'b0;
                if (match) begin
                    if (!seen) begin val = INIT[k]; seen = 1'b1; end
                    else if (INIT[k] !== val) bad = 1'b1;
                end
            end
            lut_read = bad ? 1'bx : val;
        end
    endfunction
    assign O = lut_read({I5, I4, I3, I2, I1, I0});
endmodule
`endif
