//-----------------------------------------------------------------------------
// tb_usb_clk_gen.v - self-checking testbench for usb_clk_gen (Plan_60MHz.md P1)
//
//   iverilog -g2005 -o sim_clk_gen usb_clk_gen.v tb_usb_clk_gen.v
//   vvp sim_clk_gen
//
// Reference model: the number n of clk_bit rising edges since the last reset
// release.  0.2 ns after every rising edge (all DUT flops settled):
//   * phase = (n + 4) mod 8 (reset state = phase 4), decoded from phase_j;
//   * clk60 = 1 for phase 0..3, so every clk60 pulse is 4 high + 4 low clk_bit
//     cycles and the first rising edge comes 4 edges after the release;
//   * ld = (phase == 3), ce60 = (phase == 7);
//   * during reset (also asserted in the middle of a period) all outputs are
//     0 and phase_j = 0000 (phase 4).
// Self-correction: the Johnson counter is set to each of its 8 illegal states
// (hierarchical deposit); it must be back in the legal cycle within 8 clk_bit
// cycles, after which the reference model is re-aligned to the new phase.
// clk60 does not depend on clk_en: it is checked through random clk_en changes,
// while clkout starts / stops only on whole periods (half a clk_bit before E0,
// only when clk_en was 1 in the cycle before) and clk_on follows it.
//
// Boundary rule (usb_clk_gen header): a clk60 counter is copied into a clk_bit
// register on ld and back into a clk60 register.  In simulation and hardware
// alike this must give exactly one clk60 tick of latency each way, i.e. the
// copy back is always the counter value of the previous tick.  A copy taken on
// E0 instead (ce60) is shown for contrast: simulation returns it one tick
// earlier than the hardware would (zero-cycle race), the case the rule avoids.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_usb_clk_gen;

    localparam real TB = 2.0833;        // clk_bit period (ns)

    reg  clk_bit = 1'b0;
    reg  rst_n   = 1'b0;
    reg  clk_en  = 1'b0;
    wire clk60, ld, ce60, clkout, clk_on;
    wire [3:0] phase_j;
    reg  [2:0] phase;                   // binary decode of the Johnson phase

    usb_clk_gen dut (.clk_bit(clk_bit), .rst_n(rst_n), .clk_en(clk_en),
                     .clk60(clk60), .phase_j(phase_j), .ld(ld), .ce60(ce60),
                     .clkout(clkout), .clk_on(clk_on));

    always #(TB / 2.0) clk_bit = ~clk_bit;

    // phase_j table of the usb_clk_gen header; x for an illegal code
    always @(*) begin
        case (phase_j)
            4'b1111: phase = 3'd0;  4'b1110: phase = 3'd1;
            4'b1100: phase = 3'd2;  4'b1000: phase = 3'd3;
            4'b0000: phase = 3'd4;  4'b0001: phase = 3'd5;
            4'b0011: phase = 3'd6;  4'b0111: phase = 3'd7;
            default: phase = 3'bxxx;
        endcase
    end

    integer errors = 0;
    integer n      = 0;                 // clk_bit rising edges since reset release
    integer off    = 4;                 // expected phase = (n + off) mod 8
    integer checks = 0;
    reg     skip   = 1'b0;              // illegal-state recovery in progress

    task err(input [8*64-1:0] msg);
        begin
            errors = errors + 1;
            if (errors <= 20) $display("ERROR @%0t n=%0d: %0s", $time, n, msg);
        end
    endtask

    //-------------------------------------------------------------------------
    // per-cycle reference check of clk60 / phase / ld / ce60
    //-------------------------------------------------------------------------
    reg en_q;                           // clk_en as seen at the previous edge
    reg [2:0] ph_exp;
    reg       exp_on = 1'b0;            // reference clk_on of the current period
    always @(negedge rst_n) exp_on = 1'b0;

    // clkout after every falling edge: high in phases 7, 0, 1, 2 of an enabled
    // period, low otherwise
    always @(negedge clk_bit) begin
        #0.2;
        if (rst_n && !skip &&
            clkout !== (exp_on && (phase == 3'd7 || phase <= 3'd2)))
            err("clkout");
    end
    always @(posedge clk_bit or negedge rst_n) begin
        if (!rst_n) n <= 0;
        else        n <= n + 1;
    end

    always @(posedge clk_bit) begin
        #0.2;
        checks = checks + 1;
        if (!rst_n) begin
            if (clk60 !== 1'b0 || phase !== 3'd4 || ld !== 1'b0 || ce60 !== 1'b0 ||
                clkout !== 1'b0 || clk_on !== 1'b0)
                err("outputs not 0 / phase not 4 during reset");
        end else if (!skip) begin
            ph_exp = n + off;
            if (phase !== ph_exp)                                err("phase");
            if (clk60 !== (ph_exp <= 3'd3))                      err("clk60");
            if (ld    !== (ph_exp == 3'd3))                      err("ld");
            if (ce60  !== (ph_exp == 3'd7))                      err("ce60");
            // clk_on / clkout period decision: clk_en at the edge into phase 7
            if (ph_exp == 3'd7) exp_on = en_q;
            if (clk_on !== exp_on)                               err("clk_on");
        end else begin
            exp_on = clk_on;            // re-aligned after the recovery
        end
    end

    // asynchronous reset: everything drops at once, also mid-period
    always @(negedge rst_n) begin
        #0.1;
        if (clk60 !== 1'b0 || ld !== 1'b0 || ce60 !== 1'b0 || clkout !== 1'b0 ||
            clk_on !== 1'b0 || phase !== 3'd4)
            err("asynchronous reset");
    end

    //-------------------------------------------------------------------------
    // clk60 pulse widths in time (50 %, 4 + 4 clk_bit), independent of clk_en
    //-------------------------------------------------------------------------
    realtime t_r = 0.0, t_f = 0.0;
    integer  n_pulses = 0;
    always @(posedge clk60) begin
        if (t_f > 0.0 && rst_n && !skip && n > 9 && ($realtime - t_f < 4*TB - 0.01 || $realtime - t_f > 4*TB + 0.01))
            err("clk60 low phase not 4 clk_bit");
        t_r = $realtime;
    end
    always @(negedge clk60) begin
        if (rst_n && !skip) begin
            if ($realtime - t_r < 4*TB - 0.01 || $realtime - t_r > 4*TB + 0.01)
                err("clk60 high phase not 4 clk_bit");
            n_pulses = n_pulses + 1;
        end
        t_f = $realtime;
    end

    //-------------------------------------------------------------------------
    // clkout: rises half a clk_bit before E0 (phase 7, falling clk_bit edge),
    // only after clk_en = 1 in the cycle before; whole periods; clk_on
    //-------------------------------------------------------------------------
    integer n_clkout = 0;
    always @(posedge clk_bit) en_q <= clk_en;
    always @(posedge clkout) begin : chk_rise
        if (skip) disable chk_rise;
        if (clk_bit !== 1'b0)  err("clkout rise not on a falling clk_bit edge");
        if (phase !== 3'd7)    err("clkout rise not in phase 7");
        if (clk60 !== 1'b0)    err("clkout rise not before the clk60 rise");
        if (!clk_on)           err("clkout high with clk_on = 0");
        n_clkout = n_clkout + 1;
        @(posedge clk_bit); #0.2;
        if (clk60 !== 1'b1)    err("clk60 did not rise half a clk_bit after clkout");
    end
    always @(negedge clkout) if (rst_n && !skip && phase !== 3'd3) err("clkout fall not in phase 3");
    always @(posedge clk_bit) begin
        #0.3;
        if (rst_n && !clk_on && clkout) err("clkout high while clk_on = 0");
    end

    //-------------------------------------------------------------------------
    // 60 <-> 480 boundary loopback
    //-------------------------------------------------------------------------
    reg [7:0] c60 = 8'd0, back = 8'd0, isl = 8'd0, isl_e0 = 8'd0, back_e0 = 8'd0;
    reg       c60_v = 1'b0;             // back is valid (two ticks after reset)
    reg [1:0] c60_cnt = 2'd0;
    integer   n_loop = 0, n_e0_short = 0;
    always @(posedge clk60) begin
        c60     <= c60 + 8'd1;
        back    <= isl;                 // island -> core, island changed on E4
        back_e0 <= isl_e0;              // island -> core, island changed on E0 (race)
    end
    // the loopback is checked from the third tick after a reset on (a reset in
    // the middle of a tick leaves the island copy of that tick stale)
    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n)               c60_cnt <= 2'd0;
        else if (c60_cnt != 2'd3) c60_cnt <= c60_cnt + 2'd1;
    end
    always @(posedge clk_bit) begin
        if (ld)   isl    <= c60;        // core -> island on E4 (the rule)
        if (ce60) isl_e0 <= c60;        // core -> island on E0
    end
    always @(posedge clk60) begin
        #0.5;
        if (c60_cnt == 2'd3 && !skip) begin
            n_loop = n_loop + 1;
            // c60 = k after this edge.  isl was loaded on the E4 of tick k-1
            // with k-1 and is copied back now, so back must be k-1.
            if (back !== c60 - 8'd1) err("ld boundary: wrong latency");
            // isl_e0 is loaded on E0 together with the clk60 edge: hardware
            // copies back the value of the tick before (k-2), simulation
            // already sees the new one (k-1).  Counted, not checked.
            if (back_e0 === c60 - 8'd1) n_e0_short = n_e0_short + 1;
        end
    end

    //-------------------------------------------------------------------------
    // stimulus
    //-------------------------------------------------------------------------
    integer i, k, n_ill = 0, seed = 32'h60_480;
    function is_legal(input [3:0] v);
        is_legal = (v == 4'b0000) || (v == 4'b0001) || (v == 4'b0011) || (v == 4'b0111) ||
                   (v == 4'b1111) || (v == 4'b1110) || (v == 4'b1100) || (v == 4'b1000);
    endfunction
    initial begin
        // reset, release at an arbitrary point between edges
        repeat (5) @(posedge clk_bit);
        #0.7 rst_n = 1'b1;

        // clk60 runs without clk_en
        repeat (100) @(posedge clk_bit);
        if (n_clkout != 0) err("clkout ran with clk_en = 0");
        if (n_pulses < 10) err("clk60 not running with clk_en = 0");

        // CLKOUT on, then random clk_en changes (whole periods only)
        @(negedge clk_bit) clk_en = 1'b1;
        repeat (200) @(posedge clk_bit);
        if (n_clkout < 20) err("clkout did not start");
        for (i = 0; i < 400; i = i + 1) begin
            @(negedge clk_bit);
            if (($random(seed) & 15) == 0) clk_en = ~clk_en;
        end

        // reset in the middle of a clk60 high phase, then again in a low phase
        wait (clk60 === 1'b1); @(posedge clk_bit); #0.5 rst_n = 1'b0;
        repeat (3) @(posedge clk_bit); #0.9 rst_n = 1'b1;
        repeat (77) @(posedge clk_bit);
        wait (clk60 === 1'b0); @(posedge clk_bit); #0.3 rst_n = 1'b0;
        #1.4 rst_n = 1'b1;
        repeat (300) @(posedge clk_bit);

        // every illegal Johnson state: back in the cycle within 8 cycles
        for (i = 0; i < 16; i = i + 1) begin
            if (!is_legal(i[3:0])) begin
                @(negedge clk_bit);
                skip = 1'b1;
                dut.j = i[3:0];
                k = 0;
                while (!is_legal(phase_j) && k < 20) begin @(negedge clk_bit); k = k + 1; end
                if (k > 8) err("illegal Johnson state not corrected within 8 cycles");
                n_ill = n_ill + 1;
                repeat (24) @(negedge clk_bit);     // let the outputs follow
                off = phase - n;                    // n counts at the next edge too
                @(posedge clk_bit); #0.05;          // re-align away from the check
                skip = 1'b0;
                repeat (40) @(posedge clk_bit);
            end
        end
        if (n_ill != 8) err("not all illegal states tried");

        $display("checks: %0d per-cycle, %0d clk60 pulses, %0d clkout pulses, %0d loopback ticks",
                 checks, n_pulses, n_clkout, n_loop);
        $display("contrast: a copy on E0 (ce60) was one tick early (zero-cycle race) in %0d of %0d ticks",
                 n_e0_short, n_loop);
        if (n_loop < 50) err("loopback not exercised");
        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d errors", errors);
        $finish;
    end

endmodule
