#!/usr/bin/env python3
"""run_sims.py - ngspice characterisation of the discrete USB 2.0 CDR board
(afe_cdr on the CDR board)

Usage:  python3 AFE/Discrete/CDR/sim/run_sims.py [case-filter ...] [--force]
        (JOBS=n parallel runs; results in sim/results/<case>/, summary in
        sim/results/summary.json)

Circuit (schematic sheets 3 / 4, doc section 4):
  VCO     BFR93A Colpitts (Q3) with a base-coupled tank: 6.2 nH LQW18 (L1),
          coarse branch C_S 18 pF + 1SV305 (D1) tuned through R_K 2.2 k from
          CDR_V_IN_2 (buffered), fine branch C_F 12 pF + 1SV305 (D2): cathode
          = node F (CDR_CH_OUT) fed through the 47 nH RF choke L2 from the
          prop driver, anode at V_A (fine bias / trim, buffered DAC, RF
          bypassed); BFR93A buffer (Q4) -> 100 pF -> NB6L14 IN (internal 50 Ohm to
          VT = VREF_AC, AC-grounded; single-ended drive needs >= 200 mV p-p).
  Driver  "charge pump": two BFR93A current switches (Q5/Q6 UP, Q7/Q8 DN),
          20 mA tails, into R_L = 62 Ohm from +5V_A (node P):
          idle (UP = DN = 0) 3.76 V, UP 5.0 V, DN 2.5 V.  The model's
          icp * R8 proportional path.
  PD      Alexander, 100EP logic (behavioural, XSPICE): FF1 (data, rising
          CLK), FF2 (edge, falling), FF3 (FF1 + 1 bit), FF4 (FF2 retimed);
          UP = FF3 xor FF4, DN = FF4 xor FF1 (MC100EP29 tpd 420 ps, MC100EP08
          330 ps, LVPECL 1.49 / 2.29 V, 200 ps edges); clock = NB6L14 (input
          threshold at VREF, tpd 450 ps).

Cases
  vco_<T>       transistor level: f vs coarse input 2.0 .. 4.5 V at F idle,
                and the UP / DN frequency steps (T = -40 / 27 / 85 C)
  vcotol_<L>    L1 6.0 / 6.4 nH (tolerance), 27 C
  vafine        f vs V_A (fine bias / calibration trim)
  lock_<k>      full loop, transistor-level VCO and driver: idle (VCO free
                running), then a HS packet (32-bit SYNC + PRBS payload) at the
                free-running frequency, start phase k / 8 UI: bits to lock
  ppm_<p>       the same with a +-p ppm data-rate offset and 600 bits payload
                (frequency tracking without an integral path)
  jit           400 bits with 25 ps rms random jitter + 40 ps p-p sinusoidal
                jitter on the data edges
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
LIB = os.path.join(HERE, "models", "cdr_models.lib")

# ---- component values (keep equal to the schematic / doc section 4) ----
VAL = dict(
    RC1=22.0, RB1a=4.7e3, RB1b=4.7e3, RB2=6.8e3, RE1=180.0, C1=10e-12, C2=10e-12,
    Ccpl=3.3e-12, Cp=0.3e-12, Cs=18e-12, Rk=2.2e3, Cf=12e-12, Cb2=1.5e-12,
    RB3=10e3, RB4=4.7e3, RE2=100.0, RC2=100.0, Rtap=470.0,
    RL=62.0, RT=100.0,               # prop driver: load, tail resistors (15 mA)
    RBS=47.0,                        # prop driver base stoppers
    LCH="47N", RCH=0.5,              # fine feed: 47 nH RF choke (+ series R)
    VA=2.6,                          # fine varactor anode (nominal trim)
    VDD_VCO=4.82, V5=5.0,
    VREF=1.875,                      # NB6L14 VREF_AC = VCC - 1.425 V
    RIN=50.0)                        # NB6L14 IN: internal 50 Ohm to VT (= VREF_AC, AC ground)
VOH, VOL = 2.29, 1.49                # 100EP at VCC = 3.3 V, 25 C (datasheet typ.)
T_FF, T_XOR, T_CLK = 0.42e-9, 0.33e-9, 0.45e-9
TBIT = 1 / 480e6
VK_PTS = [2.0, 2.5, 3.0, 3.18, 3.5, 4.0, 4.5]


def fmt(v):
    return "%.6g" % v


def vco_core(c):
    """VCO + fine branch + prop driver (common to all cases)"""
    V = VAL
    lk = c.get("lk", "")
    return [
        ".include %s" % LIB,
        ".options temp=%g tnom=27 reltol=%g method=gear maxord=2" % (c.get("temp", 27), c.get("reltol", 1e-4)),
        "VCC vcc 0 %g" % V["VDD_VCO"], "V5 v5 0 %g" % V["V5"],
        "RC1 vcc c1 %s" % fmt(V["RC1"]), "CC1 c1 0 100p",
        "RB1b vcc x %s" % fmt(V["RB1b"]), "RB1a x b1 %s" % fmt(V["RB1a"]),
        "RB2 b1 0 %s" % fmt(V["RB2"]),
        "XQ3 c1 b1 e1 BFR93A", "RE1 e1 0 %s" % fmt(V["RE1"]),
        "C1 b1 e1 %s" % fmt(V["C1"]), "C2 e1 0 %s" % fmt(V["C2"]),
        "Ccpl b1 t %s" % fmt(V["Ccpl"]),
        "XL1 t lg LQW18_6N2%s" % lk, "Llg lg 0 0.3n", "Cpar t 0 0.6p", "CP0 t 0 %s" % fmt(V["Cp"]),
        "Cs t k %s" % fmt(V["Cs"]), "XD1 0 k SV305", "Rk vk k %s" % fmt(V["Rk"]),
        "VK vk 0 %g" % c.get("vk", 3.18),
        "Cf t f %s" % fmt(c.get("cf", V["Cf"])), "XD2 a2 f SV305",
        "VA a2 0 %g" % c.get("va", V["VA"]),
        ("XL2 f pq LQW18_%s" % c.get("lch", V["LCH"])) if c.get("lch", V["LCH"]) != "R"
        else "Rpq0 f pq 0.01", "Rpq pq p %g" % c.get("rch", V["RCH"]),
        "RL v5 p %s" % fmt(c.get("rl", V["RL"])), "Cpp p 0 1.5p",
        "RBU1 upn upn_b %g" % c.get("rb", V["RBS"]), "RBU2 upp upp_b %g" % c.get("rb", V["RBS"]),
        "RBD1 dnp dnp_b %g" % c.get("rb", V["RBS"]), "RBD2 dnn dnn_b %g" % c.get("rb", V["RBS"]),
        "XQ5 p upn_b eu BFR93A", "XQ6 v5 upp_b eu BFR93A", "RTU eu 0 %s" % fmt(c.get("rt", V["RT"])),
        "XQ7 p dnp_b ed BFR93A", "XQ8 v5 dnn_b ed BFR93A", "RTD ed 0 %s" % fmt(c.get("rt", V["RT"])),
        "CEU eu 0 0.5p", "CED ed 0 0.5p",
        "Cb2 e1 b2 %s" % fmt(V["Cb2"]),
        "RB3 vcc b2 %s" % fmt(V["RB3"]), "RB4 b2 0 %s" % fmt(V["RB4"]),
        "XQ4 c2 b2 e2 BFR93A", "RE2 e2 0 %s" % fmt(V["RE2"]), "CE2 e2 0 100p",
        "RC2 vcc c2 %s" % fmt(c.get("rc2", V["RC2"])),
        "Cout c2 inp 100p", "Rin inp vrf %g" % c.get("rin", V["RIN"]), "VRF vrf 0 %g" % V["VREF"],
        "Cin inp 0 1.0p",
        "Rtap c2 sma %s" % fmt(V["Rtap"]), "Rsma sma 0 50"]


# ---------------------------------------------------------------------------
# static VCO: f at one (coarse, state, V_A) point
# ---------------------------------------------------------------------------
def vco_netlist(c, out):
    st = c.get("st", 0)
    up = VOH if st > 0 else VOL
    dn = VOH if st < 0 else VOL
    L = ["* discrete CDR board - VCO - generated by run_sims.py"] + vco_core(c)
    L += ["VUP upp 0 %g" % up, "VUN upn 0 %g" % (VOH + VOL - up),
          "VDP dnp 0 %g" % dn, "VDN dnn 0 %g" % (VOH + VOL - dn),
          "Ikick 0 t PULSE(0 1m 1n 0.2n 0.2n 0.5n 1)",
          ".tran 20p 300n 0 20p", ".control", "run",
          "wrdata %s v(inp) v(f) v(p)" % out, ".endc", ".end"]
    return "\n".join(L)


def vco_measure(path, t0=180e-9):
    d = np.loadtxt(path)
    t, v = d[:, 0], d[:, 1]
    m = t > t0
    vf = float(d[m, 3].mean())
    t, v = t[m], v[m]
    pp = float(v.max() - v.min())
    if pp < 0.02:
        return 0.0, pp, vf
    vm = 0.5 * (v.max() + v.min())
    s = np.where((v[:-1] < vm) & (v[1:] >= vm))[0]
    tc = t[s] + (vm - v[s]) / (v[s + 1] - v[s]) * (t[s + 1] - t[s])
    return float((len(tc) - 1) / (tc[-1] - tc[0])), pp, vf


def run_ngspice(d, net, name="tb.cir"):
    cir = os.path.join(d, name)
    with open(cir, "w") as f:
        f.write(net)
    r = subprocess.run(["ngspice", "-b", cir], capture_output=True, text=True, cwd=d)
    with open(os.path.join(d, "log.txt"), "w") as f:
        f.write(r.stdout + r.stderr)
    return r.returncode


def vco_point(d, c, tag):
    out = os.path.join(d, "w_%s.txt" % tag)
    run_ngspice(d, vco_netlist(c, out), "tb_%s.cir" % tag)
    r = vco_measure(out)
    os.remove(out)
    os.remove(os.path.join(d, "tb_%s.cir" % tag))
    return r


def case_vco(name, c):
    d = os.path.join(RES, name)
    os.makedirs(d, exist_ok=True)
    rows = []
    for vk in VK_PTS:
        f, pp, vf = vco_point(d, dict(c, vk=vk), "k%g" % vk)
        rows.append(dict(vk=vk, f=f, vpp=pp, vf=vf))
    steps = {}
    for st, nm in ((1, "up"), (-1, "dn")):
        f, pp, vf = vco_point(d, dict(c, vk=3.18, st=st), nm)
        steps[nm] = dict(f=f, vf=vf, vpp=pp)
    f0 = [r["f"] for r in rows if r["vk"] == 3.18][0]
    res = dict(case=name, temp=c.get("temp", 27), lk=c.get("lk", ""), rows=rows, f0=f0,
               df_up=steps["up"]["f"] - f0, df_dn=steps["dn"]["f"] - f0,
               vf_up=steps["up"]["vf"], vf_dn=steps["dn"]["vf"],
               vf_idle=[r["vf"] for r in rows if r["vk"] == 3.18][0])
    fs = [r["f"] for r in rows]
    vks = [r["vk"] for r in rows]
    res["kc"] = float((np.interp(3.5, vks, fs) - np.interp(2.5, vks, fs)) / 1.0)
    res["v480"] = float(np.interp(480e6, fs, vks)) if fs[0] < 480e6 < fs[-1] else None
    res["vpp_min"] = min([r["vpp"] for r in rows] + [s["vpp"] for s in steps.values()])
    res["step_ui"] = 0.5 * (res["df_up"] - res["df_dn"]) * TBIT
    return res


def case_vafine(name, c):
    d = os.path.join(RES, name)
    os.makedirs(d, exist_ok=True)
    rows = []
    for va in (1.8, 2.2, 2.6, 3.0, 3.4):
        f, pp, _ = vco_point(d, dict(c, va=va), "a%g" % va)
        fu, _, _ = vco_point(d, dict(c, va=va, st=1), "a%gu" % va)
        fd, _, _ = vco_point(d, dict(c, va=va, st=-1), "a%gd" % va)
        rows.append(dict(va=va, f=f, df_up=fu - f, df_dn=fd - f, vpp=pp))
    return dict(case=name, rows=rows)


# ---------------------------------------------------------------------------
# full loop: behavioural 100EP phase detector + transistor-level VCO / driver
# ---------------------------------------------------------------------------
def prbs7(n, seed=0x5A):
    s, out = seed & 0x7F, []
    for _ in range(n):
        b = ((s >> 6) ^ (s >> 5)) & 1
        s = ((s << 1) | b) & 0x7F
        out.append(b)
    return out


def usb_hs_bits(n_payload, seed=0x5A):
    """line levels (1 = J) of a HS packet: SYNC (KJKJ... KK, 32 bits), NRZI
    payload with bit stuffing (PRBS7 data), EOP (8 bits 01111111 NRZI, no stuffing)"""
    data = [0] * 31 + [1] + prbs7(n_payload, seed)
    lvl, out, ones = 1, [], 0            # idle J before the packet
    for b in data:
        if b == 0:
            lvl ^= 1
            ones = 0
        else:
            ones += 1
        out.append(lvl)
        if ones == 6:                    # stuff a 0
            lvl ^= 1
            out.append(lvl)
            ones = 0
    for b in [0] + [1] * 7:              # EOP: NRZI 01111111 without stuffing
        if b == 0:
            lvl ^= 1
        out.append(lvl)
    return out


def data_pwl(bits, t0, tb, jit_rms=0.0, sj_pp=0.0, sj_f=0.0, seed=1, tr=150e-12):
    rng = np.random.default_rng(seed)
    pts, lvl, t = ["0 1"], 1, t0          # idle level: 1 (J)
    edges = []
    for k, b in enumerate(bits):
        tk = t0 + k * tb
        if b != lvl:
            te = tk + (rng.normal(0, jit_rms) if jit_rms else 0.0) \
                + (0.5 * sj_pp * np.sin(2 * np.pi * sj_f * tk) if sj_pp else 0.0)
            pts.append("%.6e %d" % (te - tr / 2, lvl))
            pts.append("%.6e %d" % (te + tr / 2, b))
            edges.append(te)
            lvl = b
    return " ".join(pts), edges


def loop_netlist(c, out, pwl):
    L = ["* discrete CDR board - loop transient - generated by run_sims.py"] + vco_core(c)
    L += [
        # data (0 / 1 V) -> 100EP input
        "VDAT dat 0 PWL(%s)" % pwl,
        "Adat [dat] [datd] adc1", ".model adc1 adc_bridge(in_low=0.45 in_high=0.55 rise_delay=1e-12 fall_delay=1e-12)",
        # NB6L14: comparator at VREF, tpd T_CLK; ckn = inverted (FF2 clock pins swapped)
        "Bcmp cmp 0 V=0.5 + 0.5 * tanh((V(inp) - %g) / 0.01)" % VAL["VREF"],
        "Ack [cmp] [ck0] adc1",
        "Ackb ck0 ck nbuf", ".model nbuf d_buffer(rise_delay=%g fall_delay=%g)" % (T_CLK, T_CLK),
        "Ackn ck ckn ninv", ".model ninv d_inverter(rise_delay=1e-12 fall_delay=1e-12)",
        # CDR_EN (set inputs of the MC100EP29s): 1 = enabled
        "Aen [en0] [enn] adc1", "VEN en0 0 PWL(0 0 %g 0 %g 1)" % (c["t_en"], c["t_en"] + 1e-9),
        "Aseti enn setn ninv",
        "Ahi hi pu1", ".model pu1 d_pullup", "Alo lo pd1", ".model pd1 d_pulldown",
        # MC100EP29 x 2: FF1 data / rising, FF2 edge / falling, FF3, FF4 retimed
        ".model ff d_dff(clk_delay=%g set_delay=%g reset_delay=%g rise_delay=1e-12 fall_delay=1e-12)" % (T_FF, T_FF, T_FF),
        "Aff1 datd ck setn lo qa qan ff",
        "Aff2 datd ckn setn lo qtp qtpn ff",
        "Aff3 qa ck setn lo qb qbn ff",
        "Aff4 qtp ck setn lo qt qtn ff",
        # MC100EP08 x 2
        ".model xr d_xor(rise_delay=%g fall_delay=%g)" % (T_XOR, T_XOR),
        "Aup [qb qt] up xr", "Adn [qt qa] dn xr",
        ".model dac1 dac_bridge(out_low=0 out_high=1 t_rise=200p t_fall=200p)",
        "Aua [up dn qa ck] [upa dna qaa cka] dac1",
        # LVPECL levels into the driver bases
        "BUP upp 0 V=%g + %g * V(upa)" % (VOL, VOH - VOL),
        "BUN upn 0 V=%g - %g * V(upa)" % (VOH, VOH - VOL),
        "BDP dnp 0 V=%g + %g * V(dna)" % (VOL, VOH - VOL),
        "BDN dnn 0 V=%g - %g * V(dna)" % (VOH, VOH - VOL),
        "Ikick 0 t PULSE(0 1m 1n 0.2n 0.2n 0.5n 1)",
        ".save v(cka) v(qaa) v(f) v(upa) v(dna)",
        ".tran 10p %g 0 10p" % c["tstop"], ".control", "run",
        "linearize v(cka) v(qaa) v(f) v(upa) v(dna)",
        "wrdata %s v(cka) v(qaa) v(f) v(upa) v(dna)" % out, ".endc", ".end"]
    return "\n".join(L)


def crossings(t, v, th=0.5, rising=True):
    if rising:
        s = np.where((v[:-1] < th) & (v[1:] >= th))[0]
    else:
        s = np.where((v[:-1] >= th) & (v[1:] < th))[0]
    return t[s] + (th - v[s]) / (v[s + 1] - v[s]) * (t[s + 1] - t[s])


def case_loop(name, c):
    d = os.path.join(RES, name)
    os.makedirs(d, exist_ok=True)
    # free-running frequency of the nominal VCO at this corner (static case)
    vr = json.load(open(os.path.join(RES, c.get("vco", "vco_27"), "result.json")))
    f0 = vr["f0"]
    tb = 1 / (f0 * (1 + 1e-6 * c.get("ppm", 0)))
    bits = usb_hs_bits(c["npay"], seed=c.get("seed", 0x5A))
    t_data = c["t_en"] + 400e-9 + c.get("phase", 0) * tb
    pwl, edges = data_pwl(bits, t_data, tb, c.get("jit", 0), c.get("sj", 0), c.get("sjf", 0),
                          seed=c.get("seed", 1))
    c = dict(c, tstop=t_data + (len(bits) + 20) * tb)
    out = os.path.join(d, "wave.txt")
    if os.path.exists(out):
        os.remove(out)                      # an aborted run writes nothing: never read a stale file
    rc = run_ngspice(d, loop_netlist(c, out, pwl))
    w = np.loadtxt(out) if os.path.exists(out) else np.zeros((2, 10))
    if rc != 0 or w[-1, 0] < c["tstop"] - 1e-9:
        # timestep failure in a driver transistor (rare): retry with reltol 1e-3
        c = dict(c, reltol=1e-3)
        if os.path.exists(out):
            os.remove(out)
        rc = run_ngspice(d, loop_netlist(c, out, pwl))
        w = np.loadtxt(out)
    t, ck, qa, vf, upa, dna = w[:, 0], w[:, 1], w[:, 3], w[:, 5], w[:, 7], w[:, 9]
    tck = crossings(t, ck) - 100e-12        # FF clock edge (ck) = sampling instant; dac_bridge 200 ps rise
    # sampling phase of every rising edge inside the packet: position inside the bit (0 .. 1)
    ts = tck[(tck > t_data) & (tck < t_data + len(bits) * tb)]
    ph = ((ts - t_data) / tb) % 1.0
    k = np.floor((ts - t_data) / tb).astype(int)
    # error-free sampling: the sample must fall between the bit's actual edges
    te = np.array(edges)
    good = []
    for tsi, ki in zip(ts, k):
        prev = te[te <= tsi]
        nxt = te[te > tsi]
        m1 = tsi - prev[-1] if len(prev) else 1.0
        m2 = nxt[0] - tsi if len(nxt) else 1.0
        good.append(min(m1, m2) > 100e-12)          # 100 ps: MC100EP29 setup / hold
    good = np.array(good)
    # lock: first bit from which every sample stays inside 0.2 .. 0.8 UI (>= 0.2 UI margin to the
    # data edges) to the end of the packet; errors: samples within 100 ps of an edge (EP29 setup / hold)
    inside = (ph > 0.2) & (ph < 0.8)
    out_ = np.where(~inside)[0]
    lock_bits = int(k[out_[-1]] + 1) if len(out_) else 0
    res = dict(case=name, rc=rc, f0=f0, reltol=c.get("reltol", 1e-4), ppm=c.get("ppm", 0), phase=c.get("phase", 0),
               n_bits=len(bits), lock_bits=lock_bits,
               errors_sync=int((~good[:32]).sum()), errors_after_sync=int((~good[32:]).sum()),
               samples=int(len(good)), complete=bool(t[-1] > c["tstop"] - 1e-9))
    pay = ph[32:]
    if len(pay):
        # dither of the sampling phase in the payload (eye-centre = 0.5)
        res["phase_mean_ui"] = float(pay.mean())
        res["phase_pp_ui"] = float(pay.max() - pay.min())
        res["phase_rms_ui"] = float(pay.std())
        res["min_margin_ps"] = float(1e12 * min(np.min(pay), np.min(1 - pay)) * tb)
    m = t > t_data + 32 * tb
    res["vf_mean"] = float(vf[m].mean())
    res["up_frac"] = float((upa[m] > 0.5).mean())
    res["dn_frac"] = float((dna[m] > 0.5).mean())
    np.savetxt(os.path.join(d, "phase.txt"), np.c_[k, ph, good.astype(int)], fmt="%d %.4f %d")
    # decimate the wave for the figures
    tg = np.arange(t[0], t[-1], 50e-12)
    np.savetxt(out, np.c_[tg, np.interp(tg, t, vf), np.interp(tg, t, upa) - np.interp(tg, t, dna)],
               fmt="%.5e")
    return res


# ---------------------------------------------------------------------------
CASES = {}
for T in (-40, 27, 85):
    CASES["vco_%d" % T] = ("vco", dict(temp=T))
for lk in ("m", "p"):
    CASES["vcotol_%s" % lk] = ("vco", dict(temp=27, lk="_" + lk))
CASES["vafine"] = ("vafine", dict(temp=27))
for k in range(8):
    CASES["lock_%d" % k] = ("loop", dict(t_en=10e-9, phase=k / 8.0, npay=60, seed=0x5A + k))
for p in (-10000, -2000, -500, 500, 2000, 10000):
    CASES["ppm_%+d" % p] = ("loop", dict(t_en=10e-9, phase=0.5, npay=600, ppm=p, seed=0x33))
CASES["jit"] = ("loop", dict(t_en=10e-9, phase=0.25, npay=400, jit=25e-12, sj=40e-12, sjf=7e6,
                             seed=0x11))
for T in (-40, 85):
    CASES["lock_t%d" % T] = ("loop", dict(t_en=10e-9, phase=0.5, npay=60, temp=T, vco="vco_%d" % T,
                                          seed=0x21))


def run_case(name):
    kind, c = CASES[name]
    if kind == "vco":
        return case_vco(name, c)
    if kind == "vafine":
        return case_vafine(name, c)
    return case_loop(name, c)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    names = [n for n in CASES if not args or any(a in n for a in args)]
    # static VCO cases first: the loop cases use their f0
    stat = [n for n in names if CASES[n][0] != "loop"]
    loop = [n for n in names if CASES[n][0] == "loop"]
    os.makedirs(RES, exist_ok=True)
    sp = os.path.join(RES, "summary.json")
    summary = json.load(open(sp)) if os.path.exists(sp) else {}
    jobs = int(os.environ.get("JOBS", "2"))
    for group in (stat, loop):
        todo = [n for n in group if force or n not in summary]
        with ThreadPoolExecutor(jobs) as ex:
            fut = {ex.submit(run_case, n): n for n in todo}
            for f in as_completed(fut):
                n = fut[f]
                try:
                    r = f.result()
                except Exception as e:      # keep going, report
                    r = dict(case=n, error=repr(e))
                summary[n] = r
                with open(os.path.join(RES, n, "result.json") if os.path.isdir(os.path.join(RES, n))
                          else os.devnull, "w") as fo:
                    json.dump(r, fo, indent=1)
                with open(sp, "w") as fo:
                    json.dump(summary, fo, indent=1)
                print("done", n, {k: v for k, v in r.items() if k not in ("rows",)}, flush=True)


if __name__ == "__main__":
    main()
