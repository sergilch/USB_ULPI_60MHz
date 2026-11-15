//-----------------------------------------------------------------------------
// tb_usb_rx_hs_sipo.v - unit test of the HS receive island (Plan_60MHz.md P5)
//
//   iverilog -g2005 -o sim_rx_hs_sipo usb_rx_hs_frontend.v usb_rx_hs_sipo.v \
//            tb_usb_rx_hs_sipo.v
//   vvp sim_rx_hs_sipo
//
// Drives random data, squelch and lock (bursts of active bits, idle gaps,
// glitches) on clk_rx and plays the word FIFO's write side: w_full is random
// in some phases.  Checked:
//   * every word offered on clk_rxw is 8 consecutive {b_lvl, b_act} bits of
//     the front end, in order (slot 0 oldest), with no bit skipped or doubled
//     (reference: the front end's outputs, recorded per clk_rx cycle);
//   * write rule: a word is offered (w_en) iff it has an active bit, or the
//     previous one had, or a word was lost; a lost word (w_en while w_full) is
//     followed by an all-inactive word at the next accepted write;
//   * boundary rule: the word register changes only 4 clk_rx cycles after a
//     clk_rxw rising edge (never within 3 cycles in front of one), and clk_rxw
//     has period 8.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_usb_rx_hs_sipo;

    parameter integer NCYC = 200000;           // clk_rx cycles

    reg clk_rx = 1'b0;
    always #1.0415 clk_rx = ~clk_rx;

    reg rst_n = 1'b0;
    reg rxd = 1'b1, squelch = 1'b1, cdr_lock = 1'b0, enable = 1'b1;
    reg w_full = 1'b0;

    wire        clk_rxw, w_en, w_rst_n;
    wire [15:0] w_data;

    usb_rx_hs_sipo dut (
        .clk_rx (clk_rx), .rst_n (rst_n),
        .rxd (rxd), .squelch (squelch), .cdr_lock (cdr_lock), .enable (enable),
        .clk_rxw (clk_rxw), .w_en (w_en), .w_data (w_data), .w_full (w_full),
        .w_rst_n (w_rst_n));

    integer errors = 0;
    task err(input [8*64-1:0] msg);
        begin
            errors = errors + 1;
            if (errors <= 20) $display("ERROR @%0t: %0s", $time, msg);
        end
    endtask

    // ---------------- reference bit stream (front end outputs) ----------------
    localparam integer QL = 1 << 20;
    reg [1:0] bq [0:QL-1];                     // {act, lvl}
    integer   nb = 0;                          // bits recorded
    always @(posedge clk_rx)
        if (dut.rst_rx_n) begin
            bq[nb % QL] = {dut.hb_act & dut.hb_en, dut.hb_lvl};
            nb = nb + 1;
        end

    // ---------------- stimulus ----------------
    integer seed = 32'h51F0;
    function integer rnd(input integer n);
        rnd = $unsigned($random(seed)) % n;
    endfunction

    integer run = 0, mode = 0;
    always @(posedge clk_rx) begin
        rxd <= #0.2 $random(seed);
        if (run == 0) begin
            mode = rnd(10);
            case (mode)
                0, 1, 2, 3: begin run = 20 + rnd(400); squelch <= #0.3 1'b0; cdr_lock <= #0.3 1'b1; end
                4, 5:       begin run = 1 + rnd(40);   squelch <= #0.3 1'b1; cdr_lock <= #0.3 1'b0; end
                6:          begin run = 1 + rnd(4);    squelch <= #0.3 rnd(2); cdr_lock <= #0.3 rnd(2); end
                7:          begin run = 1 + rnd(30);   squelch <= #0.3 1'b0; cdr_lock <= #0.3 1'b0; end
                8:          begin run = 5 + rnd(60);   enable  <= #0.3 rnd(4) != 0; end
                default:    begin run = 1 + rnd(16);   squelch <= #0.3 rnd(2); end
            endcase
        end else
            run = run - 1;
    end

    // backpressure phases (clk_rxw domain)
    integer fphase = 0, frun = 0;
    always @(negedge clk_rxw) begin
        if (frun == 0) begin fphase = rnd(4); frun = 10 + rnd(200); end
        else frun = frun - 1;
        w_full = (fphase == 0) ? (rnd(3) == 0) : 1'b0;
    end

    // ---------------- checks ----------------
    // boundary rule: last time the word register changed (any delta)
    realtime t_wchg = 0, t_rise = 0, t_now;
    // boundary rule, both sides: the word changes 4 clk_rx cycles after a
    // clk_rxw rise (E4), never on or near the rise itself
    always @(dut.ac_w or dut.lv_w) begin
        t_wchg = $realtime;
        if (t_rise > 0 && w_rst_n && (($realtime - t_rise) < 3.5 * 2.083 || ($realtime - t_rise) > 4.5 * 2.083))
            err("word register changed away from E4 (4 clk_rx after the clk_rxw rise)");
    end

    integer   rd = -1;                         // bit index of slot 0 of the next word
    integer   n_w = 0, n_wr = 0, n_lost = 0, n_drop_w = 0, n_skip = 0, i;
    reg       prev_act = 1'b0, lost = 1'b0;
    reg [15:0] wd;
    // values sampled at the edge; the boundary check a little after it, so a
    // word change on the edge itself is seen
    reg        s_en, s_full;
    reg [15:0] s_data;
    always @(posedge clk_rxw) if (w_rst_n) begin
        t_now = $realtime;
        wd = {dut.ac_w, dut.lv_w}; s_en = w_en; s_full = w_full; s_data = w_data;
        #0.05;
        if (t_rise > 0 && (t_now - t_rise < 16.6 || t_now - t_rise > 16.7)) err("clk_rxw period is not 8 clk_rx");
        if (t_now - t_wchg < 3 * 2.083 - 0.1) err("word register changed less than 3 cycles before clk_rxw");
        t_rise = t_now;
        // align: the first word decides the offset; afterwards exactly 8 bits per word
        if (rd < 0) begin
            for (i = 0; i <= nb - 8; i = i + 1)
                if (rd < 0 && {bq[i+7][0], bq[i+6][0], bq[i+5][0], bq[i+4][0], bq[i+3][0], bq[i+2][0], bq[i+1][0], bq[i][0]} == wd[7:0] &&
                    {bq[i+7][1], bq[i+6][1], bq[i+5][1], bq[i+4][1], bq[i+3][1], bq[i+2][1], bq[i+1][1], bq[i][1]} == wd[15:8] &&
                    (nb - i - 8) <= 8 && (nb - i - 8) >= 0)
                    rd = i;
            if (rd < 0) err("first word does not match the bit stream");
        end
        if (rd >= 0) begin
            for (i = 0; i < 8; i = i + 1)
                if (wd[i] !== bq[(rd + i) % QL][0] || wd[8 + i] !== bq[(rd + i) % QL][1]) begin
                    err("word differs from the front end bits");
                    i = 8;
                end
            rd = rd + 8;
        end
        n_w = n_w + 1;
        // write rule
        if (s_en !== ((|wd[15:8]) || prev_act || lost)) err("w_en does not follow the write rule");
        if (s_en && !s_full) begin
            n_wr = n_wr + 1;
            if (lost) begin
                if (s_data !== 16'h00FF) err("no all-inactive word after a lost word");
                n_drop_w = n_drop_w + 1;
            end else if (s_data !== wd) err("w_data differs from the word");
            lost = 1'b0;
        end else if (s_en && s_full) begin
            n_lost = n_lost + 1;
            lost = 1'b1;
        end else
            n_skip = n_skip + 1;
        prev_act = |wd[15:8];
    end

    initial begin
        if ($value$plusargs("seed=%d", seed)) $display("seed %0d", seed);
        #20 rst_n = 1'b1;
        repeat (NCYC) @(posedge clk_rx);
        if (n_lost == 0 || n_drop_w == 0) err("no lost word / inactive replacement covered");
        if (n_skip == 0) err("no idle word skipped");
        $display("%0d words: %0d written, %0d idle skipped, %0d lost (%0d inactive replacements)",
                 n_w, n_wr, n_skip, n_lost, n_drop_w);
        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d errors", errors);
        $finish;
    end

endmodule
