#!/usr/bin/env python3
"""tb_ldo_tr.py - ngspice testbench of afe_ldo_tr (3.3 V -> 1.8 V LDO, xh018)

Usage:
    python3 "AFE/LDO analog part/sim/tb_ldo_tr.py" [cases] [--corner tm] [--temp 27]
            [--vin 3.3] [--cout 1e-6] [--esr 0.01] [--tag _x] [--netlist path]

Cases (default: op temp line load ac psrr zout noise start uvlo step line_step en short)
  op        operating point at no load, 20 mA and LDO_EN = 0: VOUT, VBG,
            quiescent / ground current, off current
  temp      VBG and VOUT from -40 to 125 C (DC, 5 mA)
  line      VOUT vs VIN 2.0 .. 3.63 V at 1 / 20 mA: line regulation, dropout
  load      VOUT vs load 0 .. 100 mA at VIN 3.3 V and 2.97 V: load
            regulation, current limit
  ac        loop gain (voltage injection at the feedback node, vinj in the
            netlist) at 0 / 10 u / 100 u / 1 m / 5 m / 20 m / 50 mA: crossover,
            phase margin, gain margin
  psrr      VOUT / VIN at 1 / 20 mA, 10 Hz .. 100 MHz
  zout      output impedance at 1 / 20 mA
  noise     output noise density and 10 Hz .. 100 kHz rms at 5 mA
  start     VIN 0 -> 3.3 V in 100 us, LDO_EN tied to VIN, 5 mA: UVLO
            release, soft start, PWR_GOOD / POR_N delays, inrush
  uvlo      VIN 3.3 -> 2.0 -> 3.3 V slowly (1 V/ms), 5 mA: UVLO and
            power-good thresholds with hysteresis
  step      load 1 -> 20 -> 1 mA in 1 us: undershoot, overshoot, settling
  line_step VIN 3.0 -> 3.6 -> 3.0 V in 1 us at 5 mA
  en        LDO_EN 0 -> 1 -> 0 -> 1 at VIN 3.3 V, 5 mA: soft start, delays,
            discharge
  short     load steps from 5 mA to a 1 Ohm short and back: current limit,
            recovery
Results: build/ldo/<corner>_<temp>_<vin><tag>/results_<case>.json and CSV
windows; prints TEST PASSED / TEST FAILED.  Models: build/ldo/models
(sim/xfab2ngspice_ldo.py).
"""
import argparse
import concurrent.futures as cf
import json
import math
import os
import re
import subprocess

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DUT_DIR = os.path.dirname(HERE)
ROOT = os.path.abspath(os.path.join(DUT_DIR, "..", ".."))
MODELS = os.path.join(ROOT, "build", "ldo", "models")
NETLIST = os.path.join(DUT_DIR, "afe_ldo_tr.sp")
OPTS = ".options method=gear reltol=1e-4 abstol=1e-12 vntol=1e-7 itl4=100 rshunt=1e12"
VNOM = 1.8
# The bandgap has a second, zero-current DC solution (its start-up branch only
# acts in a transient); DC analyses start from the regulated state instead.
NODESET = (".nodeset v(x0.vbg)=1.19 v(x0.a)=0.71 v(x0.b)=0.71 v(x0.bd)=0.66 v(x0.cd)=0.71 "
           "v(x0.vr)=1.19 v(vout)=1.8 v(x0.fb)=1.19 v(x0.fbe)=1.19 v(x0.pg)=2.3 v(x0.sg)=0.02 "
           "v(x0.o1)=0.86 v(x0.m1)=0.86 v(x0.nb)=0.86 v(x0.eo)=1.9 v(x0.gp)=2.8 v(x0.ed)=2.3 v(x0.ea)=2.3 "
           "v(x0.en_in)={vin} v(x0.en_inb)=0 v(x0.bg_ok)={vin} v(x0.uv_ok)={vin} v(x0.uv_okb)=0 "
           "v(x0.on)={vin} v(x0.onb)=0 v(x0.pg_raw)={vin} v(x0.pg_rawb)=0 v(x0.pg_d)={vin} v(x0.pg_db)=0 "
           "v(x0.por_d)={vin} v(x0.por_db)=0 v(pg)=1.8 v(porn)=1.8")

LIMITS = {
    "vout": (1.719, 1.881),          # 1.8 V +-4.5 % untrimmed (3 sigma diode corners: VBG -3.6 / +3.1 %)
    "iq_max": 120e-6,                # quiescent current, no load
    "ioff_max": 1e-6,                # LDO_EN = 0
    "line_reg_max": 5e-3,            # V/V, 2.97 .. 3.63 V
    "load_reg_max": 0.5e-3 / 1e-3,   # V/A?  see check(): mV per 20 mA
    "dropout_max": 0.70,             # V at 20 mA: regulates down to the UVLO (2.5 V)
    "ilim": (40e-3, 120e-3),
    "pm_min": 45.0,
    "gm_min": 10.0,
    "psrr_1k_min": 40.0,             # dB at 1 kHz, 20 mA
    "step_dev_max": 50e-3,           # V, 1 -> 20 mA in 1 us
    "uvlo_r": (2.55, 2.85), "uvlo_f": (2.35, 2.65),
    "pg_r": (1.55, 1.70), "pg_f": (1.48, 1.62),
    "t_pg": (4e-6, 25e-6), "t_por": (40e-6, 250e-6),
}


def lib(corner):
    p = os.path.join(MODELS, f"xh018_{corner}.lib")
    if not os.path.exists(p):
        subprocess.run(["python3", os.path.join(HERE, "xfab2ngspice_ldo.py")], check=True)
    return p


