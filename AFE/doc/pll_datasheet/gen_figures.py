#!/usr/bin/env python3
"""gen_figures.py - figures of the PLL datasheet (AFE/doc/pll_datasheet/pll_datasheet.md)

Usage (from anywhere; numpy only, rsvg-convert for the PNG copies used by Word):
    python3 AFE/doc/pll_datasheet/gen_figures.py [--no-png]

Model figures are computed from the afe_pll.va default parameters:
  - linear (continuous-time) loop analysis: filter impedance, open / closed loop
  - a behavioural time-domain simulation with the same equations as the
    Verilog-A model (tri-state PFD with ideal reset, charge pump with tanh
    compliance, C4 || (R2 + C3), clamped linear VCO, /N), 25 ps steps.
    It is not a Spectre run of afe_pll.va (no Spectre here).
Transistor-level data (afe_pll_tr.sp, ngspice 42, generic180.lib placeholder
models) comes from data/ (vco_sweep.txt, lock24_tt.csv), written by
data/run_spice.py.  Output: fig/*.svg (+ fig/*.png at 2x).
"""
import os, sys, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from svgplot import Plot, COLORS, _esc

FIG, DATA = os.path.join(HERE, "fig"), os.path.join(HERE, "data")
B, R, G, O, V, K = COLORS

# ---------------------------------------------------------------- parameters
P = dict(icp=20e-6, kvco=200e6, N=20, r2=34.5e3, c3=15.3e-12, c4=1.53e-12,
         f_min=400e6, f_max=500e6, v_fmin=0.5, vdd=1.8, v_cp_marg=0.1)
P_TR = dict(P, kvco=182e6, c3=15.1e-12)        # transistor level, tt (pll_schematic.md 2.4 / 4.1)


def Z(f, p):
    s = 2j * np.pi * f
    r2, c3, c4 = p["r2"], p["c3"], p["c4"]
    return (1 + s * r2 * c3) / (s * (c3 + c4) * (1 + s * r2 * c3 * c4 / (c3 + c4)))


def G_ol(f, p):
    """open-loop gain in the phase domain: Kpd * Z * Kvco / (s N)"""
    s = 2j * np.pi * f
    return p["icp"] / (2 * np.pi) * Z(f, p) * 2 * np.pi * p["kvco"] / s / p["N"]


def metrics(p):
    f = np.logspace(3, 9, 120001)
    g = G_ol(f, p)
    i = np.argmin(abs(abs(g) - 1))
    H = abs(g / (1 + g))
    j = np.where((H < 10 ** (-3 / 20)) & (f > f[np.argmax(H)]))[0][0]
    return dict(fc=f[i], pm=180 + np.degrees(np.angle(g[i])), f3=f[j], peak=20 * np.log10(H.max()),
                fz=1 / (2 * np.pi * p["r2"] * p["c3"]),
                fp=(p["c3"] + p["c4"]) / (2 * np.pi * p["r2"] * p["c3"] * p["c4"]))


# ------------------------------------------------- behavioural time domain
def tsim(fref, N, t_end=12e-6, dt=25e-12, p=P, dec=40):
    icp, kv, fmin, fmax = p["icp"], p["kvco"], p["f_min"], p["f_max"]
    r2, c3, c4, vdd, mg = p["r2"], p["c3"], p["c4"], p["vdd"], p["v_cp_marg"]
    vc = vz = ph = 0.0
    up = dn = 0
    tr = 0.5 / fref
    out = []
    for k in range(int(t_end / dt)):
        t = k * dt
        f = min(max(fmin + kv * (vc - p["v_fmin"]), fmin), fmax)
        ev = []
        if tr < t + dt:
            ev.append((tr - t, 0)); tr += 1 / fref
        php = ph + f * dt
        if np.floor(php / N) > np.floor(ph / N):
            ev.append(((np.floor(php / N) * N - ph) / f, 1))
        ev.sort()
        q = tl = 0.0
        for te, kind in ev:
            q += (up - dn) * (te - tl); tl = te
            if kind == 0:
                up, dn = (up, 0) if dn else (1, dn)
            else:
                up, dn = (0, dn) if up else (up, 1)
        q += (up - dn) * (dt - tl)
        fu = 0.5 * (1 + np.tanh((vdd - mg - vc) / 0.02))
        fd = 0.5 * (1 + np.tanh((vc - mg) / 0.02))
        icp_eff = icp * q / dt * (fu if q > 0 else fd)
        ir = (vc - vz) / r2
        vc += (icp_eff - ir) / c4 * dt
        vz += ir / c3 * dt
        ph = php
        if k % dec == 0:
            out.append((t, vc, f, ph))
    return np.array(out).T


