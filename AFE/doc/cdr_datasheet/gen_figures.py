#!/usr/bin/env python3
"""gen_figures.py - figures of the CDR datasheet (AFE/doc/cdr_datasheet/cdr_datasheet.md)

Usage (from anywhere; numpy only, rsvg-convert for the PNG copies used by Word):
    python3 AFE/doc/cdr_datasheet/gen_figures.py [--no-png] [--quick]

Model figures come from a behavioural bang-bang simulation with the
equations of afe_cdr.va (Alexander PD on the rising / falling VCO edges,
charge pump held for one VCO period after each decision, R8 + C2 filter,
VCO f = f_coarse * (1 + ppm_mis) + kvco_f * (V(CDR_CH_OUT) - vf_mid)).
It is evaluated once per VCO period; C1 (0.1 pF) is neglected, its time
constant with R8 is 0.1 ns.  It is not a Spectre run of afe_cdr.va (no
Spectre here).  The same simulation with the transistor values (icp 50 uA,
R8 2 kOhm, C2 40 pF, K_fine per corner) stands in for afe_cdr_tr.sp where
no ngspice data exists.  Transistor data: data/tr_*.csv (extract_tr.py, from
the AFE/spice/tb/tb_cdr_tr.py runs) and data/vco_tr.txt (cdr_schematic.md
4.1).  Output: fig/*.svg (+ fig/*.png at 2x).
"""
import os, sys, bisect, random, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "pll_datasheet"))
from svgplot import Plot, COLORS, _esc

FIG, DATA = os.path.join(HERE, "fig"), os.path.join(HERE, "data")
B, R, G, O, V, K = COLORS
F_BIT = 480e6
UI = 1 / F_BIT
QUICK = "--quick" in sys.argv

# ---------------------------------------------------------------- parameters
P = dict(name="model", icp=100e-6, r8=1e3, c2=500e-12, c1=0.1e-12, kf=300e6)
P_TT = dict(name="transistor values, tt", icp=50e-6, r8=2e3, c2=40e-12, c1=0.13e-12, kf=301e6)
P_SS = dict(P_TT, name="transistor values, ss 125 °C 1.62 V", kf=139e6)
P_FF = dict(P_TT, name="transistor values, ff −40 °C 1.98 V", kf=355e6)


def prop_step(p):
    """phase step of one decision in UI (proportional path, one bit long)"""
    return p["icp"] * p["r8"] * p["kf"] / F_BIT


def int_step(p):
    """frequency step of one net decision, relative (integral path)"""
    return p["icp"] * UI / p["c2"] * p["kf"] / F_BIT


# ---------------------------------------------------------------- stimulus
def prbs7(n, seed):
    s, out = seed & 0x7F or 1, []
    for _ in range(n):
        b = ((s >> 6) ^ (s >> 5)) & 1
        s = ((s << 1) | b) & 0x7F
        out.append(b)
    return out


def nrzi_stuffed(data, cur):
    """USB NRZI (0 = toggle) with bit stuffing after six 1s; returns line levels"""
    lvl, ones = [], 0
    for b in data:
        if b:
            ones += 1
            lvl.append(cur)
            if ones == 6:
                cur = 1 - cur; lvl.append(cur); ones = 0
        else:
            ones = 0
            cur = 1 - cur
            lvl.append(cur)
    return lvl


def packet(n_pay, rng):
    """line levels (1 = J): 12-bit SYNC KJKJKJKJKJKK, stuffed NRZI PRBS7 payload, 8-bit EOP"""
    sync = [0, 1] * 5 + [0, 0]
    pay = nrzi_stuffed(prbs7(n_pay, rng.randrange(1, 127)), sync[-1])
    return sync + pay + [1 - pay[-1]] * 8


# ------------------------------------------------- behavioural bang-bang CDR
def run(bits, p, phase0, ppm=0.0, vc2=0.0, jit=0.0, sj=None, rng=None, warm=0):
    """Simulate one burst.  bits: line levels starting at t = 0 (bit i spans
    [i, i+1) UI_data); the line is 0 before.  phase0: first rising VCO edge at
    phase0 * UI_data (0..1).  ppm: data rate offset against the free-running
    VCO (+ = data faster).  jit: uniform edge jitter +-jit UI on every
    transition.  sj: (A_pp_UI, f_hz) sinusoidal jitter.  Returns arrays of
    the rising edges: bit position, signed offset from the bit centre (UI),
    margin to the nearest transition (UI), sampled bit, correct flag, and
    the final vc2 (V, integral voltage)."""
    ui = UI / (1 + ppm * 1e-6)
    rng = rng or random.Random(1)
    xs, lv = [], [0]
    for i, b in enumerate(bits):
        if b != lv[-1]:
            x = i * ui
            if jit:
                x += rng.uniform(-jit, jit) * ui
            if sj:
                x += 0.5 * sj[0] * ui * np.sin(2 * np.pi * sj[1] * i * ui)
            xs.append(x); lv.append(b)
    t_end = len(bits) * ui
    if sj:   # cell boundaries of every bit (for the slip check)
        ii = np.arange(len(bits) + 1)
        bnd = list(ii * ui + 0.5 * sj[0] * ui * np.sin(2 * np.pi * sj[1] * ii * ui))
    icp, r8, c2, kf = p["icp"], p["r8"], p["c2"], p["kf"]
    t, cp, d_prev, e = (phase0 - 1) * ui, 0, 0, 0
    out = []
    while True:
        f = F_BIT + kf * (vc2 + cp * icp * r8)
        T = 1 / f
        tf = t + T / 2
        e = lv[bisect.bisect_right(xs, tf)]
        tr = t + T
        if tr >= t_end:
            break
        vc2 += cp * icp * T / c2
        j = bisect.bisect_right(xs, tr)
        d = lv[j]
        cp = (-1 if e == d_prev else 1) if d != d_prev else 0
        d_prev = d
        pos = tr / ui
        k = int(pos)
        dist = min(abs(tr - xs[j - 1]) if j > 0 else 9, abs(xs[j] - tr) if j < len(xs) else 9) / ui
        cell = bisect.bisect_right(bnd, tr) - 1 if sj else k
        out.append((pos, pos - k - 0.5, min(dist, 0.5), d, d == bits[k], cell, vc2))
        t = tr
    a = np.array(out, dtype=float)
    return a, vc2


