#!/usr/bin/env python3
"""tables.py - result tables of the PLL-board simulations (doc section 5)

    python3 tables.py        -> stdout and results/tables.md

Reads results/*/result.json (run run_sims.py first).  Adds the small-signal
loop analysis (open-loop gain of the charge-pump PLL with the board's filter
C4 || (R2 + C3), node capacitance and the R_K / varactor-node pole) for the
Kvco spread of the VCO cases, the reference-spur periodic jitter and an
in-band phase-noise estimate from the ADF4002 figure of merit.
"""
import glob
import json
import math
import os

import numpy as np

import run_sims as rs

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
V = rs.VAL
PNSYNTH = -222.0          # ADF4002 normalized phase-noise floor (dBc/Hz), datasheet
F_OUT = 480e6


def load(name):
    p = os.path.join(RES, name, "result.json")
    return json.load(open(p)) if os.path.exists(p) else None


def open_loop(f, icp, kvco, neff):
    """G(j2pi f) of the CP-PLL: Icp / (2 pi) * Z(s) * Kvco_rad / s / N with the
    varactor feed R_K - C_K as a further pole (kvco in Hz / V)"""
    s = 2j * np.pi * f
    c1 = V["C4"] + V["C_node"]
    zk = V["Rk"] + 1 / (s * V["C_k"])                 # R_K + varactor node
    y = s * c1 + 1 / (V["R2"] + 1 / (s * V["C3"])) + 1 / zk
    z = 1 / y
    hk = (1 / (s * V["C_k"])) / zk                     # VTUNE -> varactor node
    return icp / (2 * np.pi) * z * hk * 2 * np.pi * kvco / s / neff


def margins(icp, kvco, neff):
    f = np.logspace(3, 8, 20001)
    g = open_loop(f, icp, kvco, neff)
    mag = np.abs(g)
    i = np.where(mag < 1)[0][0]
    fc = f[i]
    pm = 180 + np.degrees(np.angle(g[i]))
    # gain margin at -180 deg
    ph = np.unwrap(np.angle(g))
    j = np.where(ph < -np.pi)[0]
    gm = -20 * np.log10(mag[j[0]]) if len(j) else float("inf")
    # closed-loop peaking
    h = g / (1 + g)
    pk = 20 * np.log10(np.abs(h).max())
    return fc, pm, gm, pk


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


def main():
    md = []
    # ---- VCO ----
    rows = []
    for p in sorted(glob.glob(os.path.join(RES, "vco*_*", "result.json"))):
        r = json.load(open(p))
        if "rows" not in r:
            continue
        vs = [x["vt"] for x in r["rows"]]
        fs = [x["f"] for x in r["rows"]]
        v480 = float(np.interp(F_OUT, fs, vs)) if fs[0] < F_OUT < fs[-1] else float("nan")
        k = (np.interp(v480 + 0.25, vs, fs) - np.interp(v480 - 0.25, vs, fs)) / 0.5
        a = [x["vpp_in"] for x in r["rows"]]
        rows.append((r["case"], r["temp"], "%.2f" % r["vdd"], "%.1f" % (fs[0] / 1e6),
                     "%.1f" % (np.interp(4.5, vs, fs) / 1e6), "%.2f" % v480, "%.1f" % (k / 1e6),
                     "%.2f .. %.2f" % (min(a), max(a))))
    md += ["### VCO tuning (transistor level, BFR93A / 1SV305 / LQW18)", "",
           table(["case", "T (C)", "VDD (V)", "f(0 V) MHz", "f(4.5 V) MHz", "V @ 480 MHz",
                  "Kvco MHz/V", "Vpp at CDCM IN"], rows), ""]
    st = load("vcostart")
    if st:
        md += ["Start-up (VCO_OFF 1 -> 0, VTUNE 3.2 V): oscillation at %.1f MHz, %.2f Vpp, after %.0f ns; "
               "stop (VCO_OFF 0 -> 1) within %.0f ns." % (st["f"] / 1e6, st["vpp_in"], st["t_start"] * 1e9,
                                                         st["t_stop"] * 1e9), ""]
    # ---- loop, small signal ----
    rows = []
    for name, icp, neff in (("24 MHz: R 1, N 10, 1.25 mA", rs.ICP_24, 20),
                            ("19.2 MHz: R 2, N 25, 3.125 mA", rs.ICP_19, 50)):
        for kv in (19.6e6, 20.5e6, 22.8e6):
            fc, pm, gm, pk = margins(icp, kv, neff)
            rows.append((name, "%.1f" % (kv / 1e6), "%.0f" % (fc / 1e3), "%.1f" % pm,
                         "%.1f" % gm, "%.2f" % pk))
    md += ["### Loop, small signal (Kvco spread of the VCO cases)", "",
           table(["setting", "Kvco MHz/V", "fc kHz", "PM deg", "GM dB", "peaking dB"], rows), ""]
    # ---- loop transients ----
    rows = []
    for c in ("loop_24", "loop_24_cold", "loop_24_hot", "loop_24_slow", "loop_19"):
        r = load(c)
        if not r or r.get("t_lock1") is None:
            continue
        beta = 2 * 10 ** (r["spur_dbc"] / 20)                  # rad, narrow-band FM
        pj = beta / (2 * math.pi * F_OUT) * 1e12
        rows.append((c, "%.1f" % (r["fref"] / 1e6), r["curve"], "%.1f" % (r["t_lock1"] * 1e6),
                     "%.1f" % (r["t_lock2"] * 1e6), "%.3f" % r["vt_lock"], "%.1f" % r["f_lock_ppm"],
                     "%.1f" % (r["f_peak"] / 1e6), "%.1f" % r["spur_dbc"], "%.3f" % pj,
                     "%.1f" % (r["t_dis_50mv"] * 1e6)))
    md += ["### Loop transients (ngspice: XSPICE PFD, CP with compliance and 2 % mismatch, filter, VCO curve)",
           "",
           table(["case", "f_ref MHz", "VCO curve", "t_lock (us)", "t_relock (us)", "VTUNE (V)",
                  "f error ppm", "f peak MHz", "ref spur dBc", "PJ ps", "discharge to 50 mV (us)"], rows),
           ""]
    for c, lab in (("loop_26", "-40 C"), ("loop_26_fast", "fastest case: L -2 %, -40 C")):
        r = load(c)
        if r:
            md += ["REFSEL 10 at 26 MHz, model division /20 (target %.0f MHz), VCO %s: %s, VCO at %.1f MHz "
                   "(VTUNE %.2f V at the charge-pump limit; afe_pll.va: f_max 500 MHz)." %
                   (r["target"] / 1e6, lab, "LOCKED (fails)" if r["locked"] else "no lock",
                    r["f_end"] / 1e6, r["vt_end"]), ""]
    # ---- phase noise estimate ----
    rows = []
    for name, fpfd in (("24 MHz (PFD 24 MHz)", 24e6), ("19.2 MHz (PFD 9.6 MHz)", 9.6e6)):
        pn = PNSYNTH + 10 * math.log10(fpfd) + 20 * math.log10(F_OUT / fpfd)
        rows.append((name, "%.0f" % pn))
    md += ["### In-band phase noise (ADF4002 PNSYNTH %.0f dBc/Hz; reference and VCO not included)" % PNSYNTH, "",
           table(["reference", "L(f) at 480 MHz, dBc/Hz"], rows), ""]
    text = "\n".join(md)
    print(text)
    open(os.path.join(RES, "tables.md"), "w").write(text + "\n")


if __name__ == "__main__":
    main()
