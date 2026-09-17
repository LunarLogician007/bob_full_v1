// -----------------------------------------------------------------------------
// cfg_frames.v - UG470-style frame configuration controller (M13)
//
// The packet path of docs/bitstream-format.md section 10, on CFG_IN / CFG_OUT:
//
//   CFG_IN   words MSB first; hunt bit by bit for the sync word 0xAA995566, then
//            32-bit words: type-1 / type-2 packet headers and WRITE data words
//   parser   HDR -> (T2) -> DATA -> HDR; ERR on any error (left only by JPROGRAM)
//   register CRC  compare with the running CRC-32C over {reg[4:0], data}
//            FAR  frame address (7-series layout), auto-increment
//                 block type 0: configuration memory; block type 1 (M15): BRAM
//                 contents - column = BRAM index, frame n = row * 128 + minor
//                 (n < 256) holds addresses 4n..4n+3, word = {14'b0, data[17:0]}
//            FDRI frame data: 4 words fill a frame; the 4th loads it into cfg_store's
//                 frame buffer (frame_load) and the memory takes it on the falling edge
//            CMD  NULL WCFG LFRM RCFG START RCRC AGHIGH DESYNC
//            IDCODE must match before FDRI is accepted
//   CFG_OUT  READ packets queue words (FDRO frames from FAR, STAT, FAR, IDCODE,
//            CRC); each CFG_OUT scan shifts them out MSB first; with nothing
//            queued it returns STAT
//
// Frame writes need WCFG, a matched IDCODE, no error, a valid FAR and GWE = 0 -
// or (M14, partial reconfiguration) the fabric frozen: AGHIGH (UG470 CMD 8, which
// asserts GHIGH_B) raises `freeze`; clock_ctrl.v then holds every user-clock enable
// low, so no fabric register, BRAM or DSP register can change, and acknowledges
// (`frozen_ack`, synchronised here). While acknowledged, frames may be written with
// the design running. LFRM (UG470 CMD 3, DGHIGH/LFRM) releases the freeze only after
// a CRC match that followed the last FDRI word; otherwise WR_ERROR and the fabric
// stays frozen (recover with JPROGRAM and a full load). STAT bit 7 is GHIGH_B: 0
// while the freeze is acknowledged.
// START is accepted only after a CRC match that followed the last FDRI word;
// `start_ok` then lets cfg_ctrl's JSTART sequence run.
//
// Everything is in the TCK domain on the rising edge; the frame itself lands in
// cfg_store on the following falling edge. JPROGRAM resets the controller.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module cfg_frames #(
    parameter [31:0]  IDCODE_VALUE = 32'h0,
    parameter integer FW           = 4,            // words per frame
    parameter integer NFRAMES      = 4,
    parameter integer NCOLS        = 2,            // FAR columns
    parameter [16*NCOLS-1:0] FAR_TABLE = 0,        // column c: [16c+7:16c] base, [16c+15:16c+8] count
    parameter integer FIDX_W       = 8,
    parameter integer NBRAM        = 2             // M15: FAR block type 1 columns
)(
    input  wire              tck,
    input  wire              tdi,
    input  wire              dr_capture,
    input  wire              dr_shift,
    input  wire              sel_in,        // CFG_IN
    input  wire              sel_out,       // CFG_OUT
    input  wire              jprogram,

    input  wire              gsr,
    input  wire              gts,
    input  wire              gwe,
    input  wire              done,
    input  wire              frozen_ack,    // clock_ctrl: gce held (sysclk domain; synchronised here)
    input  wire [32*FW-1:0]  rd_frame,      // cfg_store's read mux at rd_idx, for FDRO
    output wire [FIDX_W-1:0] rd_idx,

    output wire              so,
    // M15: BRAM content frames, to bram_jtag.v's sysclk side (toggle handshake)
    output reg               bf_wr_t,        // toggles: write bf_data (4 words) at bf_addr of BRAM bf_tgt
    output reg               bf_rd_t,        // toggles: read 4 words at bf_addr of BRAM bf_tgt into bf_rdata
    output reg  [3:0]        bf_tgt,
    output reg  [9:0]        bf_addr,
    output reg  [71:0]       bf_data,
    input  wire [71:0]       bf_rdata,
    output wire              frame_load,     // this rising edge: frame_load_data into the frame buffer
    output wire [32*FW-1:0]  frame_load_data,
    output reg               frame_we,       // next falling edge: frame buffer -> memory
    output reg  [FIDX_W-1:0] frame_idx,
    output reg               start_ok,
    output reg               freeze,         // to clock_ctrl: hold the user clock (M14)
    output wire              any_error,
    output wire              crc_error,
    output wire [31:0]       stat
);

    localparam integer FB = 32 * FW;

    localparam [31:0] SYNC = 32'hAA995566;
    localparam [4:0]  R_CRC = 5'd0, R_FAR = 5'd1, R_FDRI = 5'd2, R_FDRO = 5'd3,
                      R_CMD = 5'd4, R_STAT = 5'd7, R_IDCODE = 5'd12;
    localparam [4:0]  C_NULL = 5'd0, C_WCFG = 5'd1, C_LFRM = 5'd3, C_RCFG = 5'd4,
                      C_START = 5'd5, C_RCRC = 5'd7, C_AGHIGH = 5'd8, C_DESYNC = 5'd13;
    localparam [1:0]  OP_NOP = 2'd0, OP_READ = 2'd1, OP_WRITE = 2'd2;
    localparam [1:0]  ST_HDR = 2'd0, ST_T2 = 2'd1, ST_DATA = 2'd2, ST_ERR = 2'd3;
    localparam [7:0]  VERSION = 8'h15;

    // ---------------------------------------------------------------------
    // state
    // ---------------------------------------------------------------------
    reg [31:0] sh      = 32'h0;
    reg        synced  = 1'b0;
    reg [4:0]  bitcnt  = 5'd0;
    reg [1:0]  st      = ST_HDR;
    reg [1:0]  op      = 2'd0;
    reg [4:0]  rsel    = 5'd0;
    reg [26:0] cnt     = 27'd0;

    reg [31:0] far     = 32'h0;
    reg [31:0] crc     = 32'h0;
    reg        wcfg = 1'b0, rcfg = 1'b0, lfrm = 1'b0, id_ok = 1'b0, crc_ok = 1'b0, data_seen = 1'b0;
    reg        crc_err = 1'b0, id_err = 1'b0, pkt_err = 1'b0, wr_err = 1'b0;

    reg [FB-33:0]        fbuf  = {(FB-32){1'b0}};      // words 0..FW-2 of the frame being filled
    reg [$clog2(FW)-1:0] widx  = 0;

    reg [4:0]  rd_reg  = 5'd0;
    reg [26:0] rd_cnt  = 27'd0;
    reg [$clog2(FW)-1:0] rwidx = 0;
    reg [31:0] out     = 32'h0;
    reg [4:0]  ocnt    = 5'd0;

    (* ASYNC_REG = "TRUE" *) reg [1:0] ack_m = 2'b00;
    wire frozen = freeze & ack_m[1];

    reg [31:0] bf_far = 32'hFFFFFFFF;            // FAR whose BRAM frame bf_rdata holds (prefetch)

    initial begin
        bf_wr_t    = 1'b0;
        bf_rd_t    = 1'b0;
        bf_tgt     = 4'd0;
        bf_addr    = 10'd0;
        bf_data    = 72'd0;
        freeze     = 1'b0;
        frame_we   = 1'b0;
        frame_idx  = {FIDX_W{1'b0}};
        start_ok   = 1'b0;
    end

    assign any_error = crc_err | id_err | pkt_err | wr_err;
    assign crc_error = crc_err;

    // ---------------------------------------------------------------------
    // FAR decode: column / minor -> frame index, validity, next address
    // ---------------------------------------------------------------------
    function [7:0] col_base(input integer ci);
        col_base = FAR_TABLE[16*ci +: 8];
    endfunction
    function [7:0] col_count(input integer ci);
        col_count = FAR_TABLE[16*ci + 8 +: 8];
    endfunction

    wire [6:0]  far_minor = far[6:0];
    wire [31:0] far_col   = {22'd0, far[16:7]};
    wire       far_valid = (far[31:17] == 15'd0) && (far_col < NCOLS) &&
                           ({1'b0, far_minor} < col_count(far_col));
    wire [FIDX_W-1:0] far_fidx = col_base(far_col) + far_minor;

    // M15: block type 1 (BRAM contents)
    wire [5:0]  far_row    = far[22:17];
    wire [7:0]  bfar_n_inc;
    wire        bfar_valid = (far[31:26] == 6'd0) && (far[25:23] == 3'd1) && (far_row[5:1] == 5'd0) &&
                             (far_col < NBRAM);
    wire [7:0]  bfar_n     = {far_row[0], far_minor};             // frame 0..255
    wire [9:0]  bfar_addr  = {bfar_n, 2'b00};
    assign      bfar_n_inc = bfar_n + 8'd1;

    reg [31:0] far_next;
    integer    c;
    always @(*) begin
        far_next = {15'd0, 10'd1023, 7'd0};                    // past the end: invalid
        if (bfar_valid) begin
            if (bfar_n != 8'd255)
                far_next = {6'd0, 3'd1, 5'd0, bfar_n_inc[7], far[16:7], bfar_n_inc[6:0]};
            else if (far_col + 32'd1 < NBRAM)
                far_next = {6'd0, 3'd1, 6'd0, far[16:7] + 10'd1, 7'd0};
        end else if (far_valid) begin
            if ({1'b0, far_minor} + 8'd1 < col_count(far_col))
                far_next = {far[31:7], far_minor + 7'd1};
            else begin
                for (c = NCOLS - 1; c >= 0; c = c - 1)          // constant bounds; the lowest match wins
                    if (c > far_col && col_count(c) != 8'd0)
                        far_next = {15'd0, c[9:0], 7'd0};
            end
        end
    end

    // ---------------------------------------------------------------------
    // CRC-32C over {reg, data}, 37 bits LSB first, reflected polynomial
    // ---------------------------------------------------------------------
    function [31:0] crc37(input [31:0] c_in, input [4:0] r, input [31:0] d);
        integer i;
        reg [36:0] v;
        reg [31:0] x;
        begin
            v = {r, d};
            x = c_in;
            for (i = 0; i < 37; i = i + 1)
                x = ((x[0] ^ v[i]) ? ((x >> 1) ^ 32'h82F63B78) : (x >> 1));
            crc37 = x;
        end
    endfunction

    // ---------------------------------------------------------------------
    // STAT
    // ---------------------------------------------------------------------
    assign stat = {rcfg, start_ok, gsr, crc_ok, wcfg, synced, wr_err, pkt_err,
                   VERSION,
                   id_err, done, 1'b0, ~any_error, 1'b1, 3'b000, ~frozen, gwe, ~gts, 4'b0000, crc_err};

    // ---------------------------------------------------------------------
    // the word being completed on this edge
    // ---------------------------------------------------------------------
    wire [31:0] nxt     = {sh[30:0], tdi};
    wire        in_bit  = sel_in & dr_shift;
    wire        wv      = in_bit & synced & (bitcnt == 5'd31);
    wire [31:0] w       = nxt;

    wire        reg_ok_w = (w[17:13] == R_CRC) || (w[17:13] == R_FAR) || (w[17:13] == R_FDRI) ||
                           (w[17:13] == R_CMD) || (w[17:13] == R_IDCODE);
    wire        reg_ok_r = (w[17:13] == R_FAR) || (w[17:13] == R_FDRO) || (w[17:13] == R_STAT) ||
                           (w[17:13] == R_IDCODE) || (w[17:13] == R_CRC);
    wire        hdr1_ok  = (w[26:18] == 9'd0) && (w[12:11] == 2'd0);

    // the 4th word of a frame, accepted: written into cfg_store's frame buffer on this
    // edge (the same condition as the FDRI branch below)
    wire   fdri_ok         = wcfg && id_ok && (!gwe || frozen) && far_valid && !any_error;
    assign frame_load      = wv && (st == ST_DATA) && (rsel == R_FDRI) && fdri_ok && ({30'd0, widx} == FW - 1);
    assign frame_load_data = {w, fbuf};

    // FDRO source: cfg_store's frame read mux at the FAR frame, then one of FW words
    // (M12b: shared with CHAIN_OUT; M13 had its own FW*NFRAMES-way word mux)
    assign rd_idx = far_fidx;
    wire [31:0] rd_frame_word [0:FW-1];
    genvar gw;
    generate
        for (gw = 0; gw < FW; gw = gw + 1) begin : g_word
            assign rd_frame_word[gw] = rd_frame[gw*32 +: 32];
        end
    endgenerate
    wire fdro_in_range = ({{(32-FIDX_W){1'b0}}, far_fidx} < NFRAMES);

    // word CFG_OUT hands out next (for the current read request)
    reg [31:0] rword;
    always @(*) begin
        rword = stat;
        if (rd_cnt != 27'd0) begin
            case (rd_reg)
                R_FDRO:   rword = bfar_valid ? ((rcfg && !gwe) ? {14'd0, bf_rdata[{30'd0, rwidx}*18 +: 18]} : 32'h0) :
                                  (rcfg && far_valid && fdro_in_range) ? rd_frame_word[rwidx] : 32'h0;
                R_FAR:    rword = far;
                R_IDCODE: rword = IDCODE_VALUE;
                R_CRC:    rword = crc;
                default:  rword = stat;
            endcase
        end
    end

    // ---------------------------------------------------------------------
    // one clocked process: CFG_IN parser + register file, CFG_OUT readback
    // (they share FAR, so they share the always block)
    // ---------------------------------------------------------------------
    always @(posedge tck) begin
        frame_we <= 1'b0;
        ack_m    <= {ack_m[0], frozen_ack};

        if (jprogram) begin
            freeze <= 1'b0;
            sh <= 32'h0; synced <= 1'b0; bitcnt <= 5'd0; st <= ST_HDR; op <= 2'd0; rsel <= 5'd0; cnt <= 27'd0;
            far <= 32'h0; crc <= 32'h0; bf_far <= 32'hFFFFFFFF;
            wcfg <= 1'b0; rcfg <= 1'b0; lfrm <= 1'b0; id_ok <= 1'b0; crc_ok <= 1'b0; data_seen <= 1'b0;
            crc_err <= 1'b0; id_err <= 1'b0; pkt_err <= 1'b0; wr_err <= 1'b0;
            start_ok <= 1'b0; widx <= 0; fbuf <= {(FB-32){1'b0}};
            rd_reg <= 5'd0; rd_cnt <= 27'd0; rwidx <= 0; out <= 32'h0; ocnt <= 5'd0;
        end else begin
            // ------------------------------------------------- CFG_IN
            if (in_bit) begin
                sh <= nxt;
                if (!synced) begin
                    if (nxt == SYNC) begin
                        synced <= 1'b1;
                        bitcnt <= 5'd0;
                    end
                end else
                    bitcnt <= bitcnt + 5'd1;
            end

            if (wv) begin
                case (st)
                    ST_HDR: begin
                        if (w[31:29] == 3'b001) begin
                            op   <= w[28:27];
                            rsel <= w[17:13];
                            if (w[28:27] == OP_NOP) begin
                                // NOP
                            end else if (!hdr1_ok || w[28:27] == 2'd3 ||
                                         (w[28:27] == OP_WRITE && !reg_ok_w) ||
                                         (w[28:27] == OP_READ  && !reg_ok_r)) begin
                                pkt_err <= 1'b1; st <= ST_ERR;
                            end else if (w[10:0] == 11'd0) begin
                                st <= ST_T2;
                            end else if (w[28:27] == OP_READ) begin
                                rd_reg <= w[17:13]; rd_cnt <= {16'd0, w[10:0]}; rwidx <= 0;
                                if (w[17:13] == R_FDRO && !rcfg) wr_err <= 1'b1;
                            end else begin
                                cnt <= {16'd0, w[10:0]}; st <= ST_DATA;
                            end
                        end else begin
                            pkt_err <= 1'b1; st <= ST_ERR;
                        end
                    end

                    ST_T2: begin
                        if (w[31:29] != 3'b010 || w[28:27] != op) begin
                            pkt_err <= 1'b1; st <= ST_ERR;
                        end else if (w[26:0] == 27'd0) begin
                            st <= ST_HDR;
                        end else if (op == OP_READ) begin
                            rd_reg <= rsel; rd_cnt <= w[26:0]; rwidx <= 0; st <= ST_HDR;
                            if (rsel == R_FDRO && !rcfg) wr_err <= 1'b1;
                        end else begin
                            cnt <= w[26:0]; st <= ST_DATA;
                        end
                    end

                    ST_DATA: begin
                        if (cnt == 27'd1) st <= ST_HDR;
                        cnt <= cnt - 27'd1;
                        if (rsel != R_CRC)
                            crc <= crc37(crc, rsel, w);
                        case (rsel)
                            R_CRC: begin
                                if (w == crc) crc_ok <= 1'b1;
                                else begin crc_err <= 1'b1; st <= ST_ERR; end
                            end
                            R_FAR: begin far <= w; bf_far <= 32'hFFFFFFFF; end
                            R_IDCODE: begin
                                if (w == IDCODE_VALUE) id_ok <= 1'b1;
                                else begin id_err <= 1'b1; st <= ST_ERR; end
                            end
                            R_CMD: begin
                                if (w[31:5] != 27'd0) begin
                                    pkt_err <= 1'b1; st <= ST_ERR;
                                end else case (w[4:0])
                                    C_NULL:   ;
                                    C_WCFG:   wcfg <= 1'b1;
                                    C_LFRM: begin
                                        lfrm <= 1'b1;
                                        if (freeze) begin
                                            if (crc_ok && !any_error) freeze <= 1'b0;
                                            else begin wr_err <= 1'b1; st <= ST_ERR; end
                                        end
                                    end
                                    C_AGHIGH: begin
                                        if (id_ok) freeze <= 1'b1;
                                        else begin wr_err <= 1'b1; st <= ST_ERR; end
                                    end
                                    C_RCFG:   rcfg <= 1'b1;
                                    C_START:  if (crc_ok && id_ok && data_seen && !any_error) start_ok <= 1'b1;
                                    C_RCRC:   crc  <= 32'h0;
                                    C_DESYNC: begin synced <= 1'b0; st <= ST_HDR; end
                                    default:  begin pkt_err <= 1'b1; st <= ST_ERR; end
                                endcase
                            end
                            R_FDRI: begin
                                crc_ok    <= 1'b0;
                                data_seen <= 1'b1;
                                if (bfar_valid) begin
                                    // M15: BRAM contents, before startup only (as USER4)
                                    if (wcfg && id_ok && !gwe && !any_error) begin
                                        if ({30'd0, widx} == FW - 1) begin
                                            bf_data <= {w[17:0], fbuf[81:64], fbuf[49:32], fbuf[17:0]};
                                            bf_tgt  <= far[10:7];
                                            bf_addr <= bfar_addr;
                                            bf_wr_t <= ~bf_wr_t;
                                            bf_far  <= 32'hFFFFFFFF;
                                            far     <= far_next;
                                            widx    <= 0;
                                        end else begin
                                            fbuf[{30'd0, widx}*32 +: 32] <= w;
                                            widx <= widx + 1;
                                        end
                                    end else begin
                                        wr_err <= 1'b1; st <= ST_ERR;
                                    end
                                end else if (fdri_ok) begin
                                    if ({30'd0, widx} == FW - 1) begin
                                        frame_we   <= 1'b1;
                                        frame_idx  <= far_fidx;
                                        far        <= far_next;
                                        widx       <= 0;
                                    end else begin
                                        fbuf[{30'd0, widx}*32 +: 32] <= w;
                                        widx <= widx + 1;
                                    end
                                end else begin
                                    wr_err <= 1'b1; st <= ST_ERR;
                                end
                            end
                            default: begin pkt_err <= 1'b1; st <= ST_ERR; end
                        endcase
                    end

                    default: ;                                     // ST_ERR: ignore everything
                endcase
            end

            // ------------------------------------------------- CFG_OUT
            if (sel_out && (dr_capture || (dr_shift && ocnt == 5'd31))) begin
                out  <= rword;
                ocnt <= 5'd0;
                if (rd_cnt != 27'd0) begin
                    rd_cnt <= rd_cnt - 27'd1;
                    if (rd_reg == R_FDRO && rcfg && (far_valid || bfar_valid)) begin
                        if ({30'd0, rwidx} == FW - 1) begin
                            rwidx <= 0;
                            far   <= far_next;
                        end else
                            rwidx <= rwidx + 1;
                    end
                end
            end else if (sel_out && dr_shift) begin
                out  <= {out[30:0], 1'b0};
                ocnt <= ocnt + 5'd1;
            end

            // M15: prefetch the BRAM frame FDRO will hand out next (the sysclk side needs a
            // few cycles; the next word load is at least 32 TCK edges away)
            if (rd_reg == R_FDRO && rd_cnt != 27'd0 && rcfg && !gwe && bfar_valid && far != bf_far &&
                !(sel_out && (dr_capture || (dr_shift && ocnt == 5'd31)))) begin
                bf_far  <= far;
                bf_tgt  <= far[10:7];
                bf_addr <= bfar_addr;
                bf_rd_t <= ~bf_rd_t;
            end
        end
    end

    assign so = out[31];

    wire _unused = &{1'b0, lfrm, sh[31]};

endmodule

`default_nettype wire
