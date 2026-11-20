#!/usr/bin/env python3
"""gen_figures.py - figures of the receiver datasheet
(AFE/doc/receiver_datasheet/receiver_datasheet.md)

Usage (from anywhere; numpy only, rsvg-convert for the PNG copies used by Word):
    python3 AFE/doc/receiver_datasheet/gen_figures.py [--no-png]

Transistor data: data/rx_<corner>_*.csv, cut by data/extract_tr.py from the
ngspice runs of AFE/spice/tb/tb_receiver_tr.py at tt (27 C, 3.3 / 1.8 V),
ss (125 C, 3.0 / 1.62 V) and ff (-40 C, 3.6 / 1.98 V), and the printed
results of those runs, data/rx_<corner>_summary.txt.  Model curves: a
sample-by-sample re-implementation of the afe_receiver.va equations
(Schmitt trigger, squelch envelope with bridge / on / off timers, disconnect
timer, output delays) driven by the same line waveform V(p) - V(n) as the
transistor run.  It is not a Spectre run of afe_receiver.va (no Spectre here).
Output: fig/*.svg (+ fig/*.png at 2x).
"""
import os, re, sys, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "pll_datasheet"))
from svgplot import Plot, COLORS, _esc

FIG, DATA = os.path.join(HERE, "fig"), os.path.join(HERE, "data")
B, R, G, O, V, K = COLORS
UI = 1 / 480e6
CORNERS = (("tt", G, None, 1.80, "tt 27 °C 3.3 / 1.8 V"),
           ("ss", R, "6,3", 1.62, "ss 125 °C 3.0 / 1.62 V"),
           ("ff", O, "2,2", 1.98, "ff −40 °C 3.6 / 1.98 V"))
MODEL = dict(v_hys=20e-3, v_off=0.0, t_dly=0.3e-9, v_sq=125e-3, t_sq_on=4e-9, t_sq_off=12e-9,
             t_bridge=1e-9, v_disc=575e-3, t_disc=4e-9, t_dly_sq=0.1e-9, vdd_min=2.97)


# ---------------------------------------------------------------- data
def csv(corner, win):
    f = os.path.join(DATA, f"rx_{corner}_{win}.csv")
    if not os.path.exists(f):
        return None
    a = np.loadtxt(f, delimiter=",", skiprows=1)
    names = open(f).readline().strip().split(",")
    return {n: a[:, i] for i, n in enumerate(names)}


def summary(corner):
    f = os.path.join(DATA, f"rx_{corner}_summary.txt")
    s = open(f).read() if os.path.exists(f) else ""
    num = lambda pat, k=1: float(re.search(pat, s).group(k)) if re.search(pat, s) else float("nan")
    d = dict(
        bias=num(r"bias \(vbp18\) settled ([\d.]+) ns"), on=num(r"outputs enabled \(on\) ([\d.]+) ns"),
        rel400=num(r"400 mV: SQUELCH_A falls ([\d.]+) ns"), rel160=num(r"160 mV alternating: released after ([\d.]+) ns"),
        assert_=num(r"idle: SQUELCH_A rises ([\d.]+) ns"), disc=num(r"static 650 mV: DISC_A rises ([\d.]+) ns"),
        d_rise=num(r"RX_OUT_P delay (\d+) ps rising"), d_fall=num(r"rising / (\d+) ps falling"),
        duty=num(r"duty ([\d.]+) %"), i_off=num(r"supply current ([\d.]+) nA"),
        i_vdd=num(r"RX_VDD (\d+) uA, RX_VDDO"), i_vddo=num(r"RX_VDDO (\d+) uA; with"), i_vddo_d=num(r"data: RX_VDDO (\d+) uA"),
        p400=re.search(r"PRBS7 400 mV: (\d+) bit errors.*delay (\d+) \.\. (\d+) ps", s),
        p150=re.search(r"PRBS7 150 mV: (\d+) bit errors.*delay (\d+) \.\. (\d+) ps", s),
        sqamp=dict((int(a), b == "released") for a, b in re.findall(r"(\d+) mV (released|squelched)", s)),
        uvlo=(num(r"UVLO: off below ([\d.]+) V"), num(r"on again above ([\d.]+) V")),
        passed="TEST PASSED" in s)
    for cm in ("-50", "200", "500"):
        blk = re.search(rf"common mode {cm} mV\n(.*?)(?=\n\S|\Z)", s, re.S)
        b = blk.group(1) if blk else ""
        g = lambda pat: float(re.search(pat, b).group(1)) if re.search(pat, b) else float("nan")
        d["hs" + cm] = (g(r"switches at ([+-][\d.]+)"), g(r"/ ([+-][\d.]+) mV"), g(r"hysteresis ([\d.]+)"))
        d["sq" + cm] = (g(r"squelch DP > DM: ([\d.]+)"), g(r"squelch DM > DP: ([\d.]+)"))
        if cm == "500":
            d["disc_p"], d["disc_n"] = g(r"disconnect DP > DM.*?: ([\d.]+) mV"), g(r"disconnect DM > DP.*?: ([\d.]+) mV")
    return d


