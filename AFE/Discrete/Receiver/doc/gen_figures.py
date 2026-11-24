#!/usr/bin/env python3
"""gen_figures.py - figures of the receiver-board documentation

    python3 AFE/Discrete/Receiver/doc/gen_figures.py [--no-png]

Reads sim/results (run sim/run_sims.py first) and writes doc/fig/*.svg, plus
*.png at 2x (rsvg-convert) for the Word document.  Plot helper: the repo's
AFE/doc/pll_datasheet/svgplot.py.
"""
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
SIM = os.path.join(HERE, "..", "sim")
FIG = os.path.join(HERE, "fig")
sys.path.insert(0, os.path.join(ROOT, "AFE", "doc", "pll_datasheet"))
sys.path.insert(0, SIM)
from svgplot import Plot  # noqa: E402
import run_sims as rs     # noqa: E402

B, R, G, O, P, K = "#1f4e9c", "#c0392b", "#2e8b57", "#d4860b", "#6c3483", "#555555"
UI = rs.UI
SUM = json.load(open(os.path.join(SIM, "results", "summary.json")))


def wave(name, n=None, t0=None, t1=None):
    f = os.path.join(SIM, "results", name, "wave.txt")
    if not os.path.exists(f):
        return None
    w = rs.load_wave(name)
    if t0 is not None:
        m = (w["t"] >= t0) & (w["t"] <= t1)
        w = {k: v[m] for k, v in w.items()}
    if n:
        tg = np.linspace(w["t"][0], w["t"][-1], n)
        w = {k: (tg if k == "t" else np.interp(tg, w["t"], v)) for k, v in w.items()}
    return w


def fold(ax, t, d, t0, nb, color, width=0.5):
    grid = np.linspace(0, 2 * UI, 101)
    for i in range(1, nb - 1):
        ts = t0 + (i - 0.5) * UI + grid
        ax.line(grid / UI, 1e3 * np.interp(ts, t, d), color, width)


# ---------------------------------------------------------------- eyes
def fig_eye():
    w, wr = wave("eye_tap"), wave("ref_tap")
    if w is None:
        return
    c = rs.eye_case(rs.corner(), "tap")
    nb = c["n_line"] - 8
    p = Plot(900, 430)
    for k, (node, title, lim) in enumerate(((("fp", "fm"), "Device end (0.5 m after the board)", 600),
                                            (("ry", "rz"), "RX_OUT (SN65LVDS100, 100 Ohm load)", 500))):
        ax = p.panel(70 + k * 430, 40, 380, 330, (0, 2), (-lim, lim), xlabel="time  [UI = 2.083 ns]",
                     ylabel="differential voltage  [mV]" if k == 0 else "", title=title, legend="tr")
        key = "device" if k == 0 else "rx_out"
        e = SUM["eye_tap"][key]
        dly = SUM["eye_tap"]["device"]["delay_ns"] * 1e-9 if k == 0 else \
            (SUM["eye_tap"]["tap"]["delay_ns"] + e["delay_ns"]) * 1e-9
        t0 = rs.T0 + c["first_ui"] * UI + dly + rs.TR / 2
        if k == 0 and wr is not None:
            fold(ax, wr["t"], wr[node[0]] - wr[node[1]], t0, nb, "#bbbbbb", 0.5)
            ax.line([0], [0], "#bbbbbb", 2, label="without the board")
        fold(ax, w["t"], w[node[0]] - w[node[1]], t0, nb, B if k == 0 else P)
        ax.line([0], [0], B if k == 0 else P, 2, label="with the board (tap mode)" if k == 0 else "RX_OUT")
        if k == 0:
            ax.text(0.04, -560, "EH %.0f mV with board, %.0f mV without" % (
                e["eye_height_mV"], SUM["ref_tap"]["device"]["eye_height_mV"]), K, 10)
        else:
            ax.text(0.04, -460, "jitter %.0f ps p-p, delay %.2f ns after the tap" % (
                e["jitter_pp_ps"], e["delay_ns"]), K, 10)
    p.save(os.path.join(FIG, "eye_tap.svg"))


