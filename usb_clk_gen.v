//-----------------------------------------------------------------------------
// usb_clk_gen.v - core clock clk60, island phase / ld and the ULPI CLKOUT
//                 from the 480 MHz PLL clock
//
// WORK_PLAN 5.2, AFE_INTEGRATION_PLAN.md 3.4 / phase A4, DOC/afe_interface_spec.md 2,
// Plan_60MHz.md 3.1 / 3.4 / P1.
//
//   PLL clk_bit (480 MHz) -> [THIS BLOCK] -> clk60  (60 MHz core clock, free-running)
//                                         -> phase_j, ld (480 MHz island timing)
//                                         -> clkout (CLKOUT, to the CLK pad, gated)
//
// Divider: a 4-bit Johnson (twisted-ring) counter j on clk_bit, 8 states.  The
// clk_bit rising edge on which phase becomes k is called Ek below; E0 is the
// "tick edge".
//
//     phase    0     1     2     3     4     5     6     7
//     j[3:0]  1111  1110  1100  1000  0000  0001  0011  0111
//
//   * Every next-state input is a flop output or one gate of flop outputs, and
//     each phase is decoded from two adjacent bits (one gate), so the 480 MHz
//     paths stay as short as they can be (a binary counter misses 480 MHz at
//     the slow corner by about 1 ns, build/sta, 2026-11-14).
//   * Self-correcting: j[3] <= j[2] & (j[1] | j[3]) equals j[2] in the eight
//     legal states and brings every illegal state (e.g. after an upset) back
//     into the cycle within a few clk_bit cycles.
//   * Reset state 0000 = phase 4: all outputs low, and the first E0 comes 4
//     clk_bit edges after the release.  (The binary counter of the single-clock
//     design started at phase 0 and gave the first E0 after 8 edges.  Only the
//     position of the first tick after an asynchronous reset release moves.)
//
// clk60 (core clock, Plan_60MHz.md 3.1)
//   * A dedicated flop, clk60 <= j[2], i.e. a copy of j[3]: rises at E0, falls
//     at E4, so high and low are 4 clk_bit cycles each (50 %, 16.67 ns).  Its
//     output feeds nothing inside this block (no clock-as-data path).  Not
//     gated: it runs whenever clk_bit runs, also while clkout is stopped.
//   * E0 is the edge on which the single-clock design's ce60 logic updated
//     (ce60 was high while phase = 7), so the flops moved from clk_bit + ce60
//     to clk60 change at the same time as before: the move was cycle-exact.
//     Testbenches that still need that tick decode it as phase_j == 4'b0111.
//
// phase / ld (480 MHz islands, Plan_60MHz.md 3.2 / 3.4)
//   * phase_j[3:0] = j, the Johnson code of the phase (table above), straight
//     from the counter flops.  For island logic that captures it (the lock
//     detector LSBs, P7) and decodes it after the capture.  The binary decode
//     is not done here: in front of the counter flops it would add load to the
//     480 MHz paths (about 0.2 ns at the slow corner).  Not for enables in
//     480 MHz paths (use ld).
//   * ld is a registered strobe, high while phase = 3, so island flops written
//     "if (ld)" update at E4, half a clk60 period away from both clk60 edges
//     on which the core launches (E0) and samples (E8 = next E0).
//   * Boundary rule: a clk_bit island register that is read by the clk60 domain
//     changes only on ld (E4); a clk_bit register that samples clk60-domain
//     data samples only on ld.  Both directions then have 4 clk_bit cycles
//     (8.3 ns) of setup and of hold, independent of the skew between the two
//     clock trees up to about +-3 clk_bit cycles (risk K3).  SDC:
//     set_multicycle_path 4 (setup) / 3 (hold) both ways (constraints/usb_phy.sdc).
//   * This also keeps RTL simulation free of races: clk60 is a flop output and
//     rises one delta after clk_bit, so a clk_bit register that changed on E0
//     would already be seen at that clk60 edge in simulation (zero cycles)
//     although the hardware sees the old value (8 cycles).  Registers that
//     change on E4 are stable at every clk60 edge.
//   * Deviation from Plan_60MHz.md 3.4 (load on phase 7 = E0, multicycle 8 / 7):
//     recorded as part of decision D10 in WORK_PLAN.md.
//
// ce60: the legacy enable output (registered, high while phase = 7) was
//   removed in Plan_60MHz.md P9; no block uses it any more.
//
// clkout (ULPI CLKOUT)
//   * A flop on the falling clk_bit edge: it rises in the middle of the phase-7
//     cycle, half a clk_bit period before E0 (on which the core samples and
//     launches), and falls 4 clk_bit cycles later.  So high and low are 4
//     clk_bit cycles each (50 % duty), and the core's ULPI outputs change about
//     1 ns after the CLKOUT edge (clock-to-out / hold for the Link).
//   * clkout <= hi is a plain copy of a posedge flop (no logic and no feedback
//     in the half-cycle path).  hi is high in phases 7, 0, 1, 2 of an enabled
//     period.  The half-cycle flop-to-flop path itself does not meet 480 MHz
//     at the slow corner (clock-to-Q + setup > 1.04 ns): the CLKOUT launch
//     point is revisited with the ULPI I/O timing (Plan_60MHz.md 3.4, K2).
//
// Glitch-free start / stop of clkout
//   clk_en (pll_lock & ~clock suspend, clk_bit domain) is sampled once per
//   period, in the cycle before clkout would rise (phase 6).  If it is 0, that
//   rising edge and the whole period are skipped; a pulse that has started
//   always runs to its end.  So clkout only ever shows complete 4 + 4 periods,
//   and stops low.  clk_on = 1 while clkout is running (updated at the same
//   decision point), so a power sequencer can wait for clk_on = 0 before it
//   stops the PLL: clk_bit must not stop while clkout or clk60 is high (the
//   stop itself would cut the pulse).  clk60, phase and ld keep running
//   whenever clk_bit runs.
//
// Reset: rst_n is the clock domain's reset (power-on), not the ULPI RESETB:
//   CLKOUT must keep running while the Link holds RESETB low.  Asynchronous
//   assert; clk60 = 0, clkout = 0, ld = 0, clk_on = 0 and
//   phase_j = 0000 (phase 4) during reset.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_clk_gen (
    input  wire       clk_bit,
    input  wire       rst_n,
    input  wire       clk_en,       // CLKOUT allowed
    output reg        clk60,        // core clock (free-running)
    output wire [3:0] phase_j,      // clk_bit position inside the clk60 period (Johnson)
    output reg        ld,           // island strobe, high while phase = 3
    output reg        clkout,       // CLKOUT
    output reg        clk_on        // CLKOUT is running
);

    reg [3:0] j;                    // Johnson counter
    reg       hi;                   // clkout value for the next falling edge

    assign phase_j = j;

    // Phase flags, registered one edge ahead (Plan_60MHz.md P9: one gate per
    // flop at 480 MHz, slow corner): p2 = 1 in state 1100 (decoded from 1110),
    // p6 = 1 in state 0011 (from 0001), hq = ~p2 & ~p6.  Each decode is one
    // gate of an adjacent bit pair; the same function as the old combinational
    // ph2 / ph6.
    reg p2, p6, hq;

    always @(posedge clk_bit or negedge rst_n) begin
        if (!rst_n) begin
            j      <= 4'b0000;
            clk60  <= 1'b0;
            ld     <= 1'b0;
            hi     <= 1'b0;
            clk_on <= 1'b0;
            p2     <= 1'b0;                      // flags of state 0000
            p6     <= 1'b0;
            hq     <= 1'b1;
        end else begin
            j     <= {j[2] & (j[1] | j[3]), j[1], j[0], ~j[3]};
            clk60 <= j[2];                       // = next j[3]
            p2    <=  j[1] & ~j[0];              // 1110 -> 1100 next
            p6    <= ~j[1] &  j[0];              // 0001 -> 0011 next
            hq    <= ~(j[1] ^ j[0]);             // neither
            ld    <= p2;                         // phase 3 next
            if (p6)                              // decision point
                clk_on <= clk_en;
            hi    <= (p6 & clk_en) | (hq & hi);  // set: phases 7, 0, 1, 2;
                                                 // p2: fall at the middle of phase 3
        end
    end

    always @(negedge clk_bit or negedge rst_n) begin
        if (!rst_n) clkout <= 1'b0;
        else        clkout <= hi;
    end

endmodule
