#!/usr/bin/env python3
"""run_fsls.py - ngspice characterisation of the discrete FS/LS driver (board sheet 3)

Usage:  python3 AFE/Discrete/Transmitter/sim/run_fsls.py [case-filter ...] [--force]
        (JOBS=n parallel runs; results in sim/results/fsls_<case>/, summary in
        sim/results/fsls_summary.json; python3 tables.py prints the tables)

Circuit (doc section 4.4, values in VAL below; keep equal to the schematic):
  FS_OE / FS_DAT / FS_SE0 / FS_LS (VADJ) -> SN74LVC8T245 -> SN74LVC138 (G1 = OE,
  A = DAT, B = LS, C = SE0) -> 4 x SN74LVC1G11 gate commands
      GP_P = Y1# & Y2#        GN_P = OE & Y1# & Y2#      (D+ high: FS J, LS K)
      GP_M = Y0# & Y3#        GN_M = OE & Y0# & Y3#      (D- high: FS K, LS J)
  per wire: NX3008CBKS P (source +3V3) / N (source GND) drains -> R_S 33 Ohm
  -> FSUSB42 port 1 -> line; the switch is enabled (OE# = NOR(FS_OE, HS_TERM_EN),
  SN74LVC1G02) only while the driver transmits, so in receive mode the gate
  networks do not load the line.  Per gate: R_LS from the LVC1G11 output (always),
  R_FS from an SN74LVC125 output enabled while FS_LS = 0, a BAT54WS that turns
  the gate off fast (turn-on is slow -> break-before-make), and the Miller
  capacitor C_M from the drain to the gate that sets the slew rate.  P gates
  only: C_K across R_LS (earlier LS turn-on, LS crossover) and C_M2 behind R_M2
  (LS Miller capacitor that the FS edges do not see); N gates only: C_KF across
  R_FS (earlier FS turn-on, FS crossover).
  The line also carries the HS driver (BFT92 collectors through RB751S40
  blocking diodes, the LVPECL base levels of the idle FS/LS state), TX_CAP,
  FSUSB42 capacitances, USBLC6, the receivers behind 1 kOhm (TLV3502
  single-ended with 13k / 10k / 82k Schmitt network, TLV3501 differential) and
  the test load.

Logic: ideal Boolean functions with the datasheet propagation delays (typ,
3.3 V): 8T245 4.0 ns, LVC138 4.5 ns, LVC1G11 3.5 ns, LVC125 3.5 ns, LVC1G02
3.5 ns, FSUSB42 tON / tOFF 13 / 12 ns, 1 ns edges,
25 Ohm outputs.  The '138 decode glitches of simultaneous input changes are
not modelled (they are shorter than the gate time constants).

Loads (USB 2.0 7.1.1.3, USB3320 table 4-6): CL from each wire to GND at the
connector; FS: board pull-up 1.5 kOhm on D+ (DP_PULLUP_EN), host 15 kOhm
pull-downs; LS (PHY as host): board 15 kOhm pull-downs (PD_EN0/1), device
1.5 kOhm on D- to 3.3 V.
"""
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import usbpat  # noqa: E402

RES = os.path.join(HERE, "results")
LIB_TX = os.path.join(HERE, "models", "tx_models.lib")
LIB_FS = os.path.join(HERE, "models", "fsls_models.lib")
TB_FS, TB_LS = 1e-6 / 12, 1e-6 / 1.5            # bit times

# ---- component values (doc section 4.4, schematic sheet 3) ----
VAL = dict(
    RS=33.0,                     # series resistor (R25 / R26)
    RON=4.5,                     # FSUSB42 R_on
    CM_N=150e-12, CM_P=8.2e-12,  # Miller capacitors drain -> gate (edge rate)
    CM2_N=0.0, CM2_P=47e-12,     # second Miller capacitor behind R_M2: only acts on the slow
    RM2_N=0.0, RM2_P=470.0,      #   LS edges (tau 22 ns), keeps the weak P's LS rise load-independent
    RLS_N=560.0, RLS_P=1200.0,   # LS gate resistors (always in)
    RFS_N=18.0, RFS_P=43.0,      # FS gate resistors (LVC125 path, FS_LS = 0), + 25 Ohm LVC output
    CKF_N=39e-12, CKF_P=0.0,     # speed-up capacitor across R_FS: N turns on earlier (FS crossover)
    CK_N=0.0, CK_P=10e-12,       # speed-up capacitor across R_LS: P turns on earlier (LS crossover)
    RPU=1500.0, RPD=15000.0,
    VREF_TOP=13e3, VREF_BOT=10e3, VREF_FB=82e3,   # single-ended receiver Schmitt network
    ITAIL=18.9e-3,               # HS tail current, dumped while TX_EN = 0
)
DLY = dict(t245=4.0e-9, t138=4.5e-9, t11=3.5e-9, t125=3.5e-9, t02=3.5e-9, t_on=13e-9, t_off=12e-9)
T_EDGE = 1.0e-9
R_LVC = 25.0


