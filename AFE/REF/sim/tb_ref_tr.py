#!/usr/bin/env python3
"""tb_ref_tr.py - ngspice testbench of afe_ref_tr (reference / bias block, xh018)

Usage:
    python3 AFE/REF/sim/tb_ref_tr.py [cases] [--corner tm] [--temp 27] [--vdd 3.3]
            [--code auto|0..15] [--tag _x] [--netlist path]

Cases (default: all)
  op       operating point at the trim code: TX_VREF, RX_VREF, V(RBIAS),
           TX_I_5U, supply current; BIAS_EN = 0: off current
  trim     TX_VREF for every code 0..15 at 27 C: LSB, DNL, range; picks the
           code nearest 1.200 V ("--code auto" uses it in every other case)
  temp     -40 .. 125 C at VDD33 2.97 / 3.3 / 3.63 V, untrimmed (1000b) and
           trimmed: TX_VREF, RX_VREF, TX_I_5U, supply current
  line     VDD33 ramped 3.63 -> 1.8 V: line regulation, minimum supply
  psrr     VDD33 -> TX_VREF / RX_VREF / TX_I_5U, 10 Hz .. 100 MHz
  noise    TX_VREF and TX_I_5U noise density, rms 10 Hz .. 100 kHz / 10 MHz
  stab     loop gain of the bandgap, the gain stage A1, the TX buffer (0 / 10 / 100 pF)
           and the current loop A_I (RBIAS pin 0 / 20 / 100 pF)
  zout     TX_VREF output impedance (AC) and DC load regulation (+-10 uA)
  comply   TX_I_5U vs output voltage 0 .. VDD33: compliance, output resistance
  rbias    V(RBIAS), TX_I_5U vs RBIAS 6 .. 24 kOhm; RBIAS shorted / open
  start    BIAS_EN 0 -> 1 -> 0 (10 / 100 pF), VDD33 power-up with BIAS_EN = 1
  tran     VDD33 step 3.0 <-> 3.6 V in 1 us; 10 uA pulses into TX_VREF
           (TX -> RX isolation)
  offset   sensitivity of TX_VREF to a 1 mV offset of each amplifier
Results: build/ref/<corner>_<temp>_<vdd><tag>/results_<case>.json (+ CSV
windows); prints TEST PASSED / TEST FAILED.  Models: build/ldo/models
(AFE/LDO analog part/sim/xfab2ngspice_ldo.py; MOS + dp3 diode).
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DUT_DIR = os.path.dirname(HERE)
ROOT = os.path.abspath(os.path.join(DUT_DIR, "..", ".."))
MODELS = os.path.join(ROOT, "build", "ldo", "models")
CONVERTER = os.path.join(ROOT, "AFE", "LDO analog part", "sim", "xfab2ngspice_ldo.py")
NETLIST = os.path.join(DUT_DIR, "afe_ref_tr.sp")
OPTS = ".options method=gear reltol=1e-5 abstol=1e-13 vntol=1e-8 itl4=100 rshunt=1e13"
VREF = 1.200
I5 = 5e-6
TEMPS = [-40, -20, 0, 27, 50, 85, 105, 125]
CASES = ["op", "trim", "temp", "line", "psrr", "noise", "stab", "zout", "comply", "rbias", "start", "tran",
         "offset"]

LIMITS = {
    "vref_untrimmed": (1.140, 1.260),   # +-5 % before trim (3 sigma diode corners)
    "vref_trimmed": (1.188, 1.212),     # +-1 % after trim, -40 .. 125 C, 2.97 .. 3.63 V
    "lsb": (0.004, 0.010),              # V per code
    "trim_range": (0.035, 0.07),        # each side, fraction of VREF
    "tx_rx": 2e-3,                      # |TX_VREF - RX_VREF|
    "i5_err": 0.02,                     # TX_I_5U vs VREF / RBIAS / 20 (incl. RBIAS 1 %: not here)
    "idd_max": 320e-6,                  # -40..125 C, 2.97..3.63 V, incl. 100 uA in RBIAS and 5 uA out (core <= 215 uA)
    "ioff_max": 0.1e-6,
    "line_max": 5e-3,                   # V/V
    "psrr_1k_min": 40.0,                # dB (45 dB worst: wp 125 C)
    "pm_min": 45.0, "gm_min": 10.0,
    "t_settle_max": 10e-6,              # BIAS_EN -> 0.5 %, 10 pF (power sequencer BIAS_CYC = 10 us)
    "t_settle_max_100p": 12e-6,         # with 100 pF (slew-limited buffers): needs BIAS_CYC = 12 us
    "comply_min": 2.0,                  # V: TX_I_5U within 1 % from 0 V up to this
}


def lib(corner):
    p = os.path.join(MODELS, f"xh018_{corner}.lib")
    if not os.path.exists(p):
        subprocess.run(["python3", CONVERTER], check=True)
    return p


def run(path, text, timeout=3600):
    # op / ac / noise start from a transient operating point: the bandgap has a
    # second (zero-current) DC solution that its start-up only leaves in a
    # transient
    if re.search(r"^(op|ac |noise |dc )", text, re.M) and "\ntran " not in text and "ven en 0 dc 0\n" not in text:
        text = text.replace(".control\n", ".control\noptran 0 0 0 50n 200u 0\n", 1)
    open(path, "w").write(text)
    for d in re.findall(r"wrdata (\S+)", text):
        if os.path.exists(d):
            os.remove(d)
    r = subprocess.run(["ngspice", "-b", path], capture_output=True, text=True, timeout=timeout)
    open(path[:-3] + ".log", "w").write(r.stdout + r.stderr)
    return r.stdout


def vals(out):
    """name = value lines of ngspice print / let."""
    d = {}
    for m in re.finditer(r"^(\S+) = ([-+0-9.eE]+)\s*$", out, re.M):
        d[m.group(1)] = float(m.group(2))
    return d


def dut(a, title, code=None, vdd=None, temp=None, en="dc 1.8", rbias="12k", ctx="10p", crx="10p", vi5="dc 0.6",
        netlist=None):
    code = a.code if code is None else code
    vdd = a.vdd if vdd is None else vdd
    temp = a.temp if temp is None else temp
    bits = "\n".join(f"vt{k} tr{k} 0 dc {1.8 if (code >> k) & 1 else 0}" for k in range(4))
    ens = f"ven en 0 {en}" if not en.startswith("vdd") else "ven en vdd dc 0"
    return f"""* {title}