def windows(T, PH, w=0.25e-6, t0=0.05e-6):
    e = np.arange(t0, T[-1] - w, w)
    return e + w, (np.interp(e + w, T, PH) - np.interp(e, T, PH)) / w


def settle_time(T, PH, target, tol=800e-6):
    e, fw = windows(T, PH)
    bad = np.where(abs(fw / target - 1) > tol)[0]
    if len(bad) and bad[-1] == len(e) - 1:
        return None
    return (e[bad[-1] + 1] - 0.25e-6) if len(bad) else e[0] - 0.25e-6


# -------------------------------------------------------------- figures
def fig_vco(sim):
    p = Plot(900, 470)
    ax = p.panel(80, 40, 780, 360, (0, 1.4), (350, 600), xlabel="Control voltage V(CDR_CH_OUT_PLL)  [V]",
                 ylabel="CLK_BIT_A frequency  [MHz]", title="VCO tuning curve", legend="tl")
    v = np.linspace(0, 1.4, 281)
    fm = np.clip(P["f_min"] + P["kvco"] * (v - P["v_fmin"]), P["f_min"], P["f_max"]) / 1e6
    ax.band(400, 500, color=B, opacity=0.05)
    ax.line(v, fm, B, 2.6, label="afe_pll.va model (400–500 MHz clamp, 200 MHz/V)")
    for (c, col, mk, lab) in (("tt", G, "o", "transistor tt, 27 °C, 1.8 V"),
                              ("ss", R, "s", "transistor ss, 125 °C, 1.62 V"),
                              ("ff", O, "^", "transistor ff, −40 °C, 1.98 V")):
        if c in sim:
            vv, ff = sim[c]
            ax.line(vv, ff / 1e6, col, 1.3, dash="3,3")
            ax.points(vv, ff / 1e6, col, label=lab, marker=mk)
    ax.hline(480, B, "6,4", text="480 MHz (N · f_ref)")
    ax.hline(520, K, "2,4", text="520 MHz = 20 × 26 MHz (must not be reported as lock)", anchor="start")
    ax.marker(0.9, 480, "0.9 V / 480 MHz", B, 8, 16)
    p.save(os.path.join(FIG, "vco_tuning.svg"))


def fig_cp():
    p = Plot(900, 330)
    ax = p.panel(80, 40, 780, 230, (0, 1.8), (0, 1.1), xlabel="Control voltage V(CDR_CH_OUT_PLL)  [V]",
                 ylabel="Current factor", title="Charge-pump compliance (fraction of icp delivered)", legend="bl")
    v = np.linspace(0, 1.8, 721)
    ax.line(v, 0.5 * (1 + np.tanh((1.8 - 0.1 - v) / 0.02)), R, 2.4, label="UP (source) factor fc_up")
    ax.line(v, 0.5 * (1 + np.tanh((v - 0.1) / 0.02)), B, 2.4, dash="7,4", label="DN (sink) factor fc_dn")
    ax.vline(0.1, K, text="v_cp_marg")
    ax.vline(1.7, K, text="VDD − v_cp_marg", left=True)
    ax.vline(0.9, G, text="lock 0.9 V", top=False)
    p.save(os.path.join(FIG, "cp_compliance.svg"))


