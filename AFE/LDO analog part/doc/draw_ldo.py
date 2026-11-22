#!/usr/bin/env python3
"""draw_ldo.py - SVG schematic sheets of afe_ldo_tr.sp

    python3 "AFE/LDO analog part/doc/draw_ldo.py"
        -> AFE/LDO analog part/doc/ldo_*.svg (+ .png with rsvg-convert)

Same symbols and conventions as AFE/spice/doc/draw_cdr.py (imported):
3-terminal MOS (PMOS with gate bubble, source on top), zig-zag resistor,
two-plate capacitor, rail bar, ground; one accent colour for the main path.
All MOS are xh018 ne3i / pe3i (3.3 V isolated), W / L in um; m = multiplier.

Sheets
  ldo_block.svg       block diagram
  ldo_bandgap.svg     bandgap core, op-amp, start-up, bias outputs
  ldo_regulator.svg   soft start, error amplifier, buffer, pass device,
                      current limit, divider, discharge
  ldo_supervisor.svg  enable input, UVLO, power good, delays, outputs
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "AFE", "spice", "doc"))
from draw_cdr import Sheet, STYLE  # noqa: E402


def diode(s, x, y1, y2, name, val, lab="r"):
    """vertical diode, anode (x, y1) on top, cathode (x, y2)"""
    m = (y1 + y2) / 2
    s.line((x, y1), (x, m - 8))
    s.el.append(f'<polygon points="{x - 9},{m - 8} {x + 9},{m - 8} {x},{m + 6}" fill="var(--panel, none)" '
                f'stroke="currentColor"/>')
    s.line((x - 9, m + 6), (x + 9, m + 6))
    s.line((x, m + 6), (x, y2))
    tx, anc = (x + 16, "start") if lab == "r" else (x - 16, "end")
    s.text(tx, m - 2, name, anc, "dev")
    s.text(tx, m + 11, val, anc, "sz")


def comp(s, x, y, name, sub=None):
    """comparator triangle, + input (x, y-12), - input (x, y+12), output (x+50, y)"""
    s.el.append(f'<polygon points="{x},{y - 28} {x},{y + 28} {x + 50},{y}" fill="var(--panel, none)" '
                f'stroke="currentColor"/>')
    s.text(x + 6, y - 8, "+", "start", "lb")
    s.text(x + 6, y + 16, "−", "start", "lb")
    s.text(x + 22, y - 32, name, "middle", "dev")
    if sub:
        s.text(x + 22, y + 44, sub, "middle", "sz")
    return (x, y - 12), (x, y + 12), (x + 50, y)


def nand(s, x, y, name=None):
    """NAND, inputs (x, y-8) / (x, y+8), output (x+46, y)"""
    s.el.append(f'<path d="M{x},{y - 18} h20 a18,18 0 0 1 0,36 h-20 z" fill="var(--panel, none)" stroke="currentColor"/>')
    s.el.append(f'<circle cx="{x + 42}" cy="{y}" r="4" fill="var(--bg, #fff)" stroke="currentColor"/>')
    if name:
        s.text(x + 20, y - 23, name, "middle", "dev")
    return (x, y - 8), (x, y + 8), (x + 46, y)


def schmitt(s, x, y, name=None, sub=None):
    """Schmitt buffer, input (x, y), output (x + 38, y)"""
    s.el.append(f'<polygon points="{x},{y - 18} {x},{y + 18} {x + 38},{y}" fill="var(--panel, none)" stroke="currentColor"/>')
    s.el.append(f'<path d="M{x + 6},{y + 5} h7 v-10 h7 M{x + 9},{y + 5} h7 v-10 h5" stroke-width="1"/>')
    if name:
        s.text(x + 18, y - 24, name, "middle", "dev")
    if sub:
        s.text(x + 18, y + 32, sub, "middle", "sz")
    return (x + 38, y)


def amp(s, x, y, name, sub=None, acc=False):
    """op-amp / error amplifier, + input (x, y-14), - input (x, y+14), output (x+60, y)"""
    st = 'stroke="var(--accent, #0f7c80)" stroke-width="1.8"' if acc else 'stroke="currentColor"'
    s.el.append(f'<polygon points="{x},{y - 34} {x},{y + 34} {x + 60},{y}" fill="var(--panel, none)" {st}/>')
    s.text(x + 7, y - 10, "+", "start", "lb")
    s.text(x + 7, y + 18, "−", "start", "lb")
    s.text(x + 26, y - 40, name, "middle", "dev")
    if sub:
        s.text(x + 26, y + 52, sub, "middle", "sz")
    return (x, y - 14), (x, y + 14), (x + 60, y)


# ------------------------------------------------------------------ block
def sheet_block():
    s = Sheet(1130, 520, "Block diagram of afe_ldo_tr: the bandgap, soft-start filter, error amplifier, gate buffer and "
                         "PMOS pass device regulating VOUT through the feedback divider; current limit, UVLO and "
                         "enable logic, power-good comparator with the 10 us and 100 us delays driving PWR_GOOD "
                         "and POR_N")
    s.pin(10, 50, "VIN 3.3 V", "tl", acc=True)
    s.line((14, 50), (1000, 50), acc=True)
    s.pin(10, 470, "GND", "r")
    # bandgap
    s.box(40, 120, 150, 70, "Bandgap", "VBG 1.187 V, 5 µA bias")
    s.line((115, 50), (115, 120))
    # soft start
    s.line((190, 150), (240, 150))
    s.hres(240, 320, 150, "RSS", "5 MΩ")
    s.line((320, 150), (360, 150)); s.dot(340, 150)
    s.cap(340, 150, 210, "CSS", "10 pF", "l"); s.gnd(340, 210)
    s.text(350, 140, "vr", "start", "sz")
    # error amp
    ip, im, o = amp(s, 400, 170, "Error amplifier", acc=True)
    s.line((360, 150), (380, 150), (380, ip[1]), ip)
    s.line(o, (500, 170), acc=True)
    s.box(500, 145, 90, 50, "Buffer", "PMOS SF 20 µA")
    s.line((590, 170), (660, 170), acc=True)
    s.text(625, 162, "gp", "middle", "sz")
    # pass device
    mp = s.mos(690, 170, "p", "MPASS", "20/0.5 ×120")
    s.line(mp["g"], (660, 170), acc=True)
    s.line(mp["u"], (705, 50), acc=True)
    s.line(mp["d"], (705, 260), acc=True)
    s.dot(705, 260)
    s.line((705, 260), (1000, 260), acc=True)
    s.pin(1004, 260, "VOUT 1.8 V", "r", acc=True)
    # COUT
    s.line((940, 260), (940, 300)); s.dot(940, 260)
    s.cap(940, 300, 360, "COUT", "1 µF (ext.)", "r"); s.gnd(940, 360)
    s.text(940, 395, "0.47–2.2 µF, ESR ≤ 0.5 Ω", "middle", "ar")
    # divider
    s.line((790, 260), (790, 280)); s.dot(790, 260)
    s.res(790, 280, 340, "RDA–RDB", "61.3 kΩ")
    s.dot(790, 340)
    s.res(790, 340, 400, "RDC", "118.7 kΩ"); s.gnd(790, 400)
    s.line((790, 340), (560, 340), (560, 260), (370, 260), (370, im[1]), im)
    s.text(565, 335, "fb = 0.659 × VOUT", "start", "ar")
    # current limit
    s.box(560, 80, 110, 40, "I limit", "sense 1:1200")
    s.line((615, 120), (615, 140), (530, 140), (530, 145))
    s.text(612, 136, "≈ 75 mA", "end", "ar")
    # discharge
    s.box(840, 180, 80, 40, "Discharge", "≈ 0.6 kΩ")
    s.line((880, 220), (880, 260)); s.dot(880, 260)
    # supervisor
    s.box(40, 290, 160, 70, "Enable + UVLO", "2.7 V ↑ / 2.5 V ↓")
    s.pin(10, 325, "LDO_EN", "tl")
    s.line((14, 325), (40, 325))
    s.line((120, 290), (120, 190))
    s.text(126, 250, "bg_ok, VBG", "start", "ar")
    s.line((200, 325), (260, 325), (260, 190), (230, 190), (230, 155), dash=True)
    s.text(268, 310, "on / onb", "start", "ar")
    s.line((880, 140), (880, 180), dash=True)
    s.text(886, 150, "onb", "start", "ar")
    s.box(300, 400, 160, 60, "Power good", "1.62 V ↑ / 1.55 V ↓")
    s.line((790, 300), (720, 300), (720, 380), (380, 380), (380, 400))
    s.text(600, 374, "pr / pf taps", "middle", "ar")
    s.dot(790, 300)
    s.box(520, 400, 130, 60, "Delay 10 µs", "→ PWR_GOOD")
    s.box(700, 400, 130, 60, "Delay 100 µs", "→ POR_N")
    s.arrow(460, 430, 520, 430)
    s.arrow(650, 430, 700, 430)
    s.line((585, 460), (585, 490), (1000, 490))
    s.pin(1004, 490, "PWR_GOOD", "r")
    s.line((830, 430), (1000, 430))
    s.pin(1004, 430, "POR_N", "r")
    s.text(1000, 515, "outputs swing 0 … VOUT", "end", "ar")
    return s


# ------------------------------------------------------------------ bandgap
def sheet_bandgap():
    s = Sheet(1220, 665, "Bandgap: PMOS mirror MP0 to MP4 and MPN (8/4), MP0 diode-connected through the op-amp "
                         "output stage MN3; diodes D1 (1x), D2 (8x) with R1, R2 and D3 on the output branch; "
                         "PMOS-input op-amp MA1, MA2 with mirror MN1, MN2 and CCB; start-up MS1 to MS3 gated by VBG; "
                         "NMOS bias diode MNB")
    top, gy, bus = 40, 560, 150
    s.line((60, top), (1180, top))
    s.text(60, top - 8, "VIN", "start", "rail")
    cols = (("MP0", 295), ("MP1", 445), ("MP2", 595), ("MP3", 745), ("MP4", 960), ("MPN", 1150))
    for nm, t in cols:
        m = s.mos(t - 15, 100, "p", nm, "8/4")
        s.line(m["u"], (t, top))
        s.line(m["g"], (t - 45, bus))
        s.dot(t - 45, bus)
    s.line((175, bus), (1105, bus))
    s.text(300, bus - 6, "pg", "start", "sz")
    # MP0 drain = pg, MN3 below
    s.line((295, 130), (295, 200)); s.dot(295, bus)
    m3 = s.mos(280, 230, "n", "MN3", "8/4")
    s.line(m3["d"], (295, gy)); s.gnd(295, gy)
    s.line(m3["g"], (220, 230), (220, gy + 25), (1090, gy + 25), (1090, 300), (1060, 300))
    # start-up
    s.text(40, 225, "start-up (VBG-gated)", "start", "lb")
    s.vdd(115, 255, "VIN")
    ms3 = s.mos(100, 300, "p", "MS3", "1/40")
    s.line((115, 255), ms3["u"])
    s.line(ms3["g"], (60, 300)); s.text(56, 304, "en_inb", "end", "sz")
    ms2 = s.mos(100, 420, "n", "MS2", "2/2")
    s.line(ms3["d"], ms2["u"])
    s.line(ms2["d"], (115, gy)); s.gnd(115, gy)
    s.line(ms2["g"], (60, 420)); s.text(56, 424, "VBG", "end", "lb")
    s.dot(115, 360); s.text(108, 352, "sg", "end", "sz")
    ms1 = s.mos(160, 360, "n", "MS1", "2/2")
    s.line((115, 360), ms1["g"])
    s.line(ms1["u"], (175, bus))
    s.dot(175, bus)
    s.line(ms1["d"], (175, 470), (445, 470))
    # node a / D1
    s.line((445, 130), (445, 500)); s.dot(445, 400); s.dot(445, 470)
    s.text(452, 396, "a", "start", "sz")
    diode(s, 445, 500, 545, "D1", "dp3 1×")
    s.line((445, 545), (445, gy)); s.gnd(445, gy)
    # node b / R1 / D2
    s.line((595, 130), (595, 260)); s.dot(595, 260); s.text(602, 256, "b", "start", "sz")
    s.res(595, 260, 360, "R1", "10.8 kΩ")
    diode(s, 595, 420, 490, "D2", "dp3 8×")
    s.line((595, 360), (595, 420)); s.line((595, 490), (595, gy)); s.gnd(595, gy)
    # VBG / R2 / D3
    s.line((745, 130), (745, 290), acc=True); s.dot(745, 290)
    s.line((745, 290), (790, 290), acc=True)
    s.pin(794, 290, "VBG 1.187 V", "r", acc=True)
    s.res(745, 290, 400, "R2", "95.5 kΩ", "l")
    diode(s, 745, 420, 490, "D3", "dp3 1×", "l")
    s.line((745, 400), (745, 420)); s.line((745, 490), (745, gy)); s.gnd(745, gy)
    # op-amp
    s.line((960, 130), (960, 180)); s.dot(960, 180); s.text(966, 176, "tlb", "start", "sz")
    ma1 = s.mos(905, 230, "p", "MA1", "20/2")
    ma2 = s.mos(1015, 230, "p", "MA2", "20/2", mirror=True)
    s.line((920, 200), (920, 180), (1000, 180), (1000, 200))
    s.line(ma1["g"], (860, 230)); s.text(855, 234, "a", "end", "lb")
    s.line(ma2["g"], (1060, 230)); s.text(1065, 234, "b", "start", "lb")
    mn1 = s.mos(935, 380, "n", "MN1", "4/4", mirror=True)
    mn2 = s.mos(985, 380, "n", "MN2", "4/4")
    s.text(870, 376, "MN1", "end", "dev") if False else None
    s.line(ma1["d"], mn1["u"]); s.line(ma2["d"], mn2["u"])
    s.line(mn1["g"], mn2["g"])
    s.line((920, 335), (960, 335), (960, 380)); s.dot(920, 335); s.dot(960, 380)
    s.line(mn1["d"], (920, gy)); s.gnd(920, gy)
    s.line(mn2["d"], (1000, gy)); s.gnd(1000, gy)
    s.dot(1000, 300); s.text(1006, 296, "o1", "start", "sz")
    s.line((1000, 300), (1060, 300))
    s.dot(1060, 300)
    s.cap(1060, 300, 380, "CCB", "2 pF")
    s.line((1060, 380), (1060, gy)); s.gnd(1060, gy)
    # NMOS bias
    s.line((1150, 130), (1150, 210)); s.dot(1150, 185)
    s.text(1157, 181, "nb", "start", "sz")
    mnb = s.mos(1135, 240, "n", "MNB", "4/4")
    s.line((1150, 185), (1105, 185), (1105, 240))
    s.line(mnb["d"], (1150, gy)); s.gnd(1150, gy)
    s.text(40, 612, "VBG = VBE(D3) + (R2 / R1) · Vt · ln 8;  the op-amp forces a = b;  o1 drives MN3, which sets "
           "the mirror current through the diode MP0 (pg).", "start", "ar")
    s.text(40, 630, "pg biases the comparators, gate buffer and delay sources; nb (MNB) the error-amplifier tail ME0.",
           "start", "ar")
    s.text(40, 648, "Disabled: MBG_OFF pulls pg to VIN, MBG_O1 grounds o1, MSO (1/0.35, gate en_inb) grounds sg.",
           "start", "ar")
    return s


# ------------------------------------------------------------------ regulator
def sheet_regulator():
    s = Sheet(1220, 640, "Regulator: soft-start filter RSS, CSS with discharge MSS; NMOS-input error amplifier ME1, ME2 "
                         "with tail ME0, PMOS mirror ME3, ME4 and the series REA, CEA network from eo to ed; PMOS source "
                         "follower MB1 with bias MB0 and pull-up MGD; pass device MPASS; current sense MSEN, RCS with "
                         "detector MCL whose mirror MCL1, MCL2 pulls eo up; divider RDA to RDC; discharge MDIS")
    top = 40
    s.line((20, top), (1190, top), acc=True)
    s.text(20, top - 8, "VIN", "start", "rail")
    # soft start
    s.pin(0, 330, "VBG", "tl")
    s.line((4, 330), (10, 330))
    s.hres(10, 90, 330, "RSS", "5 MΩ")
    s.line((90, 330), (250, 330)); s.dot(120, 330); s.dot(235, 330)
    s.text(180, 322, "vr", "middle", "sz")
    s.cap(120, 330, 400, "CSS", "10 pF", "l"); s.gnd(120, 400)
    mss = s.mos(220, 400, "n", "MSS", "1/0.35")
    s.line((235, 330), mss["u"]); s.line(mss["d"], (235, 440)); s.gnd(235, 440)
    s.line(mss["g"], (175, 400)); s.text(171, 418, "onb", "end", "sz")
    # error amplifier: mirror ME3 (diode, ed) / ME4 (eo)
    me3 = s.mos(355, 100, "p", "ME3", "8/2", mirror=True, lab="l")
    me4 = s.mos(545, 100, "p", "ME4", "8/2")
    s.line(me3["u"], (340, top)); s.line(me4["u"], (560, top))
    s.line(me3["g"], me4["g"])
    s.line((340, 145), (450, 145), (450, 100)); s.dot(340, 145); s.dot(450, 100)
    s.text(334, 160, "ed", "end", "sz")
    me1 = s.mos(325, 270, "n", "ME1", "20/1")
    me2 = s.mos(575, 270, "n", "ME2", "20/1", mirror=True)
    s.line(me3["d"], me1["u"]); s.line(me4["d"], me2["u"], acc=True)
    s.line(me1["d"], (340, 320), (560, 320), me2["d"]); s.dot(450, 320)
    s.text(456, 316, "te", "start", "sz")
    me0 = s.mos(435, 360, "n", "ME0", "8/4")
    s.line((450, 320), me0["u"]); s.line(me0["d"], (450, 420)); s.gnd(450, 420)
    s.line(me0["g"], (390, 360)); s.text(386, 364, "nb", "end", "sz")
    # REA + CEA between ed and eo
    s.dot(340, 195)
    s.hres(340, 440, 195, "REA", "2 MΩ")
    s.line((440, 195), (470, 195))
    s.line((470, 183), (470, 207)); s.line((478, 183), (478, 207))
    s.text(474, 177, "CEA", "middle", "dev"); s.text(474, 222, "50 pF", "middle", "sz")
    s.line((478, 195), (560, 195)); s.dot(560, 195)
    # inputs
    s.line(me1["g"], (280, 270), (280, 600))
    s.line((250, 330), (250, 560), (625, 560), (625, 270), me2["g"])
    s.text(631, 300, "vr", "start", "sz")
    s.text(274, 290, "fbe", "end", "sz")
    # eo and current-limit pull-up
    s.dot(560, 170)
    s.line((560, 170), (640, 170), (640, 250), (670, 250), acc=True)
    s.text(580, 164, "eo", "middle", "sz")
    s.arrow(600, 72, 600, 168)
    s.line((600, top), (600, 72))
    s.dot(600, 170)
    s.text(606, 132, "I_lim", "start", "ar"); s.text(606, 146, "(MCL2)", "start", "ar")
    # buffer
    mb0 = s.mos(700, 100, "p", "MB0", "32/4")
    s.line(mb0["u"], (715, top)); s.line(mb0["g"], (655, 100)); s.text(651, 104, "pg", "end", "sz")
    mb1 = s.mos(700, 250, "p", "MB1", "20/1")
    s.line(mb0["d"], mb1["u"])
    s.line(mb1["d"], (715, 310)); s.gnd(715, 310)
    s.dot(715, 170)
    mgd = s.mos(840, 100, "p", "MGD", "4/0.3")
    s.line(mgd["u"], (855, top)); s.line(mgd["g"], (795, 100)); s.text(791, 104, "on", "end", "sz")
    s.line(mgd["d"], (855, 170)); s.dot(855, 170)
    # pass device
    s.line((715, 170), (900, 170), acc=True)
    s.text(780, 162, "gp", "middle", "sz")
    mp = s.mos(930, 170, "p", "MPASS", "20/0.5 m=120")
    s.line(mp["u"], (945, top), acc=True)
    s.line(mp["d"], (945, 330), acc=True)
    s.dot(945, 330)
    s.line((945, 330), (1180, 330), acc=True)
    s.pin(1184, 330, "VOUT", "tl", acc=True)
    # current sense
    msen = s.mos(1040, 110, "p", "MSEN", "2/0.5")
    s.line(msen["u"], (1055, top)); s.line(msen["g"], (995, 110)); s.text(991, 114, "gp", "end", "sz")
    s.line(msen["d"], (1055, 160)); s.dot(1055, 160); s.text(1048, 168, "cs", "end", "sz")
    s.res(1055, 160, 230, "RCS", "12 kΩ"); s.gnd(1055, 230)
    mcl = s.mos(1130, 200, "n", "MCL", "4/1")
    s.line((1055, 160), (1100, 160), (1100, 200), mcl["g"]) if False else None
    s.line((1055, 160), (1085, 160), (1085, 200), mcl["g"]) if False else None
    s.line(mcl["d"], (1145, 250)); s.gnd(1145, 250)
    s.line(mcl["u"], (1145, 150)); s.text(1152, 154, "cl", "start", "sz")
    s.line((1055, 160), (1090, 160), (1090, 200), (1100, 200))
    s.text(1190, 300, "cl → MCL1 : MCL2 (1 : 2) → eo", "end", "ar")
    # divider
    xd = 1120
    s.line((xd, 330), (xd, 345)); s.dot(xd, 330)
    s.res(xd, 345, 395, "RDA", "42.20 kΩ")
    s.dot(xd, 395); s.text(xd - 10, 399, "pf", "end", "sz")
    s.res(xd, 395, 430, "RDD", "5.96 kΩ")
    s.dot(xd, 430); s.text(xd - 10, 434, "pr", "end", "sz")
    s.res(xd, 430, 480, "RDB", "13.18 kΩ")
    s.dot(xd, 480); s.text(xd - 10, 476, "fb", "end", "sz")
    s.res(xd, 480, 560, "RDC", "118.66 kΩ"); s.gnd(xd, 560)
    s.line((xd, 480), (1040, 480), (1040, 600), (280, 600))
    # discharge
    mdis = s.mos(995, 420, "n", "MDIS", "6/1")
    s.line((1010, 330), mdis["u"]); s.dot(1010, 330)
    s.line(mdis["d"], (1010, 460)); s.gnd(1010, 460)
    s.line(mdis["g"], (950, 420)); s.text(946, 424, "onb", "end", "sz")
    s.text(290, 625, "fb → fbe through vinj (0 V source: loop-gain injection point in simulation);  "
           "MEO (1/0.3, gate on) pulls eo to VIN while off", "start", "ar")
    s.text(1190, 625, "pf / pr → power-good comparator", "end", "ar")
    return s


# ------------------------------------------------------------------ supervisor
def sheet_supervisor():
    s = Sheet(1120, 650, "Supervisor: LDO_EN input MI with long-PMOS load and two inverters; bandgap-running detector MG; "
                         "UVLO divider RUA, RUB, RUC with tap switches and comparator XCU; on = en_in and uv_ok; "
                         "power-good taps pr, pf with comparator XCP; 10 us and 100 us delays (current-charged "
                         "capacitor, Schmitt trigger) and the VOUT-supplied output inverters")
    # enable input
    s.text(20, 14, "Enable input (threshold ≈ 0.8 V)", "start", "bx")
    s.pin(20, 120, "LDO_EN", "l")
    mi = s.mos(90, 120, "n", "MI", "4/1")
    s.line((24, 120), mi["g"])
    s.line(mi["d"], (105, 170)); s.gnd(105, 170)
    mil = s.mos(90, 60, "p", "MIL", "1/40")
    s.line(mil["d"], mi["u"]); s.dot(105, 90)
    s.line(mil["g"], (50, 60), (50, 80)); s.gnd(50, 80)
    s.line(mil["u"], (105, 25)); s.text(112, 36, "VIN", "start", "rail")
    s.line((105, 90), (150, 90)); s.text(140, 84, "eib", "end", "sz")
    o = s.inv(150, 90); s.line(o, (210, 90))
    o2 = s.inv(210, 90); s.line(o2, (270, 90))
    s.text(205, 80, "en_in", "middle", "sz"); s.text(275, 94, "en_inb", "start", "sz")
    # bg_ok
    s.text(400, 14, "Bandgap running (VBG > ≈ 0.85 V)", "start", "bx")
    mg = s.mos(470, 120, "n", "MG", "2/2")
    s.line(mg["g"], (420, 120)); s.text(415, 124, "VBG", "end", "lb")
    s.line(mg["d"], (485, 170)); s.gnd(485, 170)
    mgl = s.mos(470, 60, "p", "MGL", "1/40")
    s.line(mgl["d"], mg["u"]); s.dot(485, 90)
    s.line(mgl["u"], (485, 25)); s.text(492, 36, "VIN", "start", "rail"); s.text(440, 64, "en_inb", "end", "sz")
    s.line((485, 90), (540, 90))
    o = s.inv(540, 90); s.line(o, (600, 90)); s.text(604, 94, "bg_ok", "start", "sz")
    # UVLO
    s.text(20, 230, "UVLO: VIN × 0.4395 (rising) / 0.4746 (falling) vs VBG", "start", "bx")
    s.line((60, 250), (60, 260)); s.text(60, 246, "VIN", "middle", "rail")
    s.res(60, 260, 330, "RUA", "788 kΩ", "l")
    s.dot(60, 330); s.text(68, 324, "utf", "start", "sz")
    s.res(60, 330, 380, "RUB", "52.7 kΩ", "l")
    s.dot(60, 380); s.text(68, 374, "utr", "start", "sz")
    s.res(60, 380, 460, "RUC", "659.3 kΩ", "l")
    mus = s.mos(45, 500, "n", "MUS", "2/0.35")
    s.line((60, 460), mus["u"]); s.line(mus["d"], (60, 545)); s.gnd(60, 545)
    s.text(10, 504, "en_in", "end", "sz")
    s.line((60, 330), (130, 330)); s.tg(130, 330, "SU2 (uv_ok)"); s.line((160, 330), (190, 330), (190, 355))
    s.line((60, 380), (130, 380)); s.tg(130, 380, "SU1 (uv_okb)"); s.line((160, 380), (190, 380), (190, 355))
    s.dot(190, 355); s.text(196, 350, "utap", "start", "sz")
    ip, im, oo = comp(s, 230, 367, "XCU")
    s.line((190, 355), ip)
    s.line(im, (215, 379), (215, 420)); s.text(215, 436, "VBG", "middle", "lb")
    a1, b1, on1 = nand(s, 320, 375, "XNU")
    s.line(oo, (300, 367), a1)
    s.line(b1, (305, 383), (305, 410)); s.text(305, 424, "bg_ok", "middle", "sz")
    o = s.inv(on1[0] + 4, 375); s.line(on1, (on1[0] + 4, 375))
    s.line(o, (450, 375)); s.dot(430, 375); s.text(430, 367, "uv_ok", "middle", "sz")
    a2, b2, on2 = nand(s, 470, 400, "XNE")
    s.line((450, 375), (460, 375), (460, 392), a2)
    s.line(b2, (455, 408), (455, 440)); s.text(455, 454, "en_in", "middle", "sz")
    s.line(on2, (540, 400)); s.dot(540, 400); s.text(544, 392, "onb", "start", "sz")
    o = s.inv(560, 400); s.line((540, 400), (560, 400)); s.line(o, (620, 400)); s.text(624, 404, "on", "start", "sz")
    s.text(20, 590, "Tap switches: uv_ok = 1 → utf (2.5 V falling), 0 → utr (2.7 V rising)", "start", "ar")
    s.text(20, 608, "Comparators: PMOS-input OTA + NMOS common-source stage + inverter; disabled (en_in = 0):",
           "start", "ar")
    s.text(20, 624, "co → GND, o2 → VDD, out = 0.  MGO (1/0.3, gate en_in) pulls bgb to VIN: bg_ok = 0.",
           "start", "ar")
    # power good
    s.text(680, 230, "Power good: VOUT taps vs VBG, 1.62 V ↑ / 1.55 V ↓", "start", "bx")
    s.text(700, 300, "pr (×0.7325)", "end", "sz"); s.line((700, 296), (720, 296)); s.tg(720, 296, "SP1")
    s.text(700, 340, "pf (×0.7656)", "end", "sz"); s.line((700, 336), (720, 336)); s.tg(720, 336, "SP2")
    s.line((750, 296), (770, 296), (770, 336), (750, 336)); s.dot(770, 316); s.text(776, 312, "ptap", "start", "sz")
    ip, im, oo = comp(s, 800, 328, "XCP")
    s.line((770, 316), ip)
    s.line(im, (785, 340), (785, 380)); s.text(785, 396, "VBG", "middle", "lb")
    a3, b3, on3 = nand(s, 880, 336, "XNP")
    s.line(oo, (870, 328), a3)
    s.line(b3, (870, 344), (870, 370)); s.text(870, 384, "on", "middle", "sz")
    o = s.inv(on3[0] + 4, 336); s.line(on3, (on3[0] + 4, 336))
    s.line(o, (1040, 336)); s.text(1044, 340, "pg_raw", "start", "sz")
    # delays
    s.text(680, 425, "Delays: ≈ 0.3 µA (MPD1 / MRD1 1/8) charges", "start", "ar")
    s.text(680, 441, "CPGD 1.6 pF → 10 µs, CPRD 16 pF → 100 µs", "start", "ar")
    for i, (cn, cv, mn, sn, nin, nout, pin) in enumerate((("CPGD", "1.6 pF", "MPD1", "XSPG", "pg_rawb", "pg_d", "PWR_GOOD"),
                                                           ("CPRD", "16 pF", "MRD1", "XSPR", "pg_db", "por_d", "POR_N"))):
        x = 690 + i * 220
        y = 520
        mp = s.mos(x, 470, "p", mn, "1/8")
        s.line(mp["u"], (x + 15, 455)); s.text(x - 34, 474, "pg", "end", "sz")
        s.line(mp["d"], (x + 15, y)); s.dot(x + 15, y)
        s.cap(x + 15, y, 580, cn, cv, "l"); s.gnd(x + 15, 580)
        s.text(x + 15, 600, f"discharge: {nin}", "middle", "sz")
        s.line((x + 15, y), (x + 60, y))
        so = schmitt(s, x + 60, y)
        s.line(so, (x + 110, y))
        o = s.inv(x + 110, y, None, None, 22)
        s.line(o, (x + 160, y))
        s.text(x + 160, y - 22, pin, "end", "pin")
    s.text(1100, 625, "Output inverters XOPG / XOPR are supplied by VOUT", "end", "ar")
    return s


def main():
    sheets = {"block": sheet_block, "bandgap": sheet_bandgap, "regulator": sheet_regulator,
              "supervisor": sheet_supervisor}
    for name, fn in sheets.items():
        s = fn()
        svg = s.svg().replace("<defs>", STYLE + "<defs>", 1)
        svg = svg.replace('class="sch"', 'class="sch" style="background:#fff;color:#17221f"', 1)
        p = os.path.join(HERE, f"ldo_{name}.svg")
        open(p, "w").write(svg)
        if shutil.which("rsvg-convert"):
            subprocess.run(["rsvg-convert", "-z", "2", "-b", "white", "-o", p[:-4] + ".png", p], check=True)
        print("wrote", p)


if __name__ == "__main__":
    main()
