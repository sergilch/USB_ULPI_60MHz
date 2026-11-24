#!/usr/bin/env python3
"""gen_figures.py - figures of the PLL-board documentation

    python3 AFE/Discrete/PLL/doc/gen_figures.py [--no-png]

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
import tables             # noqa: E402

B, R, G, O, P, K = "#1f4e9c", "#c0392b", "#2e8b57", "#d4860b", "#6c3483", "#555555"
RES = os.path.join(SIM, "results")


def res(name):
    p = os.path.join(RES, name, "result.json")
    return json.load(open(p)) if os.path.exists(p) else None


def wave(name):
    p = os.path.join(RES, name, "wave.txt")
    return np.loadtxt(p) if os.path.exists(p) else None


def fig_vco():
    p = Plot(900, 420)
    ax = p.panel(70, 30, 380, 320, (0, 4.75), (370, 530), xlabel="VTUNE  [V]", ylabel="f_VCO  [MHz]",
                 title="VCO tuning curve", legend="br")
    ax.band(400, 500, G, 0.08)
    ax.hline(480, R, "4,3", text="480 MHz")
    ax.hline(520, K, "2,3", text="26 MHz x 20")
    for name, col, lab in (("vco_27_4.82", B, "27 C"), ("vco_-40_4.82", P, "-40 C"),
                           ("vco_85_4.82", O, "85 C"), ("vcotol_m2_-40", K, "L -2 %, -40 C"),
                           ("vcotol_p2_85", G, "L +2 %, 85 C")):
        r = res(name)
        if r:
            ax.line([x["vt"] for x in r["rows"]], [x["f"] / 1e6 for x in r["rows"]], col, 1.8, label=lab)
    ax2 = p.panel(545, 30, 325, 320, (0, 4.75), (0, 0.9), xlabel="VTUNE  [V]", ylabel="[V p-p]",
                  title="Amplitude at CDCM1804 IN", legend="br")
    for name, col, lab in (("vco_27_4.60", O, "VDD 4.60 V"), ("vco_27_4.82", B, "4.82 V"),
                           ("vco_27_5.00", P, "5.00 V")):
        r = res(name)
        if r:
            ax2.line([x["vt"] for x in r["rows"]], [x["vpp_in"] for x in r["rows"]], col, 1.8, label=lab)
    ax2.hline(0.5, R, "4,3", text="CDCM1804: 500 mV for AC specs")
    ax2.hline(0.15, K, "2,3", text="150 mV functional")
    p.save(os.path.join(FIG, "vco_tuning.svg"))


def fig_lock():
    p = Plot(900, 560)
    a1 = p.panel(70, 30, 800, 220, (0, 70), (370, 530), ylabel="f_VCO  [MHz]",
                 title="Lock from PLL_EN (t = 0), PLL_EN = 0 at 40 us, again 1 at 46 us", legend="br")
    a2 = p.panel(70, 300, 800, 200, (0, 70), (-0.2, 5.0), xlabel="time  [us]", ylabel="VTUNE  [V]",
                 legend="br")
    for name, col, lab in (("loop_24", B, "24 MHz"), ("loop_19", G, "19.2 MHz"),
                           ("loop_26", R, "26 MHz (no lock)")):
        w = wave(name)
        if w is None:
            continue
        a1.line(w[::10, 0] * 1e6, w[::10, 3] / 1e6, col, 1.4, label=lab)
        a2.line(w[::10, 0] * 1e6, w[::10, 1], col, 1.4, label=lab)
    a1.hline(480, K, "4,3")
    p.save(os.path.join(FIG, "lock.svg"))


def fig_bode():
    f = np.logspace(4, 7.5, 600)
    p = Plot(900, 400)
    a1 = p.panel(70, 30, 380, 300, (1e4, 3e7), (-40, 60), xlog=True, xlabel="f  [Hz]", ylabel="|G|  [dB]",
                 title="Open-loop gain (24 MHz setting)", legend="tr")
    a2 = p.panel(510, 30, 360, 300, (1e4, 3e7), (-200, -90), xlog=True, xlabel="f  [Hz]",
                 ylabel="phase  [deg]", title="Open-loop phase", legend="br")
    for kv, col in ((19.6e6, O), (20.5e6, B), (22.8e6, P)):
        g = tables.open_loop(f, tables.rs.ICP_24, kv, 20)
        fc, pm, _, _ = tables.margins(tables.rs.ICP_24, kv, 20)
        lab = "Kvco %.1f MHz/V: fc %.0f kHz, PM %.0f" % (kv / 1e6, fc / 1e3, pm)
        a1.line(f, 20 * np.log10(np.abs(g)), col, 1.6, label=lab)
        a2.line(f, np.degrees(np.unwrap(np.angle(g))), col, 1.6)
    a1.hline(0, K, "4,3")
    a2.hline(-180, K, "4,3")
    p.save(os.path.join(FIG, "bode.svg"))


def main():
    os.makedirs(FIG, exist_ok=True)
    fig_vco()
    fig_lock()
    fig_bode()
    if "--no-png" not in sys.argv:
        for f in sorted(os.listdir(FIG)):
            if f.endswith(".svg"):
                subprocess.run(["rsvg-convert", "-z", "2", "-o", os.path.join(FIG, f[:-4] + ".png"),
                                os.path.join(FIG, f)], check=True)
    print("\n".join(sorted(os.listdir(FIG))))


if __name__ == "__main__":
    main()
