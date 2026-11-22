#!/usr/bin/env python3
"""gen_figures.py - figures and result tables of the LDO datasheet

Usage (numpy only; rsvg-convert for the PNG copies used by Word):
    python3 "AFE/LDO analog part/datasheet/gen_figures.py"

Reads the ngspice results that sim/run_all.py copied to data/<run>/
(results_<case>.json, *.csv) and writes
  fig/*.svg (+ .png at 2x)       the datasheet figures
  data/tables.md                 the corner tables quoted in ldo_datasheet.md
The plot helper is AFE/doc/pll_datasheet/svgplot.py (imported, not copied).
"""
import json
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
TM = "tm_27_3.3"
CORNERS = [("tm_27_3.3", "tm", "27 °C 3.3 V"), ("ws_-40_2.97", "ws", "−40 °C 2.97 V"),
           ("ws_125_2.97", "ws", "125 °C 2.97 V"), ("wp_-40_3.63", "wp", "−40 °C 3.63 V"),
           ("wp_125_3.63", "wp", "125 °C 3.63 V"), ("wo_27_3.3", "wo", "27 °C 3.3 V"),
           ("wz_27_3.3", "wz", "27 °C 3.3 V")]
LOADS = ["0", "10u", "100u", "1m", "5m", "20m", "50m"]
LOADV = [10e-6, 20e-6, 110e-6, 1.01e-3, 5.01e-3, 20.01e-3, 50.01e-3]   # incl. the 10 uA divider
LOADL = ["0", "10 µA", "100 µA", "1 mA", "5 mA", "20 mA", "50 mA"]


