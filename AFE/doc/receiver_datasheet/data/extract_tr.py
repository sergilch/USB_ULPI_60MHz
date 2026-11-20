#!/usr/bin/env python3
"""extract_tr.py - cut the ngspice waveforms of AFE/spice/tb/tb_receiver_tr.py
into small CSV windows for the receiver datasheet figures.

Usage:
    python3 AFE/doc/receiver_datasheet/data/extract_tr.py [dir_tt dir_ss dir_ff]

Each directory holds the tb_receiver_tr_{seq,sqamp,dc0,dc2,dc5}.dat of one
corner (default build/spice/rx_{tt,ss,ff}, made by running tb_receiver_tr.py
with OUT pointing there; the corners are tt 27 C 3.3 / 1.8 V, ss 125 C
3.0 / 1.62 V, ff -40 C 3.6 / 1.98 V).  The window times are those of
tb_receiver_tr.py (run_seq: line active at 300 ns, idle at 400 ns, 160 mV at
580 ns, 650 mV static at 770 ns, PRBS7 150 mV at 1520 ns; run_dc: HS ramps
100 .. 1100 ns, UVLO ramp 2050 .. 2650 ns in dc2).  Output: rx_<corner>_<win>.csv,
resampled on a uniform grid; times in ns, voltages in V, vd = V(p) - V(n).
"""
import os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
UI = 1 / 480e6


def load(path):
    """ngspice wrdata: t v1 t v2 ... -> t, [v1, v2, ...]"""
    a = np.loadtxt(path)
    return a[:, 0], [a[:, k] for k in range(1, a.shape[1], 2)]


def window(name, t, cols, names, a, b, dt, fmt="%.4f"):
    g = np.arange(a, b, dt)
    out = [g * 1e9] + [np.interp(g, t, c) for c in cols]
    np.savetxt(os.path.join(HERE, name + ".csv"), np.column_stack(out), delimiter=",",
               header="t_ns," + ",".join(names), comments="", fmt=["%.3f"] + [fmt] * len(cols))


def main():
    dirs = sys.argv[1:] or [os.path.join(ROOT, "build", "spice", "rx_" + c) for c in ("tt", "ss", "ff")]
    for corner, d in zip(("tt", "ss", "ff"), dirs):
        f = lambda c: os.path.join(d, f"tb_receiver_tr_{c}.dat")
        if not os.path.exists(f("seq")):
            print("missing", f("seq")); continue
        t, (p, n, op, on, sq, dc, ivdd, ivddo, act, vbp, ion) = load(f("seq"))
        vd = p - n
        S = dict(vd=vd, rx_out_p=op, squelch_a=sq, disc_a=dc, act=act, on=ion)
        def w(name, a, b, dt, cols):
            window(f"rx_{corner}_{name}", t, [S[c] for c in cols], cols, a, b, dt, "%.3f")
        window(f"rx_{corner}_bias", t, [vbp, ion, sq, -ivdd * 1e6, -ivddo * 1e6],
               ["vbp18", "on", "squelch_a", "i_vdd_ua", "i_vddo_ua"], 0, 300e-9, 0.25e-9, "%.3f")   # RX_EN at 20 ns
        w("a400", 296e-9, 316e-9, 5e-12, ["vd", "rx_out_p", "squelch_a", "act"])     # 400 mV alternating from 300 ns
        w("idle", 392e-9, 420e-9, 10e-12, ["vd", "squelch_a", "act"])                # line idle at 300 ns + 48 UI
        w("a160", 578e-9, 594e-9, 5e-12, ["vd", "squelch_a", "act"])                 # 160 mV alternating, 24 bits
        w("burst", 657e-9, 675e-9, 10e-12, ["vd", "squelch_a", "act"])               # 2 ns at 400 mV
        w("disc", 765e-9, 782e-9, 10e-12, ["vd", "disc_a"])                          # static 650 mV at 770 ns
        for amp, t0 in ((150, 1520e-9), (400, 1200e-9)):                              # PRBS7, 127 bits
            w(f"prbs{amp}", t0 - 2e-9, t0 + 127 * UI + 3e-9, 20e-12, ["vd", "rx_out_p"])
        if os.path.exists(f("sqamp")):
            ts, (sqa,) = load(f("sqamp"))
            window(f"rx_{corner}_sqamp", ts, [sqa], ["squelch_a"], 150e-9, ts[-1], 0.2e-9, "%.3f")
        if os.path.exists(f("dc2")):
            t2, (p2, n2, op2, act2, dsc2, sqp2, sqn2, dsp2, dsn2, on2, vdd2) = load(f("dc2"))
            window(f"rx_{corner}_dc2_hs", t2, [p2 - n2, op2], ["vd", "rx_out_p"], 100e-9, 1100e-9, 1e-9, "%.5f")
            window(f"rx_{corner}_dc2_sq", t2, [p2 - n2, sqp2, sqn2], ["vd", "sqp", "sqn"], 1150e-9, 2000e-9, 1e-9, "%.4f")
            window(f"rx_{corner}_dc2_uvlo", t2, [vdd2, on2], ["rx_vdd", "on"], 2050e-9, 2650e-9, 1e-9, "%.4f")
        if os.path.exists(f("dc5")):
            t5, cols5 = load(f("dc5"))
            p5, n5, dsp5, dsn5 = cols5[0], cols5[1], cols5[7], cols5[8]
            window(f"rx_{corner}_dc5_disc", t5, [p5 - n5, dsp5, dsn5], ["vd", "dsp", "dsn"], 2050e-9, t5[-1], 1e-9, "%.4f")
        print(corner, "done from", d)


if __name__ == "__main__":
    main()