# ---------------------------------------------------------------- model
def model(t_ns, vd, m=MODEL):
    """afe_receiver.va on a sampled vd(t): returns RX_OUT_P, SQUELCH_A, DISC_A (0 / 1)"""
    t = t_ns * 1e-9
    n = len(t)
    op, sq, dc = np.zeros(n), np.ones(n), np.zeros(n)
    st = 1 if vd[0] - m["v_off"] > 0 else 0
    act_raw = env = act_f = int(abs(vd[0]) > m["v_sq"])
    dsc_raw, dsc_f = int(abs(vd[0]) > m["v_disc"]), 0
    INF = 1e9
    t_br = t_son = t_soff = t_dchk = INF
    s_st, s_act, s_dsc = np.zeros(n), np.zeros(n), np.zeros(n)
    for i in range(n):
        x, v = t[i], vd[i] - m["v_off"]
        if v > m["v_hys"] / 2: st = 1
        elif v < -m["v_hys"] / 2: st = 0
        raw = abs(vd[i]) > m["v_sq"]
        if raw and not act_raw:
            act_raw, t_br = 1, INF
            if not env:
                env = 1
                if not act_f: t_son = x + m["t_sq_on"]
                t_soff = INF
        elif not raw and act_raw:
            act_raw, t_br = 0, x + m["t_bridge"]
        if x >= t_br:
            t_br = INF
            if not act_raw and env:
                env, t_son = 0, INF
                if act_f: t_soff = x + max(m["t_sq_off"] - m["t_bridge"], 0)
        if x >= t_son:
            t_son = INF
            if env: act_f = 1
        if x >= t_soff:
            t_soff = INF
            if not env: act_f = 0
        draw = abs(vd[i]) > m["v_disc"]
        if draw and not dsc_raw:
            dsc_raw, t_dchk = 1, x + m["t_disc"]
        elif not draw and dsc_raw:
            dsc_raw, dsc_f, t_dchk = 0, 0, INF
        if x >= t_dchk:
            dsc_f, t_dchk = dsc_raw, INF
        s_st[i], s_act[i], s_dsc[i] = st, act_f, dsc_f
    shift = lambda y, d: np.interp(t - d, t, y, left=y[0])
    return shift(s_st, m["t_dly"]), 1 - shift(s_act, m["t_dly_sq"]), shift(s_dsc, m["t_dly_sq"])


def model_env(t_ns, vd, m=MODEL):
    """internal model signals for the timing figure: comparator, envelope, act_f"""
    t = t_ns * 1e-9
    INF = 1e9
    act_raw = env = act_f = 0
    t_br = t_son = t_soff = INF
    out = np.zeros((len(t), 3))
    for i, x in enumerate(t):
        raw = abs(vd[i]) > m["v_sq"]
        if raw and not act_raw:
            act_raw, t_br = 1, INF
            if not env:
                env = 1
                if not act_f: t_son = x + m["t_sq_on"]
                t_soff = INF
        elif not raw and act_raw:
            act_raw, t_br = 0, x + m["t_bridge"]
        if x >= t_br:
            t_br = INF
            if not act_raw and env:
                env, t_son = 0, INF
                if act_f: t_soff = x + max(m["t_sq_off"] - m["t_bridge"], 0)
        if x >= t_son:
            t_son = INF
            if env: act_f = 1
        if x >= t_soff:
            t_soff = INF
            if not env: act_f = 0
        out[i] = act_raw, env, act_f
    return out


def line_bits(t_ns, t0_ns, bits, amp, te=0.625):
    """vd(t) of tb_receiver_tr.Line.bits: J = +amp, K = -amp, linear edges te ns centred on the bit boundary"""
    ui = UI * 1e9
    pts = [(t0_ns, 0.0), (t0_ns + 0.1, amp if bits[0] else -amp)]
    lvl = amp if bits[0] else -amp
    for i, b in enumerate(bits[1:], 1):
        v = amp if b else -amp
        if v != lvl:
            ts = t0_ns + i * ui - te / 2
            pts += [(ts, lvl), (ts + te, v)]
            lvl = v
    tend = t0_ns + len(bits) * ui
    pts += [(tend, lvl), (tend + 0.1, 0.0)]
    x, y = zip(*pts)
    return np.interp(t_ns, x, y, left=0.0, right=0.0)


# ---------------------------------------------------------------- helpers
def save_raw(name, w, h, s):
    open(os.path.join(FIG, name + ".svg"), "w").write(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'font-family="Arial, Helvetica, sans-serif"><rect width="{w}" height="{h}" fill="white"/>'
        + "\n".join(s) + "</svg>")


ARROW = ('<defs><marker id="ah" markerWidth="9" markerHeight="8" refX="8" refY="4" orient="auto">'
         '<polygon points="0,0 9,4 0,8" fill="#222"/></marker>'
         '<marker id="ad" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">'
         '<polygon points="0,0 8,4 0,8" fill="#555"/></marker></defs>')


