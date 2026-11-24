### VCO tuning (transistor level, BFR93A / 1SV305 / LQW18)

| case | T (C) | VDD (V) | f(0 V) MHz | f(4.5 V) MHz | V @ 480 MHz | Kvco MHz/V | Vpp at CDCM IN |
|---|---|---|---|---|---|---|---|
| vco_-40_4.82 | -40 | 4.82 | 393.5 | 511.3 | 2.83 | 21.7 | 0.58 .. 0.67 |
| vco_27_4.60 | 27 | 4.60 | 386.2 | 504.3 | 3.17 | 20.4 | 0.55 .. 0.61 |
| vco_27_4.82 | 27 | 4.82 | 386.1 | 504.2 | 3.18 | 20.4 | 0.60 .. 0.67 |
| vco_27_5.00 | 27 | 5.00 | 386.0 | 504.1 | 3.18 | 20.4 | 0.64 .. 0.71 |
| vco_85_4.82 | 85 | 4.82 | 381.3 | 502.9 | 3.26 | 20.6 | 0.61 .. 0.67 |
| vcotol_m2_-40 | -40 | 4.82 | 397.3 | 516.3 | 2.62 | 22.8 | 0.57 .. 0.66 |
| vcotol_p2_85 | 85 | 4.82 | 377.8 | 498.2 | 3.48 | 19.6 | 0.62 .. 0.68 |

Start-up (VCO_OFF 1 -> 0, VTUNE 3.2 V): oscillation at 479.6 MHz, 0.62 Vpp, after 303 ns; stop (VCO_OFF 0 -> 1) within 48 ns.

### Loop, small signal (Kvco spread of the VCO cases)

| setting | Kvco MHz/V | fc kHz | PM deg | GM dB | peaking dB |
|---|---|---|---|---|---|
| 24 MHz: R 1, N 10, 1.25 mA | 19.6 | 395 | 61.0 | 25.7 | 0.91 |
| 24 MHz: R 1, N 10, 1.25 mA | 20.5 | 411 | 60.4 | 25.3 | 0.89 |
| 24 MHz: R 1, N 10, 1.25 mA | 22.8 | 451 | 58.9 | 24.4 | 0.86 |
| 19.2 MHz: R 2, N 25, 3.125 mA | 19.6 | 395 | 61.0 | 25.7 | 0.91 |
| 19.2 MHz: R 2, N 25, 3.125 mA | 20.5 | 411 | 60.4 | 25.3 | 0.89 |
| 19.2 MHz: R 2, N 25, 3.125 mA | 22.8 | 451 | 58.9 | 24.4 | 0.86 |

### Loop transients (ngspice: XSPICE PFD, CP with compliance and 2 % mismatch, filter, VCO curve)

| case | f_ref MHz | VCO curve | t_lock (us) | t_relock (us) | VTUNE (V) | f error ppm | f peak MHz | ref spur dBc | PJ ps | discharge to 50 mV (us) |
|---|---|---|---|---|---|---|---|---|---|---|
| loop_24 | 24.0 | vco_27_4.82 | 12.8 | 11.1 | 3.178 | 15.6 | 486.7 | -89.1 | 0.023 | 3.5 |
| loop_24_cold | 24.0 | vco_-40_4.82 | 12.1 | 11.8 | 2.828 | -5.8 | 486.6 | -91.4 | 0.018 | 3.1 |
| loop_24_hot | 24.0 | vco_85_4.82 | 13.3 | 12.9 | 3.265 | 3.2 | 486.3 | -86.0 | 0.033 | 3.6 |
| loop_24_slow | 24.0 | vcotol_p2_85 | 14.9 | 12.2 | 3.484 | -9.8 | 486.3 | -92.5 | 0.016 | 3.8 |
| loop_19 | 19.2 | vco_27_4.82 | 11.9 | 11.5 | 3.178 | 2.2 | 489.3 | -78.7 | 0.077 | 3.5 |

REFSEL 10 at 26 MHz, model division /20 (target 520 MHz), VCO -40 C: no lock, VCO at 507.1 MHz (VTUNE 4.25 V at the charge-pump limit; afe_pll.va: f_max 500 MHz).

REFSEL 10 at 26 MHz, model division /20 (target 520 MHz), VCO fastest case: L -2 %, -40 C: no lock, VCO at 512.1 MHz (VTUNE 4.25 V at the charge-pump limit; afe_pll.va: f_max 500 MHz).

### In-band phase noise (ADF4002 PNSYNTH -222 dBc/Hz; reference and VCO not included)

| reference | L(f) at 480 MHz, dBc/Hz |
|---|---|
| 24 MHz (PFD 24 MHz) | -122 |
| 19.2 MHz (PFD 9.6 MHz) | -118 |

