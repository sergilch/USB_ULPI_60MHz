#!/usr/bin/env python3
"""run_all.py - corner regression of afe_ref_tr for the datasheet

Usage:
    python3 AFE/REF/sim/run_all.py [--skip-done]

Stage 1 (27 C, VDD33 3.3 V, trim code found automatically, as in production
test): tm with all cases, ws / wp / wo / wz with op trim temp line psrr stab
start comply rbias.  Stage 2 (-40 / 125 C at 2.97 / 3.63 V) with the trim
code of the same corner from stage 1: op line psrr stab start comply tran.
Copies results_*.json, code.json and log.txt to AFE/REF/datasheet/data/<run>/
for gen_figures.py.  JOBS (default 2) runs in parallel.
"""
import concurrent.futures as cf
import glob
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DATA = os.path.join(os.path.dirname(HERE), "datasheet", "data")
TB = os.path.join(HERE, "tb_ref_tr.py")

ALL = ["op", "trim", "temp", "line", "psrr", "noise", "stab", "zout", "comply", "rbias", "start", "tran", "offset"]
C27 = ["op", "trim", "temp", "line", "psrr", "stab", "start", "comply", "rbias"]
CX = ["op", "line", "psrr", "stab", "start", "comply", "tran"]
STAGE1 = [("tm", 27, 3.3, ALL), ("ws", 27, 3.3, C27), ("wp", 27, 3.3, C27), ("wo", 27, 3.3, C27),
          ("wz", 27, 3.3, C27)]
STAGE2 = [("ws", -40, 2.97), ("ws", 125, 2.97), ("wp", -40, 3.63), ("wp", 125, 3.63), ("tm", -40, 2.97),
          ("tm", 125, 3.63)]


def one(corner, temp, vdd, cases, code="auto"):
    name = f"{corner}_{temp:g}_{vdd:g}"
    cmd = [sys.executable, TB, *cases, "--corner", corner, "--temp", str(temp), "--vdd", str(vdd), "--code", str(code)]
    r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, JOBS="1"), cwd=ROOT)
    out = r.stdout + r.stderr
    src, dst = os.path.join(ROOT, "build", "ref", name), os.path.join(DATA, name)
    os.makedirs(dst, exist_ok=True)
    for f in glob.glob(os.path.join(src, "results_*.json")) + glob.glob(os.path.join(src, "code.json")):
        shutil.copy(f, dst)
    open(os.path.join(dst, "log.txt"), "w").write(out)
    last = [l for l in out.splitlines() if l.startswith("TEST ")]
    return name, (last[-1] if last else "TEST FAILED: no result line"), out


def main():
    jobs = int(os.environ.get("JOBS", "2"))
    fails = []

    def report(res):
        for name, status, out in res:
            print(f"{name:16s} {status}", flush=True)
            if not status.startswith("TEST PASSED"):
                fails.append(name)
                for l in out.splitlines():
                    if "ERROR" in l or "Traceback" in l or "Error" in l:
                        print("    ", l, flush=True)

    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        report(list(ex.map(lambda r: one(*r), STAGE1)))
        codes = {}
        for c in {r[0] for r in STAGE2}:
            p = os.path.join(DATA, f"{c}_27_3.3", "code.json")
            codes[c] = json.load(open(p))["code"] if os.path.exists(p) else 8
        report(list(ex.map(lambda r: one(*r, CX, codes[r[0]]), STAGE2)))
    print("TEST PASSED" if not fails else f"TEST FAILED: {', '.join(fails)}")


if __name__ == "__main__":
    main()