def lock_bits(a, crit="margin", m_min=0.15):
    """tb definition: bits from the packet start to the last edge with margin
    < m_min (crit = margin), or to the last wrong sample (crit = error)"""
    bad = a[:, 2] < m_min if crit == "margin" else a[:, 4] == 0
    idx = np.where(bad)[0]
    return 0 if len(idx) == 0 else int(a[idx[-1], 0]) + 1


def lock_stats(p, jit, n, seed, crit):
    rng = random.Random(seed)
    L = []
    for _ in range(n):
        bits = packet(64, rng)
        a, _ = run(bits, p, rng.random(), ppm=rng.choice((-1000, 0, 1000)), jit=jit, rng=rng)
        L.append(lock_bits(a, crit))
    return np.array(L)


def jtol(p, freqs, n_bits=3000, seed=11):
    """largest sinusoidal jitter (UI p-p) without a bit slip (a data cell skipped
    or sampled twice) after a 300-bit warm-up; noiseless, so the limit is the
    loop's ability to follow the data phase"""
    rng = random.Random(seed)
    stream = nrzi_stuffed(prbs7(20000, 0x2B), 0)
    res = []
    for fj in freqs:
        n = int(max(n_bits, 2.5 * F_BIT / fj)) + 300
        bits = stream * (n // len(stream) + 1)
        bits = bits[:n]
        lo, hi = 0.0, 1000.0
        for _ in range(9 if QUICK else 12):
            mid = (lo * hi) ** 0.5 if lo > 0 else min(1.0, hi / 4)
            a, _ = run(bits, p, 0.5, sj=(mid, fj), rng=rng)
            sel = (a[:, 0] > 300) & (a[:, 0] < len(bits) - mid / 2 - 40)   # skip warm-up and the end of the burst
            ok = np.all(np.diff(a[sel][:, 5]) == 1)   # no bit skipped or sampled twice
            lo, hi = (mid, hi) if ok else (lo, mid)
            if lo > 0 and hi / lo < 1.03:
                break
        res.append(lo)
    return np.array(res)


# ---------------------------------------------------------------- data files
def load_tr(case):
    fn = os.path.join(DATA, f"tr_{case}.csv")
    return np.loadtxt(fn, delimiter=",", skiprows=1) if os.path.exists(fn) else None


def load_vco():
    rows = [l.split() for l in open(os.path.join(DATA, "vco_tr.txt")) if l.strip() and not l.startswith("#")]
    d = {}
    for c, vc, f in rows:
        d.setdefault(c, []).append((float(vc), float(f)))
    return {c: np.array(sorted(v)).T for c, v in d.items()}


def save_raw(name, w, h, s):
    open(os.path.join(FIG, name + ".svg"), "w").write(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'font-family="Arial, Helvetica, sans-serif"><rect width="{w}" height="{h}" fill="white"/>'
        + "\n".join(s) + "</svg>")


ARROW = ('<defs><marker id="ah" markerWidth="9" markerHeight="8" refX="8" refY="4" orient="auto">'
         '<polygon points="0,0 9,4 0,8" fill="#222"/></marker></defs>')


# ---------------------------------------------------------------- diagrams
def fig_block():
    s = [ARROW]
    def box(x, y, w, h, t, sub=None, fill="#eef3fb"):
        s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="#1f4e9c" stroke-width="1.8"/>')
        s.append(f'<text x="{x + w / 2}" y="{y + h / 2 + (0 if sub else 5)}" font-size="14" font-weight="bold" text-anchor="middle">{_esc(t)}</text>')
        if sub:
            s.append(f'<text x="{x + w / 2}" y="{y + h / 2 + 17}" font-size="11.5" text-anchor="middle">{_esc(sub)}</text>')
    def arr(pts, lab=None, lx=0, ly=-6, anchor="middle", col="#222"):
        s.append(f'<polyline points="{" ".join(f"{a},{b}" for a, b in pts)}" fill="none" stroke="{col}" stroke-width="1.8" marker-end="url(#ah)"/>')
        if lab:
            (a, b), (c, d) = pts[-2], pts[-1]
            s.append(f'<text x="{(a + c) / 2 + lx}" y="{(b + d) / 2 + ly}" font-size="11.5" text-anchor="{anchor}">{_esc(lab)}</text>')
    def pin(x, y, t, side="l"):
        s.append(f'<rect x="{x - 5}" y="{y - 5}" width="10" height="10" fill="#1f4e9c"/>')
        a = "end" if side == "l" else "start"
        s.append(f'<text x="{x + (-10 if side == "l" else 10)}" y="{y + 4}" font-size="12.5" font-weight="bold" text-anchor="{a}">{_esc(t)}</text>')
    s.append('<rect x="120" y="30" width="720" height="430" rx="10" fill="none" stroke="#888" stroke-dasharray="6,4"/>')
    s.append('<text x="130" y="50" font-size="13" fill="#555">afe_cdr (VDD18A / VSS18A, 1.8 V)</text>')
    pin(120, 120, "CDR_DATA"); pin(120, 330, "CDR_V_IN_2"); pin(120, 410, "CDR_EN")
    pin(840, 120, "HS_RXD", "r"); pin(840, 250, "CLK_RX", "r"); pin(840, 190, "CDR_CH_OUT", "r")
    box(160, 85, 170, 70, "Alexander PD", "data ↑ / edge ↓ samples")
    box(380, 90, 110, 60, "Charge pump", "±icp, 1 bit")
    box(380, 200, 110, 60, "Loop filter", "C1 ‖ (R8 + C2)")
    box(560, 220, 130, 60, "Ring VCO", "coarse + fine")
    box(160, 300, 170, 60, "Coarse curve", "= afe_pll VCO", "#f3f7ee")
    box(620, 95, 110, 50, "Retime", "t_cq 0.3 ns", "#f3f7ee")
    box(160, 385, 170, 50, "Enable / UVLO", "CDR_EN ∧ VDD > vdd_min", "#fbf3e6")
    arr([(120, 120), (160, 120)])
    arr([(330, 112), (380, 112)], lab="UP", ly=-5); arr([(330, 130), (380, 130)], lab="DN", ly=14)
    arr([(435, 150), (435, 200)], lab="I_CP", lx=-22, ly=20)
    arr([(490, 230), (530, 230), (530, 240), (560, 240)])
    s.append('<text x="497" y="222" font-size="11.5">V_F</text>')
    arr([(530, 230), (530, 190), (835, 190)])
    s.append('<text x="545" y="184" font-size="11.5">fine control (observe only)</text>')
    arr([(120, 330), (160, 330)])
    arr([(330, 330), (600, 330), (600, 280)], lab="f_coarse", lx=-80, ly=-6)
    arr([(690, 250), (835, 250)], lab="480 MHz", lx=-28)
    s.append('<polyline points="780,250 780,168 245,168 245,155" fill="none" stroke="#222" stroke-width="1.8" marker-end="url(#ah)"/>')
    s.append('<circle cx="780" cy="250" r="3.5" fill="#222"/>')
    s.append('<text x="600" y="163" font-size="11.5" text-anchor="middle">CLK_RX: rising = data sample, falling = edge sample</text>')
    arr([(300, 85), (300, 70), (675, 70), (675, 95)])
    s.append('<text x="490" y="64" font-size="11.5" text-anchor="middle">data sample</text>')
    arr([(730, 120), (835, 120)])
    arr([(780, 168), (780, 135), (730, 135)])
    arr([(120, 410), (160, 410)])
    s.append('<text x="345" y="405" font-size="11" fill="#c0392b">CDR_EN = 0: CLK_RX stops low, HS_RXD = 1 (J),</text>')
    s.append('<text x="345" y="419" font-size="11" fill="#c0392b">charge pump off, filter reset to vf_mid = 0.9 V</text>')
    s.append('<text x="345" y="440" font-size="11" fill="#555">no data transitions: no pump, VCO runs at f_coarse(CDR_V_IN_2) · (1 + ppm_mis)</text>')
    save_raw("block_diagram", 1000, 480, s)


def fig_pd_timing():
    """Alexander phase detector: early and late cases"""
    s = [ARROW]
    def wave(y, pts, col="#1f4e9c"):
        s.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill="none" stroke="{col}" stroke-width="2"/>')
    def lab(x, y, t, a="end", sz=12.5, w="bold", col="#222"):
        s.append(f'<text x="{x}" y="{y}" font-size="{sz}" font-weight="{w}" text-anchor="{a}" fill="{col}">{_esc(t)}</text>')
    U = 120  # px per UI
    for col, (x0, title, shift, verdict) in enumerate(((150, "Clock early (edge sample = previous bit) → DN", -0.25, "DN: slower"),
                                                       (600, "Clock late (edge sample = new bit) → UP", 0.25, "UP: faster"))):
        lab(x0 - 10, 30, title, "start", 13)
        # data: bit A = 0, transition at x0 + U, bit B = 1
        yd = 70
        tx = x0 + 1.5 * U
        wave(yd, [(x0, yd + 30), (tx - 6, yd + 30), (tx + 6, yd), (x0 + 3.2 * U, yd)])
        lab(x0 + 0.4 * U, yd + 22, "D(k−1) = 0", "middle", 11, "normal")
        lab(x0 + 2.75 * U, yd + 22, "D(k) = 1", "middle", 11, "normal")
        # clock: rising edges at x0 + (0.5 + n) U + shift*U -> sample points
        yc = 150
        pts = []
        for n in range(-1, 4):
            r = x0 + (0.5 + n + 0.5) * U + shift * U
            f = r + U / 2
            pts += [(r, yc + 30), (r, yc), (f, yc), (f, yc + 30)]
        pts = [(max(min(a, x0 + 3.2 * U), x0), b) for a, b in pts]
        wave(yc, pts, "#2e8b57")
        r1, fe, r2 = x0 + 1.0 * U + shift * U, x0 + 1.5 * U + shift * U, x0 + 2.0 * U + shift * U
        for x, t, c in ((r1, "data k−1", "#1f4e9c"), (fe, "edge", "#c0392b"), (r2, "data k", "#1f4e9c")):
            s.append(f'<line x1="{x:.1f}" y1="55" x2="{x:.1f}" y2="200" stroke="{c}" stroke-dasharray="4,3"/>')
            lab(x, 218, t, "middle", 11, "normal", c)
        ev = 0 if shift < 0 else 1
        lab(x0 + 1.6 * U, 245, f"edge sample = {ev} = {'D(k−1)' if ev == 0 else 'D(k)'}", "middle", 12, "normal")
        lab(x0 + 1.6 * U, 266, verdict + " for one bit", "middle", 12.5, "bold", "#c0392b" if shift < 0 else "#2e8b57")
    lab(140, 100, "CDR_DATA", "end"); lab(140, 180, "CLK_RX", "end")
    lab(140, 300, "Decision at the rising edge k:  UP = D(k−1) ⊕ E(k),  DN = D(k) ⊕ E(k);  no transition (D(k) = D(k−1)): no pump.", "start", 12, "normal")
    lab(140, 320, "Transistor PD: FFA (↑) data, FFB (↓) edge, FFC / FFD retime; UP = qc ⊕ qd, DN = qa ⊕ qd (cdr_schematic.md 2.2).", "start", 12, "normal")
    save_raw("pd_timing", 1000, 340, s)


def fig_filter_schematic():
    s = []
    L = lambda x1, y1, x2, y2: s.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#222" stroke-width="2"/>')
    T = lambda x, y, t, a="start", sz=14: s.append(f'<text x="{x}" y="{y}" font-size="{sz}" text-anchor="{a}">{_esc(t)}</text>')
    def cap(x, y):
        L(x - 18, y - 5, x + 18, y - 5); L(x - 18, y + 5, x + 18, y + 5)
    def res(x, y1, y2):
        n, h = 6, (y2 - y1) / 6
        pts = [(x, y1)] + [(x + (10 if i % 2 else -10), y1 + h * (i + 0.5)) for i in range(n)] + [(x, y2)]
        s.append('<polyline fill="none" stroke="#222" stroke-width="2" points="' + " ".join(f"{a},{b}" for a, b in pts) + '"/>')
    def gnd(x, y):
        L(x, y, x, y + 10); L(x - 14, y + 10, x + 14, y + 10); L(x - 9, y + 15, x + 9, y + 15); L(x - 4, y + 20, x + 4, y + 20)
    s.append('<circle cx="120" cy="150" r="24" fill="white" stroke="#222" stroke-width="2"/>')
    L(120, 165, 120, 135); s.append('<polygon points="120,130 114,142 126,142" fill="#222"/>')
    T(88, 147, "I_CP = ±icp", "end", 13); T(88, 164, "for one bit", "end", 12)
    L(120, 70, 120, 126); L(120, 174, 120, 260); gnd(120, 260)
    L(120, 70, 640, 70)
    for x in (300, 470):
        s.append(f'<circle cx="{x}" cy="70" r="4" fill="#222"/>')
    L(300, 70, 300, 145); cap(300, 150); L(300, 155, 300, 260); gnd(300, 260)
    T(272, 147, "C1 0.1 pF", "end", 13); T(272, 165, "(transistor 0.13 pF)", "end", 11.5)
    L(470, 70, 470, 95); res(470, 95, 155); L(470, 155, 470, 195); cap(470, 200); L(470, 205, 470, 260); gnd(470, 260)
    T(495, 130, "R8 1 kΩ  (transistor 2 kΩ)", "start", 13)
    T(495, 180, "n_z", "start", 12)
    T(495, 205, "C2 500 pF  (transistor 40 pF)", "start", 13)
    s.append('<circle cx="646" cy="70" r="6" fill="white" stroke="#222" stroke-width="2"/>')
    T(660, 60, "CDR_CH_OUT  → VCO fine input", "start", 14)
    T(660, 80, "observe through a high-impedance bus only", "start", 12)
    T(640, 230, "CDR_EN = 0: both nodes reset to vf_mid = 0.9 V", "start", 12)
    T(640, 248, "(model r_rst 100 Ω; transistor 20 kΩ divider + TGs)", "start", 12)
    save_raw("loop_filter", 1000, 290, s)


def fig_rx_timing():
    s = [ARROW]
    X0, U = 200, 150
    def wave(y, pts, col="#1f4e9c"):
        s.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill="none" stroke="{col}" stroke-width="2"/>')
    def lab(x, y, t, a="end", sz=12.5, w="bold", col="#222"):
        s.append(f'<text x="{x}" y="{y}" font-size="{sz}" font-weight="{w}" text-anchor="{a}" fill="{col}">{_esc(t)}</text>')
    ys = {"CDR_DATA": 50, "CLK_RX": 120, "HS_RXD": 190}
    for k, y in ys.items():
        lab(X0 - 20, y + 20, k)
    # data: bits b0 b1 b2 b3 with transitions
    lv = [0, 1, 1, 0, 1]
    pts = []
    for i, b in enumerate(lv):
        x = X0 + i * U
        y = ys["CDR_DATA"] + (0 if b else 30)
        if i and lv[i - 1] != b:
            pts += [(x - 5, ys["CDR_DATA"] + (30 if b else 0)), (x + 5, y)]
        elif not i:
            pts.append((x, y))
        pts.append((x + U - 5, y))
    wave(0, pts)
    # clock rising at bit centres X0 + (i + .5) U
    pts = [(X0, ys["CLK_RX"] + 30)]
    for i in range(5):
        r = X0 + (i + 0.5) * U
        pts += [(r, ys["CLK_RX"] + 30), (r, ys["CLK_RX"]), (r + U / 2, ys["CLK_RX"]), (r + U / 2, ys["CLK_RX"] + 30)]
    wave(0, [(min(a, X0 + 5 * U), b) for a, b in pts], "#2e8b57")
    # HS_RXD: changes t_cq after each rising edge to the sampled bit
    tcq = 0.3 / 2.083 * U
    pts = [(X0, ys["HS_RXD"] + 30)]
    prev = 0
    for i, b in enumerate(lv):
        x = X0 + (i + 0.5) * U + tcq
        if b != prev:
            pts += [(x - 4, ys["HS_RXD"] + (30 if prev == 0 else 0)), (x + 4, ys["HS_RXD"] + (0 if b else 30))]
            prev = b
    pts.append((X0 + 5 * U, ys["HS_RXD"] + (0 if prev else 30)))
    wave(0, pts)
    for i in range(5):
        r = X0 + (i + 0.5) * U
        s.append(f'<line x1="{r:.1f}" y1="40" x2="{r:.1f}" y2="235" stroke="#888" stroke-dasharray="3,3"/>')
    r1, r2 = X0 + 1.5 * U, X0 + 2.5 * U
    s.append(f'<polyline points="{r1:.1f},250 {r1 + tcq:.1f},250" fill="none" stroke="#c0392b" stroke-width="1.5" marker-end="url(#ah)"/>')
    lab(r1 + tcq + 6, 254, "t_cq = 0.3 ns (= hold at the next capture edge; transistor 0.285 ns)", "start", 11.5, "normal", "#c0392b")
    s.append(f'<polyline points="{X0 + 0.5 * U + tcq:.1f},272 {r1:.1f},272" fill="none" stroke="#1f4e9c" stroke-width="1.5" marker-end="url(#ah)"/>')
    lab(X0 + 0.5 * U + tcq + 4, 288, "setup = T_bit − t_cq = 1.78 ns (transistor 1.67 ns); requirement ≥ 0.4 / ≥ 0.1 ns", "start", 11.5, "normal", "#1f4e9c")
    lab(X0, 320, "The rising CLK_RX edge k samples bit k of CDR_DATA (data sample) and puts it on HS_RXD after t_cq; the digital", "start", 12, "normal")
    lab(X0, 338, "(usb_afe_rx_if) captures HS_RXD with the next rising CLK_RX edge: one CLK_RX cycle of latency.", "start", 12, "normal")
    save_raw("rx_timing", 1000, 350, s)


def fig_sync_budget():
    s = []
    X0, U = 200, 52
    def lab(x, y, t, a="start", sz=12, w="normal", col="#222"):
        s.append(f'<text x="{x}" y="{y}" font-size="{sz}" font-weight="{w}" text-anchor="{a}" fill="{col}">{_esc(t)}</text>')
    sync = "KJKJKJKJKJKK"
    for i, c in enumerate(sync):
        s.append(f'<rect x="{X0 + i * U}" y="40" width="{U}" height="30" fill="{"#eef3fb" if c == "J" else "#f6f6f6"}" stroke="#888"/>')
        lab(X0 + i * U + U / 2, 60, c, "middle", 13, "bold")
        lab(X0 + i * U + U / 2, 30, str(i), "middle", 11)
    lab(X0 - 10, 60, "12-bit SYNC (5 hubs)", "end", 12.5, "bold")
    lab(X0 + 12 * U + 6, 60, "→ PID", "start", 12)
    def bar(y, a, b, col, t, tl=None):
        s.append(f'<rect x="{X0 + a * U}" y="{y}" width="{(b - a) * U}" height="24" fill="{col}" stroke="#555"/>')
        lab(X0 + (a + b) / 2 * U, y + 16, t, "middle", 11.5)
        if tl:
            lab(X0 - 10, y + 16, tl, "end", 12)
    bar(90, 0, 6, "#fbe3df", "CDR may deliver wrong bits (≤ 6)", "HS_ZMIN 4, LOCK_DLY 2")
    bar(90, 6, 12, "#dff0e3", "6 SYNC bits needed by the digital")
    bar(130, 0, 4, "#fbe3df", "≤ 4 wrong bits", "HS_ZMIN 6 (RTL default)")
    bar(130, 4, 12, "#dff0e3", "8 SYNC bits needed")
    rows = (("transistor tt (ngspice), no jitter", 4, "12 packets: mean 1.2, worst 4 bits"),
            ("model / tt values, no jitter", 4, "1000 packets: worst 4 bits"),
            ("ss 125 °C values, no jitter", 7, "worst 7 bits, 0.2 % > 6 bits"),
            ("model, ±0.15 UI jitter (99 %)", 8, "97 % ≤ 4, 99 % ≤ 8 bits, tail to 24"))
    for k, (tl, w, t) in enumerate(rows):
        y = 175 + 34 * k
        bar(y, 0, w, "#cfe0f7" if w <= 6 else "#f5d0c8", "", tl)
        lab(X0 + max(w, 6) * U + 8, y + 16, t, "start", 11.5)
    s.append(f'<line x1="{X0 + 6 * U}" y1="80" x2="{X0 + 6 * U}" y2="315" stroke="#c0392b" stroke-width="2" stroke-dasharray="6,4"/>')
    lab(X0 + 6 * U + 4, 330, "requirement: correct bits from the 7th bit after the first transition (spec 4.2, Q2)", "start", 11.5, "normal", "#c0392b")
    lab(X0, 352, "Bars: worst-case lock time (bits from the packet start) of the cases in section 8; the bar ends where every later sample is good.", "start", 11, "normal", "#555")
    save_raw("sync_budget", 1000, 365, s)


# ---------------------------------------------------------------- plots
def fig_vco():
    vt = load_vco()
    p = Plot(900, 430)
    a = p.panel(80, 40, 470, 330, (0.4, 1.45), (360, 540), xlabel="Coarse input V(CDR_V_IN_2)  [V]  (fine at 0.9 V)",
                ylabel="CLK_RX frequency  [MHz]", title="Coarse tuning", legend="tl")
    v = np.linspace(0.4, 1.45, 300)
    a.band(400, 500, B, 0.05)
    a.line(v, np.clip(400 + 200 * (v - 0.5), 400, 500), B, 2.6, None, "model (= afe_pll curve)")
    for c, col, mk, lab in (("tt", G, "o", "tt 27 °C 1.8 V"), ("ss125", R, "s", "ss 125 °C 1.62 V"),
                            ("ff-40", O, "^", "ff −40 °C 1.98 V"), ("ss", V, "s", "ss 27 °C"), ("ff", K, "^", "ff 27 °C")):
        if c in vt:
            a.line(vt[c][0], vt[c][1], col, 1.2, "3,3")
            a.points(vt[c][0], vt[c][1], col, lab, 4, mk)
    a.hline(480, B, "5,4", text="480 MHz", anchor="end")
    b = p.panel(640, 40, 230, 330, (0.75, 1.05), (420, 540), xlabel="Fine input V(CDR_CH_OUT)  [V]",
                ylabel="", title="Fine tuning (coarse 0.9 V)", legend="tl", xticks=[0.8, 0.9, 1.0])
    vf = np.linspace(0.75, 1.05, 50)
    b.line(vf, 480 + 300 * (vf - 0.9), B, 2.6, None, "model 300 MHz/V")
    for f0, kf, col, lab in ((476.6, 301, G, "tt 301"), (451.5, 139, R, "ss125 139"), (454.0, 355, O, "ff−40 355")):
        b.line(vf, f0 + kf * (vf - 0.9), col, 1.6, "4,3", lab + " MHz/V")
    b.vline(0.9, K)
    p.save(os.path.join(FIG, "vco_tuning.svg"))


def fig_filter_z():
    f = np.logspace(4, 10, 600)
    def Z(f, q):
        s = 2j * np.pi * f
        return 1 / (s * q["c1"] + 1 / (q["r8"] + 1 / (s * q["c2"])))
    p = Plot(900, 420)
    a = p.panel(90, 40, 770, 320, (1e4, 1e10), (1, 1e7), True, True, xlabel="Frequency  [Hz]",
                ylabel="|Z|  [Ω]", title="Loop-filter impedance Z(f) = V(CDR_CH_OUT) / I_CP", legend="bl")
    for q, col, d in ((P, B, None), (P_TT, G, "6,3")):
        a.line(f, abs(Z(f, q)), col, 2.4, d, f"{q['name']}: R8 {q['r8'] / 1e3:.0f} kΩ, C2 {q['c2'] * 1e12:.0f} pF, C1 {q['c1'] * 1e12:.2f} pF")
        fz = 1 / (2 * np.pi * q["r8"] * q["c2"])
        a.vline(fz, col, "2,3", text=f"zero {fz / 1e6:.2f} MHz", top=True)
    a.vline(F_BIT / 2, R, "5,4", text="f_bit / 2", top=True)
    a.hline(1e3, K, "2,4", text="R8 = 1 kΩ", anchor="start", below=True)
    a.hline(2e3, K, "2,4", text="2 kΩ", anchor="start")
    p.save(os.path.join(FIG, "filter_impedance.svg"))


def fig_decision():
    n = np.arange(0, 129)
    p = Plot(900, 400)
    a = p.panel(90, 40, 770, 290, (0, 128), (0, 0.32), xlabel="Bits after one UP decision (no further decisions)",
                ylabel="Sampling-phase shift  [UI]", title="Response to one phase-detector decision", legend="tl",
                xticks=[0, 16, 32, 48, 64, 80, 96, 112, 128])
    for q, col, d in ((P, B, None), (P_TT, G, "6,3"), (P_SS, R, "3,3")):
        ph = np.where(n >= 1, prop_step(q) + int_step(q) * np.maximum(n - 1, 0), 0)
        a.line(n, ph, col, 2.4, d, f"{q['name']}: {prop_step(q):.4f} UI + {int_step(q) * 1e6:.0f} ppm per bit")
    p.save(os.path.join(FIG, "decision_response.svg"))


def fig_lock_transient(tr0):
    rng = random.Random(4)
    bits = packet(64, rng)
    p = Plot(900, 640)
    a = p.panel(90, 40, 770, 230, (0, 48), (-0.5, 0.5), xlabel="", ylabel="Sampling offset  [UI]",
                title="Lock transient: sampling instant relative to the bit centre (0 ppm, no jitter)", legend="br",
                xticks=list(range(0, 49, 4)), yticks=[-0.5, -0.25, 0, 0.25, 0.5])
    for k, ph in enumerate(np.linspace(0.02, 0.98, 9)):
        r, _ = run(bits, P, ph)
        a.line(r[:, 0], r[:, 1], B, 1.4, None, "model, 9 start phases" if k == 0 else None)
    a.band(-0.35, 0.35, G, 0.06)
    a.hline(0.35, G, "3,3", text="±0.35 UI = margin 0.15 UI", anchor="start")
    a.hline(-0.35, G, "3,3")
    b = p.panel(90, 330, 770, 230, (0, 48), (-0.5, 0.5), xlabel="Bits from the packet start (SYNC bit 0)",
                ylabel="Sampling offset  [UI]", title="Transistor level (ngspice, tt): the 12 packets of tb_cdr_tr lock0",
                legend="br", xticks=list(range(0, 49, 4)), yticks=[-0.5, -0.25, 0, 0.25, 0.5])
    if tr0 is not None:
        for k in range(12):
            r = tr0[tr0[:, 0] == k]
            b.line(r[:, 1], r[:, 2], G, 1.4, None, "transistor tt, 12 packets" if k == 0 else None)
    b.band(-0.35, 0.35, G, 0.06)
    b.hline(0.35, G, "3,3"); b.hline(-0.35, G, "3,3")
    p.save(os.path.join(FIG, "lock_transient.svg"))


def fig_lock_stats(st):
    p = Plot(900, 450)
    a = p.panel(90, 40, 770, 330, (0, 20), (1e-3, 1), False, True, xlabel="L  [bits from the packet start]",
                ylabel="Fraction of packets with lock time > L", legend="tr", xticks=list(range(0, 21, 2)),
                title="Lock-time distribution (random start phase, −1000 / 0 / +1000 ppm, 1000 packets per curve)")
    styles = {0.0: None, 0.15: "6,3", 0.25: "2,3"}
    for (name, jit), L in st.items():
        if jit > 0.2:
            continue
        col = {"model": B, "tt values": G, "ss 125 °C values": R}[name]
        x = np.arange(0, 21)
        y = np.array([(L > v).mean() for v in x])
        y = np.where(y > 0, y, 1e-4)
        a.line(x, y, col, 2.2, styles[jit], f"{name}, jitter ±{jit:.2f} UI")
    a.vline(6, R, "5,4", text="spec 4.2: ≤ 6 bits")
    p.save(os.path.join(FIG, "lock_stats.svg"))


def fig_tracking(trp, trn):
    rng = random.Random(9)
    bits = packet(1580, rng)
    p = Plot(900, 640)
    a = p.panel(90, 40, 770, 230, (0, 1600), (-0.5, 0.5), xlabel="", ylabel="Sampling offset  [UI]",
                title="Frequency tracking: one 1600-bit packet, data at +1000 / −1000 ppm", legend="br",
                yticks=[-0.5, -0.25, 0, 0.25, 0.5])
    b = p.panel(90, 330, 770, 230, (0, 1600), (-4000, 4000), xlabel="Bits from the packet start",
                ylabel="Integral-path offset  [ppm]", legend="br",
                title="Frequency held by the integral path (C2), relative to the free-running VCO")
    for ppm, col in ((1000, B), (-1000, O)):
        r, _ = run(bits, P, 0.3, ppm=ppm)
        a.line(r[:, 0], r[:, 1], col, 1.0, None, f"model, {ppm:+d} ppm")
        b.line(r[:, 0], P["kf"] * r[:, 6] / F_BIT * 1e6, col, 2.2, None, f"model, {ppm:+d} ppm")
        if ppm > 0:
            r, _ = run(bits, P_TT, 0.3, ppm=ppm)
            b.line(r[:, 0], P_TT["kf"] * r[:, 6] / F_BIT * 1e6, G, 0.9, None,
                   f"behavioural with transistor values, {ppm:+d} ppm (1633 ppm per net decision)")
    for ppm, col, tr in ((1000, G, trp), (-1000, R, trn)):
        if tr is not None:
            a.line(tr[:, 1], tr[:, 2], col, 1.0, "4,2", f"transistor tt, {ppm:+d} ppm")
    b.hline(1000, K, "3,3"); b.hline(-1000, K, "3,3")
    p.save(os.path.join(FIG, "tracking.svg"))


V0_TR = 0.9


def fig_dither(tr0, trp, trn):
    rng = random.Random(21)
    bits = packet(1580, rng)
    edges = np.linspace(-0.2, 0.2, 41)
    p = Plot(900, 400)
    a = p.panel(90, 40, 770, 290, (-0.2, 0.2), (0, 0.14), xlabel="Sampling offset after lock  [UI]",
                ylabel="Fraction of edges", title="Steady-state sampling-phase dither (bang-bang limit cycle)", legend="tr")
    def hist(x, col, d, lab):
        h, _ = np.histogram(x, edges)
        h = h / max(h.sum(), 1)
        xs = np.repeat(edges, 2)[1:-1]
        ys = np.repeat(h, 2)
        a.line(xs, ys, col, 2, d, lab)
    r, _ = run(bits, P, 0.3)
    hist(r[r[:, 0] > 50][:, 1], B, None, f"model, 0 ppm (step ±{prop_step(P):.3f} UI)")
    rt, _ = run(bits, P_TT, 0.3)
    hist(rt[rt[:, 0] > 50][:, 1], O, "2,2", "behavioural with transistor values, 0 ppm")
    tr = [x for x in (trp, trn) if x is not None]
    if tr:
        x = np.concatenate([t[t[:, 1] > 50][:, 2] for t in tr])
        hist(x, G, "6,3", "transistor tt (ngspice), ±1000 ppm packets")
    p.save(os.path.join(FIG, "dither.svg"))


def fig_jtol(freqs, res):
    p = Plot(900, 430)
    a = p.panel(90, 40, 770, 320, (freqs[0], freqs[-1]), (0.1, 1000), True, True, xlabel="Jitter frequency  [Hz]",
                ylabel="Tolerated sinusoidal jitter  [UI p-p]", legend="tr",
                title="Sinusoidal jitter tolerance (behavioural, PRBS7 NRZI with bit stuffing, no other jitter)")
    for (q, col, d), y in zip(((P, B, None), (P_TT, G, "6,3"), (P_SS, R, "3,3")), res):
        a.line(freqs, y, col, 2.4, d, q["name"])
        a.points(freqs, y, col, None, 3)
        slew = prop_step(q) * 0.5 * F_BIT / (np.pi * freqs)   # proportional slew limit, density 0.5
        a.line(freqs, slew, col, 1, "1,3")
    a.text(2.2e6, 6, "dotted: slew limit step · 0.5 · f_bit / (π f)", K, 11)
    a.hline(1, K, "3,3")
    p.save(os.path.join(FIG, "jtol.svg"))


# ---------------------------------------------------------------- main
def main():
    os.makedirs(FIG, exist_ok=True)
    global V0_TR
    tr0, trp, trn = load_tr("lock0"), load_tr("lockp"), load_tr("lockn")
    if tr0 is not None:
        V0_TR = tr0[tr0[:, 1] > 10][:, 4].mean()
    fig_block(); fig_pd_timing(); fig_filter_schematic(); fig_rx_timing(); fig_sync_budget()
    fig_vco(); fig_filter_z(); fig_decision()
    fig_lock_transient(tr0); fig_tracking(trp, trn); fig_dither(tr0, trp, trn)
    for q in (P, P_TT, P_SS, P_FF):
        print(f"{q['name']}: proportional step {prop_step(q):.4f} UI ({prop_step(q) * UI * 1e12:.0f} ps), "
              f"integral step {int_step(q) * 1e6:.0f} ppm, R8*C2 {q['r8'] * q['c2'] * 1e9:.0f} ns, "
              f"zero {1 / (2 * np.pi * q['r8'] * q['c2']) / 1e6:.3f} MHz, T_bit/(R8 C2) {UI / (q['r8'] * q['c2']):.4f}")
    n = 200 if QUICK else 1000
    st = {}
    for name, q in (("model", P), ("tt values", P_TT), ("ss 125 °C values", P_SS)):
        for jit in (0.0, 0.15, 0.25):
            L = lock_stats(q, jit, n, 100 + int(jit * 100), "error" if jit else "margin")
            st[(name, jit)] = L
            print(f"lock {name} jitter {jit}: mean {L.mean():.2f}, p99 {np.percentile(L, 99):.0f}, worst {L.max()}, "
                  f">4: {100 * (L > 4).mean():.1f} %, >6: {100 * (L > 6).mean():.1f} % ({n} packets)")
    fig_lock_stats(st)
    # tracking summary
    rng = random.Random(9)
    bits = packet(1580, rng)
    for q in (P, P_TT, P_SS):
        for ppm in (1000, -1000):
            r, vc2 = run(bits, q, 0.3, ppm=ppm)
            after = r[r[:, 0] > 20]
            print(f"track {q['name']} {ppm:+d} ppm: min margin {after[:, 2].min():.2f} UI, mean offset {after[:, 1].mean():+.3f} UI, "
                  f"errors {int((after[:, 4] == 0).sum())}, stored offset at the end {q['kf'] * vc2 / F_BIT * 1e6:+.0f} ppm")
    for q in (P, P_TT, P_SS):
        r, _ = run(bits, q, 0.3)
        after = r[r[:, 0] > 50]
        print(f"dither {q['name']}: offset rms {after[:, 1].std():.3f} UI, p-p {np.ptp(after[:, 1]):.3f} UI, mean {after[:, 1].mean():+.3f}")
    freqs = np.logspace(5, np.log10(2e8), 9 if QUICK else 14)
    res = [jtol(q, freqs) for q in (P, P_TT, P_SS)]
    for q, y in zip((P, P_TT, P_SS), res):
        print("jtol", q["name"], " ".join(f"{f / 1e6:.3g}MHz:{v:.2f}" for f, v in zip(freqs, y)))
    fig_jtol(freqs, res)
    if "--no-png" not in sys.argv:
        for f in sorted(os.listdir(FIG)):
            if f.endswith(".svg"):
                subprocess.run(["rsvg-convert", "-z", "2", "-o", os.path.join(FIG, f[:-4] + ".png"), os.path.join(FIG, f)], check=True)
    print("figures in", FIG)


if __name__ == "__main__":
    main()