# ---------------------------------------------------------------- squelch timing
def fig_squelch():
    r = SUM.get("eye_tap")
    c = rs.eye_case(rs.corner(), "tap")
    t_start = rs.T0 + c["first_ui"] * UI + r["tap"]["delay_ns"] * 1e-9
    t_end = rs.T0 + (c["first_ui"] + c["n_line"]) * UI + r["tap"]["delay_ns"] * 1e-9
    p = Plot(900, 600)
    for k, (ta, tb, title) in enumerate(((t_start - 10e-9, t_start + 40e-9, "Packet start (SYNC)"),
                                         (t_end - 25e-9, t_end + 25e-9, "Packet end (EOP)"))):
        w = wave("eye_tap", 3000, ta, tb)
        if w is None:
            return
        t = (w["t"] - (t_start if k == 0 else t_end)) * 1e9
        x0 = 70 + k * 430
        a1 = p.panel(x0, 30, 380, 150, (t[0], t[-1]), (-500, 500), ylabel="[mV]" if k == 0 else "",
                     title=title, legend="tr")
        a1.line(t, 1e3 * (w["tp"] - w["tm"]), B, 1.2, label="vd at the tap")
        for v in (125, -125):
            a1.hline(v, R, "4,3")
        a2 = p.panel(x0, 225, 380, 150, (t[0], t[-1]), (-0.2, 3.6), ylabel="[V]" if k == 0 else "",
                     legend="tr")
        a2.line(t, w["sqa"], G, 1.0, label="SQ+ (U9)")
        a2.line(t, w["sqb"], O, 1.0, label="SQ- (U10)")
        a3 = p.panel(x0, 420, 380, 140, (t[0], t[-1]), (-0.2, 3.6),
                     xlabel="time from the first edge / end of EOP  [ns]", ylabel="[V]" if k == 0 else "",
                     legend="tr")
        a3.line(t, w["envs"], P, 1.6, label="ENV_SQ")
        a3.line(t, w["sqact"], K, 1.6, label="SQ_ACT")
        a3.hline(3.3 * 10 / 28, R, "4,3", text="V_ETH")
    p.save(os.path.join(FIG, "squelch_timing.svg"))


# ---------------------------------------------------------------- thresholds over corners
def fig_trips():
    p = Plot(900, 380)
    for k, (pre, lo, hi, lim, title) in enumerate((("sq_", 100, 150, (60, 180), "Squelch trip |vd|"),
                                                   ("dc_", 525, 625, (450, 700), "Disconnect trip |vd|"))):
        names = ["nom"] + sorted(n[len(pre):] for n in SUM if n.startswith(pre) and n != pre + "nom")
        names = [n for n in names if pre + n in SUM and "error" not in SUM[pre + n]]
        ax = p.panel(70 + k * 430, 30, 380, 280, (-0.5, len(names) - 0.5), lim,
                     ylabel="[mV] at the tap" if k == 0 else "", title=title, legend="tr", xticks=[])
        ax.band(lo, hi, G, 0.10)
        ax.hline(lo, G, "4,3"); ax.hline(hi, G, "4,3")
        for i, n in enumerate(names):
            r = SUM[pre + n]
            if r["max_off_mV"] is not None and r["min_on_mV"] is not None:
                ax.line([i, i], [r["max_off_mV"], r["min_on_mV"]], B, 3)
                ax.points([i], [r["trip_mV"]], B)
            ax.text(i, lim[0] + (0.03 if i % 2 == 0 else 0.08) * (lim[1] - lim[0]), n.replace("_", "/"), K, 8, anchor="middle")
        ax.text(-0.3, lim[1] - 0.08 * (lim[1] - lim[0]),
                "USB 2.0: %d .. %d mV (VDD/T corners, comparator offset +-5 mV)" % (lo, hi), K, 9)
    p.save(os.path.join(FIG, "trips.svg"))


def main():
    os.makedirs(FIG, exist_ok=True)
    fig_eye()
    fig_squelch()
    fig_trips()
    if "--no-png" not in sys.argv:
        for f in sorted(os.listdir(FIG)):
            if f.endswith(".svg"):
                subprocess.run(["rsvg-convert", "-z", "2", "-o", os.path.join(FIG, f[:-4] + ".png"),
                                os.path.join(FIG, f)], check=True)
    print("\n".join(sorted(os.listdir(FIG))))


if __name__ == "__main__":
    main()
