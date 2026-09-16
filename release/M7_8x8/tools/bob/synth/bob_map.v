// -----------------------------------------------------------------------------
// bob_map.v - yosys techmap rules onto the bob cell library (M8)
//
// Patterned on yosys' own xilinx flow (share/yosys/xilinx: ff_map.v,
// arith_map.v, xc7_dsp_map.v), reduced to what one bob CLB / BRAM / DSP holds.
// -----------------------------------------------------------------------------

// --- flip-flops: after `dfflegalize -cell $_SDFFE_PP0P_ r -cell $_SDFFE_PP1P_ r`
// (sync reset beats enable, init = reset value = the fabric's GSR value)

module \$_SDFFE_PP0P_ (input C, input R, input E, input D, output Q);
    parameter _TECHMAP_WIREINIT_Q_ = 1'bx;
    wire _TECHMAP_REMOVEINIT_Q_ = 1'b1;
    BOB_FDRE #(.INIT(1'b0)) _TECHMAP_REPLACE_ (.C(C), .CE(E), .R(R), .D(D), .Q(Q));
endmodule

module \$_SDFFE_PP1P_ (input C, input R, input E, input D, output Q);
    parameter _TECHMAP_WIREINIT_Q_ = 1'bx;
    wire _TECHMAP_REMOVEINIT_Q_ = 1'b1;
    BOB_FDSE #(.INIT(1'b1)) _TECHMAP_REPLACE_ (.C(C), .CE(E), .S(R), .D(D), .Q(Q));
endmodule

// --- arithmetic: one BOB_ADD (one CLB in carry mode) per bit -------------------
// arith_map.v's MUXCY/XORCY form with bob's constraint that the carry-generate
// input is the LUT's own i[0] (= A). BI must be a constant (add or subtract);
// otherwise the cell is left to the generic map (LUT logic).

// _80_ ranks ahead of the generic _90_alu in +/techmap.v (xilinx does the same)
(* techmap_celltype = "$alu" *)
module _80_bob_alu (A, B, CI, BI, X, Y, CO);
    parameter A_SIGNED = 0;
    parameter B_SIGNED = 0;
    parameter A_WIDTH  = 1;
    parameter B_WIDTH  = 1;
    parameter Y_WIDTH  = 1;
    parameter _TECHMAP_CONSTVAL_BI_ = 0;
    parameter _TECHMAP_CONSTMSK_BI_ = 0;

    (* force_downto *) input  [A_WIDTH-1:0] A;
    (* force_downto *) input  [B_WIDTH-1:0] B;
    (* force_downto *) output [Y_WIDTH-1:0] X, Y;
    input CI, BI;
    (* force_downto *) output [Y_WIDTH-1:0] CO;

    wire _TECHMAP_FAIL_ = (Y_WIDTH <= 1) || (_TECHMAP_CONSTMSK_BI_ != 1);

    (* force_downto *) wire [Y_WIDTH-1:0] A_buf, B_buf;
    \$pos #(.A_SIGNED(A_SIGNED), .A_WIDTH(A_WIDTH), .Y_WIDTH(Y_WIDTH)) A_conv (.A(A), .Y(A_buf));
    \$pos #(.A_SIGNED(B_SIGNED), .A_WIDTH(B_WIDTH), .Y_WIDTH(Y_WIDTH)) B_conv (.A(B), .Y(B_buf));

    (* force_downto *) wire [Y_WIDTH:0] C;
    assign C[0] = CI;

    genvar i;
    generate for (i = 0; i < Y_WIDTH; i = i + 1) begin : slice
        BOB_ADD #(.INV_B(_TECHMAP_CONSTVAL_BI_)) add (
            .A(A_buf[i]), .B(B_buf[i]), .CI(C[i]), .O(Y[i]), .CO(C[i+1]));
    end endgenerate

    assign CO = C[Y_WIDTH:1];
    assign X  = A_buf ^ (_TECHMAP_CONSTVAL_BI_ ? ~B_buf : B_buf);
endmodule

// --- multipliers: mul2dsp splits to <= 25 x 18 signed, each one BOB_DSP ---------

module \$__MUL25X18 (input [24:0] A, input [17:0] B, output [42:0] Y);
    parameter A_SIGNED = 0;
    parameter B_SIGNED = 0;
    parameter A_WIDTH  = 0;
    parameter B_WIDTH  = 0;
    parameter Y_WIDTH  = 0;
    wire [47:0] P;
    BOB_DSP _TECHMAP_REPLACE_ (.A(A), .B(B), .P(P));
    assign Y = P[42:0];
endmodule
