//-----------------------------------------------------------------------------
// usb_afe_rx_if.v - HS receive boundary to the analog front end (HS RX + CDR)
//
// WORK_PLAN 6.2, AFE_INTEGRATION_PLAN.md 3.2 / 5.2 / phase A3, pin list and
// timing in DOC/afe_interface_spec.md 3.2 and 4.2.  Position:
//
//   AFE: HS RX -> CDR --clk_rx, hs_rxd_a--> [THIS BLOCK] --clk_rx, hs_rxd-----> usb_rx_datapath
//        squelch det. --squelch_a-------->              --hs_squelch, hs_cdr_lock->
//                     <--rx_en_hs, cdr_en--
//
// Function
//   * Enables (clk60, registered): rx_en_hs (RX_EN: HS receiver + squelch
//     detector) and cdr_en (CDR_EN) are on in HS mode (speed = 00) while rx_en
//     is set and iso_en is not.  In FS / LS mode, in low-power mode and while
//     isolated both are off; the CDR then stops clk_rx (the HS chain of
//     usb_rx_datapath is disabled in those modes anyway, and its clk_rx reset
//     synchronizer releases once the clock runs again).
//   * Isolation: iso_en forces the inputs to their isolated values
//     (squelch_a -> 1, hs_rxd_a -> 1, spec 3.2) before anything samples them.
//   * Squelch synchronizer (2 FF on clk_rx) and lock: hs_cdr_lock rises
//     lock_dly bit times after the synchronized squelch falls and drops with
//     it (the CDR has no lock detector, spec 4.2); an OR window over the
//     synchronized squelch, one gate per stage (Plan_60MHz.md P9).  Both
//     outputs are registered together, so they change on the same clk_rx
//     edge.
//   * Squelch latency compensation: the data is delayed by 3 + sq_comp bit
//     times, the squelch / lock outputs by 3 (synchronizer + output register).
//     usb_rx_hs_frontend aligns its data with its own squelch synchronizer, so
//     sq_comp extra bits of data before the squelch detector released are
//     received as well: sq_comp ~ squelch response time / bit time gives those
//     bits back to the SYNC budget.  At the end of a packet the squelch rises
//     sq_comp bits earlier relative to the data, so the squelch hold time after
//     the line goes idle must stay above sq_comp bits plus the CDR latency.
//     Bits taken in front of the real signal are idle-line noise.
//
// Settings (measured in tb_usb_afe_rx_if, 12-bit SYNC; DOC/afe_interface_spec.md 4.2)
//   * Squelch release and CDR lock overlap in time, so the squelch costs SYNC
//     bits only where it is slower than the CDR.  Recommended: lock_dly = 2
//     with HS_ZMIN = 4 in usb_rx_datapath: the CDR may then deliver up to 6
//     wrong bits after the first line bit (HS_ZMIN = 6, lock_dly = 0: 4), and
//     a squelch release up to 12 ns is tolerated.  lock_dly hides wrong
//     pre-lock bits from the SYNC detector, which otherwise can take them for
//     a SYNC end.
//   * sq_comp = 0 unless the squelch detector releases later than about 12 ns:
//     at 16 ns, sq_comp = 2 recovers the loss.  With faster squelch it only adds
//     idle-line noise in front of SYNC (false SYNCs with HS_ZMIN = 4) and costs
//     EOP margin (sq_comp = 3 fails with a 6 ns squelch hold time).
//
// Configuration (lock_dly, sq_comp): static, from the clk60 domain (vendor
//   register usb_afe_trim_regs, WORK_PLAN 6.4); used on clk_rx without
//   synchronization, so change them only while HS reception is off
//   (rx_en_hs = 0).  speed, rx_en, iso_en are clk60-domain inputs (core
//   registers, usb_pwr_seq iso_en_c / afe_en_c); iso_en also gates the
//   asynchronous AFE inputs.
//
// Outputs to usb_rx_datapath (all registered on clk_rx):
//   hs_rxd      CDR data, 1 = J, delayed 3 + sq_comp clk_rx cycles
//   hs_squelch  1 = no signal (synchronized, delayed 3 cycles)
//   hs_cdr_lock 1 = data valid (lock_dly cycles after hs_squelch fell)
//
// Clocks / resets: clk60 (enables; Plan_60MHz.md P8, was clk_bit), clk_rx
//   (data).  The enables are AFE pins (static levels for the analog), so they
//   leave from clk60 flops like the other mode pins.  rst_n asynchronous; its
//   release is synchronized to clk_rx here, as two copies released on the
//   same edge (Plan_60MHz.md P9): rst_rx_n resets sq1 and the delay-line
//   select decode selr, the flops whose D can differ from their reset value at
//   the first edge after the release; rst_rx_m_n resets sq2, the lock window
//   z, hs_squelch, hs_cdr_lock, its copy rst_rx_m2_n the select sel and the
//   delay line (fan-out), whose D
//   inputs equal their reset values at that edge, and has a 2-cycle recovery
//   in constraints/usb_phy.sdc (a release one edge late changes nothing;
//   tb_usb_rx_hs_reset).  The data capture dq and the static lock-length
//   decode a have no reset.
//   480 MHz at the slow corner: every clk_rx flop has at most one gate in
//   front of it, and sources with a large fan-out (dq, sq2) are replicated
//   (keep processes, fan-out <= 3).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_afe_rx_if #(
    parameter DLY_W  = 3,                    // lock_dly width
    parameter COMP_W = 3                     // sq_comp width
) (
    input  wire              clk60,
    input  wire              rst_n,

    // mode / control (clk60 domain)
    input  wire [1:0]        speed,          // XcvrSelect: 00 HS
    input  wire              rx_en,          // reception allowed (not low power)
    input  wire              iso_en,
    input  wire [DLY_W-1:0]  lock_dly,       // bit times, static
    input  wire [COMP_W-1:0] sq_comp,        // bit times, static

    // AFE
    output reg               rx_en_hs,       // RX_EN
    output reg               cdr_en,         // CDR_EN
    input  wire              clk_rx,         // CDR recovered clock
    input  wire              hs_rxd_a,       // CDR retimed data, 1 = J
    input  wire              squelch_a,      // SQUELCH_A, 1 = no signal

    // to usb_rx_datapath (clk_rx domain)
    output wire              hs_rxd,
    output reg               hs_squelch,
    output reg               hs_cdr_lock
);

    localparam NST = (1 << COMP_W) + 1;      // delay-line stages behind the capture flop dq

    // ---------------- enables (clk60) ----------------
    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            rx_en_hs <= 1'b0;
            cdr_en   <= 1'b0;
        end else begin
            rx_en_hs <= rx_en & ~iso_en & (speed == 2'b00);
            cdr_en   <= rx_en & ~iso_en & (speed == 2'b00);
        end
    end

    // ---------------- clk_rx reset synchronizer ----------------
    // Two copies of the second stage, released on the same edge (header):
    // rst_rx_n for sq1 / selr; rst_rx_m_n and rst_rx_m2_n (multicycle recovery,
    // two copies for the fan-out) for the rest.
    reg rr1, rst_rx_n, rst_rx_m_n, rst_rx_m2_n;
    always @(posedge clk_rx or negedge rst_n) begin
        if (!rst_n) rr1 <= 1'b0;
        else        rr1 <= 1'b1;
    end
    // keep on the processes: the two equal flops must not be merged
    (* keep *) always @(posedge clk_rx or negedge rst_n) begin
        if (!rst_n) rst_rx_n <= 1'b0;
        else        rst_rx_n <= rr1;
    end
    (* keep *) always @(posedge clk_rx or negedge rst_n) begin
        if (!rst_n) rst_rx_m_n <= 1'b0;
        else        rst_rx_m_n <= rr1;
    end
    // second multicycle copy for the delay line and its select (fan-out)
    (* keep *) always @(posedge clk_rx or negedge rst_n) begin
        if (!rst_n) rst_rx_m2_n <= 1'b0;
        else        rst_rx_m2_n <= rr1;
    end

    // ---------------- squelch, lock (clk_rx) ----------------
    // Lock (Plan_60MHz.md P9, was a saturating counter + compare, 3-4 gates):
    // hs_cdr_lock = no squelch in the current and the last lock_dly samples
    // of sq2, i.e. the same function.  z[1] = OR of sq2 over the last
    // lock_dly samples, built by an OR chain whose length is set by the static
    // decode a[i] = (i < lock_dly): z[i] <= sq2 | (z[i+1] & a[i]), one gate per
    // stage; hs_cdr_lock <= ~(sq2 | (z[1] & a[0])), one gate.
    localparam LMAX = (1 << DLY_W) - 1;            // largest lock_dly
    wire             sq_in = squelch_a | iso_en;   // isolated value 1
    // sq2 has NSQ equal copies (fan-out <= 3 each: z, hs_squelch, hs_cdr_lock)
    localparam NSQ = (LMAX + 4) / 3;
    reg              sq1;
    reg [NSQ-1:0]    sq2;
    wire [LMAX+1:0]  sq2_s;                        // sq2 copy per consumer
    reg [LMAX:1]     z;                            // OR windows of sq2
    reg [LMAX-1:0]   a;                            // static: a[i] = (i < lock_dly)

    // fast group: sq1
    always @(posedge clk_rx or negedge rst_rx_n) begin
        if (!rst_rx_n) sq1 <= 1'b1;
        else           sq1 <= sq_in;
    end

    integer i;
    always @(posedge clk_rx)
        for (i = 0; i < LMAX; i = i + 1) a[i] <= (i < lock_dly);

    // one process per sq2 copy, with keep: the equal copies must not be merged
    genvar g;
    generate for (g = 0; g < NSQ; g = g + 1) begin : g_sq2
        (* keep *) always @(posedge clk_rx or negedge rst_rx_m_n) begin
            if (!rst_rx_m_n) sq2[g] <= 1'b1;
            else             sq2[g] <= sq1;
        end
    end endgenerate
    generate for (g = 0; g <= LMAX + 1; g = g + 1) begin : g_sq2s
        assign sq2_s[g] = sq2[g / 3];
    end endgenerate

    // at the first edge after the release: sq2 <- sq1 = 1, z <- 1 (sq2 = 1),
    // hs_squelch <- sq2 = 1, hs_cdr_lock <- 0: all equal to their reset values
    always @(posedge clk_rx or negedge rst_rx_m_n) begin
        if (!rst_rx_m_n) begin
            z           <= {LMAX{1'b1}};
            hs_squelch  <= 1'b1;
            hs_cdr_lock <= 1'b0;
        end else begin
            for (i = 1; i < LMAX; i = i + 1) z[i] <= sq2_s[i] | (z[i+1] & a[i]);
            z[LMAX]     <= sq2_s[LMAX];
            hs_squelch  <= sq2_s[0];
            hs_cdr_lock <= ~(sq2_s[LMAX+1] | (z[1] & a[0]));
        end
    end

    // ---------------- data delay line (clk_rx) ----------------
    // The input is captured in dq (isolation OR only, no mux in front: the CDR
    // output timing is the AFE's), stage 1 + sq_comp loads dq (one-hot select,
    // static), every stage below shifts down, stage 0 is the output: delay =
    // 1 + (1 + sq_comp) + 1 = 3 + sq_comp cycles, as before P9.  One mux per
    // stage between flops.  dq is NDQ equal copies (fan-out <= 3 each, 480 MHz at
    // the slow corner), no reset (data; dl ignores it while sel = 0).
    // Reset (Plan_60MHz.md P9): dl is on the
    // multicycle reset (all ones = J), as sel (reset 0, D = selr, which is
    // on the fast reset with reset value 0): sel = 0 (every stage shifts in J)
    // during the reset whenever clk_rx runs and on the first two edges after
    // the release, so every dl stage and sel have D = their reset value at the
    // release edge.  Those J bits are masked (hs_squelch stays 1 for
    // >= 3 edges after the release).
    wire           d_in = hs_rxd_a | iso_en;     // isolated value 1 (J)
    wire [COMP_W:0] ent = {1'b0, sq_comp} + 2'd1;   // entry stage
    localparam NDQ = (NST + 2) / 3;           // dq copies, fan-out <= 3 each
    reg  [NDQ-1:0] dq;
    reg  [NST-1:0] selr;                     // static decode, fast reset 0
    reg  [NST-1:0] sel;
    reg  [NST-1:0] dl;
    wire [NST-1:0] dq_s;                     // dq copy of each stage

    // one process per copy, with keep: the equal copies must not be merged
    generate for (g = 0; g < NDQ; g = g + 1) begin : g_dqc
        (* keep *) always @(posedge clk_rx) dq[g] <= d_in;
    end endgenerate
    generate for (g = 0; g < NST; g = g + 1) begin : g_dq
        assign dq_s[g] = dq[g / 3];
    end endgenerate

    // selr: D is the static decode only (no clk_rx path in front), reset 0
    // until the release; sel <= selr, no gate.  At the release edge sel loads
    // selr = 0 (its reset value), so sel = 0 on the release edge and the one
    // after it.
    always @(posedge clk_rx or negedge rst_rx_n) begin
        if (!rst_rx_n) selr <= {NST{1'b0}};
        else           selr <= {{(NST-1){1'b0}}, 1'b1} << ent;
    end

    always @(posedge clk_rx or negedge rst_rx_m2_n) begin
        if (!rst_rx_m2_n) sel <= {NST{1'b0}};
        else             sel <= selr;
    end

    always @(posedge clk_rx or negedge rst_rx_m2_n) begin
        if (!rst_rx_m2_n) dl <= {NST{1'b1}};
        else             dl <= (sel & dq_s) | (~sel & {1'b1, dl[NST-1:1]});
    end

    assign hs_rxd = dl[0];

endmodule
