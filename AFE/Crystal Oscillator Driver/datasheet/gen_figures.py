#!/usr/bin/env python3
"""gen_figures.py - figures and result tables of the crystal oscillator datasheet

Usage (numpy only; rsvg-convert for the PNG copies used by Word):
    python3 "AFE/Crystal Oscillator Driver/datasheet/gen_figures.py"

Reads the ngspice results that sim/run_all.py copied to data/<run>/
(results_<case>.json, *_win.csv, *_env.csv) and writes
  fig/*.svg (+ .png at 2x)       the datasheet figures
  data/tables.md                 the corner tables quoted in xosc_datasheet.md
The plot helper is AFE/doc/pll_datasheet/svgplot.py (imported, not copied).
"""
import glob
import json
import math
import os
import shutil
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DUT = os.path.dirname(HERE)
ROOT = os.path.abspath(os.path.join(DUT, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "AFE", "doc", "pll_datasheet"))
from svgplot import Plot, COLORS  # noqa: E402

FIG, DATA = os.path.join(HERE, "fig"), os.path.join(HERE, "data")
B, R, G, O, V, K = COLORS
F0, CM, C0 = 24e6, 2.88e-15, 0.83e-12
CORNERS = [("tm_27_1.8", "tm 27 °C 1.8 V"), ("ws_125_1.62", "ws 125 °C 1.62 V"),
           ("ws_-40_1.62", "ws −40 °C 1.62 V"), ("wp_-40_1.98", "wp −40 °C 1.98 V"),
           ("wp_125_1.98", "wp 125 °C 1.98 V"), ("wo_27_1.8", "wo 27 °C 1.8 V"), ("wz_27_1.8", "wz 27 °C 1.8 V")]


def res(run, case):
    p = os.path.join(DATA, run, f"results_{case}.json")
    if not os.path.exists(p):
        return None
    r = json.load(open(p))
    if case == "start":
        # growth time constant after the XTAL_EN bias transient (envelope minimum)
        t, e = np.array(r["env_t"]), np.array(r["env"])
        fin = e[-5:].mean()
        imin = int(np.argmin(e[t < r["t90"] + 1e-6]))
        g = (e > 0.02 * fin) & (e < 0.3 * fin) & (np.arange(len(e)) > imin)
        r["tau"] = float(1 / np.polyfit(t[g], np.log(e[g]), 1)[0]) if g.sum() > 3 else float("nan")
    return r


def csv(run, name):
    p = os.path.join(DATA, run, name)
    if not os.path.exists(p):
        return None
    return np.loadtxt(p, delimiter=",", skiprows=1)


def save(p, name):
    path = os.path.join(FIG, name + ".svg")
    p.save(path)
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-z", "2", "-o", path[:-4] + ".png", path], check=True)
    print("wrote", path)


def cat_axis(ax, labels, y):
    """category labels under a panel whose x axis runs 0 .. n-1"""
    for i, l in enumerate(labels):
        ax.text(i, y, l, size=10.5, anchor="middle")


# ------------------------------------------------------------------ figures
def fig_block():
    for ext in ("svg", "png"):
        src = os.path.join(DUT, "doc", f"xosc_block.{ext}")
        if os.path.exists(src):
            shutil.copy(src, os.path.join(FIG, f"block_diagram.{ext}"))
    print("copied block_diagram")


def fig_rneg():
    r = res("tm_27_1.8", "ac")
    if not r:
        return
    p = Plot(900, 470)
    ax = p.panel(90, 40, 770, 360, (20, 28), (0, 1200), xlabel="Frequency  [MHz]",
                 ylabel="−R_neg seen by the motional arm  [Ω]",
                 title="Small-signal negative resistance (tm, 27 °C, 1.8 V, C1 = C2 = 12 pF)", legend="tr")
    for d, col in zip(("0", "1", "2", "3"), (K, O, B, R)):
        ax.line(np.array(r[d]["f"]) / 1e6, -np.array(r[d]["rneg"]), col, 2.4,
                label=f"DRV = {int(d):02b}  ({250 + 125 * int(d)} µA)")
    ax.hline(500, R, "6,4", text="5 × ESR_max = 500 Ω (design target)", anchor="start")
    ax.hline(100, K, "3,3", text="ESR_max = 100 Ω (VXM7A)", anchor="start")
    ax.vline(24, text="24 MHz")
    save(p, "rneg_freq")


