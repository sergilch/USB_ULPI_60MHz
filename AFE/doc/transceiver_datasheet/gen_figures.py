#!/usr/bin/env python3
"""gen_figures.py - figures of the transceiver datasheet
(AFE/doc/transceiver_datasheet/transceiver_datasheet.md)

Usage (from anywhere; numpy only, rsvg-convert for the PNG copies used by Word):
    python3 AFE/doc/transceiver_datasheet/gen_figures.py [--no-png]

Transistor data: data/xc_<corner>_*.csv, cut by data/extract_tr.py from the
ngspice runs of AFE/spice/tb/tb_transceiver_tr.py at tt (27 C, 3.3 / 1.8 V),
ss (125 C, 3.0 / 1.62 V) and ff (-40 C, 3.6 / 1.98 V), and the printed
results of those runs, data/xc_<corner>_summary.txt.  Model curves: a
re-implementation of the afe_transceiver.va equations (afe_hs_tx current
steering with t_en / t_dly / t_rf_hs, afe_fsls_xcvr voltage sources behind
r_out with linear ramps, afe_term resistors, receiver thresholds and delays)
driven by the stimulus of tb_transceiver_tr.py and solved with the same far-end
loads (45 Ohm / 2 pF in HS; 15 kOhm, 1.5 kOhm and 50 / 200 / 600 pF in FS / LS).
It is not a Spectre run of afe_transceiver.va (no Spectre here).
Output: fig/*.svg (+ fig/*.png at 2x).
"""
import os, re, sys, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "pll_datasheet"))
from svgplot import Plot, COLORS, _esc

FIG, DATA = os.path.join(HERE, "fig"), os.path.join(HERE, "data")
B, R, G, O, V, K = COLORS
UI = 1 / 480e6 * 1e9                       # ns
UI_FS, UI_LS = 1e3 / 12, 1e3 / 1.5         # ns
CORNERS = (("tt", G, None, 1.80, 3.3, "tt 27 °C 3.3 / 1.8 V"),
           ("ss", R, "6,3", 1.62, 3.0, "ss 125 °C 3.0 / 1.62 V"),
           ("ff", O, "2,2", 1.98, 3.6, "ff −40 °C 3.6 / 1.98 V"))
M = dict(i_hs=17.78e-3, t_en=20.0, t_dly=0.5, t_rf_hs=0.625, r_out=45.0, t_fs=12.5, t_ls=187.5, t_oe=1.0,
         vse=1.4, hys_se=0.2, vdi=0.2, t_rx=2.0, r_pu=1500.0, r_hs=45.0, r_pd=15000.0, vdd_min=2.97)

# stimulus of tb_transceiver_tr.py
T_EN_HS = 100.0
T_D_HS = T_EN_HS + 10 * UI


def prbs7(n, seed=0x5A):
    s, out = seed, []
    for _ in range(n):
        b = ((s >> 6) ^ (s >> 5)) & 1
        s = ((s << 1) | b) & 0x7F
        out.append(b)
    return out


def nrzi(bits, start):
    lvl, out = start, []
    for b in bits:
        lvl = lvl if b else 1 - lvl
        out.append(lvl)
    return out


def hs_levels():
    sync = [0, 1] * 15 + [0, 0]
    pay = nrzi(prbs7(127), sync[-1])
    return sync + pay + [1 - pay[-1]] * 8


def fsls_levels(ls):
    return [0, 1, 0, 1, 0, 1, 0, 0] + nrzi(prbs7(12 if ls else 40), 0)


# ---------------------------------------------------------------- data
def csv(corner, win):
    f = os.path.join(DATA, f"xc_{corner}_{win}.csv")
    if not os.path.exists(f):
        return None
    a = np.loadtxt(f, delimiter=",", skiprows=1)
    names = open(f).readline().strip().split(",")
    return {n: a[:, i] for i, n in enumerate(names)}


def blocks(corner):
    f = os.path.join(DATA, f"xc_{corner}_summary.txt")
    s = open(f).read() if os.path.exists(f) else ""
    out, cur = {"_all": s}, None
    for ln in s.splitlines():
        m = re.match(r"^(\w+) \(", ln)
        if m:
            cur = m.group(1); out[cur] = ""
        elif cur:
            out[cur] += ln + "\n"
    return out


def num(s, pat, k=1):
    m = re.search(pat, s or "")
    return float(m.group(k)) if m else float("nan")