# ------------------------------------------------------------------ stimulus
def fs_packet(payload, ls=False):
    """Per-bit pin values (oe, dat, se0) of one packet: idle, SYNC, PID DATA0,
    payload, CRC16, EOP (SE0 SE0 J), idle.  dat = 1 is J (the driver applies
    the LS polarity)."""
    data = [0xC3] + list(payload)
    data += usbpat.crc16(payload)
    bits = usbpat.bits_lsb([0x80]) + usbpat.stuff(usbpat.bits_lsb(data))
    line = usbpat.nrzi(bits)                      # J = 1, starts from idle J
    pins = [(0, 1, 0)] * 6                        # idle, driver off
    pins += [(1, b, 0) for b in line]
    pins += [(1, 0, 1), (1, 0, 1), (1, 1, 0)]     # EOP
    pins += [(0, 1, 0)] * 6
    return pins, line


def stepfun(events):
    """events: sorted [(t, value)] -> f(t) (value of the last event at or before t)"""
    ts = np.array([e[0] for e in events])
    vs = [e[1] for e in events]

    def f(t):
        i = np.searchsorted(ts, t, side="right") - 1
        return vs[max(i, 0)]
    return f, list(ts)


def logic_waves(pins, tb, ls, t0):
    """Gate commands (0 / 1) at the LVC1G11 and LVC125 outputs as event lists."""
    ev = [(t0 + i * tb, p) for i, p in enumerate(pins)]
    ev = [(-1.0, pins[0])] + ev
    pin, tpin = stepfun(ev)
    d1 = DLY["t245"]
    d2 = d1 + DLY["t138"]
    d3 = d2 + DLY["t11"]

    def y(k, t):                                  # LVC138 outputs (active low) at time t
        oe, dat, se0 = pin(t - d2)
        code = (se0 << 2) | (int(ls) << 1) | dat
        return 0 if (oe and code == k) else 1

    def oe_at(t):
        return pin(t - d1)[0]

    out = {}
    cand = sorted(set([t + d for t in tpin for d in (d1 + DLY["t11"], d3)]))

    def gate_fun(f):
        vals, last = [], None
        for t in [-1.0] + cand:
            v = f(t + 1e-13)
            if v != last:
                vals.append((t, v))
                last = v
        return vals
    out["gpp"] = gate_fun(lambda t: y(1, t - DLY["t11"]) & y(2, t - DLY["t11"]))
    out["gnp"] = gate_fun(lambda t: oe_at(t - DLY["t11"]) & y(1, t - DLY["t11"]) & y(2, t - DLY["t11"]))
    out["gpm"] = gate_fun(lambda t: y(0, t - DLY["t11"]) & y(3, t - DLY["t11"]))
    out["gnm"] = gate_fun(lambda t: oe_at(t - DLY["t11"]) & y(0, t - DLY["t11"]) & y(3, t - DLY["t11"]))
    for k in ("gpp", "gnp", "gpm", "gnm"):
        out[k + "f"] = [(t + DLY["t125"], v) for t, v in out[k]]
    return out


def pwl_src(name, node, events, vdd):
    pts = [(0.0, events[0][1] * vdd)]
    for t, v in events[1:]:
        if t <= pts[-1][0]:
            continue
        pts.append((t, pts[-1][1]))
        pts.append((t + T_EDGE, v * vdd))
    body = " ".join("%.5e %.4f" % p for p in pts)
    lines, cur = [], "%s %s 0 PWL(" % (name, node)
    for tok in body.split(" "):
        if len(cur) > 100:
            lines.append(cur)
            cur = "+"
        cur += " " + tok
    lines.append(cur + ")")
    return "\n".join(lines)


