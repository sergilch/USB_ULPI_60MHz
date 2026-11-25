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

# ---------------------------------------------------------------- FS/LS driver (run_fsls.py)
FP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "fsls_summary.json")
F = json.load(open(FP)) if os.path.exists(FP) else {}


def fsls_row(name, label):
    r = F.get(name)
    if not r or "error" in r:
        return "| %s | not converged | | | | | | | |" % label
    return "| %s | %.2f / %.3f | %.1f | %.1f | %.0f | %.2f-%.2f | %.1f | %.2f / %.2f | %.0f |" % (
        label, r["voh_min_V"], r["vol_max_V"], r["tr_ns"][1], r["tf_ns"][1], r["match_pct"][1],
        r["vcrs_V"][0], r["vcrs_V"][2], r["jitter_pp_ns"], r["line_max_V"], r["line_min_V"],
        r["crowbar_peak_mA"])


def fsls_label(k):
    m = {"nom": "3.300 V, 27 C", "50p": "3.300 V, 27 C", "600p": "3.300 V, 27 C"}
    tail = k.split("_", 1)[1]
    if tail in m:
        return m[tail]
    if tail.startswith("vt_"):
        n = tail[3:]
        return "V_th N %s / P %s" % ("-0.25" if n[1:3] == "lo" else "+0.20", "-0.25" if n[-2:] == "lo" else "+0.20")
    if tail.startswith("cap"):
        return "C_gs / C_gd x %s" % tail[3:]
    if tail == "nodiode":
        return "no RB751 collector diodes"
    v, tt = tail.split("_")
    return "%s V, %s C" % (v, tt)


if F:
    hdr = ("| Corner | VOH / VOL [V] | t_r [ns] | t_f [ns] | t_r/t_f [%] | VCRS [V] | jitter p-p [ns] "
           "| line max / min [V] | crowbar peak [mA] |\n|---|---|---|---|---|---|---|---|---|")
    for title, pre, first in (("FS (CL 50 pF)", "fs_", "fs_nom"), ("LS, CL 50 pF", "ls50_", "ls_50p"),
                              ("LS, CL 600 pF", "ls600_", "ls_600p")):
        print("\n#### %s\n" % title)
        print(hdr)
        names = [first] + sorted(k for k in F if k.startswith(pre) and k != first and "host" not in k)
        for n in names:
            print(fsls_row(n, fsls_label(n)))
    z = {k: v["z_ohm"] for k, v in F.items() if k.startswith("zout")}
    if z:
        print("\noutput impedance (R_S + R_on + driver): " + ", ".join("%s %.1f" % (k, v) for k, v in sorted(z.items())))
    for k in ("fs_host", "ls_host"):
        r = F.get(k)
        if r and "error" not in r:
            print("%s (host drives, board driver off and isolated): t_r %.1f / t_f %.1f ns, VCRS %.2f-%.2f V, "
                  "rx errors %d" % (k, r["tr_ns"][1], r["tf_ns"][1], r["vcrs_V"][0], r["vcrs_V"][2], r["rx_errors"]))
    r = F.get("fs_nom")
    if r:
        print("fs_nom: idle D+ %.2f V, EOP SE0 %.0f ns, rx errors %d; fs_nodiode: idle D+ %.2f V" % (
            r["idle_pu_V"], r["eop_se0_ns"], r["rx_errors"], F.get("fs_nodiode", {}).get("idle_pu_V", 0)))