def dim(p, ax, a, b, y, text, col="#555", above=True):
    """dimension arrow between x = a and x = b at data height y"""
    X1, X2, Y = ax._tx(a), ax._tx(b), ax._ty(y)
    p.raw(f'<line x1="{X1:.1f}" y1="{Y:.1f}" x2="{X2:.1f}" y2="{Y:.1f}" stroke="{col}" stroke-width="1.2" '
          f'marker-start="url(#adr)" marker-end="url(#ad)"/>')
    p.raw(f'<text x="{(X1 + X2) / 2:.1f}" y="{Y + (-5 if above else 14):.1f}" font-size="11" fill="{col}" '
          f'text-anchor="middle">{_esc(text)}</text>')


DIM_DEFS = ('<defs><marker id="ad" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
            '<polygon points="0,0 8,4 0,8" fill="#555"/></marker>'
            '<marker id="adr" markerWidth="8" markerHeight="8" refX="1" refY="4" orient="auto">'
            '<polygon points="8,0 0,4 8,8" fill="#555"/></marker></defs>')


# ---------------------------------------------------------------- diagrams
def fig_block():
    s = [ARROW]
    def box(x, y, w, h, t, sub=None, fill="#eef3fb", sub2=None):
        s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="#1f4e9c" stroke-width="1.8"/>')
        dy = -6 if sub2 else 0
        s.append(f'<text x="{x + w / 2}" y="{y + h / 2 + (dy if sub else 5)}" font-size="13.5" font-weight="bold" text-anchor="middle">{_esc(t)}</text>')
        if sub:
            s.append(f'<text x="{x + w / 2}" y="{y + h / 2 + 15 + dy}" font-size="11" text-anchor="middle">{_esc(sub)}</text>')
        if sub2:
            s.append(f'<text x="{x + w / 2}" y="{y + h / 2 + 28 + dy}" font-size="11" text-anchor="middle">{_esc(sub2)}</text>')
    def arr(pts, col="#222"):
        s.append(f'<polyline points="{" ".join(f"{a},{b}" for a, b in pts)}" fill="none" stroke="{col}" stroke-width="1.8" marker-end="url(#ah)"/>')
    def txt(x, y, t, a="start", sz=11.5, col="#222", w="normal"):
        s.append(f'<text x="{x}" y="{y}" font-size="{sz}" fill="{col}" font-weight="{w}" text-anchor="{a}">{_esc(t)}</text>')
    def pin(x, y, t, side="l"):
        s.append(f'<rect x="{x - 5}" y="{y - 5}" width="10" height="10" fill="#1f4e9c"/>')
        txt(x + (-10 if side == "l" else 10), y + 4, t, "end" if side == "l" else "start", 12.5, "#222", "bold")
    # supply domains
    s.append('<rect x="130" y="30" width="250" height="450" rx="8" fill="#fbf3e6" stroke="#d4860b" stroke-dasharray="6,4"/>')
    txt(140, 48, "RX_VDD 3.3 V: input stages (pch33)", sz=12, col="#a0640a")
    s.append('<rect x="390" y="30" width="470" height="450" rx="8" fill="#f3f7ee" stroke="#2e8b57" stroke-dasharray="6,4"/>')
    txt(400, 48, "RX_VDDO 1.8 V: comparators, timers, logic, outputs", sz=12, col="#22663f")
    pin(130, 110, "RX_IN_P"); pin(130, 140, "RX_IN_N"); pin(130, 420, "RX_EN"); pin(130, 455, "RX_VREF")
    pin(860, 105, "RX_OUT_P", "r"); pin(860, 135, "RX_OUT_N", "r"); pin(860, 240, "SQUELCH_A", "r"); pin(860, 340, "DISC_A", "r")
    box(170, 90, 180, 70, "HS preamp", "PMOS pair, 200 µA, 3 kΩ")
    box(420, 90, 150, 70, "Comparator", "hysteresis ±9 mV")
    box(620, 90, 150, 70, "Output gates", "& on, delay 0.9 ns")
    box(170, 200, 180, 70, "Squelch preamps ×2", "|vd| > 105 mV ref (DDA)")
    box(420, 200, 150, 70, "2 comparators", "OR")
    box(620, 195, 150, 80, "Squelch filter", "bridge 3 ns, on 6 ns,", sub2="off 10 ns, SR latch")
    box(170, 300, 180, 70, "Disconnect preamps ×2", "|vd| > 560 mV ref (DDA)")
    box(420, 300, 150, 70, "2 comparators", "OR")
    box(620, 300, 150, 70, "Timer", "4 ns, fall at once")
    box(420, 395, 150, 75, "Bias, refs", "I0 = V(RX_VREF) / 60 kΩ", fill="#fff", sub2="poly string → thresholds")
    box(620, 395, 150, 75, "Enable / UVLO", "ready ≈ 170 ns,", fill="#fff", sub2="RX_VDD > 2.95 V")
    for y in (110, 140):
        arr([(130, y), (170, y)])
    s.append('<polyline points="150,110 150,235 170,235" fill="none" stroke="#222" stroke-width="1.4"/>')
    s.append('<polyline points="150,235 150,335 170,335" fill="none" stroke="#222" stroke-width="1.4"/>')
    s.append('<circle cx="150" cy="110" r="3" fill="#222"/><circle cx="150" cy="235" r="3" fill="#222"/>')
    txt(155, 290, "DP, DM", sz=10.5, col="#555")
    arr([(350, 125), (420, 125)]); txt(385, 118, "xa / ya", "middle", 10.5)
    arr([(570, 125), (620, 125)]); arr([(770, 105), (855, 105)]); arr([(770, 135), (855, 135)])
    arr([(350, 235), (420, 235)]); arr([(570, 235), (620, 235)]); arr([(770, 240), (855, 240)])
    arr([(350, 335), (420, 335)]); arr([(570, 335), (620, 335)]); arr([(770, 340), (855, 340)])
    arr([(130, 420), (420, 420)]); arr([(130, 455), (420, 455)])
    arr([(570, 432), (620, 432)])
    s.append('<polyline points="770,432 800,432 800,165" fill="none" stroke="#c0392b" stroke-width="1.6" stroke-dasharray="5,3"/>')
    for y in (165, 280, 375):
        s.append(f'<line x1="800" y1="{y}" x2="772" y2="{y}" stroke="#c0392b" stroke-width="1.4" stroke-dasharray="5,3" marker-end="url(#ah)"/>')
    txt(806, 395, "on", sz=11.5, col="#c0392b", w="bold")
    txt(495, 388, "I0, vbp18 / vbp33, references → all preamps and comparators", "middle", 10.5, "#6c3483")
    txt(495, 505, "Off (RX_EN = 0, RX_VDD low or not ready): RX_OUT_P = 0, RX_OUT_N = 1, SQUELCH_A = 1, DISC_A = 0, all bias currents off",
        "middle", 11.5, "#c0392b")
    save_raw("block_diagram", 1000, 520, s)