def res(run, case):
    p = os.path.join(DATA, run, f"results_{case}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def csv(run, name):
    p = os.path.join(DATA, run, name)
    return np.loadtxt(p, delimiter=",", skiprows=1) if os.path.exists(p) else None


def save(p, name):
    path = os.path.join(FIG, name + ".svg")
    p.save(path)
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-z", "2", "-o", path[:-4] + ".png", path], check=True)
    print("wrote", path)


def cat_axis(ax, labels, y):
    for i, l in enumerate(labels):
        ax.text(i, y, l, size=10.5, anchor="middle")


# ------------------------------------------------------------------ figures
def fig_block():
    for name in ("block", "bandgap", "regulator", "supervisor"):
        for ext in ("svg", "png"):
            src = os.path.join(DUT, "doc", f"ldo_{name}.{ext}")
            if os.path.exists(src):
                shutil.copy(src, os.path.join(FIG, f"sch_{name}.{ext}"))
    print("copied schematic sheets")


def fig_temp():
    p = Plot(900, 560)
    a1 = p.panel(90, 40, 770, 210, (-40, 125), (1.12, 1.27), ylabel="VBG  [V]",
                 title="Bandgap voltage and output voltage vs temperature (5 mA)", legend="tl")
    a2 = p.panel(90, 300, 770, 210, (-40, 125), (1.70, 1.90), xlabel="Temperature  [°C]",
                 ylabel="VOUT  [V]", legend="br")
    for (run, c, lab), col in zip([CORNERS[0], CORNERS[1], CORNERS[3]], (K, R, B)):
        r = res(run, "temp")
        if not r:
            continue
        a1.line(r["t"], r["vbg"], col, 2.2, label=f"{c} {lab.split(' ')[-2]} {lab.split(' ')[-1]}" if False else
                f"{c}, VIN {lab.split()[-2]} V")
        a2.line(r["t"], r["vout"], col, 2.2)
    a2.band(1.719, 1.881, G, 0.06)
    save(p, "temp")


def fig_line():
    r = res(TM, "line")
    if not r:
        return
    p = Plot(900, 560)
    a1 = p.panel(90, 40, 770, 210, (2.0, 3.7), (0, 2.0), ylabel="VOUT  [V]",
                 title="Line regulation: VIN ramped down 3.63 → 1.5 V (tm, 27 °C)", legend="br")
    for il, col in (("1m", B), ("20m", R)):
        a1.line(r[il]["vin"], r[il]["vout"], col, 2.2, label=f"{il[:-1]} mA")
    a1.vline(2.497, text="UVLO off 2.50 V", left=True)
    a1.vline(2.97, text="VIN min 2.97 V")
    a2 = p.panel(90, 300, 770, 210, (1.6, 2.6), (1.70, 1.82), xlabel="VIN  [V]", ylabel="VOUT  [V]",
                 title="Dropout (UVLO overridden in the testbench)", legend="br")
    for il, col in (("1m", B), ("20m", R)):
        a2.line(r[il]["drop_vin"], r[il]["drop_vout"], col, 2.2,
                label=f"{il[:-1]} mA: dropout {r[il]['dropout'] * 1e3:.0f} mV")
    a2.vline(2.5, text="UVLO off", left=True)
    save(p, "line")


def fig_load():
    p = Plot(900, 560)
    a1 = p.panel(90, 40, 770, 210, (0, 100), (0, 2.0), ylabel="VOUT  [V]",
                 title="Load regulation and current limit (tm, 27 °C; load ramp 0 → 100 mA)", legend="bl")
    a2 = p.panel(90, 300, 770, 210, (0, 25), (-9, 1), xlabel="Load current  [mA]",
                 ylabel="VOUT − VOUT(0)  [mV]", legend="br", title="Load regulation, all corners")
    r = res(TM, "load")
    if r:
        for v, col in (("3.3", B), ("2.97", R)):
            il = np.array(r[v]["il"]) * 1e3
            a1.line(il, r[v]["vout"], col, 2.2, label=f"VIN {v} V: limit {r[v]['ilim'] * 1e3:.0f} mA")
            vo = np.array(r[v]["vout"])
            a2.line(il, (vo - vo[0]) * 1e3, col, 2.2, label=f"tm VIN {v} V: {r[v]['dv_20m'] * 1e3:+.1f} mV at 20 mA")
    for (run, c, lab), col in zip(CORNERS[1:5], (K, G, O, V)):
        rc = res(run, "load")
        if rc:
            k = list(rc.keys())[0]
            vo = np.array(rc[k]["vout"])
            a2.line(np.array(rc[k]["il"]) * 1e3, (vo - vo[0]) * 1e3, col, 1.4, dash="5,3", label=f"{c} {lab}")
    save(p, "load")


def fig_bode():
    r = res(TM, "ac")
    if not r:
        return
    p = Plot(900, 620)
    a1 = p.panel(90, 40, 770, 250, (1, 3e7), (-60, 110), xlog=True, ylabel="|T|  [dB]",
                 title="Loop gain T (tm, 27 °C, COUT 1 µF, ESR 10 mΩ)", legend="tr")
    a2 = p.panel(90, 330, 770, 230, (1, 3e7), (-200, 200), xlog=True, xlabel="Frequency  [Hz]",
                 ylabel="Phase margin 180° + ∠T  [°]", yticks=[-180, -90, 0, 45, 90, 180], legend="bl")
    for il, lab, col in zip(LOADS, LOADL, (K, V, O, G, B, R, "#888888")):
        if il not in r:
            continue
        f = np.array(r[il]["f"])
        a1.line(f, r[il]["mag"], col, 2.0, label=f"{lab}: PM {r[il]['pm']:.0f}°, fc {r[il]['fc'] / 1e3:.3g} kHz")
        ph = (180 + np.array(r[il]["ph"]) + 180) % 360 - 180
        a2.line(f, ph, col, 1.8)
    a1.hline(0, "#888888", "3,3")
    a2.hline(45, R, "6,4", text="45°")
    save(p, "loopgain")


def fig_pm():
    p = Plot(900, 680)
    a1 = p.panel(90, 40, 770, 210, (5e-6, 1e-1), (0, 120), xlog=True, ylabel="Phase margin  [°]",
                 title="Phase margin and crossover vs load (PVT corners and COUT)")
    a2 = p.panel(90, 300, 770, 330, (5e-6, 1e-1), (3e2, 1e9), xlog=True, ylog=True,
                 xlabel="Load current incl. divider  [A]", ylabel="Crossover  [Hz]", legend="tl")
    runs = CORNERS + [("tm_27_3.3_c2u2_esr0.5", "tm", "2.2 µF, ESR 0.5 Ω"), ("tm_27_3.3_c0u47", "tm", "0.47 µF")]
    cols = (K, B, R, G, O, V, "#888888", "#b03a8a", "#2a9d8f")
    for (run, c, lab), col in zip(runs, cols):
        r = res(run, "ac")
        if not r:
            continue
        x = [LOADV[i] for i, l in enumerate(LOADS) if l in r]
        a1.line(x, [r[l]["pm"] for l in LOADS if l in r], col, 1.8)
        a2.line(x, [r[l]["fc"] for l in LOADS if l in r], col, 1.8, label=f"{c} {lab}")
    a1.hline(45, R, "6,4", text="45°", anchor="start")
    save(p, "pm_load")


def fig_capsweep():
    r = res(TM, "capsweep")
    if not r:
        return
    combos = []
    for x in r:
        k = (x["cout"], x["esr"])
        if k not in combos:
            combos.append(k)
    n = len(combos)
    p = Plot(900, 470)
    ax = p.panel(90, 40, 770, 330, (-0.5, n - 0.5), (0, 120), ylabel="Phase margin  [°]",
                 title="Phase margin vs output capacitor and ESR (tm, 27 °C)", xticks=[], legend="br")
    for il, col, mk in (("0", K, "s"), ("1m", B, "^"), ("20m", R, "o")):
        ax.points(range(n), [next(x["pm"] for x in r if (x["cout"], x["esr"]) == c and x["il"] == il) for c in combos],
                  col, label=f"load {il if il != '0' else '0 (divider)'}".replace("m", " mA"), marker=mk)
    ax.hline(45, R, "6,4", text="45°", anchor="start")
    cat_axis(ax, [f"{c * 1e6:g} µF" for c, e in combos], -12)
    cat_axis(ax, [f"ESR {e * 1e3:g} mΩ" if e < 1 else f"ESR {e:g} Ω" for c, e in combos], -22)
    save(p, "pm_cout")


def fig_psrr_zout():
    p = Plot(900, 600)
    a1 = p.panel(90, 40, 770, 230, (10, 1e8), (0, 100), xlog=True, ylabel="PSRR  [dB]",
                 title="Power-supply rejection and output impedance (tm, 27 °C, COUT 1 µF)", legend="br")
    a2 = p.panel(90, 320, 770, 220, (10, 1e8), (1e-3, 10), xlog=True, ylog=True, xlabel="Frequency  [Hz]",
                 ylabel="|Z_out|  [Ω]", legend="tl")
    r = res(TM, "psrr")
    if r:
        for il, col in (("1m", B), ("20m", R)):
            a1.line(r[il]["f"], r[il]["psrr"], col, 2.2, label=f"{il[:-1]} mA")
    for run, c, lab in CORNERS[1:5]:
        rc = res(run, "psrr")
        if rc:
            a1.line(rc["20m"]["f"], rc["20m"]["psrr"], "#999999", 1.0, dash="4,3")
    a1.text(15, 8, "dashed grey: 20 mA at ws / wp corners", "#777777", 10.5)
    r = res(TM, "zout")
    if r:
        for il, col in (("1m", B), ("20m", R)):
            a2.line(r[il]["f"], r[il]["z"], col, 2.2, label=f"{il[:-1]} mA")
    f = np.logspace(1, 8, 200)
    a2.line(f, np.abs(1 / (2j * np.pi * f * 1e-6) + 0.01), "#888888", 1.2, dash="5,4", label="1 µF + 10 mΩ alone")
    save(p, "psrr_zout")


def fig_noise():
    r = res(TM, "noise")
    if not r:
        return
    p = Plot(900, 420)
    ax = p.panel(90, 40, 770, 300, (10, 1e6), (1e-8, 1e-4), xlog=True, ylog=True, xlabel="Frequency  [Hz]",
                 ylabel="Output noise  [V/√Hz]",
                 title=f"Output noise density (tm, 27 °C, 5 mA): {r['rms_10_100k'] * 1e6:.0f} µV rms 10 Hz–100 kHz",
                 legend="tr")
    ax.line(r["f"], r["vn"], B, 2.2, label="VOUT")
    ax.vline(3.2e3, text="RSS·CSS pole 3.2 kHz")
    save(p, "noise")


def fig_start():
    a = csv(TM, "start.csv")
    r = res(TM, "start")
    if a is None:
        return
    t, vin, vo, pg, pr, i = a.T
    t = t * 1e6
    p = Plot(900, 600)
    a1 = p.panel(90, 40, 770, 300, (0, 400), (-0.1, 3.6), ylabel="Voltage  [V]",
                 title="Power-up: VIN 0 → 3.3 V in 100 µs, LDO_EN = VIN, 5 mA (tm, 27 °C)", legend="br")
    a1.line(t, vin, K, 2.0, label="VIN")
    a1.line(t, vo, B, 2.4, label="VOUT")
    a1.line(t, pg + 0.02, G, 1.8, label="PWR_GOOD")
    a1.line(t, pr - 0.02, R, 1.8, dash="6,3", label="POR_N")
    if r:
        a1.vline(r["t_on"] * 1e6, text=f"UVLO release, VIN {r['vin_at_on']:.2f} V", left=True)
    a2 = p.panel(90, 390, 770, 160, (0, 400), (0, 90), xlabel="Time  [µs]", ylabel="I(VIN)  [mA]", legend="tr")
    a2.line(t, i * 1e3, O, 2.0, label="supply current (COUT charge at the current limit)")
    save(p, "startup")


def fig_enable():
    a = csv(TM, "en.csv")
    r = res(TM, "en")
    if a is None:
        return
    t, vo, pg, pr, i = a.T
    p = Plot(900, 520)
    a1 = p.panel(90, 40, 360, 400, (0, 300), (-0.1, 2.0), xlabel="Time  [µs]", ylabel="Voltage  [V]",
                 title="Enable (LDO_EN ↑ at 20 µs)", legend="br")
    m = t < 320e-6
    a1.line(t[m] * 1e6, vo[m], B, 2.4, label="VOUT")
    a1.line(t[m] * 1e6, pg[m] + 0.02, G, 1.8, label="PWR_GOOD")
    a1.line(t[m] * 1e6, pr[m] - 0.02, R, 1.8, dash="6,3", label="POR_N")
    a1.vline(20, text="LDO_EN", top=True)
    a2 = p.panel(500, 40, 360, 400, (0, 4), (-0.1, 2.0), xlabel="Time after LDO_EN ↓  [ms]",
                 title="Disable: discharge ≈ 0.6 kΩ, 1 µF, 0.1 mA", legend="tr")
    m = (t > 0.59e-3) & (t < 4.6e-3)
    a2.line((t[m] - 0.6e-3) * 1e3, vo[m], B, 2.4, label="VOUT")
    a2.line((t[m] - 0.6e-3) * 1e3, pg[m], G, 1.8, label="PWR_GOOD")
    if r:
        a2.vline(r["t_discharge"] * 1e3, text=f"10 % at {r['t_discharge'] * 1e3:.2f} ms", top=False)
    save(p, "enable")


def fig_uvlo():
    a = csv(TM, "uvlo.csv")
    r = res(TM, "uvlo")
    if a is None:
        return
    t, vin, vo, pg, pr = a.T
    p = Plot(900, 470)
    ax = p.panel(90, 40, 770, 360, (0.4, float(np.ceil(t[-1] * 2e3) / 2)), (-0.1, 3.5), xlabel="Time  [ms]", ylabel="Voltage  [V]",
                 title="UVLO: VIN 3.3 → 2.0 → 3.3 V at 1 V/ms, 5 mA (tm, 27 °C)", legend="tr")
    m = t > 0.4e-3
    ax.line(t[m] * 1e3, vin[m], K, 2.0, label="VIN")
    ax.line(t[m] * 1e3, vo[m], B, 2.4, label="VOUT")
    ax.line(t[m] * 1e3, pg[m], G, 1.8, label="PWR_GOOD")
    if r:
        ax.hline(r["uvlo_f"], R, "5,4", text=f"off {r['uvlo_f']:.3f} V", anchor="start", below=True)
        ax.hline(r["uvlo_r"], R, "2,3", text=f"on {r['uvlo_r']:.3f} V", anchor="start")
    save(p, "uvlo")


def fig_steps():
    a = csv(TM, "step.csv")
    b = csv(TM, "line_step.csv")
    if a is None or b is None:
        return
    p = Plot(900, 620)
    t = a[:, 0] * 1e6
    m1 = t < 100
    m2 = t > 150
    a1 = p.panel(90, 40, 360, 220, (-10, 60), (1.785, 1.810), ylabel="VOUT  [V]", title="Load 1 → 20 mA (1 µs)",
                 legend="br")
    a1.line(t[m1], a[m1, 1], B, 2.2)
    a2 = p.panel(500, 40, 360, 220, (190, 260), (1.785, 1.810), title="Load 20 → 1 mA (1 µs)", legend="br")
    a2.line(t[m2], a[m2, 1], B, 2.2)
    for c in CORNERS[1:5] + [("tm_27_3.3_c2u2_esr0.5", "tm", "2.2 µF ESR 0.5 Ω"), ("tm_27_3.3_c0u47", "tm", "0.47 µF")]:
        x = csv(c[0], "step.csv")
        if x is None:
            continue
        tt = x[:, 0] * 1e6
        a1.line(tt[tt < 100], x[tt < 100, 1], "#999999", 1.0, dash="4,3")
        a2.line(tt[tt > 150], x[tt > 150, 1], "#999999", 1.0, dash="4,3")
    a1.text(-8, 1.7865, "grey: PVT corners and COUT 0.47 / 2.2 µF", "#777777", 10)
    t = b[:, 0] * 1e6
    m1 = t < 100
    m2 = t > 150
    a3 = p.panel(90, 330, 360, 220, (-10, 60), (1.794, 1.801), xlabel="Time  [µs]", ylabel="VOUT  [V]",
                 title="VIN 3.0 → 3.6 V (1 µs), 5 mA")
    a3.line(t[m1], b[m1, 2], R, 2.2)
    a4 = p.panel(500, 330, 360, 220, (190, 260), (1.794, 1.801), xlabel="Time  [µs]", title="VIN 3.6 → 3.0 V (1 µs)")
    a4.line(t[m2], b[m2, 2], R, 2.2)
    save(p, "steps")


def fig_short():
    a = csv(TM, "short.csv")
    if a is None:
        return
    t, vo, i, pg = a.T
    t = t * 1e6
    p = Plot(900, 520)
    a1 = p.panel(90, 40, 770, 220, (-20, 500), (-0.1, 2.0), ylabel="Voltage  [V]",
                 title="Output short (1 Ω) for 200 µs at 5 mA load (tm, 27 °C)", legend="tr")
    a1.line(t, vo, B, 2.4, label="VOUT")
    a1.line(t, pg, G, 1.8, label="PWR_GOOD")
    a2 = p.panel(90, 310, 770, 160, (-20, 500), (0, 110), xlabel="Time  [µs]", ylabel="I(VIN)  [mA]")
    a2.line(t, i * 1e3, O, 2.2)
    save(p, "short")


# ------------------------------------------------------------------ tables
def tables():
    rows = []
    hdr = ("Corner", "VOUT 0 / 20 mA [V]", "Iq [µA]", "Line reg. 20 mA [mV/V]", "ΔVOUT 0→20 mA [mV]", "I_lim [mA]",
           "PM min, rated load [°] (at)", "PSRR 1 kHz 20 mA [dB]", "Step 1↔20 mA [mV]", "UVLO on / off [V]",
           "t_PG / t_POR [µs]", "Dropout 20 mA [mV]")
    for run, c, lab in CORNERS + [("tm_27_3.3_c2u2_esr0.5", "tm", "27 °C, 2.2 µF ESR 0.5 Ω"),
                                  ("tm_27_3.3_c0u47", "tm", "27 °C, 0.47 µF")]:
        op, ln, ld, ac = res(run, "op"), res(run, "line"), res(run, "load"), res(run, "ac")
        ps, st, uv, en = res(run, "psrr"), res(run, "step"), res(run, "uvlo"), res(run, "en")
        if not any((op, ac)):
            continue
        f = lambda v, s="{:.4f}": (s.format(v) if v is not None and np.isfinite(v) else "–")  # noqa: E731
        k = list(ld.keys())[0] if ld else None
        rated = ("0", "10u", "100u", "1m", "5m") if "c0u47" in run else ("0", "10u", "100u", "1m", "5m", "20m")
        pmmin = min(((r["pm"], l) for l, r in ac.items() if l in rated), default=(None, "")) if ac else (None, "")
        rows.append((f"{c} {lab}",
                     f"{f(op['nl']['vout'])} / {f(op['l20']['vout'])}" if op else "–",
                     f(op["iq"] * 1e6, "{:.0f}") if op else "–",
                     f(ln["20m"]["line_reg"] * 1e3, "{:.2f}") if ln else "–",
                     f(ld[k]["dv_20m"] * 1e3, "{:+.2f}") if ld else "–",
                     f(ld[k]["ilim"] * 1e3, "{:.0f}") if ld else "–",
                     f"{pmmin[0]:.0f} ({pmmin[1]})" if pmmin[0] is not None else "–",
                     f(ps["20m"]["psrr_1k"], "{:.0f}") if ps else "–",
                     f"−{st['undershoot'] * 1e3:.1f} / +{st['overshoot'] * 1e3:.1f}" if st else "–",
                     f"{uv['uvlo_r']:.3f} / {uv['uvlo_f']:.3f}" if uv else "–",
                     f"{en['t_pg'] * 1e6:.1f} / {en['t_por'] * 1e6:.0f}" if en else "–",
                     f(ln["20m"]["dropout"] * 1e3, "{:.0f}") if ln else "–"))
    out = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    # temperature table (tm)
    t = res(TM, "temp")
    if t:
        out += ["", "| T [°C] | " + " | ".join(str(x) for x in t["t"]) + " |", "|---|" + "---|" * len(t["t"]),
                "| VBG [V] | " + " | ".join(f"{v:.4f}" for v in t["vbg"]) + " |",
                "| VOUT [V] (5 mA) | " + " | ".join(f"{v:.4f}" for v in t["vout"]) + " |",
                "| I_GND [µA] | " + " | ".join(f"{v * 1e6:.0f}" for v in t["ivin"]) + " |"]
    cs = res(TM, "capsweep")
    if cs:
        out += ["", "| COUT | ESR | Load | Crossover [kHz] | PM [°] | GM [dB] |", "|---|---|---|---|---|---|"]
        out += [f"| {x['cout'] * 1e6:g} µF | {x['esr']:g} Ω | {x['il']} | {x['fc'] / 1e3:.1f} | {x['pm']:.0f} | "
                f"{x['gm']:.0f} |" for x in cs]
    open(os.path.join(DATA, "tables.md"), "w").write("\n".join(out) + "\n")
    print("wrote", os.path.join(DATA, "tables.md"))


def main():
    os.makedirs(FIG, exist_ok=True)
    for fn in (fig_block, fig_temp, fig_line, fig_load, fig_bode, fig_pm, fig_capsweep, fig_psrr_zout, fig_noise,
               fig_start, fig_enable, fig_uvlo, fig_steps, fig_short, tables):
        fn()


if __name__ == "__main__":
    main()
