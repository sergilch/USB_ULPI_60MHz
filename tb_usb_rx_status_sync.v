//-----------------------------------------------------------------------------
// tb_usb_rx_status_sync.v - unit testbench for usb_rx_status_sync
//
// Run (Icarus Verilog):
//   iverilog -g2005 -o sim_rx_status_sync usb_rx_status_flt.v \
//            usb_rx_status_sync.v tb_usb_rx_status_sync.v
//   vvp sim_rx_status_sync
//
// Clocks: clk_bit; clk60 / ld generated as in the ULPI testbenches (clk60 rises
// with a blocking assignment on the edge where ce60 was high, ld = phase 3).
// Stimulus: the asynchronous inputs change on the falling clk_bit edge (so the
// sampling edge is unambiguous), with random run lengths from 1 cycle up to a
// few filter lengths: pulses shorter than, equal to and longer than the filter,
// and single-cycle disconnect pulses.
//
// Reference (history-based, independent of the counters / flops in the DUT):
// let in[k] be an input as sampled at rising clk_bit edge k (reset: the
// isolated value).  Plan_60MHz.md P7 timing:
//   * squelch: tick value at the ld edge k = in[k-2] (2-FF synchronizer);
//     disc: tick value = OR of in[k-9 .. k-2] (the 8 samples of the tick).
//     At a clk60 edge the output flips to !out iff the last L + 1 tick values
//     (the newest one taken 4 clk_bit edges before) all equal !out
//     (L = sq_flt / disc_flt, ticks).
//   * VBUS / ID: 2-FF on clk60: at clk60 edge e the filter sees the input
//     sampled at clk60 edge e-2; the output flips iff the last L + 1 of these
//     (L = vb_flt) all equal !out.
//   * Every output may change on clk60 edges only.
// Every output is compared after every clk_bit edge, also in and right after
// reset (reset values = isolated values: squelch = 1, disc = 0,
// a_vbus_vld = sess_vld = 0, sess_end = 1, id_gnd = 0).
// Phases: filter lengths (sq, disc, vb) = (0, 0, 0), (1, 0, 1), (2, 3, 3),
// (15, 15, 0); a long VBUS debounce (vb_flt = 200 ticks) with bounce; reset in
// the middle of activity.  Directed: a one-cycle disconnect pulse at each of
// the 8 phases of a tick must show (disc_flt = 0), a one-cycle squelch pulse
// shows only if it covers the E4 sample.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_usb_rx_status_sync;
    parameter real HALF = 1.0416667;

    integer errors = 0;
    integer seed   = 32'h51A7_0C11;

    reg clk_bit = 1'b0;
    always #(HALF) clk_bit = ~clk_bit;
    reg rst_n = 1'b0;
    reg [2:0] ce_cnt = 3'd0;
    always @(posedge clk_bit) ce_cnt <= ce_cnt + 3'd1;
    reg  clk60 = 1'b0;
    always @(posedge clk_bit) begin
        if (ce_cnt == 3'd7)      clk60 = 1'b1;
        else if (ce_cnt == 3'd3) clk60 = 1'b0;
    end
    wire ld = (ce_cnt == 3'd3);

    // inputs / outputs: bit order {id, sess_end, sess_vld, a_vbus, disc, squelch}
    localparam [5:0] ISO = {1'b0, 1'b1, 1'b0, 1'b0, 1'b0, 1'b1};
    reg  [5:0] in = ISO;
    reg  [3:0] sq_flt = 4'd0, disc_flt = 4'd0;
    reg [15:0] vb_flt = 16'd0;
    wire [5:0] out;

    usb_rx_status_sync dut (
        .clk_bit(clk_bit), .rst_n(rst_n), .clk60(clk60), .ld(ld),
        .squelch(in[0]), .disc(in[1]),
        .a_vbus_vld(in[2]), .sess_vld(in[3]), .sess_end(in[4]), .id_gnd(in[5]),
        .sq_flt(sq_flt), .disc_flt(disc_flt), .vb_flt(vb_flt),
        .squelch_s(out[0]), .disc_s(out[1]), .a_vbus_vld_s(out[2]), .sess_vld_s(out[3]),
        .sess_end_s(out[4]), .id_gnd_s(out[5]));

    initial begin
        $dumpfile("tb_usb_rx_status_sync.vcd");
        $dumpvars(0, tb_usb_rx_status_sync);
    end

    // ---------------- reference ----------------
    localparam HN = 300;
    reg  [15:0]   h  [0:1];          // clk_bit samples of squelch / disc, [j] = in[k-j]
    reg  [HN-1:0] th [0:1];          // tick values (squelch / disc), [0] newest
    reg  [HN-1:0] vh [2:5];          // VBUS / ID sampled at clk60 edges, [0] newest
    reg  [5:0] exp_o, o_before;
    reg        t_new [0:1];          // tick value taken at the last ld edge
    integer    b, k, L, ncmp = 0, nflip = 0;
    reg        all, orv;

    task ref_reset;
        begin
            for (b = 0; b < 2; b = b + 1) begin
                h[b] = {16{ISO[b]}}; th[b] = {HN{ISO[b]}}; t_new[b] = ISO[b];
            end
            for (b = 2; b < 6; b = b + 1) vh[b] = {HN{ISO[b]}};
            exp_o = ISO;
        end
    endtask
    initial ref_reset;

    // edge type of this edge, from ce_cnt before the edge
    always @(posedge clk_bit) begin : refm
        reg is_ld, is_e0;
        is_ld = (ce_cnt == 3'd3);
        is_e0 = (ce_cnt == 3'd7);
        if (!rst_n) begin
            ref_reset;
        end else begin
            o_before = exp_o;
            // clk_bit sample of this edge
            for (b = 0; b < 2; b = b + 1) h[b] = {h[b][14:0], in[b]};
            // h[b][j] = in[k - j]
            if (is_ld) begin
                t_new[0] = h[0][2];
                orv = 1'b0;
                for (k = 2; k <= 9; k = k + 1) orv = orv | h[1][k];
                t_new[1] = orv;
            end
            if (is_e0) begin
                for (b = 0; b < 2; b = b + 1) begin
                    th[b] = {th[b][HN-2:0], t_new[b]};
                    L = (b == 0) ? sq_flt : disc_flt;
                    all = 1;
                    for (k = 0; k <= L; k = k + 1) if (th[b][k] != !o_before[b]) all = 0;
                    if (all) exp_o[b] = !o_before[b];
                end
                // VBUS / ID: vh[b][0] = sample of this clk60 edge; the filter sees vh[b][2]
                for (b = 2; b < 6; b = b + 1) begin
                    vh[b] = {vh[b][HN-2:0], in[b]};
                    L = vb_flt;
                    all = 1;
                    for (k = 2; k <= L + 2; k = k + 1) if (vh[b][k] != !o_before[b]) all = 0;
                    if (all) exp_o[b] = !o_before[b];
                end
            end
        end
        #0.1;
        ncmp = ncmp + 1;
        if (exp_o != o_before) nflip = nflip + 1;
        if (out !== exp_o) begin
            errors = errors + 1;
            if (errors < 20)
                $display("ERROR @%0t: out %b, expected %b (flt %0d/%0d/%0d, rst %b)",
                         $time, out, exp_o, sq_flt, disc_flt, vb_flt, rst_n);
            exp_o = out;          // resynchronize, report each divergence once
        end
    end

    // ---------------- stimulus ----------------
    integer run_left [0:5];
    integer maxrun   [0:5];
    reg     stim_on = 1'b1;

    initial for (b = 0; b < 6; b = b + 1) run_left[b] = 1;

    always @(negedge clk_bit) begin : stim
        integer i;
        if (stim_on)
            for (i = 0; i < 6; i = i + 1) begin
                run_left[i] = run_left[i] - 1;
                if (run_left[i] <= 0) begin
                    in[i] = ~in[i];
                    run_left[i] = 1 + ({$random(seed)} % maxrun[i]);
                end
            end
    end

    task set_phase(input integer s, input integer d, input integer v);
        integer i;
        begin
            sq_flt = s; disc_flt = d; vb_flt = v;
            maxrun[0] = 8 * (2 * s + 2);
            maxrun[1] = 8 * (2 * d + 2);
            for (i = 2; i < 6; i = i + 1) maxrun[i] = 8 * (2 * v + 3);
        end
    endtask

    task cyc(input integer n); begin repeat (n) @(negedge clk_bit); end endtask

    // ---------------- sequence ----------------
    integer ph, nd, ns;
    initial begin
        set_phase(0, 0, 0);
        repeat (7) @(posedge clk_bit);
        @(negedge clk_bit) rst_n = 1'b1;
        repeat (4000) @(posedge clk_bit);
        // filter lengths change only while the inputs are quiet
        @(negedge clk_bit) rst_n = 1'b0;
        set_phase(1, 0, 1);
        repeat (4) @(posedge clk_bit);
        @(negedge clk_bit) rst_n = 1'b1;
        repeat (8000) @(posedge clk_bit);
        @(negedge clk_bit) rst_n = 1'b0;
        set_phase(2, 3, 3);
        repeat (3) @(posedge clk_bit);
        @(negedge clk_bit) rst_n = 1'b1;
        repeat (10000) @(posedge clk_bit);
        // reset in the middle of activity, then the longest squelch filter
        @(negedge clk_bit) rst_n = 1'b0;
        set_phase(15, 15, 0);
        repeat (2) @(posedge clk_bit);
        @(negedge clk_bit) rst_n = 1'b1;
        repeat (20000) @(posedge clk_bit);

        // directed: single-cycle pulses at every phase of a tick
        stim_on = 1'b0;
        @(negedge clk_bit) rst_n = 1'b0;
        set_phase(0, 0, 0);
        in = ISO;
        cyc(3);
        @(negedge clk_bit) rst_n = 1'b1;
        cyc(40);
        nd = 0; ns = 0;
        for (ph = 0; ph < 8; ph = ph + 1) begin
            while (ce_cnt != ph[2:0]) cyc(1);
            in[1] = 1'b1; cyc(1); in[1] = 1'b0;
            fork : wd
                begin @(posedge out[1]) nd = nd + 1; disable wd; end
                begin cyc(40); disable wd; end
            join
            cyc(40);
            while (ce_cnt != ph[2:0]) cyc(1);
            in[0] = 1'b0; cyc(1); in[0] = 1'b1;
            fork : ws
                begin @(negedge out[0]) ns = ns + 1; disable ws; end
                begin cyc(40); disable ws; end
            join
            cyc(40);
        end
        if (nd != 8) begin
            errors = errors + 1; $display("ERROR: %0d of 8 one-cycle disconnect pulses shown", nd);
        end
        if (ns != 1) begin
            errors = errors + 1; $display("ERROR: %0d of 8 one-cycle squelch pulses shown (expected 1)", ns);
        end

        // long VBUS debounce: bouncing for a while (runs up to 120 ticks), then
        // a clean level (history depth limits L to HN - 3 ticks)
        stim_on = 1'b1;
        @(negedge clk_bit) rst_n = 1'b0;
        set_phase(0, 0, 200);
        for (b = 2; b < 6; b = b + 1) maxrun[b] = 8 * 120;
        repeat (2) @(posedge clk_bit);
        @(negedge clk_bit) rst_n = 1'b1;
        repeat (8 * 2000) @(posedge clk_bit);
        for (b = 2; b < 6; b = b + 1) begin maxrun[b] = 8 * 1000; run_left[b] = 8 * 1000; end
        repeat (8 * 900) @(posedge clk_bit);
        if (out[5:2] !== in[5:2]) begin
            errors = errors + 1;
            $display("ERROR: VBUS / ID outputs %b did not settle to %b after 900 ticks",
                     out[5:2], in[5:2]);
        end

        $display("    %0d edges compared, %0d output changes", ncmp, nflip);
        if (nflip < 1000) begin errors = errors + 1; $display("ERROR: too few output changes"); end
        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d error(s)", errors);
        $finish;
    end

    initial begin
        #2000000;
        $display("TEST FAILED: timeout");
        $finish;
    end
endmodule