def fig_squelch_timing():
    """model squelch filter on a synthetic line: burst, packet, idle"""
    t = np.arange(0, 70, 0.005)
    vd = line_bits(t, 3.0, [1], 0.4)[:]
    vd[(t > 3.0) & (t < 5.0)] = 0.4                        # 2 ns burst
    vd[(t >= 5.0) & (t < 5.1)] = 0.4 * (1 - (t[(t >= 5.0) & (t < 5.1)] - 5.0) / 0.1)
    vd[t >= 5.1] = 0.0
    pk = line_bits(t, 14.0, [i % 2 for i in range(16)], 0.4)
    vd = vd + pk
    sig = model_env(t, vd)
    _, sq, _ = model(t, vd)
    p = Plot(900, 600)
    p.raw(DIM_DEFS)
    rows = [("|DP − DM|  [mV]", np.abs(vd) * 1e3, (0, 450)), ("comparator |vd| > v_sq", sig[:, 0], (-0.2, 1.3)),
            ("envelope (bridges dips < t_bridge)", sig[:, 1], (-0.2, 1.3)), ("SQUELCH_A", sq, (-0.2, 1.3))]
    axs = []
    for k, (lab, y, yl) in enumerate(rows):
        a = p.panel(110, 40 + k * 130, 760, 90, (0, 70), yl, xlabel="Time  [ns]" if k == 3 else "",
                    ylabel="" if k else "mV", title=lab, yticks=[0, 200, 400] if k == 0 else [0, 1])
        a.line(t, y, [K, B, B, R][k], 1.6 if k == 0 else 2)
        axs.append(a)
    axs[0].hline(125, R, "4,3", text="v_sq = 125 mV (transistor: 105 mV reference, 110 mV static)", below=True)
    dim(p, axs[3], 3.0, 7.0, 0.55, "burst ignored", above=False)
    dim(p, axs[3], 14.0, 18.1, 0.55, "t_sq_on 4 ns", above=True)
    end = 14.0 + 16 * UI * 1e9 + 0.1
    dim(p, axs[3], end, end + 12, 0.45, "t_sq_off 12 ns in total (t_bridge + 11 ns)", above=False)
    dim(p, axs[2], end, end + 1, 0.45, "")
    axs[2].text(end + 1.6, 0.4, "t_bridge 1 ns", K, 11)
    axs[1].text(16, 1.15, "dips at every transition (≈ 0.2 ns at 400 mV with 625 ps edges)", B, 11)
    p.save(os.path.join(FIG, "squelch_timing.svg"))


