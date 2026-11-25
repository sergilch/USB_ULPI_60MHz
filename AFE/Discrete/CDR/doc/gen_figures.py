#!/usr/bin/env python3
"""gen_figures.py - figures of the CDR-board documentation

    python3 AFE/Discrete/CDR/doc/gen_figures.py [--no-png]

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
from svgplot import Plot  # noqa: E402

B, R, G, O, P, K = "#1f4e9c", "#c0392b", "#2e8b57", "#d4860b", "#6c3483", "#555555"
RES = os.path.join(SIM, "results")


def res(name):
    p = os.path.join(RES, name, "result.json")
    return json.load(open(p)) if os.path.exists(p) else None


def phase(name):
    p = os.path.join(RES, name, "phase.txt")
    return np.loadtxt(p) if os.path.exists(p) else None


def fig_vco():
    p = Plot(900, 420)
    ax = p.panel(70, 30, 380, 320, (1.9, 4.6), (450, 515), xlabel="coarse input CDR_V_IN_2  [V]",
                 ylabel="f free-running  [MHz]", title="VCO: coarse tuning (UP = DN = 0)", legend="br")
    ax.hline(480, R, "4,3", text="480 MHz")
    for name, col, lab in (("vco_27", B, "27 C"), ("vco_-40", P, "-40 C"), ("vco_85", O, "85 C"),
                           ("vcotol_m", K, "L1 -0.2 nH"), ("vcotol_p", G, "L1 +0.2 nH")):
        r = res(name)
        if r:
            ax.line([x["vk"] for x in r["rows"]], [x["f"] / 1e6 for x in r["rows"]], col, 1.8, label=lab)
    r = res("vafine")
    ax2 = p.panel(545, 30, 325, 320, (1.7, 3.5), (430, 520), xlabel="V_A (fine bias trim)  [V]",
                  ylabel="f  [MHz]", title="Fine path: idle, UP, DN (27 C)", legend="tr")
    if r:
        va = [x["va"] for x in r["rows"]]
        ax2.line(va, [(x["f"] + x["df_up"]) / 1e6 for x in r["rows"]], R, 1.6, label="UP")
        ax2.line(va, [x["f"] / 1e6 for x in r["rows"]], B, 1.8, label="idle")
        ax2.line(va, [(x["f"] + x["df_dn"]) / 1e6 for x in r["rows"]], G, 1.6, label="DN")
    ax2.hline(480, K, "4,3")
    p.save(os.path.join(FIG, "vco_tuning.svg"))


def fig_lock():
    p = Plot(900, 420)
    ax = p.panel(70, 30, 800, 320, (0, 60), (0, 1), xlabel="bit after the start of SYNC",
                 ylabel="sampling phase in the bit  [UI]",
                 title="Lock from SYNC: 8 start phases (27 C), -40 / 85 C; eye centre 0.5, edges 0 / 1",
                 legend="br")
    ax.band(0.2, 0.8, G, 0.07)
    ax.vline(32, K, "4,3", text="end of SYNC")
    cols = [B, R, G, O, P, K, "#117a8b", "#8e44ad"]
    for k in range(8):
        d = phase("lock_%d" % k)
        if d is not None:
            ax.line(d[:, 0], d[:, 1], cols[k], 1.3, label="start %.3f UI" % (k / 8) if k % 2 == 0 else None)
    for name, col, lab in (("lock_t-40", P, "-40 C"), ("lock_t85", O, "85 C")):
        d = phase(name)
        if d is not None:
            ax.line(d[:, 0], d[:, 1], col, 1.3, dash="4,3", label=lab)
    p.save(os.path.join(FIG, "lock.svg"))


def fig_ppm():
    p = Plot(900, 420)
    ax = p.panel(70, 30, 800, 320, (0, 660), (0, 1), xlabel="bit", ylabel="sampling phase  [UI]",
                 title="Data-rate offset (no integral path): the UP / DN duty tracks it", legend="br")
    ax.band(0.2, 0.8, G, 0.07)
    for name, col in (("ppm_-10000", P), ("ppm_-2000", B), ("ppm_+2000", R), ("ppm_+10000", O),
                      ("jit", K)):
        d = phase(name)
        r = res(name)
        if d is not None and r and "error" not in r:
            lab = "%+d ppm" % r["ppm"] if name != "jit" else "25 ps rms + 40 ps p-p SJ"
            ax.line(d[:, 0], d[:, 1], col, 1.2, label=lab)
    p.save(os.path.join(FIG, "ppm.svg"))


def main():
    os.makedirs(FIG, exist_ok=True)
    fig_vco()
    fig_lock()
    fig_ppm()
    if "--no-png" not in sys.argv:
        for f in sorted(os.listdir(FIG)):
            if f.endswith(".svg"):
                subprocess.run(["rsvg-convert", "-z", "2", "-o", os.path.join(FIG, f[:-4] + ".png"),
                                os.path.join(FIG, f)], check=True)
    print("\n".join(sorted(os.listdir(FIG))))


if __name__ == "__main__":
    main()
