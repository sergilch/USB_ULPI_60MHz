#!/usr/bin/env python3
"""tb_xosc_tr.py - ngspice testbench of afe_xosc_tr (24 MHz Pierce oscillator)

Usage (from anywhere; needs ngspice and the X-FAB library under X-FAB/spice):
    python3 "AFE/Crystal Oscillator Driver/sim/tb_xosc_tr.py" [case ...]
        [--corner tm|ws|wp|wo|wz] [--temp T] [--vdd V] [--drv 0..3] [--esr R]

Cases (default: op ac ss start byp):
  op     DC operating point, supply current for DRV = 0..3 and with XTAL_EN = 0
  ac     small-signal impedance of the amplifier between XI and XO (with the
         crystal's C0), negative resistance seen by the motional arm 20..28 MHz,
         for DRV = 0..3
  ss     steady state: motional arm pre-loaded by a 24 MHz burst, then free
         running; amplitude, crystal current / drive level, frequency, REF_CLK
         duty / edges, supply current
  start  start-up after XTAL_EN 0 -> 1 (no pre-load): time to the first
         REF_CLK edge, to 90 % amplitude, envelope growth time constant
  byp    bypass: no crystal, XI driven by an external 24 MHz clock: 1.8 V
         square through 33 Ohm, and a 0.5 Vpp sine through 10 nF (XO open)
  en     XTAL_EN 1 -> 0 -> 1 while running (REF_CLK gating, current)

Board / crystal (DOC/VXM7A-9001-24M0000000_Jan04_2022.pdf, Vectron VXM7A,
24 MHz AT-cut fundamental, CL 8 pF, C0 0.83 pF, C1 2.88 fF, ESR <= 100 Ohm,
drive level <= 200 uW): C1 = C2 = 12 pF external + 2.5 pF pin (pad,
bond, package), 0.5 pF board stray across the crystal: CL = 0.5 + 14.5 / 2
= 7.75 pF.  The motional inductance is set so that the crystal is at
24.000 MHz with CL = 8 pF.  REF_CLK load 100 fF (PLL input + wire).

Each case prints its results; the script ends with TEST PASSED /
TEST FAILED: <n> error(s) like the other testbenches.  Netlists, logs and
waveforms go to build/xosc/<corner>_<temp>_<vdd>/.  Results are also
written as JSON (results_<case>.json) there.
"""
import argparse
import concurrent.futures as cf
import json
import math
import os
import re
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DUT_DIR = os.path.dirname(HERE)
ROOT = os.path.abspath(os.path.join(DUT_DIR, "..", ".."))
MODELS = os.path.join(ROOT, "build", "xosc", "models")
NETLIST = os.path.join(DUT_DIR, "afe_xosc_tr.sp")
OPTS = ".options method=trap reltol=1e-4 abstol=1e-12 vntol=1e-7 chgtol=1e-16 itl4=100 rshunt=1e12"

F0 = 24e6
CM, C0 = 2.88e-15, 0.83e-12
CL_SPEC = 8e-12
FS = F0 / (1 + CM / (2 * (C0 + CL_SPEC)))          # series resonance
LM = 1 / ((2 * math.pi * FS) ** 2 * CM)
CEXT, CPIN, CSTRAY = 12e-12, 2.5e-12, 0.5e-12
CLOAD = 100e-15

LIMITS = {
    "margin_min": 5.0,          # |R_neg| / ESR at 24 MHz, DRV default
    "dl_max": 200e-6,           # crystal drive level
    "duty": (45.0, 55.0),       # REF_CLK duty cycle [%]
    "ppm": 50.0,                # frequency error from the circuit (pulling) [ppm]
    "t_start": 2e-3,            # start-up to a stable REF_CLK
    "idd_off": 1e-6,            # XTAL_EN = 0
    "idd_on": 1.2e-3,           # XTAL_EN = 1, DRV default
}