def summary(corner):
    b = blocks(corner)
    hs, sq, rx, dc = b.get("hs", ""), b.get("seq", ""), b.get("rx", ""), b.get("dc", "")
    d = dict(passed="TEST PASSED" in b["_all"],
             ready=num(hs, r"ready ([\d.]+) ns after TX_EN"), dly=num(hs, r"line delay (\d+) ps"),
             jit=num(hs, r"crossing jitter ([\d.]+) ps"),
             st_lo=num(hs, r"\(3rd bit of a run\) ([\d.]+)"), st_hi=num(hs, r"\(3rd bit of a run\) [\d.]+ \.\. ([\d.]+)"),
             bc_lo=num(hs, r"every bit centre: ([\d.]+)"), bc_hi=num(hs, r"every bit centre: [\d.]+ \.\. ([\d.]+)"),
             first=num(hs, r"\(([+-][\d.]+) % of steady"), mg=num(hs, r"inner hexagon .*?\) ([+-]\d+) mV"),
             eye_lo=num(hs, r">= (\d+) mV over 25"), peak=num(hs, r"peak (\d+) mV"),
             r_lo=num(hs, r"rise (\d+) \.\. "), r_hi=num(hs, r"rise \d+ \.\. (\d+)"),
             f_lo=num(hs, r"fall (\d+) \.\. "), f_hi=num(hs, r"fall \d+ \.\. (\d+)"),
             off=num(hs, r"< 5 mV ([\d.]+) ns later"), chirp=num(hs, r"DM - DP = (\d+) mV"), chirp_dp=num(hs, r"DP (\d+) mV \(A6"),
             i33=num(hs, r"packet: VDD33 ([\d.]+) mA"), i18=num(hs, r"VDD18 ([\d.]+) mA"),
             seq_ready=num(sq, r"HS ready .*? ([\d.]+) ns after"), seq_dly=num(sq, r"line delay \(50 %\): ([\d.]+) ns"),
             seq_fall=num(sq, r"fall time: ([\d.]+) ns"))
    for c in ("fs", "ls200", "ls600"):
        s = b.get(c, "")
        d[c] = dict(r=(num(s, r"rise ([\d.]+) \.\. "), num(s, r"rise [\d.]+ \.\. ([\d.]+)")),
                    f=(num(s, r"fall ([\d.]+) \.\. "), num(s, r"fall [\d.]+ \.\. ([\d.]+)")),
                    match=num(s, r"matching ([\d.]+) %"), cx=(num(s, r"crossover ([\d.]+)"), num(s, r"crossover [\d.]+ \.\. ([\d.]+)")),
                    voh=num(s, r"high >= ([\d.]+) V"), vol=num(s, r"low <= (\d+) mV"), err=num(s, r"each bit: (\d+) errors"),
                    rd=(num(s, r"RXRCV_A ([\d.]+) \.\. "), num(s, r"RXRCV_A [\d.]+ \.\. ([\d.]+) ns")),
                    skew=num(s, r"skew <= ([\d.]+) ns"), i33=num(s, r"packet ([\d.]+) mA"))
    d["se"] = (num(rx, r"RXDP_A: high above ([\d.]+)"), num(rx, r"RXDP_A: .*?low below ([\d.]+)"))
    d["rcv"] = {cm: (num(rx, rf"CM {cm:.2f} V: switches at ([+-][\d.]+)"), num(rx, rf"CM {cm:.2f} V: switches at [+-][\d.]+ / ([+-][\d.]+)"))
                for cm in (0.4, 0.8, 1.65, 2.5)}
    d["uvlo"] = (num(rx, r"isolated below ([\d.]+) V"), num(rx, r"on again above ([\d.]+) V"))
    d["dc"] = dict(pu=num(dc, r"pull-up, DP = 0 V: (\d+)"), hs=num(dc, r"termination DP at 0.4 V: ([\d.]+)"),
                   pd=num(dc, r"pull-down DP at [\d.]+ V: ([\d.]+)"), zh=num(dc, r"FS driver high \(J.*?: ([\d.]+)"),
                   zl=num(dc, r"FS driver low \(J.*?: ([\d.]+)"), ihs=num(dc, r"HS current J into 0.4 V: ([\d.]+)"),
                   ioff=num(dc, r"bias current with everything off: VDD33 (\d+)"))
    return d


# ---------------------------------------------------------------- model
def ramp_events(t, events, t0, dly, tr):
    """Verilog-A transition(): target changes at events (time, value), output follows
    after dly with linear ramps of tr (rate 1 / tr, interrupted ramps continue from where they are)"""
    tgt = np.zeros_like(t)
    ev = sorted(events)
    v = ev[0][1]
    for (te, val) in ev:
        tgt[t >= te + dly] = val
    out = np.zeros_like(t)
    y = tgt[0]
    dt = np.diff(t, prepend=t[0])
    for i in range(len(t)):
        step = dt[i] / tr
        y = min(tgt[i], y + step) if tgt[i] > y else max(tgt[i], y - step)
        out[i] = y
    return out


def lowpass(t, y, tau):
    out = np.empty_like(y)
    out[0] = y[0]
    for i in range(1, len(t)):
        a = (t[i] - t[i - 1]) / tau
        out[i] = out[i - 1] + (y[i] - out[i - 1]) * min(a, 1.0)
    return out


def hs_model(t):
    """afe_hs_tx in the hs case: both ends 45 Ohm (22.5 Ohm per wire pair), 2 pF per wire"""
    lv = hs_levels()
    t_end = T_D_HS + len(lv) * UI
    settled = T_EN_HS + M["t_en"]
    evp, evn = [(0.0, 0.0)], [(0.0, 0.0)]
    # J during the lead from "settled" on, then the data
    evp.append((settled, 1.0)); evn.append((settled, 0.0))
    for i, b in enumerate(lv):
        tb = max(T_D_HS + i * UI, settled)
        evp.append((tb, float(b))); evn.append((tb, float(1 - b)))
    evp.append((t_end, 0.0)); evn.append((t_end, 0.0))
    fp = ramp_events(t, evp, 0, M["t_dly"], M["t_rf_hs"])
    fm = ramp_events(t, evn, 0, M["t_dly"], M["t_rf_hs"])
    i = M["i_hs"]
    vp, vm = i * fp * 22.5, i * fm * 22.5
    tau = 22.5 * 2e-12 * 1e9
    return lowpass(t, vp, tau) - lowpass(t, vm, tau)


def hs_chirp_model(t, V=3.3):
    """device chirp K: device pull-up on, no device termination, host 45 Ohm"""
    t_end = T_D_HS + len(hs_levels()) * UI
    t_ch = t_end + 100
    pu = np.clip((t - (t_ch - 50)) / 1.0, 0, 1)
    fm = ramp_events(t, [(0.0, 0.0), (t_ch + M["t_en"], 1.0), (t_ch + 145, 0.0)], 0, M["t_dly"], M["t_rf_hs"])
    # before t_ch - 50 the device termination is on (TX off, line 0 V)
    dp = V * M["r_hs"] / (M["r_pu"] + M["r_hs"]) * pu
    dm = M["i_hs"] * fm * M["r_hs"]
    return dp, dm