# ------------------------------------------------------------------ netlist
def mos_models(c):
    """NX3008CBKS models with the case's threshold / capacitance corner."""
    txt = open(LIB_FS).read()
    out = []
    for m in re.findall(r"^\.model\s+NX3008[NP].*?(?=^\.model|\Z)", txt, re.S | re.M):
        m = re.sub(r"^\*.*$", "", m, flags=re.M).strip()
        p = m.split()[1][-1]                      # N or P
        dv = c.get("dvt_" + p.lower(), 0.0)       # |VTO| shift
        m = re.sub(r"vto=(-?[\d.]+)", lambda g: "vto=%g" % (float(g.group(1)) + (dv if p == "N" else -dv)), m)
        k = c.get("capk", 1.0)
        for par in ("cgs", "cgdmax", "cgdmin"):
            m = re.sub(par + r"=([\d.]+)p", lambda g: "%s=%gp" % (par, float(g.group(1)) * k), m)
        out.append(m)
    return "\n".join(out)


def netlist(c):
    V = dict(VAL, **c.get("val", {}))
    vdd = c["vdd"]
    ls = c["ls"]
    tb = TB_LS if ls else TB_FS
    t0 = 100e-9
    L = ["* discrete FS/LS driver - generated by run_fsls.py",
         ".include %s" % LIB_TX,
         ".model RB751S40 D (is=8n n=1.03 rs=3.5 cjo=2.6p vj=0.35 m=0.45 bv=40 ibv=10u eg=0.69 xti=2)",
         ".model BAT54WS D (is=20n n=1.03 rs=1.6 cjo=10p vj=0.33 m=0.45 bv=30 ibv=10u eg=0.69 xti=2)",
         mos_models(c),
         ".options temp=%g tnom=27 reltol=1e-4 method=gear" % c["temp"],
         "VDD vdd 0 %g" % vdd,
         "VDRV vdd vdrv 0"]                       # driver supply current (shoot-through)
    # host case: the board's driver stays off (receive mode), a host driver sends the packet
    lw = logic_waves([(0, 1, 0)] * len(c["pins"]) if c.get("host") else c["pins"], tb, ls, t0)
    # FSUSB42 OE#: FS_OE -> 8T245 -> LVC1G02 -> switch on 13 ns (tON typ) / off 12 ns (tOFF typ)
    L.append(".model SWFS SW (vt=0.5 vh=0.05 ron=%g roff=1e9)" % V["RON"])
    oe = [p[0] for p in c["pins"]] if not c.get("host") else [0] * len(c["pins"])
    pts = [(0.0, float(oe[0]))]
    for i in range(1, len(oe)):
        if oe[i] != oe[i - 1]:
            tt = t0 + i * tb + DLY["t245"] + DLY["t02"] + (DLY["t_on"] if oe[i] else DLY["t_off"])
            pts += [(tt, float(oe[i - 1])), (tt + 1e-9, float(oe[i]))]
    L.append("VSWC swc 0 PWL(%s)" % " ".join("%.5e %g" % q for q in pts))
    for w, s in (("p", "p"), ("m", "m")):
        for g in ("p", "n"):
            k = "g%s%s" % (g, s)
            L.append(pwl_src("VL" + k, "l" + k, lw[k], vdd))
            L.append("RO%s l%s x%s %g" % (k, k, k, R_LVC))
            # slow path (always), fast path (LVC125, FS only)
            L.append("RLS%s x%s %s %g" % (k, k, k, V["RLS_" + g.upper()]))
            if V.get("CK_" + g.upper(), 0) > 0:     # speed-up capacitor across R_LS
                L.append("CK%s x%s %s %g" % (k, k, k, V["CK_" + g.upper()]))
            if not ls:
                L.append(pwl_src("VL%sf" % k, "l%sf" % k, lw[k + "f"], vdd))
                L.append("RFS%s l%sf %s %g" % (k, k, k, R_LVC + V["RFS_" + g.upper()]))
                if V.get("CKF_" + g.upper(), 0) > 0:    # speed-up capacitor across R_FS
                    L.append("ROF%s l%sf y%sf %g" % (k, k, k, R_LVC))
                    L.append("CKF%s y%sf %s %g" % (k, k, k, V["CKF_" + g.upper()]))
            # fast turn-off diode: P gate pulled up, N gate pulled down
            if g == "p":
                L.append("DH%s x%s %s BAT54WS" % (k, k, k))
            else:
                L.append("DH%s %s x%s BAT54WS" % (k, k, k))
            L.append("CM%s d%s %s %g" % (k, w, k, V["CM_" + g.upper()]))
            if V.get("CM2_" + g.upper(), 0) > 0:    # LS Miller capacitor behind R_M2
                L.append("CM2%s d%s m2%s %g" % (k, w, k, V["CM2_" + g.upper()]))
                L.append("RM2%s m2%s %s %g" % (k, k, k, V["RM2_" + g.upper()]))
        # output stage, 0 V sources for the transistor currents
        # 0 V probes in the drains: channel + C_gd / C_ds current (the source terminal would
        # also carry the gate charge through C_gs)
        L.append("MP%s pd%s gp%s vdrv NX3008P" % (w, w, s))
        L.append("VDP%s pd%s d%s 0" % (w, w, w))
        L.append("MN%s nd%s gn%s 0 NX3008N" % (w, w, s))
        L.append("VDN%s d%s nd%s 0" % (w, w, w))
        L.append("CPD%s d%s 0 1p" % (w, w))
        L.append("RS%s d%s s1%s %g" % (w, w, w, V["RS"]))
        L.append("CS1%s s1%s 0 1.8p" % (w, w))     # FSUSB42 port 1 side
        L.append("SW%s s1%s l%s swc 0 SWFS" % (w, w, w))  # FSUSB42 port 1, OE# = NOR(FS_OE, HS_TERM_EN)
        L.append("CSW%s l%s 0 1.9p" % (w, w))      # FSUSB42 common side
        # HS driver on the line: BFT92 collector through the blocking diode, base at its
        # idle LVPECL level (TX_IN_P = 1: D+ base at VOL, D- base at VOH), R_B 68 Ohm
        vb = (vdd - 1.61) if w == "p" else (vdd - 1.02)
        L.append("VB%s bt%s 0 %g" % (w, w, vb))
        L.append("RBT%s bt%s bb%s 50" % (w, w, w))
        L.append("RBB%s bb%s bq%s 68" % (w, w, w))
        if c.get("hs_diode", True):
            L.append("QH%s ch%s bq%s nem BFT92" % (w, w, w))
            L.append("CCH%s ch%s 0 0.3p" % (w, w))
            L.append("DB%s ch%s l%s RB751S40" % (w, w, w))
        else:
            L.append("QH%s l%s bq%s nem BFT92" % (w, w, w))
        L.append("CTX%s l%s 0 6.8p" % (w, w))       # TX_CAP
        L.append("CD%s l%s 0 1.0p" % (w, w))
        L.append("CESD%s l%s 0 2.5p" % (w, w))      # USBLC6 + connector
        L.append("CL%s l%s 0 %g" % (w, w, c["cl"]))
    # HS tail: TX_EN = 0 -> dump transistor (base 0.60 V) takes the 18.9 mA
    L.append("IT vdd nem %g" % V["ITAIL"])
    L.append("VBD bd 0 0.60")
    L.append("QD 0 bd nem BFT92")
    # pulls
    if not ls:
        L.append("RPU vdd lp %g" % (V["RPU"] + 4.0))      # DP_PULLUP_EN PMOS (about 4 Ohm)
        L.append("RPDP lp 0 %g" % V["RPD"])               # host pull-downs
        L.append("RPDM lm 0 %g" % V["RPD"])
    else:
        L.append("RPUD vpu lm %g" % V["RPU"])             # LS device pull-up on D-
        L.append("VPU vpu 0 3.3")
        L.append("RPDP lp 0 %g" % (V["RPD"] + 3.0))       # board pull-downs (2N7002)
        L.append("RPDM lm 0 %g" % (V["RPD"] + 3.0))
    if c.get("host"):
        # host FS/LS driver: 3.3 V / 0 V ideal source, 4 ns (FS) / 100 ns (LS) 0-100 % ramps,
        # 36 Ohm (USB 2.0 Z_DRV 28-44 Ohm), at the connector; idle = J (pulled-up wire high)
        tr = 100e-9 if ls else 4e-9
        for w in ("p", "m"):
            pts, prev = [(0.0, None)], None
            for i, (oe, dat, s0) in enumerate(c["pins"]):
                hi = (not s0) and ((dat != ls) == (w == "p"))
                v = vdd if hi else 0.0
                if prev is None:
                    pts = [(0.0, v)]
                elif v != prev:
                    tt = t0 + i * tb
                    pts += [(tt, prev), (tt + tr, v)]
                prev = v
            body = " ".join("%.5e %.4f" % q for q in pts)
            L.append("VHO%s ho%s 0 PWL(%s)" % (w, w, body))
            L.append("RHO%s ho%s l%s 36" % (w, w, w))
    if c.get("iload"):                                    # output-impedance test current
        L.append("ILD %s 0 PWL(0 0 %g 0 %g %g)" % (c["iload_node"], c["t_iload"], c["t_iload"] + 50e-9,
                                                   c["iload"]))
    # receivers: TLV3502 (VP, VM): line on IN-, Schmitt divider on IN+ (output = NOT line);
    # TLV3501 (RCV): IN+ = D-, IN- = D+ (output = NOT RCV); the 74LVC3G04 at VADJ inverts
    for w in ("p", "m"):
        L.append("RRT%s vdd rr%s %g" % (w, w, V["VREF_TOP"]))
        L.append("RRB%s rr%s 0 %g" % (w, w, V["VREF_BOT"]))
        L.append("RRF%s co%s rr%s %g" % (w, w, w, V["VREF_FB"]))
        L.append("RRX%s l%s rx%s 1k" % (w, w, w))          # R55 / R56 input isolation
        L.append("CRX%s rx%s 0 4p" % (w, w))               # TLV3502 + TLV3501 inputs + trace
        L.append("BC%s ci%s 0 V=%g*(0.5+0.5*tanh(400*(v(rr%s)-v(rx%s))))" % (w, w, vdd, w, w))
        L.append("RCO%s ci%s co%s 50" % (w, w, w))
        L.append("CCO%s co%s 0 20p" % (w, w))              # ~1 ns output edge, 4.5 ns with the delay below
    L.append("BCR cir 0 V=%g*(0.5+0.5*tanh(400*(v(rxm)-v(rxp))))" % vdd)
    L.append("RCOR cir cor 50")
    L.append("CCOR cor 0 20p")
    ts = c.get("tstep", 0.05e-9)
    L.append(".tran %g %g 0 %g" % (ts, c["t_stop"], 4 * ts))
    L.append(".control")
    L.append("set wr_singlescale")
    L.append("set wr_vecnames")
    L.append("option numdgt=6")
    L.append("run")
    L.append("wrdata %s v(lp) v(lm) v(dp) v(dm) v(gpp) v(gnp) v(gpm) v(gnm) i(vdpp) i(vdnp) "
             "i(vdpm) i(vdnm) v(cop) v(com) v(cor) i(vdrv) v(lgpp) v(lgnp) v(lgpm) v(lgnm)" % c["out"])
    L.append("quit")
    L.append(".endc")
    L.append(".end")
    return "\n".join(L) + "\n", t0, tb