def run(path, text, timeout=7200):
    # operating point of op / ac / noise: transient op (1 ms, all sources at
    # their DC values) instead of the plain DC solve, which can stop in a
    # non-converged off state of the latched supervisor / bandgap (ws, -40 C)
    if re.search(r"^(op|ac |noise )", text, re.M) and "\ntran " not in text and "ven en 0 dc 0\n" not in text:
        text = text.replace(".control\n", ".control\noptran 0 0 0 100n 1m 0\n", 1)
        # no .nodeset: it would start the transient op at VOUT = 1.8 V, which
        # a regulator that cannot sink current does not pull down at no load
        text = re.sub(r"^\.nodeset .*\n", "", text, flags=re.M)
    open(path, "w").write(text)
    for d in re.findall(r"wrdata (\S+)", text):
        if os.path.exists(d):
            os.remove(d)
    r = subprocess.run(["ngspice", "-b", path], capture_output=True, text=True, timeout=timeout)
    open(path[:-3] + ".log", "w").write(r.stdout + r.stderr)
    return r.stdout


def header(a, title, vin=None, en="vin", load="5m", cout=None, esr=None):
    """DUT with supply, enable, output capacitor (+ ESR) and a DC load."""
    vin = a.vin if vin is None else vin
    cout = a.cout if cout is None else cout
    esr = a.esr if esr is None else esr
    ens = "ven en 0 dc 1.8" if en == "1.8" else ("ven en vin dc 0" if en == "vin" else f"ven en 0 {en}")
    return f"""* {title}
.include "{lib(a.corner)}"
.include "{a.netlist}"
.temp {a.temp}
vin vin 0 dc {vin}
{ens}
x0 vin vout 0 en pg porn afe_ldo_tr
cout vout co {cout}
resr co 0 {esr}
cpg pg 0 0.1p
cpr porn 0 0.1p
{OPTS}
{NODESET.format(vin=vin) if en != "dc 0" else ""}
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


def res_lines(o):
    return {k: float(v) for k, v in re.findall(r"^RES (\w+) = (\S+)", o, re.M)}


# ------------------------------------------------------------------ cases
def case_op(a, out):
    r = {}
    for name, en, il in (("nl", "1.8", "0"), ("l20", "1.8", "20m"), ("off", "0", "0")):
        o = run(f"{out}/op_{name}.sp", header(a, "op", en=en if en != "0" else "dc 0") +
                f"iload vout 0 {il}\n.control\nop\n" +
                "".join(f'echo "RES {k} = $&{v}"\n' for k, v in (
                    ("vout", "v(vout)"), ("vbg", "v(x0.vbg)"), ("ivin", "i(vin)"), ("vgp", "v(x0.gp)"),
                    ("veo", "v(x0.eo)"), ("pg", "v(pg)"), ("porn", "v(porn)"))) + ".endc\n.end\n")
        g = res_lines(o)
        g["ivin"] = -g.get("ivin", float("nan"))
        r[name] = g
    r["iq"] = r["nl"]["ivin"]
    r["ignd_20m"] = r["l20"]["ivin"] - 20e-3
    r["ioff"] = r["off"]["ivin"]
    print(f"  op: VOUT {r['nl']['vout']:.4f} V (no load) {r['l20']['vout']:.4f} V (20 mA)  VBG "
          f"{r['nl']['vbg']:.4f} V  Iq {r['iq'] * 1e6:.1f} uA  I_gnd(20 mA) {r['ignd_20m'] * 1e6:.1f} uA  "
          f"I_off {r['ioff'] * 1e9:.1f} nA")
    return r


def case_temp(a, out):
    temps = [-40, -20, 0, 27, 50, 85, 105, 125]

    # a 400 us power-up transient instead of a DC solution: at low temperature
    # the DC solver lands in the bandgap's zero-current state even with nodesets
    def one(t):
        b = header(a, "temp", en="1.8").replace(f".temp {a.temp}", f".temp {t}").replace(
            f"vin vin 0 dc {a.vin}", f"vin vin 0 pwl(0 0 20u {a.vin})")
        o = run(f"{out}/temp_{t}.sp", b + "iload vout 0 5m\n.control\ntran 50n 400u 0 1u\n"
                "let n = length(time) - 1\nlet e1 = v(x0.vbg)[n]\nlet e2 = v(vout)[n]\nlet e3 = i(vin)[n]\n"
                'echo "RES vbg = $&e1"\necho "RES vout = $&e2"\necho "RES ivin = $&e3"\n.endc\n.end\n')
        return res_lines(o)
    with cf.ThreadPoolExecutor(max_workers=int(os.environ.get("JOBS", "2"))) as ex:
        g = list(ex.map(one, temps))
    r = {"t": temps, "vbg": [x["vbg"] for x in g], "vout": [x["vout"] for x in g],
         "ivin": [-x["ivin"] - 5e-3 for x in g]}
    vb = np.array(r["vbg"])
    r["vbg_tc_ppm"] = float((vb.max() - vb.min()) / vb.mean() / (temps[-1] - temps[0]) * 1e6)
    print(f"  temp: VBG {vb.min():.4f} .. {vb.max():.4f} V ({r['vbg_tc_ppm']:.1f} ppm/K box), VOUT "
          f"{min(r['vout']):.4f} .. {max(r['vout']):.4f} V, I_gnd {min(r['ivin']) * 1e6:.1f} .. "
          f"{max(r['ivin']) * 1e6:.1f} uA")
    return r


def bload(expr):
    """Load current source that folds back below 0.2 V (a collapsed output is
    not driven negative).  A pwl() in it needs a flat last segment: ngspice
    extrapolates B-source pwl() linearly past the last point."""
    return f"bload vout 0 i = ({expr}) * min(1, max(v(vout), 0) / 0.2)\n"


def ramp(a, out, name, body, tstop, save, pre=""):
    """Slow transient ramp instead of a DC sweep: the UVLO / power-good
    latches make the DC problem bistable, and a DC sweep can jump to the off
    state after a failed continuation step."""
    return tran(a, out, name, body, tstop, "1u", save, "2u", pre)


def case_line(a, out):
    r = {}
    for il in ("1m", "20m"):
        ilv = {"1m": 1e-3, "20m": 20e-3}[il]
        # VIN 3.63 -> 1.5 V in 4 ms (after 0.4 ms settling)
        t, (vin, vout, ivin) = ramp(a, out, f"line_{il}", header(a, "line", en="1.8").replace(
            f"vin vin 0 dc {a.vin}", "vin vin 0 pwl(0 3.63 0.4m 3.63 4.4m 1.5)") + bload(f"{ilv}"),
            "4.4m", "v(vin) v(vout) i(vin)")
        w = t > 0.4e-3
        vin, vout, ivin = vin[w][::-1], vout[w][::-1], ivin[w][::-1]
        hi = vin >= 2.97 - 1e-6
        reg = (np.interp(3.63, vin, vout) - np.interp(2.97, vin, vout)) / 0.66
        # dropout: the UVLO (2.5 V falling) switches the LDO off before the pass
        # device runs out of headroom, so measure it with the UVLO released at
        # ~1.4 V (top divider resistor 788 k -> 100 k, test only): VIN - VOUT
        # where VOUT has fallen 50 mV below its value at 2.6 V
        td, (dv, dvo, dvbg) = ramp(a, out, f"drop_{il}", header(a, "dropout", en="1.8").replace(
            f"vin vin 0 dc {a.vin}", "vin vin 0 pwl(0 2.6 0.4m 2.6 2.4m 1.6)") + bload(f"{ilv}"), "2.4m",
            "v(vin) v(vout) v(x0.vbg)", pre="alter @r.x0.rua[resistance]=100k")
        w = td > 0.4e-3
        dv, dvo, dvbg = dv[w][::-1], dvo[w][::-1], dvbg[w][::-1]
        k = np.nonzero(dvo < np.interp(2.6, dv, dvo) - 0.05)[0]
        drop = float(dv[k[-1]] - dvo[k[-1]]) if len(k) else float("nan")
        vbg_at = float(dvbg[k[-1]]) if len(k) else float("nan")
        sub = slice(None, None, max(1, len(vin) // 600))
        r[il] = {"vin": vin[sub].tolist(), "vout": vout[sub].tolist(), "ivin": (-ivin[sub]).tolist(),
                 "drop_vin": dv[sub].tolist(), "drop_vout": dvo[sub].tolist(),
                 "line_reg": float(reg), "vout_33": float(np.interp(3.3, vin, vout)), "dropout": drop,
                 "vbg_at_dropout": vbg_at, "vout_2v5": float(np.interp(2.55, vin, vout)),
                 "uvlo_off": float(vin[np.nonzero(vout > 1.0)[0][0]]) if (vout > 1.0).any() else float("nan"),
                 "vout_min_hi": float(vout[hi].min()), "vout_max_hi": float(vout[hi].max())}
        print(f"  line {il}: VOUT {vout[hi].min():.4f} .. {vout[hi].max():.4f} V for VIN 2.97 .. 3.63 V, "
              f"{reg * 1e3:.2f} mV/V; VOUT {r[il]['vout_2v5']:.4f} V at 2.55 V, off below {r[il]['uvlo_off']:.3f} V; "
              f"dropout (-50 mV, UVLO overridden) {drop * 1e3:.0f} mV")
    return r


def case_load(a, out):
    r = {}
    for vin in (3.3, 2.97):
        tag = f"{vin:g}"
        # load 0 -> 100 mA in 4 ms (after 0.4 ms settling)
        t, (vout, ivin) = ramp(a, out, f"load_{tag}", header(a, "load", vin=vin, en="1.8") +
                               bload("0.1 * max(time - 0.4m, 0) / 4m"), "4.4m", "v(vout) i(vin)")
        w = t > 0.4e-3
        il = 0.1 * (t[w] - 0.4e-3) / 4e-3
        vout, ivin = vout[w], ivin[w]
        reg = (np.interp(20e-3, il, vout) - np.interp(0, il, vout)) / 20e-3
        k = np.nonzero(vout < np.interp(1e-3, il, vout) - 0.1)[0]
        ilim = float(il[k[0]]) if len(k) else float("nan")
        # short-circuit current: the largest load current actually delivered
        iout = il * np.minimum(1, np.maximum(vout, 0) / 0.2)
        sub = slice(None, None, max(1, len(il) // 600))
        r[tag] = {"il": il[sub].tolist(), "vout": vout[sub].tolist(), "ivin": (-ivin[sub]).tolist(),
                  "load_reg": float(reg), "ilim": ilim, "iout_max": float(np.max(np.abs(iout))),
                  "dv_20m": float(np.interp(20e-3, il, vout) - np.interp(0, il, vout))}
        print(f"  load VIN {tag}: 0 -> 20 mA {r[tag]['dv_20m'] * 1e3:+.2f} mV ({reg:.3f} Ohm), "
              f"current limit (VOUT -100 mV) {ilim * 1e3:.1f} mA, max {r[tag]['iout_max'] * 1e3:.1f} mA")
    return r


def loopgain(a, out, il, cout=None, esr=None, tag=""):
    o = run(f"{out}/ac_{il}{tag}.sp", header(a, "loop gain", en="1.8", cout=cout, esr=esr) +
            f"iload vout 0 {il}\n.control\nop\nalter @v.x0.vinj[acmag]=1\nac dec 50 1 30meg\n"
            f"let t = -v(x0.fb)/v(x0.fbe)\nwrdata {out}/ac_{il}{tag}.dat real(t) imag(t)\n.endc\n.end\n")
    f, (re_, im) = load(f"{out}/ac_{il}{tag}.dat")
    t = re_ + 1j * im
    mag = 20 * np.log10(abs(t))
    ph = np.unwrap(np.angle(t)) * 180 / np.pi
    # crossover: last downward 0 dB crossing below 30 MHz
    k = np.nonzero((mag[:-1] > 0) & (mag[1:] <= 0))[0]
    if len(k):
        i = k[-1]
        fc = f[i] * (f[i + 1] / f[i]) ** (mag[i] / (mag[i] - mag[i + 1]))
        pm = 180 + np.interp(np.log(fc), np.log(f[i:i + 2]), ph[i:i + 2])
    else:
        fc, pm = float("nan"), float("nan")
    # phase margin as 180 + phase: wrap into (-180, 180]
    pm = (pm + 180) % 360 - 180
    # minimum phase margin over the whole band where |T| > 1 (conditional)
    above = mag > 0
    pm_min_cond = float(np.min((180 + ph[above] + 180) % 360 - 180)) if above.any() else float("nan")
    # gain margin: |T| where the phase (180 + ph) crosses 0 above the crossover
    pmc = (180 + ph + 180) % 360 - 180
    # (below 10 MHz: above it the gate capacitance of the error amplifier
    # loads the injection point and the single-injection estimate is invalid)
    j = np.nonzero((f > fc) & (f < 10e6) & (np.abs(pmc) < 5))[0] if np.isfinite(fc) else []
    gm = float(-mag[j[0]]) if len(j) else float(-np.interp(10e6, f, mag))
    return {"f": f.tolist(), "mag": mag.tolist(), "ph": ph.tolist(), "fc": float(fc), "pm": float(pm),
            "gm": gm, "dc_gain": float(mag[0]), "pm_cond": pm_min_cond}


def case_ac(a, out):
    loads = ["0", "10u", "100u", "1m", "5m", "20m", "50m"]
    with cf.ThreadPoolExecutor(max_workers=int(os.environ.get("JOBS", "2"))) as ex:
        res = dict(zip(loads, ex.map(lambda il: loopgain(a, out, il), loads)))
    for il in loads:
        r = res[il]
        print(f"  ac {il:>4s}: DC gain {r['dc_gain']:5.1f} dB  crossover {r['fc'] / 1e3:8.1f} kHz  "
              f"PM {r['pm']:5.1f} deg  GM {r['gm']:5.1f} dB")
    return res


def case_capsweep(a, out):
    """Phase margin over output capacitance / ESR (no load and 20 mA)."""
    combos = [(0.47e-6, 0.005), (0.47e-6, 0.5), (1e-6, 0.01), (2.2e-6, 0.005), (2.2e-6, 0.5), (10e-6, 0.01)]
    jobs = [(c, e, il) for c, e in combos for il in ("0", "1m", "20m")]
    with cf.ThreadPoolExecutor(max_workers=int(os.environ.get("JOBS", "2"))) as ex:
        rr = list(ex.map(lambda j: loopgain(a, out, j[2], j[0], j[1], f"_c{j[0] * 1e6:g}_e{j[1]:g}"), jobs))
    res = []
    for (c, e, il), r in zip(jobs, rr):
        res.append({"cout": c, "esr": e, "il": il, "fc": r["fc"], "pm": r["pm"], "gm": r["gm"]})
        print(f"  capsweep C {c * 1e6:g} uF ESR {e:g} Ohm {il:>3s}: crossover {r['fc'] / 1e3:7.1f} kHz "
              f"PM {r['pm']:5.1f} deg GM {r['gm']:5.1f} dB")
    return res


def case_psrr(a, out):
    r = {}
    for il in ("1m", "20m"):
        run(f"{out}/psrr_{il}.sp", header(a, "psrr", en="1.8").replace(f"vin vin 0 dc {a.vin}",
            f"vin vin 0 dc {a.vin} ac 1") + f"iload vout 0 {il}\n.control\nac dec 20 10 100meg\n"
            f"wrdata {out}/psrr_{il}.dat vdb(vout)\n.endc\n.end\n")
        f, (db,) = load(f"{out}/psrr_{il}.dat")
        psrr = -db
        r[il] = {"f": f.tolist(), "psrr": psrr.tolist(),
                 **{f"psrr_{k}": float(np.interp(np.log10(v), np.log10(f), psrr))
                    for k, v in (("100", 100), ("1k", 1e3), ("10k", 1e4), ("100k", 1e5), ("1M", 1e6))},
                 "psrr_min": float(psrr.min()), "f_min": float(f[np.argmin(psrr)])}
        x = r[il]
        print(f"  psrr {il}: {x['psrr_100']:.1f} / {x['psrr_1k']:.1f} / {x['psrr_10k']:.1f} / "
              f"{x['psrr_100k']:.1f} / {x['psrr_1M']:.1f} dB at 100 Hz / 1k / 10k / 100k / 1 MHz; "
              f"minimum {x['psrr_min']:.1f} dB at {x['f_min'] / 1e3:.0f} kHz")
    return r


def case_zout(a, out):
    r = {}
    for il in ("1m", "20m"):
        run(f"{out}/zout_{il}.sp", header(a, "zout", en="1.8") + f"iload vout 0 {il} ac 1\n.control\n"
            f"ac dec 20 10 100meg\nwrdata {out}/zout_{il}.dat mag(v(vout))\n.endc\n.end\n")
        f, (z,) = load(f"{out}/zout_{il}.dat")
        r[il] = {"f": f.tolist(), "z": z.tolist(), "z_100": float(np.interp(2, np.log10(f), z)),
                 "z_max": float(z.max()), "f_zmax": float(f[np.argmax(z)])}
        print(f"  zout {il}: {r[il]['z_100'] * 1e3:.1f} mOhm at 100 Hz, peak {r[il]['z_max'] * 1e3:.0f} mOhm "
              f"at {r[il]['f_zmax'] / 1e3:.0f} kHz")
    return r


def case_noise(a, out):
    o = run(f"{out}/noise.sp", header(a, "noise", en="1.8").replace(f"vin vin 0 dc {a.vin}",
            f"vin vin 0 dc {a.vin} ac 1") + "iload vout 0 5m\n.control\nnoise v(vout) vin dec 20 10 1meg\n"
            f"setplot noise1\nwrdata {out}/noise.dat onoise_spectrum\nsetplot noise2\n"
            "echo \"RES vn_total = $&onoise_total\"\n"
            "setplot noise1\nlet x = onoise_spectrum^2\nlet f = frequency\n.endc\n.end\n")
    f, (vn,) = load(f"{out}/noise.dat")
    m = (f >= 10) & (f <= 1e5)
    rms = float(np.sqrt(np.trapz(vn[m] ** 2, f[m])))
    r = {"f": f.tolist(), "vn": vn.tolist(), "rms_10_100k": rms,
         "vn_1k": float(np.interp(3, np.log10(f), vn)), "vn_100k": float(np.interp(5, np.log10(f), vn))}
    print(f"  noise: {r['vn_1k'] * 1e9:.0f} nV/rtHz at 1 kHz, {r['vn_100k'] * 1e9:.0f} nV/rtHz at 100 kHz, "
          f"{rms * 1e6:.1f} uV rms (10 Hz .. 100 kHz)")
    return r


def tran(a, out, name, body, tstop, tstep, save, tmax=None, pre=""):
    tmax = tmax or tstep
    dat = f"{out}/{name}.dat"
    run(f"{out}/{name}.sp", body + f""".control
{pre}
save {save}
tran {tstep} {tstop} 0 {tmax}
wrdata {dat} {save}
.endc
.end
""")
    return load(dat)


T0 = 0.5e-3   # power-up time before the events of the step / short / enable cases


def powerup(a, body):
    """VIN ramps 0 -> VIN in 20 us: the transient then starts from the real
    power-up (the DC solution of the latched supervisor may be the off state)."""
    return body.replace(f"vin vin 0 dc {a.vin}", f"vin vin 0 pwl(0 0 20u {a.vin})")


def case_start(a, out):
    t, (vin, vout, pg, porn, ivin, uv, on, pgr) = tran(a, out, "start", header(a, "start", en="vin").replace(
        f"vin vin 0 dc {a.vin}", f"vin vin 0 pwl(0 0 10u 0 110u {a.vin})") + bload("5m"),
        "800u", "20n", "v(vin) v(vout) v(pg) v(porn) i(vin) v(x0.uv_ok) v(x0.on) v(x0.pg_raw)", "50n")
    t10 = cross(t, vout, 0.1 * VNOM)
    # UVLO release: the last rising edge of on before VOUT rises (at low VIN
    # the supervisor logic is not defined yet and on may toggle)
    d = on - 0.5 * vin
    k = np.nonzero((d[:-1] <= 0) & (d[1:] > 0) & (t[1:] < t10) & (vin[1:] > 1.0))[0]
    t_on = float(t[k[-1] + 1]) if len(k) else float("nan")
    vin_on = float(np.interp(t_on, t, vin)) if np.isfinite(t_on) else float("nan")
    t90 = cross(t, vout, 0.9 * VNOM)
    # PWR_GOOD delay from the comparator decision (pg_raw: VOUT > VBG / 0.7325,
    # 1.62 V at the nominal VBG), so that it does not depend on the VBG corner
    t_pgv = cross(t, pgr - 0.5 * vin, 0.0, after=t10)
    t_pg = cross(t, pg, 0.5 * VNOM)
    t_por = cross(t, porn, 0.5 * VNOM)
    r = {"t_on": t_on, "vout_at_pg_raw": float(np.interp(t_pgv, t, vout)) if np.isfinite(t_pgv) else float("nan"), "vin_at_on": vin_on, "t_ss_10_90": t90 - t10, "t_ss_90": t90 - t_on,
         "t_pg": t_pg - t_pgv, "t_por": t_por - t_pg, "i_inrush": float((-ivin).max()),
         "vout_final": float(vout[-1]), "overshoot": float(vout.max() - vout[-1])}
    print(f"  start: regulator on at VIN {vin_on:.3f} V, VOUT 90 % {r['t_ss_90'] * 1e6:.1f} us later "
          f"(10-90 % {r['t_ss_10_90'] * 1e6:.1f} us), PG comparator at VOUT {r['vout_at_pg_raw']:.3f} V, "
          f"PWR_GOOD {r['t_pg'] * 1e6:.1f} us later, "
          f"POR_N {r['t_por'] * 1e6:.1f} us later, inrush {r['i_inrush'] * 1e3:.1f} mA, "
          f"overshoot {r['overshoot'] * 1e3:.1f} mV")
    s_ = slice(None, None, max(1, len(t) // 4000))
    np.savetxt(f"{out}/start.csv", np.column_stack([t, vin, vout, pg, porn, -ivin])[s_], delimiter=",",
               header="t,vin,vout,pwr_good,por_n,ivin", comments="", fmt="%.6e")
    return r


def case_uvlo(a, out):
    v = a.vin
    t, (vin, vout, pg, porn, uv) = tran(a, out, "uvlo", header(a, "uvlo", en="1.8").replace(
        f"vin vin 0 dc {v}", f"vin vin 0 pwl(0 0 20u {v} 0.6m {v} {0.6e-3 + (v - 2.0) * 1e-3} 2.0 "
        f"{0.9e-3 + (v - 2.0) * 1e-3} 2.0 {0.9e-3 + 2 * (v - 2.0) * 1e-3} {v} 4.0m {v})")
        + bload("5m"), "4.0m", "50n", "v(vin) v(vout) v(pg) v(porn) v(x0.uv_ok)", "200n")
    t_f = cross(t, uv - 0.5 * vin, 0.0, rising=False, after=0.6e-3)
    t_r = cross(t, uv - 0.5 * vin, 0.0, rising=True, after=0.9e-3 + (a.vin - 2.0) * 1e-3)
    t_pgf = cross(t, pg - 0.5 * vout, 0.0, rising=False, after=0.6e-3)
    w = (t > 0.6e-3) & (t < t_f) if np.isfinite(t_f) else (t > 0.6e-3)
    r = {"uvlo_f": float(np.interp(t_f, t, vin)), "uvlo_r": float(np.interp(t_r, t, vin)),
         "vin_pg_f": float(np.interp(t_pgf, t, vin)), "vout_min_before_off": float(vout[w].min())}
    r["uvlo_hys"] = r["uvlo_r"] - r["uvlo_f"]
    print(f"  uvlo: off at VIN {r['uvlo_f']:.3f} V (falling), on at {r['uvlo_r']:.3f} V (rising), "
          f"hysteresis {r['uvlo_hys'] * 1e3:.0f} mV; VOUT >= {r['vout_min_before_off']:.4f} V until off, "
          f"PWR_GOOD fell at VIN {r['vin_pg_f']:.3f} V")
    s_ = slice(None, None, max(1, len(t) // 4000))
    np.savetxt(f"{out}/uvlo.csv", np.column_stack([t, vin, vout, pg, porn])[s_], delimiter=",",
               header="t,vin,vout,pwr_good,por_n", comments="", fmt="%.6e")
    return r


def case_step(a, out):
    t1, t2 = T0, T0 + 0.2e-3
    t, (vout,) = tran(a, out, "step", powerup(a, header(a, "step", en="1.8")) +
                      bload(f"pwl(time, 0, 1m, {t1}, 1m, {t1 + 1e-6}, 20m, {t2}, 20m, {t2 + 1e-6}, 1m, 1, 1m)"),
                      f"{t2 + 0.2e-3}", "2n", "v(vout)", "20n")
    il = np.interp(t, [0, t1, t1 + 1e-6, t2, t2 + 1e-6, 1], [1e-3, 1e-3, 20e-3, 20e-3, 1e-3, 1e-3])
    v0 = float(np.interp(t1 - 1e-6, t, vout))
    v1 = float(np.interp(t2 - 1e-6, t, vout))
    w1 = (t > t1) & (t < t2)
    w2 = t > t2
    under = float(v0 - vout[w1].min())
    over = float(vout[w2].max() - v1)

    def settle(w, vf, tol=2e-3):
        k = np.nonzero(np.abs(vout[w] - vf) > tol)[0]
        return float(t[w][k[-1]] - t[w][0]) if len(k) else 0.0
    r = {"v_1m": v0, "v_20m": v1, "undershoot": under, "overshoot": over,
         "t_settle_up": settle(w1, v1), "t_settle_down": settle(w2, float(vout[-1]))}
    print(f"  step 1 -> 20 mA: undershoot {under * 1e3:.1f} mV, settles (2 mV) in {r['t_settle_up'] * 1e6:.1f} us; "
          f"20 -> 1 mA: overshoot {over * 1e3:.1f} mV, settles in {r['t_settle_down'] * 1e6:.1f} us")
    w = (t > t1 - 10e-6) & (t < t1 + 60e-6) | (t > t2 - 10e-6) & (t < t2 + 60e-6)
    np.savetxt(f"{out}/step.csv", np.column_stack([t[w] - t1, vout[w], il[w]]), delimiter=",",
               header="t,vout,iload", comments="", fmt="%.6e")
    return r


def case_line_step(a, out):
    t1, t2 = T0, T0 + 0.2e-3
    t, (vin, vout) = tran(a, out, "line_step", header(a, "line step", en="1.8").replace(
        f"vin vin 0 dc {a.vin}", f"vin vin 0 pwl(0 0 20u 3.0 {t1} 3.0 {t1 + 1e-6} 3.6 {t2} 3.6 {t2 + 1e-6} 3.0)") +
        bload("5m"), f"{t2 + 0.2e-3}", "2n", "v(vin) v(vout)", "20n")
    v0 = float(np.interp(t1 - 1e-6, t, vout))
    w1 = (t > t1) & (t < t2)
    w2 = t > t2
    r = {"dv_up": float(vout[w1].max() - v0), "dv_down": float(np.interp(t2 - 1e-6, t, vout) - vout[w2].min()),
         "dv_dc": float(np.interp(t2 - 1e-6, t, vout) - v0)}
    print(f"  line step 3.0 <-> 3.6 V in 1 us: +{r['dv_up'] * 1e3:.2f} mV / -{r['dv_down'] * 1e3:.2f} mV peak, "
          f"{r['dv_dc'] * 1e3:+.3f} mV DC")
    w = (t > t1 - 10e-6) & (t < t1 + 60e-6) | (t > t2 - 10e-6) & (t < t2 + 60e-6)
    np.savetxt(f"{out}/line_step.csv", np.column_stack([t[w] - t1, vin[w], vout[w]]), delimiter=",",
               header="t,vin,vout", comments="", fmt="%.6e")
    return r


def case_en(a, out):
    # LDO_EN: 0 until 20 us, 1 until 0.6 ms, 0 until 6 ms (discharge through
    # MDIS with a 0.1 mA load only), 1 again; VIN on from the start
    t, (vout, pg, porn, ivin, pgr) = tran(a, out, "en", header(a, "enable", en="pwl(0 0 20u 0 20.01u 1.8 "
                                     "600u 1.8 600.01u 0 6m 0 6.00001m 1.8)").replace(
                                     f"vin vin 0 dc {a.vin}", f"vin vin 0 pwl(0 0 5u {a.vin})") + bload("0.1m"),
                                     "6.6m", "20n", "v(vout) v(pg) v(porn) i(vin) v(x0.pg_raw)", "500n")
    t10 = cross(t, vout, 0.1 * VNOM, after=20e-6)
    t90 = cross(t, vout, 0.9 * VNOM, after=20e-6)
    t_pgv = cross(t, pgr - 0.5 * a.vin, 0.0, after=20e-6)
    t_pg = cross(t, pg, 0.5 * VNOM, after=20e-6)
    t_por = cross(t, porn, 0.5 * VNOM, after=20e-6)
    t_pgo = cross(t, pg - 0.5 * vout, 0.0, rising=False, after=600e-6)
    t_dis = cross(t, vout, 0.1 * VNOM, rising=False, after=600e-6)
    t90b = cross(t, vout, 0.9 * VNOM, after=6e-3)
    r = {"t_en_10": t10 - 20e-6, "t_en_90": t90 - 20e-6, "t_rise": t90 - t10, "t_pg": t_pg - t_pgv,
         "t_por": t_por - t_pg, "t_pg_off": t_pgo - 600e-6, "t_discharge": t_dis - 600e-6,
         "r_dis_eff": float((t_dis - 600e-6) / (1e-6 * math.log(10))) if np.isfinite(t_dis) else float("nan"),
         "t_en_90_restart": t90b - 6e-3, "i_inrush": float((-ivin[t < 590e-6]).max()),
         "overshoot": float(vout[(t > 20e-6) & (t < 600e-6)].max() - np.interp(590e-6, t, vout))}
    print(f"  en: VOUT 10 % after {r['t_en_10'] * 1e6:.1f} us, 90 % after {r['t_en_90'] * 1e6:.1f} us "
          f"(rise {r['t_rise'] * 1e6:.1f} us), PWR_GOOD +{r['t_pg'] * 1e6:.1f} us after the PG comparator, "
          f"POR_N +{r['t_por'] * 1e6:.1f} us, "
          f"inrush {r['i_inrush'] * 1e3:.1f} mA; off: PWR_GOOD low after {r['t_pg_off'] * 1e9:.0f} ns, "
          f"VOUT < 10 % after {r['t_discharge'] * 1e6:.0f} us; restart 90 % after {r['t_en_90_restart'] * 1e6:.1f} us")
    s_ = slice(None, None, max(1, len(t) // 4000))
    np.savetxt(f"{out}/en.csv", np.column_stack([t, vout, pg, porn, -ivin])[s_], delimiter=",",
               header="t,vout,pwr_good,por_n,ivin", comments="", fmt="%.6e")
    return r


def case_short(a, out):
    t1, t2 = T0, T0 + 0.2e-3
    t, (vout, ivin, pg) = tran(a, out, "short", powerup(a, header(a, "short", en="1.8")) + bload("5m") +
                               f"ssh vout sh ctl 0 swm\n.model swm sw vt=0.5 vh=0.1 ron=0.5 roff=1e9\n"
                               f"rsh sh 0 0.5\nvctl ctl 0 pwl(0 0 {t1} 0 {t1 + 0.1e-6} 1 {t2} 1 {t2 + 0.1e-6} 0)\n",
                               f"{t2 + 0.3e-3}", "5n", "v(vout) i(vin) v(pg)", "50n")
    w = (t > t1 + 50e-6) & (t < t2)
    r = {"i_short": float((-ivin[w]).mean()), "i_peak": float((-ivin[t > t1]).max()),
         "vout_short": float(vout[w].mean()),
         "t_recover": cross(t, vout, 0.98 * VNOM, after=t2) - t2,
         "overshoot": float(vout[t > t2].max() - vout[-1]), "vout_final": float(vout[-1])}
    print(f"  short (1 Ohm): {r['i_short'] * 1e3:.1f} mA from VIN (peak {r['i_peak'] * 1e3:.1f} mA), recovers to "
          f"98 % in {r['t_recover'] * 1e6:.1f} us, overshoot {r['overshoot'] * 1e3:.1f} mV")
    w = (t > t1 - 20e-6) & (t < t2 + 0.3e-3)
    s_ = slice(None, None, max(1, w.sum() // 4000))
    np.savetxt(f"{out}/short.csv", np.column_stack([t[w] - t1, vout[w], -ivin[w], pg[w]])[s_], delimiter=",",
               header="t,vout,ivin,pwr_good", comments="", fmt="%.6e")
    return r


def case_enth(a, out):
    """LDO_EN threshold: LDO_EN 0 -> 1.8 V -> 0 in 1 ms each (VIN on), the
    internal en_in edges."""
    t, (ven, eni) = tran(a, out, "enth", header(a, "enable threshold", en="pwl(0 0 0.1m 0 1.1m 1.8 2.1m 0)").replace(
        f"vin vin 0 dc {a.vin}", f"vin vin 0 pwl(0 0 5u {a.vin})") + bload("1m"), "2.1m", "200n",
        "v(en) v(x0.en_in)", "1u")
    tr = cross(t, eni - 0.5 * a.vin, 0.0, rising=True, after=0.1e-3)
    tf = cross(t, eni - 0.5 * a.vin, 0.0, rising=False, after=1.1e-3)
    r = {"vth_r": float(np.interp(tr, t, ven)), "vth_f": float(np.interp(tf, t, ven))}
    print(f"  enth: LDO_EN threshold {r['vth_r']:.3f} V rising, {r['vth_f']:.3f} V falling")
    return r


# ------------------------------------------------------------------ checks
def check(a, R):
    err = []
    L = LIMITS

    def rng(name, v, lo, hi):
        if not (lo <= v <= hi):
            err.append(f"{name} = {v:.4g} outside {lo:.4g} .. {hi:.4g}")
    if "op" in R:
        rng("VOUT no load", R["op"]["nl"]["vout"], *L["vout"])
        rng("VOUT 20 mA", R["op"]["l20"]["vout"], *L["vout"])
        rng("Iq", R["op"]["iq"], 0, L["iq_max"])
        rng("I_off", R["op"]["ioff"], -1e-9, L["ioff_max"])
    if "temp" in R:
        for t, v in zip(R["temp"]["t"], R["temp"]["vout"]):
            rng(f"VOUT at {t} C", v, *L["vout"])
    if "line" in R:
        if a.vin >= 2.97:
            rng("line regulation 20 mA [V/V]", abs(R["line"]["20m"]["line_reg"]), 0, L["line_reg_max"])
            rng("dropout 20 mA", R["line"]["20m"]["dropout"], 0, L["dropout_max"])
    if "load" in R:
        rng("load regulation 0-20 mA [V]", abs(R["load"]["3.3"]["dv_20m"]), 0, 10e-3)
        rng("current limit", R["load"]["3.3"]["ilim"], *L["ilim"])
    if "ac" in R:
        for il, r in R["ac"].items():
            # rated: 0-20 mA with COUT >= 1 uF, 0-5 mA with 0.47 uF; 50 mA is
            # above the rating (checked only for PM > 30 deg, GM > 2 dB)
            if a.cout < 0.9e-6 and il in ("20m", "50m"):
                continue
            over = il == "50m"
            pm_min = 30 if over else (40 if (a.cout > 1.5e-6 and il == "0") else L["pm_min"])
            rng(f"phase margin {il}", r["pm"], pm_min, 180)
            rng(f"gain margin {il}", r["gm"], 2 if over else L["gm_min"], 300)
    if "capsweep" in R:
        for r in R["capsweep"]:
            # rated: 0.47 uF up to 5 mA; 2.2 uF: PM >= 40 deg at no load (the
            # crossover falls below the REA / CEA zero); 10 uF only with >= 1 mA
            if r["cout"] < 0.9e-6 and r["il"] == "20m":
                continue
            if r["cout"] > 5e-6 and r["il"] == "0":
                continue
            pm_min = 40 if (r["cout"] > 1.5e-6 and r["il"] == "0") else L["pm_min"]
            rng(f"phase margin C {r['cout']:g} ESR {r['esr']:g} {r['il']}", r["pm"], pm_min, 180)
    if "psrr" in R:
        rng("PSRR 1 kHz 20 mA", R["psrr"]["20m"]["psrr_1k"], L["psrr_1k_min"], 300)
    if "step" in R:
        rng("load step undershoot", R["step"]["undershoot"], 0, L["step_dev_max"])
        rng("load step overshoot", R["step"]["overshoot"], 0, L["step_dev_max"])
    if "uvlo" in R:
        rng("UVLO rising", R["uvlo"]["uvlo_r"], *L["uvlo_r"])
        rng("UVLO falling", R["uvlo"]["uvlo_f"], *L["uvlo_f"])
    if "start" in R:
        rng("t_pg (start)", R["start"]["t_pg"], *L["t_pg"])
        rng("t_por (start)", R["start"]["t_por"], *L["t_por"])
    if "en" in R:
        rng("t_pg (en)", R["en"]["t_pg"], *L["t_pg"])
        rng("t_por (en)", R["en"]["t_por"], *L["t_por"])
        rng("PWR_GOOD off delay", R["en"]["t_pg_off"], -1e-9, 1e-6)
        rng("discharge time to 10 %", R["en"]["t_discharge"], 0, 5e-3)
    if "enth" in R:
        rng("LDO_EN threshold rising", R["enth"]["vth_r"], 0.5, 1.2)
        rng("LDO_EN threshold falling", R["enth"]["vth_f"], 0.5, 1.2)
    if "short" in R:
        rng("short-circuit current", R["short"]["i_short"], 0, L["ilim"][1])
    return err


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cases", nargs="*", default=["op", "temp", "line", "load", "ac", "psrr", "zout", "noise",
                                                "start", "uvlo", "step", "line_step", "en", "enth", "short"])
    p.add_argument("--corner", default="tm")
    p.add_argument("--temp", type=float, default=27)
    p.add_argument("--vin", type=float, default=3.3)
    p.add_argument("--cout", type=float, default=1e-6)
    p.add_argument("--esr", type=float, default=0.01)
    p.add_argument("--tag", default="")
    p.add_argument("--netlist", default=NETLIST)
    a = p.parse_args()
    out = os.path.join(ROOT, "build", "ldo", f"{a.corner}_{a.temp:g}_{a.vin:g}{a.tag}")
    os.makedirs(out, exist_ok=True)
    print(f"afe_ldo_tr: corner {a.corner}, {a.temp:g} C, VIN {a.vin:g} V, COUT {a.cout * 1e6:g} uF "
          f"ESR {a.esr:g} Ohm ({os.path.basename(a.netlist)})")
    fn = {k[5:]: v for k, v in globals().items() if k.startswith("case_")}
    R = {}
    with cf.ThreadPoolExecutor(max_workers=int(os.environ.get("JOBS", "2"))) as ex:
        futs = {c: ex.submit(fn[c], a, out) for c in a.cases}
        for c, f in futs.items():
            R[c] = f.result()
            json.dump(R[c], open(f"{out}/results_{c}.json", "w"), indent=1, default=float)
    err = check(a, R)
    for e in err:
        print("  ERROR:", e)
    print("TEST PASSED" if not err else f"TEST FAILED: {len(err)} error(s)")


if __name__ == "__main__":
    main()
