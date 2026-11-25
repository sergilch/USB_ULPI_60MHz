//-----------------------------------------------------------------------------
// cdr_rxchk.v - checker of the recovered data HS_RXD, CLK_RX / 8 word clock
//
// Input: w = 8 HS_RXD bits per clk_rxw tick (ISERDESE2 1:8 SDR on CLK_RX,
//   bit 0 first in time; the word boundary is arbitrary, nothing here needs it).
//
// Packets (TXMODE 1): the repo's usb_rx_decoder8 (HS, ZMIN_HS = 4, 8 bits per
//   tick; a packet ends at the EOP's bit-stuff violation) turns the bits into
//   START / BYTE / END events.  The board has no squelch, so s_act emulates
//   it: a bit is inactive after SQ_BITS (12) bits without a transition (a
//   packet has at most 6, its EOP 7); HS SYNC detection re-arms only while the
//   receiver is inactive.  A packet counts as good (rxok) when
//   its bytes are PID C3h plus txlen PRBS7 bytes (seed 5Ah, as cdr_txgen) and
//   its END has no error.
//   SYNC bits lost: NRZI-decoded zero runs are counted here in parallel; the
//   run in front of the SYNC's final 1 (the first run >= 4 of its tick, taken
//   SYNC_LAT ticks later with the decoder's START; the PID C3h behind it
//   has a 4-zero run of its own, so neither a later candidate nor a later
//   tick may be used) gives
//   lost = 31 - zeros (the 32-bit HS SYNC has 31 zeros after idle J).  It is
//   what the CDR got wrong while locking (plus nothing else: the generator
//   sends the full SYNC).  losts = sum, lostmax / lostmin over the packets.
// PRBS7 (TXMODE 2): self-synchronising checker, every received bit is
//   compared with x[n-7] ^ x[n-6] of the received bits; one line error gives
//   three counted errors.  pbits counts words, perr errors; psync = the last
//   word had no error.
//
// Counters clear on clr (one clk_rxw pulse).  snap_req (toggle from the system
//   clock domain) copies all counters into the shadow outputs and returns
//   snap_ack = snap_req; the shadow stays stable until the next toggle.
// Clocking: clk_rxw (BUFR of CLK_RX / 8), rst_n asynchronous assert,
//   synchronous release in clk_rxw (cdr_fpga_top).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module cdr_rxchk #(
    parameter SYNC_LAT = 3,          // ticks from the SYNC bits to their START event
    parameter SQ_BITS  = 12          // bits without a transition -> "squelch" (s_act = 0)
) (
    input  wire        clk,          // clk_rxw
    input  wire        rst_n,
    input  wire [7:0]  w,
    input  wire [7:0]  txlen,        // static during a test (quasi-static, system domain)
    input  wire        clr,
    input  wire        snap_req,     // already synchronised to clk
    output reg         snap_ack,
    output reg  [23:0] s_rxpkt,
    output reg  [23:0] s_rxok,
    output reg  [23:0] s_losts,
    output reg  [7:0]  s_lostmax,
    output reg  [7:0]  s_lostmin,
    output reg  [31:0] s_pbits,
    output reg  [31:0] s_perr,
    output reg         psync
);
    function [14:0] prbs8(input [6:0] s);     // as cdr_txgen
        integer i;
        reg [6:0] t;
        reg [7:0] b;
        begin
            t = s;
            for (i = 0; i < 8; i = i + 1) begin
                b[i] = t[0] ^ t[1];
                t    = {b[i], t[6:1]};
            end
            prbs8 = {t, b};
        end
    endfunction

    // ---------------- decoder ----------------
    wire       e0, e1, e2, e3;
    wire [9:0] d0, d1, d2, d3;
    usb_rx_decoder8 #(.ZMIN_HS(4), .ZMIN_FS(4)) u_dec (
        .clk60(clk), .rst_n(rst_n), .hs(1'b1), .s_en(8'hFF), .s_lvl(w), .s_se0(8'h00),
        .s_act(act), .buf_afull(1'b0),
        .ev0_wr(e0), .ev0_data(d0), .ev1_wr(e1), .ev1_data(d1),
        .ev2_wr(e2), .ev2_data(d2), .ev3_wr(e3), .ev3_data(d3), .busy(), .ovf());

    // ---------------- SYNC zero runs ----------------
    reg        lvl_p;                // last bit of the previous word
    reg [5:0]  zr;                   // zero run carried (saturates at 63)
    reg [5:0]  orr;                  // run of bits without a transition (saturates at 63)
    reg [5:0]  ot;
    reg [7:0]  act;
    reg [5:0]  cpz [0:7];            // first candidate zero run of the last ticks
    reg [7:0]  cpv;
    reg [5:0]  zt, ct;
    reg        cv, lp;
    integer    i;
    always @(*) begin
        zt = zr; ct = 6'd0; cv = 1'b0; lp = lvl_p; ot = orr;
        for (i = 0; i < 8; i = i + 1) begin
            if (w[i] != lp) begin                      // NRZI 0
                if (zt != 6'd63) zt = zt + 6'd1;
                ot = 6'd0;
            end else begin                             // NRZI 1
                if (ot != 6'd63) ot = ot + 6'd1;
                if (zt >= 6'd4 && !cv) begin ct = zt; cv = 1'b1; end
                zt = 6'd0;
            end
            lp = w[i];
            act[i] = (ot < SQ_BITS);
        end
    end

    // ---------------- PRBS7 checker ----------------
    reg [6:0]  ph;                   // previous 7 received bits, ph[6] newest
    reg [7:0]  perr_w;
    reg [14:0] x;
    reg [3:0]  pe_n;
    integer    j;
    always @(*) begin
        x = {w, ph};                                   // x[0] oldest
        pe_n = 4'd0;
        for (j = 0; j < 8; j = j + 1) begin
            perr_w[j] = x[j + 7] ^ (x[j] ^ x[j + 1]);
            pe_n = pe_n + {3'd0, perr_w[j]};
        end
    end

    // ---------------- events ----------------
    reg [23:0] rxpkt, rxok, losts;
    reg [7:0]  lostmax, lostmin;
    reg [31:0] pbits, perr;
    reg        in_pkt, ok;
    reg [8:0]  idx;
    reg [6:0]  eprbs;
    // per-tick event processing (blocking temporaries, events in order)
    reg        t_in, t_ok, t_start, t_good;
    reg [8:0]  t_idx;
    reg [6:0]  t_pr;
    reg [14:0] t_pn;
    reg [7:0]  t_exp;
    reg [9:0]  ev [0:3];
    reg [3:0]  ew;
    integer    k;
    always @(*) begin
        ev[0] = d0; ev[1] = d1; ev[2] = d2; ev[3] = d3; ew = {e3, e2, e1, e0};
        t_in = in_pkt; t_ok = ok; t_idx = idx; t_pr = eprbs; t_start = 1'b0; t_good = 1'b0;
        t_pn = 15'd0; t_exp = 8'd0;
        for (k = 0; k < 4; k = k + 1) begin
            if (ew[k]) begin
                case (ev[k][9:8])
                    2'b01: begin                                  // START
                        t_in = 1'b1; t_ok = 1'b1; t_idx = 9'd0; t_pr = 7'h5A; t_start = 1'b1;
                    end
                    2'b00: if (t_in) begin                        // BYTE
                        t_pn  = prbs8(t_pr);
                        t_exp = (t_idx == 9'd0) ? 8'hC3 : t_pn[7:0];
                        if (t_idx != 9'd0) t_pr = t_pn[14:8];
                        if (ev[k][7:0] != t_exp || t_idx > {1'b0, txlen}) t_ok = 1'b0;
                        if (t_idx != 9'h1FF) t_idx = t_idx + 9'd1;
                    end
                    default: if (t_in) begin                      // END
                        if (!ev[k][0] && t_ok && t_idx == {1'b0, txlen} + 9'd1) t_good = 1'b1;
                        t_in = 1'b0;
                    end
                endcase
            end
        end
    end

    wire [5:0] zs   = cpv[SYNC_LAT - 1] ? cpz[SYNC_LAT - 1] : 6'd0;   // SYNC zeros of this START
    wire [7:0] lost = (zs >= 6'd31) ? 8'd0 : {2'd0, 6'd31 - zs};

    integer m;
    always @(posedge clk) begin                    // data only
        cpz[0] <= ct;
        for (m = 1; m < 8; m = m + 1) cpz[m] <= cpz[m - 1];
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lvl_p <= 1'b1; zr <= 6'd0; orr <= 6'd63; cpv <= 8'd0; ph <= 7'd0; psync <= 1'b0;
            in_pkt <= 1'b0; ok <= 1'b0; idx <= 9'd0; eprbs <= 7'h5A;
            rxpkt <= 0; rxok <= 0; losts <= 0; lostmax <= 0; lostmin <= 8'hFF; pbits <= 0; perr <= 0;
            snap_ack <= 1'b0; s_rxpkt <= 0; s_rxok <= 0; s_losts <= 0; s_lostmax <= 0;
            s_lostmin <= 8'hFF; s_pbits <= 0; s_perr <= 0;
        end else begin
            lvl_p <= w[7];
            zr    <= zt;
            orr   <= ot;
            cpv   <= {cpv[6:0], cv};
            ph    <= w[7:1];
            psync <= (pe_n == 4'd0);
            in_pkt <= t_in; ok <= t_ok; idx <= t_idx; eprbs <= t_pr;
            if (clr) begin
                rxpkt <= 0; rxok <= 0; losts <= 0; lostmax <= 0; lostmin <= 8'hFF; pbits <= 0; perr <= 0;
            end else begin
                if (t_start) begin
                    rxpkt <= rxpkt + 24'd1;
                    losts <= losts + {16'd0, lost};
                    if (lost > lostmax) lostmax <= lost;
                    if (lost < lostmin) lostmin <= lost;
                end
                if (t_good) rxok <= rxok + 24'd1;
                if (pbits != 32'hFFFF_FFFF) pbits <= pbits + 32'd1;
                if (perr < 32'hFFFF_FFF0) perr <= perr + {28'd0, pe_n};
            end
            if (snap_req != snap_ack) begin
                snap_ack <= snap_req;
                s_rxpkt <= rxpkt; s_rxok <= rxok; s_losts <= losts; s_lostmax <= lostmax;
                s_lostmin <= lostmin; s_pbits <= pbits; s_perr <= perr;
            end
        end
    end

endmodule