def fig_margin():
    labs, vals = [], {d: [] for d in "0123"}
    for run, lab in CORNERS:
        r = res(run, "ac")
        if not r:
            continue
        labs.append(lab)
        for d in "0123":
            vals[d].append(-r[d]["rneg24"])
    if not labs:
        return
    n = len(labs)
    p = Plot(900, 470)
    ax = p.panel(90, 40, 770, 330, (-0.5, n - 0.5), (0, 1400), ylabel="−R_neg at 24 MHz  [Ω]",
                 title="Start-up margin over corners (ESR_max = 100 Ω)", xticks=[], legend="tr")
    for d, col, mk in zip("0123", (K, O, B, R), ("s", "^", "o", "o")):
        ax.points(np.arange(n), vals[d], col, label=f"DRV = {int(d):02b}", marker=mk)
    ax.hline(500, R, "6,4", text="5 × ESR_max", anchor="start")
    ax.hline(100, K, "3,3", text="ESR_max", anchor="start")
    cat_axis(ax, [l.split(" ", 1)[0] for l in labs], -90)
    cat_axis(ax, [l.split(" ", 1)[1] for l in labs], -150)
    save(p, "margin_corners")


def fig_waveforms():
    a = csv("tm_27_1.8", "ss_d2_r100_win.csv")
    if a is None:
        return
    t = (a[:, 0] - a[-1, 0]) * 1e9 + 100
    m = t >= 0
    p = Plot(900, 560)
    a1 = p.panel(90, 40, 770, 210, (0, 100), (-0.1, 2.0), ylabel="Voltage  [V]",
                 title="Steady state (tm, 27 °C, 1.8 V, ESR 100 Ω, DRV = 10)", legend="tr")
    a1.line(t[m], a[m, 1], B, 2.2, label="XI")
    a1.line(t[m], a[m, 2], R, 2.2, label="XO")
    a1.line(t[m], a[m, 3], G, 1.8, label="REF_CLK")
    a2 = p.panel(90, 300, 770, 200, (0, 100), (-1.5, 1.5), xlabel="Time  [ns]  (last 100 ns of 240 µs)",
                 ylabel="Crystal current  [mA]", legend="tr")
    a2.line(t[m], a[m, 4] * 1e3, V, 2.2, label="I_x (motional arm)")
    save(p, "waveforms")


def fig_startup():
    p = Plot(900, 450)
    ax = p.panel(90, 40, 770, 340, (0, 1.6), (0, 1.0), xlabel="Time after XTAL_EN  [ms]",
                 ylabel="XI amplitude  [Vpp]", legend="br",
                 title="Start-up after XTAL_EN 0 → 1 (envelope of XI, 2 µs windows; ESR 100 Ω, DRV = 10)")
    for (run, lab), col in zip(CORNERS, COLORS + ["#888888"]):
        r = res(run, "start")
        if r:
            ax.line(np.array(r["env_t"]) * 1e3 - 1e-3, r["env"], col, 2.2, label=lab)
    save(p, "startup")


def corner_vals(case, key, scale=1.0):
    labs, v = [], []
    for run, lab in CORNERS:
        r = res(run, case)
        if r and key in r:
            labs.append(lab)
            v.append(r[key] * scale)
    return labs, v