# ---------------------------------------------------------------- plots
def fig_thresholds(S):
    p = Plot(900, 420)
    labs = ["static, CM −50 mV", "static, CM 200 mV", "static, CM 500 mV", "480 Mbit/s data (bar)"]
    a = p.panel(200, 40, 400, 300, (90, 160), (-0.6, 3.6), xlabel="Differential threshold  [mV]",
                title="Squelch threshold", yticks=[0, 1, 2, 3], yfmt=lambda v: labs[int(round(v))], legend="br")
    p.s.append(f'<rect x="{a._tx(100):.1f}" y="40" width="{a._tx(150) - a._tx(100):.1f}" height="300" fill="#2e8b57" fill-opacity="0.08"/>')
    a.text(101, 3.45, "USB 2.0: squelch < 100 mV, active > 150 mV", G, 10.5, "start")
    a.vline(125, B, "5,4")
    for j, (c, col, d, vddo, lab) in enumerate(CORNERS):
        dd = S[c]
        ys = [0, 1, 2]
        xs = [dd["sq-50"][0], dd["sq200"][0], dd["sq500"][0]]
        a.points(xs, [y + 0.15 * (j - 1) for y in ys], col, lab, marker="os^"[j])
        am = dd["sqamp"]
        rel = [x for x, r in sorted(am.items()) if r]
        sqd = [x for x, r in sorted(am.items()) if not r]
        if rel and sqd:
            y = 3 + 0.15 * (j - 1)
            a.line([max(sqd), min(rel)], [y, y], col, 5)
    a.points([125] * 4, [0, 1, 2, 3], B, "model (125 mV)", r=3, marker="o")
    b = p.panel(660, 40, 200, 300, (500, 650), (-0.6, 1.6), xlabel="[mV]", title="Disconnect threshold",
                yticks=[0, 1], yfmt=lambda v: ["DP > DM", "DM > DP"][int(round(v))], legend="br")
    p.s.append(f'<rect x="{b._tx(525):.1f}" y="40" width="{b._tx(625) - b._tx(525):.1f}" height="300" fill="#2e8b57" fill-opacity="0.08"/>')
    b.vline(575, B, "5,4")
    for j, (c, col, d, vddo, lab) in enumerate(CORNERS):
        b.points([S[c]["disc_p"], S[c]["disc_n"]], [0 + 0.15 * (j - 1), 1 + 0.15 * (j - 1)], col, marker="os^"[j])
    b.text(645, 1.45, "USB window", G, 10.5, "end")
    # move the y labels of b inward: they are short
    p.save(os.path.join(FIG, "thresholds.svg"))


def fig_hs_transfer(S):
    p = Plot(900, 420)
    a = p.panel(90, 40, 770, 300, (-25, 25), (-0.1, 1.15), xlabel="DP − DM  [mV]  (slow ramp, common mode 200 mV)",
                ylabel="RX_OUT_P / RX_VDDO", title="HS receiver transfer characteristic (hysteresis)", legend="tl")
    xm = [-25, 10, 10, 25]; a.line(xm, [0, 0, 1, 1], B, 2.6, None, "model (v_hys 20 mV)")
    a.line([25, -10, -10, -25], [1, 1, 0, 0], B, 2.6)
    for c, col, d, vddo, lab in CORNERS:
        h = csv(c, "dc2_hs")
        if h is None:
            continue
        hy = S[c]["hs200"]
        a.line(h["vd"] * 1e3, h["rx_out_p"] / vddo, col, 1.8, d, f"{lab}: {hy[1]:+.1f} / {hy[0]:+.1f} mV")
    a.text(12, 0.45, "rising: switches at +v_hys/2", K, 11)
    a.text(-12, 0.55, "falling: at −v_hys/2", K, 11, "end")
    p.save(os.path.join(FIG, "hs_transfer.svg"))


def stack_window(name, win, t0, xlim, title, sig_rows, S, note=None, xlab=None, leg="tr"):
    """vd on top, then one panel per signal: transistor corners + model"""
    tt = csv("tt", win)
    if tt is None:
        return
    n = len(sig_rows) + 1
    h = 120
    p = Plot(900, 70 + n * (h + 40) + 20)
    p.raw(DIM_DEFS)
    x = tt["t_ns"] - t0
    vmax = np.max(np.abs(tt["vd"])) * 1e3
    lim = 50 * np.ceil(vmax * 1.15 / 50)
    a = p.panel(100, 40, 760, h, xlim, (0, lim) if tt["vd"].min() > -0.01 else (-lim, lim), ylabel="mV", title=title)
    a.line(x, tt["vd"] * 1e3, K, 1.4)
    axs = [a]
    mo = dict(zip(("rx_out_p", "squelch_a", "disc_a"), model(tt["t_ns"], tt["vd"])))
    for k, (col_name, lab) in enumerate(sig_rows, 1):
        last = k == n - 1
        b = p.panel(100, 40 + k * (h + 40), 760, h, xlim, (-0.15, 1.25) if col_name == "act" else (-0.15, 2.3),
                    xlabel=(xlab or "") if last else "", ylabel="/ VDDO", title=lab, yticks=[0, 1], legend=leg)
        if col_name == "act":
            b.line(x, tt["act"] / 1.8, G, 1.5)
        else:
            b.line(x, mo[col_name], B, 2.4, None, "model")
            for c, col, d, vddo, lab2 in CORNERS:
                w = csv(c, win)
                if w is not None:
                    b.line(w["t_ns"] - t0, w[col_name] / vddo, col, 1.6, d, "transistor " + lab2)
        axs.append(b)
    p.save(os.path.join(FIG, name + ".svg"))
    return p, axs


