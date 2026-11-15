//-----------------------------------------------------------------------------
// afe_pll_bm.v - behavioural model of the PLL lower loop (frequency only)
//
// Part of the AFE behavioural models (AFE_INTEGRATION_PLAN.md 5.3, phase A4).
// Testbench only.  Pin names follow the analog block (CDR_FREF in); the
// output is the digital-side clk_bit.
//
// Behaviour (frequency, no phase): the model measures the reference period on
//   every rising CDR_FREF edge and settles its output frequency towards
//   DIV / T_ref with a first-order response (time constant TAU), clipped to
//   the VCO range [F_MIN, F_MAX].  Each output period is computed from the
//   current frequency.
//   * PLL_EN = 0: clk_out stops low; on enable the VCO starts at F_START.
//   * Reference missing for more than 4 expected periods: the target falls to
//     F_MIN (the control voltage drains), so the output drifts down.
//   * f_off adds a relative frequency error on top (loss-of-lock injection,
//     e.g. 0.003 = +0.3 %); dead = 1 stops the output while PLL_EN = 1 (VCO
//     failure).
//   * clk60_out (CLK60_A of afe_pll.va): clk_out / P_DIV60, 50 % duty.  It
//     rises together with every P_DIV60-th rising clk_out edge (same time
//     step, assigned right after clk_out).  The divider restarts with the
//     clock: the first clk_out edge after PLL_EN = 1 (or after dead) is also
//     a clk60_out rising edge.  Low while the clock is stopped.
//   * DIV, TAU, f_off, dead are module variables: testbenches set them
//     hierarchically.  f_now (MHz) is the current output frequency.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module afe_pll_bm #(
    parameter real P_DIV   = 20.0,
    parameter real P_TAU   = 5000.0,    // ns, settling time constant
    parameter real F_MIN   = 400.0,     // MHz, VCO range
    parameter real F_MAX   = 500.0,     // MHz
    parameter real F_START = 400.0,     // MHz, VCO at enable
    parameter integer P_DIV60 = 8       // clk60_out = clk_out / P_DIV60 (even)
) (
    input  wire CDR_FREF,
    input  wire PLL_EN,
    output reg  clk_out,
    output reg  clk60_out
);
    real DIV   = P_DIV;
    real TAU   = P_TAU;
    real f_off = 0.0;
    reg  dead  = 1'b0;

    real f_now = F_START;               // MHz
    real f_tgt = F_START;
    real t_ref = -1.0e9, t_ref_per = 41.667, per;
    integer cnt60 = 0;

    // reference period and target
    always @(posedge CDR_FREF) begin
        if ($realtime - t_ref < 1000.0) t_ref_per = $realtime - t_ref;
        t_ref = $realtime;
        f_tgt = DIV * 1000.0 / t_ref_per;
        if (f_tgt > F_MAX) f_tgt = F_MAX;
        if (f_tgt < F_MIN) f_tgt = F_MIN;
    end

    initial begin clk_out = 1'b0; clk60_out = 1'b0; end
    always begin
        if ((PLL_EN !== 1'b1) || dead) begin
            clk_out   = 1'b0;
            clk60_out = 1'b0;
            cnt60     = 0;
            if (PLL_EN !== 1'b1) f_now = F_START;
            wait ((PLL_EN === 1'b1) && !dead);
        end
        if ($realtime - t_ref > 4.0 * t_ref_per) f_tgt = F_MIN;     // reference lost
        per   = 1000.0 / (f_now * (1.0 + f_off));
        f_now = f_now + (f_tgt - f_now) * per / TAU;
        if (f_now > F_MAX) f_now = F_MAX;
        if (f_now < F_MIN) f_now = F_MIN;
        clk_out = 1'b1;
        if (cnt60 == 0)                clk60_out = 1'b1;
        else if (cnt60 == P_DIV60 / 2) clk60_out = 1'b0;
        cnt60 = (cnt60 + 1) % P_DIV60;
        #(per / 2.0);
        clk_out = 1'b0;
        #(per / 2.0);
    end
endmodule