def fig_amp_dl():
    labs, xi = corner_vals("ss", "xi_pp")
    if not labs:
        return
    _, xo = corner_vals("ss", "xo_pp")
    _, dl = corner_vals("ss", "dl", 1e6)
    _, idd = corner_vals("ss", "idd", 1e3)
    n = len(labs)
    p = Plot(900, 640)
    a1 = p.panel(90, 40, 770, 220, (-0.5, n - 0.5), (0, 1.4), ylabel="Amplitude  [Vpp]", xticks=[],
                 title="Regulated amplitude, drive level and current over corners (ESR 100 Ω, DRV = 10)",
                 legend="tr")
    a1.points(np.arange(n), xi, B, label="XI")
    a1.points(np.arange(n), xo, R, label="XO", marker="s")
    a2 = p.panel(90, 300, 770, 220, (-0.5, n - 0.5), (0, 250), ylabel="Drive level [µW] / I(VDD) [100 µA]",
                 xticks=[], legend="tr")
    a2.points(np.arange(n), dl, V, label="crystal drive level  [µW]")
    a2.points(np.arange(n), np.array(idd) * 100, G, label="I(VDD) in steady state  [100 µA]", marker="^")
    a2.hline(200, R, "6,4", text="crystal DL_max 200 µW", anchor="start")
    cat_axis(a2, [l.split(" ", 1)[0] for l in labs], -40)
    cat_axis(a2, [l.split(" ", 1)[1] for l in labs], -65)
    save(p, "amplitude_corners")


def fig_current():
    p = Plot(900, 430)
    ax = p.panel(90, 40, 770, 320, (-0.3, 3.3), (0, 1.0), xlabel="DRV1 DRV0  (0 = 00 … 3 = 11)",
                 ylabel="I(VDD) at start-up (no oscillation)  [mA]", xticks=[0, 1, 2, 3],
                 title="Supply current before the ALC acts (op, XTAL_EN = 1)", legend="tl")
    for (run, lab), col in zip(CORNERS, COLORS + ["#888888"]):
        r = res(run, "op")
        if r:
            ax.line([0, 1, 2, 3], [r[f"d{d}_e1"]["idd"] * 1e3 for d in range(4)], col, 1.8, label=lab)
            ax.points([0, 1, 2, 3], [r[f"d{d}_e1"]["idd"] * 1e3 for d in range(4)], col)
    save(p, "current_drv")


def fig_pulling():
    pts = []
    for run, c in (("tm_27_1.8_c10", 10), ("tm_27_1.8", 12), ("tm_27_1.8_c14", 14)):
        r = res(run, "ss")
        if r:
            pts.append((c, r["ppm"], r["c_ext"]))
    if not pts:
        return
    p = Plot(900, 450)
    ax = p.panel(90, 40, 770, 340, (8, 16), (-60, 60), xlabel="External C1 = C2  [pF]",
                 ylabel="Frequency error  [ppm]",
                 title="Pulling by the load capacitors (tm, 27 °C, 1.8 V; crystal at 24.000 MHz for C_L = 8 pF)",
                 legend="tr")
    c = np.linspace(8, 16, 81)
    # analytic: C_L = 0.5 + (c + 2.5) / 2 + offset (fit to the 12 pF point)
    c12 = [x for x in pts if x[0] == 12]
    off = (c12[0][2] - C0) * 1e12 - (0.5 + 14.5 / 2) if c12 else 0.0
    cl = 0.5 + (c + 2.5) / 2 + off
    fs = F0 / (1 + CM / (2 * (C0 + 8e-12)))
    f = fs * np.sqrt(1 + CM / ((C0 + cl * 1e-12)))
    ax.line(c, (f / F0 - 1) * 1e6, K, 1.6, dash="5,4", label="arm resonance with C_L(C1, C2) (analytic)")
    ax.points([x[0] for x in pts], [x[1] for x in pts], B, label="ngspice steady state (extracted)")
    ax.band(-50, 50, G, 0.06)
    ax.text(8.2, 54, "crystal tolerance ±50 ppm (VXM7A)", size=10.5)
    save(p, "pulling")


