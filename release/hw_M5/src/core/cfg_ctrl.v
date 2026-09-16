// -----------------------------------------------------------------------------
// cfg_ctrl.v - configuration control: CRC, commit decision, status, startup
//
// Implements docs/bitstream-format.md sections 4-6:
//   - serial CRC-32C and a bit counter over every bit shifted in during CFG_IN
//   - commit only if count == CHAIN_W and ~crc == expected CRC (UG470: the
//     integrity check happens before anything is released)
//   - CFG_CTRL (USER2) 64-bit register: status out, expected CRC in behind a
//     write key
//   - JPROGRAM clear, and the JSTART sequence GSR -> GTS -> GWE -> DONE
//
// Edge discipline: counters, flags and startup on the rising edge; the
// expected-CRC write on the falling edge (Update-DR); the cfg commit itself is
// taken by cfg_tile_sr on the falling edge from `cfg_commit`.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module cfg_ctrl #(
    parameter integer CHAIN_W = 64
)(
    input  wire        tck,
    input  wire        tdi,

    input  wire        dr_capture,
    input  wire        dr_shift,
    input  wire        dr_update,
    input  wire        sel_cfg_in,
    input  wire        sel_cfg_out,
    input  wire        sel_ctrl,
    input  wire        jprogram,
    input  wire        jstart_tick,

    // to cfg_mem
    output wire        cfg_capture,
    output wire        cfg_shift,
    output wire        cfg_commit,
    output wire        cfg_clear,

    output wire        ctrl_so,

    output reg         gsr,
    output reg         gts,
    output reg         gwe,
    output reg         done,
    output reg         committed,
    output wire [3:0]  ir_status      // {DONE, INIT_B, COMMITTED, CRC_ERR}
);

    localparam [31:0] CRC_POLY     = 32'h82F63B78;   // CRC-32C, reflected
    localparam [31:0] CRC_INIT     = 32'hFFFFFFFF;
    localparam [7:0]  CTRL_VERSION = 8'h02;
    localparam [7:0]  CTRL_KEY     = 8'hC5;
    localparam [15:0] WANT_COUNT   = CHAIN_W[15:0];

    reg [31:0] crc      = CRC_INIT;
    reg [15:0] count    = 16'h0;
    reg [31:0] expected = 32'h0;
    reg        crc_ok   = 1'b0;
    reg        crc_err  = 1'b0;
    reg        len_err  = 1'b0;
    reg [2:0]  phase    = 3'd0;
    reg [63:0] ctrl_sr  = 64'h0;

    // ---------------------------------------------------------------------
    // Chain strobes. CFG_OUT captures and shifts but can never commit.
    // ---------------------------------------------------------------------
    wire chain_sel = sel_cfg_in | sel_cfg_out;

    assign cfg_capture = chain_sel & dr_capture;
    assign cfg_shift   = chain_sel & dr_shift;
    assign cfg_clear   = jprogram;

    wire [31:0] crc_next  = ((crc[0] ^ tdi) ? ((crc >> 1) ^ CRC_POLY) : (crc >> 1));
    wire        crc_good  = (~crc == expected);
    wire        len_good  = (count == WANT_COUNT);
    wire        load_good = crc_good & len_good;

    assign cfg_commit = sel_cfg_in & dr_update & load_good;

    // ---------------------------------------------------------------------
    // CRC and bit count over one CFG_IN scan
    // ---------------------------------------------------------------------
    always @(posedge tck) begin
        if (sel_cfg_in & dr_capture) begin
            crc   <= CRC_INIT;
            count <= 16'h0;
        end else if (sel_cfg_in & dr_shift) begin
            crc <= crc_next;
            if (count != 16'hFFFF)
                count <= count + 16'h1;
        end
    end

    // ---------------------------------------------------------------------
    // Status flags and startup
    // ---------------------------------------------------------------------
    always @(posedge tck) begin
        if (jprogram) begin
            committed <= 1'b0;
            crc_ok    <= 1'b0;
            crc_err   <= 1'b0;
            len_err   <= 1'b0;
            gsr       <= 1'b1;
            gts       <= 1'b1;
            gwe       <= 1'b0;
            done      <= 1'b0;
            phase     <= 3'd0;
        end else begin
            if (sel_cfg_in & dr_update) begin
                crc_ok  <= load_good;
                crc_err <= ~crc_good;
                len_err <= ~len_good;
                if (load_good)
                    committed <= 1'b1;
            end

            if (jstart_tick & committed & (phase != 3'd4)) begin
                phase <= phase + 3'd1;
                case (phase)
                    3'd0:    gsr  <= 1'b0;
                    3'd1:    gts  <= 1'b0;
                    3'd2:    gwe  <= 1'b1;
                    3'd3:    done <= 1'b1;
                    default: ;
                endcase
            end
        end
    end

    // ---------------------------------------------------------------------
    // CFG_CTRL data register
    // ---------------------------------------------------------------------
    always @(posedge tck) begin
        if (sel_ctrl & dr_capture)
            ctrl_sr <= {CTRL_VERSION, done, gwe, gts, gsr,
                        committed, len_err, crc_err, crc_ok,
                        count, ~crc};
        else if (sel_ctrl & dr_shift)
            ctrl_sr <= {tdi, ctrl_sr[63:1]};
    end

    always @(negedge tck) begin
        if (sel_ctrl & dr_update & (ctrl_sr[63:56] == CTRL_KEY))
            expected <= ctrl_sr[31:0];
    end

    assign ctrl_so   = ctrl_sr[0];
    assign ir_status = {done, ~(crc_err | len_err), committed, crc_err};

    initial begin
        gsr       = 1'b1;
        gts       = 1'b1;
        gwe       = 1'b0;
        done      = 1'b0;
        committed = 1'b0;
    end

    // Only the key and the CRC field are read back from CFG_CTRL on update.
    wire _unused = &{1'b0, ctrl_sr[55:32]};

endmodule

`default_nettype wire
