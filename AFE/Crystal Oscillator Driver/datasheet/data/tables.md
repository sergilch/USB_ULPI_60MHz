| Parameter | tm 27 °C 1.8 V | ws 125 °C 1.62 V | ws −40 °C 1.62 V | wp −40 °C 1.98 V | wp 125 °C 1.98 V | wo 27 °C 1.8 V | wz 27 °C 1.8 V |
|---|---|---|---|---|---|---|---|
| −R_neg at 24 MHz, DRV 10 [Ω] | 776 | 483 | 709 | 1106 | 738 | 807 | 742 |
| Start-up margin −R_neg / ESR_max, DRV 10 | 7.8 | 4.8 | 7.1 | 11.1 | 7.4 | 8.1 | 7.4 |
| −R_neg at 24 MHz, DRV 11 [Ω] | 889 | 562 | 822 | 1247 | 844 | 926 | 847 |
| Start-up margin, DRV 11 | 8.9 | 5.6 | 8.2 | 12.5 | 8.4 | 9.3 | 8.5 |
| I(VDD) before oscillation, DRV 10 [mA] | 0.700 | 0.490 | 0.468 | 0.969 | 0.954 | 0.718 | 0.679 |
| I(VDD), XTAL_EN = 0 [nA] | 0.2 | 1.6 | 0.2 | 0.2 | 6.9 | 0.2 | 0.2 |
| XI / XO DC bias [V] | 0.848 | 0.786 | 0.917 | 0.882 | 0.745 | 0.815 | 0.881 |
| XI amplitude [Vpp] | 0.751 | 0.706 | 0.707 | 0.788 | 0.813 | — | — |
| XO amplitude [Vpp] | 0.843 | 0.785 | 0.799 | 0.894 | 0.932 | — | — |
| Crystal current [mA rms] | 0.702 | 0.659 | 0.660 | 0.738 | 0.764 | — | — |
| Drive level at ESR 100 Ω [µW] | 49.3 | 43.5 | 43.5 | 54.5 | 58.4 | — | — |
| I(VDD) in steady state [mA] | 0.364 | 0.326 | 0.307 | 0.420 | 0.524 | — | — |
| Load capacitance seen by the arm C0 + C_L [pF] | 8.703 | 8.731 | 8.721 | 8.665 | 8.450 | — | — |
| Frequency error (circuit) [ppm] | +2.4 | +1.8 | +2.0 | +3.1 | +7.3 | — | — |
| R_ext (−ESR when settled) [Ω] | -112 | -119 ¹ | -115 | -107 | -132 ¹ | — | — |
| REF_CLK duty cycle [%] | 48.61 | 48.13 | 48.53 | 49.05 | 48.55 | — | — |
| REF_CLK rise / fall 10–90 % [ps] | 256 / 214 | 415 / 370 | 304 / 244 | 170 / 141 | 238 / 214 | — | — |
| Start-up: stable REF_CLK (±1 % period) [µs] | 275 | 530 | — | 162 | — | — | — |
| Start-up: 90 % amplitude [µs] | 596 | 1064 | — | 376 | — | — | — |
| Envelope growth time constant τ [µs] | 46.4 | 82.0 | — | 31.5 | — | — | — |
| Bypass square: duty [%] / XI→REF_CLK [ns] | 50.0 / 0.90 | 50.0 / 1.47 | — | 50.0 / 0.58 | — | — | — |
| Bypass sine 0.5 Vpp: duty [%] / delay [ns] | 48.4 / 1.71 | 47.8 / 2.99 | — | 48.9 / 0.82 | — | — | — |
| Bypass I(VDD) square / sine [mA] | 0.185 / 0.533 | 0.142 / 0.396 | — | 0.234 / 0.732 | — | — | — |

| Run (tm) | XI [Vpp] | DL [µW] | I(VDD) [mA] | f [ppm] | duty [%] | start stable [µs] | τ [µs] |
|---|---|---|---|---|---|---|---|
| 27 °C, 1.8 V, ESR 100 Ω, DRV 10, C1 = C2 = 12 pF | 0.751 | 49.3 | 0.364 | +2.4 | 48.61 | 275 | 46.4 |
| C1 = C2 = 10 pF | 0.806 | 45.1 | 0.330 | +24.5 | 48.67 | — | — |
| C1 = C2 = 14 pF ¹ | 0.679 | 49.4 | 0.414 | -14.3 | 48.56 | — | — |

- tm_27_1.8_c10: −R_neg(24 MHz, DRV 10) = 951 Ω, margin 9.5
- tm_27_1.8_c14: −R_neg(24 MHz, DRV 10) = 641 Ω, margin 6.4
- enable: REF_CLK low 0.0 ns after XTAL_EN = 0, first edge 1.0 ns after XTAL_EN = 1 (crystal still ringing), I(VDD) while off and ringing 1.18 µA

ELECTRICAL
| Parameter | Min | Typ | Max | Unit | Corners |
|---|---|---|---|---|---|
| Start-up current I(VDD), no oscillation, DRV 10 | 0.47 | 0.70 | 0.97 | mA | 7 |
| Start-up current I(VDD), no oscillation, DRV 11 | 0.55 | 0.81 | 1.12 | mA | 7 |
| Supply current, XTAL_EN = 0 | 0.2 | 0.2 | 6.9 | nA | 7 |
| XI / XO DC bias (no oscillation) | 0.745 | 0.848 | 0.917 | V | 7 |
| −R_neg at 24 MHz, DRV 10 | 483 | 776 | 1106 | Ω | 7 |
| −R_neg at 24 MHz, DRV 11 | 562 | 889 | 1247 | Ω | 7 |
| Start-up margin −R_neg / 100 Ω, DRV 11 | 5.6 | 8.9 | 12.5 |  | 7 |
| XI amplitude (regulated) | 0.706 | 0.751 | 0.813 | Vpp | 5 |
| XO amplitude | 0.785 | 0.843 | 0.932 | Vpp | 5 |
| Crystal current | 0.659 | 0.702 | 0.764 | mA rms | 5 |
| Crystal drive level, ESR 100 Ω | 43.5 | 49.3 | 58.4 | µW | 5 |
| Supply current in operation | 0.307 | 0.364 | 0.524 | mA | 5 |
| Load capacitance seen by the arm C0 + C_L | 8.45 | 8.70 | 8.73 | pF | 5 |
| Frequency error from the circuit | +1.8 | +2.4 | +7.3 | ppm | 5 |
| REF_CLK duty cycle | 48.1 | 48.6 | 49.1 | % | 5 |
| REF_CLK rise time 10–90 %, 100 fF | 170 | 256 | 415 | ps | 5 |
| REF_CLK fall time 10–90 %, 100 fF | 141 | 214 | 370 | ps | 5 |
| Start-up to stable REF_CLK (±1 % period), DRV 10 | 162 | 275 | 530 | µs | 3 |
| Start-up to 90 % amplitude, DRV 10 | 376 | 596 | 1064 | µs | 3 |
| Envelope growth time constant, DRV 10 | 31.5 | 46.4 | 82.0 | µs | 3 |
| Bypass: XI → REF_CLK delay, CMOS input | 0.58 | 0.90 | 1.47 | ns | 3 |
| Bypass: duty cycle, CMOS input 50 % | 50.0 | 50.0 | 50.0 | % | 3 |
| Bypass: duty cycle, 0.5 Vpp sine | 47.8 | 48.4 | 48.9 | % | 3 |
| Bypass: supply current, CMOS input | 0.142 | 0.185 | 0.234 | mA | 3 |
