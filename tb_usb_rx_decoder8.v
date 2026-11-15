//-----------------------------------------------------------------------------
// tb_usb_rx_decoder8.v - usb_rx_decoder8 against the serial usb_rx_decoder
//                        (Plan_60MHz.md P3)
//
//   iverilog -g2005 -o sim_rx_decoder8 usb_rx_nrzi_decoder.v usb_rx_sync_detect.v \
//            usb_rx_bit_unstuffer.v usb_rx_deserializer.v usb_rx_eop_check.v \
//            usb_rx_decoder.v usb_rx_decoder8.v tb_usb_rx_decoder8.v
//   vvp sim_rx_decoder8
//   (more packets / other seed: iverilog ... -Ptb_usb_rx_decoder8.NPKT=100000,
//    vvp sim_rx_decoder8 +seed=7; HS SYNC length: -Ptb_usb_rx_decoder8.ZMIN_HS=4)
//
// One stream of received bits {lvl, se0, act} goes into serial usb_rx_decoder
// references (HS = 1 / ZMIN_HS and HS = 0 / ZMIN 4), one bit per clock, and into
// usb_rx_decoder8, n bits per tick.  Each tick of the DUT is 8 clocks of the
// references: its n bits, then 8 - n clocks without a bit.  The event
// sequences (START / BYTE / END with the error bit) and the number of dropped
// bytes / packets (ovf) must be identical, per batch of packets.
//
// Backpressure is compared exactly: a random per-tick pattern A[t] is the
// DUT's buf_afull in tick t.  The DUT assembles the bits of tick t in tick t+2;
// the serial EOP check sees the bit of clock c in clock c + 4 (four register
// stages in front of it), so the reference's buf_afull in clock c is
// A[(c - 4) / 8 + 2] and both decide each event on the same flag.
//
// Stimulus, in batches of packets (one speed per batch; a batch ends with
// receiver-inactive bits so both sides are idle at the boundary):
//   HS: 8 bits per tick, sometimes 0..7; squelch gaps (sometimes none); SYNC
//       with 0..31 zeros (short ones are not detected); 0..40 bit-stuffed
//       bytes; HS EOP (01111111 before NRZI); noise bursts (random levels,
//       receiver active / inactive per bit), and forced 3 / 4-event ticks
//       (ZMIN_HS <= 5): a START (SYNC with carried zeros) or the last bit of a
//       byte in slot 0, a 1-bit squelch, ZMIN_HS zeros and a SYNC, a 1-bit
//       squelch - START END START END / BYTE END START END at ZMIN_HS = 4.
//   FS / LS: 0 or 1 bit per tick; idle J, SE0 glitches, RX disabled; SYNC with
//       0..7 zeros; 0..12 bytes; EOP SE0 SE0 J.
//   Errors in a quarter of the packets: flipped bit, cut off (squelch / RX
//   disabled / early EOP), extra bit, missing bit, stuff violation.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_usb_rx_decoder8;

    parameter integer NPKT  = 1000;       // packets in total
    parameter integer BATCH = 100;        // packets per batch
    parameter integer ZMIN_HS = 6;        // 4..8
    localparam integer MAXB = 100000;     // bits per batch (upper bound)
    localparam integer MAXT = 2 * MAXB + 64;  // ticks per batch (upper bound)

    reg clk_s = 1'b0, clk_t = 1'b0;       // serial clock / tick clock
    reg rst_n = 1'b0;

    // ---------------- stimulus memory ----------------
    reg [2:0] bits [0:MAXB-1];            // {lvl, se0, act}
    reg       mark [0:MAXB-1];            // a tick starts at this bit
    reg [3:0] tk_n [0:MAXT-1];            // bits in tick t
    reg       afl  [0:MAXT+3];            // buf_afull in tick t
    integer   nbits, nticks;

    // ---------------- serial references ----------------
    reg        s_en = 0, s_lvl = 1, s_se0 = 0, s_act = 0, s_afull = 0;
    wire       rh_wr, rf_wr, rh_ovf, rf_ovf;
    wire [9:0] rh_d, rf_d;

    usb_rx_decoder #(.HS(1), .ZMIN(ZMIN_HS)) u_rh (.clk(clk_s), .rst_n(rst_n),
        .b_en(s_en), .b_lvl(s_lvl), .b_se0(s_se0), .b_act(s_act), .buf_afull(s_afull),
        .ev_wr(rh_wr), .ev_data(rh_d), .busy(), .ovf(rh_ovf));
    usb_rx_decoder #(.HS(0), .ZMIN(4)) u_rf (.clk(clk_s), .rst_n(rst_n),
        .b_en(s_en), .b_lvl(s_lvl), .b_se0(s_se0), .b_act(s_act), .buf_afull(s_afull),
        .ev_wr(rf_wr), .ev_data(rf_d), .busy(), .ovf(rf_ovf));

    // ---------------- DUT ----------------
    reg        hs = 1'b1;
    reg  [7:0] t_en = 0, t_lvl = 8'hFF, t_se0 = 0, t_act = 0;
    reg        t_afull = 1'b0;
    wire       d_w0, d_w1, d_w2, d_w3, d_busy;
    wire [1:0] d_ovf;
    wire [9:0] d_e0, d_e1, d_e2, d_e3;

    usb_rx_decoder8 #(.ZMIN_HS(ZMIN_HS), .ZMIN_FS(4)) dut (.clk60(clk_t), .rst_n(rst_n), .hs(hs),
        .s_en(t_en), .s_lvl(t_lvl), .s_se0(t_se0), .s_act(t_act), .buf_afull(t_afull),
        .ev0_wr(d_w0), .ev0_data(d_e0), .ev1_wr(d_w1), .ev1_data(d_e1),
        .ev2_wr(d_w2), .ev2_data(d_e2), .ev3_wr(d_w3), .ev3_data(d_e3),
        .busy(d_busy), .ovf(d_ovf));

    // ---------------- event queues ----------------
    localparam integer QL = 65536;
    reg [9:0] q_r [0:QL-1], q_d [0:QL-1];
    integer   n_r, n_d, o_r, o_d;
    integer   c_start, c_byte, c_end_ok, c_end_err, c_two, c_end_start, c_byte_end;
    integer   c_three, c_four, c_sese, c_bese, c_dov;

    always @(posedge clk_s) if (rst_n) begin
        if (hs ? rh_wr : rf_wr) begin q_r[n_r % QL] = hs ? rh_d : rf_d; n_r = n_r + 1; end
        if (hs ? rh_ovf : rf_ovf) o_r = o_r + 1;
    end

    integer errors = 0;
    task err(input [8*64-1:0] msg);
        begin
            errors = errors + 1;
            if (errors <= 20) $display("ERROR @%0t: %0s", $time, msg);
        end
    endtask

    always @(posedge clk_t) if (rst_n) begin
        if (d_w0) begin q_d[n_d % QL] = d_e0; n_d = n_d + 1; end
        if (d_w1) begin q_d[n_d % QL] = d_e1; n_d = n_d + 1; end
        if (d_w2) begin q_d[n_d % QL] = d_e2; n_d = n_d + 1; end
        if (d_w3) begin q_d[n_d % QL] = d_e3; n_d = n_d + 1; end
        if ((d_w1 && !d_w0) || (d_w2 && !d_w1) || (d_w3 && !d_w2)) err("ev*_wr not a thermometer code");
        o_d = o_d + d_ovf;
        if (d_ovf == 2'd2) c_dov = c_dov + 1;
        if (d_w2) c_three = c_three + 1;
        if (d_w3) c_four  = c_four + 1;
        if (d_w3 && d_e0[9:8] == 2'b01 && d_e2[9:8] == 2'b01) c_sese = c_sese + 1;
        if (d_w3 && d_e0[9:8] == 2'b00 && d_e2[9:8] == 2'b01) c_bese = c_bese + 1;
        // coverage
        if (d_w0 && d_e0[9:8] == 2'b01) c_start = c_start + 1;
        if (d_w1 && d_e1[9:8] == 2'b01) c_start = c_start + 1;
        if (d_w0 && d_e0[9:8] == 2'b00) c_byte  = c_byte + 1;
        if (d_w0 && d_e0[9:8] == 2'b10) begin if (d_e0[0]) c_end_err = c_end_err + 1; else c_end_ok = c_end_ok + 1; end
        if (d_w1 && d_e1[9:8] == 2'b10) begin if (d_e1[0]) c_end_err = c_end_err + 1; else c_end_ok = c_end_ok + 1; end
        if (d_w1) c_two = c_two + 1;
        if (d_w1 && d_e0[9:8] == 2'b10 && d_e1[9:8] == 2'b01) c_end_start = c_end_start + 1;
        if (d_w1 && d_e0[9:8] == 2'b00 && d_e1[9:8] == 2'b10) c_byte_end  = c_byte_end + 1;
    end

    // ---------------- stimulus generator ----------------
    integer seed = 32'h0D_EC08;
    integer k;
    reg     lvl;                          // current line level (NRZI state)
    integer ones;                         // stuffing run
    reg     quick = 1'b0;                 // HS: next packet right behind a 1-bit squelch

    function integer rnd(input integer n);   // 0 .. n-1
        rnd = $unsigned($random(seed)) % n;
    endfunction

    task put_bit(input l, input s0, input a);
        begin
            bits[k] = {l, s0, a};
            mark[k] = 1'b0;
            k = k + 1;
        end
    endtask

    // one decoded bit: NRZI-encode it (0 = change, 1 = no change)
    task put_dec(input b);
        begin
            if (!b) lvl = ~lvl;
            put_bit(lvl, 1'b0, 1'b1);
        end
    endtask

    // a data bit with stuffing
    task put_data(input b);
        begin
            put_dec(b);
            ones = b ? ones + 1 : 0;
            if (ones == 6) begin
                put_dec(1'b0);
                ones = 0;
            end
        end
    endtask

    task idle_inactive(input integer n);
        integer m;
        begin
            for (m = 0; m < n; m = m + 1) put_bit(1'b1, 1'b0, 1'b0);
            lvl = 1'b1;
        end
    endtask

    task fs_eop;
        begin
            put_bit(1'b0, 1'b1, 1'b1);
            put_bit(1'b0, 1'b1, 1'b1);
            put_bit(1'b1, 1'b0, 1'b1);
            lvl = 1'b1;
        end
    endtask

    task packet;
        integer nz, nby, b, bit_i, err_kind, err_at, cnt, tot;
        reg [7:0] by;
        begin
            // HS noise burst / forced two-SYNC tick in front of some packets
            if (hs && !quick && rnd(8) == 0) begin
                for (b = 8 + rnd(40); b > 0; b = b - 1) begin
                    if (rnd(5) == 0) put_bit(1'b1, 1'b0, 1'b0);
                    else             begin lvl = rnd(2); put_bit(lvl, 1'b0, 1'b1); end
                end
                idle_inactive(1 + rnd(3));
            end
            if (hs && !quick && ZMIN_HS <= 5 && rnd(16) == 0) begin
                repeat (ZMIN_HS + 2) put_dec(1'b0);       // SYNC (zeros carried into the tick)
                put_dec(1'b1);
                if (rnd(2)) begin                         // START in slot 0 ...
                    mark[k-1] = 1'b1;
                end else begin                            // ... or a BYTE (00h) in slot 0
                    ones = 1;
                    repeat (8) put_data(1'b0);
                    mark[k-1] = 1'b1;
                end
                idle_inactive(1);                         // END in slot 1
                repeat (ZMIN_HS) put_dec(1'b0);
                put_dec(1'b1);                            // START in slot ZMIN_HS + 2
                idle_inactive(1 + rnd(4));                // (ZMIN_HS = 4: END in slot 7)
            end
            // gap in front
            if (hs) begin
                if (!quick && rnd(10) != 0) idle_inactive(1 + rnd(20));
            end else begin
                case (rnd(10))
                    0:       idle_inactive(1 + rnd(3));                     // RX disabled
                    1:       begin put_bit(1'b0, 1'b1, 1'b1); lvl = 1'b1; end  // SE0 glitch
                    default: ;
                endcase
                for (b = rnd(6); b > 0; b = b - 1) put_bit(1'b1, 1'b0, 1'b1);  // idle J
                lvl = 1'b1;
            end
            nz  = quick ? 6 : hs ? rnd(32) : rnd(8);
            quick = 1'b0;
            nby = hs ? rnd(41) : rnd(13);
            err_kind = (rnd(4) == 0) ? 1 + rnd(5) : 0;
            tot = 8 * nby;
            err_at = (tot > 0) ? rnd(tot) : 0;
            // SYNC: nz zeros then 1
            for (b = 0; b < nz; b = b + 1) put_dec(1'b0);
            put_dec(1'b1);
            ones = 1;
            // payload
            cnt = 0;
            for (b = 0; b < nby; b = b + 1) begin
                by = $random(seed);
                for (bit_i = 0; bit_i < 8; bit_i = bit_i + 1) begin
                    if (err_kind != 0 && cnt == err_at) begin
                        case (err_kind)
                            1: by[bit_i] = ~by[bit_i];                       // flip (stuffing follows)
                            2: begin                                         // cut off here
                                   if (hs && rnd(2)) begin                   // END + START in one tick
                                       mark[k] = 1'b0; idle_inactive(1); mark[k-1] = 1'b1; quick = 1'b1;
                                   end
                                   else if (hs)     idle_inactive(2 + rnd(4));
                                   else if (rnd(2)) idle_inactive(2);
                                   else             fs_eop;
                                   err_kind = 9;                             // rest of the packet lost
                               end
                            3: put_data(rnd(2));                             // extra bit
                            4: begin cnt = cnt + 1; bit_i = bit_i + 1; end   // missing bit
                            5: begin repeat (7) put_dec(1'b1); ones = 0; end // stuff violation
                        endcase
                    end
                    if (err_kind != 9 && bit_i < 8) put_data(by[bit_i]);
                    cnt = cnt + 1;
                end
            end
            // EOP
            if (err_kind != 9) begin
                if (hs) begin
                    put_dec(1'b0);
                    repeat (7) put_dec(1'b1);
                end else begin
                    fs_eop;
                end
            end
        end
    endtask

    // ---------------- drivers ----------------
    always #1.0 clk_s = ~clk_s;
    always #4.0 clk_t = ~clk_t;

    integer bi, pi, t, ts, c, e, es, m, ci, apct, n_pkt_total, n_hs_b, n_fs_b;
    integer base_r, base_d, base_or, base_od;
    reg [2:0] v;
    reg [7:0] b_en, b_lvl, b_se0, b_act;

    initial begin
        if ($value$plusargs("seed=%d", seed)) $display("seed %0d", seed);
        n_r = 0; n_d = 0; o_r = 0; o_d = 0;
        c_start = 0; c_byte = 0; c_end_ok = 0; c_end_err = 0; c_two = 0; c_end_start = 0; c_byte_end = 0;
        c_three = 0; c_four = 0; c_sese = 0; c_bese = 0; c_dov = 0;
        n_pkt_total = 0; n_hs_b = 0; n_fs_b = 0;
        repeat (4) @(posedge clk_s);
        rst_n = 1'b1;
        repeat (4) @(posedge clk_t);

        for (bi = 0; n_pkt_total < NPKT; bi = bi + 1) begin
            // ---- build a batch ----
            @(negedge clk_t);
            hs = (bi % 2 == 0);
            if (hs) n_hs_b = n_hs_b + 1; else n_fs_b = n_fs_b + 1;
            apct = (rnd(3) == 0) ? 30 : 0;            // backpressure in a third of the batches
            k = 0; lvl = 1'b1; ones = 0;
            idle_inactive(4);
            for (pi = 0; pi < BATCH && k < MAXB - 3000; pi = pi + 1) packet;
            n_pkt_total = n_pkt_total + pi;
            idle_inactive(24);
            nbits = k;
            // bits per tick
            m = 0;
            for (t = 0; m < nbits; t = t + 1) begin
                if (hs) tk_n[t] = (rnd(16) == 0) ? rnd(8) : 8;
                else    tk_n[t] = rnd(2);
                for (e = tk_n[t] - 1; e > 0; e = e - 1)       // tick boundary at a mark
                    if (m + e < nbits && mark[m + e]) tk_n[t] = e;
                if (m + tk_n[t] > nbits) tk_n[t] = nbits - m;
                m = m + tk_n[t];
            end
            nticks = t;
            for (t = 0; t < nticks + 4; t = t + 1) afl[t] = (rnd(100) < apct);
            base_r = n_r; base_d = n_d; base_or = o_r; base_od = o_d;

            // ---- run both sides on the batch ----
            fork
                begin : serial_side
                    ci = 0;
                    for (ts = 0; ts < nticks + 2; ts = ts + 1)
                        for (es = 0; es < 8; es = es + 1) begin
                            @(negedge clk_s);
                            c = 8 * ts + es;
                            if (ts < nticks && es < tk_n[ts]) begin
                                v = bits[ci]; ci = ci + 1;
                                s_en = 1'b1; s_lvl = v[2]; s_se0 = v[1]; s_act = v[0];
                            end else begin
                                s_en = 1'b0;
                            end
                            s_afull = (c >= 4) ? afl[(c - 4) / 8 + 2] : 1'b0;
                        end
                    s_en = 1'b0;
                end
                begin : tick_side
                    m = 0;
                    for (t = 0; t < nticks + 4; t = t + 1) begin
                        @(negedge clk_t);
                        b_en = 8'd0; b_lvl = 8'hFF; b_se0 = 8'd0; b_act = 8'd0;
                        if (t < nticks)
                            for (e = 0; e < tk_n[t]; e = e + 1) begin
                                b_en[e] = 1'b1;
                                {b_lvl[e], b_se0[e], b_act[e]} = bits[m];
                                m = m + 1;
                            end
                        {t_en, t_lvl, t_se0, t_act} = {b_en, b_lvl, b_se0, b_act};   // one update per tick
                        t_afull = afl[t];
                    end
                    t_en = 8'd0;
                end
            join
            repeat (4) @(posedge clk_t);

            // ---- compare this batch ----
            if (n_d - base_d != n_r - base_r) begin
                err("number of events differs");
                $display("   batch %0d (%s): serial %0d, decoder8 %0d", bi, hs ? "HS" : "FS/LS", n_r - base_r, n_d - base_d);
            end
            for (e = 0; e < n_r - base_r && e < n_d - base_d; e = e + 1)
                if (q_r[(base_r + e) % QL] !== q_d[(base_d + e) % QL]) begin
                    err("event differs");
                    if (errors <= 20) $display("   batch %0d (%s) event %0d: serial %h, decoder8 %h", bi, hs ? "HS" : "FS/LS",
                                               e, q_r[(base_r + e) % QL], q_d[(base_d + e) % QL]);
                end
            if (o_d - base_od != o_r - base_or) begin
                err("number of drops (ovf) differs");
                $display("   batch %0d: serial %0d, decoder8 %0d", bi, o_r - base_or, o_d - base_od);
            end
            if (d_busy) err("decoder8 busy at a batch boundary");
            if (errors > 20) begin
                $display("TEST FAILED: %0d errors", errors);
                $finish;
            end
        end

        if (o_d == 0)       err("backpressure never dropped anything");
        if (c_end_start == 0) err("no END + START in one tick");
        if (c_byte_end == 0)  err("no BYTE + END in one tick");
        if (ZMIN_HS < 6 && c_three == 0) err("no tick with three events");
        if (ZMIN_HS == 4 && c_sese == 0) err("no START END START END tick");
        if (ZMIN_HS == 4 && c_bese == 0) err("no BYTE END START END tick");
        $display("%0d packets in %0d HS + %0d FS/LS batches; %0d events: %0d START, %0d BYTE, END %0d ok / %0d error",
                 n_pkt_total, n_hs_b, n_fs_b, n_d, c_start, c_byte, c_end_ok, c_end_err);
        $display("two events in a tick: %0d (END+START %0d, BYTE+END %0d); drops (ovf): %0d",
                 c_two, c_end_start, c_byte_end, o_d);
        $display("ZMIN_HS %0d: three events %0d, four %0d (START END START END %0d, BYTE END START END %0d); two drops in a tick %0d",
                 ZMIN_HS, c_three, c_four, c_sese, c_bese, c_dov);
        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d errors", errors);
        $finish;
    end

endmodule
