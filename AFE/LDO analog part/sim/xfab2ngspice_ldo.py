#!/usr/bin/env python3
"""xfab2ngspice_ldo.py - ngspice model libraries for the LDO (xh018, 3.3 V)

Usage:
    python3 "AFE/LDO analog part/sim/xfab2ngspice_ldo.py" [--sigma=3]

Writes build/ldo/models/xh018_<corner>.lib (git-ignored: confidential PDK
data, never commit) for corner in tm ws wp wo wz.  Each file

  * includes the MOS library of the crystal-oscillator converter
    (build/xosc/models/xh018_<corner>.lib: ne3i / pe3i BSIM3v3 cards and the
    corner parameters of mos/ and dio/, among them dp3_is_mul_exp and
    dp3_rs_res_mul); it runs that converter first when the file is missing;
  * adds the subckt  dp3 (a c) area= perimeter=  (diode PDIFF / NWELL2,
    3.3 V; dio/dp3.scs).

dp3 is a JUNCAP2 (level 200) model in the PDK, which ngspice does not have.
The bandgap needs only its forward ideal current, so the subckt is a
B-source with the JUNCAP2 equations of the bottom and STI-sidewall
components (the gate-edge component is 0 for pgate = 0):

    I = sum_k idsatr_k * size_k * ftd_k^2 * (exp(V / Vt) - 1)
    ftd_k = (T / Trj)^1.5 * exp(phig_k(Trj) / (2 Vt(Trj)) - phig_k(T) / (2 Vt))
    phig_k(T) = phig_k - 4.73e-4 T^2 / (T + 636)       (PHIG* is at 0 K)

with idsatr_k = exp(dp3_is_mul_exp) * value from dp3.scs, the series
resistance dp3_rs_res_mul * 6.33e-10 / area and the zero-bias junction
capacitance cjorbot * area + cjorsti * perimeter.  Left out: SRH, trap-
assisted and band-to-band currents (< 1e-4 of the ideal current at the
forward bias of a bandgap, and only reverse leakage otherwise), the voltage
dependence of the capacitance, breakdown.  Temperature: ngspice's `temper`
(circuit temperature, .temp).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
XF = os.path.join(ROOT, "X-FAB", "spice")
OUT = os.path.join(ROOT, "build", "ldo", "models")
MOS = os.path.join(ROOT, "build", "xosc", "models")
CONV = os.path.join(ROOT, "AFE", "Crystal Oscillator Driver", "sim", "xfab2ngspice.py")
CORNERS = ["tm", "ws", "wp", "wo", "wz"]


def num(src, name):
    m = re.search(r"\b" + name + r"\s*=\s*\(?\s*(?:exp\(dp3_is_mul_exp\)\*|dp3_\w+_mul\*)?([-+0-9.eE]+)", src)
    if not m:
        sys.exit(f"dp3.scs: {name} not found")
    return float(m.group(1))


def dp3_subckt():
    src = open(os.path.join(XF, "dio", "dp3.scs")).read()
    rs = float(re.search(r"dp3_rs_res_mul\*\(([-+0-9.eE]+)/area\)", src).group(1))
    p = {k: num(src, k) for k in ("trj", "idsatrbot", "idsatrsti", "phigbot", "phigsti",
                                  "cjorbot", "cjorsti")}
    tr = p["trj"] + 273.15
    k_q = 8.617333262e-5
    vtr = k_q * tr

    def ftd2(phig):
        pr = f"({phig} - 4.73e-4 * {tr} * {tr} / ({tr} + 636))"
        pt = f"({phig} - 4.73e-4 * tk * tk / (tk + 636))"
        return f"(tk / {tr}) ^ 3 * exp({pr} / {vtr} - {pt} / ({k_q} * tk))"

    isat = (f"exp(dp3_is_mul_exp) * ({p['idsatrbot']} * area * {ftd2(p['phigbot'])}"
            f" + {p['idsatrsti']} * perimeter * {ftd2(p['phigsti'])})")
    isat = isat.replace("tk", "(temper + 273.15)")
    vt = f"({k_q} * (temper + 273.15))"
    return f"""* dp3: diode PDIFF / NWELL2 (3.3 V), JUNCAP2 ideal current (see xfab2ngspice_ldo.py)
.subckt dp3 a c area=1e-12 perimeter=4e-6
rs a b {{dp3_rs_res_mul * {rs} / area}}
bd b c i = {isat}
+   * (exp(min(v(b,c) / {vt}, 60)) - 1)
cj b c {{dp3_cjorbot * area + dp3_cjorsti * perimeter}}
.ends dp3
"""


def main():
    sig = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--sigma=")]
    os.makedirs(OUT, exist_ok=True)
    sub = dp3_subckt()
    for c in CORNERS:
        mos = os.path.join(MOS, f"xh018_{c}.lib")
        if not os.path.exists(mos) or sig:
            subprocess.run([sys.executable, CONV] + [f"--sigma={s}" for s in sig], check=True)
        path = os.path.join(OUT, f"xh018_{c}.lib")
        open(path, "w").write(f"* xh018 {c}: MOS ({mos}) + dp3\n.include \"{mos}\"\n{sub}")
        print("wrote", path)


if __name__ == "__main__":
    main()