def fig_filter_schematic():
    s = []
    L = lambda x1, y1, x2, y2: s.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#222" stroke-width="2"/>')
    T = lambda x, y, t, a="middle", sz=14, w="normal": s.append(f'<text x="{x}" y="{y}" font-size="{sz}" text-anchor="{a}" font-weight="{w}">{_esc(t)}</text>')
    def cap(x, y):  # vertical capacitor centred at (x, y)
        L(x - 18, y - 5, x + 18, y - 5); L(x - 18, y + 5, x + 18, y + 5)
    def res(x, y1, y2):
        n, h = 6, (y2 - y1) / 6
        pts = [(x, y1)] + [(x + (10 if i % 2 else -10), y1 + h * (i + 0.5)) for i in range(n)] + [(x, y2)]
        s.append('<polyline fill="none" stroke="#222" stroke-width="2" points="' + " ".join(f"{a},{b}" for a, b in pts) + '"/>')
    def gnd(x, y):
        L(x, y, x, y + 10); L(x - 14, y + 10, x + 14, y + 10); L(x - 9, y + 15, x + 9, y + 15); L(x - 4, y + 20, x + 4, y + 20)
    # charge pump source
    s.append('<circle cx="120" cy="150" r="24" fill="white" stroke="#222" stroke-width="2"/>')
    L(120, 165, 120, 135); s.append('<polygon points="120,130 114,142 126,142" fill="#222"/>')
    T(88, 147, "I_CP = ±icp", sz=13, a="end"); T(88, 164, "(UP / DN)", sz=12, a="end")
    L(120, 126, 120, 70); L(120, 174, 120, 250); gnd(120, 250)
    L(120, 70, 640, 70)
    s.append('<circle cx="120" cy="70" r="3" fill="#222"/>')
    # C4
    L(300, 70, 300, 145); cap(300, 150); L(300, 155, 300, 250); gnd(300, 250); T(330, 155, "C4  1.53 pF", "start")
    s.append('<circle cx="300" cy="70" r="4" fill="#222"/>')
    # R2 + C3
    L(470, 70, 470, 95); res(470, 95, 155); L(470, 155, 470, 185); cap(470, 190); L(470, 195, 470, 250); gnd(470, 250)
    T(492, 130, "R2  34.5 kΩ", "start"); T(492, 195, "C3  15.3 pF", "start"); T(492, 172, "n_z", "start", 12)
    s.append('<circle cx="470" cy="70" r="4" fill="#222"/>')
    # discharge switches
    T(640, 150, "PLL_EN = 0: both nodes", "start", 12); T(640, 166, "discharged (r_dis = 1 kΩ)", "start", 12)
    s.append('<circle cx="640" cy="70" r="5" fill="white" stroke="#222" stroke-width="2"/>')
    T(655, 60, "CDR_CH_OUT_PLL", "start", 14, "bold"); T(655, 92, "→ VCO and CDR_V_IN_2 of afe_cdr", "start", 12)
    svg = "\n".join(s)
    open(os.path.join(FIG, "loop_filter.svg"), "w").write(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="290" viewBox="0 0 900 290" '
        f'font-family="Arial, Helvetica, sans-serif"><rect width="900" height="290" fill="white"/>{svg}</svg>')


def fig_filter_z():
    f = np.logspace(3, 9, 1200)
    z = Z(f, P)
    m = metrics(P)
    p = Plot(900, 560)
    a1 = p.panel(90, 40, 770, 210, (1e3, 1e9), (1e2, 1e8), True, True, ylabel="|Z|  [Ω]",
                 title="Loop-filter transimpedance Z(f) = V(CDR_CH_OUT_PLL) / I_CP")
    a1.line(f, abs(z), B, 2.4, label="C4 ‖ (R2 + C3)")
    a1.line(f, 1 / (2 * np.pi * f * (P["c3"] + P["c4"])), K, 1.2, dash="4,4", label="1 / (2πf (C3 + C4))")
    a1.hline(P["r2"] * P["c3"] / (P["c3"] + P["c4"]), K, "2,4", text="R2 · C3 / (C3 + C4) = 31.4 kΩ")
    a1.vline(m["fz"], G, text=f"zero {m['fz'] / 1e3:.0f} kHz"); a1.vline(m["fp"], R, text=f"pole {m['fp'] / 1e6:.2f} MHz")
    a2 = p.panel(90, 300, 770, 200, (1e3, 1e9), (-95, -25), True, False, xlabel="Frequency  [Hz]",
                 ylabel="Phase  [°]", yticks=[-90, -75, -60, -45, -30])
    a2.line(f, np.degrees(np.angle(z)), B, 2.4)
    a2.vline(m["fz"], G); a2.vline(m["fp"], R)
    a2.vline(np.sqrt(m["fz"] * m["fp"]), K, text="max. phase lead at √(f_z f_p) = 1.0 MHz", top=False)
    p.save(os.path.join(FIG, "filter_impedance.svg"))


def fig_open_loop():
    f = np.logspace(4, 8.5, 1500)
    cases = [(P, B, None, "model, N = 20 (24 MHz)"), (dict(P, N=25), O, "7,4", "model, N = 25 (19.2 MHz)"),
             (P_TR, G, "3,3", "transistor tt (K_vco 182 MHz/V), N = 20")]
    p = Plot(900, 600)
    a1 = p.panel(90, 40, 770, 240, (1e4, 10 ** 8.5), (-40, 80), True, False, ylabel="|G(f)|  [dB]",
                 title="Open-loop gain G = (icp / 2π) · Z(f) · (2π kvco) / (s N)", legend="bl")
    a2 = p.panel(90, 330, 770, 200, (1e4, 10 ** 8.5), (-180, -100), True, False, xlabel="Frequency  [Hz]",
                 ylabel="Phase  [°]", yticks=[-180, -160, -140, -120, -100], legend="br")
    a1.hline(0, K, "3,3")
    for q, col, d, lab in cases:
        g = G_ol(f, q); m = metrics(q)
        a1.line(f, 20 * np.log10(abs(g)), col, 2.2, d, lab)
        a2.line(f, np.degrees(np.angle(g)), col, 2.2, d)
        dx, dy, an = {B: (14, -8, "start"), O: (-14, -8, "end"), G: (0, -22, "middle")}[col]
        a2.marker(m["fc"], -180 + m["pm"], f"f_c {m['fc'] / 1e6:.2f} MHz, PM {m['pm']:.1f}°", col, dx, dy, an)
    a1.vline(24e6, K, text="f_ref 24 MHz"); a2.vline(24e6, K)
    a2.hline(-180, K, "3,3")
    p.save(os.path.join(FIG, "open_loop.svg"))