def fsls_model(t, ls, cl, V=3.3, vl=1.8):
    """afe_fsls_xcvr + afe_term with the fs / ls stimulus: DP, DM, RXRCV_A, RXDP_A, RXDM_A"""
    ui = UI_LS if ls else UI_FS
    lv = fsls_levels(ls)
    t0 = 5 * ui + 200
    te = t0 + len(lv) * ui
    dat_ev = [(0.0, 1), (t0 - 4 * ui, 1)] + [(t0 + i * ui, b) for i, b in enumerate(lv)] + [(te + 2 * ui, 1)]
    se0_ev = [(0.0, 0), (te, 1), (te + 2 * ui, 0)]
    def at(ev, x):
        v = ev[0][1]
        for a, b in ev:
            if x >= a: v = b
        return v
    tp_ev, tm_ev = [], []
    for x in sorted(set([e[0] for e in dat_ev + se0_ev])):
        d, s = at(dat_ev, x), at(se0_ev, x)
        tp, tm = (0, 0) if s else ((1, 0) if d != ls else (0, 1))
        tp_ev.append((x, float(tp))); tm_ev.append((x, float(tm)))
    tr = M["t_ls"] if ls else M["t_fs"]
    vps = V * ramp_events(t, tp_ev, 0, 0, tr)
    vms = V * ramp_events(t, tm_ev, 0, 0, tr)
    g = ramp_events(t, [(0.0, 0.0), (t0 - 4 * ui, 1.0), (te + 3 * ui, 0.0)], 0, 0, M["t_oe"]) / M["r_out"]
    pu = 0.0 if ls else 1.0
    dp, dm = np.zeros_like(t), np.zeros_like(t)
    p = V * M["r_pd"] / (M["r_pd"] + M["r_pu"]) if pu else 0.0
    m = 0.0
    C = cl * 1e-12
    for i in range(len(t)):
        if i:
            h = (t[i] - t[i - 1]) * 1e-9
            for _ in range(4):                          # 4 Euler substeps (stiff for 45 Ohm * 50 pF = 2.25 ns)
                ip = g[i] * (vps[i] - p) - p / M["r_pd"] + pu * (V - p) / M["r_pu"]
                im = g[i] * (vms[i] - m) - m / M["r_pd"]
                p += ip * h / 4 / C; m += im * h / 4 / C
        dp[i], dm[i] = p, m
    rcv, rdp, rdm = receivers(t, dp, dm, vl)
    return dp, dm, rcv, rdp, rdm


def receivers(t, dp, dm, vl=1.8):
    hi, lo = M["vse"] + M["hys_se"] / 2, M["vse"] - M["hys_se"] / 2
    sp, sm, sd = np.zeros_like(t), np.zeros_like(t), np.zeros_like(t)
    a, b, c = dp[0] > M["vse"], dm[0] > M["vse"], dp[0] > dm[0]
    for i in range(len(t)):
        if dp[i] > hi: a = 1
        elif dp[i] < lo: a = 0
        if dm[i] > hi: b = 1
        elif dm[i] < lo: b = 0
        x = dp[i] - dm[i]
        if x > M["vdi"] / 2: c = 1
        elif x < -M["vdi"] / 2: c = 0
        sp[i], sm[i], sd[i] = a, b, c
    sh = lambda y: vl * np.interp(t - M["t_rx"], t, y, left=y[0])
    return sh(sd), sh(sp), sh(sm)


# ---------------------------------------------------------------- helpers
def save_raw(name, w, h, s):
    open(os.path.join(FIG, name + ".svg"), "w").write(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'font-family="Arial, Helvetica, sans-serif"><rect width="{w}" height="{h}" fill="white"/>'
        + "\n".join(s) + "</svg>")


ARROW = ('<defs><marker id="ah" markerWidth="9" markerHeight="8" refX="8" refY="4" orient="auto">'
         '<polygon points="0,0 9,4 0,8" fill="#222"/></marker>'
         '<marker id="ad" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
         '<polygon points="0,0 8,4 0,8" fill="#555"/></marker>'
         '<marker id="adr" markerWidth="8" markerHeight="8" refX="1" refY="4" orient="auto">'
         '<polygon points="8,0 0,4 8,8" fill="#555"/></marker></defs>')


def dim(p, ax, a, b, y, text, col="#555", above=True):
    X1, X2, Y = ax._tx(a), ax._tx(b), ax._ty(y)
    p.raw(f'<line x1="{X1:.1f}" y1="{Y:.1f}" x2="{X2:.1f}" y2="{Y:.1f}" stroke="{col}" stroke-width="1.2" '
          f'marker-start="url(#adr)" marker-end="url(#ad)"/>')
    p.raw(f'<text x="{(X1 + X2) / 2:.1f}" y="{Y + (-5 if above else 14):.1f}" font-size="11" fill="{col}" '
          f'text-anchor="middle">{_esc(text)}</text>')


