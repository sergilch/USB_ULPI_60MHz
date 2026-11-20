#!/usr/bin/env python3
"""extract_tr.py - per-edge data of the transistor-level CDR runs for the datasheet.

Reads the ngspice waveforms written by AFE/spice/tb/tb_cdr_tr.py (build/spice/
tb_cdr_tr_{lock0,lockp,lockn}.dat), rebuilds the same stimulus (same random
seeds) and writes, for every rising edge of the PD sampling clock ckpd inside
a packet, one row to tr_<case>.csv:

    packet, bit (edge position in bits from the packet start), s (sampling
    offset from the centre of the din bit cell in UI, + = late), margin (UI,
    distance to the nearest din transition, max 0.5), v_chout (V)

Usage: python3 AFE/doc/cdr_datasheet/data/extract_tr.py [case ...]
(rerun tb_cdr_tr.py first if the netlist changed).
"""
import os, sys, bisect, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "spice", "tb"))
import tb_cdr_tr as tb

SEED = {"lock0": 3, "lockp": 5, "lockn": 7}

def extract(case, vdd=1.8):
    pwl, pkts, t_dis = tb.build_stimulus(case, random.Random(SEED[case]))
    t, clk, rxd, chout, ckpd, din, ivdd = tb.load(os.path.join(tb.OUT, f"tb_cdr_tr_{case}.dat"))
    th = vdd / 2
    ck_r = tb.crossings(t, ckpd, th, True)
    din_x = tb.crossings(t, din, th)
    rows = []
    for k, (t0, ui, bits) in enumerate(pkts):
        t1 = t0 + len(bits) * ui
        for x in (e for e in ck_r if t0 < e < t1):
            j = bisect.bisect_left(din_x, x)
            prev = din_x[j - 1] if j > 0 else t0
            nxt = din_x[j] if j < len(din_x) else 1.0
            m = min((x - prev) / ui, (nxt - x) / ui, 0.5)
            s = ((x - prev) / ui) % 1.0 - 0.5
            i = min(max(bisect.bisect_left(t, x), 1), len(t) - 1)
            rows.append((k, (x - t0) / ui, s, m, chout[i]))
    fn = os.path.join(HERE, f"tr_{case}.csv")
    with open(fn, "w") as fo:
        fo.write("packet,bit,s_ui,margin_ui,v_chout\n")
        for r in rows:
            fo.write("%d,%.3f,%.4f,%.4f,%.5f\n" % r)
    print(case, len(rows), "edges ->", fn, flush=True)

if __name__ == "__main__":
    for c in sys.argv[1:] or ["lock0", "lockp", "lockn"]:
        extract(c)