def lib(corner):
    p = os.path.join(MODELS, f"xh018_{corner}.lib")
    if not os.path.exists(p):
        subprocess.run([sys.executable, os.path.join(HERE, "xfab2ngspice.py")], check=True,
                       stdout=subprocess.DEVNULL)
    return p


def header(a, drv, title):
    d1, d0 = (drv >> 1) & 1, drv & 1
    return f"""* {title}
.include "{lib(a.corner)}"
.include "{a.netlist}"
.temp {a.temp}
.param vdd={a.vdd}
vdd vdd 0 {{vdd}}
vd1 d1 0 {d1 * a.vdd}
vd0 d0 0 {d0 * a.vdd}
c1 xi 0 {a.cext + CPIN}
c2 xo 0 {a.cext + CPIN}
cl clk 0 {CLOAD}
{OPTS}
"""


def xtal(esr, burst=0.0, tburst=0.0):
    """BVD crystal between xi and xo; optional sine burst in the motional arm."""
    s = f"""cs xi xo {CSTRAY}
c0x xi xo {C0}
vix xi m0 0
rm m0 m1 {esr}
lm m1 m2 {LM}
cm m2 m3 {CM}
"""
    if burst:
        # 24 MHz minus the ~300 ppm the trapezoidal step (0.4 ns) takes off the
        # simulated motional resonance, so the burst stays in phase
        s += f"bk m3 xo v = time < {tburst} ? {burst} * sin(2 * pi * {F0 * (1 - 2.8e-4)} * time) : 0\n"
    else:
        s += "vk m3 xo 0\n"
    return s


def run(path, text):
    open(path, "w").write(text)
    r = subprocess.run(["ngspice", "-b", path], capture_output=True, text=True)
    open(path[:-3] + ".log", "w").write(r.stdout + r.stderr)
    return r.stdout


def scal(out, name):
    m = re.search(rf"^{re.escape(name)}\s*=\s*([-+0-9.eE]+)", out, re.M)
    return float(m.group(1)) if m else float("nan")


def load(path):
    a = np.loadtxt(path)
    t = a[:, 0]
    return t, [a[:, i] for i in range(1, a.shape[1], 2)]


def edges(t, v, th, rising=True):
    s = v > th
    idx = np.nonzero((~s[:-1] & s[1:]) if rising else (s[:-1] & ~s[1:]))[0]
    return t[idx] + (th - v[idx]) / (v[idx + 1] - v[idx]) * (t[idx + 1] - t[idx])


# ----------------------------------------------------------------------- cases
def case_op(a, out):
    res = {}
    for drv in range(4):
        for en in (1, 0):
            sp = f"{out}/op_d{drv}_e{en}.sp"
            o = run(sp, header(a, drv, "op") + f"ven en 0 {en * a.vdd}\nx0 xi xo en d1 d0 clk vdd 0 afe_xosc_tr\n"
                    + xtal(a.esr) + """.control
op
echo "RES vxi = $&v(xi)"
echo "RES vxo = $&v(xo)"
echo "RES vnb = $&v(x0.nb)"
echo "RES vpb = $&v(x0.pb)"
echo "RES vsa = $&v(x0.sa)"
echo "RES idd = $&i(vdd)"
.endc
.end
""")
            g = {k: float(v) for k, v in re.findall(r"^RES (\w+) = (\S+)", o, re.M)}
            res[f"d{drv}_e{en}"] = {k: (-v if k == "idd" else v) for k, v in g.items()}
    for k, v in res.items():
        print(f"  op {k}: XI {v.get('vxi', 0):.3f} V  XO {v.get('vxo', 0):.3f} V  "
              f"I(VDD) {v.get('idd', float('nan')) * 1e6:9.3f} uA")
    return res