COLS = ["t", "lp", "lm", "dp", "dm", "gpp", "gnp", "gpm", "gnm", "ipp", "inp", "ipm", "inm",
        "cop", "com", "cor", "idrv", "lgpp", "lgnp", "lgpm", "lgnm"]
SOLVER = ["reltol=1e-4 method=gear", "reltol=1e-3 method=gear", "reltol=1e-3 method=trap",
          "reltol=2e-3 method=gear gmin=1e-10"]


def run(name, c):
    d = os.path.join(RES, "fsls_" + name)
    os.makedirs(d, exist_ok=True)
    c = dict(c, out=os.path.join(d, "wave.txt"))
    net, t0, tb = netlist(c)
    for opt in SOLVER:
        open(os.path.join(d, "tb.cir"), "w").write(net.replace("reltol=1e-4 method=gear", opt))
        if os.path.exists(c["out"]):
            os.remove(c["out"])
        r = subprocess.run(["ngspice", "-b", os.path.join(d, "tb.cir")], capture_output=True, text=True,
                           timeout=7200)
        open(os.path.join(d, "log.txt"), "w").write(r.stdout + r.stderr)
        if os.path.exists(c["out"]) and "Timestep too small" not in r.stdout + r.stderr:
            break
    else:
        raise RuntimeError("ngspice failed, see " + d)
    w = np.loadtxt(c["out"], skiprows=1)
    return {k: w[:, i] for i, k in enumerate(COLS)}, t0, tb