# ---------------------------------------------------------------- diagrams
def fig_block():
    s = [ARROW]
    def box(x, y, w, h, t, sub=None, sub2=None, fill="#eef3fb"):
        s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="#1f4e9c" stroke-width="1.8"/>')
        n = 1 + bool(sub) + bool(sub2)
        y0 = y + h / 2 - (n - 1) * 7.5 + 5
        s.append(f'<text x="{x + w / 2}" y="{y0}" font-size="13.5" font-weight="bold" text-anchor="middle">{_esc(t)}</text>')
        for k, st in enumerate([q for q in (sub, sub2) if q]):
            s.append(f'<text x="{x + w / 2}" y="{y0 + 15 * (k + 1)}" font-size="11" text-anchor="middle">{_esc(st)}</text>')
    def arr(pts, col="#222", dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        s.append(f'<polyline points="{" ".join(f"{a},{b}" for a, b in pts)}" fill="none" stroke="{col}" stroke-width="1.7"{d} marker-end="url(#ah)"/>')
    def txt(x, y, t, a="start", sz=11.5, col="#222", w="normal"):
        s.append(f'<text x="{x}" y="{y}" font-size="{sz}" fill="{col}" font-weight="{w}" text-anchor="{a}">{_esc(t)}</text>')
    def pin(x, y, t, side="l"):
        s.append(f'<rect x="{x - 5}" y="{y - 5}" width="10" height="10" fill="#1f4e9c"/>')
        txt(x + (-10 if side == "l" else 10), y + 4, t, "end" if side == "l" else "start", 12, "#222", "bold")
    s.append('<rect x="160" y="30" width="250" height="520" rx="8" fill="#f3f7ee" stroke="#2e8b57" stroke-dasharray="6,4"/>')
    txt(170, 48, "VDD18 1.8 V: input logic, pre-drivers,", sz=11.5, col="#22663f")
    txt(170, 63, "ready timer, receiver output gates", sz=11.5, col="#22663f")
    s.append('<rect x="420" y="30" width="420" height="520" rx="8" fill="#fbf3e6" stroke="#d4860b" stroke-dasharray="6,4"/>')
    txt(430, 48, "VDD33 3.3 V: everything on DP / DM (thick oxide)", sz=11.5, col="#a0640a")
    for y, n in ((95, "TX_IN_P"), (120, "TX_IN_N"), (150, "TX_EN"), (230, "FS_OE_A"), (250, "FS_DAT_A"), (270, "FS_SE0_A"),
                 (290, "FS_LS_A"), (360, "FS_RX_EN_A"), (440, "DP_PULLUP_EN_A"), (460, "HS_TERM_EN_A"), (480, "PD_EN_A0/1"),
                 (520, "TX_VREF")):
        pin(160, y, n)
    for y, n in ((330, "RXRCV_A"), (390, "RXDP_A"), (410, "RXDM_A")):
        pin(160, y, n)
    pin(1000, 250, "DP", "r"); pin(1000, 300, "DM", "r")
    box(190, 85, 200, 80, "Steering logic,", "pre-drivers, ready timer", "rdy ≈ 14 … 17 ns after TX_EN")
    box(450, 85, 200, 80, "HS current source", "17.8 mA (×178 replica)", "steering DP / DM / dump")
    box(190, 220, 200, 85, "FS / LS logic", "u / d per wire, & pok", "level shift ×5")
    box(450, 220, 200, 85, "FS / LS drivers ×2", "push-pull + 26 Ω (34 Ω)", "Miller slew, FS / LS")
    box(190, 330, 200, 90, "Output gates", "RXDP/DM = s & on", "RXRCV = d | !on")
    box(450, 330, 200, 90, "Receivers", "2 Schmitt (1.26 / 1.60 V)", "differential (both pairs)")
    box(450, 430, 200, 70, "Terminations", "1.5 kΩ up, 45 Ω ×2,", "15 kΩ down ×2")
    box(680, 480, 140, 55, "Bias, UVLO", "V(TX_VREF) / 12 kΩ", fill="#fff")
    box(450, 178, 200, 34, "RDQ 22.5 Ω (dump)", fill="#fff")
    for y in (95, 120, 150):
        arr([(160, y), (190, y)])
    for y in (230, 250, 270, 290):
        arr([(160, y), (190, y)])
    arr([(390, 125), (450, 125)]); txt(420, 118, "gates", "middle", 10.5)
    arr([(390, 262), (450, 262)])
    arr([(550, 165), (550, 178)]); txt(556, 175, "XSD", sz=10)
    # line bus
    s.append('<line x1="900" y1="70" x2="900" y2="520" stroke="#222" stroke-width="2"/>')
    s.append('<line x1="930" y1="70" x2="930" y2="520" stroke="#222" stroke-width="2"/>')
    txt(900, 64, "DP", "middle", 11, w="bold"); txt(930, 64, "DM", "middle", 11, w="bold")
    s.append('<line x1="900" y1="250" x2="995" y2="250" stroke="#222" stroke-width="2"/>')
    s.append('<line x1="930" y1="300" x2="995" y2="300" stroke="#222" stroke-width="2"/>')
    for y in (115, 135, 255, 275):
        x = 900 if y in (115, 255) else 930
        arr([(650, y), (x - 3, y)])
        s.append(f'<circle cx="{x}" cy="{y}" r="3" fill="#222"/>')
    txt(775, 108, "XSP → DP, XSN → DM", "middle", 10.5)
    for y, x in ((455, 900), (475, 930)):
        s.append(f'<line x1="650" y1="{y}" x2="{x}" y2="{y}" stroke="#222" stroke-width="1.6"/><circle cx="{x}" cy="{y}" r="3" fill="#222"/>')
    for y, x in ((350, 900), (370, 930)):
        arr([(x, y), (653, y)])
        s.append(f'<circle cx="{x}" cy="{y}" r="3" fill="#222"/>')
    arr([(450, 375), (390, 375)]); txt(420, 368, "ls_dn", "middle", 10)
    for y in (330, 390, 410):
        arr([(190, y), (165, y)])
    arr([(160, 360), (190, 360)])
    for y in (440, 460, 480):
        arr([(160, y), (450, y)])
    arr([(160, 520), (680, 520)])
    s.append('<polyline points="750,480 750,155 653,155" fill="none" stroke="#6c3483" stroke-width="1.5" stroke-dasharray="5,3" marker-end="url(#ah)"/>')
    s.append('<line x1="750" y1="310" x2="653" y2="310" stroke="#6c3483" stroke-width="1.5" stroke-dasharray="5,3" marker-end="url(#ah)"/>')
    txt(756, 205, "vbp, nb, pok", sz=10.5, col="#6c3483")
    txt(500, 575, "Off (TX_EN = 0, FS_OE_A = 0, FS_RX_EN_A = 0 or VDD33 below ≈ 2.84 V): drivers off, RXDP_A = RXDM_A = 0, RXRCV_A = 1; pulls follow their enables",
        "middle", 11.5, "#c0392b")
    save_raw("block_diagram", 1080, 590, s)


# ---------------------------------------------------------------- HS plots
def fig_hs_start(S):
    p = Plot(900, 560)
    p.raw(ARROW)
    a = p.panel(90, 40, 770, 90, (-5, 35), (-0.2, 1.3), ylabel="", yticks=[0, 1],
                title="TX_EN (stimulus, grey) and rdy (ready timer): tt / ss / ff " + " / ".join(f"{S[c[0]]['ready']:.1f}" for c in CORNERS) + " ns")
    b = p.panel(90, 170, 770, 110, (-5, 35), (-50, 450), ylabel="mV", title="Dump node RDQ (22.5 Ω): the current settles here first",
                legend="tr")
    c = p.panel(90, 320, 770, 170, (-5, 35), (-480, 480), xlabel="Time after TX_EN rises  [ns]", ylabel="mV",
                title="DP − DM: lead J, then SYNC (KJKJ …) from 20.8 ns", legend="tl", yticks=[-400, -200, 0, 200, 400])
    a.line([-5, 0, 0, 35], [0, 0, 1, 1], K, 1.8)
    for cn, col, d, vl, vv, lab in CORNERS:
        w = csv(cn, "hs_start")
        if w is None:
            continue
        x = w["t_ns"] - T_EN_HS
        a.line(x, w["rdy"] / vl, col, 1.8, d)
        b.line(x, w["dq"] * 1e3, col, 1.8, d, cn)
        c.line(x, w["vd"] * 1e3, col, 1.6, d, f"transistor {lab}")
    t = np.arange(90, 140, 0.01)
    c.line(t - T_EN_HS, hs_model(t) * 1e3, B, 2.2, None, "model (t_en 20 ns, t_dly 0.5 ns)")
    c.vline(10 * UI, K, "3,3", "SYNC (lead 10)", top=False, left=True)
    c.vline(10, R, "3,3", "t_en / 2", top=False, left=True)
    p.save(os.path.join(FIG, "hs_start.svg"))


def fig_hs_bits(S):
    p = Plot(900, 420)
    t0 = T_D_HS + 40 * UI
    a = p.panel(90, 40, 770, 300, (0, 16 * UI), (-470, 760), xlabel="Time from payload bit 8  [ns]", ylabel="DP − DM  [mV]",
                title="HS data, 16 bits of PRBS7 into 45 Ω at each end, 2 pF per wire", legend="tr",
                yticks=[-400, -200, 0, 200, 400])
    a.band(360, 440, G, 0.08); a.band(-440, -360, G, 0.08)
    t = np.arange(t0 - 1, t0 + 16 * UI + 1, 0.005)
    a.line(t - t0, hs_model(t) * 1e3, B, 2.4, None, "model (0.5 ns + 625 ps linear edges)")
    for cn, col, d, vl, vv, lab in CORNERS:
        w = csv(cn, "hs_pkt")
        if w is None:
            continue
        k = (w["t_ns"] > t0 - 1) & (w["t_ns"] < t0 + 16 * UI + 1)
        a.line(w["t_ns"][k] - t0, w["vd"][k] * 1e3, col, 1.6, d, f"{lab}: delay {S[cn]['dly']:.0f} ps")
    a.text(0.2, 450, "USB 360 … 440 mV", G, 10.5)
    p.save(os.path.join(FIG, "hs_bits.svg"))


def fig_eye(S):
    p = Plot(900, 380)
    hexa = [(0.075, 0), (0.375, 300), (0.625, 300), (0.925, 0), (0.625, -300), (0.375, -300)]
    lv = hs_levels()
    for j, (cn, col, d, vl, vv, lab) in enumerate(CORNERS):
        w = csv(cn, "hs_pkt")
        dd = S[cn]
        ax = p.panel(80 + j * 275, 50, 240, 250, (-0.5, 1.5), (-500, 500), xlabel="UI", ylabel="DP − DM  [mV]" if j == 0 else "",
                     title=f"{cn}: margin {dd['mg']:+.0f} mV, peak {dd['peak']:.0f} mV", xticks=[-0.5, 0, 0.5, 1, 1.5],
                     yticks=[-400, -200, 0, 200, 400])
        if w is None:
            continue
        pts = " ".join(f"{ax._tx(x):.1f},{ax._ty(y):.1f}" for x, y in hexa)
        p.raw(f'<polygon points="{pts}" fill="#c0392b" fill-opacity="0.12" stroke="#c0392b" stroke-width="1.4"/>')
        tt = (w["t_ns"] - T_D_HS - dd["dly"] / 1e3) / UI
        for k in range(40, len(lv) - 9):
            sel = (tt >= k - 0.5) & (tt <= k + 1.5)
            ax.line((tt[sel] - k)[::2], (w["vd"][sel] * 1e3)[::2], col, 0.7)
        ax.hline(475, K, "3,3"); ax.hline(-475, K, "3,3")
    p.s.append('<text x="450" y="22" font-size="13" font-weight="bold" text-anchor="middle">HS eye, bits 40 … 158 at the mean delay; '
               'red: template 1 inner hexagon; dashed: 475 mV testbench peak</text>')
    p.save(os.path.join(FIG, "hs_eye.svg"))


def fig_hs_chirp(S):
    p = Plot(900, 380)
    t_end = T_D_HS + len(hs_levels()) * UI
    t_ch = t_end + 100
    a = p.panel(90, 40, 770, 270, (-60, 150), (-0.05, 0.9), xlabel="Time after TX_EN rises for the chirp  [ns]", ylabel="V",
                title="Device chirp K: pull-up on (from −50 ns), device termination off, host 45 Ω", legend="tl")
    t = np.arange(500, 718, 0.1)
    dp, dm = hs_chirp_model(t)
    a.line(t - t_ch, dm, B, 2.4, None, "model DM (800 mV), DP 96 mV")
    a.line(t - t_ch, dp, B, 2.0, "6,3")
    for cn, col, d, vl, vv, lab in CORNERS:
        w = csv(cn, "hs_chirp")
        if w is None:
            continue
        a.line(w["t_ns"] - t_ch, w["dm"], col, 1.6, d, f"{lab}: DM − DP {S[cn]['chirp']:.0f} mV, DP {S[cn]['chirp_dp']:.0f} mV")
        a.line(w["t_ns"] - t_ch, w["dp"], col, 1.3, d)
    a.text(100, 0.62, "USB V_CHIRPK: DM − DP 500 … 900 mV", G, 10.5, "middle")
    p.save(os.path.join(FIG, "hs_chirp.svg"))


def fig_seq_hs(S):
    p = Plot(900, 420)
    T2 = 200
    a = p.panel(90, 40, 770, 270, (-2, 52), (-0.05, 0.9), xlabel="Time after TX_EN  [ns]   (sequence of tb_afe_transceiver; DP falls from 3.0 V at 0: pull-up off)",
                ylabel="V", title="HS steps: J, K, TX_IN_P = TX_IN_N, chirp J (device termination off), TX_EN = 0", legend="tl")
    marks = [(0, "TX_EN"), (30, "K"), (40, "P = N"), (43, "chirp J"), (48, "TX off")]
    for x, tx in marks:
        a.vline(x, K, "2,3", tx, top=False)
    for cn, col, d, vl, vv, lab in CORNERS:
        w = csv(cn, "seq_hs")
        if w is None:
            continue
        a.line(w["t_ns"] - T2, w["dp"], col, 1.7, d, f"DP {lab}")
        a.line(w["t_ns"] - T2, w["dm"], col, 1.1, d)
    # model levels
    a.line([20, 30.5, 30.8, 40.5, 40.8, 43.5, 43.8, 48.5, 49.1], [0.4, 0.4, 0, 0, 0.2, 0.2, 0.8, 0.8, 0], B, 2.2, None, "model DP")
    a.text(47.5, 0.84, "800 mV", B, 10.5, "end")
    a.text(25, 0.43, "J 400 mV", B, 10.5, "middle")
    a.text(41.5, 0.24, "200 mV", B, 10.5, "middle")
    p.save(os.path.join(FIG, "hs_seq.svg"))


# ---------------------------------------------------------------- FS / LS plots
def fig_fs_packet(S):
    p = Plot(900, 600)
    ui = UI_FS
    t0 = 5 * ui + 200
    a = p.panel(90, 40, 770, 220, (-1.2 * ui, 2.5 * ui), (-0.2, 5.4), ylabel="V", yticks=[0, 1, 2, 3],
                title="FS: J idle, then SYNC (K J K …), 50 pF per wire, host 15 kΩ, device 1.5 kΩ pull-up", legend="tr")
    b = p.panel(90, 310, 770, 200, (-1.2 * ui, 2.5 * ui), (-0.3, 6.6), xlabel="Time from the first SYNC bit  [ns]",
                ylabel="", title="Receivers (each / VDD18, offset); solid: transistor tt, blue: model", yticks=[0, 2.2, 4.4],
                yfmt=lambda v: {0: "RXDM_A", 2.2: "RXDP_A", 4.4: "RXRCV_A"}.get(round(v, 1), ""))
    t = np.arange(0, 830, 0.02)
    dp, dm, rcv, rdp, rdm = fsls_model(t, False, 50)
    k = t >= 510
    t, dp, dm, rcv, rdp, rdm = t[k][::5], dp[k][::5], dm[k][::5], rcv[k][::5], rdp[k][::5], rdm[k][::5]
    a.line(t - t0, dp, B, 2.2, None, "model DP (12.5 ns ramp, 45 Ω)")
    a.line(t - t0, dm, B, 2.2, "6,3", "model DM")
    for cn, col, d, vl, vv, lab in CORNERS:
        w = csv(cn, "fs_zoom")
        if w is None:
            continue
        a.line(w["t_ns"] - t0, w["dp"], col, 1.5, d, f"{lab}")
        a.line(w["t_ns"] - t0, w["dm"], col, 1.5, d)
        if cn == "tt":
            for k, sig in enumerate(("rdm", "rdp", "rcv")):
                b.line(w["t_ns"] - t0, w[sig] / vl * 1.6 + 2.2 * k, col, 1.6)
    for k, sig in enumerate((rdm, rdp, rcv)):
        b.line(t - t0, sig / 1.8 * 1.6 + 2.2 * k, B, 1.6, "5,3")
    a.hline(2.0, K, "2,3", text="2.0 V", anchor="start"); a.hline(0.8, K, "2,3", text="0.8 V", anchor="start")
    p.save(os.path.join(FIG, "fs_packet.svg"))


def fig_fsls_edges(S):
    p = Plot(900, 420)
    specs = (("fs", False, 50, UI_FS, (-5, 25), "FS, 50 pF: 4 … 20 ns"),
             ("ls200", True, 200, UI_LS, (-40, 360), "LS, 200 pF: 75 … 300 ns"),
             ("ls600", True, 600, UI_LS, (-40, 360), "LS, 600 pF"))
    for j, (case, ls, cl, ui, xl, ttl) in enumerate(specs):
        ax = p.panel(80 + j * 275, 50, 240, 280, xl, (-0.1, 1.1), xlabel="Time from the data change  [ns]",
                     ylabel="Rising wire / VDD33" if j == 0 else "", title=ttl, legend="br", yticks=[0, 0.1, 0.5, 0.9, 1])
        t0 = 5 * ui + 200
        te = t0 + 1 * ui                               # SYNC bit 1: J; at FS the DP rises, at LS the DM rises
        tm = np.arange(0, te + 400 if ls else te + 40, 0.05 if not ls else 0.5)
        dp, dm, *_ = fsls_model(tm, ls, cl)
        k = tm > te - 50
        tm, dp, dm = tm[k], dp[k], dm[k]
        rise = dp if not ls else dm
        ax.line(tm - te, rise / 3.3, B, 2.2, None, "model")
        for cn, col, d, vl, vv, lab in CORNERS:
            w = csv(cn, case if ls else "fs_zoom")
            if w is None:
                continue
            sel = (w["t_ns"] > te - 50) & (w["t_ns"] < te + 400)
            y = (w["dp"] if not ls else w["dm"])[sel] / vv
            r = S[cn][case]["r"]
            ax.line(w["t_ns"][sel] - te, y, col, 1.5, d, f"{cn}: {r[0]:.1f} … {r[1]:.1f} ns" if not ls else f"{cn}: {r[0]:.0f} ns")
        ax.hline(0.1, K, "2,3"); ax.hline(0.9, K, "2,3")
    p.s.append('<text x="450" y="22" font-size="13" font-weight="bold" text-anchor="middle">FS / LS rising edge (SYNC bit 1, J) at the three '
               'corners against the model; legend: transistor 10–90 % rise (FS: range over the packet)</text>')
    p.save(os.path.join(FIG, "fsls_edges.svg"))


def fig_ls_packet(S):
    p = Plot(900, 400)
    ui = UI_LS
    t0 = 5 * ui + 200
    lv = fsls_levels(True)
    te = t0 + len(lv) * ui
    a = p.panel(90, 40, 770, 280, (-5 * ui / 1e3, (te + 4 * ui - t0) / 1e3), (-0.2, 3.8), xlabel="Time from the first SYNC bit  [µs]",
                ylabel="V", title="LS packet (SYNC, 12 bits, SE0 SE0 J), 600 pF per wire, transistor tt and model", legend="tr")
    t = np.arange(0, te + 4 * ui, 1.0)
    dp, dm, *_ = fsls_model(t, True, 600)
    a.line((t - t0) / 1e3, dp, B, 1.8, None, "model DP"); a.line((t - t0) / 1e3, dm, B, 1.8, "6,3", "model DM")
    w = csv("tt", "ls600")
    if w is not None:
        a.line((w["t_ns"] - t0) / 1e3, w["dp"], G, 1.4, None, "transistor DP")
        a.line((w["t_ns"] - t0) / 1e3, w["dm"], O, 1.4, None, "transistor DM")
    a.vline(-4 * ui / 1e3, K, "2,3", "FS_OE_A", top=False)
    a.vline((te - t0) / 1e3, K, "2,3", "EOP", top=False)
    p.save(os.path.join(FIG, "ls_packet.svg"))


# ---------------------------------------------------------------- receivers
def fig_receivers(S):
    p = Plot(900, 420)
    a = p.panel(80, 40, 360, 290, (0.6, 2.2), (-0.1, 1.15), xlabel="DP (= DM)  [V], slow ramp 0 → VDD33 → 0", ylabel="RXDP_A / VDD18",
                title="Single-ended receivers", legend="tl", yticks=[0, 0.5, 1])
    a.band(0, 0, G)
    p.raw(f'<rect x="{a._tx(0.8):.1f}" y="40" width="{a._tx(2.0) - a._tx(0.8):.1f}" height="290" fill="#2e8b57" fill-opacity="0.07"/>')
    a.line([0.6, 1.5, 1.5, 2.2], [0, 0, 1, 1], B, 2.4, None, "model 1.5 / 1.3 V")
    a.line([2.2, 1.3, 1.3, 0.6], [1, 1, 0, 0], B, 2.4)
    for cn, col, d, vl, vv, lab in CORNERS:
        w = csv(cn, "rx")
        if w is None:
            continue
        sel = (w["t_ns"] > 100) & (w["t_ns"] < 4100)
        se = S[cn]["se"]
        a.line(w["dp"][sel], w["rdp"][sel] / vl, col, 1.6, d, f"{cn}: {se[0]:.3f} / {se[1]:.3f} V")
    a.text(1.92, 0.3, "USB 0.8 … 2.0 V", G, 10.5, "middle")
    rows = [0.4, 0.8, 1.65, 2.5]
    b = p.panel(560, 40, 310, 290, (-220, 220), (-0.6, 5.6), xlabel="DP − DM where RXRCV_A switches  [mV]",
                title="Differential receiver RXRCV_A", yticks=[0, 1, 2, 3], yfmt=lambda v: f"CM {rows[int(round(v))]} V", legend="tr")
    p.raw(f'<rect x="{b._tx(-100):.1f}" y="40" width="{b._tx(100) - b._tx(-100):.1f}" height="290" fill="#1f4e9c" fill-opacity="0.06"/>')
    b.vline(-200, G, "4,3"); b.vline(200, G, "4,3")
    b.text(-195, 5.3, "USB ±200 mV", G, 10, "start")
    b.points([100] * 4 + [-100] * 4, [0, 1, 2, 3] * 2, B, "model ±100 mV", r=3.5)
    for j, (cn, col, d, vl, vv, lab) in enumerate(CORNERS):
        rc = S[cn]["rcv"]
        ys = [k + 0.15 * (j + 1) for k in range(4)]
        b.points([rc[cm][0] for cm in rows], ys, col, cn, marker="os^"[j])
        b.points([rc[cm][1] for cm in rows], ys, col, marker="os^"[j])
    p.save(os.path.join(FIG, "receivers.svg"))


def fig_uvlo(S):
    p = Plot(900, 380)
    a = p.panel(90, 40, 770, 260, (2.6, 3.4), (-0.1, 1.15), xlabel="VDD33  [V]  (ramp 3.3 → 2.6 → 3.3 V, DP at 2.0 V)",
                ylabel="RXDP_A / VDD18", title="Under-voltage lock-out (pok): receivers isolated, drivers off (pulls follow their enables)", legend="tl",
                yticks=[0, 0.5, 1])
    a.line([2.6, 2.97, 2.97, 3.4], [0, 0, 1, 1], B, 2.4, None, "model vdd_min 2.97 V")
    for cn, col, d, vl, vv, lab in CORNERS:
        w = csv(cn, "rx")
        if w is None:
            continue
        sel = w["t_ns"] > 12700
        u = S[cn]["uvlo"]
        a.line(w["vdd33"][sel], w["rdp"][sel] / vl, col, 1.6, d, f"{lab}: off < {u[0]:.3f} V, on > {u[1]:.3f} V")
    p.raw(f'<rect x="{a._tx(2.97):.1f}" y="40" width="{a._tx(3.0) - a._tx(2.97):.1f}" height="260" fill="#c0392b" fill-opacity="0.08"/>')
    a.text(3.005, 0.55, "3.0 V: lowest VDD33", R, 10.5)
    p.save(os.path.join(FIG, "uvlo.svg"))


def fig_seq(S):
    p = Plot(900, 560)
    w = csv("tt", "seq")
    steps = [(100, "attach"), (200, "HS"), (253, "FS J"), (353, "K"), (453, "SE0"), (553, "LS J"), (1553, "LS K"),
             (2553, "pulls"), (2653, "RX off"), (2673, "2.5 V")]
    a = p.panel(90, 40, 770, 220, (0, 2700), (-0.3, 3.6), ylabel="V", title="tb_afe_transceiver sequence at tt: DP (green), DM (orange)")
    b = p.panel(90, 300, 770, 180, (0, 2700), (-0.3, 6.6), xlabel="Time  [ns]", title="Receiver outputs (/ VDD18, offset)",
                yticks=[0, 2.2, 4.4], yfmt=lambda v: {0: "RXDM_A", 2.2: "RXDP_A", 4.4: "RXRCV_A"}.get(round(v, 1), ""))
    if w is not None:
        a.line(w["t_ns"], w["dp"], G, 1.5); a.line(w["t_ns"], w["dm"], O, 1.5)
        for k, sig in enumerate(("rdm", "rdp", "rcv")):
            b.line(w["t_ns"], w[sig] / 1.8 * 1.6 + 2.2 * k, [O, G, V][k], 1.5)
    for k, (x, tx) in enumerate(steps):
        a.vline(x, K, "2,3"); b.vline(x, K, "2,3")
        end = x > 2600
        row = 2 if x == 2673 else k % 2
        p.raw(f'<text x="{a._tx(x) + (-3 if end else 3):.1f}" y="{a.y0 + 14 + 13 * row}" font-size="10.5" fill="#555" '
              f'text-anchor="{"end" if end else "start"}">{_esc(tx)}</text>')
    p.save(os.path.join(FIG, "sequence.svg"))


def fig_corners(S):
    """the key figures against their limits over the corners"""
    p = Plot(900, 470)
    rows = [("ready after TX_EN [ns]", "ready", (10, 21.3), 20, (0, 25)),
            ("TX_IN → line delay [ns] (testbench 0.5 … 1.3)", "dly", (0.5, 1.3), 0.81, (0, 1.6)),
            ("HS 10–90 % edge, min [ps]", "r_lo", (500, None), 500, (0, 1200)),
            ("crossing jitter [ps p-p]", "jit", (None, 100), None, (0, 120)),
            ("first SYNC bit [%]", "first", (-2, 2), 0, (-3, 3)),
            ("eye margin to template 1 [mV]", "mg", (0, None), None, (0, 120))]
    for k, (lab, key, lim, mod, xl) in enumerate(rows):
        col_, row_ = k % 2, k // 2
        ax = p.panel(90 + col_ * 430, 40 + row_ * 140, 360, 80, xl, (-0.5, 2.5), title=lab, yticks=[0, 1, 2],
                     yfmt=lambda v: ["tt", "ss", "ff"][int(round(v))])
        lo, hi = lim
        x0 = ax._tx(lo if lo is not None else xl[0]); x1 = ax._tx(hi if hi is not None else xl[1])
        p.raw(f'<rect x="{x0:.1f}" y="{ax.y0}" width="{x1 - x0:.1f}" height="{ax.h}" fill="#2e8b57" fill-opacity="0.10"/>')
        if mod is not None:
            ax.vline(mod, B, "5,4")
        for j, (cn, col, d, vl, vv, lab2) in enumerate(CORNERS):
            v = S[cn][key] / (1e3 if key == "dly" else 1)
            if key == "r_lo":
                v = min(S[cn]["r_lo"], S[cn]["f_lo"])
            ax.points([v], [j], col, marker="os^"[j], r=5)
            p.raw(f'<text x="{ax._tx(v) + 9:.1f}" y="{ax._ty(j) + 4:.1f}" font-size="10.5" fill="{col}">{v:.4g}</text>')
    p.s.append('<text x="90" y="460" font-size="11.5" fill="#555">Green: limit (USB 2.0 or testbench); blue dashed: the model\'s '
               'value. Transistor values from the hs case.</text>')
    p.save(os.path.join(FIG, "hs_corners.svg"))


# ---------------------------------------------------------------- main
def main():
    os.makedirs(FIG, exist_ok=True)
    S = {c[0]: summary(c[0]) for c in CORNERS}
    for c in S:
        d = S[c]
        print(c, "PASSED" if d["passed"] else "NOT PASSED / missing",
              {k: d[k] for k in ("ready", "dly", "jit", "st_lo", "st_hi", "first", "mg", "peak", "r_lo", "f_lo", "chirp", "seq_dly")})
        print("  fs", d["fs"], "\n  ls200", d["ls200"], "\n  se", d["se"], "rcv", d["rcv"], "uvlo", d["uvlo"], "\n  dc", d["dc"])
    fig_block(); fig_hs_start(S); fig_hs_bits(S); fig_eye(S); fig_hs_chirp(S); fig_seq_hs(S); fig_corners(S)
    fig_fs_packet(S); fig_fsls_edges(S); fig_ls_packet(S); fig_receivers(S); fig_uvlo(S); fig_seq(S)
    if "--no-png" not in sys.argv:
        for f in sorted(os.listdir(FIG)):
            if f.endswith(".svg"):
                subprocess.run(["rsvg-convert", "-z", "2", "-o", os.path.join(FIG, f[:-4] + ".png"), os.path.join(FIG, f)], check=True)
    print("figures in", FIG)


if __name__ == "__main__":
    main()