def fig_closed_loop():
    f = np.logspace(4, 8.5, 1500)
    p = Plot(900, 470)
    ax = p.panel(90, 40, 770, 360, (1e4, 10 ** 8.5), (-40, 6), True, False, xlabel="Frequency  [Hz]",
                 ylabel="Magnitude  [dB]", title="Closed loop: reference → output H = G / (1 + G) (÷ N), "
                 "VCO-noise → output E = 1 / (1 + G)", legend="bl")
    for q, col, d, lab in ((P, B, None, "N = 20"), (dict(P, N=25), O, "7,4", "N = 25")):
        g = G_ol(f, q); m = metrics(q)
        ax.line(f, 20 * np.log10(abs(g / (1 + g))), col, 2.4, d, f"H, {lab}: f_−3dB {m['f3'] / 1e6:.2f} MHz, peaking {m['peak']:.1f} dB")
        ax.line(f, 20 * np.log10(abs(1 / (1 + g))), col, 1.6, "2,3" if d is None else "8,3,2,3", f"E (high-pass), {lab}")
    ax.hline(-3, K, "3,3", text="−3 dB", anchor="start")
    ax.vline(24e6, K, text="f_ref")
    p.save(os.path.join(FIG, "closed_loop.svg"))


def fig_step():
    # linear phase-domain step response: output frequency for a reference-frequency step
    dt, tend = 1e-9, 8e-6
    def run(q):
        th_e = vc = vz = 0.0; t, y = [], []
        icp, kv, N, r2, c3, c4 = q["icp"], q["kvco"], q["N"], q["r2"], q["c3"], q["c4"]
        th_r = th_f = 0.0; df = 1.0  # 1 Hz step at the reference (normalized)
        for k in range(int(tend / dt)):
            th_r += 2 * np.pi * df * dt
            i = icp / (2 * np.pi) * (th_r - th_f)
            ir = (vc - vz) / r2
            vc += (i - ir) / c4 * dt; vz += ir / c3 * dt
            fo = kv * vc
            th_f += 2 * np.pi * fo / N * dt
            if k % 5 == 0: t.append(k * dt); y.append(fo / N)
        return np.array(t), np.array(y)
    p = Plot(900, 420)
    ax = p.panel(90, 40, 770, 310, (0, 8), (0, 1.4), xlabel="Time after the step  [µs]",
                 ylabel="f_out / (N · Δf_ref)", title="Linear step response: output frequency after a "
                 "reference-frequency step", legend="br")
    for q, col, d, lab in ((P, B, None, "N = 20"), (dict(P, N=25), O, "7,4", "N = 25"), (P_TR, G, "3,3", "transistor K_vco, N = 20")):
        t, y = run(q)
        ax.line(t * 1e6, y, col, 2.4, d, lab)
        i = np.argmax(y)
        j = np.where(abs(y - 1) > 0.02)[0][-1]
        print(f"step {lab}: overshoot {100 * (y[i] - 1):.1f} % at {t[i] * 1e6:.3f} us, within 2 % after {t[j] * 1e6:.3f} us")
        if col == B:
            ax.marker(t[i] * 1e6, y[i], f"overshoot {100 * (y[i] - 1):.0f} % at {t[i] * 1e6:.2f} µs", col, 8, -8)
    ax.band(1 - 8e-4 * 50, 1 + 8e-4 * 50, G, 0.0)
    ax.hline(1, K, "3,3")
    p.save(os.path.join(FIG, "step_response.svg"))


