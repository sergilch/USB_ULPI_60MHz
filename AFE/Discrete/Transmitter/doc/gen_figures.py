#!/usr/bin/env python3
"""gen_figures.py - figures of the transmitter-board documentation

    python3 AFE/Discrete/Transmitter/doc/gen_figures.py [--no-png]

Reads sim/results (run sim/run_sims.py and sim/run_fsls.py first) and writes doc/fig/*.svg, plus
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
import run_fsls as rf     # noqa: E402

B, R, G, O, P, K = "#1f4e9c", "#c0392b", "#2e8b57", "#d4860b", "#6c3483", "#555555"
UI = rs.UI
SUM = json.load(open(os.path.join(SIM, "results", "summary.json")))


def wave(name, n=None):
    """waveform columns; with n, resampled onto n uniform time points (SVG size)"""
    f = os.path.join(SIM, "results", name, "wave.txt")
    if not os.path.exists(f):
        return None
    w = rs.load_wave(name)
    if n:
        tg = np.linspace(w["t"][0], w["t"][-1], n)
        w = {k: (tg if k == "t" else np.interp(tg, w["t"], v)) for k, v in w.items()}
    return w


# ---------------------------------------------------------------- eye diagrams
def fig_eye(model):
    w = wave("eye_" + model)
    if w is None:
        return
    c = rs.eye_case(rs.base_cfg(model))
    t = w["t"]
    p = Plot(900, 430)
    for k, (node, title) in enumerate(((("np", "nm"), "Near end (connector, TP2)"),
                                       (("fp", "fm"), "Far end (after 0.5 m cable, host 45 Ohm)"))):
        d = w[node[0]] - w[node[1]]
        t0 = 20e-9 + c["first_ui"] * UI
        z0 = rs.cross(t, d, 0.0, t0 - UI / 2, rising=False)[0]
        nb = len(c["line"]) - 8
        ax = p.panel(70 + k * 430, 40, 380, 330, (0, 2), (-600, 600), xlabel="time  [UI = 2.083 ns]",
                     ylabel="V(DP) - V(DM)  [mV]" if k == 0 else "", title=title, legend="tr")
        grid = np.linspace(0, 2 * UI, 101)
        for i in range(1, nb - 1):
            ts = z0 + (i - 0.5) * UI + grid
            ax.line(grid / UI, 1e3 * np.interp(ts, t, d), B, 0.5)
        if k == 0:                       # USB 2.0 transmit eye, Template 1 (TP2)
            x = [0.5 + f for f in (0.075, 0.375, 0.625, 0.925, 0.625, 0.375, 0.075)]
            y = [0, 300, 300, 0, -300, -300, 0]
            ax.line(x, y, R, 1.8, label="USB 2.0 Template 1 (TP2)")
            ax.hline(525, R, "5,4")
            ax.hline(-525, R, "5,4")
        e = SUM.get("eye_" + model, {}).get("near" if k == 0 else "far", {})
        if e:
            ax.text(0.04, -560, "EH %.0f mV  jitter %.0f ps p-p  t10-90 %.0f ps" % (
                e["eye_height_mV"], e["jitter_pp_ps"], e["rise_ps"] or 0), K, 10)
    p.save(os.path.join(FIG, "eye_%s.svg" % model))


# ---------------------------------------------------------------- static / enable
def fig_static(model):
    w = wave("static_" + model, 6000)
    if w is None:
        return
    t = (w["t"] - 20e-9) / UI
    p = Plot(900, 520)
    a1 = p.panel(80, 30, 780, 200, (0, 480), (-100, 500), ylabel="line  [mV]",
                 title="States: idle | J (TX_EN = 1) | K | P = N = 1 | P = N = 0 | J | TX_EN = 0", legend="tr")
    a1.line(t, 1e3 * w["np"], B, 1.4, label="DP (near end)")
    a1.line(t, 1e3 * w["nm"], R, 1.4, label="DM (near end)")
    a2 = p.panel(80, 280, 780, 190, (0, 480), (-1, 20), xlabel="time from t0 = 20 ns  [UI]",
                 ylabel="collector current  [mA]", legend="tr")
    a2.line(t, 1e3 * w["ip"], B, 1.4, label="Q_P")
    a2.line(t, 1e3 * w["in"], R, 1.4, label="Q_N")
    a2.line(t, 1e3 * w["id"], G, 1.4, label="Q_D (dump)")
    for x in (40, 140, 240, 300, 360, 420):
        a1.vline(x, K, "2,4")
        a2.vline(x, K, "2,4")
    p.save(os.path.join(FIG, "static_%s.svg" % model))


def fig_chirp(model):
    w = wave("chirp_" + model, 3000)
    if w is None:
        return
    t = (w["t"] - 20e-9) * 1e9
    p = Plot(900, 330)
    ax = p.panel(80, 30, 780, 250, (0, t[-1]), (-100, 900), xlabel="time  [ns]",
                 ylabel="[mV]", title="Chirp K: HS termination off, 1.5 kOhm pull-up on, host 45 Ohm",
                 legend="tr")
    ax.line(t, 1e3 * w["np"], B, 1.6, label="DP")
    ax.line(t, 1e3 * w["nm"], R, 1.6, label="DM")
    r = SUM.get("chirp_" + model, {})
    if r:
        ax.hline(r["dm_mV"], R, "5,4", text="DM %.0f mV" % r["dm_mV"])
    p.save(os.path.join(FIG, "chirp_%s.svg" % model))


# ---------------------------------------------------------------- trim + R_B sweep
def fig_trim():
    r = SUM.get("trim")
    if not r:
        return
    v = np.array(r["vctl"])
    p = Plot(900, 380)
    ax = p.panel(80, 30, 780, 300, (0.3, 0.9), (0, 30), xlabel="V_CTL  [V]",
                 ylabel="current  [mA]", title="Amplitude trim: Q_P collector current vs. V_CTL",
                 legend="tl")
    ax.line(v, np.array(r["tail_mA"]), K, 1.4, dash="5,4", label="I_tail = V_CTL Rr / (Rg Rs)")
    ax.line(v, np.array(r["i_mA"]), B, 2.4, label="Q_P collector (to the line)")
    ax.vline(0.6, G, "3,3", text="TX_AMP = 8: 0.600 V")
    ax.hline(17.78, G, "3,3", text="17.78 mA = 400 mV / 22.5 Ohm", anchor="start")
    p.save(os.path.join(FIG, "trim.svg"))


def fig_rb():
    p = Plot(900, 400)
    ax = p.panel(80, 30, 780, 320, (0, 105), (0, 1500), xlabel="base resistor R_B  [Ohm]",
                 ylabel="10-90 % rise time, near end  [ps]",
                 title="Edge rate vs. R_B and TX_CAP (3.3 V, 27 C)", legend="tl")
    series = {}
    for n, r in SUM.items():
        if n.startswith("rb_") and "near" in r:
            series.setdefault((r["model"], r["tx_cap_pF"]), []).append((r["rbase"], r["near"]["rise_ps"]))
    cols = [B, R, G, O, P, K, "#0b7a75", "#8e44ad"]
    for i, ((m, cap), pts) in enumerate(sorted(series.items())):
        pts.sort()
        x, y = [a for a, _ in pts], [b for _, b in pts]
        ax.line(x, y, cols[i % len(cols)], 1.6, label="%s, TX_CAP %.1f pF" % (m, cap))
        ax.points(x, y, cols[i % len(cols)])
    ax.band(500, 1500, G, 0.05)
    ax.hline(500, G, "5,4", text="USB 2.0 HS: t_r, t_f >= 500 ps", anchor="start")
    p.save(os.path.join(FIG, "rb_sweep.svg"))


# ---------------------------------------------------------------- FS/LS driver
def fwave(name, t_from=None, t_to=None, n=4000):
    f = os.path.join(SIM, "results", "fsls_" + name, "wave.txt")
    if not os.path.exists(f):
        return None
    a = np.loadtxt(f, skiprows=1)
    w = {k: a[:, i] for i, k in enumerate(rf.COLS)}
    t = w["t"]
    lo = t[0] if t_from is None else t_from
    hi = t[-1] if t_to is None else t_to
    tg = np.linspace(lo, hi, n)
    return {k: (tg if k == "t" else np.interp(tg, t, v)) for k, v in w.items()}


def first_edge(c, tb, k=1):
    """time of the k-th data transition after the SYNC start"""
    pins = c["pins"]
    first = next(i for i, p in enumerate(pins) if p[0])
    idx = [i for i in range(first + 3, len(pins)) if pins[i][1] != pins[i - 1][1] and not pins[i][2]]
    return 100e-9 + idx[k - 1] * tb


def fig_fsls_packet():
    c = rf.case()
    w = fwave("fs_nom", 0, 100e-9 + 24 * rf.TB_FS)
    if w is None:
        return
    t = w["t"] * 1e9
    p = Plot(900, 560)
    a1 = p.panel(80, 30, 780, 230, (300, t[-1]), (-0.5, 4.0), ylabel="line  [V]",
                 title="FS packet start (3.3 V, 27 C, CL 50 pF): idle (pull-up) | SYNC | PID", legend="tr")
    a1.line(t, w["lp"], B, 1.5, label="D+")
    a1.line(t, w["lm"], R, 1.5, label="D-")
    a1.band(1.3, 2.0, G, 0.08)
    a1.hline(1.65, G, "3,3", text="VCRS 1.3-2.0 V", anchor="start")
    a2 = p.panel(80, 310, 780, 200, (300, t[-1]), (-0.3, 3.6), xlabel="time  [ns]",
                 ylabel="gate  [V]", title="NX3008CBKS gates", legend="tr")
    a2.line(t, w["gpp"], B, 1.2, label="P gate D+")
    a2.line(t, w["gnp"], B, 1.2, dash="4,3", label="N gate D+")
    a2.line(t, w["gpm"], R, 1.2, label="P gate D-")
    a2.line(t, w["gnm"], R, 1.2, dash="4,3", label="N gate D-")
    x = 100 + 6 * rf.TB_FS * 1e9                  # FS_OE rises: first SYNC bit (K)
    a1.vline(x, K, "2,4")
    a2.vline(x, K, "2,4")
    p.save(os.path.join(FIG, "fsls_fs_packet.svg"))


def fig_fsls_edges():
    p = Plot(900, 470)
    for k, (name, ls, title, span, cl) in enumerate((
            ("fs_nom", False, "FS J -> K, CL 50 pF", 40e-9, None),
            ("ls_50p", True, "LS, CL 50 pF / 600 pF", 500e-9, None))):
        c = rf.case(ls)
        tb = rf.TB_LS if ls else rf.TB_FS
        tl = first_edge(c, tb, 2)                  # FS_DAT edge at the board pins
        w0 = fwave(name, tl, tl + tb, 4000)
        te = rs.cross(w0["t"], w0["lp"] - w0["lm"], 0.0, tl)[0]
        ax = p.panel(70 + k * 430, 40, 380, 360, (-0.5 * span * 1e9, 0.5 * span * 1e9), (-0.6, 4.2),
                     xlabel="time from the crossover  [ns]  (logic edge %.0f ns earlier)" % (1e9 * (te - tl)),
                     ylabel="line  [V]" if k == 0 else "", title=title, legend="tr")
        ax.band(1.3, 2.0, G, 0.08)
        names = (name,) if not ls else ("ls_50p", "ls_600p")
        for j, nm in enumerate(names):
            w = fwave(nm, te - 0.5 * span, te + 0.5 * span, 3000)
            if w is None:
                continue
            tt = (w["t"] - te) * 1e9
            d = "" if j == 0 else "5,3"
            lab = "" if not ls else (" 50 pF" if j == 0 else " 600 pF")
            ax.line(tt, w["lp"], B, 1.6, dash=d or None, label="D+" + lab)
            ax.line(tt, w["lm"], R, 1.6, dash=d or None, label="D-" + lab)
    p.save(os.path.join(FIG, "fsls_edges.svg"))


def main():
    os.makedirs(FIG, exist_ok=True)
    for m in ("BFT92", "MMBTH81"):
        fig_eye(m)
        fig_static(m)
        fig_chirp(m)
    fig_trim()
    fig_rb()
    fig_fsls_packet()
    fig_fsls_edges()
    if "--no-png" not in sys.argv:
        for f in sorted(os.listdir(FIG)):
            if f.endswith(".svg"):
                subprocess.run(["rsvg-convert", "-z", "2", "-o", os.path.join(FIG, f[:-4] + ".png"),
                                os.path.join(FIG, f)], check=True)
    print("\n".join(sorted(os.listdir(FIG))))


if __name__ == "__main__":
    main()
