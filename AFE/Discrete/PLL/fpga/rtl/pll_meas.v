//-----------------------------------------------------------------------------
// pll_meas.v - measurements of the PLL-board FPGA
//
//   FCNT     CLK60_A cycles counted (clk60a domain) over 2^FW REF_DIG cycles
//            (ref_clk domain): a free-running ref counter toggles a flag every
//            2^FW cycles; the flag is synchronized into clk60a and every toggle
//            latches and restarts the count.  The latched value is stable for a
//            whole window, so the clk -> 2-FF capture after a new-value toggle
//            is safe.  24 MHz, FW = 14: 40960 at exactly 480 MHz (24 ppm / LSB).
//   T_LOCK   us from the PLL_EN rising edge to pll_lock rising (usb_pll_lock_det),
//   T_DLD    the same to the ADF4002 MUXOUT rising (digital lock detect when
//            MUXSEL = 1); 16 bit, saturating; 65535 = not seen (yet).
//   PHASE    clk_bit domain: CLK60_A (the board's /8, CDCM1804 Y2) sampled on
//            every clk_bit edge (2 FF), an 8-bit shift register captured on ld
//            (usb_clk_gen, the 60 <-> 480 boundary rule), judged in the clk60
//            domain of usb_clk_gen: a valid word is a rotation of 11110000; the
//            position of its 0 -> 1 step, corrected by the fixed sampling
//            latency, is the usb_clk_gen phase (0 = E0 ... 7) at which CLK60_A
//            rises (doc section 7; tb_pll_fpga_top checks it against
//            usb_clk_gen.phase_j directly).  ph_err counts invalid words (saturating at 255).
//            phase / valid / ph_err go to clk through 2-FF synchronizers; they
//            are quasi-static (a changing phase means a broken divider).
//
// Clocks: clk (system, 60 MHz), clk60a (CLK60_A BUFG), ref_clk (REF_DIG BUFG),
//   clk_bit (CLK_BIT_A BUFG) with clk60 / ld from usb_clk_gen.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module pll_meas #(
    parameter FW     = 14,
    parameter CLK_HZ = 60000000
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        clk60a,
    input  wire        ref_clk,
    input  wire        clk_bit,
    input  wire        clk60,          // usb_clk_gen
    input  wire        ld,             // usb_clk_gen
    input  wire        clk60a_d,       // CLK60_A as data (IBUFDS output)
    input  wire        pll_en,         // clk domain
    input  wire        pll_lock,       // clk60 domain (usb_pll_lock_det)
    input  wire        muxout,         // asynchronous
    output reg  [23:0] fcnt,
    output reg  [15:0] t_lock,
    output reg  [15:0] t_dld,
    output reg  [2:0]  phase,
    output reg         ph_valid,
    output reg  [7:0]  ph_err,
    output reg         clk_alive
);

    // ---------------- FCNT ----------------
    reg [FW-1:0] rc;
    reg          rflag;
    always @(posedge ref_clk or negedge rst_n)
        if (!rst_n) begin rc <= 0; rflag <= 1'b0; end
        else begin
            rc <= rc + 1'b1;
            if (&rc) rflag <= ~rflag;
        end
    reg [2:0]  af;
    reg [23:0] acnt, alat;
    reg        anew;
    always @(posedge clk60a or negedge rst_n)
        if (!rst_n) begin af <= 0; acnt <= 0; alat <= 0; anew <= 1'b0; end
        else begin
            af <= {af[1:0], rflag};
            if (af[2] != af[1]) begin alat <= acnt + 24'd1; acnt <= 24'd0; anew <= ~anew; end
            else acnt <= acnt + 24'd1;
        end
    reg [2:0]  cn;
    reg [23:0] l1;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin cn <= 0; l1 <= 0; fcnt <= 0; end
        else begin
            cn <= {cn[1:0], anew};
            l1 <= alat;
            if (cn[2] != cn[1]) fcnt <= l1;
        end

    // ---------------- lock timers ----------------
    reg [1:0] ls, ms;
    reg       en_q, lk_q, mx_q, run_l, run_d;
    reg [5:0] us_div;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            ls <= 0; ms <= 0; en_q <= 0; lk_q <= 0; mx_q <= 0; run_l <= 0; run_d <= 0;
            us_div <= 0; t_lock <= 16'hFFFF; t_dld <= 16'hFFFF;
        end else begin
            ls <= {ls[0], pll_lock};
            ms <= {ms[0], muxout};
            en_q <= pll_en; lk_q <= ls[1]; mx_q <= ms[1];
            us_div <= (us_div == CLK_HZ / 1000000 - 1) ? 6'd0 : us_div + 6'd1;
            if (pll_en && !en_q) begin
                run_l <= 1'b1; run_d <= 1'b1; t_lock <= 16'd0; t_dld <= 16'd0; us_div <= 6'd0;
            end else begin
                if (!pll_en) begin run_l <= 1'b0; run_d <= 1'b0; end
                if (run_l && ls[1] && !lk_q) run_l <= 1'b0;
                if (run_d && ms[1] && !mx_q) run_d <= 1'b0;
                if (us_div == 0) begin
                    if (run_l && t_lock != 16'hFFFE) t_lock <= t_lock + 16'd1;
                    if (run_d && t_dld  != 16'hFFFE) t_dld  <= t_dld  + 16'd1;
                end
            end
            // not reached: report 65535 while still running at saturation
            if (run_l && t_lock == 16'hFFFE) t_lock <= 16'hFFFF;
            if (run_d && t_dld  == 16'hFFFE) t_dld  <= 16'hFFFF;
        end

    // ---------------- CLK60_A phase against usb_clk_gen ----------------
    reg [1:0] bs;
    reg [7:0] bsr, bw;
    always @(posedge clk_bit or negedge rst_n)
        if (!rst_n) begin bs <= 0; bsr <= 0; bw <= 0; end
        else begin
            bs  <= {bs[0], clk60a_d};
            bsr <= {bsr[6:0], bs[1]};            // bsr[0] = newest sample
            if (ld) bw <= bsr;                   // island register, changes on ld (E4)
        end
    reg [7:0] cw;
    reg [2:0] cpos;
    reg       cval;
    reg [7:0] cerr;
    reg [1:0] hb;                                // heartbeat for clk_alive
    integer k;
    reg [2:0] pos_c;
    reg       hit_c;
    always @(*) begin
        hit_c = 1'b0; pos_c = 3'd0;
        for (k = 0; k < 8; k = k + 1)
            if (cw == ((8'hF0 >> k) | (8'hF0 << (8 - k)))) begin hit_c = 1'b1; pos_c = k; end
    end
    always @(posedge clk60 or negedge rst_n)
        if (!rst_n) begin cw <= 0; cpos <= 0; cval <= 0; cerr <= 0; hb <= 0; end
        else begin
            cw <= bw;                            // clk60 input register (K10)
            hb <= hb + 2'd1;
            if (hit_c) begin cpos <= pos_c + 3'd1; cval <= 1'b1; end   // +1: sampling latency (2 FF + shift)
            else begin cval <= 1'b0; if (cerr != 8'hFF) cerr <= cerr + 8'd1; end
        end
    reg [2:0] p1, p2;
    reg [1:0] v1;
    reg [7:0] e1, e2;
    reg [2:0] h1;
    reg [7:0] hcnt;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            p1 <= 0; p2 <= 0; v1 <= 0; e1 <= 0; e2 <= 0; h1 <= 0; hcnt <= 0;
            phase <= 0; ph_valid <= 0; ph_err <= 0; clk_alive <= 0;
        end else begin
            p1 <= cpos; p2 <= p1; v1 <= {v1[0], cval}; e1 <= cerr; e2 <= e1;
            h1 <= {h1[1:0], hb[1]};
            phase <= p2; ph_valid <= v1[1] & pll_lock_s; ph_err <= e2;
            if (h1[2] != h1[1]) begin hcnt <= 8'd0; clk_alive <= 1'b1; end
            else if (hcnt == 8'd200) clk_alive <= 1'b0;
            else hcnt <= hcnt + 8'd1;
        end
    wire pll_lock_s = ls[1];

endmodule
