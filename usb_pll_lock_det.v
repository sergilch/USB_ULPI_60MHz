//-----------------------------------------------------------------------------
// usb_pll_lock_det.v - digital PLL lock / loss-of-lock detector, REFSEL decode
//
// WORK_PLAN 5.3, AFE_INTEGRATION_PLAN.md 3.4 / phase A4, DOC/afe_interface_spec.md
// 2, 3.3 and 4.3.  The PLL has no lock output, so lock is judged digitally:
//
//   ref_clk (ref_dig, buffered CDR_FREF) --> window of 2^NW reference cycles
//   clk_bit (PLL output)                 --> counted over that window
//
// Criterion (spec 4.3): the count must be within EXP +- TOL, EXP = 480 MHz /
//   f_ref * 2^NW (NW = 8: 6400 / 5120 / 4726 for 19.2 / 24 / 26 MHz; TOL = 5 is
//   +-0.1 % at 24 MHz).  GOOD_N consecutive good windows -> pll_lock = 1; one
//   bad window -> pll_lock = 0 and, if it was locked, the sticky loss-of-lock
//   flag lol = 1 (cleared by lol_clr or reset).  The count measures the ratio
//   clk_bit / ref_clk, i.e. whether the PLL follows its reference; a reference
//   that is off frequency but still within the PLL's range is not detected
//   (the USB +-500 ppm of the crystal is not this block's job).
//
// Window: a counter on ref_clk toggles a flag every 2^NW cycles; the flag is
//   synchronized into clk_bit (2 FF) and every toggle ends one window.  The
//   synchronizer delay is the same at both ends of a window, so the count is
//   exact to +-1.  The first window after start is partial and is ignored.
//   If no toggle arrives (reference stopped) the count saturates (timeout,
//   2^(CW-3) - 1 ticks = 8184 clk_bit cycles, 17 us at 480 MHz; must stay
//   above the largest EXP + TOL), which counts as a bad window and starts the
//   next one.
//
// Count (Plan_60MHz.md 3.2 / P7): the count is kept in clk_bit cycles, but
//   only its 3 LSBs are found at bit rate.  A 17-flop clk_bit island (the
//   synchronizer, a 7-bit shift register and an 8-sample word register loaded
//   on ld, the usb_clk_gen boundary rule) delivers the synchronized flag of
//   the 8 clk_bit edges of each tick to clk60; there the window end is the
//   sample where the flag changes (position p = 0 .. 7, at most one change per
//   tick since a window is > 4000 cycles).  Count = 8 x (ticks between the
//   two window-end words, a CW-3 bit clk60 counter) + p - p_start: the same
//   number of clk_bit cycles as a counter at bit rate, without one (the
//   13-bit counter of the single-clock version failed 480 MHz at the slow
//   corner).  The word gets a clk60 input register first (an island register
//   read by the core feeds a flop, Plan_60MHz.md K10: the E4 -> E0 path has
//   half a tick); the judgement is one tick later, 2 to 3 ticks after the flag
//   change.  (Plan 3.2 proposed the usb_clk_gen phase
//   as the LSBs; an enable-captured phase needs two gates in front of the
//   island flops, the sample word none.)
//
// Timing: lock after GOOD_N + 1 windows at most once the PLL is inside the
//   tolerance (24 MHz, NW = 8: a window is 10.7 us, lock <= 53 us after
//   settling); loss of lock within 2 windows (21 us) + 4 ticks, or within
//   1 window + the timeout if the reference stops.
//
// pll_en (async, from the power sequencer): 0 clears pll_lock at once and
//   restarts the detector (its own reset synchronizer, async assert / sync
//   release on clk60).  Switching the PLL off on purpose does not set lol.
//
// Dead clock: if clk_bit (and with it clk60) stops while pll_en = 1, nothing
//   on those clocks can react.  A free-running heartbeat (clk60 / 16, period
//   128 clk_bit cycles as before P7) is checked on ref_clk; without an edge for
//   32 reference cycles (1.3 us at 24 MHz) the detector is reset
//   asynchronously, so pll_lock falls even without a clock.  lol is then set
//   when the clock comes back (lock_hist below is only reset by pll_en).
//
// REFSEL (static strap / register, used before clk_bit runs, so decoded
//   combinationally):
//   refsel  f_ref     fb_div  refsel_err
//     00    19.2 MHz    25       0
//     01    24 MHz      20       0        (default; the PLL's fixed /20 today)
//     10    26 MHz       0       1        480 / 26 is not an integer: needs a
//                                         fractional divider (Q6); EXP is still
//                                         set, for a PLL that can do it
//     11    reserved    20       1        treated as 24 MHz
//
// Clocks: clk60 (detector, outputs), clk_bit + ld (sample island), ref_clk
//   (window); clk60 / ld from usb_clk_gen on the same clk_bit.  rst_n
//   asynchronous (power-on reset of the clock control, not RESETB), release
//   synchronized per domain here; the island flops take rst_n directly (they
//   hold the reset value of their input, r_tog, until it moves).  lol_clr is
//   a clk60 pulse (usb_afe_trim_regs).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_pll_lock_det #(
    parameter NW     = 8,          // window = 2^NW reference cycles
    parameter CW     = 13,         // count width in clk_bit cycles (timeout 2^(CW-3) - 1 ticks, > EXP + TOL)
    parameter TOL    = 5,          // accepted deviation, counts
    parameter GOOD_N = 4           // consecutive good windows for lock
) (
    input  wire       clk_bit,
    input  wire       clk60,       // core clock (usb_clk_gen)
    input  wire       ld,          // island strobe (usb_clk_gen)
    input  wire       ref_clk,
    input  wire       rst_n,
    input  wire       pll_en,
    input  wire [1:0] refsel,
    input  wire       lol_clr,     // clk60 pulse
    output reg        pll_lock,
    output reg        lol,
    output reg  [4:0] fb_div,
    output reg        refsel_err
);

    localparam integer EXP_19 = (4800 << NW) / 192;
    localparam integer EXP_24 = (4800 << NW) / 240;
    localparam integer EXP_26 = (4800 << NW) / 260;
    localparam integer TW     = CW - 3;                // tick counter width
    localparam [TW-1:0] TMAX  = {TW{1'b1}};

    // ---------------- REFSEL decode ----------------
    reg [CW-1:0] lo, hi;
    always @* begin
        case (refsel)
            2'b00:   begin fb_div = 5'd25; refsel_err = 1'b0; lo = EXP_19 - TOL; hi = EXP_19 + TOL; end
            2'b10:   begin fb_div = 5'd0;  refsel_err = 1'b1; lo = EXP_26 - TOL; hi = EXP_26 + TOL; end
            2'b11:   begin fb_div = 5'd20; refsel_err = 1'b1; lo = EXP_24 - TOL; hi = EXP_24 + TOL; end
            default: begin fb_div = 5'd20; refsel_err = 1'b0; lo = EXP_24 - TOL; hi = EXP_24 + TOL; end
        endcase
    end

    // ---------------- reference window (ref_clk) ----------------
    reg          rr1, rst_r_n;
    reg [NW-1:0] r_cnt;
    reg          r_tog;
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin rr1 <= 1'b0; rst_r_n <= 1'b0; end
        else        begin rr1 <= 1'b1; rst_r_n <= rr1;  end
    end
    always @(posedge ref_clk or negedge rst_r_n) begin
        if (!rst_r_n) begin
            r_cnt <= {NW{1'b0}};
            r_tog <= 1'b0;
        end else begin
            r_cnt <= r_cnt + 1'b1;
            if (&r_cnt) r_tog <= ~r_tog;
        end
    end

    // ---------------- sample island (clk_bit) ----------------
    // tw: the synchronized flag t2 after 8 consecutive clk_bit edges, the last
    // one the edge before ld (bit 0 oldest); loaded on ld (E4), so consecutive
    // words cover every edge once and tw is stable from E4 to E4
    reg       t1, t2;
    reg [6:0] sh;
    reg [7:0] tw;
    always @(posedge clk_bit or negedge rst_n) begin
        if (!rst_n) begin
            t1 <= 1'b0; t2 <= 1'b0; sh <= 7'd0; tw <= 8'd0;
        end else begin
            t1 <= r_tog;
            t2 <= t1;
            sh <= {t2, sh[6:1]};
            if (ld) tw <= {t2, sh};
        end
    end

    // ---------------- heartbeat (clk60, power-on domain) ----------------
    reg [3:0] hb_div;
    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) hb_div <= 4'd0;
        else        hb_div <= hb_div + 4'd1;
    end

    // ---------------- clock-alive check (ref_clk) ----------------
    reg       h1, h2, h3, dead;
    reg [5:0] dcnt;                        // reference cycles since the last heartbeat edge
    always @(posedge ref_clk or negedge rst_r_n) begin
        if (!rst_r_n) begin
            h1 <= 1'b0; h2 <= 1'b0; h3 <= 1'b0;
            dcnt <= 6'd0;
            dead <= 1'b0;
        end else begin
            h1 <= hb_div[3]; h2 <= h1; h3 <= h2;
            if (h2 ^ h3)          dcnt <= 6'd0;
            else if (!dcnt[5])    dcnt <= dcnt + 6'd1;
            dead <= dcnt[5];
        end
    end

    // ---------------- detector reset: rst_n & pll_en & clock alive ----------------
    wire rst_l_a = rst_n & pll_en & ~dead;
    reg  rl1, rst_l_n;
    always @(posedge clk60 or negedge rst_l_a) begin
        if (!rst_l_a) begin rl1 <= 1'b0; rst_l_n <= 1'b0; end
        else          begin rl1 <= 1'b1; rst_l_n <= rl1;  end
    end

    // lock history, reset only by pll_en (not by a dead clock)
    wire rst_e_a = rst_n & pll_en;
    reg  re1, rst_e_n, lock_hist;
    always @(posedge clk60 or negedge rst_e_a) begin
        if (!rst_e_a) begin re1 <= 1'b0; rst_e_n <= 1'b0; end
        else          begin re1 <= 1'b1; rst_e_n <= re1;  end
    end

    // ---------------- window end, count and judge (clk60) ----------------
    reg  [7:0]   twc;                      // tw, clk60 input register
    reg          wl;                       // twc[7] of the previous tick
    reg [TW-1:0] tk;                       // ticks since the word that started the window
    reg [2:0]    p0;                       // sample position of the window start
    reg          armed;                    // a full window is being counted
    reg [2:0]    good;                     // consecutive good windows (saturating)

    wire [7:0] chg = twc ^ {twc[6:0], wl};
    wire       wend = |chg;                // the flag changed in this word
    reg  [2:0] p;
    integer    i;
    always @* begin
        p = 3'd0;
        for (i = 7; i >= 0; i = i - 1) if (chg[i]) p = i;
    end
    wire          tout  = (tk == TMAX);
    // window length in clk_bit cycles
    wire [CW:0]   n_win = {1'b0, tk, 3'b000} + {{(CW-2){1'b0}}, p} - {{(CW-2){1'b0}}, p0};
    wire          ok    = (n_win >= {1'b0, lo}) && (n_win <= {1'b0, hi});

    always @(posedge clk60 or negedge rst_l_n) begin
        if (!rst_l_n) begin
            twc      <= 8'd0;
            wl       <= 1'b0;
            tk       <= {{(TW-1){1'b0}}, 1'b1};
            p0       <= 3'd0;
            armed    <= 1'b0;
            good     <= 3'd0;
            pll_lock <= 1'b0;
        end else begin
            twc <= tw;
            wl  <= twc[7];
            if (wend || tout) begin
                tk    <= {{(TW-1){1'b0}}, 1'b1};
                p0    <= wend ? p : 3'd0;
                armed <= 1'b1;
                if (armed) begin
                    if (wend && ok && !tout) begin
                        if (good != 3'd7) good <= good + 3'd1;
                        if (good + 3'd1 >= GOOD_N) pll_lock <= 1'b1;
                    end else begin
                        good     <= 3'd0;
                        pll_lock <= 1'b0;
                    end
                end
            end else begin
                tk <= tk + 1'b1;
            end
        end
    end

    // loss of lock = was locked, is not, with pll_en still on (bad window, or a
    // dead-clock reset seen once the clock is back)
    always @(posedge clk60 or negedge rst_e_n) begin
        if (!rst_e_n) lock_hist <= 1'b0;
        else          lock_hist <= pll_lock;
    end
    wire lost = lock_hist & ~pll_lock & rst_e_n;

    // sticky loss-of-lock flag: survives pll_en = 0, cleared by lol_clr / reset
    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n)       lol <= 1'b0;
        else if (lost)    lol <= 1'b1;
        else if (lol_clr) lol <= 1'b0;
    end

endmodule
