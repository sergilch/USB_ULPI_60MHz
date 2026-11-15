//-----------------------------------------------------------------------------
// tb_usb_rx_hs_reset.v - clk_rx island reset release (Plan_60MHz.md P9)
//
//   iverilog -g2005 -o sim_rx_hs_reset usb_rx_hs_frontend.v usb_rx_hs_sipo.v \
//            usb_afe_rx_if.v tb_usb_rx_hs_reset.v
//   vvp sim_rx_hs_reset
//
// usb_rx_hs_sipo and usb_afe_rx_if split their clk_rx reset into a fast copy
// rst_rx_n and a multicycle copy rst_rx_m_n (2-cycle recovery in the SDC).
// The claim: every flop on rst_rx_m_n has D = its reset value at the first
// clk_rx edge after the release, so a release that lands one edge late
// changes nothing.  This bench runs each island twice, the second copy with
// rst_rx_m_n (usb_afe_rx_if: also its copy rst_rx_m2_n) forced to release
// one clk_rx edge after its rst_rx_n, and
// requires identical outputs (===, including X of the unreset data flops) on
// every clk_rx edge.  rst_n is asserted and released many times at random
// times (asynchronously to clk_rx) while the inputs are active: squelch low,
// lock and enable high, random data, random w_full, random iso_en / settings
// changes between resets, so a flop whose D differs from its reset value at
// the release edge shows up as a mismatch.
// Also checked: the late release really happened (rst_rx_m_n of the two
// copies differ in at least one cycle per reset), and words were written.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_usb_rx_hs_reset;

    parameter integer NRST = 400;               // reset cycles

    reg clk_rx = 1'b0;
    always #1.0415 clk_rx = ~clk_rx;
    reg clk60 = 1'b0;
    always #8.333 clk60 = ~clk60;

    reg rst_n = 1'b0;
    reg rxd = 1'b1, squelch = 1'b1, cdr_lock = 1'b0, enable = 1'b1, w_full = 1'b0;
    reg iso_en = 1'b0;
    reg [2:0] lock_dly = 3'd2, sq_comp = 3'd0;
    integer seed = 32'h5E7_0F11;
    integer errors = 0;

    // ---------------- usb_rx_hs_sipo: normal and late copy ----------------
    wire        cw_n, we_n, wr_n, cw_l, we_l, wr_l;
    wire [15:0] wd_n, wd_l;
    usb_rx_hs_sipo u_sn (.clk_rx(clk_rx), .rst_n(rst_n), .rxd(rxd), .squelch(squelch),
        .cdr_lock(cdr_lock), .enable(enable), .clk_rxw(cw_n), .w_en(we_n), .w_data(wd_n),
        .w_full(w_full), .w_rst_n(wr_n));
    usb_rx_hs_sipo u_sl (.clk_rx(clk_rx), .rst_n(rst_n), .rxd(rxd), .squelch(squelch),
        .cdr_lock(cdr_lock), .enable(enable), .clk_rxw(cw_l), .w_en(we_l), .w_data(wd_l),
        .w_full(w_full), .w_rst_n(wr_l));

    // ---------------- usb_afe_rx_if: normal and late copy ----------------
    wire en_n, ce_n, d_n, sq_n, lk_n, en_l, ce_l, d_l, sq_l, lk_l;
    usb_afe_rx_if u_an (.clk60(clk60), .rst_n(rst_n), .speed(2'b00), .rx_en(1'b1), .iso_en(iso_en),
        .lock_dly(lock_dly), .sq_comp(sq_comp), .rx_en_hs(en_n), .cdr_en(ce_n),
        .clk_rx(clk_rx), .hs_rxd_a(rxd), .squelch_a(squelch),
        .hs_rxd(d_n), .hs_squelch(sq_n), .hs_cdr_lock(lk_n));
    usb_afe_rx_if u_al (.clk60(clk60), .rst_n(rst_n), .speed(2'b00), .rx_en(1'b1), .iso_en(iso_en),
        .lock_dly(lock_dly), .sq_comp(sq_comp), .rx_en_hs(en_l), .cdr_en(ce_l),
        .clk_rx(clk_rx), .hs_rxd_a(rxd), .squelch_a(squelch),
        .hs_rxd(d_l), .hs_squelch(sq_l), .hs_cdr_lock(lk_l));

    // late release: rst_rx_m_n of the second copies follows their rst_rx_n one
    // clk_rx edge later (assert stays asynchronous)
    reg late_s = 1'b0, late_a = 1'b0;
    always @(posedge clk_rx or negedge rst_n)
        if (!rst_n) late_s <= 1'b0; else late_s <= u_sl.rst_rx_n;
    always @(posedge clk_rx or negedge rst_n)
        if (!rst_n) late_a <= 1'b0; else late_a <= u_al.rst_rx_n;
    initial begin
        force u_sl.rst_rx_m_n = late_s;
        force u_al.rst_rx_m_n = late_a;
        force u_al.rst_rx_m2_n = late_a;
    end

    // ---------------- compare on every clk_rx edge ----------------
    integer ncmp = 0, nlate_s = 0, nlate_a = 0, nwr = 0;
    always @(negedge clk_rx) begin
        ncmp = ncmp + 1;
        if ({cw_n, we_n, wd_n, wr_n} !== {cw_l, we_l, wd_l, wr_l}) begin
            errors = errors + 1;
            if (errors <= 20) $display("ERROR @%0t: hs_sipo late copy differs: clk_rxw %b/%b w_en %b/%b w_data %h/%h",
                                       $time, cw_n, cw_l, we_n, we_l, wd_n, wd_l);
        end
        if ({en_n, ce_n, d_n, sq_n, lk_n} !== {en_l, ce_l, d_l, sq_l, lk_l}) begin
            errors = errors + 1;
            if (errors <= 20) $display("ERROR @%0t: afe_rx_if late copy differs: %b%b%b%b%b / %b%b%b%b%b",
                                       $time, en_n, ce_n, d_n, sq_n, lk_n, en_l, ce_l, d_l, sq_l, lk_l);
        end
        if (u_sn.rst_rx_m_n !== u_sl.rst_rx_m_n) nlate_s = nlate_s + 1;
        if (u_an.rst_rx_m_n !== u_al.rst_rx_m_n) nlate_a = nlate_a + 1;
        if (we_n && !w_full && wd_n[15:8] != 8'h00) nwr = nwr + 1;
    end

    // ---------------- stimulus ----------------
    // inputs change on the falling clk_rx edge (setup to the rising one);
    // mostly active so that the release edge sees non-reset D values upstream
    always @(negedge clk_rx) begin
        rxd      <= $random(seed);
        squelch  <= ({$random(seed)} % 64) == 0;
        cdr_lock <= ({$random(seed)} % 64) != 0;
        enable   <= ({$random(seed)} % 128) != 0;
        w_full   <= ({$random(seed)} % 16) == 0;
    end

    integer r;
    initial begin
        $dumpfile("tb_usb_rx_hs_reset.vcd");
        $dumpvars(0, tb_usb_rx_hs_reset);
        for (r = 0; r < NRST; r = r + 1) begin
            // reset: random length and phase, settings may change only here
            rst_n = 1'b0;
            #(1.0 + ({$random(seed)} % 10000) / 1000.0);
            iso_en   = ({$random(seed)} % 8) == 0;
            lock_dly = $random(seed);
            sq_comp  = {$random(seed)} % 3;
            #(3.0 + ({$random(seed)} % 10000) / 1000.0);
            rst_n = 1'b1;                       // asynchronous to clk_rx
            #(40.0 + ({$random(seed)} % 400000) / 1000.0);
        end
        #50;
        if (nlate_s < NRST || nlate_a < NRST) begin
            errors = errors + 1;
            $display("ERROR: late release not exercised (%0d / %0d cycles, %0d resets)", nlate_s, nlate_a, NRST);
        end
        if (nwr < 10 * NRST) begin
            errors = errors + 1;
            $display("ERROR: too few active words written (%0d)", nwr);
        end
        $display("resets %0d, edges compared %0d, active words %0d, late-release cycles %0d / %0d",
                 NRST, ncmp, nwr, nlate_s, nlate_a);
        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d errors", errors);
        $finish;
    end

endmodule