# ------------------------------------------------------------------ evaluation
def crossings(t, y, lvl, t_from, t_to, rising=None):
    s = y - lvl
    idx = np.where((s[:-1] * s[1:] < 0) & (t[:-1] >= t_from) & (t[1:] <= t_to))[0]
    out = []
    for i in idx:
        r = s[i + 1] > s[i]
        if rising is None or r == rising:
            out.append(t[i] - s[i] * (t[i + 1] - t[i]) / (s[i + 1] - s[i]))
    return out


def evaluate(w, c, t0, tb):
    t = w["t"]
    pins = c["pins"]
    ls = c["ls"]
    vdd = c["vdd"]
    n = len(pins)
    lvl = lambda k, ui: float(np.interp(t0 + ui * tb, t, w[k]))  # noqa: E731
    # wire that is high in J: FS D+, LS D-
    jw, kw = ("lm", "lp") if ls else ("lp", "lm")
    first = next(i for i, p in enumerate(pins) if p[0])
    last_on = max(i for i, p in enumerate(pins) if p[0])
    se0 = [i for i, p in enumerate(pins) if p[0] and p[2]]
    r = {}
    # idle level of the pulled-up wire before the packet, levels late in long states
    r["idle_pu_V"] = lvl(jw, first - 0.3)
    hi, lo = [], []
    for i in range(first + 1, se0[0]):
        if pins[i][1] == pins[i - 1][1] and i + 1 < se0[0] and pins[i + 1][1] == pins[i][1]:
            # end of a run of >= 2 equal bits: settled levels
            j, k = (jw, kw) if pins[i][1] else (kw, jw)
            hi.append(lvl(j, i + 0.95))
            lo.append(lvl(k, i + 0.95))
    r["voh_min_V"], r["vol_max_V"] = min(hi), max(lo)
    r["se0_max_V"] = max(lvl("lp", se0[0] + 0.95), lvl("lm", se0[0] + 0.95))
    voh, vol = float(np.median(hi)), float(np.median(lo))
    a, b = vol + 0.1 * (voh - vol), vol + 0.9 * (voh - vol)
    # J/K transitions (excluding the first transition from idle and EOP)
    trs, tfs, ratios, vcrs, tcross = [], [], [], [], []
    for i in range(first + 1, se0[0]):
        if pins[i][1] == pins[i - 1][1]:
            continue
        te = t0 + i * tb
        win = (te - 0.3 * tb, te + 0.95 * tb)
        rise_w, fall_w = (jw, kw) if pins[i][1] else (kw, jw)
        ra = crossings(t, w[rise_w], a, *win, rising=True)
        rb = crossings(t, w[rise_w], b, *win, rising=True)
        fa = crossings(t, w[fall_w], b, *win, rising=False)
        fb = crossings(t, w[fall_w], a, *win, rising=False)
        if not (ra and rb and fa and fb):
            continue
        tr, tf = rb[0] - ra[0], fb[0] - fa[0]
        trs.append(tr)
        tfs.append(tf)
        ratios.append(tr / tf)
        x = crossings(t, w["lp"] - w["lm"], 0.0, *win)
        if x:
            tcross.append((i, x[0]))
            vcrs.append(float(np.interp(x[0], t, w["lp"])))
    r["n_edges"] = len(trs)
    r["tr_ns"] = [1e9 * min(trs), 1e9 * float(np.mean(trs)), 1e9 * max(trs)]
    r["tf_ns"] = [1e9 * min(tfs), 1e9 * float(np.mean(tfs)), 1e9 * max(tfs)]
    r["match_pct"] = [100 * min(ratios), 100 * float(np.mean(trs) / np.mean(tfs)), 100 * max(ratios)]
    r["vcrs_V"] = [min(vcrs), float(np.mean(vcrs)), max(vcrs)]
    # data jitter: differential crossings against the bit grid (common delay removed)
    dev = np.array([x - (t0 + i * tb) for i, x in tcross])
    r["delay_ns"] = 1e9 * float(np.mean(dev))
    r["jitter_pp_ns"] = 1e9 * float(dev.max() - dev.min())
    # paired transitions (TDJ2): spacing of crossings two transitions apart vs nominal
    # shoot-through: channel current that flows while both gates of a wire are above
    # threshold, min(I_N, I_P) with the square law of the models (saturation, the case's
    # threshold corner and temperature).  The terminal currents cannot show it: they
    # also carry the C_gd / C_ds displacement current of every edge.
    kn, kp_, vtn, vtp = 1.011, 0.1415, 1.03 + c.get("dvt_n", 0.0), 0.92 + c.get("dvt_p", 0.0)
    dT = c["temp"] - 27.0
    vtn -= 0.0022 * dT
    vtp -= 0.0022 * dT
    mob = ((c["temp"] + 273.15) / 300.15) ** -1.5
    st = []
    for s_ in ("p", "m"):
        i_n = 0.5 * kn * mob * np.maximum(w["gn" + s_] - vtn, 0.0) ** 2
        i_p = 0.5 * kp_ * mob * np.maximum(vdd - w["gp" + s_] - vtp, 0.0) ** 2
        st.append(np.minimum(i_n, i_p))
    st = np.maximum(st[0], st[1])
    r["crowbar_peak_mA"] = 1e3 * float(st.max())
    dt = np.diff(t)
    q = float(np.sum(0.5 * (st[1:] + st[:-1]) * dt))
    r["crowbar_q_per_edge_pC"] = 1e12 * q / max(len(trs), 1)
    # off-state gate excursion: N gate while its LVC output is low, P gate while high
    gmax = 0.0
    for g, lg, sign in (("gnp", "lgnp", 1), ("gnm", "lgnm", 1), ("gpp", "lgpp", -1), ("gpm", "lgpm", -1)):
        off = (w[lg] < 0.1 * vdd) if sign > 0 else (w[lg] > 0.9 * vdd)
        # settled: the LVC output has been in this state for > 30 % of a bit
        tch = np.array(crossings(t, w[lg], vdd / 2, 0.0, t[-1]) + [-1.0])
        last = np.array([tch[tch <= x].max() for x in t])
        off = off & (t - last > 0.3 * tb)
        vgs = w[g] if sign > 0 else vdd - w[g]
        m = off & (t > t0 + first * tb)
        if m.any():
            gmax = max(gmax, float(vgs[m].max()))
    r["off_vgs_max_V"] = gmax
    # EOP: SE0 width at the J wire (falls into SE0 or stays low, rises into J)
    up = crossings(t, w[jw], 0.5 * (voh + vol), t0 + (se0[-1] + 0.5) * tb, t0 + (se0[-1] + 1.8) * tb,
                   rising=True)
    dn = crossings(t, np.maximum(w["lp"], w["lm"]), 0.5 * (voh + vol), t0 + (se0[0] - 0.5) * tb,
                   t0 + (se0[0] + 0.8) * tb, rising=False)
    r["eop_se0_ns"] = 1e9 * (up[0] - dn[0]) if up and dn else None
    # receivers: comparator outputs are inverted (NOT line), sampled at 3/4 bit
    errs = 0
    for i in range(first, last_on + 1):
        oe, dat, s0 = pins[i]
        ts = t0 + (i + 0.75) * tb
        vp = float(np.interp(ts, t, w["cop"])) < vdd / 2
        vm = float(np.interp(ts, t, w["com"])) < vdd / 2
        rcv = float(np.interp(ts, t, w["cor"])) < vdd / 2
        exp_p = (not s0) and (dat != ls)
        exp_m = (not s0) and (dat == ls)
        errs += (vp != exp_p) + (vm != exp_m) + ((not s0) and (rcv != exp_p))
    r["rx_errors"] = int(errs)
    # over- / undershoot of the line during the packet (USB 2.0 figure 7-4 maximum input
    # waveform: -1.0 .. 4.6 V)
    m = (t > t0 + first * tb) & (t < t0 + (last_on + 1) * tb)
    r["line_max_V"] = float(max(w["lp"][m].max(), w["lm"][m].max()))
    r["line_min_V"] = float(min(w["lp"][m].min(), w["lm"][m].min()))
    r["vdd_ripple_mA_peak"] = 1e3 * float(np.max(np.abs(w["idrv"])))
    return r