def fig_lock(ts, tr):
    T, VC, F, PH = ts["24"]
    p = Plot(900, 640)
    a1 = p.panel(90, 40, 770, 240, (0, 8), (380, 520), ylabel="CLK_BIT_A  [MHz]",
                 title="Lock transient after PLL_EN, 24 MHz, REFSEL = 01 (÷20), loop filter discharged", legend="br")
    a2 = p.panel(90, 330, 770, 240, (0, 8), (0, 1.4), xlabel="Time after PLL_EN  [µs]",
                 ylabel="V(CDR_CH_OUT_PLL)  [V]", legend="br")
    e, fw = windows(T, PH, 0.05e-6)
    a1.line(T * 1e6, F / 1e6, B, 1.0, label="model: instantaneous VCO frequency")
    a1.line(e * 1e6, fw / 1e6, R, 2.2, label="model: mean over 50 ns")
    a1.hline(480, K, "3,3", text="480 MHz")
    a2.line(T * 1e6, VC, B, 2.0, label="model (behavioural sim of afe_pll.va)")
    if tr is not None:
        a2.line(tr[0] * 1e6, tr[1], G, 1.6, "4,3", "transistor tt (ngspice, afe_pll_tr.sp)")
        if len(tr) > 2:
            a1.line(tr[0] * 1e6, tr[2] / 1e6, G, 1.6, "4,3", "transistor tt: mean over 50 ns")
    a2.hline(0.9, K, "3,3", text="0.9 V")
    st = settle_time(T, PH, 480e6)
    a1.vline(st * 1e6, G, text=f"model inside ±800 ppm after {st * 1e6:.2f} µs", top=False)
    p.save(os.path.join(FIG, "lock_transient.svg"))


def fig_settle(ts):
    p = Plot(900, 460)
    ax = p.panel(90, 40, 770, 350, (0, 12), (1, 3e5), False, True, xlabel="Time after PLL_EN  [µs]",
                 ylabel="|f_CLK_BIT_A / (N f_ref) − 1|  [ppm]", title="Frequency error in 0.25 µs windows (model)",
                 yfmt=lambda v: f"{v:g}", legend="tr")
    for key, fr, N, col, lab in (("24", 24e6, 20, B, "24 MHz, ÷20"), ("19", 19.2e6, 25, O, "19.2 MHz, ÷25"),
                                 ("26", 26e6, 20, R, "26 MHz, ÷20 (VCO at f_max, never locks)")):
        T, VC, F, PH = ts[key]
        e, fw = windows(T, PH)
        err = np.maximum(abs(fw / (N * fr) - 1) * 1e6, 1.0)
        st = settle_time(T, PH, N * fr)
        ax.line(e * 1e6, err, col, 2.2, label=lab + (f": settled {st * 1e6:.2f} µs" if st else ""))
    ax.hline(800, G, "6,4", text="±800 ppm: settling criterion (spec 4.3: within 45 µs)", below=True)
    ax.hline(1000, R, "2,4", text="±0.1 % = ±5 counts: lock-detector tolerance", anchor="start")
    ax.hline(200, K, "3,3", text="±200 ppm: locked-frequency check")
    p.save(os.path.join(FIG, "settling.svg"))


def fig_budget(st24, st19):
    p = Plot(900, 300)
    ax = p.panel(190, 50, 670, 180, (0, 210), (0, 3), xlabel="Time after PLL_EN  [µs]",
                 title="Lock-time budget (24 MHz; one lock-detector window = 256 / 24 MHz = 10.7 µs)",
                 yticks=[], legend="br")
    rows = [("spec 4.3 / LOCK_TO", [(0, 100, "#dddddd", "PLL_EN → pll_lock ≤ 100 µs"), (100, 200, "#f2e0c9", "usb_pwr_seq LOCK_TO = 200 µs")]),
            ("PLL requirement", [(0, 45, "#c9d9f2", "settle ≤ 45 µs"), (45, 45 + 53.3, "#d9ead3", "≤ 5 windows: 53 µs")]),
            ("model / transistor tt", [(0, st24, B, ""), (st24, st24 + 53.3, "#d9ead3", f"settle {st24:.1f} µs + ≤ 5 windows")])]
    for i, (lab, segs) in enumerate(rows):
        y = 2.75 - i
        ax.text(-8, y - 0.38, lab, size=12, anchor="end")
        for a, b, col, t in segs:
            X1, X2 = ax._tx(a), ax._tx(b); Y1, Y2 = ax._ty(y), ax._ty(y - 0.55)
            p.raw(f'<rect x="{X1:.1f}" y="{Y1:.1f}" width="{X2 - X1:.1f}" height="{Y2 - Y1:.1f}" fill="{col}" stroke="#666"/>')
            if t:
                ax.text((a + b) / 2, y - 0.36, t, size=11, anchor="middle")
    ax.vline(100, R, text="100 µs")
    p.save(os.path.join(FIG, "lock_budget.svg"))


