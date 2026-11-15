//-----------------------------------------------------------------------------
// usb_tx_serializer8.v - TX "Serializer 8:1 + EOP Gen" on the 60 MHz core
//                        clock (Plan_60MHz.md 4.2, P6)
//
//   TX Holding -> SYNC/PID mux -> Bit Stuffer -> NRZI Encoder -> [THIS BLOCK]
//        -> txd_v / tx_en_v / tx_se0_v (8 bits per tick) -> usb_afe_tx_if8
//        -> usb_tx_piso (480 MHz, the only bit-rate part) -> AFE pins
//
// Replaces the bit-serial ref_tx_serializer (kept as the reference model of
// tb_usb_tx_vec).  Instead of one line bit per clk_bit cycle it produces, on
// every clk60 edge, the 8 line bits of the next tick as vectors: bit 0 is sent
// first.  Each vector covers the same 8 bit times as the old serializer
// running with ce60 on the clk60 edges: vector register value after tick T's
// edge = the old txd / tx_en / tx_se0 after the clk_bit edges 8T + 2 .. 8T + 9
// (8T = the clk_bit edge with ce60).  Word handshake (in_ready, accepts),
// busy, tx_speed, and the tick of tx_done / tx_underrun are those of the old
// serializer, tick for tick; tb_usb_tx_vec checks both against each other.
//
// Clock: clk60 only (all inputs / outputs clk60 domain).  Reset rst_n,
//   asynchronous.
//
// Input words: as ref_tx_serializer.  in_data is NRZI-encoded (J = 1), LSB
//   first; words have 8 valid bits except the last one (in_last = 1,
//   in_nbits = 0..8, > 8 clamped to 8; 0 = EOP only).  A word is taken on a
//   clk60 edge with in_valid && in_ready.
//
// HS (8 bits per tick; a packet starts on a vector boundary, every word fills
//   one vector):
//   * a word accepted on a tick's edge is that tick's vector;
//   * the last word with n bits: bits 0 .. n-1 data, then the 8 EOP bits
//     (inverted level of the last data bit, NRZI 01111111) from bit n on,
//     spliced across two vectors (er = n EOP bits left for the next one); the
//     bit after them releases the line (tx_en = 0, txd = 1) and tx_done pulses
//     with that vector;
//   * no word in time (running, not the last word): tx_underrun with this
//     vector, the vector is an EOP (8 bits), release in the next one;
//   * eop_dis = 1 (OpMode 10): no EOP; the line is released on the bit after
//     the last data bit (an underrun releases at bit 0 of the vector).
//   in_ready falls from the last word until the release; if the release is at
//   bit 6 or 7 of a vector, one more tick (the old serializer's ready came
//   2 cycles after the release, see ST_REL).
// FS / LS (one bit per FS_TK = 5 / LS_TK = 40 ticks, the old FS_DIV = 40 /
//   LS_DIV = 320 clk_bit cycles): all 8 bits of a vector are equal.  The
//   one-word holding register and the bit timer of the old serializer, in
//   ticks; the first bit is sent in the tick that accepts the first word.
//   EOP: SE0, SE0, J (one bit each), then release, tx_done.
// Speed (XcvrSelect): 00 HS, 01 FS, 10 LS, 11 FS rate; speed / eop_dis are
//   sampled when the first word is accepted and reported on tx_speed.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_tx_serializer8 #(
    parameter FS_TK = 5,      // ticks per FS bit (40 clk_bit)
    parameter LS_TK = 40,     // ticks per LS bit (320 clk_bit)
    parameter TK_W  = 6       // bit-timer width (>= clog2(LS_TK))
) (
    input  wire        clk,          // clk60
    input  wire        rst_n,

    input  wire [1:0]  speed,        // 00 HS, 01 FS, 10 LS
    input  wire        eop_dis,      // 1 = end the packet without EOP

    input  wire        in_valid,
    output wire        in_ready,
    input  wire [7:0]  in_data,      // NRZI-encoded bits, LSB first
    input  wire [3:0]  in_nbits,     // valid bits of the LAST word (0..8)
    input  wire        in_last,

    output reg  [7:0]  txd_v,        // line levels of the tick, bit 0 first (J = 1)
    output reg  [7:0]  tx_en_v,      // driver enable per bit
    output reg  [7:0]  tx_se0_v,     // SE0 per bit (FS/LS EOP)
    output reg  [1:0]  tx_speed,     // speed of the current packet
    output wire        busy,
    output reg         tx_done,      // one tick: the release is in this tick's vector
    output reg         tx_underrun   // one tick: packet aborted (this vector is its EOP)
);

    localparam [1:0] SPD_HS = 2'b00;
    localparam [1:0] SPD_LS = 2'b10;

    localparam [1:0] ST_IDLE = 2'd0;
    localparam [1:0] ST_RUN  = 2'd1;   // sending data
    localparam [1:0] ST_EOP  = 2'd2;   // HS: EOP bits / release pending; FS/LS: EOP
    localparam [1:0] ST_REL  = 2'd3;   // HS: released at bit 6 / 7, ready next tick

    reg  [1:0]       st;
    reg  [1:0]       spd_q;
    reg              eop_q;
    reg              closing;          // last word accepted (FS/LS: still in hold / cur)
    reg              ll;               // level of the last data bit
    reg  [3:0]       er;               // HS: EOP bits left for the next vector (0..8)
    // FS / LS
    reg              hv, hl;           // holding register
    reg  [7:0]       hd;
    reg  [3:0]       hn;
    reg  [7:0]       cd;               // word being sent
    reg  [3:0]       cc;
    reg              cl;
    reg  [TK_W-1:0]  tk;               // ticks into the current bit
    reg  [1:0]       ec;               // EOP step
    reg              lv_d, lv_e, lv_s; // current line value

    wire accept = in_valid & in_ready;
    wire [3:0] nb = in_last ? ((in_nbits > 4'd8) ? 4'd8 : in_nbits) : 4'd8;

    assign in_ready = (st == ST_IDLE) | ((st == ST_RUN) & ~hv & ~closing);
    assign busy     = hv | (st != ST_IDLE);

    function [TK_W-1:0] tk_m1;
        input [1:0] spd;
        tk_m1 = (spd == SPD_LS) ? LS_TK - 1 : FS_TK - 1;
    endfunction

    // low n bits set (n = 0..8)
    function [7:0] lmask;
        input [3:0] n;
        lmask = (n >= 4'd8) ? 8'hFF : ((8'h01 << n) - 8'h01);
    endfunction

    // ---------------- next state ----------------
    reg  [1:0]       n_st, n_spd;
    reg              n_eop, n_closing, n_ll, n_hv, n_hl, n_cl, n_lvd, n_lve, n_lvs;
    reg  [3:0]       n_er, n_hn, n_cc;
    reg  [7:0]       n_hd, n_cd;
    reg  [TK_W-1:0]  n_tk;
    reg  [1:0]       n_ec, n_tspd;
    reg  [7:0]       v_d, v_e, v_s;
    reg              n_done, n_under;
    // temporaries
    reg  [7:0]       m;
    reg              lvl, ev, fs_go, h_ok;
    reg  [7:0]       e_d;
    reg  [3:0]       e_n;
    reg              e_l;

    always @* begin
        n_st = st; n_spd = spd_q; n_eop = eop_q; n_closing = closing; n_ll = ll;
        n_er = er; n_hv = hv; n_hd = hd; n_hn = hn; n_hl = hl;
        n_cd = cd; n_cc = cc; n_cl = cl; n_tk = tk; n_ec = ec;
        n_lvd = lv_d; n_lve = lv_e; n_lvs = lv_s; n_tspd = tx_speed;
        n_done = 1'b0; n_under = 1'b0;
        v_d = 8'hFF; v_e = 8'h00; v_s = 8'h00;            // idle
        m = 8'h00; lvl = 1'b1; ev = 1'b0; fs_go = 1'b0; h_ok = 1'b0;
        e_d = 8'h00; e_n = 4'd0; e_l = 1'b0;

        if (accept && in_last) n_closing = 1'b1;

        // ================= HS =================
        if ((st == ST_IDLE && accept && speed == SPD_HS) ||
            (st == ST_RUN && spd_q == SPD_HS && accept)) begin
            // a data word: this tick's vector
            if (st == ST_IDLE) begin
                n_spd = speed; n_eop = eop_dis; n_tspd = speed;
            end
            if (!in_last) begin
                v_d = in_data; v_e = 8'hFF;
                n_ll = in_data[7];
                n_st = ST_RUN;
            end else begin
                m   = lmask(nb);
                lvl = (nb == 4'd0) ? ((st == ST_IDLE) ? 1'b1 : ll) : in_data[nb - 4'd1];
                n_ll = lvl;
                if (!((st == ST_IDLE) ? eop_dis : eop_q)) begin
                    v_d  = (in_data & m) | ({8{~lvl}} & ~m);
                    v_e  = 8'hFF;
                    n_er = nb;                          // EOP bits left for the next vector
                    n_st = ST_EOP;
                end else begin
                    v_d = (in_data & m) | ~m;
                    v_e = m;
                    if (nb == 4'd8) begin              // release at bit 0 of the next vector
                        n_er = 4'd0;
                        n_st = ST_EOP;
                    end else begin                     // release at bit nb of this one
                        n_done    = 1'b1;
                        n_closing = 1'b0;
                        n_st      = (nb >= 4'd6) ? ST_REL : ST_IDLE;
                    end
                end
            end
        end else if (st == ST_RUN && spd_q == SPD_HS) begin
            // underrun: no word for this tick
            n_under = 1'b1;
            if (eop_q) begin                           // release at bit 0
                n_done = 1'b1;
                n_st   = ST_IDLE;
            end else begin
                v_d  = {8{~ll}}; v_e = 8'hFF;
                n_er = 4'd0;
                n_st = ST_EOP;
            end
        end else if (st == ST_EOP && spd_q == SPD_HS) begin
            m   = lmask(er);
            v_d = ({8{~ll}} & m) | ~m;
            v_e = m;
            if (er == 4'd8)
                n_er = 4'd0;
            else begin                                 // release at bit er
                n_done    = 1'b1;
                n_closing = 1'b0;
                n_st      = (er >= 4'd6) ? ST_REL : ST_IDLE;
            end
        end else if (st == ST_REL) begin
            n_st = ST_IDLE;

        // ================= FS / LS =================
        end else begin
            // hold register as seen by this tick's bit event (a word accepted
            // on this edge is already there, as in the old serializer)
            if (st != ST_IDLE && accept) begin
                n_hv = 1'b1; n_hd = in_data; n_hn = nb; n_hl = in_last;
            end
            if (st == ST_IDLE) begin
                if (accept) begin                      // speed != HS here
                    n_spd = speed; n_eop = eop_dis; n_tspd = speed;
                    n_cd  = in_data; n_cc = nb; n_cl = in_last;
                    n_ec  = 2'd0;
                    n_st  = (nb == 4'd0) ? ST_EOP : ST_RUN;
                    fs_go = 1'b1;
                end
            end
            ev = fs_go | ((st != ST_IDLE) && (tk == tk_m1(spd_q)));
            if (!ev) begin
                if (st != ST_IDLE) n_tk = tk + 1'b1;
            end else begin
                n_tk = {TK_W{1'b0}};
                if (n_st == ST_RUN) begin
                    // data bit (cur state after a possible load: n_cd / n_cc / n_cl)
                    n_lvd = n_cd[0]; n_lve = 1'b1; n_lvs = 1'b0;
                    n_ll  = n_cd[0];
                    e_d = n_cd; e_n = n_cc; e_l = n_cl;
                    n_cd = {1'b0, e_d[7:1]};
                    n_cc = e_n - 4'd1;
                    if (e_n == 4'd1) begin
                        if (e_l) begin
                            n_st = ST_EOP; n_ec = 2'd0;
                        end else if (n_hv) begin
                            n_hv = 1'b0;
                            if (n_hn == 4'd0) begin
                                n_st = ST_EOP; n_ec = 2'd0;
                            end else begin
                                n_cd = n_hd; n_cc = n_hn; n_cl = n_hl;
                            end
                        end else begin
                            n_under = 1'b1;
                            n_st = ST_EOP; n_ec = 2'd0;
                        end
                    end
                end else begin
                    // EOP step (n_st == ST_EOP)
                    e_n  = {2'b00, n_ec};                 // step before the increment
                    n_ec = n_ec + 2'd1;
                    if (n_eop || e_n == 4'd3) begin
                        n_lvd = 1'b1; n_lve = 1'b0; n_lvs = 1'b0;
                        n_st = ST_IDLE; n_closing = 1'b0; n_done = 1'b1;
                    end else if (e_n == 4'd2) begin
                        n_lvd = 1'b1; n_lve = 1'b1; n_lvs = 1'b0;   // J
                    end else begin
                        n_lvd = 1'b0; n_lve = 1'b1; n_lvs = 1'b1;   // SE0, SE0
                    end
                end
            end
            if (st != ST_IDLE || fs_go) begin
                v_d = {8{n_lvd}}; v_e = {8{n_lve}}; v_s = {8{n_lvs}};
            end
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= ST_IDLE; spd_q <= SPD_HS; eop_q <= 1'b0; closing <= 1'b0; ll <= 1'b1;
            er <= 4'd0; hv <= 1'b0; hd <= 8'd0; hn <= 4'd0; hl <= 1'b0;
            cd <= 8'd0; cc <= 4'd0; cl <= 1'b0; tk <= {TK_W{1'b0}}; ec <= 2'd0;
            lv_d <= 1'b1; lv_e <= 1'b0; lv_s <= 1'b0;
            txd_v <= 8'hFF; tx_en_v <= 8'h00; tx_se0_v <= 8'h00;
            tx_speed <= SPD_HS; tx_done <= 1'b0; tx_underrun <= 1'b0;
        end else begin
            st <= n_st; spd_q <= n_spd; eop_q <= n_eop; closing <= n_closing; ll <= n_ll;
            er <= n_er; hv <= n_hv; hd <= n_hd; hn <= n_hn; hl <= n_hl;
            cd <= n_cd; cc <= n_cc; cl <= n_cl; tk <= n_tk; ec <= n_ec;
            lv_d <= n_lvd; lv_e <= n_lve; lv_s <= n_lvs;
            txd_v <= v_d; tx_en_v <= v_e; tx_se0_v <= v_s;
            tx_speed <= n_tspd; tx_done <= n_done; tx_underrun <= n_under;
        end
    end

endmodule