def fig_release(S):
    stack_window("squelch_release", "a400", 300, (-2, 14), "Line becomes active: 400 mV alternating J / K at 480 Mbit/s (DP − DM)",
                 [("act", "Squelch comparators (transistor tt)"), ("squelch_a", "SQUELCH_A")], S,
                 xlab="Time after the first line transition  [ns]")


def fig_assert(S):
    stack_window("squelch_assert", "idle", 400, (-6, 20), "Line goes idle after the last bit (DP − DM)",
                 [("act", "Squelch comparators (transistor tt)"), ("squelch_a", "SQUELCH_A")], S,
                 xlab="Time after the end of the last bit  [ns]", leg="tl")


def fig_160(S):
    stack_window("squelch_160mv", "a160", 580, (-1, 13), "160 mV alternating data (just above the USB 150 mV limit)",
                 [("act", "Squelch comparators (transistor tt): short pulses, the bridge timer fills the gaps"),
                  ("squelch_a", "SQUELCH_A")], S, xlab="Time after the first line transition  [ns]")


def fig_disc(S):
    stack_window("disconnect", "disc", 770, (-3, 10), "Static differential step 0 → 650 mV (disconnect level, other wire at 0 V)",
                 [("disc_a", "DISC_A")], S, xlab="Time after the step  [ns]", leg="tl")


def fig_sqamp(S):
    amps = [100, 110, 120, 130, 140, 145, 150, 155, 160, 170]
    p = Plot(900, 330)
    rows = ["model"] + [c[4] for c in CORNERS]
    a = p.panel(220, 40, 640, 220, (95, 175), (-0.6, 3.6), xlabel="Amplitude of alternating 480 Mbit/s data  [mV]",
                title="Squelch on 480 Mbit/s data (40 bits per amplitude): released (filled) or squelched (open)",
                yticks=[0, 1, 2, 3], yfmt=lambda v: rows[int(round(v))])
    p.s.append(f'<rect x="{a._tx(100):.1f}" y="40" width="{a._tx(150) - a._tx(100):.1f}" height="220" fill="#2e8b57" fill-opacity="0.08"/>')
    a.vline(100, G, "4,3", "USB: squelched", top=True, left=True); a.vline(150, G, "4,3", "USB: released", top=True)
    for j, col in enumerate([B] + [c[1] for c in CORNERS]):
        for amp in amps:
            if j == 0:
                rel = amp > 125
            else:
                rel = S[CORNERS[j - 1][0]]["sqamp"].get(amp)
                if rel is None:
                    continue
            X, Y = a._tx(amp), a._ty(j)
            p.s.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="7" fill="{col if rel else "white"}" stroke="{col}" stroke-width="2"/>')
    p.save(os.path.join(FIG, "squelch_amplitude.svg"))


def fig_rx_delay(S):
    p = Plot(900, 470)
    a = p.panel(90, 40, 770, 120, (8, 16), (-450, 450), ylabel="mV", title="DP − DM: 400 mV alternating data, 625 ps edges",
                yticks=[-400, 0, 400])
    b = p.panel(90, 200, 770, 200, (8, 16), (-0.1, 1.95), xlabel="Time after the first line transition  [ns]",
                ylabel="RX_OUT_P / VDDO", title="RX_OUT_P: model 0.3 ns, transistor 0.73 … 1.24 ns after the zero crossing",
                legend="tr", yticks=[0, 0.5, 1])
    tt = csv("tt", "a400")
    x = tt["t_ns"] - 300
    a.line(x, tt["vd"] * 1e3, K, 1.6)
    a.hline(0, K, "2,2")
    mo, _, _ = model(tt["t_ns"], tt["vd"])
    b.line(x, mo, B, 2.4, None, "model (t_dly 0.3 ns)")
    for c, col, d, vddo, lab in CORNERS:
        w = csv(c, "a400")
        dd = S[c]
        b.line(w["t_ns"] - 300, w["rx_out_p"] / vddo, col, 1.8, d,
               f"transistor {lab}: {dd['d_rise']:.0f} / {dd['d_fall']:.0f} ps")
    b.hline(0.5, K, "2,2")
    p.save(os.path.join(FIG, "rx_delay.svg"))


def fig_eye(S):
    p = Plot(900, 640)
    ui = UI * 1e9
    for row, amp in enumerate((400, 150)):
        for j, (c, col, d, vddo, lab) in enumerate(CORNERS):
            w = csv(c, f"prbs{amp}")
            if w is None:
                continue
            m = S[c]["p150" if amp == 150 else "p400"]
            dly = (float(m.group(2)) + float(m.group(3))) / 2e3 if m else 1.0
            t0 = (1520 if amp == 150 else 1200)
            ax = p.panel(80 + j * 270, 50 + row * 290, 240, 210, (0, 2 * ui), (-0.1, 1.1),
                         xlabel="Time in 2 UI  [ns]" if row == 1 else "", ylabel="RX_OUT_P / VDDO" if j == 0 else "",
                         title=(f"{amp} mV, {c}: {int(m.group(1))} errors, {m.group(2)}–{m.group(3)} ps" if m else f"{amp} mV, {c}"), xticks=[0, 1, 2, 3, 4], yticks=[0, 0.5, 1])
            tt = w["t_ns"] - t0 - dly                   # bit boundaries (+ delay) at k ui, centres at (k + 1/2) ui
            for k in range(8, 124, 2):
                sel = (tt >= k * ui) & (tt <= (k + 2) * ui)
                ax.line(tt[sel] - k * ui, w["rx_out_p"][sel] / vddo, col, 0.8)
            ax.vline(ui / 2, K, "2,2"); ax.vline(1.5 * ui, K, "2,2")
    p.s.append('<text x="450" y="22" font-size="13" font-weight="bold" text-anchor="middle">RX_OUT_P eye, PRBS7 at 480 Mbit/s '
               '(118 bits, folded at the mean delay; dashed: bit centres)</text>')
    p.save(os.path.join(FIG, "eye.svg"))