def fig_sensitivity():
    k = np.logspace(np.log10(0.25), np.log10(4), 61)
    fc, pm = [], []
    for x in k:
        m = metrics(dict(P, icp=P["icp"] * x)); fc.append(m["fc"]); pm.append(m["pm"])
    b = np.logspace(np.log10(2), np.log10(40), 40); pmb, fcb = [], []
    for x in b:  # keep C3 + C4 and R2 * C3 scaling so f_c stays centred (C4 = C3 / b)
        c4 = P["c3"] / x
        m = metrics(dict(P, c4=c4)); pmb.append(m["pm"]); fcb.append(m["fc"])
    p = Plot(900, 470)
    a1 = p.panel(90, 50, 340, 330, (0.25, 4), (0.3e6, 3e6), True, True,
                 xlabel="Loop-gain factor icp·kvco / (20 µA · 200 MHz/V)", ylabel="f_c  [Hz]",
                 title="Crossover and phase margin vs loop gain", xticks=[0.25, 0.5, 1, 2, 4], xfmt=lambda v: f"{v:g}",
                 yticks=[3e5, 5e5, 1e6, 2e6, 3e6], yfmt=lambda v: f"{v / 1e6:g} M", legend="tl")
    a1.line(k, fc, B, 2.4, label="f_c")
    a1.vline(1, K, text="default"); a1.vline(182 / 200, G, text="tt", top=False)
    a1b = p.panel(520, 50, 340, 330, (0.25, 4), (30, 60), True, False, xlabel="Loop-gain factor",
                  ylabel="Phase margin  [°]", title="", xticks=[0.25, 0.5, 1, 2, 4], xfmt=lambda v: f"{v:g}", legend="bl")
    a1b.line(k, pm, R, 2.4, label="PM vs loop gain (C3 / C4 = 10)")
    a1b.vline(1, K)
    a1b.hline(45, K, "3,3", text="45°")
    p.save(os.path.join(FIG, "sensitivity.svg"))
    for x in (0.5, 182 / 200, 1.0, 1.5, 2.0):
        m = metrics(dict(P, icp=P["icp"] * x))
        print(f"loop gain x{x:.2f}: fc {m['fc'] / 1e6:.3f} MHz, PM {m['pm']:.1f} deg, peaking {m['peak']:.2f} dB")
    return k, fc, pm


def fig_block():
    s = []
    def box(x, y, w, h, t, sub=None, fill="#eef3fb"):
        s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="#1f4e9c" stroke-width="1.8"/>')
        s.append(f'<text x="{x + w / 2}" y="{y + h / 2 + (0 if sub else 5)}" font-size="14" font-weight="bold" text-anchor="middle">{_esc(t)}</text>')
        if sub:
            s.append(f'<text x="{x + w / 2}" y="{y + h / 2 + 17}" font-size="11.5" text-anchor="middle">{_esc(sub)}</text>')
    def arr(pts, col="#222", lab=None, lx=0, ly=-6, anchor="middle"):
        s.append(f'<polyline points="{" ".join(f"{a},{b}" for a, b in pts)}" fill="none" stroke="{col}" stroke-width="1.8" marker-end="url(#ah)"/>')
        if lab:
            (a, b), (c, d) = pts[-2], pts[-1]
            s.append(f'<text x="{(a + c) / 2 + lx}" y="{(b + d) / 2 + ly}" font-size="11.5" text-anchor="{anchor}">{_esc(lab)}</text>')
    def pin(x, y, t, side="l"):
        s.append(f'<rect x="{x - 5}" y="{y - 5}" width="10" height="10" fill="#1f4e9c"/>')
        a = "end" if side == "l" else "start"
        s.append(f'<text x="{x + (-10 if side == "l" else 10)}" y="{y + 4}" font-size="12.5" font-weight="bold" text-anchor="{a}">{_esc(t)}</text>')
    s.append('<defs><marker id="ah" markerWidth="9" markerHeight="8" refX="8" refY="4" orient="auto"><polygon points="0,0 9,4 0,8" fill="#222"/></marker></defs>')
    s.append('<rect x="120" y="30" width="700" height="430" rx="10" fill="none" stroke="#888" stroke-dasharray="6,4"/>')
    s.append('<text x="130" y="50" font-size="13" fill="#555">afe_pll (VDD18A / VSS18A, 1.8 V)</text>')
    pin(120, 120, "CDR_FREF"); pin(120, 400, "PLL_EN"); pin(120, 300, "REFSEL1/0")
    pin(820, 120, "CLK_BIT_A", "r"); pin(820, 210, "CLK60_A", "r"); pin(820, 70, "REF_DIG", "r"); pin(820, 400, "CDR_CH_OUT_PLL", "r")
    box(150, 100, 60, 40, "buf")
    box(250, 95, 90, 50, "PFD", "tri-state")
    box(375, 95, 100, 50, "Charge pump", "±icp 20 µA")
    box(375, 190, 100, 60, "Loop filter", "C4 ‖ (R2+C3)")
    box(540, 95, 110, 50, "Ring VCO", "400–500 MHz")
    box(690, 190, 80, 40, "÷ 8", "div60", "#f3f7ee")
    box(370, 280, 100, 50, "÷ N", "20 / 25", "#f3f7ee")
    box(150, 370, 160, 50, "Enable / UVLO", "PLL_EN ∧ VDD > vdd_min", "#fbf3e6")
    arr([(120, 120), (150, 120)]); arr([(210, 120), (250, 120)], lab="ref")
    arr([(180, 100), (180, 70), (815, 70)], lab="t_ref_dly 0.2 ns", lx=180)
    arr([(340, 112), (375, 112)], lab="UP", ly=-5); arr([(340, 130), (375, 130)], lab="DN", ly=14)
    arr([(425, 145), (425, 190)], lab="I_CP", lx=26, ly=4)
    arr([(475, 220), (510, 220), (510, 120), (540, 120)], lab="")
    s.append('<text x="480" y="180" font-size="11.5">V_C</text>')
    arr([(510, 220), (510, 400), (815, 400)], lab="→ CDR_V_IN_2 of afe_cdr (coarse)", lx=40)
    arr([(650, 120), (815, 120)], lab="480 MHz")
    arr([(670, 120), (670, 210), (690, 210)])
    arr([(770, 210), (815, 210)], lab="60 MHz", lx=-4, ly=-8)
    arr([(670, 210), (670, 305), (470, 305)])
    arr([(370, 305), (295, 305), (295, 145)], lab="fb = f_VCO / N", lx=-50, ly=40)
    arr([(120, 300), (230, 300), (230, 318), (370, 318)], lab="", ly=-4)
    s.append('<text x="250" y="335" font-size="11">N select (prog_div = 1)</text>')
    arr([(120, 400), (150, 400)])
    s.append('<text x="150" y="440" font-size="11" fill="#c0392b">en = 0: PFD / CP reset, VCO and ÷8 stopped low,</text>')
    s.append('<text x="150" y="454" font-size="11" fill="#c0392b">loop filter discharged (restart at f_min)</text>')
    svg = "\n".join(s)
    open(os.path.join(FIG, "block_diagram.svg"), "w").write(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="480" viewBox="0 0 1000 480" '
        f'font-family="Arial, Helvetica, sans-serif"><rect width="1000" height="480" fill="white"/>{svg}</svg>')


