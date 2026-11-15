//-----------------------------------------------------------------------------
// usb_rx_decoder8.v - RX bit chain, up to 8 bits per clk60 tick (Plan_60MHz.md P3)
//
//   bits (n per tick) -> [1] NRZI decode + SYNC detect -> [2] bit unstuff
//                     -> [3] deserialize 1:8 + EOP / RxError check
//                     -> up to 4 events per tick (to the event FIFO)
//
// The clk60 replacement for ref_rx_decoder (one bit per clock).  One instance
// serves HS (0..8 bits per tick from the HS SIPO / word FIFO) and FS / LS (0 or 1
// DPLL bit per tick), selected by hs.
//
// Input, taken on every clk60 edge (no handshake): n = 0..8 bits per tick in
//   slots 0 .. n-1, slot 0 first in time.  s_en is a thermometer code
//   (s_en[i] = 1 for i < n); slot i carries
//   s_lvl[i]  line level, J = 1 / K = 0;
//   s_se0[i]  SE0 (FS / LS only);
//   s_act[i]  receiver active for this bit.
//   These are b_lvl / b_se0 / b_act of ref_rx_decoder, one slot per b_en bit.
//   FS / LS (hs = 0): at most one bit per tick (s_en[7:1] = 0); with more,
//   a tick could hold three events.  Both are errors (reported in simulation).
//
// Function: exactly that of ref_rx_decoder (ref_rx_nrzi_decoder ->
//   ref_rx_sync_detect -> ref_rx_bit_unstuffer -> ref_rx_deserializer ->
//   ref_rx_eop_check, see their headers for the rules), for the bits of a tick
//   at once.  tb_usb_rx_decoder8 compares both, event for event.
//   hs = 1: HS EOP / error rules and ZMIN_HS; hs = 0: FS / LS rules, ZMIN_FS.
//   hs must be static during a packet (it changes with XcvrSelect only).
//
// Parallel form.  Each of the three stages holds the state of one recurrence of
//   the serial chain and computes every per-bit decision of a tick in closed form
//   from that state and the tick's bits (no bit-to-bit ripple):
//   [1] NRZI: bit i is compared with the level of bit i-1 (prev for bit 0).
//       SYNC: a 1 is a SYNC candidate if the zeros in front of it (a window of
//       ZMIN bits, or all bits of the tick plus the carried zero count) reach
//       ZMIN.  "Hunting" in front of bit i = (hunting at the tick start or a
//       rearm bit before i) and no candidate since the last rearm.
//   [2] Unstuff: stuff bit = first packet bit with exactly six ones in front
//       (window, or the tick's ones plus the carried count).  A second stuff
//       bit in the same tick exists only if the first is in slot 0 (slot 7).
//   [3] Deserializer: data bit counts by prefix popcount (reset at SYNC); the
//       byte that completes in a tick is {held bits, first data bits of the
//       tick}, a barrel shift by the held count; the data bits of the tick are
//       compacted by their prefix count.  EOP check: at most one BYTE per tick
//       (it needs 8 data bits).  A SYNC needs a rearm bit and ZMIN zeros in
//       front of it, so with ZMIN_HS >= 6 a tick has at most one SYNC, with
//       ZMIN_HS = 4 / 5 at most two (the first in slot 0 / 1, the second in
//       slot 6 / 7, a packet in between that starts and ends in the tick).  The
//       events of a tick are, in order: BYTE, END of the open packet, START,
//       END, START, END of the packets started in the tick.  At most four
//       occur (BYTE END START END or START END START END, ZMIN_HS = 4), three
//       with ZMIN_HS = 5, two with ZMIN_HS >= 6.
//   The facts these rest on (a SYNC only after the open packet has ended,
//   because the rearm bit in front of it is an end condition; a packet started
//   in a tick that also holds the next SYNC has ended in between, for the same
//   reason; at most 7 bits behind a SYNC in its tick, so no byte completes and
//   an END there is always an error; an open packet and two SYNCs never share
//   a tick) need ZMIN_HS >= 4 and ZMIN_FS >= 1 (checked at elaboration in
//   simulation) and <= 8 bits per tick.  (FS / LS: one bit per tick, so one
//   event.)
//
// Output: up to four events per tick, in order ev0, ev1, ev2, ev3 (ev<k>_wr is
//   a thermometer code), with the event word of ref_rx_eop_check:
//   {type[1:0], data[7:0]}, type 01 START, 00 BYTE, 10 END (data[0] = error).
//   Typical pairs: BYTE + END (receiver lost right after a byte), END + START
//   (HS: receiver lost, then a new SYNC within the tick); three or four events
//   only with ZMIN_HS < 6 and squelch / lock glitches of a few bits.
//   busy = a packet is open in stage 3 (as ref_rx_eop_check); ovf = number of
//   bytes / packets dropped in the tick (0..2; ref_rx_eop_check pulses once per
//   drop).
//
// Buffer room: buf_afull = the event FIFO cannot take 4 more events, counting
//   the events on ev*_wr (written at the end of this tick): up to three events
//   of a tick plus the END that a packet left open reserves, or four events
//   that leave no packet open.  It is used by stage 3 in the tick in which it
//   assembles the bits (two ticks after they arrived); the rules of
//   ref_rx_eop_check then apply unchanged: no START without room (packet
//   skipped), a BYTE that does not fit is dropped and the END gets the error;
//   the END of an open packet is always written (its entry is reserved).
//
// Latency: the bits of tick t are decoded by stage 1 in tick t, stage 2 in t+1
//   and stage 3 in t+2; their events are in ev*_wr / ev*_data during tick t+3
//   (the serial decoder: 5 bit clocks).
//
// Clocking: clk60 (core clock), active-low asynchronous reset rst_n.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_rx_decoder8 #(
    parameter ZMIN_HS = 6,            // SYNC zeros needed, HS    (4..8)
    parameter ZMIN_FS = 4             // SYNC zeros needed, FS/LS (1..8)
) (
    input  wire       clk60,
    input  wire       rst_n,
    input  wire       hs,

    input  wire [7:0] s_en,
    input  wire [7:0] s_lvl,
    input  wire [7:0] s_se0,
    input  wire [7:0] s_act,

    input  wire       buf_afull,
    output reg        ev0_wr,
    output reg  [9:0] ev0_data,
    output reg        ev1_wr,
    output reg  [9:0] ev1_data,
    output reg        ev2_wr,
    output reg  [9:0] ev2_data,
    output reg        ev3_wr,
    output reg  [9:0] ev3_data,
    output wire       busy,
    output reg  [1:0] ovf
);

    localparam [1:0] EV_BYTE  = 2'b00;
    localparam [1:0] EV_START = 2'b01;
    localparam [1:0] EV_END   = 2'b10;

    localparam [1:0] ST_IDLE = 2'd0;
    localparam [1:0] ST_PKT  = 2'd1;
    localparam [1:0] ST_SKIP = 2'd2;

    // synthesis translate_off
    initial if (ZMIN_HS < 4 || ZMIN_HS > 8 || ZMIN_FS < 1 || ZMIN_FS > 8) begin
        $display("usb_rx_decoder8: ZMIN_HS = %0d (4..8), ZMIN_FS = %0d (1..8)", ZMIN_HS, ZMIN_FS);
        $finish;
    end
    always @(posedge clk60)
        if (rst_n && (s_en & (s_en + 8'd1)) != 8'd0)
            $display("ERROR %m @%0t: s_en %b is not a thermometer code", $time, s_en);
    always @(posedge clk60)
        if (rst_n && !hs && s_en[1])
            $display("ERROR %m @%0t: more than one FS / LS bit in a tick", $time);
    // synthesis translate_on

    integer i, j, k;
    reg     t;                        // loop temporary

    // last valid position as one-hot over p = 0..8 (p = number of bits)
    function [8:0] last_sel(input [7:0] v);
        integer p;
        begin
            for (p = 0; p <= 8; p = p + 1)
                last_sel[p] = ((p == 0) ? 1'b1 : v[p-1]) & ((p == 8) ? 1'b1 : !v[p]);
        end
    endfunction

    // population count, balanced
    function [3:0] popc(input [7:0] x);
        reg [1:0] a0, a1, a2, a3;
        reg [2:0] b0, b1;
        begin
            a0 = x[0] + x[1]; a1 = x[2] + x[3]; a2 = x[4] + x[5]; a3 = x[6] + x[7];
            b0 = a0 + a1;     b1 = a2 + a3;
            popc = b0 + b1;
        end
    endfunction

    //=========================================================================
    // stage 1: NRZI decoder + SYNC detect
    //=========================================================================
    reg       prev_q, hunt_q;
    reg [3:0] zc_q;

    reg [8:0] rf;                     // reference level in front of bit p
    reg [7:0] nb, rm, qz, cand, sy1, pk1;
    reg [8:0] allz;                   // bits 0 .. p-1 all extend the zero run
    reg [8:0] hat;                    // hunting in front of bit p
    reg [8:0] sel1;
    reg       wh, wf, ge, rr, cc;
    reg       prev_n, hunt_n;
    reg [3:0] zc_n, zc_p;
    reg [4:0] zsum;

    always @* begin
        rf[0] = prev_q;
        for (i = 1; i <= 8; i = i + 1)
            rf[i] = (!s_act[i-1] || s_se0[i-1]) ? 1'b1 : s_lvl[i-1];
        for (i = 0; i < 8; i = i + 1) begin
            nb[i] = (s_lvl[i] == rf[i]);
            rm[i] = s_en[i] & (!s_act[i] | s_se0[i]);
            qz[i] = s_en[i] & !nb[i] & !rm[i];
        end
        for (i = 0; i <= 8; i = i + 1) begin
            allz[i] = 1'b1;
            for (j = 0; j < i; j = j + 1) allz[i] = allz[i] & qz[j];
        end
        // SYNC candidates
        for (i = 0; i < 8; i = i + 1) begin
            wh = (i >= ZMIN_HS);
            for (j = i - ZMIN_HS; j < i; j = j + 1) if (j >= 0) wh = wh & qz[j];
            wf = (i >= ZMIN_FS);
            for (j = i - ZMIN_FS; j < i; j = j + 1) if (j >= 0) wf = wf & qz[j];
            zsum = {1'b0, zc_q} + i;
            ge = (hs ? wh : wf) | (allz[i] & (zsum >= (hs ? ZMIN_HS : ZMIN_FS)));
            cand[i] = s_en[i] & !rm[i] & nb[i] & ge;
        end
        // hunting in front of bit p
        for (i = 0; i <= 8; i = i + 1) begin
            rr = 1'b0;
            for (j = 0; j < i; j = j + 1) rr = rr | rm[j];
            cc = 1'b0;
            for (j = 0; j < i; j = j + 1) begin
                t = cand[j];
                for (k = j + 1; k < i; k = k + 1) t = t & !rm[k];
                cc = cc | t;
            end
            hat[i] = (hunt_q | rr) & !cc;
        end
        for (i = 0; i < 8; i = i + 1) begin
            sy1[i] = cand[i] & hat[i];
            pk1[i] = !hat[i];
        end
        // state after the tick
        sel1   = last_sel(s_en);
        prev_n = 1'b0;
        hunt_n = 1'b0;
        zc_n   = 4'd0;
        for (i = 0; i <= 8; i = i + 1) begin
            // zero run in front of bit i (only kept while hunting)
            zc_p = 4'd0;
            for (j = 1; j <= i; j = j + 1) begin
                t = 1'b1;
                for (k = i - j; k < i; k = k + 1) t = t & qz[k];
                if (t) zc_p = j;
            end
            zsum = {1'b0, zc_q} + i;
            if (allz[i]) zc_p = (zsum > 5'd15) ? 4'd15 : zsum[3:0];
            if (!hat[i]) zc_p = 4'd0;
            prev_n = prev_n | (sel1[i] & rf[i]);
            hunt_n = hunt_n | (sel1[i] & hat[i]);
            zc_n   = zc_n   | ({4{sel1[i]}} & zc_p);
        end
    end

    reg [7:0] r1_en, r1_nb, r1_sy, r1_pk, r1_act, r1_se0;
    reg       r1_hs;

    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            prev_q <= 1'b1;
            hunt_q <= 1'b1;
            zc_q   <= 4'd0;
            r1_en  <= 8'd0; r1_nb  <= 8'd0; r1_sy <= 8'd0; r1_pk <= 8'd0;
            r1_act <= 8'd0; r1_se0 <= 8'd0; r1_hs <= 1'b0;
        end else begin
            prev_q <= prev_n;
            hunt_q <= hunt_n;
            zc_q   <= zc_n;
            r1_en  <= s_en;  r1_nb  <= nb;    r1_sy <= sy1; r1_pk <= pk1;
            r1_act <= s_act; r1_se0 <= s_se0; r1_hs <= hs;
        end
    end

    //=========================================================================
    // stage 2: bit unstuffer
    //=========================================================================
    reg [2:0] ones_q;

    reg [7:0] pb, q, raw6, c6, stf, q2, dat2, serr2;
    reg [8:0] sel2;
    reg       w, f;
    reg [2:0] ones_n, ones_p;

    always @* begin
        for (i = 0; i < 8; i = i + 1) begin
            pb[i] = r1_en[i] & r1_pk[i] & r1_act[i] & !r1_se0[i];   // processed packet bit
            q[i]  = (pb[i] & r1_nb[i]) | r1_sy[i];                  // the ones run grows
        end
        // exactly six ones in front of bit i (valid up to the first stuff bit)
        for (i = 0; i < 8; i = i + 1) begin
            w = 1'b1;
            for (j = i - 6; j < i; j = j + 1) if (j >= 0) w = w & q[j];
            if (i < 6)       raw6[i] = w & (ones_q == 3'd6 - i);
            else if (i == 6) raw6[i] = w & (ones_q == 3'd0);
            else             raw6[i] = w & !q[i-7];
            c6[i] = pb[i] & raw6[i];
        end
        f = 1'b0;
        for (i = 0; i < 8; i = i + 1) begin
            stf[i] = c6[i] & !f;
            f      = f | c6[i];
        end
        stf[7] = stf[7] | (stf[0] & (&q[6:1]) & pb[7]);
        for (i = 0; i < 8; i = i + 1) begin
            serr2[i] = stf[i] & r1_nb[i];
            dat2[i]  = pb[i] & !stf[i];
            q2[i]    = q[i] & !stf[i];
        end
        // ones count after the tick: run of q2 in front of p, a SYNC restarts it at 1
        sel2   = last_sel(r1_en);
        ones_n = 3'd0;
        for (i = 0; i <= 8; i = i + 1) begin
            ones_p = 3'd0;
            for (j = 1; j <= i; j = j + 1) begin
                w = 1'b1;
                for (k = i - j; k < i; k = k + 1) w = w & q2[k];
                for (k = i - j + 1; k < i; k = k + 1) w = w & !r1_sy[k];
                if (w) ones_p = j;
            end
            w = 1'b1;
            for (k = 0; k < i; k = k + 1) w = w & q2[k] & !r1_sy[k];
            if (w) ones_p = ones_q + i;
            ones_n = ones_n | ({3{sel2[i]}} & ones_p);
        end
    end

    reg [7:0] r2_en, r2_dat, r2_nb, r2_serr, r2_sy, r2_act, r2_se0;
    reg       r2_hs;

    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            ones_q <= 3'd0;
            r2_en  <= 8'd0; r2_dat <= 8'd0; r2_nb  <= 8'd0; r2_serr <= 8'd0;
            r2_sy  <= 8'd0; r2_act <= 8'd0; r2_se0 <= 8'd0; r2_hs   <= 1'b0;
        end else begin
            ones_q <= ones_n;
            r2_en  <= r1_en; r2_dat <= dat2;   r2_nb  <= r1_nb;  r2_serr <= serr2;
            r2_sy  <= r1_sy; r2_act <= r1_act; r2_se0 <= r1_se0; r2_hs   <= r1_hs;
        end
    end

    //=========================================================================
    // stage 3: deserializer + EOP / RxError check
    //=========================================================================
    reg [7:0] sh_q;                   // last 8 data bits, [7] = newest
    reg [2:0] n_q;                    // data bits held
    reg [1:0] st_q;
    reg       ovf_f_q;

    reg [2:0]  pc [0:7];              // data bits of this tick in front of bit p
    reg [8:0]  syb;                   // a SYNC in front of bit p
    reg [8:0]  syb2;                  // two SYNCs in front of bit p
    reg [2:0]  n7, n0, n_n;
    reg [7:0]  endc, eerr, bytec, g;
    reg [3:0]  nd;
    reg [15:0] seq;
    reg [7:0]  sh_n, byte_v;
    reg        open, any_sy, two_sy, e_pre, e_pre_err, e_post1, e_post2, bb, x;
    reg        b_wr, b_drop, s_wr, pre_wr, post1_wr, post2_wr, s2_wr;
    reg [1:0]  st_n;
    reg        ovf_f_n;
    reg [1:0]  ovf_n;
    reg [4:0]  ev_v;                  // END, START, END, START, END (no BYTE)
    reg [9:0]  ev_d [0:4];
    reg [3:0]  e_w, w_n;
    reg [9:0]  e_d [0:3];
    reg [9:0]  d_n [0:3];
    reg [2:0]  ps;                    // events in front of event j

    always @* begin
        // Data bit counts.  pc[i] = data bits of this tick in front of bit i
        // (balanced popcount).  The counts the EOP check needs are those of the
        // open packet, n_q + pc[i], compared against constants, so they become
        // pc[i] == 7 - n_q (= ~n_q) and pc[i] == -n_q.  A SYNC never comes
        // while a packet is open (the rearm bit in front of it ends the packet),
        // so bits behind a SYNC need no count: no byte completes there (at most
        // 7 data bits follow it in the tick) and an END there is always an error.
        for (i = 0; i < 8; i = i + 1) pc[i] = popc(r2_dat & ((8'd1 << i) - 8'd1));
        syb[0] = 1'b0; syb2[0] = 1'b0;
        for (i = 1; i <= 8; i = i + 1) begin
            syb[i]  = syb[i-1]  | r2_sy[i-1];
            syb2[i] = syb2[i-1] | (r2_sy[i-1] & syb[i-1]);
        end
        any_sy = syb[8];
        two_sy = syb2[8];
        n7 = ~n_q;
        n0 = 3'd0 - n_q;
        for (i = 0; i < 8; i = i + 1) begin
            bytec[i] = r2_dat[i] & (pc[i] == n7);
            endc[i]  = r2_en[i] & (!r2_act[i] | (r2_hs ? r2_serr[i] : (r2_se0[i] | r2_serr[i])));
            eerr[i]  = !r2_act[i] | (r2_hs ? (pc[i] != n7) : (r2_se0[i] ? (pc[i] != n0) : 1'b1));
        end
        // data bits of the packet open after the tick (behind its SYNC)
        n_n = two_sy ? popc(r2_dat & syb2[7:0]) :
              any_sy ? popc(r2_dat & syb[7:0])  : n_q + popc(r2_dat);
        // compacted data bits of the tick, shift register, completed byte
        for (i = 0; i < 8; i = i + 1) begin
            g[i] = 1'b0;
            for (j = 0; j < 8; j = j + 1)
                g[i] = g[i] | (r2_dat[j] & r2_nb[j] & (pc[j] == i));
        end
        nd  = popc(r2_dat);
        seq = {g, sh_q};              // oldest (sh_q[0]) .. newest data bit
        for (i = 0; i < 8; i = i + 1) begin
            sh_n[i]   = seq[nd + i];
            byte_v[i] = seq[4'd8 - n_q + i];
        end
        // events
        open = (st_q != ST_IDLE);
        // first end condition of the tick: ends the open packet
        e_pre_err = 1'b0; x = 1'b0;
        for (i = 0; i < 8; i = i + 1) begin
            if (endc[i] && !x) e_pre_err = eerr[i];
            x = x | endc[i];
        end
        e_pre = open & x;
        // a completed byte in front of it
        bb = 1'b0; x = 1'b0;
        for (i = 0; i < 8; i = i + 1) begin
            x  = x | endc[i];
            bb = bb | (bytec[i] & !x);
        end
        bb     = bb & (st_q == ST_PKT);
        b_wr   = bb & !buf_afull;
        b_drop = bb &  buf_afull;
        // SYNCs: each starts a packet (an open one has ended in front of it,
        // see above); an end condition behind a SYNC ends its packet (always an
        // error).  With two SYNCs the first packet has ended before the second.
        s_wr = any_sy & !buf_afull;
        x = 1'b0;
        for (i = 0; i < 8; i = i + 1) x = x | (syb[i] & !syb2[i] & endc[i]);
        e_post1 = any_sy & x;
        x = 1'b0;
        for (i = 0; i < 8; i = i + 1) x = x | (syb2[i] & endc[i]);
        e_post2 = two_sy & x;
        pre_wr   = e_pre & (st_q == ST_PKT);
        post1_wr = e_post1 & s_wr;
        s2_wr    = two_sy & s_wr;
        post2_wr = e_post2 & s_wr;
        // next state: the packet of the last SYNC, if it is still open
        if (two_sy)      st_n = e_post2 ? ST_IDLE : (buf_afull ? ST_SKIP : ST_PKT);
        else if (any_sy) st_n = e_post1 ? ST_IDLE : (buf_afull ? ST_SKIP : ST_PKT);
        else if (e_pre)  st_n = ST_IDLE;
        else             st_n = st_q;
        ovf_f_n = s_wr ? 1'b0 : (ovf_f_q | b_drop);
        ovf_n   = {1'b0, b_drop} + {1'b0, any_sy & buf_afull} + {1'b0, two_sy & buf_afull};
        // events in order, compacted into slots 0..3.  The BYTE (first in
        // order) depends on the data bit counts and comes late; the others only
        // on SYNC / end flags.  So those are compacted first (at most four: an
        // open packet and two SYNCs never share a tick), and the BYTE shifts
        // them by one slot (then at most three).
        ev_v = {post2_wr, s2_wr, post1_wr, s_wr, pre_wr};
        ev_d[0] = {EV_END, 7'd0, e_pre_err | ovf_f_q | b_drop};
        ev_d[1] = {EV_START, 8'h00};
        ev_d[2] = {EV_END, 7'd0, 1'b1};
        ev_d[3] = {EV_START, 8'h00};
        ev_d[4] = {EV_END, 7'd0, 1'b1};
        for (k = 0; k < 4; k = k + 1) begin e_w[k] = 1'b0; e_d[k] = 10'd0; end
        for (j = 0; j < 5; j = j + 1) begin
            ps = 3'd0;
            for (k = 0; k < j; k = k + 1) ps = ps + ev_v[k];
            for (k = 0; k < 4; k = k + 1)
                if (ev_v[j] && ps == k) begin e_w[k] = 1'b1; e_d[k] = ev_d[j]; end
        end
        w_n[0] = b_wr | e_w[0];
        d_n[0] = b_wr ? {EV_BYTE, byte_v} : e_d[0];
        for (k = 1; k < 4; k = k + 1) begin
            w_n[k] = b_wr ? e_w[k-1] : e_w[k];
            d_n[k] = b_wr ? e_d[k-1] : e_d[k];
        end
    end

    assign busy = (st_q != ST_IDLE);

    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            sh_q     <= 8'd0;
            n_q      <= 3'd0;
            st_q     <= ST_IDLE;
            ovf_f_q  <= 1'b0;
            ev0_wr   <= 1'b0;
            ev0_data <= 10'd0;
            ev1_wr   <= 1'b0;
            ev1_data <= 10'd0;
            ev2_wr   <= 1'b0;
            ev2_data <= 10'd0;
            ev3_wr   <= 1'b0;
            ev3_data <= 10'd0;
            ovf      <= 2'd0;
        end else begin
            sh_q     <= sh_n;
            n_q      <= n_n;
            st_q     <= st_n;
            ovf_f_q  <= ovf_f_n;
            ev0_wr   <= w_n[0];
            ev0_data <= d_n[0];
            ev1_wr   <= w_n[1];
            ev1_data <= d_n[1];
            ev2_wr   <= w_n[2];
            ev2_data <= d_n[2];
            ev3_wr   <= w_n[3];
            ev3_data <= d_n[3];
            ovf      <= ovf_n;
            // synthesis translate_off
            if ((b_wr + ev_v[0] + ev_v[1] + ev_v[2] + ev_v[3] + ev_v[4]) > 4)
                $display("ERROR %m @%0t: more than four events in one tick", $time);
            // synthesis translate_on
        end
    end

endmodule