def case_ac(a, out):
    res = {}
    for drv in range(4):
        sp = f"{out}/ac_d{drv}.sp"
        dat = f"{out}/ac_d{drv}.dat"
        run(sp, header(a, drv, "ac") + f"""ven en 0 {a.vdd}
x0 xi xo en d1 d0 clk vdd 0 afe_xosc_tr
cs xi xo {CSTRAY}
c0x xi xo {C0}
iac xi xo dc 0 ac 1
* the source pulls 1 A out of XI into XO: Z(XI-XO) = V(XO) - V(XI)
.control
ac lin 81 20e6 28e6
let zr = real(v(xo) - v(xi))
let zi = imag(v(xo) - v(xi))
wrdata {dat} zr zi
.endc
.end
""")
        t, (zr, zi) = load(dat)
        z = zr + 1j * zi
        k = np.argmin(abs(t - F0))
        res[drv] = {"f": t.tolist(), "rneg": z.real.tolist(), "xneg": z.imag.tolist(),
                    "rneg24": float(z.real[k]), "x24": float(z.imag[k]),
                    "margin": float(-z.real[k] / a.esr)}
        print(f"  ac DRV={drv}: R_neg(24 MHz) {z.real[k]:8.1f} Ohm  X {z.imag[k]:8.1f} Ohm  "
              f"margin {-z.real[k] / a.esr:5.1f} x ESR {a.esr:g}")
    return res


def tran_common(a, out, name, drv, body, tstop, tstep, save):
    sp = f"{out}/{name}.sp"
    dat = f"{out}/{name}.dat"
    # save only the written vectors: ngspice keeps every node in memory
    # otherwise (GBs for the 1-2 M time points of a crystal transient)
    run(sp, header(a, drv, name) + body + f""".control
save {save}
tran {tstep} {tstop} 0 {tstep}
wrdata {dat} {save}
.endc
.end
""")
    return load(dat)