def fig_timing():
    s = []
    X0, PX = 170, 22.0     # x of t = 0 and pixels per VCO period
    rows = ["PLL_EN", "CLK_BIT_A", "CLK60_A", "CDR_FREF", "REF_DIG"]
    yr = {r: 60 + 62 * i for i, r in enumerate(rows)}
    def wave(name, segs):  # segs: list of (t_start_periods, level)
        y = yr[name]; hi, lo = y, y + 30
        pts, last = [], None
        for t, lv in segs:
            X = X0 + t * PX; Y = hi if lv else lo
            if last is not None: pts.append((X, last))
            pts.append((X, Y)); last = Y
        pts.append((X0 + 34 * PX, last))
        pts = [(min(max(a, X0), X0 + 34 * PX), b) for a, b in pts]
        s.append(f'<polyline points="{" ".join(f"{a:.1f},{b}" for a, b in pts)}" fill="none" stroke="#1f4e9c" stroke-width="2"/>')
        s.append(f'<text x="{X0 - 30}" y="{y + 20}" font-size="13" font-weight="bold" text-anchor="end">{name}</text>')
    t_en, t_off = 4.0, 27.0
    wave("PLL_EN", [(0, 0), (t_en, 1), (t_off, 0)])
    clk = [(0, 0)]; c60 = [(0, 0)]
    t = t_en + 0.6
    k = 0
    while t + 1 <= t_off + 0.6:
        clk += [(t, 1), (t + 0.5, 0)]
        if k % 8 == 0: c60.append((t, 1))
        if k % 8 == 4: c60.append((t, 0))
        t += 1; k += 1
    c60.append((t_off + 0.6, 0))
    wave("CLK_BIT_A", clk); wave("CLK60_A", c60)
    rp = 10.0
    ref = [(0, 1)] + [(x, lv) for i in range(0, 4) for x, lv in ((i * rp + 1.5, 0), (i * rp + 6.5, 1))]
    wave("CDR_FREF", ref)
    wave("REF_DIG", [(0, 1)] + [(x + 0.4, lv) for x, lv in ref[1:]])
    def mark(t, txt, y1=40, y2=380, col="#c0392b", anchor="start"):
        X = X0 + t * PX
        s.append(f'<line x1="{X}" y1="{y1}" x2="{X}" y2="{y2}" stroke="{col}" stroke-dasharray="4,3"/>')
        s.append(f'<text x="{X + (4 if anchor == "start" else -4)}" y="{y1 + 4}" font-size="11.5" fill="{col}" text-anchor="{anchor}">{_esc(txt)}</text>')
    mark(t_en + 0.6, "1st CLK_BIT_A rise = 1st CLK60_A rise (divider restarts)")
    mark(t_off, "PLL_EN falls: clocks stop low, filter discharged", 400, 40, anchor="end")
    X = X0 + (t_en + 0.6 + 8) * PX
    s.append(f'<text x="{X0 + (t_en + 4.6) * PX}" y="{yr["CLK60_A"] + 48}" font-size="11.5" text-anchor="middle">'
             f'8 × T_bit = 16.7 ns, high 4 / low 4</text>')
    s.append(f'<text x="{X0 + 34 * PX}" y="{yr["REF_DIG"] + 48}" font-size="11.5" text-anchor="end">REF_DIG = CDR_FREF delayed by t_ref_dly; runs while VDD18A is up, independent of PLL_EN</text>')
    s.append(f'<text x="{X0}" y="{yr["CLK_BIT_A"] - 8}" font-size="11.5" fill="#555">low (stopped)</text>')
    s.append(f'<text x="{X0 + 4 * PX}" y="{yr["PLL_EN"] + 48}" font-size="11" fill="#555">not to scale: the VCO starts near f_min, and the frequency settles in ≈ 3 µs</text>')
    svg = "\n".join(s)
    open(os.path.join(FIG, "timing.svg"), "w").write(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="980" height="420" viewBox="0 0 980 420" '
        f'font-family="Arial, Helvetica, sans-serif"><rect width="980" height="420" fill="white"/>{svg}</svg>')


