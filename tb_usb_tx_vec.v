//-----------------------------------------------------------------------------
// tb_usb_tx_vec.v - 60 MHz TX chain against the bit-serial reference
//                   (Plan_60MHz.md P6)
//
//   iverilog -g2005 -o sim_tx_vec usb_tx_serializer.v usb_tx_serializer8.v \
//            usb_afe_tx_if.v usb_afe_tx_if8.v usb_tx_piso.v tb_usb_tx_vec.v
//   vvp sim_tx_vec [+seed=n]
//
// One random word stream (HS / FS / LS / FS-rate packets, last words with
// 0..8 bits, eop_dis, gaps that cause underruns) drives
//   reference: usb_tx_serializer (clk_bit, ce60) -> usb_afe_tx_if (clk_bit)
//   DUT:       usb_tx_serializer8 (clk60) -> usb_afe_tx_if8 (clk60)
//              -> usb_tx_piso (clk_bit, load on ld)
// Checked
//   * serializer, tick for tick: in_ready before every clk60 edge, busy,
//     tx_speed; every vector bit i of tick T equals the reference txd /
//     tx_en / tx_se0 after clk_bit edge 8T + 2 + i; tx_done / tx_underrun in
//     the tick that holds the reference pulse;
//   * pins, cycle-exact: every DUT pin equals the reference pin LAT clk_bit
//     cycles earlier, for random tx_lead / tx_lag / lead_first (changed only
//     while idle), outside the clamp;
//   * clamp (drv_dis / iso_en, random pulses of 1..40 cycles, reference
//     without clamp): from the second edge after the clamp the pins are idle
//     until the last driver enable of the interrupted packet has fallen, then
//     the shifted reference again; fs_ls goes to 0 and holds until the next
//     FS/LS bit; tx_active is high a cycle before every driven enable and low
//     once nothing is in flight.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_usb_tx_vec;

    parameter integer NPKT = 3000;
    parameter integer LAT  = 9;                 // DUT pins vs reference pins, clk_bit cycles

    integer errors = 0;
    integer seed   = 32'h6E7A_0B1D;
    task err(input [8*72-1:0] msg);
        begin
            errors = errors + 1;
            if (errors <= 25) $display("ERROR @%0t: %0s", $time, msg);
        end
    endtask

    // ---------------- clocks (CLAUDE.md TB convention) ----------------
    reg clk_bit = 1'b0;
    always #1.0416667 clk_bit = ~clk_bit;
    reg [2:0] ce_cnt = 3'd0;
    reg clk60 = 1'b0;
    wire ce60 = (ce_cnt == 3'd7);
    wire ld   = (ce_cnt == 3'd3);
    always @(posedge clk_bit) begin
        if (ce_cnt == 3'd7) clk60 = 1'b1;
        if (ce_cnt == 3'd3) clk60 = 1'b0;
        ce_cnt <= ce_cnt + 3'd1;
    end
    reg rst_n = 1'b0;
    integer cyc = 0;                            // clk_bit edge counter (edge 8T has ce60)
    always @(posedge clk_bit) cyc <= cyc + 1;

    function integer rnd(input integer n);
        rnd = $unsigned($random(seed)) % n;
    endfunction

    // ---------------- word source ----------------
    reg        s_valid = 1'b0, s_last = 1'b0;
    reg  [7:0] s_data = 8'h00;
    reg  [3:0] s_nbits = 4'd8;
    reg  [1:0] speed = 2'b00;
    reg        eop_dis = 1'b0;
    wire       r_ready, n_ready;

    // ---------------- reference serializer ----------------
    wire       r_txd, r_en, r_se0, r_busy, r_done, r_under;
    wire [1:0] r_spd;
    usb_tx_serializer u_ref (
        .clk_bit(clk_bit), .rst_n(rst_n), .ce60(ce60), .speed(speed), .eop_dis(eop_dis),
        .in_valid(s_valid), .in_ready(r_ready), .in_data(s_data), .in_nbits(s_nbits), .in_last(s_last),
        .txd(r_txd), .tx_en(r_en), .tx_se0(r_se0), .tx_speed(r_spd),
        .busy(r_busy), .tx_done(r_done), .tx_underrun(r_under));

    // ---------------- DUT serializer ----------------
    wire [7:0] v_d, v_e, v_s;
    wire [1:0] n_spd;
    wire       n_busy, n_done, n_under;
    usb_tx_serializer8 u_ser (
        .clk(clk60), .rst_n(rst_n), .speed(speed), .eop_dis(eop_dis),
        .in_valid(s_valid), .in_ready(n_ready), .in_data(s_data), .in_nbits(s_nbits), .in_last(s_last),
        .txd_v(v_d), .tx_en_v(v_e), .tx_se0_v(v_s), .tx_speed(n_spd),
        .busy(n_busy), .tx_done(n_done), .tx_underrun(n_under));

    // ---------------- AFE interface: reference and DUT ----------------
    reg  [4:0] tx_lead = 5'd0;
    reg  [2:0] tx_lag  = 3'd0;
    reg        lead_first = 1'b0;
    reg        drv_dis = 1'b0, iso_en = 1'b0;
    wire       r_p, r_n, r_hen, r_oe, r_dat, r_se0p, r_ls, r_act;
    usb_afe_tx_if u_ref_if (
        .clk_bit(clk_bit), .rst_n(rst_n),
        .txd(r_txd), .tx_en(r_en), .tx_se0(r_se0), .tx_speed(r_spd),
        .tx_lead(tx_lead), .tx_lag(tx_lag), .drv_dis(1'b0), .iso_en(1'b0), .lead_first(lead_first),
        .hs_tx_p(r_p), .hs_tx_n(r_n), .hs_tx_en(r_hen),
        .fs_oe(r_oe), .fs_dat(r_dat), .fs_se0(r_se0p), .fs_ls(r_ls), .tx_active(r_act));

    wire [7:0] p_p, p_hen, p_oe, p_dat, p_se0, p_any;
    wire       p_ls, p_act;
    usb_afe_tx_if8 u_if8 (
        .clk60(clk60), .rst_n(rst_n),
        .txd_v(v_d), .tx_en_v(v_e), .tx_se0_v(v_s), .tx_speed(n_spd),
        .tx_lead(tx_lead), .tx_lag(tx_lag), .lead_first(lead_first),
        .hs_p_v(p_p), .hs_en_v(p_hen), .fs_oe_v(p_oe), .fs_dat_v(p_dat), .fs_se0_v(p_se0),
        .any_v(p_any), .fs_ls_q(p_ls), .act(p_act));

    wire       d_p, d_n, d_hen, d_oe, d_dat, d_se0, d_ls, d_act;
    usb_tx_piso u_piso (
        .clk_bit(clk_bit), .rst_n(rst_n), .ld(ld),
        .hs_p_v(p_p), .hs_en_v(p_hen), .fs_oe_v(p_oe), .fs_dat_v(p_dat), .fs_se0_v(p_se0),
        .any_v(p_any), .fs_ls_q(p_ls), .act(p_act),
        .drv_dis(drv_dis), .iso_en(iso_en),
        .hs_tx_p(d_p), .hs_tx_n(d_n), .hs_tx_en(d_hen),
        .fs_oe(d_oe), .fs_dat(d_dat), .fs_se0(d_se0), .fs_ls(d_ls), .tx_active(d_act));

    // ---------------- stimulus: packets of words, changed on clk60 edges ----------------
    integer pk = 0, wl = 0, wi = 0, gap = 0, mode = 0, n_under_seen = 0, n_done_seen = 0;
    integer cfg_ph = 0, n_cfg = 0;
    reg [1:0] last_spd = 2'b00;
    integer n_hs = 0, n_fs = 0, n_ls = 0;
    reg     in_pkt = 1'b0;
    always @(posedge clk_bit) if (rst_n && ce60) begin
        if (s_valid && r_ready) begin                // word taken on this edge
            wi = wi + 1;
            if (s_last) in_pkt = 1'b0;
        end
        if (s_valid && !r_ready) begin
            // keep the word until it is taken
        end else if (!in_pkt) begin
            s_valid <= 1'b0;
            if (gap > 0) gap = gap - 1;
            else if (!r_busy && !s_valid && pk < NPKT && cfg_ph == 0 && rnd(25) == 0) begin
                // configuration change: only with the line long idle (20 ticks
                // before and after; the DUTs take it over after 16 idle ticks)
                cfg_ph = 1; gap = 20 + rnd(4);
            end else if (cfg_ph == 1) begin
                tx_lead <= (rnd(3) == 0) ? 5'd31 : $random(seed);
                tx_lag  <= $random(seed);
                lead_first <= $random(seed);
                n_cfg = n_cfg + 1;
                cfg_ph = 2; gap = 20 + rnd(4);
            end else if (!r_busy && !s_valid && pk < NPKT) begin
                // new packet; speed / eop_dis change a tick before the first word
                cfg_ph = 0;
                mode = rnd(16);
                speed   <= (mode < 9) ? 2'b00 : (mode < 12) ? 2'b01 : (mode < 14) ? 2'b10 : 2'b11;
                eop_dis <= (rnd(6) == 0);
                wl = (mode < 9) ? rnd(12) : rnd(3);    // words before the last one
                wi = 0;
                in_pkt = 1'b1;
                pk = pk + 1;
                gap = 1 + rnd(3);
                // another speed: let the previous packet leave the lead window first
                if (((mode < 9) ? 2'b00 : (mode < 12) ? 2'b01 : (mode < 14) ? 2'b10 : 2'b11) != last_spd) gap = 8;
                last_spd = (mode < 9) ? 2'b00 : (mode < 12) ? 2'b01 : (mode < 14) ? 2'b10 : 2'b11;
            end
        end else if (gap > 0) begin
            gap = gap - 1;
            s_valid <= 1'b0;
        end else begin
            s_valid <= 1'b1;
            s_data  <= $random(seed);
            s_last  <= (wi >= wl);
            s_nbits <= (wi >= wl) ? rnd(11) : rnd(16);  // > 8 clamped; ignored unless last
            // short gaps: HS underruns; rare long ones: FS / LS underruns
            if (rnd(12) == 0) gap = 1 + rnd(3);
            else if (rnd(60) == 0) gap = 20 + rnd(400);
        end
    end
    // a word presented while the packet is open: keep it until taken
    // (s_valid is only lowered by the gap logic before the next word)

    // ---------------- serializer checks ----------------
    // reference outputs per clk_bit edge, ring indexed by edge number
    reg [2:0] rq [0:255];                        // {se0, en, txd}
    reg       rd_q [0:255], ru_q [0:255];
    always @(posedge clk_bit) begin
        #0.01;
        rq[cyc[7:0]]   = {r_se0, r_en, r_txd};
        rd_q[cyc[7:0]] = r_done;
        ru_q[cyc[7:0]] = r_under;
    end
    // vector of tick T is registered at edge 8T (cyc = 8T after the edge);
    // compare it once the reference has produced edges 8T+2 .. 8T+9
    reg [7:0] vq_d [0:31], vq_e [0:31], vq_s [0:31];
    reg       vq_done [0:31], vq_under [0:31];
    integer   tT, i, e;
    reg       ck_on = 1'b0;
    always @(posedge clk60) begin
        #0.02;
        tT = cyc / 8;                            // cyc is 8T now
        vq_d[tT % 32] = v_d; vq_e[tT % 32] = v_e; vq_s[tT % 32] = v_s;
        vq_done[tT % 32] = n_done; vq_under[tT % 32] = n_under;
        if (n_under) n_under_seen = n_under_seen + 1;
        if (n_done)  n_done_seen  = n_done_seen + 1;
        // tick T-2: its bits are reference edges 8T-14 .. 8T-7, done window
        // 8T-14 .. 8T-7, underrun window 8T-15 .. 8T-8
        if (ck_on && tT >= 4) begin
            for (i = 0; i < 8; i = i + 1) begin
                e = 8 * (tT - 2) + 2 + i;
                if ({vq_s[(tT-2) % 32][i], vq_e[(tT-2) % 32][i], vq_d[(tT-2) % 32][i]} !== rq[e % 256]) begin
                    err("vector bit differs from the reference serializer");
                    i = 8;
                end
            end
            if (vq_done[(tT-2) % 32] !== (rd_q[(8*(tT-2)+2) % 256] | rd_q[(8*(tT-2)+3) % 256] |
                rd_q[(8*(tT-2)+4) % 256] | rd_q[(8*(tT-2)+5) % 256] | rd_q[(8*(tT-2)+6) % 256] |
                rd_q[(8*(tT-2)+7) % 256] | rd_q[(8*(tT-2)+8) % 256] | rd_q[(8*(tT-2)+9) % 256]))
                err("tx_done tick differs");
            if (vq_under[(tT-2) % 32] !== (ru_q[(8*(tT-2)+1) % 256] | ru_q[(8*(tT-2)+2) % 256] |
                ru_q[(8*(tT-2)+3) % 256] | ru_q[(8*(tT-2)+4) % 256] | ru_q[(8*(tT-2)+5) % 256] |
                ru_q[(8*(tT-2)+6) % 256] | ru_q[(8*(tT-2)+7) % 256] | ru_q[(8*(tT-2)+8) % 256]))
                err("tx_underrun tick differs");
        end
    end
    // handshake / status just before each clk60 edge (same edge as ce60)
    always @(posedge clk_bit) if (rst_n && ce60) begin
        if (r_ready !== n_ready) err("in_ready differs");
        if (r_busy  !== n_busy)  err("busy differs");
        if (r_spd   !== n_spd)   err("tx_speed differs");
        if (s_valid && r_ready) begin
            case (speed) 2'b00: n_hs = n_hs + 1; 2'b10: n_ls = n_ls + 1; default: n_fs = n_fs + 1; endcase
        end
    end

    // ---------------- pin checks ----------------
    // reference pins per clk_bit edge {ls, se0, dat, oe, hen, n, p}
    reg [6:0] pq [0:255];
    reg       cqm = 1'b0, kqm = 1'b0, lsm = 1'b0, F;
    reg [6:0] ex, rf, rn;
    integer   n_clamp = 0, n_cl_cyc = 0, n_act_err = 0, quiet_m = 0;
    always @(posedge clk_bit) begin
        #0.01;
        pq[cyc[7:0]] = {r_ls, r_se0p, r_dat, r_oe, r_hen, r_n, r_p};
        if (!rst_n) begin
            cqm = 1'b0; kqm = 1'b0; lsm = 1'b0;
            if ({d_ls, d_se0, d_dat, d_oe, d_hen, d_n, d_p} !== 7'b0010001 || d_act !== 1'b0)
                err("pins not idle in reset");
        end else if (cyc > 2 * LAT + 2) begin
            rf = pq[(cyc - LAT) & 255];          // reference LAT edges ago
            rn = pq[(cyc - LAT + 1) & 255];      // the bit after it (in the DUT's shift register now)
            F  = cqm | kqm;                      // clamp registered before this edge
            ex = F ? 7'b0010001 : rf;
            lsm = F ? 1'b0 : (rf[3] ? rf[6] : lsm);
            ex[6] = lsm;
            if ({d_ls, d_se0, d_dat, d_oe, d_hen, d_n, d_p} !== ex) begin
                err("pins differ from the reference (shifted by LAT, clamp model)");
                if (errors < 6) $display("   got %b exp %b ref %b F %b", {d_ls, d_se0, d_dat, d_oe, d_hen, d_n, d_p}, ex, rf, F);
            end
            if (F) n_cl_cyc = n_cl_cyc + 1;
            // tx_active is high a cycle before every driven enable (dropped bits
            // are not driven; the old usb_afe_tx_if does not cover them either)
            if ((rn[2] | rn[3]) && !F && !d_act) begin
                n_act_err = n_act_err + 1; err("tx_active low while a driver enable is due");
            end
            // ... and is low after a long quiet time
            quiet_m = (r_en | r_hen | r_oe | rf[2] | rf[3]) ? 0 : quiet_m + 1;
            if (quiet_m > 40 && d_act) err("tx_active high with nothing in flight");
            // clamp model update (DUT: cq <= drv_dis | iso_en; kq <= cq | kq & any,
            // where any = the enable the DUT puts on the pins at this edge)
            kqm = cqm | (kqm & (rf[2] | rf[3]));
            cqm = drv_dis | iso_en;
        end
    end

    // clamp pulses at random times (inputs change between edges)
    always @(negedge clk_bit) if (rst_n && ck_on) begin
        if (!drv_dis && !iso_en && rnd(3000) == 0) begin
            n_clamp = n_clamp + 1;
            if (rnd(2)) drv_dis = 1'b1; else iso_en = 1'b1;
            repeat (1 + rnd(40)) @(negedge clk_bit);
            drv_dis = 1'b0; iso_en = 1'b0;
        end
    end

    // ---------------- run ----------------
    initial begin
        if ($value$plusargs("seed=%d", seed)) $display("seed %0d", seed);
        #20.3;
        @(posedge clk_bit); while (!ce60) @(posedge clk_bit);
        rst_n = 1'b1;
        repeat (40) @(posedge clk60);
        ck_on = 1'b1;
        while (pk < NPKT || in_pkt || r_busy) @(posedge clk60);
        repeat (40) @(posedge clk60);
        $display("%0d packets, words HS %0d / FS %0d / LS %0d, %0d tx_done, %0d underruns",
                 pk, n_hs, n_fs, n_ls, n_done_seen, n_under_seen);
        $display("%0d configurations, %0d clamp pulses (%0d forced cycles)", n_cfg, n_clamp, n_cl_cyc);
        if (n_cfg < 10 || n_clamp < 10) err("configuration / clamp not covered");
        if (n_under_seen == 0) err("no underrun covered");
        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d errors", errors);
        $finish;
    end

endmodule