def case_ss(a, out, drv=None, esr=None, tag="ss", burst=None):
    drv = a.drv if drv is None else drv
    esr = a.esr if esr is None else esr
    tb, tstop = 40e-6, a.tss
    # burst amplitude for ~1 mA peak in the arm after tb: V = 2 Lm I / tb
    burst = a.burst if burst is None else burst
    t, (xi, xo, clk, ix, idd, vsb) = tran_common(
        a, out, f"{tag}_d{drv}_r{esr:g}", drv,
        f"ven en 0 {a.vdd}\nx0 xi xo en d1 d0 clk vdd 0 afe_xosc_tr\n" + xtal(esr, burst, tb),
        tstop, "0.4n", "v(xi) v(xo) v(clk) i(vix) i(vdd) v(x0.sb)")
    w = t > tstop - 20e-6
    tw, xiw, xow, ixw = t[w], xi[w], xo[w], ix[w]
    # rms over whole periods
    rising = edges(t, clk, a.vdd / 2)
    rw = rising[rising > tstop - 20e-6]
    falling = edges(t, clk, a.vdd / 2, rising=False)
    n = len(rw) - 1
    f = n / (rw[-1] - rw[0]) if n > 10 else float("nan")
    m = (t >= rw[0]) & (t <= rw[-1])
    irms = math.sqrt(np.trapz(ix[m] ** 2, t[m]) / (rw[-1] - rw[0]))
    idd_avg = -np.trapz(idd[m], t[m]) / (rw[-1] - rw[0])
    fw = falling[(falling > rw[0]) & (falling < rw[-1])]
    hi = np.mean([fw[i] - rw[i] for i in range(min(len(fw), len(rw) - 1))
                  if 0 < fw[i] - rw[i] < 1 / F0]) if len(fw) else float("nan")
    duty = 100 * hi * f
    # amplitude envelope (peak-to-peak per 1 us) over the whole run
    env_t, env = [], []
    for k in range(int(tstop / 1e-6)):
        s = (t >= k * 1e-6) & (t < (k + 1) * 1e-6)
        if s.any():
            env_t.append((k + 0.5) * 1e-6)
            env.append(float(xi[s].max() - xi[s].min()))
    # 10-90 % edges of REF_CLK
    def tr(v, up):
        lo, hi_ = 0.1 * a.vdd, 0.9 * a.vdd
        e1 = edges(t, v, lo, up)
        e2 = edges(t, v, hi_, up)
        e1, e2 = (e1, e2) if up else (e2, e1)
        e1 = e1[e1 > tstop - 5e-6]
        d = [e2[np.searchsorted(e2, x)] - x for x in e1 if np.searchsorted(e2, x) < len(e2)]
        return float(np.median(d)) if d else float("nan")
    # Frequency.  Trapezoidal integration with a fixed maximum step h slows
    # the high-Q motional LC by about (w h)^2 / 12 (~300 ppm at 0.4 ns), so the
    # transient frequency itself is not used.  Instead the fundamental phasors
    # of the arm voltage V = V(XI) - V(XO) and current I_x over whole periods
    # give the large-signal impedance the circuit presents to the motional arm,
    # Z_ext = -V / I_x = R_ext + j X_ext (R_ext must be -ESR in steady state),
    # and the oscillation frequency follows from the exact arm resonance with
    # C_ext = -1 / (w X_ext):  f = fs * sqrt(1 + Cm / C_ext).
    wq = 2 * math.pi * f
    ph = np.exp(-1j * wq * t[m])
    vph = np.trapz((xi[m] - xo[m]) * ph, t[m])
    iph = np.trapz(ix[m] * ph, t[m])
    zext = -vph / iph
    cext = -1 / (wq * zext.imag)
    f_true = FS * math.sqrt(1 + CM / cext)
    # period jitter (numerical, deterministic) - spread of the periods
    per = np.diff(rw)
    r = {
        "drv": drv, "esr": esr,
        "f": f_true, "ppm": (f_true / F0 - 1) * 1e6, "f_tran": f,
        "r_ext": float(zext.real), "x_ext": float(zext.imag), "c_ext": float(cext),
        "xi_pp": float(xiw.max() - xiw.min()), "xi_max": float(xiw.max()), "xi_min": float(xiw.min()),
        "xo_pp": float(xow.max() - xow.min()), "xo_max": float(xow.max()), "xo_min": float(xow.min()),
        "xi_dc": float(xiw.mean()), "xo_dc": float(xow.mean()),
        "ix_rms": irms, "dl": irms ** 2 * esr, "idd": idd_avg,
        "duty": duty, "tr": tr(clk, True), "tf": tr(clk, False),
        "settled": bool(abs(zext.real + esr) < 0.15 * esr),
        "per_pp": float(per.max() - per.min()) if len(per) else float("nan"),
        "env_t": env_t, "env": env,
    }
    print(f"  {tag} DRV={drv} ESR={esr:g}: f {f_true / 1e6:.6f} MHz ({r['ppm']:+.1f} ppm, "
          f"C_ext {cext * 1e12:.3f} pF, R_ext {zext.real:.1f} Ohm)  "
          f"XI {r['xi_pp']:.3f} Vpp  XO {r['xo_pp']:.3f} Vpp  I_x {irms * 1e3:.3f} mA rms  "
          f"DL {r['dl'] * 1e6:.1f} uW  I(VDD) {idd_avg * 1e3:.3f} mA  duty {duty:.2f} %  "
          f"tr/tf {r['tr'] * 1e12:.0f}/{r['tf'] * 1e12:.0f} ps")
    # waveform window for the figures
    s = t > tstop - 0.2e-6
    np.savetxt(f"{out}/{tag}_d{drv}_r{esr:g}_win.csv",
               np.column_stack([t[s], xi[s], xo[s], clk[s], ix[s], vsb[s]]), delimiter=",",
               header="t,xi,xo,ref_clk,i_x,sb", comments="", fmt="%.6e")
    return r


