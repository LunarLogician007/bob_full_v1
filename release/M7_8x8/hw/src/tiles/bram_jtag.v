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
    output reg  [DATA_W-1:0]        init_data
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

    initial begin
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
    end

    wire _unused = &{1'b0, pay_q[63:DATA_W]};

endmodule

`default_nettype wire
