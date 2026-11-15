//-----------------------------------------------------------------------------
// usb_rx_hs_sipo.v - HS receive island on the CDR clock (Plan_60MHz.md 3.3, P5)
//
//   usb_afe_rx_if --clk_rx, hs_rxd, hs_squelch, hs_cdr_lock--> [THIS BLOCK]
//        clk_rx:  usb_rx_hs_frontend -> 1:8 SIPO {level, act} -> word register
//        clk_rxw: write gate --w_en, w_data--> usb_rx_elastic_buffer (word FIFO,
//                 clk_rxw -> clk60) --> usb_rx_decoder8 (HS, 8 bits per tick)
//
// The only part of the HS receive path that runs at the bit rate.
//
// clk_rx part (about 50 flops):
//   * reset release synchronizer for clk_rx (was in usb_rx_datapath);
//   * usb_rx_hs_frontend, unchanged: data capture, 2-FF synchronizers for
//     squelch / cdr_lock / enable, alignment.  So every recovered bit gets the
//     same {b_lvl, b_act} as in the single-clock design, bit for bit, and the
//     squelch / lock / delay settings of usb_afe_rx_if measured in A3 keep
//     their meaning;
//   * 1:8 shift registers of b_lvl and b_act (slot 0 = oldest bit);
//   * a 4-bit Johnson counter {clk_rxw, jc[2:0]} (8 states, every flop -> at
//     most one gate -> flop): clk_rxw is its MSB, high for 4 cycles; a one-hot
//     flag ld_rx (flops, replicated for fan-out) makes the word register take the 8 bits on the edge
//     on which clk_rxw falls, 4 cycles before it rises again.  So the word
//     changes half a word period away from the clk_rxw edge that samples it -
//     the usb_clk_gen boundary rule (ld / clk60) on the CDR clock.  The word
//     register also stores "an active bit in the word" (accumulated bit by
//     bit, so the clk_rxw side only sees a flop).  In simulation clk_rxw rises one delta after clk_rx, so a word
//     register changing on that edge would be zero-cycle; this never happens.
//     SDC: generated clock clk_rxw = clk_rx / 8, multicycle 4 / 3.
//
// clk_rxw part (write gate, 2 flops + reset synchronizer):
//   A word is written while it has an active bit, and once more after the last
//   one (a word with no active bit, so the decoder sees the receiver drop even
//   if the clock then stops).  So the FIFO carries no idle traffic: between
//   packets it drains, and within a packet the far-end / local clock offset
//   (<= 1000 ppm) moves its level by about one word per 1000.  If a word does
//   not fit (w_full; does not happen while the reader takes a word per tick),
//   it is lost and the next word that fits is replaced by an all-inactive word,
//   so the decoder ends the packet with an error instead of decoding a gap.
//
// Word: w_data = {act[7:0], lvl[7:0]}, slot 0 = oldest bit.
//
// Clocks / resets: clk_rx (free-running CDR clock while HS reception is on),
//   clk_rxw (generated here); rst_n asynchronous, release synchronized to
//   clk_rx and to clk_rxw here.  The clk_rx release is split (Plan_60MHz.md
//   P9): rst_rx_n resets only the flops whose D can differ from their reset
//   value at the first clk_rx edge after the release (front end sq1 / lk1 /
//   en1 / b_en, Johnson bit jc[0]; fan-out 5, single-cycle recovery);
//   rst_rx_m_n, released on the same edge, resets the rest of the island
//   (fan-out 25), whose D inputs all equal their reset values at that edge.
//   Its recovery is a 2-cycle path in constraints/usb_phy.sdc: a release that
//   lands one edge late (or late and metastable) leaves those flops at their
//   reset values either way.  tb_usb_rx_hs_reset checks this with a copy
//   whose rst_rx_m_n is forced to release one edge late.  enable is a clk60 signal (synchronized in
//   usb_rx_hs_frontend).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_rx_hs_sipo (
    input  wire        clk_rx,
    input  wire        rst_n,

    input  wire        rxd,
    input  wire        squelch,
    input  wire        cdr_lock,
    input  wire        enable,

    output reg         clk_rxw,
    output wire        w_en,
    output wire [15:0] w_data,
    input  wire        w_full,
    output wire        w_rst_n
);

    // ---------------- clk_rx reset synchronizer ----------------
    // Two copies of the second stage (Plan_60MHz.md P9), released on the same
    // edge: rst_rx_n (fast, 5 flops, single-cycle recovery) and rst_rx_m_n
    // (multicycle, see the header).
    reg rr1, rst_rx_n, rst_rx_m_n;
    always @(posedge clk_rx or negedge rst_n) begin
        if (!rst_n) rr1 <= 1'b0;
        else        rr1 <= 1'b1;
    end
    // keep on the processes: the two equal flops must not be merged
    (* keep *) always @(posedge clk_rx or negedge rst_n) begin
        if (!rst_n) rst_rx_n <= 1'b0;
        else        rst_rx_n <= rr1;
    end
    (* keep *) always @(posedge clk_rx or negedge rst_n) begin
        if (!rst_n) rst_rx_m_n <= 1'b0;
        else        rst_rx_m_n <= rr1;
    end

    // ---------------- front end (bit for bit as before) ----------------
    wire hb_en, hb_lvl, hb_se0, hb_act;

    usb_rx_hs_frontend u_fe (
        .clk_rx   (clk_rx),
        .rst_n    (rst_rx_n),
        .rst_m_n  (rst_rx_m_n),
        .rxd      (rxd),
        .squelch  (squelch),
        .cdr_lock (cdr_lock),
        .enable   (enable),
        .b_en     (hb_en),
        .b_lvl    (hb_lvl),
        .b_se0    (hb_se0),
        .b_act    (hb_act)
    );

    // ---------------- SIPO, word register, word clock ----------------
    // Johnson states {clk_rxw, jc}: 0000 0001 0011 0111 1111 1110 1100 1000;
    // ld_rx is high in state 1000, so the word loads on the edge 1000 -> 0000,
    // where clk_rxw falls; clk_rxw rises 4 edges later.  480 MHz at the slow
    // corner (Plan_60MHz.md P9): ld_rx drives 17 load enables, so it is four
    // equal flops ld_q[3:0] (fan-out <= 5) plus an inverted one ld_nq, all
    // loaded without a gate from pre_ld (high in state 1100, decoded from
    // 1110); "an active bit in the word" is accumulated bit by bit in acc
    // (acc <= b | (acc & ~ld): at the load edge acc = |ac_sh), so any_w takes
    // a flop, not an 8-input OR.
    reg [2:0] jc;
    reg       pre_ld;
    reg [3:0] ld_q;                   // = ld_rx, four copies
    reg       ld_nq;                  // = ~ld_rx
    reg [7:0] ac_sh, ac_w;
    reg       acc;                    // OR of the act bits shifted in since the last load
    reg       any_w;                  // ac_w != 0
    reg [7:0] lv_sh, lv_w;            // levels: no reset (ignored while act = 0)
    wire      b_in = hb_act & hb_en;  // act bit shifted in

    // jc[0] is the only island flop here whose D differs from its reset value
    // at the first edge after the release (~clk_rxw = 1): fast reset.  All
    // others see their reset value at that edge (jc[2:1] <- jc[1:0] = 0,
    // clk_rxw <- jc[2] = 0, pre_ld <- 0, ld_q <- pre_ld = 0, ld_nq <- 1,
    // ac_sh <- {hb_act = 0, 0}, acc <- 0 (hb_act = 0), ac_w / any_w hold
    // because ld_q = 0): multicycle reset.
    always @(posedge clk_rx or negedge rst_rx_n) begin
        if (!rst_rx_n) jc[0] <= 1'b0;
        else           jc[0] <= ~clk_rxw;
    end

    always @(posedge clk_rx or negedge rst_rx_m_n) begin
        if (!rst_rx_m_n) begin
            jc[2:1] <= 2'd0;
            clk_rxw <= 1'b0;
            pre_ld  <= 1'b0;
            ac_sh   <= 8'h00;
            acc     <= 1'b0;
            ac_w    <= 8'h00;
            any_w   <= 1'b0;
        end else begin
            jc[2:1] <= jc[1:0];
            clk_rxw <= jc[2];
            pre_ld  <= jc[2] & jc[1] & ~jc[0];       // state 1110 -> pre_ld in 1100
            ac_sh   <= {b_in, ac_sh[7:1]};
            acc     <= b_in | (acc & ld_nq);
            if (ld_q[0]) begin
                ac_w[3:0] <= ac_sh[3:0];
                any_w     <= acc;
            end
            if (ld_q[1]) ac_w[7:4] <= ac_sh[7:4];
        end
    end

    // one process per load-flag copy, with keep: equal flops must not be merged
    genvar g;
    generate for (g = 0; g < 4; g = g + 1) begin : g_ld
        (* keep *) always @(posedge clk_rx or negedge rst_rx_m_n) begin
            if (!rst_rx_m_n) ld_q[g] <= 1'b0;
            else             ld_q[g] <= pre_ld;
        end
    end endgenerate
    always @(posedge clk_rx or negedge rst_rx_m_n) begin
        if (!rst_rx_m_n) ld_nq <= 1'b1;
        else             ld_nq <= ~pre_ld;
    end

    always @(posedge clk_rx) begin
        lv_sh <= {hb_lvl, lv_sh[7:1]};
        if (ld_q[2]) lv_w[3:0] <= lv_sh[3:0];
        if (ld_q[3]) lv_w[7:4] <= lv_sh[7:4];
    end

    // ---------------- write gate (clk_rxw) ----------------
    reg wr1, wrst;
    always @(posedge clk_rxw or negedge rst_n) begin
        if (!rst_n) begin
            wr1  <= 1'b0;
            wrst <= 1'b0;
        end else begin
            wr1  <= 1'b1;
            wrst <= wr1;
        end
    end
    assign w_rst_n = wrst;

    // w_en / w_data come from the word register (clk_rx, stable around the
    // clk_rxw edge) and the gate flops; the FIFO drops a write while w_full.
    reg  last_act, drop;
    wire act_any = any_w;

    assign w_en   = act_any || last_act || drop;
    assign w_data = drop ? {8'h00, 8'hFF} : {ac_w, lv_w};

    always @(posedge clk_rxw or negedge wrst) begin
        if (!wrst) begin
            last_act <= 1'b0;
            drop     <= 1'b0;
        end else begin
            last_act <= act_any;
            if (w_en) drop <= w_full;            // lost: the next word is inactive
        end
    end

endmodule
