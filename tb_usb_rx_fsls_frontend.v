//-----------------------------------------------------------------------------
// tb_usb_rx_fsls_frontend.v - self-checking testbench for the FS/LS receive
//                              front end usb_rx_fsls_sampler + usb_rx_fsls_dpll
//                              (Plan_60MHz.md P4)
//
// Run (Icarus Verilog):
//   iverilog -g2005 -o sim_rxfsfe usb_rx_fsls_sampler.v usb_rx_fsls_dpll.v \
//            ref_rx_fsls_frontend.v tb_usb_rx_fsls_frontend.v
//   vvp sim_rxfsfe
//
// DUT: usb_rx_fsls_sampler (clk_bit island, word on ld) -> usb_rx_fsls_dpll
// (clk60).  Reference: the single-clock ref_rx_fsls_frontend on the same pins;
// the DUT must strobe the same symbols in the same order (same samples, same
// DPLL rule), at most one per tick.
//
// The testbench drives D+ / D- / rxrcv with symbol frames at the FS or LS bit
// rate of a far clock with a ppm offset: idle J, then a frame that starts with
// K, random J/K runs of 1..7 bits (bit stuffing limits runs to 7), optional SE0
// pairs, and the EOP SE0 SE0 J, then idle again.  D- lags D+ by a random skew
// (SE0 / SE1 glitches at the crossovers), rxrcv switches half-way.  LS uses
// the inverted polarity (J = D- high).  Checked:
//   * the strobed symbols (b_en with b_lvl / b_se0) reproduce every frame bit
//     for bit: the first K after idle starts the comparison, each frame symbol
//     is sampled exactly once and in order, idle bits are J;
//   * about one strobe per bit time on an idle line;
//   * b_act follows enable.
//   FS at 0 / +2500 / -2500 ppm, LS at 0 / +15000 / -15000 ppm.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_usb_rx_fsls_frontend;

    parameter real    HALF   = 1.0416667;
    parameter integer FS_DIV = 40;
    parameter integer LS_DIV = 320;

    reg clk = 1'b0;                           // clk_bit
    always #(HALF) clk = ~clk;
    reg rst_n;

    // clk60 / ld as in the ULPI testbenches: clk60 rises (blocking) on the
    // clk_bit edge where phase 7 ends (E0), ld = phase 3
    reg [2:0] ce_cnt = 3'd0;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) ce_cnt <= 3'd0;
        else        ce_cnt <= ce_cnt + 3'd1;
    reg  clk60 = 1'b0;
    always @(posedge clk) begin
        if (ce_cnt == 3'd7)      clk60 = 1'b1;
        else if (ce_cnt == 3'd3) clk60 = 1'b0;
    end
    wire ld = (ce_cnt == 3'd3);

    reg  ls = 1'b0, enable = 1'b1;
    reg  dp = 1'b1, dm = 1'b0, rcv = 1'b1;    // after skew
    wire b_en, b_lvl, b_se0, b_act;

    wire [7:0] rcv_v, dp_v, dm_v;

    usb_rx_fsls_sampler u_smp (
        .clk_bit (clk), .rst_n (rst_n), .ld (ld),
        .rxrcv (rcv), .rxdp (dp), .rxdm (dm),
        .rcv_v (rcv_v), .dp_v (dp_v), .dm_v (dm_v)
    );

    usb_rx_fsls_dpll #(.FS_DIV(FS_DIV), .LS_DIV(LS_DIV), .DIV_W(9)) dut (
        .clk60 (clk60), .rst_n (rst_n),
        .rcv_v (rcv_v), .dp_v (dp_v), .dm_v (dm_v), .ls (ls), .enable (enable),
        .b_en (b_en), .b_lvl (b_lvl), .b_se0 (b_se0), .b_act (b_act)
    );

    // reference: the single-clock front end
    wire r_en, r_lvl, r_se0, r_act;
    ref_rx_fsls_frontend #(.FS_DIV(FS_DIV), .LS_DIV(LS_DIV), .DIV_W(9)) u_ref (
        .clk (clk), .rst_n (rst_n),
        .rxrcv (rcv), .rxdp (dp), .rxdm (dm), .ls (ls), .enable (enable),
        .b_en (r_en), .b_lvl (r_lvl), .b_se0 (r_se0), .b_act (r_act)
    );

    integer errors = 0;
    integer seed   = 32'h0F5F_15AA;

    // ---------------- line driver ----------------
    real    bit_ns = 83.333;
    real    skew   = 0.0;
    reg [1:0] sym = 2'd1;                     // 0 K, 1 J, 2 SE0 (as driven, before skew)

    // J: FS D+ high, LS D- high
    wire dp_raw = (sym == 2'd2) ? 1'b0 : ((sym == 2'd1) ^ ls);
    wire dm_raw = (sym == 2'd2) ? 1'b0 : !((sym == 2'd1) ^ ls);
    always @(dp_raw) dp  <= #(0.3) dp_raw;
    always @(dm_raw) dm  <= #(0.3 + skew) dm_raw;
    always @(dp_raw) rcv <= #(0.3 + skew / 2.0) dp_raw;

    // ---------------- expected frames ----------------
    reg [1:0] f_sym [0:65535];
    integer   f_w = 0;                        // symbols queued (all frames)
    integer   f_start [0:4095];
    integer   f_len   [0:4095];
    integer   nf = 0, cf = 0;                 // frames queued / being checked

    // ---------------- strobe checker ----------------
    integer ck_i = -1;                        // index in the current frame, -1 = waiting for K
    integer strobes = 0, sym_ok = 0;

    reg [31:0] en_hist = 32'hFFFF_FFFF;
    always @(posedge clk) en_hist <= {en_hist[30:0], enable};

    // reference strobes, matched in order by the DUT's
    reg [1:0] rq [0:1023];
    integer   rq_w = 0, rq_r = 0, ref_ok = 0;
    // Strobe timing: the DUT pipeline is fixed, so its strobe lags the
    // reference's by 20 .. 27 clk_bit cycles, by the tick phase only (sampler
    // shift + wait for ld + E4 -> E0 + DPLL input register + output register).
    // A strobe one sample early or late moves one phase into the previous /
    // next tick, i.e. the window to 19 .. 26 or 21 .. 28.
    real      rt [0:1023];
    real      lag_min = 1.0e9, lag_max = 0.0;
    reg       ign = 1'b0;             // speed change: compare nothing (mode_quiet)
    always @(posedge clk)
        if (rst_n && r_en && !ign) begin rq[rq_w % 1024] = {r_lvl, r_se0}; rt[rq_w % 1024] = $realtime; rq_w = rq_w + 1; end

    always @(posedge clk60) begin
        if (rst_n && b_en && !ign) begin
            if (rq_r >= rq_w) begin
                errors = errors + 1;
                $display("ERROR @%0t: DUT strobe without a reference strobe", $time);
            end else begin
                if (rq[rq_r % 1024] !== {b_lvl, b_se0}) begin
                    errors = errors + 1;
                    $display("ERROR @%0t: strobe %0d: DUT lvl/se0 %b%b, reference %b", $time, rq_r, b_lvl, b_se0, rq[rq_r % 1024]);
                end else ref_ok = ref_ok + 1;
                if ($realtime - rt[rq_r % 1024] < lag_min) lag_min = $realtime - rt[rq_r % 1024];
                if ($realtime - rt[rq_r % 1024] > lag_max) lag_max = $realtime - rt[rq_r % 1024];
                rq_r = rq_r + 1;
            end
            strobes = strobes + 1;
            if (b_act !== enable && b_act !== en_hist[31]) begin   // enable now or ~30 cycles ago (latency)
                errors = errors + 1;
                $display("ERROR @%0t: b_act = %b, enable = %b", $time, b_act, enable);
            end
            if (ck_i < 0) begin
                if (b_se0 || !b_lvl) begin                     // first non-J: frame start
                    if (cf >= nf) begin
                        errors = errors + 1;
                        $display("ERROR @%0t: unexpected non-J symbol on an idle line", $time);
                    end else ck_i = 0;
                end
            end
            if (ck_i >= 0) begin
                if (( b_se0 && f_sym[f_start[cf] + ck_i] != 2'd2) ||
                    (!b_se0 && f_sym[f_start[cf] + ck_i] != {1'b0, b_lvl})) begin
                    errors = errors + 1;
                    $display("ERROR @%0t: frame %0d symbol %0d: got %s, expected %0d",
                             $time, cf, ck_i, b_se0 ? "SE0" : (b_lvl ? "J" : "K"), f_sym[f_start[cf] + ck_i]);
                    ck_i = f_len[cf] - 1;                      // skip the rest of the frame
                end else sym_ok = sym_ok + 1;
                ck_i = ck_i + 1;
                if (ck_i == f_len[cf]) begin
                    ck_i = -1;
                    cf   = cf + 1;
                end
            end
        end
    end

    // drive one symbol for one bit time
    task drive(input [1:0] s);
        begin
            sym = s;
            #(bit_ns);
        end
    endtask

    task frame(input integer nsym);
        integer i, run, k;
        reg [1:0] s;
        begin
            f_start[nf] = f_w;
            s = 2'd0;                                          // starts with K
            i = 0;
            while (i < nsym) begin
                run = 1 + {$random(seed)} % 7;
                if ({$random(seed)} % 12 == 0) begin
                    s = 2'd2; run = 1 + {$random(seed)} % 2;   // SE0 inside (reset-like)
                end
                for (k = 0; k < run && i < nsym; k = k + 1) begin
                    f_sym[f_w] = s; f_w = f_w + 1; i = i + 1;
                end
                s = (s == 2'd0) ? 2'd1 : 2'd0;
            end
            f_sym[f_w] = 2'd2; f_w = f_w + 1;                  // EOP
            f_sym[f_w] = 2'd2; f_w = f_w + 1;
            f_sym[f_w] = 2'd1; f_w = f_w + 1;
            f_len[nf] = f_w - f_start[nf];
            nf = nf + 1;
            for (i = f_start[nf - 1]; i < f_w; i = i + 1) drive(f_sym[i]);
        end
    endtask

    task idle(input integer n);
        begin
            sym = 2'd1;
            #(n * bit_ns);
        end
    endtask

    // After a speed change (ls is quasi-static: it changes only between packets)
    // the idle line of the old speed reads as K for a moment, and the reference
    // (ls applied per sample) and the DUT (ls applied per tick, one word later)
    // strobe that transient differently.  Compare nothing for 3 idle bits, then
    // re-pair: wait for a reference strobe and let the DUT's copy of it pass
    // (DUT latency <= 30 clk_bit cycles < 36 < one FS bit).
    task mode_quiet;
        begin
            ign = 1'b1;
            idle(3);
            @(posedge clk); while (!r_en) @(posedge clk);
            repeat (36) @(posedge clk);
            rq_r = rq_w;              // drop what was in flight when the window opened
            ign  = 1'b0;
        end
    endtask

    task run(input l, input real ppm, input integer frames);
        integer p, s0;
        real    tb0;
        begin
            ls     = l;
            bit_ns = (l ? LS_DIV : FS_DIV) * 2.0 * HALF / (1.0 + ppm * 1.0e-6);
            mode_quiet;
            idle(20);
            // strobe rate on an idle line
            s0 = strobes; tb0 = $realtime;
            idle(100);
            if ((strobes - s0) < 98 || (strobes - s0) > 102) begin
                errors = errors + 1;
                $display("ERROR: %0d strobes in 100 idle bit times", strobes - s0);
            end
            for (p = 0; p < frames; p = p + 1) begin
                skew = ({$random(seed)} % 100) * (l ? 0.4 : 0.06);   // up to 40 ns LS, 6 ns FS
                frame(4 + {$random(seed)} % 60);
                idle(3 + {$random(seed)} % 6);
            end
            idle(10);
        end
    endtask

    initial begin
        $dumpfile("tb_usb_rx_fsls_frontend.vcd");
        $dumpvars(0, tb_usb_rx_fsls_frontend);
        rst_n = 1'b0;
        #20 rst_n = 1'b1;

        $display("FS 0 / +2500 / -2500 ppm");
        run(1'b0, 0.0, 60);
        run(1'b0, 2500.0, 40);
        run(1'b0, -2500.0, 40);
        $display("LS 0 / +15000 / -15000 ppm");
        run(1'b1, 0.0, 12);
        run(1'b1, 15000.0, 12);
        run(1'b1, -15000.0, 12);

        $display("enable -> b_act");
        ls = 1'b0; bit_ns = FS_DIV * 2.0 * HALF;
        mode_quiet;
        enable = 1'b0;
        idle(5);
        enable = 1'b1;
        idle(5);

        repeat (200) @(posedge clk);
        if (lag_min < 19.5 * 2.0 * HALF || lag_max > 27.5 * 2.0 * HALF) begin
            errors = errors + 1;
            $display("ERROR: DUT strobes %.2f .. %.2f clk_bit cycles after the reference, expected 20 .. 27",
                     lag_min / (2.0 * HALF), lag_max / (2.0 * HALF));
        end
        if (rq_w - rq_r > 1) begin                 // one may be in flight (idle line keeps strobing)
            errors = errors + 1;
            $display("ERROR: reference %0d strobes, DUT %0d", rq_w, rq_r);
        end
        if (cf != nf) begin
            errors = errors + 1;
            $display("ERROR: %0d of %0d frames checked", cf, nf);
        end
        $display("%0d frames, %0d symbols checked; %0d strobes equal to the reference, lag %.2f .. %.2f ns",
                 cf, sym_ok, ref_ok, lag_min, lag_max);
        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d error(s)", errors);
        $finish;
    end

    initial begin
        #200_000_000;
        $display("TEST FAILED: timeout");
        $finish;
    end

endmodule