def case_start(a, out, drv=None, esr=None):
    drv = a.drv if drv is None else drv
    esr = a.esr if esr is None else esr
    tstop = a.tstart
    t, (xi, xo, clk, idd) = tran_common(
        a, out, f"start_d{drv}_r{esr:g}", drv,
        f"ven en 0 pwl(0 0 1u 0 1.001u {a.vdd})\nx0 xi xo en d1 d0 clk vdd 0 afe_xosc_tr\n" + xtal(esr),
        tstop, "1n", "v(xi) v(xo) v(clk) i(vdd)")
    env_t, env = [], []
    for k in range(int(tstop / 2e-6)):
        s = (t >= k * 2e-6) & (t < (k + 1) * 2e-6)
        env_t.append((k + 0.5) * 2e-6)
        env.append(float(xi[s].max() - xi[s].min()))
    env_t, env = np.array(env_t), np.array(env)
    final = env[-5:].mean()
    i90 = np.nonzero(env > 0.9 * final)[0]
    t90 = float(env_t[i90[0]]) if len(i90) else float("nan")
    # growth time constant from the 2 % .. 30 % part of the envelope, after
    # the bias transient of XTAL_EN has died out (envelope minimum)
    imin = int(np.argmin(env[env_t < t90])) if np.isfinite(t90) else 0
    g = (env > 0.02 * final) & (env < 0.3 * final) & (env_t < t90) & (np.arange(len(env)) > imin)
    tau = float(1 / np.polyfit(env_t[g], np.log(env[g]), 1)[0]) if g.sum() > 3 else float("nan")
    rising = edges(t, clk, a.vdd / 2)
    t_first = float(rising[0]) if len(rising) else float("nan")
    # stable: all following periods within 1 % of 1/F0
    per = np.diff(rising)
    bad = np.nonzero(abs(per * F0 - 1) > 0.01)[0]
    t_stable = float(rising[bad[-1] + 1]) if len(bad) else t_first
    r = {"drv": drv, "esr": esr, "t_first": t_first - 1e-6, "t_stable": t_stable - 1e-6,
         "t90": t90 - 1e-6, "tau": tau, "final_pp": float(final),
         "env_t": env_t.tolist(), "env": env.tolist()}
    print(f"  start DRV={drv} ESR={esr:g}: first REF_CLK edge {r['t_first'] * 1e6:.1f} us, "
          f"stable {r['t_stable'] * 1e6:.1f} us, 90 % amplitude {r['t90'] * 1e6:.1f} us, "
          f"tau {tau * 1e6:.1f} us, final {final:.3f} Vpp")
    s = (t > 1e-6) & (t < 1.3e-6)
    np.savetxt(f"{out}/start_d{drv}_r{esr:g}_env.csv", np.column_stack([env_t, env]),
               delimiter=",", header="t,xi_pp", comments="", fmt="%.6e")
    return r


def case_byp(a, out):
    res = {}
    for name, src in (("sq", f"vext ext 0 pulse(0 {a.vdd} 0 0.5n 0.5n {0.5 / F0 - 0.5e-9} {1 / F0})\n"
                             "rext ext xi 33\n"),
                      ("sine", f"vext ext 0 sin(0 0.25 {F0})\ncext ext xi 10n\n")):
        t, (xi, xo, clk, idd) = tran_common(
            a, out, f"byp_{name}", a.drv,
            f"ven en 0 {a.vdd}\nx0 xi xo en d1 d0 clk vdd 0 afe_xosc_tr\n" + src, 20e-6, "0.2n",
            "v(xi) v(xo) v(clk) i(vdd)")
        rw = edges(t, clk, a.vdd / 2)
        rw = rw[rw > 12e-6]
        fw = edges(t, clk, a.vdd / 2, False)
        fw = fw[fw > rw[0]]
        f = (len(rw) - 1) / (rw[-1] - rw[0])
        duty = 100 * np.mean([fw[i] - rw[i] for i in range(min(len(rw) - 1, len(fw)))]) * f
        xr = edges(t, xi, a.vdd / 2 if name == "sq" else float(np.mean(xi[t > 12e-6])))
        xr = xr[xr > 12e-6]
        dl = [y - x for x in xr for y in rw if 0 < y - x < 1 / F0][:20]
        m = t > 12e-6
        idd_avg = -np.trapz(idd[m], t[m]) / (t[m][-1] - t[m][0])
        res[name] = {"f": f, "duty": duty, "delay": float(np.median(dl)) if dl else float("nan"),
                     "idd": idd_avg}
        print(f"  byp {name}: f {f / 1e6:.4f} MHz  duty {duty:.2f} %  XI->REF_CLK "
              f"{res[name]['delay'] * 1e9:.2f} ns  I(VDD) {idd_avg * 1e3:.3f} mA")
        s = (t > 19.8e-6)
        np.savetxt(f"{out}/byp_{name}_win.csv", np.column_stack([t[s], xi[s], xo[s], clk[s]]),
                   delimiter=",", header="t,xi,xo,ref_clk", comments="", fmt="%.6e")
    return res


