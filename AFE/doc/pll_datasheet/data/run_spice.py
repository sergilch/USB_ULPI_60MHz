#!/usr/bin/env python3
"""run_spice.py - transistor-level data for the PLL datasheet figures

Usage (from anywhere; needs ngspice):
    python3 AFE/doc/pll_datasheet/data/run_spice.py [--extract-only]

Runs afe_pll_tr.sp (AFE/spice, placeholder generic180.lib models) with the
netlists of AFE/spice/tb/tb_pll_tr.py:
  - lock24 / lock19 / ref26 at tt, 27 C, 1.8 V (tb_pll_tr.run_lock, results printed)
  - a VCO sweep, CDR_CH_OUT_PLL forced to 0 .. 1.4 V in 0.1 V steps, at
    tt / 27 C / 1.8 V, ss / 125 C / 1.62 V and ff / -40 C / 1.98 V
Simulation output goes to build/spice/pll_datasheet/.  Written here:
  vco_sweep.txt   corner  V_C [V]  f [Hz]  I(VDD) [A]
  lock24_tt.csv   t [s], V(CDR_CH_OUT_PLL) [V], CLK_BIT_A mean frequency over 50 ns [Hz]
Takes about an hour on two cores (the lock transients use 20 ps steps).
"""
import os, re, sys, subprocess, concurrent.futures as cf
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "AFE", "spice", "tb"))
import tb_pll_tr as tb                                      # noqa: E402

OUT = os.path.join(ROOT, "build", "spice", "pll_datasheet")
CORNERS = [("tt", 27, 1.8), ("ss", 125, 1.62), ("ff", -40, 1.98)]


def vco_pt(corner, temp, vdd, v):
    sp = f"{OUT}/vco_{corner}_{v:.2f}.sp"
    open(sp, "w").write(f"""* vco point
.lib "{tb.SP}/models/generic180.lib" {corner}
.inc "{tb.SP}/afe_pll_tr.sp"
.temp {temp}
vdd vdd 0 {vdd}
ven en 0 {vdd}
vr fref 0 0
vs1 rs1 0 0
vs0 rs0 0 {vdd}
vc vc 0 {v}
x0 fref en rs1 rs0 clk refd vc vdd 0 afe_pll_tr
cl clk 0 200f
{tb.OPTS}
.control
tran 5p 120n
meas tran t1 when v(clk)={vdd / 2} rise=10
meas tran t2 when v(clk)={vdd / 2} rise=30
meas tran ivdd avg i(vdd) from=30n to=80n
.endc
.end
""")
    o = subprocess.run(["ngspice", "-b", sp], capture_output=True, text=True).stdout
    g = {k: float(x) for k, x in re.findall(r"^(t1|t2|ivdd)\s*=\s*(\S+)", o, re.M)}
    f = 20 / (g["t2"] - g["t1"]) if "t2" in g else float("nan")
    return corner, v, f, -g.get("ivdd", float("nan"))


def extract_lock24():
    t, clk, vc = tb.load(f"{OUT}/tb_pll_tr_lock24.dat")[:3]
    t, clk, vc = map(np.asarray, (t, clk, vc))
    ck = np.asarray(tb.crossings(list(t), list(clk), 0.9, True))
    grid = np.arange(tb.T_EN, tb.T_EN + 8e-6, 10e-9)
    fm = [np.nan if (n := np.sum((ck >= g - 25e-9) & (ck < g + 25e-9))) < 3 else
          (n - 1) / (ck[(ck >= g - 25e-9) & (ck < g + 25e-9)][-1] - ck[(ck >= g - 25e-9) & (ck < g + 25e-9)][0])
          for g in grid]
    v = np.interp(grid, t, vc)
    with open(os.path.join(HERE, "lock24_tt.csv"), "w") as fo:
        fo.write("t_after_pll_en,v_ctrl,f_mean_50ns\n")
        for a, b, c in zip(grid - tb.T_EN, v, fm):
            fo.write(f"{a:.4e},{b:.5f},{c:.6e}\n")


def main():
    os.makedirs(OUT, exist_ok=True)
    tb.OUT = OUT
    if "--extract-only" not in sys.argv:
        with cf.ThreadPoolExecutor(2) as ex:
            locks = [ex.submit(tb.run_lock, c, "tt", 27, 1.8) for c in ("lock24", "lock19", "ref26")]
            pts = [ex.submit(vco_pt, c, t, vd, v / 10) for c, t, vd in CORNERS for v in range(15)]
            with open(os.path.join(HERE, "vco_sweep.txt"), "w") as fo:
                for p in pts:
                    c, v, f, i = p.result()
                    fo.write(f"{c} {v:.2f} {f:.6e} {i:.6e}\n")
            for fu in locks:
                print("\n".join(fu.result()[1]), flush=True)
    extract_lock24()
    print("data written to", HERE)


if __name__ == "__main__":
    main()