def fig_enable(S):
    p = Plot(900, 560)
    a = p.panel(90, 40, 770, 150, (-10, 250), (0, 3.0), ylabel="V", title="vbp18 (gate of the 1.8 V current sources)", legend="tr")
    b = p.panel(90, 230, 770, 110, (-10, 250), (-0.15, 2.4), ylabel="/ VDDO", title="on (bias settled, ready timer, UVLO)",
                yticks=[0, 1], legend="tl")
    c_ = p.panel(90, 380, 770, 120, (-10, 250), (0, 2000), xlabel="Time after RX_EN rises  [ns]", ylabel="µA",
                 title="Supply current, transistor tt (idle line)", legend="br")
    for c, col, d, vddo, lab in CORNERS:
        w = csv(c, "bias")
        if w is None:
            continue
        x = w["t_ns"] - 20
        a.line(x, w["vbp18"], col, 1.8, d, f"{lab}: settled {S[c]['bias']:.0f} ns")
        b.line(x, w["on"] / vddo, col, 1.8, d, f"{lab}: on after {S[c]['on']:.0f} ns")
        if c == "tt":
            c_.line(x, w["i_vdd_ua"], O, 1.6, None, "RX_VDD (3.3 V)")
            c_.line(x, w["i_vddo_ua"], V, 1.6, None, "RX_VDDO (1.8 V)")
    b.text(100, 0.3, "model: instant", B, 11)
    p.save(os.path.join(FIG, "enable.svg"))


def fig_uvlo(S):
    p = Plot(900, 400)
    a = p.panel(90, 40, 770, 280, (2.85, 3.1), (-0.1, 1.95), xlabel="RX_VDD  [V]  (ramp 3.3 → 2.8 → 3.3 V in 600 ns)",
                ylabel="on / VDDO", title="Under-voltage lock-out of the receiver (outputs enabled)", legend="tl", yticks=[0, 0.5, 1])
    a.line([2.8, 2.97, 2.97, 3.3], [0, 0, 1, 1], B, 2.4, None, "model: vdd_min 2.97 V")
    for c, col, d, vddo, lab in CORNERS:
        w = csv(c, "dc2_uvlo")
        if w is None:
            continue
        u = S[c]["uvlo"]
        a.line(w["rx_vdd"], w["on"] / vddo, col, 1.8, d, f"{lab}: off < {u[0]:.3f} V, on > {u[1]:.3f} V")
    p.s.append(f'<rect x="{a._tx(2.97):.1f}" y="40" width="{a._tx(3.0) - a._tx(2.97):.1f}" height="280" fill="#c0392b" fill-opacity="0.07"/>')
    a.text(3.003, 0.6, "3.0 V: lowest RX_VDD (3.3 V − 10 %)", R, 10.5, "start")
    p.save(os.path.join(FIG, "uvlo.svg"))


def fig_power(S):
    p = Plot(900, 380)
    s = p.s
    a = p.panel(90, 40, 430, 280, (-0.5, 2.5), (0, 1500), ylabel="µA", title="Supply currents (transistor)",
                xticks=[0, 1, 2], xfmt=lambda v: ["tt", "ss 125 °C", "ff −40 °C"][int(round(v))], legend="tl")
    items = (("i_vdd", O, "RX_VDD (3.3 V)"), ("i_vddo", V, "RX_VDDO idle (squelched)"), ("i_vddo_d", G, "RX_VDDO, 400 mV data"))
    for j, (c, *_r) in enumerate(CORNERS):
        for k, (key, col, lab) in enumerate(items):
            v = S[c][key]
            x0 = a._tx(j - 0.33 + k * 0.22)
            x1 = a._tx(j - 0.33 + (k + 1) * 0.22) - 2
            y = a._ty(v)
            s.append(f'<rect x="{x0:.1f}" y="{y:.1f}" width="{x1 - x0:.1f}" height="{a._ty(0) - y:.1f}" fill="{col}"/>')
            s.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{y - 4:.1f}" font-size="10" text-anchor="middle">{v:.0f}</text>')
        if j == 0:
            for key, col, lab in items:
                a.leg.append((lab, col, None, "line"))
    b = p.panel(620, 40, 260, 280, (0, 1), (0, 950), ylabel="µA", title="RX_VDD at tt, by block", xticks=[], legend="tr")
    parts = (("HS pair", 200, B), ("squelch preamps", 400, R), ("disconnect preamps", 160, G), ("bias chain", 80, O),
             ("references", 20, V), ("UVLO divider", 6, K))
    acc = 0
    for nm, v, col in parts:
        y0, y1 = b._ty(acc), b._ty(acc + v)
        s.append(f'<rect x="{b._tx(0.04):.1f}" y="{y1:.1f}" width="{b._tx(0.32) - b._tx(0.04):.1f}" height="{y0 - y1:.1f}" fill="{col}" stroke="white"/>')
        if v >= 100:
            s.append(f'<text x="{b._tx(0.36):.1f}" y="{(y0 + y1) / 2 + 4:.1f}" font-size="10.5">{nm} {v} µA</text>')
        acc += v
    s.append(f'<text x="{b._tx(0.36):.1f}" y="{b._ty(acc) - 4:.1f}" font-size="10.5">bias 80, refs 20, UVLO 6 µA</text>')
    p.save(os.path.join(FIG, "supply_current.svg"))