def case_en(a, out):
    t, (xi, xo, clk, idd) = tran_common(
        a, out, "en", a.drv,
        f"ven en 0 pwl(0 {a.vdd} 30u {a.vdd} 30.001u 0 40u 0 40.001u {a.vdd})\n"
        "x0 xi xo en d1 d0 clk vdd 0 afe_xosc_tr\n" + xtal(a.esr, a.burst, 25e-6),
        60e-6, "0.5n", "v(xi) v(xo) v(clk) i(vdd)")
    # XTAL_EN = 0 from 30 us to 40 us.  The crystal keeps ringing (tau = 2 Lm / ESR
    # = 0.3 ms), so I(VDD) while off includes the ringing; the static off
    # current is the op case.
    off = (t > 30.2e-6) & (t < 39.9e-6)
    hi = t[(t > 30e-6) & (t < 40e-6) & (clk > a.vdd / 2)]
    rise = edges(t, clk, a.vdd / 2)
    r = {"clk_off_max": float(clk[off].max()), "idd_off_ringing": float(-idd[off].mean()),
         "xi_off_pp": float(xi[off].max() - xi[off].min()),
         "t_stop": float(hi[-1] - 30e-6) if len(hi) else 0.0,
         "first_rise_after_en1": float(rise[rise > 40e-6][0] - 40e-6) if (rise > 40e-6).any() else float("nan")}
    print(f"  en: REF_CLK low {r['t_stop'] * 1e9:.1f} ns after XTAL_EN=0, max {r['clk_off_max']:.3f} V while off, "
          f"I(VDD) while off (crystal ringing) {r['idd_off_ringing'] * 1e9:.1f} nA, "
          f"first edge {r['first_rise_after_en1'] * 1e9:.1f} ns after XTAL_EN=1")
    np.savetxt(f"{out}/en_env.csv", np.column_stack([t[::20], xi[::20], xo[::20], clk[::20], -idd[::20]]),
               delimiter=",", header="t,xi,xo,ref_clk,idd", comments="", fmt="%.6e")
    return r