def fig_vdd_temp():
    v = []
    for run, vdd in (("tm_27_1.62", 1.62), ("tm_27_1.8", 1.8), ("tm_27_1.98", 1.98)):
        r = res(run, "ss")
        if r:
            v.append((vdd, r["ppm"], r["xi_pp"], r["idd"] * 1e3, r["dl"] * 1e6))
    tt = []
    for run, T in (("tm_-40_1.8", -40), ("tm_27_1.8", 27), ("tm_125_1.8", 125)):
        r = res(run, "ss")
        if r:
            tt.append((T, r["ppm"], r["xi_pp"], r["idd"] * 1e3, r["dl"] * 1e6))
    if not v and not tt:
        return
    p = Plot(900, 520)
    a1 = p.panel(80, 40, 360, 180, (1.6, 2.0), (-5, 10), ylabel="Δf (circuit)  [ppm]",
                 title="Supply (tm, 27 °C)", legend="tr")
    a2 = p.panel(520, 40, 360, 180, (-50, 130), (-5, 10), title="Temperature (tm, 1.8 V)", legend="tr")
    a3 = p.panel(80, 280, 360, 180, (1.6, 2.0), (0, 1.2), xlabel="VDD18A  [V]",
                 ylabel="XI [Vpp] / I(VDD) [mA]", legend="tl")
    a4 = p.panel(520, 280, 360, 180, (-50, 130), (0, 1.2), xlabel="Temperature  [°C]", legend="tl")
    for ax_f, ax_a, d in ((a1, a3, v), (a2, a4, tt)):
        if not d:
            continue
        x = [q[0] for q in d]
        ax_f.line(x, [q[1] for q in d], B, 2.0)
        ax_f.points(x, [q[1] for q in d], B, label="frequency (crystal ideal)")
        ax_a.line(x, [q[2] for q in d], R, 2.0)
        ax_a.points(x, [q[2] for q in d], R, label="XI amplitude")
        ax_a.line(x, [q[3] for q in d], G, 2.0)
        ax_a.points(x, [q[3] for q in d], G, label="I(VDD)", marker="^")
    save(p, "vdd_temp")


def fig_bypass():
    a = csv("tm_27_1.8", "byp_sq_win.csv")
    b = csv("tm_27_1.8", "byp_sine_win.csv")
    if a is None and b is None:
        return
    p = Plot(900, 560)
    for k, (arr, ttl) in enumerate(((a, "Bypass: 1.8 V CMOS clock on XI through 33 Ω (XO open)"),
                                    (b, "Bypass: 0.5 Vpp sine on XI through 10 nF (XO open)"))):
        if arr is None:
            continue
        t = (arr[:, 0] - arr[-1, 0]) * 1e9 + 200
        m = t >= 100
        ax = p.panel(90, 40 + 260 * k, 770, 200, (100, 200), (-0.1, 2.0), title=ttl, legend="tr",
                     ylabel="Voltage  [V]", xlabel="Time  [ns]" if k else "")
        ax.line(t[m], arr[m, 1], B, 2.0, label="XI")
        ax.line(t[m], arr[m, 2], R, 1.4, dash="4,3", label="XO")
        ax.line(t[m], arr[m, 3], G, 1.8, label="REF_CLK")
    save(p, "bypass")


def fig_enable():
    a = csv("tm_27_1.8", "en_env.csv")
    if a is None:
        return
    t = a[:, 0] * 1e6
    m = (t > 28) & (t < 42)
    p = Plot(900, 560)
    a1 = p.panel(90, 40, 770, 200, (28, 42), (-0.2, 2.0), ylabel="Voltage  [V]", legend="tr",
                 title="XTAL_EN = 0 at 30 µs, = 1 at 40 µs (tm; crystal keeps ringing while off)")
    a1.line(t[m], a[m, 1], B, 1.2, label="XI")
    a1.line(t[m], a[m, 3], G, 1.2, label="REF_CLK")
    a2 = p.panel(90, 300, 770, 200, (28, 42), (0, 1.0), xlabel="Time  [µs]", ylabel="I(VDD)  [mA]")
    a2.line(t[m], a[m, 4] * 1e3, R, 1.2)
    save(p, "enable")


