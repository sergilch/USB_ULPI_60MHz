#!/usr/bin/env python3
"""gen_figures.py - figures and result tables of the REF datasheet

Usage (numpy only; rsvg-convert for the PNG copies used by Word):
    python3 AFE/REF/datasheet/gen_figures.py

Reads the ngspice results that sim/run_all.py copied to data/<run>/
(results_<case>.json, code.json) and writes
  fig/*.svg (+ .png at 2x)       the datasheet figures
  data/tables.md                 the corner tables quoted in ref_datasheet.md
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
GR = "#888888"
TM = "tm_27_3.3"
C27 = [("tm_27_3.3", "tm"), ("ws_27_3.3", "ws"), ("wp_27_3.3", "wp"), ("wo_27_3.3", "wo"), ("wz_27_3.3", "wz")]
CX = [("tm_27_3.3", "tm 27 °C 3.3 V"), ("tm_-40_2.97", "tm −40 °C 2.97 V"), ("tm_125_3.63", "tm 125 °C 3.63 V"),
      ("ws_-40_2.97", "ws −40 °C 2.97 V"), ("ws_125_2.97", "ws 125 °C 2.97 V"), ("wp_-40_3.63", "wp −40 °C 3.63 V"),
      ("wp_125_3.63", "wp 125 °C 3.63 V"), ("ws_27_3.3", "ws 27 °C 3.3 V"), ("wp_27_3.3", "wp 27 °C 3.3 V"),
      ("wo_27_3.3", "wo 27 °C 3.3 V"), ("wz_27_3.3", "wz 27 °C 3.3 V")]
CCOL = {"tm": K, "ws": R, "wp": B, "wo": G, "wz": O}


def res(run, case):
    p = os.path.join(DATA, run, f"results_{case}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def code(run):
    p = os.path.join(DATA, run, "code.json")
    return json.load(open(p))["code"] if os.path.exists(p) else 8


def save(p, name):
    path = os.path.join(FIG, name + ".svg")
    p.save(path)
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-z", "2", "-o", path[:-4] + ".png", path], check=True)
    print("wrote", path)


# ------------------------------------------------------------------ figures
def fig_sheets():
    for n in ("block", "bandgap", "amps", "current"):
        for ext in ("svg", "png"):
            src = os.path.join(DUT, "doc", f"ref_{n}.{ext}")
            if os.path.exists(src):
                shutil.copy(src, os.path.join(FIG, f"sch_{n}.{ext}"))
    print("copied schematic sheets")


def fig_trim():
    p = Plot(900, 470)
    ax = p.panel(90, 40, 770, 360, (-0.5, 15.5), (1.12, 1.28), xlabel="TRIM[3:0] code", ylabel="TX_VREF  [V]",
                 title="Trim characteristic at 27 °C, VDD33 3.3 V (all process corners)", legend="tl",
                 xticks=list(range(16)))
    for run, c in C27:
        r = res(run, "trim")
        if not r:
            continue
        ax.line(r["code"], r["tx"], CCOL[c], 2.0, label=f"{c}: LSB {r['lsb'] * 1e3:.2f} mV, code {r['best']:04b}")
        ax.points([r["best"]], [r["tx"][r["best"]]], CCOL[c])
    ax.hline(1.2, R, "6,4", text="1.200 V", anchor="end")
    ax.band(1.194, 1.206, G, 0.08)
    save(p, "trim")


def fig_temp():
    p = Plot(900, 620)
    a1 = p.panel(90, 40, 770, 230, (-40, 125), (1.13, 1.27), ylabel="TX_VREF  [V]",
                 title="TX_VREF vs temperature, untrimmed (code 1000b, VDD33 3.3 V)", legend="tl")
    a2 = p.panel(90, 330, 770, 230, (-40, 125), (1.188, 1.212), xlabel="Temperature  [°C]", ylabel="TX_VREF  [V]",
                 title="Trimmed at 27 °C (code per corner), VDD33 2.97 / 3.3 / 3.63 V", legend="bl")
    for run, c in C27:
        r = res(run, "temp")
        if not r:
            continue
        k = code(run)
        a1.line(r["temps"], r["data"]["8_3.3"]["tx"], CCOL[c], 2.0, label=c)
        for vd, ds in (("2.97", "2,3"), ("3.3", None), ("3.63", "6,3")):
            key = f"{k}_{vd}"
            if key in r["data"]:
                a2.line(r["temps"], r["data"][key]["tx"], CCOL[c], 1.8 if ds else 2.2, dash=ds,
                        label=f"{c} ({k:04b})" if vd == "3.3" else None)
    a2.band(1.194, 1.206, G, 0.08)
    a2.hline(1.2, GR, "4,4")
    save(p, "temp")


def fig_temp_i():
    p = Plot(900, 620)
    a1 = p.panel(90, 40, 770, 230, (-40, 125), (4.90, 5.10), ylabel="TX_I_5U  [µA]",
                 title="TX_I_5U vs temperature (trimmed, RBIAS 12.0 kΩ ideal, VDD33 2.97 / 3.3 / 3.63 V)", legend="bl")
    a2 = p.panel(90, 330, 770, 230, (-40, 125), (180, 320), xlabel="Temperature  [°C]", ylabel="IDD  [µA]",
                 title="Supply current (incl. 100 µA in RBIAS and 5 µA out of TX_I_5U)", legend="tl")
    for run, c in C27:
        r = res(run, "temp")
        if not r:
            continue
        k = code(run)
        for vd, ds in (("2.97", "2,3"), ("3.3", None), ("3.63", "6,3")):
            key = f"{k}_{vd}"
            if key in r["data"]:
                a1.line(r["temps"], np.array(r["data"][key]["i5"]) * 1e6, CCOL[c], 1.8, dash=ds,
                        label=c if vd == "3.3" else None)
                a2.line(r["temps"], np.array(r["data"][key]["idd"]) * 1e6, CCOL[c], 1.8, dash=ds,
                        label=c if vd == "3.3" else None)
    save(p, "temp_i")


def fig_line():
    r = res(TM, "line")
    if not r:
        return
    p = Plot(900, 620)
    a1 = p.panel(90, 40, 770, 230, (1.8, 3.7), (1.15, 1.22), ylabel="Voltage  [V]",
                 title="Line: VDD33 ramped 3.63 → 1.8 V (tm, 27 °C)", legend="br")
    a1.line(r["vdd"], r["tx"], B, 2.2, label=f"TX_VREF ({r['line_reg'] * 1e3:+.2f} mV/V)")
    a1.line(r["vdd"], r["rx"], O, 1.4, dash="5,3", label="RX_VREF")
    a1.vline(2.97, text="2.97 V")
    a1.vline(r["vmin"], text=f"−0.5 % at {r['vmin']:.2f} V")
    a2 = p.panel(90, 330, 770, 230, (1.8, 3.7), (4.0, 5.2), xlabel="VDD33  [V]", ylabel="TX_I_5U  [µA]",
                 title="Reference current (output at 0.6 V)", legend="br")
    a2.line(r["vdd"], np.abs(np.array(r["i5"])) * 1e6, R, 2.2, label=f"TX_I_5U ({r['i5_line'] * 100:+.3f} %/V)")
    a2.vline(2.97, text="2.97 V")
    a2.vline(r["vmin_i5"], text=f"−1 % at {r['vmin_i5']:.2f} V", left=True)
    save(p, "line")


def fig_psrr():
    p = Plot(900, 470)
    ax = p.panel(90, 40, 770, 360, (10, 1e8), (0, 100), xlog=True, xlabel="Frequency  [Hz]", ylabel="PSRR  [dB]",
                 title="Supply rejection VDD33 → TX_VREF (corners) and → TX_I_5U (tm)", legend="bl")
    for run, lab in CX:
        r = res(run, "psrr")
        if not r:
            continue
        c = lab.split()[0]
        if run == TM:
            ax.line(r["f"], r["tx"], K, 2.4, label="TX_VREF, tm 27 °C 3.3 V")
            ax.line(r["f"], -np.array(r["i5"]), R, 2.0, dash="6,3", label="TX_I_5U (dB re 1/V), tm")
        else:
            ax.line(r["f"], r["tx"], CCOL[c], 1.0, label=None)
    ax.hline(40, GR, "4,4", text="40 dB", anchor="start")
    ax.text(2e5, 92, "thin lines: other corners (TX_VREF)", size=11)
    save(p, "psrr")


def fig_noise():
    r = res(TM, "noise")
    if not r:
        return
    p = Plot(900, 620)
    t, i = r["tx"], r["i5"]
    a1 = p.panel(90, 40, 770, 230, (1, 1e7), (1e-8, 1e-4), xlog=True, ylog=True, ylabel="V/√Hz",
                 title="Output noise density (tm, 27 °C)", legend="tr")
    a1.line(t["f"], t["s"], B, 2.2, label=f"TX_VREF: {t['rms_10_100k'] * 1e6:.0f} µV rms (10 Hz–100 kHz), "
                                           f"{t['at_1k'] * 1e6:.2f} µV/√Hz at 1 kHz")
    a2 = p.panel(90, 330, 770, 230, (1, 1e7), (1e-13, 1e-9), xlog=True, ylog=True, xlabel="Frequency  [Hz]",
                 ylabel="A/√Hz", legend="tr")
    a2.line(i["f"], i["s"], R, 2.2, label=f"TX_I_5U: {i['rms_10_100k'] * 1e9:.2f} nA rms (10 Hz–100 kHz), "
                                          f"{i['at_1k'] * 1e12:.1f} pA/√Hz at 1 kHz")
    save(p, "noise")


def fig_stab():
    r = res(TM, "stab")
    if not r:
        return
    p = Plot(900, 640)
    a1 = p.panel(90, 40, 770, 260, (10, 1e9), (-40, 100), xlog=True, ylabel="|T|  [dB]",
                 title="Loop gains (tm, 27 °C): bandgap, A1, TX buffer (10 / 100 pF), current loop (RBIAS 20 / 100 pF)",
                 legend="tr")
    a2 = p.panel(90, 350, 770, 230, (10, 1e9), (-270, 30), xlog=True, xlabel="Frequency  [Hz]",
                 ylabel="∠T  [°]", yticks=[-270, -180, -90, 0], legend="bl")
    for k, lab, col in (("bg", "bandgap", K), ("a1", "A1", G), ("tx10", "B_TX 10 pF", B), ("tx100", "B_TX 100 pF", V),
                        ("i20", "A_I RBIAS 20 pF", R), ("i100", "A_I RBIAS 100 pF", O)):
        x = r.get(k)
        if not x:
            continue
        a1.line(x["f"], x["g"], col, 1.8, label=f"{lab}: PM {x['pm']:.0f}°")
        a2.line(x["f"], np.array(x["ph"]), col, 1.8)
    a1.hline(0, GR, "4,4")
    a2.hline(-180, R, "6,4")
    a1.text(1.2e8, -32, "A1 > 100 MHz: feedthrough", size=10.5, anchor="middle")
    save(p, "stab")


def fig_zout():
    r = res(TM, "zout")
    if not r:
        return
    p = Plot(900, 470)
    ax = p.panel(90, 40, 770, 360, (10, 1e8), (1, 1e5), xlog=True, ylog=True, xlabel="Frequency  [Hz]",
                 ylabel="|Z|  [Ω]", title="Output impedance of TX_VREF (tm, 27 °C, 10 pF external + 2 pF on chip)",
                 legend="tr")
    ax.line(r["f"], r["z"], B, 2.2, label="TX_VREF")
    save(p, "zout")


def fig_comply():
    p = Plot(900, 470)
    ax = p.panel(90, 40, 770, 360, (0, 3.7), (0, 5.5), xlabel="V(TX_I_5U)  [V]", ylabel="TX_I_5U  [µA]",
                 title="Output characteristic of TX_I_5U (VDD33 at the run value)", legend="bl")
    for run, lab in CX:
        r = res(run, "comply")
        if not r or run not in (TM, "ws_-40_2.97", "ws_125_2.97", "wp_-40_3.63", "wp_125_3.63"):
            continue
        c = lab.split()[0]
        col = {TM: K, "ws_-40_2.97": R, "ws_125_2.97": O, "wp_-40_3.63": B, "wp_125_3.63": V}[run]
        ax.line(r["v"][::5], np.array(r["i"][::5]) * 1e6, col, 1.8, label=f"{lab}: 1 % up to {r['vmax']:.2f} V")
        del c
    save(p, "comply")


def fig_rbias():
    r = res(TM, "rbias")
    if not r:
        return
    p = Plot(900, 470)
    ax = p.panel(90, 40, 770, 360, (5, 25), (0, 22), xlabel="RBIAS  [kΩ]", ylabel="TX_I_5U  [µA]",
                 title="TX_I_5U vs RBIAS (tm, 27 °C): I = VREF / RBIAS / 20", legend="tr")
    rb = np.array(r["rbias"]) / 1e3
    ax.line(rb, np.array(r["i5"]) * 1e6, B, 2.2, label="simulated")
    x = np.linspace(5, 25, 50)
    ax.line(x, 1.2 / x / 20 * 1e3, R, 1.4, dash="6,3", label="1.2 V / RBIAS / 20")
    ax.points(rb, np.array(r["i5"]) * 1e6, B)
    save(p, "rbias")


def fig_start():
    r = res(TM, "start")
    if not r:
        return
    p = Plot(900, 640)
    a1 = p.panel(90, 40, 770, 260, (0, 50), (-0.05, 1.35), ylabel="Voltage  [V]",
                 title="BIAS_EN ↑ at 2 µs, ↓ at 40 µs (tm, 27 °C)", legend="br")
    for k, col, lab in (("en10", B, "TX_VREF, 10 pF"), ("en100", R, "TX_VREF, 100 pF")):
        x = r[k]
        a1.line(np.array(x["t"]) * 1e6, x["tx"], col, 2.0, label=f"{lab}: 0.5 % in {x['t_tx_05'] * 1e6:.1f} µs")
    a1.vline(2, text="BIAS_EN", top=True)
    a1.vline(12, text="+10 µs", top=True)
    a2 = p.panel(90, 360, 770, 220, (0, 50), (0, 5.6), xlabel="Time  [µs]", ylabel="TX_I_5U  [µA]", legend="br")
    x = r["en10"]
    a2.line(np.array(x["t"]) * 1e6, np.array(x["i5"]) * 1e6, G, 2.0,
            label=f"TX_I_5U: 1 % in {x['t_i5_1'] * 1e6:.1f} µs")
    save(p, "start")


def fig_tran():
    r = res(TM, "tran")
    if not r:
        return
    p = Plot(900, 640)
    a1 = p.panel(90, 40, 770, 230, (10, 100), (-5, 5), ylabel="ΔTX_VREF  [mV]",
                 title="VDD33 step 3.0 → 3.6 V at 20 µs, 3.6 → 3.0 V at 60 µs (1 µs edges)", legend="tr")
    x = r["line"]
    t = np.array(x["t"]) * 1e6
    tx = np.array(x["tx"])
    b = tx[(t > 15) & (t < 20)].mean()
    a1.line(t, (tx - b) * 1e3, B, 2.0, label=f"peak +{x['up'] * 1e3:.1f} / −{x['down'] * 1e3:.1f} mV")
    a2 = p.panel(90, 330, 770, 230, (15, 60), (-80, 80), xlabel="Time  [µs]", ylabel="ΔV  [mV]",
                 title="10 µA pulses (2 µs) into TX_VREF: TX → RX isolation", legend="tr")
    y = r["kick"]
    t = np.array(y["t"]) * 1e6
    tx, rx = np.array(y["tx"]), np.array(y["rx"])
    m = (t > 15) & (t < 20)
    a2.line(t, (tx - tx[m].mean()) * 1e3, R, 2.0, label=f"TX_VREF ({y['tx_dev'] * 1e3:.0f} mV)")
    a2.line(t, (rx - rx[m].mean()) * 1e3, G, 2.0, label=f"RX_VREF ({y['rx_dev'] * 1e6:.0f} µV)")
    save(p, "tran")


def fig_beh():
    """afe_ref.va (ngspice copy afe_ref_beh.sp) against the transistor netlist, tm 27 C."""
    BH = "tm_27_3.3_beh"
    st, sb = res(TM, "start"), res(BH, "start")
    lt, lb = res(TM, "line"), res(BH, "line")
    tt, tb = res(TM, "temp"), res(BH, "temp")
    ct, cb = res(TM, "comply"), res(BH, "comply")
    if not all((st, sb, lt, lb, tt, tb, ct, cb)):
        return
    p = Plot(900, 700)
    a1 = p.panel(80, 40, 360, 250, (0, 16), (-0.05, 1.3), xlabel="Time  [µs]", ylabel="TX_VREF  [V]",
                 title="Enable at 2 µs, 10 / 100 pF", legend="br")
    for k, col in (("en10", B), ("en100", R)):
        a1.line(np.array(st[k]["t"]) * 1e6, st[k]["tx"], col, 2.4, label=f"circuit {k[2:]} pF")
        a1.line(np.array(sb[k]["t"]) * 1e6, sb[k]["tx"], K, 1.4, dash="5,3", label=f"model {k[2:]} pF")
    a2 = p.panel(520, 40, 360, 250, (1.8, 3.7), (2.5, 5.3), xlabel="VDD33  [V]", ylabel="TX_I_5U  [µA]",
                 title="TX_I_5U vs VDD33 (TX_VREF inset text)", legend="br")
    a2.line(lt["vdd"], np.abs(np.array(lt["i5"])) * 1e6, B, 2.4, label="circuit")
    a2.line(lb["vdd"], np.abs(np.array(lb["i5"])) * 1e6, K, 1.4, dash="5,3", label="model")
    a2.text(1.9, 5.15, f"TX_VREF 0.5 % at {lt['vmin']:.2f} / {lb['vmin']:.2f} V", size=10.5)
    a3 = p.panel(80, 380, 360, 250, (-40, 125), (1.194, 1.203), xlabel="Temperature  [°C]", ylabel="TX_VREF  [V]",
                 title="Temperature (code 1000b, 3.3 V)", legend="bl")
    a3.line(tt["temps"], tt["data"]["8_3.3"]["tx"], B, 2.4, label="circuit")
    a3.line(tb["temps"], tb["data"]["8_3.3"]["tx"], K, 1.4, dash="5,3", label="model")
    a4 = p.panel(520, 380, 360, 250, (0, 3.3), (0, 5.5), xlabel="V(TX_I_5U)  [V]", ylabel="TX_I_5U  [µA]",
                 title="Output characteristic", legend="bl")
    a4.line(ct["v"][::5], np.array(ct["i"][::5]) * 1e6, B, 2.4, label="circuit")
    a4.line(cb["v"][::5], np.array(cb["i"][::5]) * 1e6, K, 1.4, dash="5,3", label="model")
    save(p, "beh")


# ------------------------------------------------------------------ tables
def tables():
    L = []
    hdr = ["Run", "Code", "TX_VREF [V]", "RX−TX [mV]", "V(RBIAS) [V]", "TX_I_5U [µA]", "IDD [µA]",
           "Line [mV/V]", "PSRR min [dB]", "PM min [°]", "Settle 10 / 100 pF [µs]", "Compliance [V]"]
    L.append("| " + " | ".join(hdr) + " |")
    L.append("|" + "---|" * len(hdr))
    for run, lab in CX:
        op = res(run, "op")
        if not op:
            continue
        ln, ps, st, sa, co = (res(run, k) for k in ("line", "psrr", "stab", "start", "comply"))
        pm = min(x["pm"] for x in st.values()) if st else float("nan")
        L.append(f"| {lab} | {op['code']:04b} | {op['tx']:.4f} | {(op['rx'] - op['tx']) * 1e3:+.2f} | {op['vrb']:.4f} | "
                 f"{op['i5'] * 1e6:.3f} | {op['idd'] * 1e6:.0f} | "
                 f"{ln['line_reg'] * 1e3:+.2f} | " if ln else "– | ")
        L[-1] += (f"{ps['tx_min']:.1f} | " if ps else "– | ") + f"{pm:.0f} | " + \
            (f"{sa['en10']['t_tx_05'] * 1e6:.1f} / {sa['en100']['t_tx_05'] * 1e6:.1f} | " if sa else "– | ") + \
            (f"{co['vmax']:.2f} |" if co else "– |")
    L.append("")
    L.append("| Corner | Code | Untrimmed (1000b) min / max [V] | Trimmed min / max [V] | Trimmed error [%] | "
             "TC trimmed [ppm/K] | TX_I_5U min / max [µA] |")
    L.append("|---|---|---|---|---|---|---|")
    for run, c in C27:
        r = res(run, "temp")
        if not r:
            continue
        k = code(run)
        L.append(f"| {c} | {k:04b} | {r['min_8']:.4f} / {r['max_8']:.4f} | {r[f'min_{k}']:.4f} / {r[f'max_{k}']:.4f} | "
                 f"{(r[f'min_{k}'] / 1.2 - 1) * 100:+.2f} / {(r[f'max_{k}'] / 1.2 - 1) * 100:+.2f} | "
                 f"{r[f'tc_{k}']:.0f} | {r[f'i5min_{k}'] * 1e6:.3f} / {r[f'i5max_{k}'] * 1e6:.3f} |")
    L.append("")
    r = res(TM, "temp")
    if r:
        k = code(TM)
        L.append("| T [°C] | " + " | ".join(str(t) for t in r["temps"]) + " |")
        L.append("|" + "---|" * (len(r["temps"]) + 1))
        d = r["data"][f"{k}_3.3"]
        L.append("| TX_VREF [V] | " + " | ".join(f"{v:.4f}" for v in d["tx"]) + " |")
        L.append("| VBG code 1000b [V] | " + " | ".join(f"{v:.4f}" for v in d["vbg8"]) + " |")
        L.append("| TX_I_5U [µA] | " + " | ".join(f"{v * 1e6:.3f}" for v in d["i5"]) + " |")
        L.append("| IDD [µA] | " + " | ".join(f"{v * 1e6:.0f}" for v in d["idd"]) + " |")
    open(os.path.join(DATA, "tables.md"), "w").write("\n".join(L) + "\n")
    print("wrote", os.path.join(DATA, "tables.md"))


def main():
    os.makedirs(FIG, exist_ok=True)
    fig_sheets()
    for f in (fig_trim, fig_temp, fig_temp_i, fig_line, fig_psrr, fig_noise, fig_stab, fig_zout, fig_comply,
              fig_rbias, fig_start, fig_tran, fig_beh):
        f()
    tables()


if __name__ == "__main__":
    main()
