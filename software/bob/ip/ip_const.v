// @ip const
// @desc A constant: y = VALUE. Tie off an input you do not use with one of these.
// @param W 1 width
// @param VALUE 0 the value
module ip_const #(parameter W = 1, parameter VALUE = 0) (
    output wire [W-1:0] y
);
    assign y = VALUE;
endmodule