def eval_zout(w, c, t0, tb):
    """Output impedance: line level change for the 0 -> iload current step."""
    t = w["t"]
    node = "l" + c["iload_node"][1]
    v1 = float(np.interp(c["t_iload"] - 5e-9, t, w[node]))
    v2 = float(np.interp(c["t_stop"] - 5e-9, t, w[node]))
    return dict(z_ohm=abs((v2 - v1) / c["iload"]), v_before=v1, v_after=v2)


# ------------------------------------------------------------------ cases
PAYLOAD_FS = [0x00, 0xFF, 0x55, 0x0F, 0xA5, 0x3C, 0x01, 0xFE]
PAYLOAD_LS = [0x00, 0xFF, 0x5A]


def case(ls=False, vdd=3.3, temp=27, cl=None, **kw):
    pins, line = fs_packet(PAYLOAD_LS if ls else PAYLOAD_FS, ls)
    tb = TB_LS if ls else TB_FS
    c = dict(ls=ls, vdd=vdd, temp=temp, cl=(50e-12 if cl is None else cl), pins=pins,
             t_stop=100e-9 + len(pins) * tb, tstep=(0.4e-9 if ls else 0.05e-9))
    c.update(kw)
    return c


def zout_case(state, wire, ls=False, temp=27):
    """state 'J'/'K', static; 10 mA drawn from (high wire) / pushed into (low wire)."""
    dat = 1 if state == "J" else 0
    pins = [(1, dat, 0)] * 30
    tb = TB_FS
    high = ("p" if (dat != ls) else "m")
    i = 10e-3 if wire == high else -10e-3
    c = dict(ls=ls, vdd=3.3, temp=temp, cl=50e-12, pins=pins, t_stop=100e-9 + 30 * tb, tstep=0.2e-9,
             iload=i, iload_node="l" + wire, t_iload=100e-9 + 15 * tb)
    return c


