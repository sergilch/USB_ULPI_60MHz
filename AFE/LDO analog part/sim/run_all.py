#!/usr/bin/env python3
"""run_all.py - corner regression of afe_ldo_tr for the datasheet

Usage:
    python3 "AFE/LDO analog part/sim/run_all.py" [--quick] [--skip-done]

Runs tb_ldo_tr.py over
  tm 27 C 3.3 V        all cases + capsweep (COUT 0.47 .. 10 uF, ESR 5 mOhm .. 0.5 Ohm)
  ws / wp x -40 / 125 C at VIN 2.97 / 3.63 V (slow-low, fast-high, and the
                       crossed pairs)                 op temp line load ac psrr step start uvlo en enth
  wo / wz 27 C 3.3 V   op line load ac step
  tm 27 C, COUT 2.2 uF / ESR 0.5 Ohm and COUT 0.47 uF   ac step
and copies results_*.json, the waveform windows (*.csv) and log.txt to
AFE/LDO analog part/datasheet/data/<run>/ for gen_figures.py.
--quick runs only tm, --skip-done skips runs already in data/.
JOBS (default 3) runs in parallel; each run uses 2 ngspice processes.
About 30 min on 6 cores.
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
TB = os.path.join(HERE, "tb_ldo_tr.py")

ALL = ["op", "temp", "line", "load", "ac", "capsweep", "psrr", "zout", "noise", "start", "uvlo", "step",
       "line_step", "en", "enth", "short"]
CORNER = ["op", "temp", "line", "load", "ac", "psrr", "step", "start", "uvlo", "en", "enth"]
RUNS = [
    # (corner, temp, vin, cases, extra args, tag)
    ("tm", 27, 3.3, ALL, [], ""),
    ("ws", 125, 2.97, CORNER, [], ""),
    ("ws", -40, 2.97, CORNER, [], ""),
    ("wp", -40, 3.63, CORNER, [], ""),
    ("wp", 125, 3.63, CORNER, [], ""),
    ("wo", 27, 3.3, ["op", "line", "load", "ac", "step"], [], ""),
    ("wz", 27, 3.3, ["op", "line", "load", "ac", "step"], [], ""),
    ("tm", 27, 3.3, ["ac", "step"], ["--cout", "2.2e-6", "--esr", "0.5"], "_c2u2_esr0.5"),
    ("tm", 27, 3.3, ["ac", "step"], ["--cout", "0.47e-6", "--esr", "0.005"], "_c0u47"),
]


def main():
    runs = RUNS[:1] if "--quick" in sys.argv else RUNS
    if "--skip-done" in sys.argv:
        runs = [r for r in runs if not os.path.exists(
            os.path.join(DATA, f"{r[0]}_{r[1]:g}_{r[2]:g}{r[5]}", "log.txt"))]
    fails = []

    def one(run):
        corner, temp, vin, cases, extra, tag = run
        name = f"{corner}_{temp:g}_{vin:g}{tag}"
        cmd = [sys.executable, TB, *cases, "--corner", corner, "--temp", str(temp), "--vin", str(vin),
               "--tag", tag, *extra]
        r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, JOBS="2"))
        out = r.stdout + r.stderr
        src = os.path.join(ROOT, "build", "ldo", name)
        dst = os.path.join(DATA, name)
        os.makedirs(dst, exist_ok=True)
        for f in glob.glob(os.path.join(src, "results_*.json")) + glob.glob(os.path.join(src, "*.csv")):
            shutil.copy(f, dst)
        open(os.path.join(dst, "log.txt"), "w").write(out)
        last = [l for l in out.splitlines() if l.startswith("TEST ")]
        status = last[-1] if last else "TEST FAILED: no result line"
        return name, status, out

    with cf.ThreadPoolExecutor(max_workers=int(os.environ.get("JOBS", "3"))) as ex:
        for name, status, out in ex.map(one, runs):
            print(f"{name:28s} {status}", flush=True)
            if not status.startswith("TEST PASSED"):
                fails.append(name)
                for l in out.splitlines():
                    if "ERROR" in l or "Traceback" in l or "Error" in l:
                        print("    ", l)
    print("TEST PASSED" if not fails else f"TEST FAILED: {', '.join(fails)}")


if __name__ == "__main__":
    main()
