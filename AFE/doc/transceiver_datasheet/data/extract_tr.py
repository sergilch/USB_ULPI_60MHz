#!/usr/bin/env python3
"""extract_tr.py - cut the ngspice waveforms of AFE/spice/tb/tb_transceiver_tr.py
into small CSV windows for the transceiver datasheet figures.

Usage:
    python3 AFE/doc/transceiver_datasheet/data/extract_tr.py [dir_tt dir_ss dir_ff]

Each directory holds the tb_transceiver_tr_{seq,hs,fs,ls200,ls600,rx}.dat of
one corner (default build/spice/xc_{tt,ss,ff}, made by running
tb_transceiver_tr.py with OUT pointing there; corners tt 27 C 3.3 / 1.8 V,
ss 125 C 3.0 / 1.62 V, ff -40 C 3.6 / 1.98 V).  The window times are those of
tb_transceiver_tr.py: hs TX_EN at 100 ns, data from 120.83 ns (10 bits lead),
167 bits, TX_EN falls at 468.75 ns, chirp K from 568.75 ns; fs OE at 283.3 ns,
SYNC at 616.7 ns, EOP at 4616.7 ns; ls SYNC at 3533 ns, EOP at 16867 ns;
seq steps T1..T16 = 100, 200, ... 2693 ns; rx ramps 100 ns .. 16.8 us.
Output: xc_<corner>_<win>.csv on a uniform grid; times in ns, voltages in V,
vd = V(DP) - V(DM), currents in mA.
"""
import os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))


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
    dirs = sys.argv[1:] or [os.path.join(ROOT, "build", "spice", "xc_" + c) for c in ("tt", "ss", "ff")]
    for corner, d in zip(("tt", "ss", "ff"), dirs):
        f = lambda c: os.path.join(d, f"tb_transceiver_tr_{c}.dat")
        W = lambda n, *a, **k: window(f"xc_{corner}_{n}", *a, **k)
        if os.path.exists(f("hs")):
            t, (dp, dm, i33, i18, rdy, dq) = load(f("hs"))
            W("hs_start", t, [dp - dm, rdy, dq], ["vd", "rdy", "dq"], 90e-9, 140e-9, 20e-12)
            W("hs_pkt", t, [dp - dm], ["vd"], 118e-9, 472e-9, 10e-12)
            W("hs_chirp", t, [dp, dm], ["dp", "dm"], 500e-9, 718e-9, 0.1e-9)
        if os.path.exists(f("seq")):
            t, (dp, dm, rcv, rdp, rdm, i33, i18, rdy) = load(f("seq"))
            W("seq", t, [dp, dm, rcv, rdp, rdm], ["dp", "dm", "rcv", "rdp", "rdm"], 0, 2693e-9, 0.5e-9, "%.3f")
            W("seq_hs", t, [dp, dm, rdy], ["dp", "dm", "rdy"], 195e-9, 260e-9, 25e-12)
        for c in ("fs", "ls200", "ls600"):
            if os.path.exists(f(c)):
                t, (dp, dm, rcv, rdp, rdm, i33) = load(f(c))
                if c == "fs":                                           # J idle, SYNC from 616.7 ns
                    W("fs_zoom", t, [dp, dm, rcv, rdp, rdm], ["dp", "dm", "rcv", "rdp", "rdm"], 510e-9, 830e-9, 50e-12, "%.3f")
                else:
                    W(c, t, [dp, dm], ["dp", "dm"], 0, t[-1], 4e-9, "%.3f")
        if os.path.exists(f("rx")):
            t, (dp, dm, rcv, rdp, rdm, v33, sd33, pok) = load(f("rx"))
            W("rx", t, [dp, rdp, v33], ["dp", "rdp", "vdd33"], 0, t[-1], 2e-9, "%.4f")
        print(corner, "done from", d)


if __name__ == "__main__":
    main()
