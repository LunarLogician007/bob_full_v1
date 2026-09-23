// -----------------------------------------------------------------------------
// lut_expand.v - the CFGLUT5 shift data for every slot of an L-frame (M22)
//
// One instance serves the whole fabric: its outputs depend only on the frame being loaded
// (lbuf) and the shift count, so every CLB shares the nets and its CE picks it
// (lut_loader.v). Shift cycle c writes CFGLUT5 address a = 31 - c (the first bit shifted in
// ends at bit 31, UG953).
//
//   INIT slot s (bits [s*2**K +: 2**K] of an INIT frame): the lo CFGLUT5 takes
//       INIT[a] and the hi one INIT[2**(K-1) + a], for a < 2**(K-1) (0 above: K < 6)
//   crossbar slots 2p, 2p+1 (bits [t*XW +: XW] of a crossbar frame, select values va, vb):
//       pair p, lxpair.v's shared leaves (M23). Addresses 31:16 are mux b's half (vb),
//       15:0 mux a's (va); in a half, v = 0 const0 (all zero), v = 1 const1 (leaf 0 all
//       ones), v = 2 + i picks source i: leaf i/4 holds address bit i%4, the others zero.
//       Values past the last source read const0, as bob_mux.v's padding does.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module lut_expand #(
    parameter integer FB   = 128,
    parameter integer K    = 6,
    parameter integer NI   = 2,        // INIT slots per INIT frame (FB / 2**K)
    parameter integer XW   = 5,        // crossbar select width
    parameter integer NX   = 25,       // crossbar slots per crossbar frame
    parameter integer S    = 24,       // crossbar sources
    parameter integer L    = (S + 3) / 4,  // leaves per pair
    parameter integer NP   = NX / 2        // pairs per crossbar frame
)(
    input  wire [FB-1:0]     lbuf,
    input  wire [4:0]        cnt,
    output wire [2*NI-1:0]   cdi_init,     // slot s: [2s] lo, [2s+1] hi
    output wire [NP*L-1:0]   cdi_x         // pair p (slots 2p, 2p+1): [p*L +: L] as lxpair.v's lcdi
);

    localparam integer IW   = 1 << K;
    localparam integer HALF = 1 << (K - 1);

    wire [4:0] a = ~cnt;                   // 31 - cnt

    wire [2*NP*L-1:0] hb;                  // slot t's half of every leaf at address a: [t*L +: L]

    genvar s, t, g;
    generate
        for (s = 0; s < NI; s = s + 1) begin : g_init
            wire [HALF-1:0] lo = lbuf[s*IW +: HALF];
            wire [HALF-1:0] hi = lbuf[s*IW + HALF +: HALF];
            if (HALF == 32) begin : g_full
                assign cdi_init[2*s]     = lo[a];
                assign cdi_init[2*s + 1] = hi[a];
            end else begin : g_part
                wire in_range = ({27'd0, a} < HALF);
                assign cdi_init[2*s]     = in_range & lo[a[K-2:0]];
                assign cdi_init[2*s + 1] = in_range & hi[a[K-2:0]];
            end
        end

        for (t = 0; t < 2 * NP; t = t + 1) begin : g_x
            wire [XW-1:0] v   = lbuf[t*XW +: XW];
            wire [31:0]   v32 = {{(32-XW){1'b0}}, v};
            wire          one = (v32 == 32'd1);
            wire          src = (v32 >= 32'd2) && (v32 < S + 2);
            wire [31:0]   i32 = v32 - 32'd2;
            for (g = 0; g < L; g = g + 1) begin : g_leaf
                assign hb[t*L + g] = (one && g == 0) || (src && i32[31:2] == g && a[{1'b0, i32[1:0]}]);
            end
        end
        for (t = 0; t < NP; t = t + 1) begin : g_p
            assign cdi_x[t*L +: L] = a[4] ? hb[(2*t+1)*L +: L] : hb[2*t*L +: L];
        end
    endgenerate

endmodule

`default_nettype wire
