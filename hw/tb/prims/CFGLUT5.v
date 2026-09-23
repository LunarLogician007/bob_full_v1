// -----------------------------------------------------------------------------
// CFGLUT5.v - simulation model of AMD's CFGLUT5 (UG953), for iverilog and verilator only
//
// Vivado and yosys (synth_xilinx) use their own primitive: this file is NOT in hw/sources.f
// (sim/hwfiles.sh --sim adds it), and its body is skipped under SYNTHESIS in case a yosys
// flow reads it. Behaviour as UG953 and yosys' cells_sim.v: a 32-bit shift register, CDI
// into bit 0 on CLK while CE, CDO = bit 31; O6 = bit {I4..I0}, O5 = bit {0, I3..I0}.
//
// Two liberties, for the simulator only (see also the output delay below): O5/O6 show the contents as they stand when CE is
// low, and hold them while a table is being shifted. On silicon a half-shifted table is
// visible, but bob only shifts with the fabric frozen (GWE low or the clock held), so
// nothing ever samples it; in a zero-delay simulator the same transient could wire an
// element's output back to its own input and spin the simulation forever (M22).
// -----------------------------------------------------------------------------
`timescale 1ns / 1ps
`ifndef SYNTHESIS
module CFGLUT5 #(
    parameter [31:0] INIT = 32'h00000000,
    parameter [0:0]  IS_CLK_INVERTED = 1'b0
)(
    output wire CDO,
    output wire O5,
    output wire O6,
    input  wire I4, I3, I2, I1, I0,
    input  wire CDI,
    input  wire CE,
    input  wire CLK
);
    reg [31:0] r = INIT;
    reg [31:0] v = INIT;                     // what O5/O6 read (see above)
    wire clk = CLK ^ IS_CLK_INVERTED;
    assign CDO = r[31];
    // a LUT read with unknown address bits is known when every entry it could be agrees
    // (as UNISIM's LUT models): an all-zero table reads 0 whatever feeds it
    function lut_read(input [31:0] t, input [4:0] a);
        integer k, b;
        reg seen, val, bad, match;
        if (^a !== 1'bx)
            lut_read = t[a];                           // the usual case: a known address
        else begin
            seen = 1'b0; val = 1'b0; bad = 1'b0;
            for (k = 0; k < 32; k = k + 1) begin
                match = 1'b1;
                for (b = 0; b < 5; b = b + 1)
                    if ((a[b] === 1'b0 && k[b]) || (a[b] === 1'b1 && !k[b]))
                        match = 1'b0;                  // a known address bit that differs
                if (match) begin
                    if (!seen) begin val = t[k]; seen = 1'b1; end
                    else if (t[k] !== val) bad = 1'b1;
                end
            end
            lut_read = bad ? 1'bx : val;
        end
    endfunction
    // 10 ps, far below a real LUT (~100 ps) and the benches' sampling waits, but not zero: a
    // configuration load passes through states where one CLB's crossbar and the routing are
    // live before another CLB's flags arrive, which can close a loop through LUTs (harmless
    // on silicon: GWE is low and the pads held). With zero delay such a transient ring
    // oscillator spins the simulator in one time step forever (M22's tb_synth, blinky); with
    // a delay it oscillates in simulated time and dies when the load completes. Every loop
    // that can oscillate inverts somewhere, i.e. passes through a LUT, i.e. through here.
    assign #0.01 O5 = lut_read(v, {1'b0, I3, I2, I1, I0});
    assign #0.01 O6 = lut_read(v, {I4, I3, I2, I1, I0});
    always @(posedge clk) if (CE) r <= {r[30:0], CDI};
    /* verilator lint_off LATCH */
    always @(r or CE) if (!CE) v = r;                // a latch on purpose (see above)
    /* verilator lint_on LATCH */
endmodule
`endif