def task_list():
    T = [("fs_nom", case(), "pkt"), ("ls_50p", case(True, cl=50e-12), "pkt"),
         ("ls_600p", case(True, cl=600e-12), "pkt"),
         ("fs_nodiode", case(hs_diode=False), "pkt")]
    for vdd in (3.135, 3.465):
        for temp in (-40, 85):
            tag = "%g_%g" % (vdd, temp)
            T.append(("fs_" + tag, case(vdd=vdd, temp=temp), "pkt"))
            T.append(("ls50_" + tag, case(True, vdd=vdd, temp=temp, cl=50e-12), "pkt"))
            T.append(("ls600_" + tag, case(True, vdd=vdd, temp=temp, cl=600e-12), "pkt"))
    for nm, dn, dp in (("nlo_phi", -0.25, 0.2), ("nhi_plo", 0.2, -0.25),
                       ("nlo_plo", -0.25, -0.25), ("nhi_phi", 0.2, 0.2)):
        T.append(("fs_vt_" + nm, case(dvt_n=dn, dvt_p=dp), "pkt"))
        T.append(("ls50_vt_" + nm, case(True, cl=50e-12, dvt_n=dn, dvt_p=dp), "pkt"))
        T.append(("ls600_vt_" + nm, case(True, cl=600e-12, dvt_n=dn, dvt_p=dp), "pkt"))
    for k in (0.7, 1.3):
        T.append(("fs_cap%g" % k, case(capk=k), "pkt"))
        T.append(("ls50_cap%g" % k, case(True, cl=50e-12, capk=k), "pkt"))
        T.append(("ls600_cap%g" % k, case(True, cl=600e-12, capk=k), "pkt"))
    # receive mode: a host drives the line, the board's driver is off and isolated by the
    # FSUSB42 (OE# high): host edges at the connector, receiver outputs
    T.append(("fs_host", case(host=True), "pkt"))
    T.append(("ls_host", case(True, cl=50e-12, host=True), "pkt"))
    for st, wire in (("J", "p"), ("J", "m"), ("K", "p"), ("K", "m")):
        T.append(("zout_%s%s" % (st, wire), zout_case(st, wire), "zout"))
        T.append(("zout85_%s%s" % (st, wire), zout_case(st, wire, temp=85), "zout"))
    return T


