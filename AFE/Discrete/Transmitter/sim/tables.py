#!/usr/bin/env python3
"""tables.py - Markdown result tables from results/summary.json (for doc/tx_board.md)

    python3 tables.py > results/tables.md
"""
import json
import os

S = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "summary.json")))


def f(v, fmt="%.0f"):
    return "-" if v is None else fmt % v


def eye_rows(model):
    rows = []
    for name in ["eye_" + model] + sorted(k for k in S if k.startswith("corner_eye_" + model)):
        r = S.get(name)
        if not r or "near" not in r:
            continue
        ne, fa = r["near"], r["far"]
        rows.append("| %s V, %s C | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            f(r["vdd"], "%.3f"), f(r["temp"]), f(ne["vJ_mV"]), f(ne["eye_height_mV"]),
            f(ne["rise_ps"]), f(ne["fall_ps"]), f(ne["jitter_pp_ps"]),
            f(fa["eye_height_mV"]), f(fa["rise_ps"]), f(fa["delay_ns"], "%.2f")))
    return rows


def static_rows(model):
    rows = []
    for name in ["static_" + model] + sorted(k for k in S if k.startswith("corner_static_" + model)):
        r = S.get(name)
        if not r:
            continue
        if "error" in r:
            rows.append("| %s | not converged | | | | | | | |" % name)
            continue
        rows.append("| %s V, %s C | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            f(r["vdd"], "%.3f"), f(r["temp"]), f(r["vJ_mV"]), f(r["i_dump_mA"], "%.2f"),
            f(r["pn11_dp_mV"]), f(r.get("pn00_dp_mV"), "%.1f"),
            f(r.get("t_en_ns"), "%.1f"), f(r.get("t_dis_ns"), "%.1f"),
            f(r.get("tail_vec_V"), "%.2f"), f(r["idle_leak_uA"], "%.2f")))
    return rows


for m in ("BFT92", "MMBTH81"):
    print("\n#### %s - eye (Test_Packet)\n" % m)
    print("| Corner | J near [mV] | EH near [mV] | t_r [ps] | t_f [ps] | jitter p-p [ps] | EH far [mV] | t_r far [ps] | delay [ns] |")
    print("|---|---|---|---|---|---|---|---|---|")
    print("\n".join(eye_rows(m)))
    print("\n#### %s - static states\n" % m)
    print("| Corner | J [mV] | I dump [mA] | P=N=1 DP [mV] | P=N=0 DP [mV] | t_en [ns] | t_dis [ns] | tail V_EC [V] | idle leakage [uA] |")
    print("|---|---|---|---|---|---|---|---|---|")
    print("\n".join(static_rows(m)))
for m in ("BFT92", "MMBTH81"):
    r = S.get("chirp_" + m)
    if r:
        print("\nchirp %s: DM %.0f mV, DP %.0f mV, DM-DP %.0f mV" % (m, r["dm_mV"], r["dp_mV"], r["dm_minus_dp_mV"]))
r = S.get("skew_BFT92")
if r:
    print("skew_BFT92 (TX_IN_N 150 ps late): near EH %.0f mV, jitter %.0f ps, t_r %.0f / t_f %.0f ps" % (
        r["near"]["eye_height_mV"], r["near"]["jitter_pp_ps"], r["near"]["rise_ps"], r["near"]["fall_ps"]))
t = S.get("trim")
if t:
    print("trim: alpha %.4f .. %.4f, linearity %.2f %%" % (t["alpha_min"], t["alpha_max"], t["lin_err_pct"]))
