#!/usr/bin/env python3
"""tables.py - prints the Markdown tables of doc/rx_board.md section 5 from
sim/results/summary.json (run run_sims.py first)"""
import json
import os

S = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "summary.json")))


def f(v, fmt="%.1f"):
    return "–" if v is None else fmt % v


def eyes():
    print("| Case | Device EH [mV] | Tap EH [mV] | RX_OUT delay [ns] | RX_OUT jitter [ps p-p] |"
          " Squelch t_on / t_off [ns] | Glitches | Disc. events |")
    print("|---|---|---|---|---|---|---|---|")
    names = ["ref_tap", "eye_tap", "eye_term"] + sorted(n for n in S if n.startswith("corner_eye_"))
    for n in names:
        if n not in S:
            continue
        r = S[n]
        rx, sq = r.get("rx_out"), r.get("squelch")
        lab = n.replace("corner_eye_", "tap %s V / " % "").replace("_", " ") if n.startswith("corner") else n
        if n.startswith("corner_eye_"):
            v, t = n[len("corner_eye_"):].split("_")
            lab = "tap, %s V, %s °C" % (v, t)
        print("| %s | %.0f | %.0f | %s | %s | %s | %s | %s |" % (
            lab, r["device"]["eye_height_mV"], r["tap"]["eye_height_mV"],
            f(rx and rx["delay_ns"], "%.2f"), f(rx and rx["jitter_pp_ps"], "%.0f"),
            "%s / %s" % (f(sq["t_on_ns"]), f(sq["t_off_ns"])) if sq else "–",
            sq["glitches"] if sq else "–", r["disc"]["events"] if "disc" in r else "–"))


def trips(pre, title):
    print("\n| %s | Highest no-trip [mV] | Lowest trip [mV] | Trip [mV] | Monotonic |" % title)
    print("|---|---|---|---|---|")
    keys = [pre + "nom"] + sorted(k for k in S if k.startswith(pre) and k != pre + "nom")
    vals = []
    for k in keys:
        if k not in S:
            continue
        r = S[k]
        tag = k[len(pre):]
        if tag == "nom":
            lab = "3.3 V, 27 °C"
        elif tag.startswith("vos"):
            lab = "comparator offset %s mV" % tag[3:]
        else:
            v, t = tag.split("_")
            lab = "%s V, %s °C" % (v, t)
        if r.get("trip_mV") is not None:
            vals.append(r["trip_mV"])
        print("| %s | %s | %s | %s | %s |" % (lab, f(r.get("max_off_mV")), f(r.get("min_on_mV")),
                                              f(r.get("trip_mV")), "yes" if r.get("monotonic") else "no"))
    if vals:
        print("\nRange of the trip: %.1f .. %.1f mV (%d cases)" % (min(vals), max(vals), len(vals)))


def fs():
    r = S.get("fs")
    if not r:
        return
    print("\n| D+ | D− | RX_OUT VOD [V] | Tap D+ [V] | Tap D− [V] |")
    print("|---|---|---|---|---|")
    seen = set()
    for s in r["states"]:
        k = (s["dp"], s["dm"])
        if k in seen:
            continue
        seen.add(k)
        print("| %s | %s | %+.2f | %.2f | %.2f |" % ("3.3 V" if s["dp"] else "0", "3.3 V" if s["dm"] else "0",
                                                  s["rx"], s["ep"], s["em"]))
    print("\nFS polarity ok: %s" % r["polarity_ok"])


if __name__ == "__main__":
    eyes()
    trips("sq_", "Squelch case")
    trips("dc_", "Disconnect case")
    fs()
