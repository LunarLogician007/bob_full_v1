// A single IEEE 1149.1 boundary scan cell, BC_1 style.
//
// BC_1 is the general-purpose cell: it can capture, it can drive, and it works
// unchanged at an input, at an output, or at a control point. One design
// serves the whole boundary, which is why it is the cell BSDL packages assume
// when nothing more specific is declared.
//
//   data_in ------+------------------------[ 0 ]--- data_out
//                 |                         [mux]
//                 v                         [ 1 ]
//            [capture/shift]---> [update] ----^
//   scan_in ----> [  flop     ]--+--> [ flop ]
//                                |
//                                +----------------- scan_out
//
// Two flops per cell, and that split is the point of the cell:
//
//   capture_reg  sits in the scan chain. It samples the system value at
//                Capture-DR and then shifts, so shifting new data through the
//                boundary never disturbs what the cell is driving.
//   update_reg   holds the value the cell drives. It only moves at Update-DR,
//                so the boundary changes once, as a unit, at a point the test
//                controls -- not gradually as bits ripple past.
//
// That separation is what makes PRELOAD possible: a full boundary can be
// staged in the capture flops while mode is still 0, and applied to the pins
// on a single Update-DR.
//
// ---------------------------------------------------------------------------
// Clock edges
// ---------------------------------------------------------------------------
// capture_reg clocks on the RISING edge, matching the shift registers inside
// jtag_tap.v: capture_dr / shift_dr are high for the whole of the state they
// name, and the flop acts on the edge that ends it.
//
// update_reg clocks on the FALLING edge, as IEEE 1149.1 requires. update_dr is
// high through Update-DR, so the falling edge in the middle of that state
// moves the outputs half a cycle away from any rising edge -- the same
// separation [FIX 1] gives TDO.
//
// ---------------------------------------------------------------------------
// Resets: one asynchronous, one synchronous, and the split is [FIX 5]
// ---------------------------------------------------------------------------
// trst is the real TRST pin. It has to be asynchronous -- that is the whole
// point of the signal, and [FIX 3] in jtag_tap.v says why: a synchronous TRST
// does nothing while TCK is parked.
//
// rst is Test-Logic-Reset, and it MUST NOT be asynchronous, because it is a
// combinational decode of the TAP state register (TLR is 4'b0000). Look at the
// transition into the state where these flops matter most:
//
//     Exit1-DR 0101  ->  Update-DR 1000
//
// The source and destination share no set bit. If the falling bits reach the
// decode before the rising ones -- and no constraint says they may not -- it
// momentarily reads 0000 and fires a reset into every flop below, in the
// instant before update_reg samples capture_reg. The update then faithfully
// commits a zero, the boundary never drives its pins, and EXTEST and INTEST
// both fail while capture and shift look perfect.
//
// That is not hypothetical. It is what the PYNQ-Z2 PS+PL build did, while the
// identical RTL passed in the pl_only build -- a decode glitch is a routing
// artefact, so it is placement dependent and never appears in RTL simulation
// at all. See ps/probe_preload.py, which isolates it: the boundary holds data
// across Exit1 -> Pause -> Exit2 -> Shift (every transition there keeps bit 2
// high, so the decode cannot reach 0000) and loses it across Exit1 -> Update.
//
// Sampling rst on the clock edge makes a glitch between edges unobservable.
// The cost is that entering TLR clears the cells on the next TCK edge rather
// than instantly -- which no host can tell apart, because reaching TLR takes
// five clocked TMS=1s and bsr_mode drops on the first of them, so the boundary
// is already transparent.

`default_nettype none

module bsc_cell (
    input  wire tck,
    input  wire trst,       // TRST pin only. ASYNCHRONOUS, active high.
    input  wire rst,        // Test-Logic-Reset. SYNCHRONOUS -- see above.

    // Strobes from the TAP. These are already qualified by the instruction,
    // so the cell needs no opcode decode of its own.
    input  wire capture_dr,
    input  wire shift_dr,
    input  wire update_dr,
    input  wire mode,       // 1 = drive data_out from update_reg

    // System path
    input  wire data_in,
    output wire data_out,

    // Scan path
    input  wire scan_in,
    output wire scan_out
);

  /* verilator lint_off PROCASSINIT */
  reg capture_reg = 1'b0;
  reg update_reg  = 1'b0;
  /* verilator lint_on PROCASSINIT */

  always @(posedge tck or posedge trst) begin
    if (trst)            capture_reg <= 1'b0;
    else if (rst)        capture_reg <= 1'b0;   // synchronous [FIX 5]
    else if (capture_dr) capture_reg <= data_in;
    else if (shift_dr)   capture_reg <= scan_in;
  end

  always @(negedge tck or posedge trst) begin
    if (trst)           update_reg <= 1'b0;
    else if (rst)       update_reg <= 1'b0;     // synchronous [FIX 5]
    else if (update_dr) update_reg <= capture_reg;
  end

  // Reset leaves mode low as well, so the boundary is transparent after a
  // chain reset and the device behaves as if the JTAG logic were not there.
  assign data_out = mode ? update_reg : data_in;
  assign scan_out = capture_reg;

endmodule

`default_nettype wire
