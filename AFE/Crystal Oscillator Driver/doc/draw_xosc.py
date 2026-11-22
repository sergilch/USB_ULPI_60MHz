#!/usr/bin/env python3
"""draw_xosc.py - SVG schematic sheets of afe_xosc_tr.sp

    python3 "AFE/Crystal Oscillator Driver/doc/draw_xosc.py"
        -> AFE/Crystal Oscillator Driver/doc/xosc_*.svg (+ .png with rsvg-convert)

Same symbols and conventions as AFE/spice/doc/draw_cdr.py (imported):
3-terminal MOS (PMOS with gate bubble, source on top), zig-zag resistor,
two-plate capacitor, VDD bar, ground; one accent colour for the signal path.
All MOS are xh018 ne3i / pe3i (3.3 V isolated), W / L in um.

Sheets
  xosc_block.svg   block diagram: crystal, pads, amplifier, ALC, squarer, PLL
  xosc_core.svg    bias, regulated branch, current-source bank, Pierce amplifier
  xosc_alc.svg     amplitude regulation: divider, peak detector, error pair
  xosc_sq.svg      squarer, Schmitt trigger, output gate, enable logic
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "AFE", "spice", "doc"))
from draw_cdr import Sheet, STYLE  # noqa: E402


def xtal(s, x, y):
    """horizontal crystal symbol centred at (x, y): leads at x-30 / x+30"""
    s.line((x - 30, y), (x - 9, y))
    s.line((x + 9, y), (x + 30, y))
    s.line((x - 9, y - 12), (x - 9, y + 12))
    s.line((x + 9, y - 12), (x + 9, y + 12))
    s.el.append(f'<rect x="{x - 5}" y="{y - 15}" width="10" height="30" fill="none" stroke="currentColor"/>')


# ------------------------------------------------------------------ block
def sheet_block():
    s = Sheet(1060, 470, "Block diagram: the external 24 MHz crystal with C1 and C2 on the XI and XO pads, the on-chip "
                         "Pierce amplifier with RF, the amplitude regulation and bias, and the squarer that drives "
                         "REF_CLK into the PLL reference input CDR_FREF")
    # board
    s.el.append('<rect x="-30" y="12" width="300" height="250" rx="6" fill="none" stroke="currentColor" '
                'stroke-dasharray="5 4" opacity=".6"/>')
    s.text(-20, 32, "PCB (external)", "start", "ar")
    xtal(s, 120, 80)
    s.text(120, 58, "Y1  24 MHz, CL 8 pF", "middle", "dev")
    s.text(120, 112, "VXM7A-9001-24M", "middle", "sz")
    s.line((90, 80), (40, 80), (40, 170)); s.dot(40, 170)
    s.line((150, 80), (210, 80), (210, 170)); s.dot(210, 170)
    s.cap(40, 170, 225, "C1", "12 pF", "r"); s.gnd(40, 225)
    s.cap(210, 170, 225, "C2", "12 pF", "l"); s.gnd(210, 225)
    s.line((40, 170), (-10, 170), (-10, 300), (330, 300), acc=True)
    s.line((210, 170), (250, 170), (250, 260), (430, 260))
    # pads
    s.box(330, 285, 60, 30, "XI", None, acc=True)
    s.box(430, 245, 60, 30, "XO", None)
    s.text(330, 345, "XI, XO: analog pads APR00F", "start", "sz")
    s.text(-20, 330, "≈ 2.5 pF per pin (pad, bond, package)", "start", "ar")
    # chip outline
    s.el.append('<rect x="300" y="135" width="760" height="320" rx="6" fill="none" stroke="currentColor" opacity=".6"/>')
    s.text(1050, 155, "afe_xosc_tr (VDD18A)", "end", "ar")
    # amplifier
    s.line((390, 300), (560, 300), acc=True); s.dot(520, 300)
    s.line((490, 260), (540, 260), (540, 230), (625, 230))
    s.box(560, 270, 130, 60, "Pierce gm stage", "MA1 + I source bank", acc=True)
    s.line((625, 270), (625, 230))
    s.text(632, 222, "XO", "start", "sz")
    s.hres(420, 520, 200, "RF", "1 MΩ")
    s.line((420, 200), (410, 200), (410, 300))
    s.line((520, 200), (540, 200), (540, 230))
    s.dot(410, 300); s.dot(540, 230)
    # bias / ALC
    s.box(560, 360, 130, 60, "bias + DRV", "I_REF 40 µA, ×12.5")
    s.arrow(625, 360, 625, 330, None)
    s.text(632, 350, "I_core 250–625 µA", "start", "ar")
    s.box(760, 360, 150, 60, "ALC", "peak det. + error pair")
    s.arrow(760, 390, 690, 390, "−ΔI", lx=725, ly=383)
    s.line((520, 300), (520, 440), (835, 440), (835, 420))
    s.text(700, 455, "XI amplitude sense", "middle", "ar")
    # squarer
    s.box(760, 175, 150, 60, "squarer", "AC-coupled, self-biased", acc=True)
    s.dot(410, 200)
    s.line((410, 200), (410, 160), (720, 160), (720, 205), (760, 205), acc=True)
    s.box(760, 260, 150, 50, "Schmitt + gate", "XTAL_EN", acc=True)
    s.arrow(835, 235, 835, 260, None, acc=True)
    s.line((910, 285), (980, 285), acc=True)
    s.pin(984, 285, "REF_CLK", "r", acc=True)
    s.text(990, 305, "→ CDR_FREF of afe_pll", "start", "ar")
    # control pins
    s.pin(330, 395, "XTAL_EN", "r")
    s.pin(330, 420, "DRV1, DRV0", "r")
    s.line((334, 395), (450, 395)); s.line((334, 420), (450, 420)); s.line((450, 395), (450, 420))
    s.arrow(450, 408, 560, 408, None)
    s.vdd(1000, 400, "VDD18A")
    s.gnd(1000, 425)
    return s


# ------------------------------------------------------------------- core
def sheet_core():
    s = Sheet(1180, 610, "Core: I_REF from RB and MB1, unregulated PMOS bias po, regulated diode MB9 (ALC current "
                         "MR5 subtracted), mirror into MB3, PMOS current-source bank with DRV switches feeding XO, "
                         "NMOS gm stage MA1 with RF from XO to XI")
    top, bot = 40, 520
    # MB0 / RB / MB1
    s.vdd(60, top)
    m = s.mos(45, 90, "p", "MB0", "4/0.3")
    s.line((60, top), m["u"]); s.text(5, 94, "ENB", "end", "lb"); s.line(m["g"], (5 + 2, 90))
    s.res(60, 120, 200, "RB", "18 kΩ")
    s.line(m["d"], (60, 120))
    s.dot(60, 200)
    m = s.mos(45, 260, "n", "MB1", "8/2")
    s.line((60, 200), m["u"]); s.line(m["d"], (60, bot)); s.gnd(60, bot)
    s.line((60, 215), (0, 215), (0, 260), m["g"])
    s.dot(60, 215)
    s.text(0, 238, "nb", "end", "sz")
    # MB7 / MB6 (po)
    s.vdd(200, top)
    m6 = s.mos(185, 90, "p", "MB6", "20/1")
    s.line((200, top), m6["u"])
    s.dot(200, 135); s.line(m6["d"], (200, 135))
    s.line((200, 135), (150, 135), (150, 90), m6["g"])
    s.text(150, 150, "po", "middle", "sz")
    m7 = s.mos(185, 260, "n", "MB7", "8/2")
    s.line((200, 135), m7["u"]); s.line(m7["d"], (200, bot)); s.gnd(200, bot)
    s.line((0, 260), (0, 330), (130, 330), (130, 260), m7["g"])
    s.dot(130, 330) if False else None
    # MB10 / MB9 (nc) + MR5
    s.vdd(330, top)
    m10 = s.mos(315, 90, "p", "MB10", "20/1")
    s.line((200, 135), (240, 135), (240, 90), (285, 90))
    s.dot(240, 135)
    s.line((330, top), m10["u"])
    s.dot(330, 200)
    s.line(m10["d"], (330, 200))
    m9 = s.mos(315, 260, "n", "MB9", "8/2")
    s.line((330, 200), m9["u"]); s.line(m9["d"], (330, bot)); s.gnd(330, bot)
    s.line((330, 215), (270, 215), (270, 260), (285, 260))
    s.dot(330, 215)
    s.text(276, 238, "nc", "start", "sz")
    m5 = s.mos(395, 360, "n", "MR5", "8/2", mirror=True)
    s.line((330, 200), (380, 200), (380, 330))
    s.dot(380, 330) if False else None
    s.line(m5["d"], (380, bot)); s.gnd(380, bot)
    s.line(m5["g"], (450, 360))
    s.pin(454, 360, "nq (ALC)", "r")
    # MB2 / MB3 (pb)
    s.vdd(530, top)
    m3 = s.mos(515, 90, "p", "MB3", "20/1")
    s.line((530, top), m3["u"])
    s.dot(530, 135); s.line(m3["d"], (530, 135))
    s.line((530, 135), (480, 135), (480, 90), m3["g"])
    s.text(480, 150, "pb", "middle", "sz")
    s.cap(610, 50, 115, "CB", "2 pF", "l")
    s.line((610, 50), (610, top), (530, top))
    s.line((610, 115), (610, 135), (530, 135))
    m2 = s.mos(515, 260, "n", "MB2", "8/2")
    s.line((530, 135), m2["u"]); s.line(m2["d"], (530, bot)); s.gnd(530, bot)
    s.line((270, 260), (270, 300), (470, 300), (470, 260), m2["g"])
    s.dot(270, 300) if False else None
    # current-source bank
    s.line((480, 135), (480, 175), (640, 175))
    s.dot(640, 175)
    xs = [(670, "MC1", "125/1", None), (790, "MC2", "62.5/1", ("MS0", "25/0.3", "D0B")),
          (910, "MC3", "125/1", ("MS1", "50/0.3", "D1B"))]
    for x, n, sz, sw in xs:
        s.vdd(x + 15, top)
        m = s.mos(x, 90, "p", n, sz)
        s.line((x + 15, top), m["u"])
        s.line((x - 30, 175), (x - 30, 90), m["g"]) if x == 670 else s.line((x - 30, 175), (x - 30, 90), m["g"])
        if sw:
            ms = s.mos(x, 190, "p", sw[0], sw[1])
            s.line(m["d"], ms["u"])
            s.line(ms["g"], (x - 40, 190))
            s.text(x - 44, 194, sw[2], "end", "lb")
            s.line(ms["d"], (x + 15, 260))
        else:
            s.line(m["d"], (x + 15, 260))
    s.line((640, 175), (880, 175))
    s.line((685, 260), (1045, 260), acc=True)
    s.dot(685, 260); s.dot(805, 260); s.dot(925, 260)
    s.text(0, 590, "I_core = 125 µA × (2 + DRV0 + 2·DRV1) × (1 − I(MR5) / I_REF)", "start", "ar")
    # amplifier
    ma = s.mos(1060, 330, "n", "MA1", "200/0.5", mirror=True)
    s.line((1045, 260), ma["u"], acc=True)
    s.line(ma["d"], (1045, bot)); s.gnd(1045, bot)
    s.line(ma["g"], (1090, 330), (1090, 440), acc=True)
    s.dot(1090, 440)
    s.line((1045, 260), (1130, 260), (1130, 300))
    s.dot(1045, 260)
    s.res(1130, 300, 410, "RF", "1 MΩ", "r")
    s.line((1130, 410), (1130, 440), (1090, 440))
    s.line((1090, 440), (1090, 456), acc=True)
    s.pin(1090, 460, "XI", "b", acc=True)
    s.pin(1045, 230, "XO", "t", acc=True)
    s.line((1045, 260), (1045, 234), acc=True)
    ma2 = s.mos(960, 470, "n", "MA2", "2/0.35")
    s.line((1090, 440), (975, 440))
    s.line(ma2["d"], (975, bot)); s.gnd(975, bot)
    s.text(926, 474, "ENB", "end", "lb"); s.line(ma2["g"], (928, 470))
    s.text(0, 570, "Disabled (XTAL_EN = 0): MB0 off, pb / po high, nb / nc low, XI pulled low by MA2", "start", "ar")
    return s


# -------------------------------------------------------------------- alc
def sheet_alc():
    s = Sheet(1040, 570, "Amplitude regulation: divider vb / vbl, XI AC-coupled through CD onto vbl, peak-detecting "
                         "follower MR1 on CPK against the reference follower MR2 on vb, PMOS error pair MRA / MRB with "
                         "tail MRT, MR6 diode drives MR5 which subtracts from the regulated bias")
    top, bot = 40, 490

    def lab(x, y, name, anchor="end"):
        s.text(x, y + 4, name, anchor, "pin")

    # divider
    s.vdd(40, top)
    s.res(40, top, 120, "RV1", "600 kΩ", "r")
    s.dot(40, 120); s.text(32, 116, "vb", "end", "sz")
    s.res(40, 120, 210, "RVS", "150 kΩ", "r")
    s.dot(40, 210); s.text(32, 206, "vbl", "end", "sz")
    s.res(40, 210, 300, "RV2", "750 kΩ", "r")
    m = s.mos(25, 360, "n", "MRV", "1/0.35")
    s.line((40, 300), m["u"]); s.line(m["d"], (40, bot)); s.gnd(40, bot)
    s.text(-10, 364, "EN", "end", "lb"); s.line(m["g"], (-8, 360))
    s.cap(100, 120, 175, "CVB", "2 pF", "r"); s.line((40, 120), (100, 120)); s.gnd(100, 175)
    # XI coupling
    s.pin(180, 20, "XI", "r", acc=True)
    s.line((180, 24), (180, 60), acc=True)
    s.cap(180, 60, 110, "CD", "1 pF", "r")
    s.line((180, 110), (180, 140), acc=True)
    s.dot(180, 140); s.text(172, 136, "dI", "end", "sz")
    s.hres(40, 180, 210, "RD", "2 MΩ")
    s.line((40, 210), (40, 230)) if False else None
    s.line((180, 210), (180, 140))
    s.dot(40, 230) if False else None
    s.line((40, 210), (60, 210), (60, 230), (40 + 0, 230)) if False else None
    # follower MR1 + CPK + MR3
    s.vdd(260, top)
    m1 = s.mos(245, 140, "n", "MR1", "4/1, B = S")
    s.line((260, top), m1["u"]); s.line((180, 140), m1["g"], acc=True)
    s.line(m1["d"], (260, 230), acc=True)
    s.dot(260, 230); s.text(252, 226, "pk", "end", "sz")
    s.line((260, 230), (330, 230))
    s.cap(330, 230, 290, "CPK", "8 pF", "r"); s.gnd(330, 290)
    m3 = s.mos(245, 340, "n", "MR3", "8/2")
    s.line((260, 230), m3["u"]); s.line(m3["d"], (260, bot)); s.gnd(260, bot)
    # reference follower MR2 + MR4
    s.vdd(460, top)
    m2 = s.mos(445, 140, "n", "MR2", "4/1, B = S")
    s.line((460, top), m2["u"])
    s.line(m2["g"], (395, 140)); lab(391, 140, "vb")
    s.line(m2["d"], (460, 230))
    s.dot(460, 230); s.text(468, 226, "rf", "start", "sz")
    m4 = s.mos(445, 340, "n", "MR4", "8/2")
    s.line((460, 230), m4["u"]); s.line(m4["d"], (460, bot)); s.gnd(460, bot)
    # I_PK reference MRP / MRD and the npk bus
    s.vdd(600, top)
    mp = s.mos(585, 100, "p", "MRP", "1.25/1")
    s.line((600, top), mp["u"]); s.line(mp["g"], (540, 100)); lab(536, 100, "po")
    s.line(mp["d"], (600, 300)); s.dot(600, 300)
    md = s.mos(585, 360, "n", "MRD", "8/2")
    s.line((600, 300), md["u"]); s.line(md["d"], (600, bot)); s.gnd(600, bot)
    s.line((600, 300), (555, 300), (555, 420))
    s.line((555, 360), md["g"])
    s.dot(555, 360)
    s.text(561, 296, "npk", "end", "sz")
    s.line((555, 420), (200, 420), (200, 340), m3["g"])
    s.line((400, 420), (400, 340), m4["g"])
    s.dot(400, 420)
    # error pair
    s.vdd(800, top)
    mt = s.mos(785, 90, "p", "MRT", "20/1")
    s.line((800, top), mt["u"]); s.line(mt["g"], (740, 90)); lab(736, 90, "po")
    s.line(mt["d"], (800, 150)); s.dot(800, 150); s.text(806, 146, "rt", "start", "sz")
    ma = s.mos(725, 210, "p", "MRA", "80/1")
    mb = s.mos(885, 210, "p", "MRB", "80/1", mirror=True)
    s.line((740, 180), (740, 150), (870, 150), (870, 180))
    s.line(ma["g"], (680, 210)); lab(676, 210, "pk")
    s.line(mb["g"], (950, 210)); lab(954, 210, "rf", "start")
    s.line(ma["d"], (740, bot)); s.gnd(740, bot)
    s.line(mb["d"], (870, 300)); s.dot(870, 300)
    m6 = s.mos(855, 360, "n", "MR6", "8/2")
    s.line((870, 300), m6["u"]); s.line(m6["d"], (870, bot)); s.gnd(870, bot)
    s.line((870, 300), (790, 300), (790, 420))
    s.line((790, 360), m6["g"]); s.dot(790, 360)
    s.text(-40, 510, "Followers MR1 / MR2 and the pair MRA / MRB have their bulk on their source (isolated devices).",
           "start", "ar")
    s.text(784, 296, "nq", "end", "sz")
    s.line((790, 420), (930, 420))
    s.pin(934, 420, "nq → MR5", "r")
    s.text(-40, 530, "I_PK = I_REF / 16 = 2.5 µA (MR3, MR4).  V(pk) − V(rf) ≈ A_XI − V_SET − peak offset, "
                     "V_SET = 0.1·VDD", "start", "ar")
    s.text(-40, 550, "A_XI above the set point ⇒ I(MRB) → I_REF ⇒ MR5 takes I_REF out of nc ⇒ I_core falls",
           "start", "ar")
    return s


# --------------------------------------------------------------------- sq
def sheet_sq():
    s = Sheet(1100, 470, "Squarer: XI AC-coupled by CC into INV1 (header MS1H, self-bias RSB), 6-transistor Schmitt "
                         "trigger, NAND with XTAL_EN and the output inverter driving REF_CLK; enable logic for ENB and "
                         "the DRV segment switches")
    top, bot = 40, 330
    s.pin(20, 190, "XI", "l", acc=True)
    s.line((24, 190), (50, 190), acc=True)
    s.el.append('<g>')
    s.line((50, 178), (50, 202)); s.line((58, 178), (58, 202))
    s.el.append('</g>')
    s.text(54, 168, "CC 0.5 pF", "middle", "dev")
    s.line((58, 190), (110, 190), acc=True)
    s.dot(110, 190)
    s.text(110, 182, "sa", "middle", "sz")
    # INV1 transistor-level
    s.vdd(205, top)
    mh = s.mos(190, 80, "p", "MS1H", "12/0.3")
    s.line((205, top), mh["u"]); s.line(mh["g"], (150, 80)); s.text(146, 84, "ENB", "end", "lb")
    mp = s.mos(190, 150, "p", "XS1P", "6/0.3")
    s.line(mh["d"], mp["u"])
    s.dot(205, 190)
    s.line(mp["d"], (205, 190))
    mn = s.mos(190, 230, "n", "XS1N", "2/0.35")
    s.line((205, 190), mn["u"]); s.line(mn["d"], (205, bot)); s.gnd(205, bot)
    s.line((110, 190), (140, 190), (140, 150), mp["g"])
    s.line((140, 190), (140, 230), mn["g"])
    s.line((110, 190), (110, 290), (130, 290))
    s.hres(130, 230, 290, "RSB", "500 kΩ")
    s.line((230, 290), (250, 290), (250, 190), (205, 190))
    s.text(258, 182, "sb", "start", "sz")
    m5 = s.mos(300, 250, "n", "XS5", "1/0.35", mirror=True)
    s.line((250, 190), (285, 190), (285, 220))
    s.line(m5["d"], (285, bot)); s.gnd(285, bot)
    s.line(m5["g"], (350, 250)); s.text(354, 254, "ENB", "start", "lb")
    # Schmitt
    x0 = 470
    s.vdd(x0 + 15, top)
    p1 = s.mos(x0, 80, "p", "XS2P1", "4/0.3")
    p2 = s.mos(x0, 140, "p", "XS2P2", "4/0.3")
    s.line((x0 + 15, top), p1["u"]); s.line(p1["d"], p2["u"])
    s.dot(x0 + 15, 190); s.line(p2["d"], (x0 + 15, 190))
    n2 = s.mos(x0, 240, "n", "XS2N2", "2/0.35")
    n1 = s.mos(x0, 300, "n", "XS2N1", "2/0.35")
    s.line((x0 + 15, 190), n2["u"]); s.line(n2["d"], n1["u"]); s.line(n1["d"], (x0 + 15, bot + 40)); s.gnd(x0 + 15, bot + 40)
    s.line((285, 190), (400, 190), acc=True)
    s.line((400, 80), (400, 300))
    s.line((400, 80), p1["g"]); s.line((400, 140), p2["g"]); s.line((400, 240), n2["g"]); s.line((400, 300), n1["g"])
    s.dot(400, 190); s.dot(400, 140); s.dot(400, 240)
    # feedback devices
    s.dot(x0 + 15, 110)
    pf = s.mos(x0 + 90, 125, "p", "XS2P3", "1/0.3")
    s.line((x0 + 15, 110), (x0 + 105, 110), (x0 + 105, 95)) if False else None
    s.line((x0 + 15, 110), (x0 + 105, 110))
    s.line(pf["u"], (x0 + 105, 110))
    s.line(pf["d"], (x0 + 105, 170)); s.gnd(x0 + 105, 170)
    s.dot(x0 + 15, 270)
    nf = s.mos(x0 + 90, 255, "n", "XS2N3", "0.5/0.35")
    s.line((x0 + 15, 270), (x0 + 105, 270), (x0 + 105, 285))
    s.line(nf["u"], (x0 + 105, 210)); s.vdd(x0 + 105, 210)
    s.line((x0 + 15, 190), (x0 + 50, 190), (x0 + 50, 125), pf["g"])
    s.line((x0 + 50, 190), (x0 + 50, 255), nf["g"])
    s.dot(x0 + 50, 190)
    s.line((x0 + 50, 190), (680, 190), acc=True)
    s.text(660, 182, "sc", "middle", "sz")
    # NAND + inverter
    s.el.append(f'<path d="M680,170 h22 a20,20 0 0 1 0,40 h-22 z" fill="var(--panel, none)" stroke="currentColor"/>')
    s.el.append('<circle cx="726" cy="190" r="4" fill="var(--bg, #fff)" stroke="currentColor"/>')
    s.text(700, 162, "XS3 (NAND)", "middle", "dev")
    s.line((660, 202), (680, 202)); s.text(656, 222, "XTAL_EN", "end", "lb")
    s.line((660, 202), (660, 218))
    s.line((730, 190), (760, 190), acc=True)
    o = s.inv(760, 190, "XS4", "12/0.3 | 6/0.35", 30)
    s.line(o, (840, 190), acc=True)
    s.pin(844, 190, "REF_CLK → CDR_FREF", "r", acc=True)
    # logic legend
    s.text(0, 420, "Enable logic: ENB = !XTAL_EN (XL1), D0B = NAND(XTAL_EN, DRV0), D1B = NAND(XTAL_EN, DRV1)",
           "start", "ar")
    s.text(0, 440, "INV1 (XS1P / XS1N) is self-biased at its trip point through RSB (sb ≈ 0.94 V at tm, 27 °C, 1.8 V)",
           "start", "ar")
    return s


def main():
    sheets = {"block": sheet_block, "core": sheet_core, "alc": sheet_alc, "sq": sheet_sq}
    for name, fn in sheets.items():
        s = fn()
        svg = s.svg().replace("<defs>", STYLE + "<defs>", 1)
        # standalone file: white background so the PNG / Word copy is readable
        svg = svg.replace('class="sch"', 'class="sch" style="background:#fff;color:#17221f"', 1)
        p = os.path.join(HERE, f"xosc_{name}.svg")
        open(p, "w").write(svg)
        if shutil.which("rsvg-convert"):
            subprocess.run(["rsvg-convert", "-z", "2", "-b", "white", "-o", p[:-4] + ".png", p], check=True)
        print("wrote", p)


if __name__ == "__main__":
    main()