# -------------------------------------------------------------- main
def load_sim():
    sim, tr = {}, None
    fn = os.path.join(DATA, "vco_sweep.txt")
    if os.path.exists(fn):
        rows = [l.split() for l in open(fn) if l.strip()]
        for c in ("tt", "ss", "ff"):
            r = [(float(a[1]), float(a[2])) for a in rows if a[0] == c]
            if r: sim[c] = tuple(np.array(x) for x in zip(*sorted(r)))
    fn = os.path.join(DATA, "lock24_tt.csv")
    if os.path.exists(fn):
        tr = np.loadtxt(fn, delimiter=",", skiprows=1).T
        tr[2][tr[0] < 50e-9] = np.nan  # 50 ns window not yet filled after PLL_EN
    return sim, tr


def main():
    os.makedirs(FIG, exist_ok=True)
    sim, tr = load_sim()
    ts = {k: tsim(fr, N) for k, fr, N in (("24", 24e6, 20), ("19", 19.2e6, 25), ("26", 26e6, 20))}
    st = {k: settle_time(ts[k][0], ts[k][3], N * fr) for k, fr, N in (("24", 24e6, 20), ("19", 19.2e6, 25), ("26", 26e6, 20))}
    fig_block(); fig_filter_schematic(); fig_timing()
    fig_vco(sim); fig_cp(); fig_filter_z(); fig_open_loop(); fig_closed_loop(); fig_step()
    fig_lock(ts, tr); fig_settle(ts); fig_budget(st["24"] * 1e6, st["19"] * 1e6); fig_sensitivity()
    # numbers quoted in the datasheet
    for name, q in (("model N=20", P), ("model N=25", dict(P, N=25)), ("transistor tt N=20", P_TR), ("transistor tt N=25", dict(P_TR, N=25))):
        m = metrics(q)
        print(f"{name}: fc {m['fc'] / 1e6:.3f} MHz, PM {m['pm']:.1f} deg, f-3dB {m['f3'] / 1e6:.3f} MHz, "
              f"peaking {m['peak']:.2f} dB, fz {m['fz'] / 1e3:.1f} kHz, fp {m['fp'] / 1e6:.3f} MHz")
    for k, (T, VC, F, PH) in ts.items():
        e, fw = windows(T, PH)
        cnt = fw[-1] * 256 / {"24": 24e6, "19": 19.2e6, "26": 26e6}[k]   # lock-detector window count once settled
        print(f"tsim {k}: settle {st[k] and st[k] * 1e6}, f_end {fw[-1] / 1e6:.4f} MHz, vc_end {VC[-1]:.3f} V, "
              f"vc_peak {VC.max():.3f} V at {T[np.argmax(VC)] * 1e6:.2f} us, f_peak {F.max() / 1e6:.1f} MHz, window count {cnt:.0f}")
    if "--no-png" not in sys.argv:
        for f in sorted(os.listdir(FIG)):
            if f.endswith(".svg"):
                subprocess.run(["rsvg-convert", "-z", "2", "-o", os.path.join(FIG, f[:-4] + ".png"), os.path.join(FIG, f)], check=True)
    print("figures in", FIG)


if __name__ == "__main__":
    main()
