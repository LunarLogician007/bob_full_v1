// -----------------------------------------------------------------------------
// bob_brams_map.v - memory_libmap's $__BOB_BRAM_ (bob_brams.txt) -> BOB_BRAM18 (M8)
//
// Port and parameter names are the ones memory_libmap emits for an srsw port
// pair with a shared named clock "C" and a global width (checked by probing it).
// Narrower memories keep their width here; the unused data bits of the 18-bit
// block are tied off.
// -----------------------------------------------------------------------------

module \$__BOB_BRAM_ (...);
    parameter INIT  = 0;
    parameter WIDTH = 18;
    parameter PORT_A_OPTION_WRITE_MODE = "READ_FIRST";
    parameter PORT_A_USED = 1;
    parameter PORT_B_OPTION_WRITE_MODE = "READ_FIRST";
    parameter PORT_B_USED = 0;

    input              CLK_C;

    input              PORT_A_CLK;
    input              PORT_A_CLK_EN;
    input  [9:0]       PORT_A_ADDR;
    input  [WIDTH-1:0] PORT_A_WR_DATA;
    input              PORT_A_WR_EN;
    input              PORT_A_RD_SRST;
    output [WIDTH-1:0] PORT_A_RD_DATA;

    input              PORT_B_CLK;
    input              PORT_B_CLK_EN;
    input  [9:0]       PORT_B_ADDR;
    input  [WIDTH-1:0] PORT_B_WR_DATA;
    input              PORT_B_WR_EN;
    input              PORT_B_RD_SRST;
    output [WIDTH-1:0] PORT_B_RD_DATA;

    function [1:0] wmode(input [8*11:1] s);
        wmode = (s == "WRITE_FIRST") ? 2'd0 : (s == "NO_CHANGE") ? 2'd2 : 2'd1;
    endfunction

    wire [17:0] do_a, do_b;

    BOB_BRAM18 #(
        .WMODE_A (wmode(PORT_A_OPTION_WRITE_MODE)),
        .WMODE_B (wmode(PORT_B_OPTION_WRITE_MODE)),
        .INIT    (INIT)
    ) _TECHMAP_REPLACE_ (
        .CLK    (CLK_C),
        .A_ADDR (PORT_A_ADDR),
        .A_DI   (PORT_A_WR_DATA),
        .A_WE   (PORT_A_WR_EN),
        .A_EN   (PORT_A_CLK_EN),
        .A_RST  (PORT_A_RD_SRST),
        .A_DO   (do_a),
        .B_ADDR (PORT_B_ADDR),
        .B_DI   (PORT_B_WR_DATA),
        .B_WE   (PORT_B_WR_EN),
        .B_EN   (PORT_B_CLK_EN),
        .B_RST  (PORT_B_RD_SRST),
        .B_DO   (do_b)
    );

    assign PORT_A_RD_DATA = do_a[WIDTH-1:0];
    assign PORT_B_RD_DATA = do_b[WIDTH-1:0];
endmodule