KEEP_WAVE = ("fs_nom", "ls_50p", "ls_600p", "fs_nodiode")


def main():
    args = sys.argv[1:]
    force = "--force" in args
    flt = [a for a in args if not a.startswith("--")]
    os.makedirs(RES, exist_ok=True)
    sp = os.path.join(RES, "fsls_summary.json")
    summary = json.load(open(sp)) if os.path.exists(sp) else {}
    tasks = [t for t in task_list() if not flt or any(f in t[0] for f in flt)]
    jobs = int(os.environ.get("JOBS", "3"))

    def work(t):
        name, c, kind = t
        if name in summary and "error" not in summary[name] and not force:
            return name, summary[name]
        try:
            w, t0, tb = run(name, c)
            r = eval_zout(w, c, t0, tb) if kind == "zout" else evaluate(w, c, t0, tb)
        except Exception as e:                    # keep the other cases
            r = dict(error=repr(e))
        r.update(ls=c["ls"], vdd=c["vdd"], temp=c["temp"], cl_pF=c["cl"] * 1e12,
                 dvt_n=c.get("dvt_n", 0), dvt_p=c.get("dvt_p", 0), capk=c.get("capk", 1),
                 hs_diode=c.get("hs_diode", True))
        wf = os.path.join(RES, "fsls_" + name, "wave.txt")
        if not name.startswith(KEEP_WAVE) and os.path.exists(wf):
            os.remove(wf)
        print("%-22s %s" % (name, json.dumps(r)[:300]), flush=True)
        return name, r

    with ThreadPoolExecutor(jobs) as ex:
        for name, r in ex.map(work, tasks):
            summary[name] = r
            json.dump(summary, open(sp, "w"), indent=1)


if __name__ == "__main__":
    main()