def fig_timing_summary(S):
    p = Plot(900, 380)
    rows = ["SQUELCH_A release, 400 mV (≤ 12 ns)", "SQUELCH_A release, 160 mV (≤ 12 ns)", "SQUELCH_A assertion (6 … 16.7 ns)", "DISC_A after 650 mV (no limit)"]
    a = p.panel(290, 40, 570, 270, (0, 20), (-0.6, 3.6), xlabel="Delay  [ns]", title="Squelch and disconnect timing against the requirements",
                yticks=[0, 1, 2, 3], yfmt=lambda v: rows[int(round(v))], legend="br")
    req = ((0, 12, "≤ 12 ns (spec 4.2, A3)"), (0, 12, "≤ 12 ns"), (6, 16.7, "6 … 16.7 ns (hold ≥ 6 ns, < 8 bits)"), (None, None, "no limit (sampled in the EOP)"))
    for k, (lo, hi, txt) in enumerate(req):
        if lo is not None:
            y0, y1 = a._ty(k + 0.38), a._ty(k - 0.38)
            p.s.append(f'<rect x="{a._tx(lo):.1f}" y="{y0:.1f}" width="{a._tx(hi) - a._tx(lo):.1f}" height="{y1 - y0:.1f}" fill="#2e8b57" fill-opacity="0.10"/>')
    mod = [4.1, 4.1, 12.1, 4.1]
    a.points(mod, [0, 1, 2, 3], B, "model", marker="o")
    for j, (c, col, d, vddo, lab) in enumerate(CORNERS):
        dd = S[c]
        a.points([dd["rel400"], dd["rel160"], dd["assert_"], dd["disc"]], [k + 0.14 * (j + 1) for k in range(4)], col,
                 "transistor " + lab, marker="os^"[j])
    p.save(os.path.join(FIG, "timing_summary.svg"))


# ---------------------------------------------------------------- main
def main():
    os.makedirs(FIG, exist_ok=True)
    S = {c[0]: summary(c[0]) for c in CORNERS}
    for c in S:
        d = S[c]
        print(c, "passed" if d["passed"] else "NOT PASSED / missing", {k: d[k] for k in
              ("bias", "on", "rel400", "rel160", "assert_", "disc", "d_rise", "d_fall", "duty", "i_off", "i_vdd", "i_vddo", "i_vddo_d", "uvlo")})
        print("  hs", d["hs-50"], d["hs200"], d["hs500"], " sq", d["sq-50"], d["sq200"], d["sq500"],
              " disc", d.get("disc_p"), d.get("disc_n"), " sqamp", d["sqamp"])
    # model checks on the transistor stimulus (tt)
    for win, t0 in (("a400", 300), ("idle", 400), ("a160", 580), ("disc", 770)):
        w = csv("tt", win)
        if w is None:
            continue
        op, sq, dc = model(w["t_ns"], w["vd"])
        f = lambda y, rising: (w["t_ns"][np.argmax(y > 0.5) if rising else np.argmax(y < 0.5)] - t0) if (np.any(y > 0.5) if rising else np.any(y < 0.5)) else None
        print(f"model {win}: SQUELCH_A fall {f(1 - sq, True)}, rise {f(sq, True) if win == 'idle' else '-'}, DISC_A rise {f(dc, True)}")
    fig_block(); fig_squelch_timing(); fig_thresholds(S); fig_hs_transfer(S)
    fig_release(S); fig_assert(S); fig_160(S); fig_disc(S); fig_sqamp(S)
    fig_rx_delay(S); fig_eye(S); fig_enable(S); fig_uvlo(S); fig_power(S); fig_timing_summary(S)
    if "--no-png" not in sys.argv:
        for f in sorted(os.listdir(FIG)):
            if f.endswith(".svg"):
                subprocess.run(["rsvg-convert", "-z", "2", "-o", os.path.join(FIG, f[:-4] + ".png"), os.path.join(FIG, f)], check=True)
    print("figures in", FIG)


if __name__ == "__main__":
    main()