# --------------------------------------------------------------------- checks
def check(a, results):
    err = []
    if "op" in results:
        off = results["op"][f"d{a.drv}_e0"]["idd"]
        on = results["op"][f"d{a.drv}_e1"]["idd"]
        if off > LIMITS["idd_off"]:
            err.append(f"I(VDD) off {off * 1e6:.2f} uA > 1 uA")
        if on > LIMITS["idd_on"]:
            err.append(f"I(VDD) on {on * 1e3:.2f} mA > {LIMITS['idd_on'] * 1e3:.1f} mA")
    if "ac" in results:
        # DRV = 11 is the recommended setting for ESR up to 100 Ohm: margin >= 5
        # there; every setting from DRV = 10 up must still give >= 4
        mg = results["ac"][3]["margin"]
        if not mg >= LIMITS["margin_min"]:
            err.append(f"start-up margin (DRV 11) {mg:.1f} < {LIMITS['margin_min']}")
        mg = results["ac"][a.drv]["margin"]
        if not mg >= 4.0:
            err.append(f"start-up margin (DRV {a.drv:02b}) {mg:.1f} < 4")
    if "ss" in results:
        r = results["ss"]
        if not r["dl"] <= LIMITS["dl_max"]:
            err.append(f"drive level {r['dl'] * 1e6:.0f} uW > 200 uW")
        if not LIMITS["duty"][0] <= r["duty"] <= LIMITS["duty"][1]:
            err.append(f"duty {r['duty']:.1f} %")
        if not r["settled"]:
            err.append(f"steady state not reached: R_ext {r['r_ext']:.0f} Ohm, ESR {r['esr']:g} Ohm")
        if not abs(r["ppm"]) <= LIMITS["ppm"]:
            err.append(f"frequency {r['ppm']:+.1f} ppm")
    if "start" in results:
        r = results["start"]
        if not r["t_stable"] <= LIMITS["t_start"]:
            err.append(f"start-up {r['t_stable'] * 1e6:.0f} us")
    if "byp" in results:
        for k, r in results["byp"].items():
            if not (abs(r["f"] / F0 - 1) < 1e-3 and 40 <= r["duty"] <= 60):
                err.append(f"bypass {k}: f {r['f'] / 1e6:.3f} MHz duty {r['duty']:.1f} %")
    if "en" in results:
        r = results["en"]
        if r["clk_off_max"] > 0.1 * a.vdd:
            err.append("REF_CLK not low while disabled")
        if not r["t_stop"] < 50e-9:
            err.append(f"REF_CLK still running {r['t_stop'] * 1e9:.0f} ns after XTAL_EN = 0")
    return err


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cases", nargs="*", default=["op", "ac", "ss", "start", "byp"])
    p.add_argument("--corner", default="tm")
    p.add_argument("--temp", type=float, default=27)
    p.add_argument("--vdd", type=float, default=1.8)
    p.add_argument("--drv", type=int, default=2)
    p.add_argument("--esr", type=float, default=100)
    p.add_argument("--tstart", type=float, default=1.6e-3)
    p.add_argument("--cext", type=float, default=CEXT, help="external C1 = C2 [F]")
    p.add_argument("--tag", default="", help="suffix of the output directory")
    p.add_argument("--burst", type=float, default=0.6, help="ss pre-load burst amplitude [V]")
    p.add_argument("--tss", type=float, default=120e-6, help="ss transient length [s]")
    p.add_argument("--dut", default="tr", help="tr: transistor netlist, beh: ngspice copy of the "
                   "Verilog-A model (sim/afe_xosc_beh.sp), or a netlist path")
    a = p.parse_args()
    a.netlist = {"tr": NETLIST, "beh": os.path.join(HERE, "afe_xosc_beh.sp")}.get(a.dut, a.dut)
    out = os.path.join(ROOT, "build", "xosc", f"{a.corner}_{a.temp:g}_{a.vdd:g}{a.tag}")
    os.makedirs(out, exist_ok=True)
    print(f"{os.path.basename(a.netlist)}: corner {a.corner}, {a.temp:g} C, VDD {a.vdd:g} V, DRV {a.drv}, ESR {a.esr:g} Ohm"
          f"  (Lm {LM * 1e3:.4f} mH, fs {FS / 1e6:.6f} MHz)")
    fn = {"op": case_op, "ac": case_ac, "ss": case_ss, "start": case_start, "byp": case_byp, "en": case_en}
    results = {}
    with cf.ThreadPoolExecutor(max_workers=int(os.environ.get("JOBS", "2"))) as ex:
        futs = {c: ex.submit(fn[c], a, out) for c in a.cases}
        for c, f in futs.items():
            results[c] = f.result()
            json.dump(results[c], open(f"{out}/results_{c}.json", "w"), indent=1, default=float)
    err = check(a, results)
    for e in err:
        print("  ERROR:", e)
    print("TEST PASSED" if not err else f"TEST FAILED: {len(err)} error(s)")


if __name__ == "__main__":
    main()
