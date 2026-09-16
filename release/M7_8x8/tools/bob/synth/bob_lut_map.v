// bob_lut_map.v - $lut -> BOB_LUT, only for the simulation netlist (<top>_syn.v).
// The JSON and BLIF keep yosys' $lut (BLIF .names), which is what the placer and
// VPR read.
(* techmap_celltype = "$lut" *)
module _90_bob_lut (A, Y);
    parameter WIDTH = 1;
    parameter LUT   = 0;
    (* force_downto *) input [WIDTH-1:0] A;
    output Y;
    BOB_LUT #(.K(WIDTH), .INIT(LUT)) _TECHMAP_REPLACE_ (.I(A), .O(Y));
endmodule
