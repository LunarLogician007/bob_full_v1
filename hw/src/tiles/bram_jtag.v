// -----------------------------------------------------------------------------
// bram_jtag.v - BRAM contents and test access over JTAG USER4 (M5, M7)
//
// UG470 keeps BRAM *contents* separate from configuration (their own frame
// block type) and lets them be written only before startup. Scan-chain
// version: a 96-bit data register on USER4 (100011), shared by every BRAM in
// the fabric; SELECT picks the one the other commands act on (M7).
//
//   capture   [17:0]  rdata    word read by the last READ
//             [27:18] ptr      address pointer
//             [45:28] do_a     live port A output of the selected BRAM
//             [63:46] do_b     live port B output of the selected BRAM
//             [64]    err      last WRITE/READ refused (GWE was 1)
//             [65]    gwe
//             [69:66] target   selected BRAM
//             [87:70] 0
//             [95:88] version 0x07
//
//   update    [95:92] command, [63:0] payload - a scan that shifts the capture
//             back (command nibble 0) does nothing:
//               1 LOAD_PTR   ptr <- payload[9:0], err <- 0
//               2 WRITE      mem[ptr] <- payload[17:0], ptr++   (GWE = 0 only)
//               3 READ       rdata <- mem[ptr], ptr++           (GWE = 0 only)
//               4 SET_DRIVE  selected BRAM's drive <- payload[63:0] (its pins
//                            when its jtag_a / jtag_b config bit is set)
//               5 SELECT     target <- payload[3:0] (ignored if >= NBRAM)
//
// Commands are latched in the TCK domain and handed to the sysclk domain with a
// toggle through a two-flop synchroniser; the payload and target are stable long
// before the toggle arrives. Reads and writes go through bram_core's port A.
//
// M15: BRAM content FRAMES from cfg_frames.v (FAR block type 1) use the same port:
// bf_wr_t / bf_rd_t toggle with bf_tgt, bf_addr and (write) bf_data stable; the
// sequencer here writes or reads the frame's 4 words on consecutive pairs of sysclk
// cycles (reads land in bf_rdata), only while GWE = 0. A frame takes ~12 sysclk
// cycles; consecutive frame requests are >= 32 TCK periods apart (docs/
// bitstream-format.md section 11, rule 4).
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module bram_jtag #(
    parameter integer ADDR_W = 10,
    parameter integer DATA_W = 18,
    parameter integer NPIN   = 64,
    parameter integer NBRAM  = 2          // 1..15
)(
    // TCK domain
    input  wire                     tck,
    input  wire                     tdi,
    input  wire                     sel,
    input  wire                     dr_capture,
    input  wire                     dr_shift,
    input  wire                     dr_update,
    output wire                     so,
    output reg  [NBRAM*NPIN-1:0]    drive,

    // sysclk domain
    input  wire                     sysclk,
    input  wire                     gwe_s,
    input  wire [NBRAM*DATA_W-1:0]  do_a,
    input  wire [NBRAM*DATA_W-1:0]  do_b,
    input  wire [NBRAM*DATA_W-1:0]  ram_a_q,
    output reg  [NBRAM-1:0]         init_go,
    output reg                      init_wr,
    output reg  [ADDR_W-1:0]        init_addr,
    output reg  [DATA_W-1:0]        init_data,

    // M15: content frames (TCK-domain request, sysclk-domain result)
    input  wire                     bf_wr_t,
    input  wire                     bf_rd_t,
    input  wire [3:0]               bf_tgt,
    input  wire [ADDR_W-1:0]        bf_addr,
    input  wire [4*DATA_W-1:0]      bf_data,
    output reg  [4*DATA_W-1:0]      bf_rdata
);

    localparam [7:0] VERSION = 8'h07;
    localparam [3:0] CMD_LOAD_PTR = 4'h1, CMD_WRITE = 4'h2, CMD_READ = 4'h3,
                     CMD_DRIVE = 4'h4, CMD_SELECT = 4'h5;

    // ---------------------------------------------------------------------
    // TCK domain: the data register, target and the command latch
    // ---------------------------------------------------------------------
    reg [95:0] sr     = 96'h0;
    reg [3:0]  cmd_q  = 4'h0;
    reg [63:0] pay_q  = 64'h0;
    reg        req_t  = 1'b0;
    reg [3:0]  target = 4'h0;
    reg [3:0]  tgt_q  = 4'h0;

    reg [ADDR_W-1:0] ptr   = {ADDR_W{1'b0}};
    reg              err   = 1'b0;
    reg [DATA_W-1:0] rdata = {DATA_W{1'b0}};

    wire [DATA_W-1:0] sel_do_a = do_a[target*DATA_W +: DATA_W];
    wire [DATA_W-1:0] sel_do_b = do_b[target*DATA_W +: DATA_W];

    always @(posedge tck) begin
        if (sel & dr_capture)
            sr <= {VERSION, 18'h0, target, gwe_s, err, sel_do_b, sel_do_a, ptr, rdata};
        else if (sel & dr_shift)
            sr <= {tdi, sr[95:1]};
    end

    always @(negedge tck) begin
        if (sel & dr_update) begin
            if (sr[95:92] == CMD_DRIVE)
                drive[target*NPIN +: NPIN] <= sr[NPIN-1:0];
            else if (sr[95:92] == CMD_SELECT) begin
                if ({28'h0, sr[3:0]} < NBRAM)
                    target <= sr[3:0];
            end else if (sr[95:92] != 4'h0) begin
                cmd_q <= sr[95:92];
                pay_q <= sr[63:0];
                tgt_q <= target;
                req_t <= ~req_t;
            end
        end
    end

    assign so = sr[0];

    initial drive = {(NBRAM*NPIN){1'b0}};

    // ---------------------------------------------------------------------
    // sysclk domain: execute one command per toggle
    // ---------------------------------------------------------------------
    (* ASYNC_REG = "TRUE" *) reg [1:0] req_m = 2'b00;
    reg req_d = 1'b0;
    reg rd_d  = 1'b0;

    wire [NBRAM-1:0] tgt_onehot;
    genvar gi;
    generate
        for (gi = 0; gi < NBRAM; gi = gi + 1) begin : g_tgt
            localparam [3:0] IDX = gi;
            assign tgt_onehot[gi] = (tgt_q == IDX);
        end
    endgenerate

    // M15 frame sequencer
    (* ASYNC_REG = "TRUE" *) reg [1:0] bfw_m = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0] bfr_m = 2'b00;
    reg              bfw_d = 1'b0, bfr_d = 1'b0;
    reg [3:0]        bstep = 4'd0;                 // 0 idle; 1,3,5,7 issue word 0..3
    reg              bwr   = 1'b0;
    reg [3:0]        btgt  = 4'd0;
    reg [ADDR_W-1:0] baddr = {ADDR_W{1'b0}};
    reg [4*DATA_W-1:0] bdata = {(4*DATA_W){1'b0}};
    reg              brd1 = 1'b0, brd2 = 1'b0;
    reg [1:0]        bk1 = 2'd0, bk2 = 2'd0;
    wire [1:0]       bk = bstep[2:1];              // (bstep - 1) / 2 for odd steps
    wire [NBRAM-1:0] btgt_onehot;
    generate
        for (gi = 0; gi < NBRAM; gi = gi + 1) begin : g_btgt
            localparam [3:0] BIDX = gi;
            assign btgt_onehot[gi] = (btgt == BIDX);
        end
    endgenerate

    initial begin
        bf_rdata  = {(4*DATA_W){1'b0}};
        init_go   = {NBRAM{1'b0}};
        init_wr   = 1'b0;
        init_addr = {ADDR_W{1'b0}};
        init_data = {DATA_W{1'b0}};
    end

    always @(posedge sysclk) begin
        req_m   <= {req_m[0], req_t};
        req_d   <= req_m[1];
        init_go <= {NBRAM{1'b0}};
        if (req_m[1] ^ req_d) begin
            case (cmd_q)
                CMD_LOAD_PTR: begin
                    ptr <= pay_q[ADDR_W-1:0];
                    err <= 1'b0;
                end
                CMD_WRITE, CMD_READ: begin
                    if (!gwe_s) begin
                        init_go        <= tgt_onehot;
                        init_wr        <= (cmd_q == CMD_WRITE);
                        init_addr      <= ptr;
                        init_data      <= pay_q[DATA_W-1:0];
                        ptr            <= ptr + 1'b1;
                    end else
                        err <= 1'b1;
                end
                default: ;
            endcase
        end
        rd_d <= |init_go & ~init_wr;
        if (rd_d) rdata <= ram_a_q[tgt_q*DATA_W +: DATA_W];

        // ---- M15 content frames ----
        bfw_m <= {bfw_m[0], bf_wr_t};
        bfr_m <= {bfr_m[0], bf_rd_t};
        bfw_d <= bfw_m[1];
        bfr_d <= bfr_m[1];
        brd1  <= 1'b0;
        brd2  <= brd1;
        bk2   <= bk1;
        if (bstep == 4'd0) begin
            if ((bfw_m[1] ^ bfw_d) || (bfr_m[1] ^ bfr_d)) begin
                bwr   <= bfw_m[1] ^ bfw_d;
                btgt  <= bf_tgt;
                baddr <= bf_addr;
                bdata <= bf_data;
                if (!gwe_s) bstep <= 4'd1;
            end
        end else begin
            bstep <= (bstep == 4'd9) ? 4'd0 : bstep + 4'd1;
            if (bstep[0] && bstep <= 4'd7) begin
                init_go   <= btgt_onehot;
                init_wr   <= bwr;
                init_addr <= baddr + {{(ADDR_W-2){1'b0}}, bk};
                init_data <= bdata[bk*DATA_W +: DATA_W];
                brd1      <= ~bwr;
                bk1       <= bk;
            end
        end
        if (brd2) bf_rdata[bk2*DATA_W +: DATA_W] <= ram_a_q[btgt*DATA_W +: DATA_W];
    end

    wire _unused = &{1'b0, pay_q[63:DATA_W]};

endmodule

`default_nettype wire