def fig_duty():
    labs, duty = corner_vals("ss", "duty")
    if not labs:
        return
    _, tr = corner_vals("ss", "tr", 1e12)
    _, tf = corner_vals("ss", "tf", 1e12)
    n = len(labs)
    p = Plot(900, 520)
    a1 = p.panel(90, 40, 770, 170, (-0.5, n - 0.5), (40, 60), ylabel="Duty cycle  [%]", xticks=[],
                 title="REF_CLK duty cycle and edges over corners (100 fF load)", legend="tr")
    a1.band(45, 55, G, 0.08)
    a1.points(np.arange(n), duty, B, label="duty cycle (limit 45–55 %)")
    a2 = p.panel(90, 250, 770, 170, (-0.5, n - 0.5), (0, 500), ylabel="10–90 %  [ps]", xticks=[], legend="tr")
    a2.points(np.arange(n), tr, R, label="rise")
    a2.points(np.arange(n), tf, K, label="fall", marker="s")
    cat_axis(a2, [l.split(" ", 1)[0] for l in labs], -60)
    cat_axis(a2, [l.split(" ", 1)[1] for l in labs], -110)
    save(p, "duty_edges")


# ------------------------------------------------------------------- tables
def f(v, fmts):
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else format(v, fmts)


def tables():
    out = []
    hdr = "| Parameter | " + " | ".join(l for _, l in CORNERS) + " |"
    sep = "|---|" + "---|" * len(CORNERS)
    rows = [
        ("−R_neg at 24 MHz, DRV 10 [Ω]", "ac", lambda r: -r["2"]["rneg24"], ".0f"),
        ("Start-up margin −R_neg / ESR_max, DRV 10", "ac", lambda r: r["2"]["margin"], ".1f"),
        ("−R_neg at 24 MHz, DRV 11 [Ω]", "ac", lambda r: -r["3"]["rneg24"], ".0f"),
        ("Start-up margin, DRV 11", "ac", lambda r: r["3"]["margin"], ".1f"),
        ("I(VDD) before oscillation, DRV 10 [mA]", "op", lambda r: r["d2_e1"]["idd"] * 1e3, ".3f"),
        ("I(VDD), XTAL_EN = 0 [nA]", "op", lambda r: r["d2_e0"]["idd"] * 1e9, ".1f"),
        ("XI / XO DC bias [V]", "op", lambda r: r["d2_e1"]["vxi"], ".3f"),
        ("XI amplitude [Vpp]", "ss", lambda r: r["xi_pp"], ".3f"),
        ("XO amplitude [Vpp]", "ss", lambda r: r["xo_pp"], ".3f"),
        ("Crystal current [mA rms]", "ss", lambda r: r["ix_rms"] * 1e3, ".3f"),
        ("Drive level at ESR 100 Ω [µW]", "ss", lambda r: r["dl"] * 1e6, ".1f"),
        ("I(VDD) in steady state [mA]", "ss", lambda r: r["idd"] * 1e3, ".3f"),
        ("Load capacitance seen by the arm C0 + C_L [pF]", "ss", lambda r: r["c_ext"] * 1e12, ".3f"),
        ("Frequency error (circuit) [ppm]", "ss", lambda r: r["ppm"], "+.1f"),
        ("R_ext (−ESR when settled) [Ω]", "ss", lambda r: f"{r['r_ext']:.0f}{'' if r['settled'] else ' ¹'}", "s"),
        ("REF_CLK duty cycle [%]", "ss", lambda r: r["duty"], ".2f"),
        ("REF_CLK rise / fall 10–90 % [ps]", "ss", lambda r: f"{r['tr'] * 1e12:.0f} / {r['tf'] * 1e12:.0f}", "s"),
        ("Start-up: stable REF_CLK (±1 % period) [µs]", "start", lambda r: r["t_stable"] * 1e6, ".0f"),
        ("Start-up: 90 % amplitude [µs]", "start", lambda r: r["t90"] * 1e6, ".0f"),
        ("Envelope growth time constant τ [µs]", "start", lambda r: r["tau"] * 1e6, ".1f"),
        ("Bypass square: duty [%] / XI→REF_CLK [ns]", "byp",
         lambda r: f"{r['sq']['duty']:.1f} / {r['sq']['delay'] * 1e9:.2f}", "s"),
        ("Bypass sine 0.5 Vpp: duty [%] / delay [ns]", "byp",
         lambda r: f"{r['sine']['duty']:.1f} / {r['sine']['delay'] * 1e9:.2f}", "s"),
        ("Bypass I(VDD) square / sine [mA]", "byp",
         lambda r: f"{r['sq']['idd'] * 1e3:.3f} / {r['sine']['idd'] * 1e3:.3f}", "s"),
    ]
    out += [hdr, sep]
    for name, case, fn, fm in rows:
        cells = []
        for run, _ in CORNERS:
            r = res(run, case)
            try:
                cells.append(f(fn(r), fm) if r else "—")
            except (KeyError, TypeError):
                cells.append("—")
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    out.append("")
    # sweeps at tm
    out.append("| Run (tm) | XI [Vpp] | DL [µW] | I(VDD) [mA] | f [ppm] | duty [%] | start stable [µs] | τ [µs] |")
    out.append("|---|---|---|---|---|---|---|---|")
    for run, lab in (("tm_27_1.8", "27 °C, 1.8 V, ESR 100 Ω, DRV 10, C1 = C2 = 12 pF"),
                     ("tm_27_1.62", "VDD 1.62 V"), ("tm_27_1.98", "VDD 1.98 V"),
                     ("tm_-40_1.8", "−40 °C"), ("tm_125_1.8", "125 °C"),
                     ("tm_27_1.8_esr30", "ESR 30 Ω"), ("tm_27_1.8_esr60", "ESR 60 Ω"),
                     ("tm_27_1.8_drv0", "DRV 00"), ("tm_27_1.8_drv3", "DRV 11"),
                     ("tm_27_1.8_c10", "C1 = C2 = 10 pF"), ("tm_27_1.8_c14", "C1 = C2 = 14 pF")):
        s, st = res(run, "ss"), res(run, "start")
        if not s:
            continue
        u = "" if s.get("settled", True) else " ¹"
        out.append(f"| {lab}{u} | {s['xi_pp']:.3f} | {s['dl'] * 1e6:.1f} | {s['idd'] * 1e3:.3f} | "
                   f"{s['ppm']:+.1f} | {s['duty']:.2f} | "
                   f"{f(st['t_stable'] * 1e6, '.0f') if st else '—'} | {f(st['tau'] * 1e6, '.1f') if st else '—'} |")
    out.append("")
    for run in ("tm_27_1.8_c10", "tm_27_1.8_c14"):
        a = res(run, "ac")
        if a:
            out.append(f"- {run}: −R_neg(24 MHz, DRV 10) = {-a['2']['rneg24']:.0f} Ω, margin {a['2']['margin']:.1f}")
    e = res("tm_27_1.8", "en")
    if e:
        out.append(f"- enable: REF_CLK low {e['t_stop'] * 1e9:.1f} ns after XTAL_EN = 0, first edge "
                   f"{e['first_rise_after_en1'] * 1e9:.1f} ns after XTAL_EN = 1 (crystal still ringing), "
                   f"I(VDD) while off and ringing {e['idd_off_ringing'] * 1e6:.2f} µA")
    # min / typ / max over the corners (typ = tm)
    out.append("")
    out.append("ELECTRICAL")
    spec = [
        ("Start-up current I(VDD), no oscillation, DRV 10", "op", lambda r: r["d2_e1"]["idd"] * 1e3, "mA", ".2f"),
        ("Start-up current I(VDD), no oscillation, DRV 11", "op", lambda r: r["d3_e1"]["idd"] * 1e3, "mA", ".2f"),
        ("Supply current, XTAL_EN = 0", "op", lambda r: r["d2_e0"]["idd"] * 1e9, "nA", ".1f"),
        ("XI / XO DC bias (no oscillation)", "op", lambda r: r["d2_e1"]["vxi"], "V", ".3f"),
        ("−R_neg at 24 MHz, DRV 10", "ac", lambda r: -r["2"]["rneg24"], "Ω", ".0f"),
        ("−R_neg at 24 MHz, DRV 11", "ac", lambda r: -r["3"]["rneg24"], "Ω", ".0f"),
        ("Start-up margin −R_neg / 100 Ω, DRV 11", "ac", lambda r: r["3"]["margin"], "", ".1f"),
        ("XI amplitude (regulated)", "ss", lambda r: r["xi_pp"], "Vpp", ".3f"),
        ("XO amplitude", "ss", lambda r: r["xo_pp"], "Vpp", ".3f"),
        ("Crystal current", "ss", lambda r: r["ix_rms"] * 1e3, "mA rms", ".3f"),
        ("Crystal drive level, ESR 100 Ω", "ss", lambda r: r["dl"] * 1e6, "µW", ".1f"),
        ("Supply current in operation", "ss", lambda r: r["idd"] * 1e3, "mA", ".3f"),
        ("Load capacitance seen by the arm C0 + C_L", "ss", lambda r: r["c_ext"] * 1e12, "pF", ".2f"),
        ("Frequency error from the circuit", "ss", lambda r: r["ppm"], "ppm", "+.1f"),
        ("REF_CLK duty cycle", "ss", lambda r: r["duty"], "%", ".1f"),
        ("REF_CLK rise time 10–90 %, 100 fF", "ss", lambda r: r["tr"] * 1e12, "ps", ".0f"),
        ("REF_CLK fall time 10–90 %, 100 fF", "ss", lambda r: r["tf"] * 1e12, "ps", ".0f"),
        ("Start-up to stable REF_CLK (±1 % period), DRV 10", "start", lambda r: r["t_stable"] * 1e6, "µs", ".0f"),
        ("Start-up to 90 % amplitude, DRV 10", "start", lambda r: r["t90"] * 1e6, "µs", ".0f"),
        ("Envelope growth time constant, DRV 10", "start", lambda r: r["tau"] * 1e6, "µs", ".1f"),
        ("Bypass: XI → REF_CLK delay, CMOS input", "byp", lambda r: r["sq"]["delay"] * 1e9, "ns", ".2f"),
        ("Bypass: duty cycle, CMOS input 50 %", "byp", lambda r: r["sq"]["duty"], "%", ".1f"),
        ("Bypass: duty cycle, 0.5 Vpp sine", "byp", lambda r: r["sine"]["duty"], "%", ".1f"),
        ("Bypass: supply current, CMOS input", "byp", lambda r: r["sq"]["idd"] * 1e3, "mA", ".3f"),
    ]
    out.append("| Parameter | Min | Typ | Max | Unit | Corners |")
    out.append("|---|---|---|---|---|---|")
    for name, case, fn, unit, fm in spec:
        vals, n = [], 0
        for run, _ in CORNERS:
            r = res(run, case)
            if r:
                vals.append(fn(r)); n += 1
        typ = res("tm_27_1.8", case)
        out.append(f"| {name} | {format(min(vals), fm)} | {format(fn(typ), fm) if typ else '—'} | "
                   f"{format(max(vals), fm)} | {unit} | {n} |")
    open(os.path.join(DATA, "tables.md"), "w").write("\n".join(out) + "\n")
    print("wrote", os.path.join(DATA, "tables.md"))


def main():
    os.makedirs(FIG, exist_ok=True)
    for fn in (fig_block, fig_rneg, fig_margin, fig_waveforms, fig_startup, fig_amp_dl, fig_current,
               fig_pulling, fig_bypass, fig_enable, fig_duty, tables):
        fn()


if __name__ == "__main__":
    main()
