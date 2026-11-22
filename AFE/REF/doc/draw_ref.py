#!/usr/bin/env python3
"""draw_ref.py - SVG schematic sheets of afe_ref_tr.sp

    python3 AFE/REF/doc/draw_ref.py
        -> AFE/REF/doc/ref_*.svg (+ .png with rsvg-convert)

Same symbols and conventions as AFE/spice/doc/draw_cdr.py and the LDO sheets
(AFE/LDO analog part/doc/draw_ldo.py, imported): 3-terminal MOS (PMOS with
gate bubble, source on top), zig-zag resistor, two-plate capacitor, rail
bar, ground; one accent colour for the reference path.  All MOS are xh018
ne3i / pe3i (3.3 V isolated), W / L in um; m = multiplier.

Sheets
  ref_block.svg      block diagram
  ref_bandgap.svg    bandgap core, tapped PTAT string, trim mux, filter
  ref_amps.svg       gain stage A1, output buffers, OTA cell
  ref_current.svg    RBIAS loop, cascode mirror, TX_I_5U; enable / trim inputs
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "AFE", "spice", "doc"))
sys.path.insert(0, os.path.join(ROOT, "AFE", "LDO analog part", "doc"))
from draw_cdr import Sheet, STYLE  # noqa: E402
from draw_ldo import diode, amp  # noqa: E402


# ------------------------------------------------------------------ block
def sheet_block():
    s = Sheet(1140, 510, "Block diagram of afe_ref_tr: dp3 bandgap with a 16-tap PTAT string, 4-bit trim mux and "
                         "ripple filter, gain stage A1 (x1.0113) to vrt = 1.200 V, two unity buffers for TX_VREF "
                         "and RX_VREF, and the current loop A_I with source follower MNF that holds the external "
                         "RBIAS at vrt; a 20:1 cascode mirror gives TX_I_5U; enable and trim inputs")
    s.pin(10, 50, "VDD33", "tl", acc=True)
    s.line((14, 50), (1040, 50), acc=True)
    s.pin(10, 485, "GND", "r")
    s.box(40, 110, 170, 80, "Bandgap", "dp3, 5 µA PTAT units", acc=True)
    s.line((125, 50), (125, 110))
    s.box(250, 110, 150, 80, "PTAT string", "16 taps, 0.6 % / step")
    s.line((210, 150), (250, 150), acc=True)
    s.box(440, 110, 120, 80, "Trim mux", "16:1 NMOS tree")
    s.line((400, 150), (440, 150), acc=True)
    s.text(420, 142, "t0…t15", "middle", "sz")
    s.line((560, 150), (600, 150), acc=True)
    s.dot(600, 150)
    s.text(600, 140, "vtap", "middle", "sz")
    s.cap(600, 150, 220, "CFL", "6 pF", "l"); s.gnd(600, 220)
    ip, im, o = amp(s, 640, 150 + 14, "A1", "×1.0113", acc=True)
    s.line((600, 150), ip, acc=True)
    s.line(o, (760, 164), acc=True)
    s.dot(760, 164); s.text(760, 154, "vrt 1.200 V", "middle", "sz")
    s.line(im, (630, 178), (630, 250), (740, 250), (740, 164))
    s.text(690, 244, "RF / RG", "middle", "ar")
    # buffers
    s.line((760, 164), (800, 164), (800, 100), (840, 100), acc=True)
    s.box(840, 75, 120, 50, "B_TX", "unity, 30 µA")
    s.line((960, 100), (1040, 100), acc=True)
    s.pin(1044, 100, "TX_VREF", "r", acc=True)
    s.line((800, 164), (800, 210), (840, 210), acc=True)
    s.box(840, 185, 120, 50, "B_RX", "unity, 30 µA")
    s.line((960, 210), (1040, 210), acc=True)
    s.pin(1044, 210, "RX_VREF", "r", acc=True)
    # current
    s.line((760, 164), (760, 270), (555, 270), (555, 300))
    s.box(470, 300, 170, 60, "A_I + MNF", "V(RBIAS) = vrt")
    s.line((555, 360), (555, 385))
    s.pin(555, 389, "RBIAS 12 kΩ", "r")
    s.box(700, 300, 160, 60, "Cascode mirror", "20 : 1")
    s.line((640, 330), (700, 330))
    s.text(670, 322, "I", "middle", "sz")
    s.vdd(780, 290, "VDD33")
    s.line((780, 290), (780, 300))
    s.line((860, 330), (1040, 330), acc=True)
    s.pin(1044, 330, "TX_I_5U", "r", acc=True)
    s.text(950, 322, "VREF / RBIAS / 20 = 5 µA", "middle", "ar")
    # inputs
    s.box(110, 290, 170, 70, "Enable + trim inputs", "threshold ≈ 0.8 V")
    s.pin(14, 310, "BIAS_EN", "tl"); s.line((18, 310), (110, 310))
    s.pin(14, 345, "TRIM[3:0]", "tl"); s.line((18, 345), (110, 345))
    s.line((280, 325), (300, 325), (300, 190), dash=True)
    s.line((300, 325), (500, 325), (500, 190), dash=True)
    s.text(306, 320, "en_in, tk / tnk", "start", "ar")
    s.line((195, 290), (195, 190), dash=True)
    s.text(40, 440, "BIAS_EN = 0: bandgap, amplifiers and mirror off (< 50 nA); TX_VREF = RX_VREF = 0 V, TX_I_5U = 0.",
           "start", "ar")
    s.text(40, 460, "TRIM 1000b = nominal; every code step adds 0.6 % (PTAT gain), range −4.8 … +4.2 %.",
           "start", "ar")
    return s


# ------------------------------------------------------------------ bandgap
def sheet_bandgap():
    s = Sheet(1240, 700, "Bandgap of afe_ref_tr: PMOS mirror MP0 to MP4 and MPN (8/4); PMOS-input op-amp MA1, MA2 "
                         "(40/4) with mirror MN1, MN2 (8/8), CCB and output device MN3; diodes D1 (1x), D2 (8x) with "
                         "R1; output branch MP3 into the PTAT string R2B plus fifteen 1.4325 kOhm segments to D3; "
                         "the 16:1 NMOS trim mux selects a tap as vtap, filtered by CFL; start-up MS1 to MS3")
    top, gy, bus = 40, 600, 150
    s.line((60, top), (1200, top))
    s.text(60, top - 8, "VDD33", "start", "rail")
    cols = (("MP0", 295), ("MP1", 445), ("MP2", 595), ("MP3", 745), ("MP4", 990), ("MPN", 1170))
    for nm, t in cols:
        m = s.mos(t - 15, 100, "p", nm, "8/4")
        s.line(m["u"], (t, top))
        s.line(m["g"], (t - 45, bus))
        s.dot(t - 45, bus)
    s.line((175, bus), (1125, bus))
    s.text(300, bus - 6, "pg", "start", "sz")
    s.line((295, 130), (295, 200)); s.dot(295, bus)
    m3 = s.mos(280, 230, "n", "MN3", "8/4")
    s.line(m3["d"], (295, gy)); s.gnd(295, gy)
    s.line(m3["g"], (220, 230), (220, gy + 25), (1110, gy + 25), (1110, 330), (1090, 330))
    # start-up
    s.text(30, 225, "start-up", "start", "lb")
    s.vdd(115, 255, "VDD33")
    ms3 = s.mos(100, 300, "p", "MS3", "1/10")
    s.line((115, 255), ms3["u"])
    s.line(ms3["g"], (60, 300)); s.text(56, 304, "en_inb", "end", "sz")
    ms2 = s.mos(100, 430, "n", "MS2", "2/2")
    s.line(ms3["d"], ms2["u"])
    s.line(ms2["d"], (115, gy)); s.gnd(115, gy)
    s.line(ms2["g"], (60, 430)); s.text(56, 434, "t15", "end", "lb")
    s.dot(115, 360); s.text(108, 352, "sg", "end", "sz")
    ms1 = s.mos(160, 360, "n", "MS1", "1/4")
    s.line((115, 360), ms1["g"])
    s.line(ms1["u"], (175, bus))
    s.dot(175, bus)
    s.line(ms1["d"], (175, 470), (445, 470))
    # a / D1
    s.line((445, 130), (445, 520)); s.dot(445, 400); s.dot(445, 470)
    s.text(452, 396, "a", "start", "sz")
    diode(s, 445, 520, 565, "D1", "dp3 1×")
    s.line((445, 565), (445, gy)); s.gnd(445, gy)
    # b / R1 / D2
    s.line((595, 130), (595, 260)); s.dot(595, 260); s.text(602, 256, "b", "start", "sz")
    s.res(595, 260, 360, "R1", "10.8 kΩ")
    diode(s, 595, 440, 510, "D2", "dp3 8×")
    s.line((595, 360), (595, 440)); s.line((595, 510), (595, gy)); s.gnd(595, gy)
    # PTAT string
    s.line((745, 130), (745, 200), acc=True)
    s.dot(745, 200); s.text(752, 196, "t15", "start", "sz")
    s.res(745, 200, 228, "", "")
    s.dot(745, 228); s.text(752, 232, "t14", "start", "sz")
    s.line((745, 228), (745, 262), dash=True)
    s.text(737, 250, "15 × RS", "end", "ar")
    s.text(737, 266, "1.4325 kΩ", "end", "ar")
    s.dot(745, 280); s.text(752, 284, "t8", "start", "sz")
    s.line((745, 262), (745, 320), dash=True)
    s.dot(745, 320); s.text(752, 324, "t0", "start", "sz")
    s.res(745, 320, 420, "R2B", "84.04 kΩ", "l")
    diode(s, 745, 450, 520, "D3", "dp3 1×", "l")
    s.line((745, 420), (745, 450)); s.line((745, 520), (745, gy)); s.gnd(745, gy)
    # mux
    s.box(830, 230, 100, 110, "Trim mux", "16:1 NMOS")
    for y0, y in ((228, 245), (280, 285), (300, 305), (320, 325)):
        s.line((745, y0), (800, y0), (800, y), (830, y))
    s.line((880, 340), (880, 370), dash=True)
    s.text(880, 386, "TRIM[3:0] → tk / tnk", "middle", "sz")
    s.line((930, 285), (960, 285), acc=True)
    s.dot(960, 285)
    s.cap(960, 285, 360, "CFL", "6 pF"); s.gnd(960, 360)
    s.line((960, 285), (960, 210), (1010, 210), acc=True)
    s.pin(1014, 210, "vtap → A1", "r", acc=True)
    # op-amp
    s.line((990, 130), (990, 180)); s.dot(990, 180); s.text(996, 176, "tlb", "start", "sz")
    ma1 = s.mos(965, 460, "p", "MA1", "40/4")
    ma2 = s.mos(1075, 460, "p", "MA2", "40/4", mirror=True)
    s.line((990, 180), (1020, 180), (1020, 410), (980, 410), (980, 430))
    s.line((1020, 410), (1060, 410), (1060, 430))
    s.line(ma1["g"], (920, 460)); s.text(915, 464, "a", "end", "lb")
    s.line(ma2["g"], (1120, 460)); s.text(1125, 464, "b", "start", "lb")
    mn1 = s.mos(995, 545, "n", "MN1", "8/8", mirror=True)
    mn2 = s.mos(1045, 545, "n", "MN2", "8/8")
    s.line(ma1["d"], mn1["u"]); s.line(ma2["d"], mn2["u"])
    s.line(mn1["g"], mn2["g"])
    s.line((980, 505), (1020, 505), (1020, 545)); s.dot(980, 505); s.dot(1020, 545)
    s.line(mn1["d"], (980, gy)); s.gnd(980, gy)
    s.line(mn2["d"], (1060, gy)); s.gnd(1060, gy)
    s.dot(1060, 500); s.text(1066, 496, "o1", "start", "sz")
    s.line((1060, 500), (1090, 500), (1090, 330))
    s.dot(1090, 400)
    s.line((1090, 400), (1150, 400))
    s.cap(1150, 400, 470, "CCB", "4 pF"); s.gnd(1150, 470)
    # NMOS bias
    s.line((1170, 130), (1170, 200)); s.dot(1170, 185)
    s.text(1177, 181, "nb", "start", "sz")
    mnb = s.mos(1155, 240, "n", "MNB", "4/4")
    s.line((1170, 185), (1125, 185), (1125, 240))
    s.line(mnb["d"], (1170, 300)); s.gnd(1170, 300)
    s.text(40, 650, "VBG(tap k) = VBE(D3) + I_PTAT · (84.04 kΩ + k · 1.4325 kΩ), I_PTAT = Vt · ln 8 / R1 ≈ 5 µA;  "
           "code 1000b = 95.5 kΩ = 1.1866 V (tm, 27 °C).", "start", "ar")
    s.text(40, 668, "The tap changes only the PTAT term, so trimming VBG to its target also corrects the "
           "temperature coefficient of a VBE spread.  nb (MNB, 5 µA) biases every NMOS tail and sink.", "start", "ar")
    s.text(40, 686, "Disabled: MBG_OFF pulls pg to VDD33, MBG_O1 grounds o1, MSO grounds sg, MNBO grounds nb.",
           "start", "ar")
    return s


# ------------------------------------------------------------------ amplifiers
def sheet_amps():
    s = Sheet(1200, 560, "Gain stage A1: PMOS input pair MGA_A, MGA_B (20/2) with tail MGA_T (2 x 8/4 from pg), NMOS "
                         "mirror MGA_NA, MGA_NB (4/4), NMOS common-source output MGA_O (8/1) with PMOS load MGA_S "
                         "(4 x 8/4), Miller RZ, CC; feedback divider RF, RG.  OTA cell ref_ota used for B_TX, B_RX "
                         "and A_I: NMOS pair (10/2), tail from nb, PMOS mirror (8/4)")
    top, gy = 40, 470
    s.line((40, top), (640, top))
    s.text(40, top - 8, "VDD33", "start", "rail")
    mt = s.mos(215, 100, "p", "MGA_T", "8/4 ×2")
    s.line(mt["u"], (230, top))
    s.line(mt["g"], (160, 100)); s.text(155, 104, "pg", "end", "lb")
    s.line(mt["d"], (230, 150)); s.dot(230, 150); s.text(236, 146, "ta", "start", "sz")
    ma = s.mos(145, 200, "p", "MGA_A", "20/2")
    mb = s.mos(315, 200, "p", "MGA_B", "20/2", mirror=True)
    s.line((160, 170), (160, 150), (300, 150), (300, 170))
    s.line(ma["g"], (80, 200)); s.text(75, 204, "fbn", "end", "lb")
    s.line(mb["g"], (365, 200)); s.text(365, 186, "vtap", "middle", "lb")
    na = s.mos(175, 320, "n", "MGA_NA", "4/4", mirror=True)
    nb = s.mos(285, 320, "n", "MGA_NB", "4/4")
    s.line(ma["d"], na["u"]); s.line(mb["d"], nb["u"])
    s.line(na["g"], nb["g"])
    s.line((160, 270), (220, 270), (220, 320)); s.dot(160, 270); s.dot(220, 320)
    s.line(na["d"], (160, gy)); s.gnd(160, gy)
    s.line(nb["d"], (300, gy)); s.gnd(300, gy)
    s.dot(300, 260); s.text(306, 256, "o1a", "start", "sz")
    # second stage
    ms = s.mos(455, 100, "p", "MGA_S", "8/4 ×4")
    s.line(ms["u"], (470, top))
    s.line(ms["g"], (410, 100)); s.text(405, 104, "pg", "end", "lb")
    mo = s.mos(455, 330, "n", "MGA_O", "8/1")
    s.line(ms["d"], mo["u"])
    s.line(mo["d"], (470, gy)); s.gnd(470, gy)
    s.line((300, 260), (380, 260), (380, 330), mo["g"])
    s.dot(380, 260)
    s.hres(380, 420, 230, "", "")
    s.text(400, 214, "RZ 40k", "middle", "sz")
    s.line((380, 260), (380, 230))
    s.line((420, 230), (430, 230))
    s.line((430, 220), (430, 240)); s.line((438, 220), (438, 240))
    s.text(434, 256, "CC 1.5p", "middle", "sz")
    s.line((438, 230), (470, 230)); s.dot(470, 230)
    s.dot(470, 200); s.line((470, 200), (580, 200), acc=True)
    s.pin(584, 200, "vrt 1.200 V", "r", acc=True)
    s.line((530, 200), (530, 250)); s.dot(530, 200)
    s.res(530, 250, 320, "RF", "2.266 kΩ")
    s.dot(530, 320); s.text(524, 316, "fbn", "end", "sz")
    s.res(530, 320, 420, "RG", "200 kΩ")
    s.line((530, 420), (530, gy)); s.gnd(530, gy)
    s.text(40, 510, "vrt = vtap · (1 + RF / RG) = 1.01133 · vtap;  first-stage gain ≈ 50 dB, DC loop gain 84 dB.  "
           "NMOS output stage: VDD33 reaches vrt only through current sources (PSRR).", "start", "ar")
    s.text(40, 528, "Disabled: MGA_OFF grounds o1a, MGA_VO grounds vrt.", "start", "ar")
    # OTA cell
    x0 = 760
    s.line((x0, top), (1160, top))
    s.text(x0, top - 8, "vdd", "start", "rail")
    s.text(x0 + 280, 90, "ref_ota", "start", "lb")
    s.text(x0 + 280, 108, "(out rises with inp)", "start", "sz")
    pa = s.mos(x0 + 105, 140, "p", "MPA", "8/4", mirror=True)
    pb = s.mos(x0 + 235, 140, "p", "MPB", "8/4")
    s.line(pa["u"], (x0 + 90, top)); s.line(pb["u"], (x0 + 250, top))
    s.line(pa["g"], pb["g"])
    s.line((x0 + 90, 200), (x0 + 170, 200), (x0 + 170, 140)); s.dot(x0 + 90, 200); s.dot(x0 + 170, 140)
    xa = s.mos(x0 + 75, 260, "n", "MA", "10/2")
    xb = s.mos(x0 + 265, 260, "n", "MB", "10/2", mirror=True)
    s.line(pa["d"], xa["u"]); s.line(pb["d"], xb["u"])
    s.line(xa["g"], (x0 + 20, 260)); s.text(x0 + 15, 264, "inp", "end", "lb")
    s.line(xb["g"], (x0 + 320, 260)); s.text(x0 + 325, 264, "inn", "start", "lb")
    s.dot(x0 + 250, 210); s.line((x0 + 250, 210), (x0 + 330, 210))
    s.pin(x0 + 334, 210, "out", "r")
    s.line(xa["d"], (x0 + 90, 310), (x0 + 250, 310), xb["d"])
    s.dot(x0 + 170, 310); s.text(x0 + 176, 306, "tl", "start", "sz")
    mt2 = s.mos(x0 + 155, 360, "n", "MT", "8/4 ×mt")
    s.line((x0 + 170, 310), mt2["u"])
    s.line(mt2["d"], (x0 + 170, 400)); s.gnd(x0 + 170, 400)
    s.line(mt2["g"], (x0 + 100, 360)); s.text(x0 + 95, 364, "nb", "end", "lb")
    s.text(x0, 432, "B_TX, B_RX: inp = vrt, inn = out (unity follower), mt = 3", "start", "ar")
    s.text(x0, 448, "(30 µA); output pole is dominant: stable with 0…100 pF;", "start", "ar")
    s.text(x0, 464, "2 pF on chip at TX_VREF / RX_VREF.  A_I: inp = vrt,", "start", "ar")
    s.text(x0, 480, "inn = RBIAS, mt = 1 (10 µA).", "start", "ar")
    return s


# ------------------------------------------------------------------ current
def sheet_current():
    s = Sheet(1200, 600, "Reference current: OTA A_I drives the NMOS source follower MNF (20/1), whose source is the "
                         "RBIAS pin; the drain current flows through the wide-swing cascode mirror MPI, MCI (20 units) "
                         "with diode node gi; MPO, MCO (1 unit) source TX_I_5U; cascode bias MCB, MCS.  Input cells: "
                         "BIAS_EN with MI and the weak load MIL, trim inputs ref_lin gated by en_in")
    top, gy = 40, 520
    s.line((40, top), (720, top))
    s.text(40, top - 8, "VDD33", "start", "rail")
    mpi = s.mos(325, 100, "p", "MPI", "4/2 ×20")
    mpo = s.mos(545, 100, "p", "MPO", "4/2 ×1")
    s.line(mpi["u"], (340, top)); s.line(mpo["u"], (560, top))
    s.line(mpi["g"], (280, 100), (280, 70), (520, 70), (520, 100), mpo["g"])
    s.dot(400, 70); s.text(405, 66, "gi", "start", "sz")
    mci = s.mos(325, 200, "p", "MCI", "4/1 ×20")
    mco = s.mos(545, 200, "p", "MCO", "4/1 ×1")
    s.line(mpi["d"], mci["u"]); s.line(mpo["d"], mco["u"])
    s.line(mci["g"], (280, 200), (280, 160), (520, 160), (520, 200), mco["g"])
    s.dot(440, 160); s.text(445, 156, "vcas", "start", "sz")
    s.line(mci["d"], (340, 260)); s.dot(340, 260)
    s.line((340, 260), (400, 260), (400, 70))
    s.text(346, 278, "gi (diode)", "start", "sz")
    s.line(mco["d"], (560, 330), acc=True)
    s.pin(560, 334, "TX_I_5U  5 µA", "b", acc=True)
    mnf = s.mos(325, 330, "n", "MNF", "20/1")
    s.line((340, 260), mnf["u"])
    s.line(mnf["d"], (340, 420)); s.dot(340, 420)
    s.line((340, 420), (340, 470))
    s.pin(340, 474, "RBIAS", "b")
    s.text(352, 478, "12.0 kΩ 1 % to GND", "start", "ar")
    ip, im, o = amp(s, 110, 330 + 14, "A_I", "ref_ota, 10 µA")
    s.line(ip, (80, 330)); s.text(75, 334, "vrt", "end", "lb")
    s.line(im, (90, 358), (90, 420), (340, 420))
    s.line(o, (230, 344), (230, 330), mnf["g"])
    s.dot(260, 330); s.text(262, 322, "gf", "start", "sz")
    s.cap(260, 330, 400, "CGF", "5 pF", "l"); s.gnd(260, 400)
    # cascode bias
    mcb = s.mos(645, 120, "p", "MCB", "1/3")
    s.line(mcb["u"], (660, top))
    s.line(mcb["d"], (660, 200)); s.dot(660, 170)
    s.line(mcb["g"], (615, 120), (615, 170), (660, 170))
    s.line((660, 170), (660, 160), (520, 160))
    mcs = s.mos(645, 260, "n", "MCS", "4/4")
    s.line((660, 200), mcs["u"])
    s.line(mcs["d"], (660, 330)); s.gnd(660, 330)
    s.line(mcs["g"], (600, 260)); s.text(595, 264, "nb", "end", "lb")
    s.text(40, 545, "I(RBIAS) = vrt / RBIAS = 100 µA;  TX_I_5U = I / 20.  MNF keeps the RBIAS pin low-impedance (1 / gm): "
           "stable up to ≥ 100 pF on the pin.", "start", "ar")
    s.text(40, 563, "Disabled: MAI_O grounds gf, MGI_O and MCB_O pull gi and vcas to VDD33.", "start", "ar")
    # input cells
    x0 = 790
    s.line((x0, top), (1170, top))
    s.text(x0, top - 8, "VDD33", "start", "rail")
    s.text(x0, 76, "BIAS_EN input", "start", "lb")
    ml = s.mos(x0 + 65, 120, "p", "MIL", "1/40")
    s.line(ml["u"], (x0 + 80, top))
    s.line(ml["g"], (x0 + 20, 120)); s.text(x0 + 15, 124, "GND", "end", "sz")
    mi = s.mos(x0 + 65, 230, "n", "MI", "4/1")
    s.line(ml["d"], mi["u"]); s.dot(x0 + 80, 175)
    s.line(mi["d"], (x0 + 80, 300)); s.gnd(x0 + 80, 300)
    s.line(mi["g"], (x0 + 20, 230))
    s.pin(x0 + 16, 230, "BIAS_EN", "l")
    s.line((x0 + 80, 175), (x0 + 130, 175))
    s.inv(x0 + 130, 175)
    s.line((x0 + 168, 175), (x0 + 200, 175))
    s.inv(x0 + 200, 175)
    s.line((x0 + 238, 175), (x0 + 260, 175))
    s.text(x0 + 184, 166, "en_in", "middle", "sz")
    s.text(x0 + 264, 179, "en_inb", "start", "sz")
    s.text(x0, 340, "threshold ≈ 0.8 V (MI against ≈ 1 µA):", "start", "ar")
    s.text(x0, 358, "1.8 V or 3.3 V logic.", "start", "ar")
    s.text(x0, 392, "ref_lin (TRIM0…3): same stage with", "start", "lb")
    s.text(x0, 410, "MIL 1/80 and a series NMOS gated by en_in", "start", "ar")
    s.text(x0, 428, "(no current while disabled) → tk, tnk", "start", "ar")
    s.text(x0, 446, "for the 2:1 NMOS cells of the trim mux.", "start", "ar")
    return s


def main():
    sheets = {"block": sheet_block, "bandgap": sheet_bandgap, "amps": sheet_amps, "current": sheet_current}
    for name, fn in sheets.items():
        s = fn()
        svg = s.svg().replace("<defs>", STYLE + "<defs>", 1)
        svg = svg.replace('class="sch"', 'class="sch" style="background:#fff;color:#17221f"', 1)
        p = os.path.join(HERE, f"ref_{name}.svg")
        open(p, "w").write(svg)
        if shutil.which("rsvg-convert"):
            subprocess.run(["rsvg-convert", "-z", "2", "-b", "white", "-o", p[:-4] + ".png", p], check=True)
        print("wrote", p)


if __name__ == "__main__":
    main()
