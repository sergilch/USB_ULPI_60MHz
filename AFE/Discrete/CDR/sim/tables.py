#!/usr/bin/env python3
"""tables.py - result tables of the CDR-board simulations (doc section 5)

    python3 tables.py        -> stdout and results/tables.md

Reads results/*/result.json (run run_sims.py first).  Besides the simulated
cases it gives the bang-bang loop figures derived from them: phase step per
decision (UI) = |df| x T_bit, the number of decisions to slew half a UI, and
the largest frequency offset a transition density D can track
(|offset| < D x df_min x T_bit / 1 bit, i.e. ppm_max = 1e6 x D x df_min / f).
"""
import json
import os

import run_sims as rs

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
T = rs.TBIT


def load(name):
    p = os.path.join(RES, name, "result.json")
    return json.load(open(p)) if os.path.exists(p) else None


def vco_table():
    L = ["| case | f0 at 3.18 V (MHz) | coarse for 480 MHz (V) | Kc (MHz/V) | UP step (MHz) | DN step (MHz) "
         "| step (UI / decision) | node F idle / UP / DN (V) | min. amplitude at NB6L14 (V p-p) |",
         "|---|---|---|---|---|---|---|---|---|"]
    for name, lab in (("vco_-40", "-40 C"), ("vco_27", "27 C"), ("vco_85", "85 C"),
                      ("vcotol_m", "L1 -0.2 nH, 27 C"), ("vcotol_p", "L1 +0.2 nH, 27 C")):
        r = load(name)
        if not r:
            continue
        L.append("| %s | %.1f | %s | %.1f | %+.1f | %+.1f | %.3f | %.2f / %.2f / %.2f | %.2f |" % (
            lab, r["f0"] / 1e6, "%.2f" % r["v480"] if r["v480"] else "-", r["kc"] / 1e6,
            r["df_up"] / 1e6, r["df_dn"] / 1e6, r["step_ui"], r["vf_idle"], r["vf_up"], r["vf_dn"],
            r["vpp_min"]))
    return L


def va_table():
    r = load("vafine")
    if not r:
        return []
    L = ["| V_A (V) | f (MHz), coarse 3.18 V | UP step (MHz) | DN step (MHz) | step (UI) |", "|---|---|---|---|---|"]
    for x in r["rows"]:
        L.append("| %.1f | %.1f | %+.1f | %+.1f | %.3f |" % (x["va"], x["f"] / 1e6, x["df_up"] / 1e6,
                                                            x["df_dn"] / 1e6, 0.5 * (x["df_up"] - x["df_dn"]) * T))
    return L


def loop_rows(names):
    L = ["| case | start phase (UI) | f VCO (MHz) | data offset (ppm) | bits to lock | sampling errors in SYNC "
         "| errors after SYNC | phase mean / p-p / rms (UI) | min. margin to an edge (ps) | UP / DN duty |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for name in names:
        r = load(name)
        if not r or "error" in r:
            L.append("| %s | (not run / failed: %s) |||||||||" % (name, (r or {}).get("error", "")))
            continue
        L.append("| %s | %.3f | %.1f | %+d | %d | %d | %d | %.2f / %.2f / %.3f | %.0f | %.2f / %.2f |" % (
            name, r["phase"], r["f0"] / 1e6, r["ppm"], r["lock_bits"], r["errors_sync"],
            r["errors_after_sync"], r.get("phase_mean_ui", 0), r.get("phase_pp_ui", 0),
            r.get("phase_rms_ui", 0), r.get("min_margin_ps", 0), r["up_frac"], r["dn_frac"]))
    return L


def derived():
    r = load("vco_27")
    if not r:
        return []
    dmin = min(r["df_up"], -r["df_dn"])
    step = r["step_ui"]
    L = ["Bang-bang figures (27 C): phase step %.3f UI per decision (afe_cdr.va: about 1/16 = 0.063 UI);"
         " slewing 0.5 UI takes %.0f decisions; the smaller step (%.1f MHz) tracks up to %.0f ppm at a"
         " transition density of 0.5 (%.0f ppm at 0.25).  USB 2.0 HS needs +-1000 ppm (2 x 500 ppm)." % (
             step, 0.5 / step, dmin / 1e6, 1e6 * 0.5 * dmin / 480e6, 1e6 * 0.25 * dmin / 480e6)]
    return L


def main():
    out = ["### VCO (transistor level, static)", ""] + vco_table() + ["", "### Fine bias V_A (27 C)", ""]
    out += va_table() + ["", "### Lock from SYNC (full loop: transistor VCO / driver, behavioural 100EP PD)", ""]
    out += loop_rows(["lock_%d" % k for k in range(8)] + ["lock_t-40", "lock_t85"])
    out += ["", "### Frequency offset (600-bit payload) and jitter", ""]
    out += loop_rows(["ppm_-10000", "ppm_-2000", "ppm_-500", "ppm_+500", "ppm_+2000", "ppm_+10000", "jit"])
    out += [""] + derived() + [""]
    txt = "\n".join(out)
    print(txt)
    with open(os.path.join(RES, "tables.md"), "w") as f:
        f.write(txt)


if __name__ == "__main__":
    main()
