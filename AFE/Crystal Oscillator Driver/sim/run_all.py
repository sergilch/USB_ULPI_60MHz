#!/usr/bin/env python3
"""run_all.py - full corner regression of afe_xosc_tr for the datasheet

Usage:
    python3 "AFE/Crystal Oscillator Driver/sim/run_all.py" [--quick]

Runs tb_xosc_tr.py over
  PVT corners  tm 27 C 1.8 V (all cases), ws 125 C 1.62 V and wp -40 C 1.98 V
               (op ac ss start byp), ws -40 C 1.62 V and wp 125 C 1.98 V (op ac
               ss), wo / wz 27 C 1.8 V (op ac); DRV 2, ESR 100 Ohm, C1 = C2 = 12 pF
  sweep (tm)   C1 = C2 = 10 / 14 pF                                  (ss, ac)
The transients are slow (about 15 s of CPU per simulated microsecond with the
xh018 BSIM3 cards), hence the reduced set; ss / start of one corner take 1-2 h.
and copies every results_*.json and the waveform windows (*.csv) to
AFE/Crystal Oscillator Driver/datasheet/data/<run>/ for gen_figures.py.
--quick runs only the tm corner, --skip-done skips runs already in data/.
Two runs in parallel (JOBS); the full set takes about 6 hours on 2 cores.
"""
import concurrent.futures as cf
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DATA = os.path.join(os.path.dirname(HERE), "datasheet", "data")
TB = os.path.join(HERE, "tb_xosc_tr.py")

ALL = ["op", "ac", "ss", "start", "byp", "en"]
CORNER = ["op", "ac", "ss", "start", "byp"]
RUNS = [
    # (corner, temp, vdd, cases, extra args, tag)
    # tm, ws 125 C and wp -40 C were run with ss --burst 0.5 --tss 240e-6
    ("tm", 27, 1.8, ALL, ["--burst", "0.5", "--tss", "240e-6"], ""),
    ("ws", 125, 1.62, CORNER, ["--burst", "0.5", "--tss", "240e-6"], ""),
    ("wp", -40, 1.98, CORNER, ["--burst", "0.5", "--tss", "240e-6"], ""),
    ("ws", -40, 1.62, ["op", "ac", "ss"], [], ""),
    ("wp", 125, 1.98, ["op", "ac", "ss"], [], ""),
    ("wo", 27, 1.8, ["op", "ac"], [], ""),
    ("wz", 27, 1.8, ["op", "ac"], [], ""),
    ("tm", 27, 1.8, ["ss", "ac"], ["--cext", "10e-12"], "_c10"),
    ("tm", 27, 1.8, ["ss", "ac"], ["--cext", "14e-12"], "_c14"),
]


def main():
    runs = RUNS[:1] if "--quick" in sys.argv else RUNS
    if "--skip-done" in sys.argv:       # runs whose results are already in data/
        runs = [r for r in runs if not os.path.exists(
            os.path.join(DATA, f"{r[0]}_{r[1]:g}_{r[2]:g}{r[5]}", "log.txt"))]
    fails = []

    def one(run):
        corner, temp, vdd, cases, extra, tag = run
        name = f"{corner}_{temp:g}_{vdd:g}{tag}"
        cmd = [sys.executable, TB, *cases, "--corner", corner, "--temp", str(temp), "--vdd", str(vdd),
               "--tag", tag, *extra]
        r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, JOBS="1"))
        print(f"=== {name}: {' '.join(cases)} {' '.join(extra)}", r.stdout,
              r.stderr[-2000:] if r.returncode else "", flush=True)
        last = [l for l in r.stdout.splitlines() if l.startswith("TEST ")]
        if not last or last[-1] != "TEST PASSED":
            fails.append(name)
        src = os.path.join(ROOT, "build", "xosc", name)
        dst = os.path.join(DATA, name)
        os.makedirs(dst, exist_ok=True)
        for f in glob.glob(f"{src}/results_*.json") + glob.glob(f"{src}/*.csv"):
            shutil.copy(f, dst)
        open(os.path.join(dst, "log.txt"), "w").write(r.stdout)

    # two runs in parallel, one ngspice job each (the long cases are single
    # transients, so this keeps both cores busy)
    with cf.ThreadPoolExecutor(max_workers=int(os.environ.get("JOBS", "2"))) as ex:
        list(ex.map(one, runs))
    print("ALL PASSED" if not fails else f"FAILED: {', '.join(fails)}")


if __name__ == "__main__":
    main()