.include "{lib(a.corner)}"
.include "{netlist or a.netlist}"
.temp {temp}
vdd vdd 0 dc {vdd}
{ens}
{bits}
rb rbias 0 {rbias}
vo i5 0 {vi5}
ctx tx 0 {ctx}
crx rx 0 {crx}
x0 vdd 0 en tr0 tr1 tr2 tr3 rbias tx rx i5 afe_ref_tr
{OPTS}
"""


def load(path):
    a = np.loadtxt(path, ndmin=2)
    return a[:, 0], [a[:, i] for i in range(1, a.shape[1], 2)]


def cross(t, v, th, rising=True, after=0.0):
    s = v > th
    idx = np.nonzero((~s[:-1] & s[1:]) if rising else (s[:-1] & ~s[1:]))[0]
    idx = idx[t[idx] >= after]
    if not len(idx):
        return float("nan")
    i = idx[0]
    return float(t[i] + (th - v[i]) / (v[i + 1] - v[i]) * (t[i + 1] - t[i]))


def settle(t, v, final, tol, t0):
    """time after t0 from which |v - final| <= tol."""
    bad = np.nonzero((np.abs(v - final) > tol) & (t >= t0))[0]
    if not len(bad):
        return 0.0
    i = bad[-1]
    return float(t[min(i + 1, len(t) - 1)] - t0) if i + 1 < len(t) else float("nan")


def opv(a, out, name, **kw):
    pr = "print v(tx) v(rx) v(rbias) i(vo) i(vdd) v(x0.vrt) v(x0.vtap) v(x0.t8) v(x0.vcas)"
    o = run(os.path.join(out, name + ".sp"), dut(a, name, **kw) + f".control\nop\n{pr}\n.endc\n.end\n")
    v = vals(o)
    return {"tx": v.get("v(tx)", np.nan), "rx": v.get("v(rx)", np.nan), "vrb": v.get("v(rbias)", np.nan),
            "i5": v.get("i(vo)", np.nan), "idd": -v.get("i(vdd)", np.nan),
            "vrt": v.get("v(x0.vrt)", np.nan), "vtap": v.get("v(x0.vtap)", np.nan),
            "vbg8": v.get("v(x0.t8)", np.nan), "vcas": v.get("v(x0.vcas)", np.nan)}


def pmap(fn, items, jobs):
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(fn, items))


# ------------------------------------------------------------------ cases
def c_op(a, out):
    r = opv(a, out, "op")
    o = run(os.path.join(out, "op_off.sp"), dut(a, "off", en="dc 0") +
            ".control\nop\nprint i(vdd) v(tx) v(rx) i(vo)\n.endc\n.end\n")
    v = vals(o)
    r["ioff"] = -v.get("i(vdd)", np.nan)
    r["off_tx"], r["off_rx"], r["off_i5"] = v.get("v(tx)", np.nan), v.get("v(rx)", np.nan), v.get("i(vo)", np.nan)
    r["code"] = a.code
    print(f"  op (code {a.code:04b}): TX_VREF {r['tx']:.5f} V  RX_VREF {r['rx']:.5f} V  V(RBIAS) {r['vrb']:.5f} V  "
          f"TX_I_5U {r['i5'] * 1e6:.4f} uA  IDD {r['idd'] * 1e6:.1f} uA (core {(r['idd'] - 105e-6) * 1e6:.1f} uA)  "
          f"VBG(1000b) {r['vbg8']:.4f} V  vcas {r['vcas']:.3f} V;  off: {r['ioff'] * 1e9:.2f} nA")
    return r


def c_trim(a, out):
    rs = pmap(lambda c: opv(a, out, f"trim_{c}", code=c, temp=27), range(16), a.jobs)
    v = np.array([r["tx"] for r in rs])
    d = np.diff(v)
    best = int(np.argmin(np.abs(v - VREF)))
    r = {"code": list(range(16)), "tx": v.tolist(), "rx": [x["rx"] for x in rs], "i5": [x["i5"] for x in rs],
         "lsb": float(d.mean()), "dnl": (d / d.mean() - 1).tolist(), "best": best,
         "range_lo": float(1 - v[0] / v[8]), "range_hi": float(v[15] / v[8] - 1), "v8": float(v[8])}
    print(f"  trim: code 1000b {v[8]:.5f} V, LSB {r['lsb'] * 1e3:.2f} mV ({r['lsb'] / v[8] * 100:.3f} %), DNL "
          f"{min(r['dnl']):+.3f} .. {max(r['dnl']):+.3f}, range -{r['range_lo'] * 100:.2f} / +{r['range_hi'] * 100:.2f} %; "
          f"best code {best:04b}: {v[best]:.5f} V")
    return r


def c_temp(a, out):
    codes = sorted({8, a.code})
    items = [(c, vd, t) for c in codes for vd in (2.97, 3.3, 3.63) for t in TEMPS]
    rs = pmap(lambda x: opv(a, out, f"temp_{x[0]}_{x[1]}_{x[2]}", code=x[0], vdd=x[1], temp=x[2]), items, a.jobs)
    r = {"temps": TEMPS, "codes": codes, "data": {}}
    for (c, vd, t), x in zip(items, rs):
        r["data"].setdefault(f"{c}_{vd}", {k: [] for k in ("tx", "rx", "i5", "idd", "vbg8")})
        for k in ("tx", "rx", "i5", "idd", "vbg8"):
            r["data"][f"{c}_{vd}"][k].append(x[k])
    for c in codes:
        allv = np.concatenate([r["data"][f"{c}_{vd}"]["tx"] for vd in (2.97, 3.3, 3.63)])
        tx = np.array(r["data"][f"{c}_3.3"]["tx"])
        tc = (tx.max() - tx.min()) / tx.mean() / (TEMPS[-1] - TEMPS[0]) * 1e6
        i5 = np.concatenate([r["data"][f"{c}_{vd}"]["i5"] for vd in (2.97, 3.3, 3.63)])
        r[f"min_{c}"], r[f"max_{c}"], r[f"tc_{c}"] = float(allv.min()), float(allv.max()), float(tc)
        r[f"i5min_{c}"], r[f"i5max_{c}"] = float(i5.min()), float(i5.max())
        rxd = np.concatenate([np.array(r["data"][f"{c}_{vd}"]["rx"]) - np.array(r["data"][f"{c}_{vd}"]["tx"])
                              for vd in (2.97, 3.3, 3.63)])
        r[f"txrx_{c}"] = float(np.abs(rxd).max())
        idd = np.concatenate([r["data"][f"{c}_{vd}"]["idd"] for vd in (2.97, 3.3, 3.63)])
        r[f"iddmax_{c}"] = float(idd.max())
        print(f"  temp code {c:04b}: TX_VREF {allv.min():.5f} .. {allv.max():.5f} V "
              f"({(allv.min() / VREF - 1) * 100:+.2f} / {(allv.max() / VREF - 1) * 100:+.2f} %), {tc:.1f} ppm/K box (3.3 V); "
              f"TX_I_5U {i5.min() * 1e6:.3f} .. {i5.max() * 1e6:.3f} uA; |RX-TX| <= {r[f'txrx_{c}'] * 1e3:.2f} mV; "
              f"IDD <= {idd.max() * 1e6:.0f} uA")
    return r


def c_line(a, out):
    name = "line"
    d = os.path.join(out, name + ".dat")
    body = dut(a, name).replace(f"vdd vdd 0 dc {a.vdd}", "vdd vdd 0 pwl(0 3.63 100u 3.63 1.1m 1.8 2 1.8)")
    run(os.path.join(out, name + ".sp"), body + f".control\ntran 50n 1.1m 0 1u\n"
        f"wrdata {d} v(vdd) v(tx) v(rx) i(vo)\n.endc\n.end\n")
    t, (vd, tx, rx, i5) = load(d)
    m = (t > 100e-6)
    vd, tx, rx, i5 = vd[m], tx[m], rx[m], i5[m]
    s = (vd >= 2.97) & (vd <= 3.63)
    k = np.polyfit(vd[s], tx[s], 1)[0]
    ref = np.interp(3.3, vd[::-1], tx[::-1])
    bad = np.nonzero(np.abs(tx - ref) > 0.005 * ref)[0]
    vmin = float(vd[bad[0]]) if len(bad) else float(vd.min())
    i5r = np.interp(3.3, vd[::-1], i5[::-1])
    badi = np.nonzero(np.abs(i5 - i5r) > 0.01 * i5r)[0]
    vmini = float(vd[badi[0]]) if len(badi) else float(vd.min())
    r = {"vdd": vd[::20].tolist(), "tx": tx[::20].tolist(), "rx": rx[::20].tolist(), "i5": i5[::20].tolist(),
         "line_reg": float(k), "vmin": vmin, "vmin_i5": vmini,
         "i5_line": float(np.polyfit(vd[s], i5[s], 1)[0] / i5r)}
    print(f"  line: {k * 1e3:+.3f} mV/V (2.97 .. 3.63 V); TX_VREF within 0.5 % down to VDD33 = {vmin:.2f} V, "
          f"TX_I_5U within 1 % down to {vmini:.2f} V ({r['i5_line'] * 100:+.3f} %/V)")
    return r


def c_psrr(a, out):
    name = "psrr"
    d = os.path.join(out, name + ".dat")
    body = dut(a, name).replace(f"vdd vdd 0 dc {a.vdd}", f"vdd vdd 0 dc {a.vdd} ac 1")
    run(os.path.join(out, name + ".sp"), body + f".control\nac dec 20 10 100meg\n"
        f"wrdata {d} v(tx) v(rx) i(vo)\n.endc\n.end\n")
    a_ = np.loadtxt(d, ndmin=2)
    f = a_[:, 0]
    tx = np.hypot(a_[:, 1], a_[:, 2])
    rx = np.hypot(a_[:, 4], a_[:, 5])
    i5 = np.hypot(a_[:, 7], a_[:, 8])
    ptx, prx = -20 * np.log10(tx), -20 * np.log10(rx)
    pi5 = 20 * np.log10(i5 / I5)          # dB re 1 (relative current change per V)
    at = lambda y, fx: float(np.interp(np.log10(fx), np.log10(f), y))  # noqa: E731
    r = {"f": f.tolist(), "tx": ptx.tolist(), "rx": prx.tolist(), "i5": pi5.tolist(),
         **{f"tx_{k}": at(ptx, v) for k, v in (("100", 100), ("1k", 1e3), ("10k", 1e4), ("100k", 1e5), ("1M", 1e6),
                                                ("10M", 1e7))},
         "tx_min": float(ptx.min()), "tx_fmin": float(f[np.argmin(ptx)]),
         "i5_1k": at(pi5, 1e3), "i5_1M": at(pi5, 1e6)}
    print(f"  psrr TX_VREF: {r['tx_100']:.1f} / {r['tx_1k']:.1f} / {r['tx_100k']:.1f} / {r['tx_1M']:.1f} / "
          f"{r['tx_10M']:.1f} dB at 100 Hz / 1k / 100k / 1M / 10M, minimum {r['tx_min']:.1f} dB at "
          f"{r['tx_fmin'] / 1e3:.0f} kHz; TX_I_5U {r['i5_1k']:.1f} dB(1/V) at 1 kHz, {r['i5_1M']:.1f} at 1 MHz")
    return r


def c_noise(a, out):
    res = {}
    for nm, node, src in (("tx", "v(tx)", "vdd"), ("i5", "v(nz)", "vdd")):
        d = os.path.join(out, f"noise_{nm}.dat")
        body = dut(a, "noise " + nm).replace(f"vdd vdd 0 dc {a.vdd}", f"vdd vdd 0 dc {a.vdd} ac 1")
        if nm == "i5":   # current noise: TX_I_5U into 0.6 V through a 0 V source, sensed by a CCVS
            body = body.replace("vo i5 0 dc 0.6", "vo i5 i5s dc 0\nvo2 i5s 0 dc 0.6\nhz nz 0 vo 1")
        run(os.path.join(out, f"noise_{nm}.sp"), body + f".control\nnoise {node} {src} dec 20 1 10meg\n"
            f"setplot noise1\nwrdata {d} onoise_spectrum\n.endc\n.end\n")
        a_ = np.loadtxt(d, ndmin=2)
        f, s = a_[:, 0], a_[:, 1]
        def rms(f1, f2):
            m = (f >= f1) & (f <= f2)
            return float(np.sqrt(np.trapz(s[m] ** 2, f[m])))
        res[nm] = {"f": f.tolist(), "s": s.tolist(), "rms_10_100k": rms(10, 1e5), "rms_10_10M": rms(10, 1e7),
                   "at_1k": float(np.interp(1e3, f, s)), "at_100k": float(np.interp(1e5, f, s))}
    t, i = res["tx"], res["i5"]
    print(f"  noise TX_VREF: {t['at_1k'] * 1e9:.0f} nV/rtHz at 1 kHz, {t['at_100k'] * 1e9:.0f} at 100 kHz, "
          f"{t['rms_10_100k'] * 1e6:.1f} uV rms (10 Hz-100 kHz), {t['rms_10_10M'] * 1e6:.1f} uV rms (10 Hz-10 MHz); "
          f"TX_I_5U {i['at_1k'] * 1e12:.2f} pA/rtHz at 1 kHz, {i['rms_10_100k'] * 1e9:.2f} nA rms (10 Hz-100 kHz)")
    return res


def loopgain(f, t):
    g = 20 * np.log10(np.abs(t))
    ph = np.degrees(np.unwrap(np.angle(t)))
    i = np.nonzero((g[:-1] > 0) & (g[1:] <= 0))[0]
    fc = pm = float("nan")
    if len(i):
        k = i[0]
        fc = float(np.interp(0, [g[k + 1], g[k]], [f[k + 1], f[k]]))
        pm = float(180 + np.interp(0, [g[k + 1], g[k]], [ph[k + 1], ph[k]]))
    j = np.nonzero((ph[:-1] > -180) & (ph[1:] <= -180) & (f[:-1] > (fc if np.isfinite(fc) else 0)))[0]
    gm = float(-np.interp(-180, [ph[j[0] + 1], ph[j[0]]], [g[j[0] + 1], g[j[0]]])) if len(j) else 99.0
    return {"f": f.tolist(), "g": g.tolist(), "ph": ph.tolist(), "dc": float(g[0]), "fc": fc, "pm": pm, "gm": gm}


def c_stab(a, out):
    cfgs = [("bg", "vinjb", "x0.o1", "x0.o1g", "10p", "0"), ("a1", "vinja", "x0.fbn", "x0.fbe", "10p", "0"), ("tx0", "vinjt", "tx", "x0.ftx", "0.01p", "0"),
            ("tx10", "vinjt", "tx", "x0.ftx", "10p", "0"), ("tx100", "vinjt", "tx", "x0.ftx", "100p", "0"),
            ("i0", "vinji", "rbias", "x0.rbf", "10p", "0.01p"), ("i20", "vinji", "rbias", "x0.rbf", "10p", "20p"),
            ("i100", "vinji", "rbias", "x0.rbf", "10p", "100p")]

    def one(c):
        nm, src, n1, n2, ct, cr = c
        d = os.path.join(out, f"stab_{nm}.dat")
        body = dut(a, "stab " + nm, ctx=ct) + f"crb rbias 0 {cr}\n"
        net = open(a.netlist).read()
        pat = {"vinja": "vinja fbn fbe 0", "vinjt": "vinjt TX_VREF ftx 0", "vinji": "vinji RBIAS rbf 0",
               "vinjb": "vinjb o1 o1g 0"}[src]
        np_ = os.path.join(out, f"net_{src}.sp")
        open(np_, "w").write(net.replace(pat, pat + " ac 1"))
        body = body.replace(f'.include "{a.netlist}"', f'.include "{np_}"')
        run(os.path.join(out, f"stab_{nm}.sp"), body + f".control\nac dec 40 10 1g\n"
            f"let t = -v({n1})/v({n2})\nwrdata {d} real(t) imag(t)\n.endc\n.end\n")
        x = np.loadtxt(d, ndmin=2)
        return nm, loopgain(x[:, 0], x[:, 1] + 1j * x[:, 3])

    r = dict(pmap(one, cfgs, a.jobs))
    for nm, x in r.items():
        print(f"  stab {nm:5s}: DC {x['dc']:5.1f} dB, crossover {x['fc'] / 1e3:9.1f} kHz, PM {x['pm']:5.1f} deg, "
              f"GM {x['gm']:5.1f} dB")
    return r


def c_zout(a, out):
    d = os.path.join(out, "zout.dat")
    body = dut(a, "zout") + "iz 0 tx dc 0 ac 1\n"
    run(os.path.join(out, "zout.sp"), body + f".control\nac dec 20 10 100meg\nwrdata {d} v(tx) v(rx)\n.endc\n.end\n")
    x = np.loadtxt(d, ndmin=2)
    f, z, zx = x[:, 0], np.hypot(x[:, 1], x[:, 2]), np.hypot(x[:, 4], x[:, 5])
    # DC load: +-10 uA into / out of TX_VREF
    def dcl(il):
        nm = f"zload_{il}"
        o = run(os.path.join(out, nm + ".sp"), dut(a, nm) + f"il tx 0 dc {il}\n.control\nop\nprint v(tx) v(rx)\n.endc\n.end\n")
        v = vals(o)
        return v.get("v(tx)", np.nan), v.get("v(rx)", np.nan)
    loads = [-10e-6, -1e-6, 0, 1e-6, 10e-6]
    dv = pmap(dcl, loads, a.jobs)
    v0 = dv[2][0]
    r = {"f": f.tolist(), "z": z.tolist(), "z_rx": zx.tolist(), "z_100": float(np.interp(2, np.log10(f), z)),
         "z_1M": float(np.interp(6, np.log10(f), z)), "loads": loads, "tx": [x[0] for x in dv],
         "rx": [x[1] for x in dv], "rdc_src": float((dv[4][0] - v0) / -10e-6), "rdc_sink": float((dv[0][0] - v0) / 10e-6),
         "xtalk_dc": float(abs(dv[4][1] - dv[2][1]))}
    print(f"  zout TX_VREF: {r['z_100'] / 1e3:.2f} kOhm at 100 Hz, {r['z_1M'] / 1e3:.2f} kOhm at 1 MHz; DC: "
          f"{r['tx'][4] - v0:+.4f} V at 10 uA out, {r['tx'][0] - v0:+.4f} V at 10 uA in; RX shift "
          f"{r['xtalk_dc'] * 1e6:.1f} uV")
    return r


def c_comply(a, out):
    d = os.path.join(out, "comply.dat")
    # slow ramp of the output voltage (the bandgap needs a transient start)
    body = dut(a, "comply", vi5=f"pwl(0 0.6 40u 0.6 60u 0 1.06m {a.vdd} 1 {a.vdd})")
    run(os.path.join(out, "comply.sp"), body + f".control\ntran 100n 1.06m 0 1u\nwrdata {d} v(i5) i(vo)\n.endc\n.end\n")
    t, (v, i) = load(d)
    m = t > 60e-6
    v, i = v[m], np.abs(i[m])
    i06 = float(np.interp(0.6, v, i))
    ok = np.abs(i / i06 - 1) <= 0.01
    vmax = float(v[np.nonzero(~ok & (v > 0.6))[0][0]]) if np.any(~ok & (v > 0.6)) else float(v[-1])
    s = (v >= 0.2) & (v <= 1.8)
    rout = float(1 / abs(np.polyfit(v[s], i[s], 1)[0]))
    r = {"v": v.tolist(), "i": i.tolist(), "i_06": i06, "vmax": vmax, "rout": rout,
         "i_0": float(i[0]), "i_2": float(np.interp(2.0, v, i))}
    print(f"  comply: TX_I_5U {i06 * 1e6:.4f} uA at 0.6 V, within 1 % from 0 to {vmax:.2f} V, Rout {rout / 1e6:.0f} MOhm "
          f"(0.2 .. 1.8 V)")
    return r


def c_rbias(a, out):
    rbs = [6e3, 8e3, 10e3, 11.88e3, 12e3, 12.12e3, 14e3, 18e3, 24e3]
    rs = pmap(lambda rb: opv(a, out, f"rbias_{rb:g}", rbias=f"{rb:g}"), rbs, a.jobs)
    flt = [opv(a, out, "rbias_short", rbias="1"), opv(a, out, "rbias_open", rbias="1g")]
    r = {"rbias": rbs, "vrb": [x["vrb"] for x in rs], "i5": [x["i5"] for x in rs], "idd": [x["idd"] for x in rs],
         "ratio": [x["i5"] * rb * 20 / x["tx"] for x, rb in zip(rs, rbs)],
         "short_i5": flt[0]["i5"], "short_idd": flt[0]["idd"], "open_i5": flt[1]["i5"], "open_idd": flt[1]["idd"],
         "open_tx": flt[1]["tx"], "short_tx": flt[0]["tx"]}
    print(f"  rbias: I5 x RBIAS x 20 / VREF = {min(r['ratio']):.4f} .. {max(r['ratio']):.4f} for 6 .. 24 kOhm; "
          f"short: TX_I_5U {r['short_i5'] * 1e6:.1f} uA, IDD {r['short_idd'] * 1e3:.2f} mA; open: "
          f"TX_I_5U {r['open_i5'] * 1e9:.1f} nA, TX_VREF {r['open_tx']:.4f} V")
    return r


def c_start(a, out):
    res = {}
    for nm, ct in (("en10", "10p"), ("en100", "100p")):
        d = os.path.join(out, f"start_{nm}.dat")
        body = dut(a, nm, en="pwl(0 0 2u 0 2.01u 1.8 40u 1.8 40.01u 0 1 0)", ctx=ct, crx=ct)
        run(os.path.join(out, f"start_{nm}.sp"), body + f".control\ntran 5n 60u 0 20n\n"
            f"wrdata {d} v(tx) v(rx) i(vo) i(vdd) v(x0.t8)\n.endc\n.end\n")
        t, (tx, rx, i5, idd, vbg) = load(d)
        i5 = np.abs(i5)
        m = (t > 30e-6) & (t < 39e-6)
        ftx, frx, fi5 = tx[m].mean(), rx[m].mean(), i5[m].mean()
        x = {"t": t[::4].tolist(), "tx": tx[::4].tolist(), "rx": rx[::4].tolist(), "i5": i5[::4].tolist(),
             "idd": (-idd[::4]).tolist(),
             "t_tx_05": settle(t[t < 40e-6], tx[t < 40e-6], ftx, 0.005 * ftx, 2e-6),
             "t_tx_01": settle(t[t < 40e-6], tx[t < 40e-6], ftx, 0.001 * ftx, 2e-6),
             "t_rx_05": settle(t[t < 40e-6], rx[t < 40e-6], frx, 0.005 * frx, 2e-6),
             "t_i5_1": settle(t[t < 40e-6], i5[t < 40e-6], fi5, 0.01 * fi5, 2e-6),
             "overshoot": float(max(tx.max(), rx.max()) - ftx),
             "t_off": cross(t, tx, 0.1 * ftx, rising=False, after=40e-6) - 40e-6,
             "peak_idd": float((-idd).max())}
        res[nm] = x
        print(f"  start {nm}: TX_VREF 0.5 % in {x['t_tx_05'] * 1e6:.2f} us, 0.1 % in {x['t_tx_01'] * 1e6:.2f} us; "
              f"RX_VREF 0.5 % in {x['t_rx_05'] * 1e6:.2f} us; TX_I_5U 1 % in {x['t_i5_1'] * 1e6:.2f} us; overshoot "
              f"{x['overshoot'] * 1e3:.1f} mV; off (10 %) {x['t_off'] * 1e9:.0f} ns; peak IDD {x['peak_idd'] * 1e6:.0f} uA")
    d = os.path.join(out, "start_pwr.dat")
    body = dut(a, "pwr", en="vdd").replace(f"vdd vdd 0 dc {a.vdd}", f"vdd vdd 0 pwl(0 0 20u {a.vdd} 1 {a.vdd})")
    run(os.path.join(out, "start_pwr.sp"), body + f".control\ntran 5n 80u 0 20n\nwrdata {d} v(vdd) v(tx) v(rx) i(vo)\n"
        f".endc\n.end\n")
    t, (vd, tx, rx, i5) = load(d)
    ftx = tx[t > 70e-6].mean()
    res["pwr"] = {"t": t[::4].tolist(), "vdd": vd[::4].tolist(), "tx": tx[::4].tolist(), "rx": rx[::4].tolist(),
                  "i5": np.abs(i5[::4]).tolist(),
                  "t_tx_05": settle(t, tx, ftx, 0.005 * ftx, 20e-6), "overshoot": float(tx.max() - ftx)}
    print(f"  start pwr (VDD33 0 -> {a.vdd} V in 20 us, BIAS_EN = VDD33): TX_VREF 0.5 % {res['pwr']['t_tx_05'] * 1e6:.2f} us "
          f"after VDD33 is up, overshoot {res['pwr']['overshoot'] * 1e3:.1f} mV")
    return res


def c_tran(a, out):
    res = {}
    d = os.path.join(out, "tran_line.dat")
    body = dut(a, "line step").replace(f"vdd vdd 0 dc {a.vdd}",
                                       "vdd vdd 0 pwl(0 3.0 20u 3.0 21u 3.6 60u 3.6 61u 3.0 1 3.0)")
    run(os.path.join(out, "tran_line.sp"), body + f".control\ntran 5n 100u 0 10n\nwrdata {d} v(tx) v(rx) i(vo)\n"
        f".endc\n.end\n")
    t, (tx, rx, i5) = load(d)
    b = tx[(t > 15e-6) & (t < 20e-6)].mean()
    m1, m2 = (t > 20e-6) & (t < 60e-6), (t > 60e-6)
    res["line"] = {"t": t[::2].tolist(), "tx": tx[::2].tolist(), "rx": rx[::2].tolist(), "i5": np.abs(i5[::2]).tolist(),
                   "up": float(np.abs(tx[m1] - b).max()), "down": float(np.abs(tx[m2] - b).max()),
                   "i5_dev": float(np.abs(np.abs(i5[(t > 20e-6)]) / np.abs(i5[(t > 15e-6) & (t < 20e-6)]).mean() - 1).max())}
    d = os.path.join(out, "tran_kick.dat")
    body = dut(a, "kick") + "ik 0 tx pulse(0 10u 20u 10n 10n 2u 10u 3)\n"
    run(os.path.join(out, "tran_kick.sp"), body + f".control\ntran 2n 60u 0 5n\nwrdata {d} v(tx) v(rx)\n.endc\n.end\n")
    t, (tx, rx) = load(d)
    b, br = tx[(t > 15e-6) & (t < 20e-6)].mean(), rx[(t > 15e-6) & (t < 20e-6)].mean()
    res["kick"] = {"t": t[::2].tolist(), "tx": tx[::2].tolist(), "rx": rx[::2].tolist(),
                   "tx_dev": float(np.abs(tx[t > 20e-6] - b).max()), "rx_dev": float(np.abs(rx[t > 20e-6] - br).max())}
    print(f"  tran: VDD33 3.0 -> 3.6 V step: TX_VREF {res['line']['up'] * 1e3:.2f} mV / {res['line']['down'] * 1e3:.2f} mV peak, "
          f"TX_I_5U {res['line']['i5_dev'] * 100:.2f} %; 10 uA pulses into TX_VREF (10 pF): TX {res['kick']['tx_dev'] * 1e3:.1f} mV, "
          f"RX {res['kick']['rx_dev'] * 1e6:.1f} uV")
    return res


def c_offset(a, out):
    net = open(a.netlist).read()
    cases = {
        "bandgap op-amp (MA1)": ("xma1 m1 a tlb tlb pe3i", "xma1 m1 aos tlb tlb pe3i", "vos aos a dc 1m"),
        "gain stage A1 (MGA_B)": ("xga_b o1a vtap ta ta", "xga_b o1a vtapo ta ta", "vos vtapo vtap dc 1m"),
        "TX buffer (B_TX)": ("xbt vrt ftx TX_VREF", "xbt vrto ftx TX_VREF", "vos vrto vrt dc 1m"),
        "current OTA A_I": ("xai vrt rbf gf", "xai vrto2 rbf gf", "vos vrto2 vrt dc 1m"),
        "R2 string +1 %": ("r2b t0 cd 84.04k", "r2b t0 cd 84.88k", ""),
        "R1 +1 %": ("r1 b bd 10.8k", "r1 b bd 10.908k", ""),
        "D2 area +1 %": ("xd2 bd GND dp3 area=800p perimeter=320u", "xd2 bd GND dp3 area=808p perimeter=323.2u", ""),
        "MP2 / MP1 current +1 %": ("xmp2 b pg VDD33 VDD33 pe3i w=8u l=4u", "xmp2 b pg VDD33 VDD33 pe3i w=8.08u l=4u",
                                   ""),
    }
    base = opv(a, out, "off_base")

    def one(item):
        k, (s1, s2, extra) = item
        assert s1 in net, s1
        p = os.path.join(out, "net_off_" + re.sub(r"\W+", "_", k) + ".sp")
        n2 = net.replace(s1, s2)
        if extra:
            n2 = n2.replace(".ends afe_ref_tr", extra + "\n.ends afe_ref_tr")
        open(p, "w").write(n2)
        x = opv(a, out, "off_" + re.sub(r"\W+", "_", k), netlist=p)
        return k, {"dtx": x["tx"] - base["tx"], "di5": x["i5"] / base["i5"] - 1}

    r = dict(pmap(one, list(cases.items()), a.jobs))
    for k, x in r.items():
        print(f"  offset {k:24s}: TX_VREF {x['dtx'] * 1e3:+.3f} mV, TX_I_5U {x['di5'] * 100:+.3f} %")
    return r


FUN = {k: globals()["c_" + k] for k in CASES}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="*")
    ap.add_argument("--corner", default="tm")
    ap.add_argument("--temp", type=float, default=27)
    ap.add_argument("--vdd", type=float, default=3.3)
    ap.add_argument("--code", default="auto")
    ap.add_argument("--tag", default="")
    ap.add_argument("--netlist", default=NETLIST)
    a = ap.parse_args()
    a.jobs = int(os.environ.get("JOBS", "2"))
    a.temp = int(a.temp) if a.temp == int(a.temp) else a.temp
    cases = a.cases or CASES
    out = os.path.join(ROOT, "build", "ref", f"{a.corner}_{a.temp:g}_{a.vdd:g}{a.tag}")
    os.makedirs(out, exist_ok=True)
    print(f"afe_ref_tr: corner {a.corner}, {a.temp} C, VDD33 {a.vdd} V, RBIAS 12 kOhm ({os.path.basename(a.netlist)})")
    R = {}
    if a.code == "auto":
        a.code = 8
        R["trim"] = FUN["trim"](a, out)
        a.code = R["trim"]["best"]
    else:
        a.code = int(a.code)
    for c in cases:
        if c == "trim" and "trim" in R:
            continue
        R[c] = FUN[c](a, out)
    for c, r in R.items():
        json.dump(r, open(os.path.join(out, f"results_{c}.json"), "w"))
    json.dump({"code": a.code}, open(os.path.join(out, "code.json"), "w"))

    L, err = LIMITS, []

    def rng(name, v, lo, hi):
        if not (np.isfinite(v) and lo <= v <= hi):
            err.append(f"{name} = {v:.4g} outside {lo:.4g} .. {hi:.4g}")

    if "trim" in R:
        t = R["trim"]
        rng("TX_VREF code 1000b", t["v8"], *L["vref_untrimmed"])
        rng("LSB", t["lsb"], *L["lsb"])
        rng("trim range low", t["range_lo"], *L["trim_range"])
        rng("trim range high", t["range_hi"], *L["trim_range"])
        rng("DNL", max(abs(x) for x in t["dnl"]), 0, 0.5)
    if "op" in R:
        o = R["op"]
        rng("TX_VREF trimmed", o["tx"], *L["vref_trimmed"])
        rng("|TX - RX|", abs(o["tx"] - o["rx"]), 0, L["tx_rx"])
        rng("TX_I_5U error", abs(o["i5"] / (o["vrb"] / 12e3 / 20) - 1), 0, L["i5_err"])
        rng("IDD", o["idd"], 0, L["idd_max"])
        rng("I_off", o["ioff"], -1e-9, L["ioff_max"])
    if "temp" in R:
        rng("TX_VREF trimmed min (T, VDD)", R["temp"][f"min_{a.code}"], *L["vref_trimmed"])
        rng("TX_VREF trimmed max (T, VDD)", R["temp"][f"max_{a.code}"], *L["vref_trimmed"])
        rng("|RX - TX| (T, VDD)", R["temp"][f"txrx_{a.code}"], 0, L["tx_rx"])
        rng("IDD max (T, VDD)", R["temp"][f"iddmax_{a.code}"], 0, L["idd_max"])
    if "line" in R:
        rng("line regulation", abs(R["line"]["line_reg"]), 0, L["line_max"])
        rng("minimum VDD33", R["line"]["vmin"], 0, 2.97)
    if "psrr" in R:
        rng("PSRR 1 kHz", R["psrr"]["tx_1k"], L["psrr_1k_min"], 300)
    if "stab" in R:
        for k, x in R["stab"].items():
            rng(f"phase margin {k}", x["pm"], L["pm_min"], 180)
            rng(f"gain margin {k}", x["gm"], L["gm_min"], 300)
    if "comply" in R:
        rng("TX_I_5U compliance", R["comply"]["vmax"], L["comply_min"], 5)
    if "start" in R:
        for k in ("en10", "en100"):
            lim = L["t_settle_max_100p"] if k == "en100" else L["t_settle_max"]
            rng(f"settling {k}", R["start"][k]["t_tx_05"], 0, lim)
            rng(f"settling RX {k}", R["start"][k]["t_rx_05"], 0, lim)
            rng(f"settling I5 {k}", R["start"][k]["t_i5_1"], 0, L["t_settle_max"])
    for e in err:
        print("  ERROR:", e)
    print("TEST PASSED" if not err else f"TEST FAILED: {len(err)} error(s)")


if __name__ == "__main__":
    main()
