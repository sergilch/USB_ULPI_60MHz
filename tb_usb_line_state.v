//-----------------------------------------------------------------------------
// tb_usb_line_state.v - unit testbench for usb_line_state
//
// Run (Icarus Verilog):
//   iverilog -g2005 -o sim_line_state usb_line_state.v tb_usb_line_state.v
//   vvp sim_line_state
//
// The inputs are the receiver samples (clk60 domain, as from usb_rx_datapath)
// and squelch / disconnect / hs_tx_act (clk_bit domain), all driven on the
// falling clk_bit edge.  clk60 / ld are generated as in the ULPI testbenches
// (clk60 rises with a blocking assignment on the edge where ce60 was high).
//
// LineState reference, rebuilt from the spec rather than from the DUT's
// counter: per clk60 tick n the testbench computes the raw state r[n] from the
// inputs the DUT sees at that edge (FS / LS {D-, D+}; HS squelch ? 00 : 01;
// chirp squelch ? 00 : rxrcv ? 01 : 10, squelch as taken on the last ld edge),
// keeps the tick history, and expects
//   linestate[n] = r[n]            if r[n] is J / K in FS / LS, or in HS mode,
//                = r[n]            if r[n-N+1 .. n] are all equal (N = 2 FS SE0 /
//                                  SE1, 14 LS SE0 / SE1, 2 chirp),
//                = linestate[n-1]  otherwise.
// It is checked after every clk_bit edge (so linestate may change on clk60
// edges only).  Phases:
//   1. random FS line: J / K bits with SE0 / SE1 skew glitches of 1-12 cycles
//      at the crossovers, real SE0 (EOP) of 2 bits, SE1 bursts;
//   2. the same at LS (glitches up to 120 cycles = 15 ticks) and XcvrSelect 11
//      (FS filter);
//   3. HS: random squelch with rxdp / rxdm / rxrcv noise that must not show;
//   4. chirp (OpMode 10): K / J chirps with squelch gaps and 1-tick rxrcv
//      glitches;
//   5. random mode changes on top of random inputs.
// Also directed: an FS EOP (J, SE0 2 bits, J) must read J, SE0, J with the SE0
// 2 ticks late at most and both J changes at most 1 tick late; a 15-cycle FS
// skew glitch (2 ticks possible) is allowed to show; LS SE0 of 14 ticks shows.
//
// HostDisconnect (tick resolution, DISC_TAIL = 4 ticks): hs_tx_act windows with
// disc pulses before, inside, in the tail and after the window; host_mode /
// OpMode / XcvrSelect gating; result taken over on the first tick after the
// window closes and held until the next window; cleared when the port leaves HS
// host mode.  The reference ORs disc / hs_tx_act per tick as the DUT's island.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_usb_line_state;
    parameter real HALF = 1.0416667;
    localparam TAIL   = 32;           // stimulus: clk_bit cycles of the window tail
    localparam TAIL_T = TAIL / 8;     // DUT / reference: ticks

    integer errors = 0;
    integer seed   = 32'h11E5_7A7E;

    reg clk_bit = 1'b0;
    always #(HALF) clk_bit = ~clk_bit;
    reg rst_n = 1'b0;
    reg [2:0] ce_cnt = 3'd0;
    wire ce60 = (ce_cnt == 3'd7);
    always @(posedge clk_bit) ce_cnt <= ce_cnt + 3'd1;
    reg  clk60 = 1'b0;
    always @(posedge clk_bit) begin
        if (ce_cnt == 3'd7)      clk60 = 1'b1;
        else if (ce_cnt == 3'd3) clk60 = 1'b0;
    end
    wire ld = (ce_cnt == 3'd3);

    reg       dp = 1'b0, dm = 1'b0, rcv = 1'b1, sq = 1'b1, disc = 1'b0;
    reg [1:0] xs = 2'b01, om = 2'b00;
    reg       host = 1'b0, txa = 1'b0;
    wire [1:0] ls;
    wire       hd;

    usb_line_state #(.DISC_TAIL(TAIL_T)) dut (
        .clk_bit(clk_bit), .rst_n(rst_n), .clk60(clk60), .ld(ld),
        .rxdp_s(dp), .rxdm_s(dm), .rxrcv_s(rcv), .squelch_s(sq), .disc_s(disc),
        .xcvrselect(xs), .opmode(om), .host_mode(host), .hs_tx_act(txa),
        .linestate(ls), .host_disc(hd));

    initial begin
        $dumpfile("tb_usb_line_state.vcd");
        $dumpvars(0, tb_usb_line_state);
    end

    // ---------------- LineState reference ----------------
    reg [1:0] rh [0:15];              // raw per tick, rh[0] newest
    reg [1:0] exp_ls = 2'b00;
    reg [1:0] r;
    reg       ce_q = 1'b0, ld_q = 1'b0;
    always @(negedge clk_bit) begin ce_q <= (ce_cnt == 3'd7); ld_q <= (ce_cnt == 3'd3); end
    reg       sq_ld = 1'b1;           // squelch as taken by the DUT on ld
    integer i, N;
    reg     same, jk;
    integer nchg = 0;                 // linestate changes seen

    initial for (i = 0; i < 16; i = i + 1) rh[i] = 2'b00;

    always @(posedge clk_bit) begin
        if (!rst_n) begin
            for (i = 0; i < 16; i = i + 1) rh[i] = 2'b00;
            exp_ls = 2'b00;
            sq_ld  = 1'b1;
        end else if (ld_q) begin
            sq_ld = sq;
        end else if (ce_q) begin
            if (xs == 2'b00 && om == 2'b10) r = sq_ld ? 2'b00 : (rcv ? 2'b01 : 2'b10);
            else if (xs == 2'b00)           r = sq_ld ? 2'b00 : 2'b01;
            else                            r = {dm, dp};
            for (i = 15; i > 0; i = i - 1) rh[i] = rh[i-1];
            rh[0] = r;
            jk = (r == 2'b01) || (r == 2'b10);
            if (xs == 2'b00 && om == 2'b10) N = 2;
            else if (xs == 2'b00)           N = 1;
            else if (jk)                    N = 1;
            else if (xs == 2'b10)           N = 14;
            else                            N = 2;
            same = 1;
            for (i = 1; i < N; i = i + 1) if (rh[i] != r) same = 0;
            if (same) exp_ls = r;
        end
        #0.1;
        if (ls !== exp_ls) begin
            errors = errors + 1;
            if (errors < 20)
                $display("ERROR @%0t: linestate %b, expected %b (xs %b om %b)",
                         $time, ls, exp_ls, xs, om);
            exp_ls = ls;
        end
    end

    reg [1:0] ls_q = 2'b00;
    always @(posedge clk_bit) begin
        #0.2;
        if (ls !== ls_q) nchg = nchg + 1;
        ls_q = ls;
    end

    // ---------------- HostDisconnect reference ----------------
    // per tick: disc / txa ORed over the clk_bit edges up to and including the
    // ld edge; at the next clk60 edge: first take over a result that was ready
    // (window closed on an earlier tick), then the window: opened / extended by
    // a tick with txa, closed TAIL_T ticks after the last one; result = disc in
    // any tick of the window.
    reg     exp_hd = 1'b0, w_open = 1'b0, w_acc = 1'b0, w_res = 1'b0, w_done = 1'b0;
    reg     d_a = 1'b0, t_a = 1'b0, d_t = 1'b0, t_t = 1'b0;
    integer w_tail = 0;
    wire    dmode = host && (xs == 2'b00) && (om == 2'b00);

    always @(posedge clk_bit) begin
        if (!rst_n) begin
            exp_hd = 0; w_open = 0; w_acc = 0; w_done = 0;
            d_a = 0; t_a = 0; d_t = 0; t_t = 0;
        end else begin
            if (ld_q) begin
                d_t = d_a | disc; t_t = t_a | txa; d_a = 0; t_a = 0;
            end else begin
                d_a = d_a | disc; t_a = t_a | txa;
            end
            if (ce_q) begin
                if (!dmode) begin
                    exp_hd = 0; w_open = 0; w_acc = 0; w_done = 0;
                end else begin
                    if (w_done) begin exp_hd = w_res; w_done = 0; end
                    if (t_t) begin
                        w_acc  = w_open ? (w_acc | d_t) : d_t;
                        w_open = 1; w_tail = TAIL_T;
                    end else if (w_open) begin
                        w_acc  = w_acc | d_t;
                        if (w_tail <= 1) begin w_open = 0; w_res = w_acc; w_done = 1; end
                        w_tail = w_tail - 1;
                    end
                end
            end
        end
        #0.1;
        if (hd !== exp_hd) begin
            errors = errors + 1;
            $display("ERROR @%0t: host_disc %b, expected %b", $time, hd, exp_hd);
            exp_hd = hd;
        end
    end

    // ---------------- stimulus helpers ----------------
    task cyc(input integer n);
        begin repeat (n) @(negedge clk_bit); end
    endtask

    task set_line(input [1:0] v);          // {dm, dp}
        begin dm = v[1]; dp = v[0]; end
    endtask

    // one FS / LS bit of level v (J / K) lasting P cycles, with a skew glitch
    // of g cycles (SE0 or SE1) at its start
    task bit_glitch(input [1:0] v, input integer P, input integer g);
        begin
            if (g > 0) begin
                set_line(({$random(seed)} % 2) ? 2'b11 : 2'b00);
                cyc(g);
            end
            set_line(v);
            cyc(P - g);
        end
    endtask

    task random_fsls(input integer nbits, input integer P, input integer gmax);
        integer n, g;
        reg [1:0] v;
        begin
            v = 2'b01;
            for (n = 0; n < nbits; n = n + 1) begin
                case ({$random(seed)} % 16)
                    0:       begin set_line(2'b00); cyc(2 * P); end         // EOP SE0
                    1:       begin set_line(2'b11); cyc(1 + {$random(seed)} % (2 * P)); end
                    default: begin
                        if ({$random(seed)} % 2) v = ~v;
                        g = (gmax > 0) ? ({$random(seed)} % (gmax + 1)) : 0;
                        bit_glitch(v, P, g);
                    end
                endcase
            end
        end
    endtask

    // ---------------- directed FS EOP latency ----------------
    real t_se0, t_j, t_ls_se0, t_ls_j;
    task fs_eop_check;
        begin
            xs = 2'b01; om = 2'b00; sq = 1'b1;
            set_line(2'b10); cyc(200);              // K
            set_line(2'b01); cyc(200);              // J
            set_line(2'b00); t_se0 = $realtime;     // SE0, 2 FS bits
            @(posedge clk_bit or negedge clk_bit);
            wait (ls == 2'b00); t_ls_se0 = $realtime;
            cyc(80 - 1);
            set_line(2'b01); t_j = $realtime;
            wait (ls == 2'b01); t_ls_j = $realtime;
            if (t_ls_se0 - t_se0 > 2.0 * 8 * 2 * HALF + 0.5 || t_ls_se0 < t_se0) begin
                errors = errors + 1;
                $display("ERROR: FS SE0 shown %.2f ns after the line (max 2 ticks)",
                         t_ls_se0 - t_se0);
            end
            if (t_ls_j - t_j > 8 * 2 * HALF + 0.5) begin
                errors = errors + 1;
                $display("ERROR: FS J after EOP shown %.2f ns after the line (max 1 tick)",
                         t_ls_j - t_j);
            end
            cyc(100);
        end
    endtask

    // ---------------- sequence ----------------
    integer k, n_hd_set;
    initial begin
        cyc(5);
        if (ls !== 2'b00 || hd !== 1'b0) begin
            errors = errors + 1; $display("ERROR: reset values ls %b hd %b", ls, hd);
        end
        rst_n = 1'b1;
        cyc(20);

        // 1. FS
        xs = 2'b01;
        random_fsls(600, 40, 12);
        fs_eop_check;
        // a 15-cycle SE0 glitch may show (it can cover two ticks); the
        // reference decides from the ticks
        set_line(2'b01); cyc(40); set_line(2'b00); cyc(15); set_line(2'b10); cyc(40);
        // 2. LS and XcvrSelect 11
        xs = 2'b10;
        random_fsls(150, 320, 120);
        set_line(2'b10); cyc(400); set_line(2'b00); cyc(14 * 8 + 3); set_line(2'b10); cyc(400);
        if (nchg == 0) begin errors = errors + 1; $display("ERROR: linestate never changed"); end
        xs = 2'b11;
        random_fsls(300, 40, 12);
        // 3. HS: squelch only
        xs = 2'b00; om = 2'b00;
        for (k = 0; k < 400; k = k + 1) begin
            sq = {$random(seed)} % 2;
            {dm, dp, rcv} = $random(seed);
            cyc(1 + {$random(seed)} % 40);
        end
        // 4. chirp
        om = 2'b10;
        for (k = 0; k < 300; k = k + 1) begin
            case ({$random(seed)} % 6)
                0: begin sq = 1; cyc(1 + {$random(seed)} % 40); end
                1: begin sq = 0; rcv = ~rcv; cyc(1 + {$random(seed)} % 8); rcv = ~rcv; end
                default: begin sq = 0; rcv = {$random(seed)} % 2; cyc(20 + {$random(seed)} % 200); end
            endcase
            {dm, dp} = $random(seed);
        end
        // 5. random modes
        for (k = 0; k < 600; k = k + 1) begin
            if ({$random(seed)} % 8 == 0) begin xs = $random(seed); om = $random(seed); end
            {dm, dp, rcv, sq} = $random(seed);
            cyc(1 + {$random(seed)} % 100);
        end

        // ---------------- HostDisconnect ----------------
        xs = 2'b00; om = 2'b00; sq = 1'b1; host = 1'b1; disc = 0; txa = 0;
        cyc(50);
        // disc inside the window
        txa = 1; cyc(100); disc = 1; cyc(5); disc = 0; cyc(100); txa = 0; cyc(TAIL + 20);
        if (hd !== 1'b1) begin errors = errors + 1; $display("ERROR: disconnect inside the window not reported"); end
        // clean window clears it
        txa = 1; cyc(300); txa = 0; cyc(TAIL + 20);
        if (hd !== 1'b0) begin errors = errors + 1; $display("ERROR: clean window did not clear host_disc"); end
        // disc in the tail (late detector)
        txa = 1; cyc(80); txa = 0; cyc(TAIL - 4); disc = 1; cyc(2); disc = 0; cyc(40);
        if (hd !== 1'b1) begin errors = errors + 1; $display("ERROR: disconnect in the tail not reported"); end
        // (the window ends 24..32 clk_bit cycles after hs_tx_act falls, by tick alignment)
        // disc for one cycle late in the tail
        txa = 1; cyc(80); txa = 0; cyc(TAIL + 20);
        txa = 1; cyc(80); txa = 0; cyc(TAIL - 8); disc = 1; cyc(1); disc = 0; cyc(40);
        if (hd !== 1'b1) begin errors = errors + 1; $display("ERROR: disconnect late in the tail not reported"); end
        // disc one tick after the latest window end: ignored
        txa = 1; cyc(80); txa = 0; cyc(TAIL + 8); disc = 1; cyc(1); disc = 0; cyc(40);
        if (hd !== 1'b0) begin errors = errors + 1; $display("ERROR: disconnect after the window reported"); end
        // disc after the window: ignored; held until the next window
        txa = 1; cyc(80); txa = 0; cyc(TAIL + 10); disc = 1; cyc(20); disc = 0; cyc(20);
        if (hd !== 1'b0) begin errors = errors + 1; $display("ERROR: disconnect outside the window reported"); end
        // set, then not in host mode: cleared, and no detection
        txa = 1; disc = 1; cyc(50); disc = 0; txa = 0; cyc(TAIL + 20);
        host = 0; cyc(20);
        if (hd !== 1'b0) begin errors = errors + 1; $display("ERROR: host_disc not cleared outside host mode"); end
        txa = 1; disc = 1; cyc(50); disc = 0; txa = 0; cyc(TAIL + 20);
        if (hd !== 1'b0) begin errors = errors + 1; $display("ERROR: host_disc set in device mode"); end
        // chirp (OpMode 10) and FS: no detection
        host = 1; om = 2'b10;
        txa = 1; disc = 1; cyc(50); disc = 0; txa = 0; cyc(TAIL + 20);
        om = 2'b00; xs = 2'b01;
        txa = 1; disc = 1; cyc(50); disc = 0; txa = 0; cyc(TAIL + 20);
        if (hd !== 1'b0) begin errors = errors + 1; $display("ERROR: host_disc set in chirp / FS"); end
        // random windows and pulses, checked by the reference
        xs = 2'b00;
        for (k = 0; k < 300; k = k + 1) begin
            txa  = {$random(seed)} % 2;
            disc = ({$random(seed)} % 10) == 0;
            if ({$random(seed)} % 50 == 0) host = ~host;
            cyc(1 + {$random(seed)} % (2 * TAIL));
        end
        txa = 0; disc = 0; host = 1;
        cyc(2 * TAIL);
        // reset in the middle
        txa = 1; disc = 1; cyc(30);
        rst_n = 0; cyc(3); rst_n = 1; disc = 0; cyc(30); txa = 0; cyc(TAIL + 20);

        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d error(s)", errors);
        $finish;
    end

    initial begin
        #5000000;
        $display("TEST FAILED: timeout");
        $finish;
    end
endmodule
