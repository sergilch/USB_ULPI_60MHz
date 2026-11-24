#!/usr/bin/env python3
"""gen_schematic.py - EasyEDA Std schematic of the discrete USB 2.0 receiver board

    python3 gen_schematic.py   -> usb_rx_board_sch.json  (EasyEDA Std project source, 4 sheets)
                                  netlist.csv            (ref, pin, pin name, net, sheet)
                                  ../bom/rx_board_bom.csv, ../bom/rx_board_bom_jlcpcb.csv

Symbols and footprints: JLCEDA/EasyEDA Official Library (https://lceda.cn/,
https://easyeda.com), cached in lib/<LCSC>.json from the EasyEDA API
(api/products/<LCSC>/components).  The copyright of the library data belongs
to JLCEDA/EasyEDA; every sheet carries this source note.  Every part is placed
unrotated; each connected pin gets a short wire stub and a net label, so the
connectivity is exactly the NETS table below (net-label style, one sheet per
function).  Same engine as AFE/Discrete/Transmitter/easyeda/gen_schematic.py.

Open in EasyEDA Std (desktop or web): new schematic > Design > "File Source"
(toolbar "<>" icon) > replace the text > "Create New Document", or File > Open >
EasyEDA Source File.  Passives share one 0603 symbol and footprint; value, MPN
and LCSC number are set per part (c_para).
"""
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "lib")
BOMDIR = os.path.join(HERE, "..", "bom")
SOURCE_NOTE = ("Symbols / footprints: JLCEDA/EasyEDA Official Library - "
               "https://lceda.cn/ - https://easyeda.com")

# ---------------------------------------------------------------------------
# parts
# ---------------------------------------------------------------------------
R0603, C0603 = "C25804", "C108079"          # symbols used for all 0603 R / C
RES = {  # value -> (MPN, LCSC)   UNI-ROYAL 0603 1 %
    "22": ("0603WAF220JT5E", "C23345"), "220": ("0603WAF2200T5E", "C22962"),
    "200": ("0603WAF2000T5E", "C8218"), "2k": ("0603WAF2001T5E", "C22975"),
    "499": ("0603WAF4990T5E", "C23065"), "1k": ("0603WAF1001T5E", "C21190"),
    "150": ("0603WAF1500T5E", "C22808"), "1.5k": ("0603WAF1501T5E", "C22843"),
    "680": ("0603WAF6800T5E", "C23228"), "18k": ("0603WAF1802T5E", "C25810"),
    "10k": ("0603WAF1002T5E", "C25804"), "150k": ("0603WAF1503T5E", "C22807"),
    "40.2": ("0603WAF402JT5E", "C23047"), "47k": ("0603WAF4702T5E", "C25819"),
    "100k": ("0603WAF1003T5E", "C25803"), "33": ("0603WAF330JT5E", "C23140"),
    "100": ("0603WAF1000T5E", "C22775"),
}
CAP = {  # value -> (MPN, LCSC, manufacturer)
    "100n": ("CC0603KRX7R7BB104", "C108079", "YAGEO"),
    "10u": ("CL10A106KP8NNNC", "C19702", "Samsung"),
    "6.8p": ("0603CG6R8C500NT", "C1679", "FH"),
    "1n": ("0603CG102J500NT", "C1636", "FH"),
}

PARTS = {}
DNP = set()


def ic(ref, sheet, sym, mpn, lcsc, mfr, value=None, note=""):
    PARTS[ref] = dict(sheet=sheet, sym=sym, value=value or mpn, mpn=mpn, lcsc=lcsc, mfr=mfr, note=note)


def r(ref, sheet, val, note=""):
    mpn, lc = RES[val]
    PARTS[ref] = dict(sheet=sheet, sym=R0603, value=val if val[-1] in "kM" else val + "R",
                      mpn=mpn, lcsc=lc, mfr="UNI-ROYAL", note=note)


def c(ref, sheet, val, note=""):
    mpn, lc, mf = CAP[val]
    PARTS[ref] = dict(sheet=sheet, sym=C0603, value=val + "F", mpn=mpn, lcsc=lc, mfr=mf, note=note)


S1, S2, S3, S4 = "1_FMC_POWER_IO", "2_LINE_TAP_HS_RX", "3_SQUELCH_DISCONNECT", "4_THRESHOLD_DAC"

# ---- sheet 1: FMC, power, level translation, output gates, IPMI EEPROM ----
ic("J1", S1, "C5366873", "ASP-134604-01", "", "Samtec", "FMC LPC mezzanine",
   note="order from Samtec / Mouser; LCSC symbol C5366873")
ic("FB1", S1, "C80165", "BLM18PG221SN1D", "C80165", "Murata", "220R@100MHz")
ic("FB2", S1, "C80165", "BLM18PG221SN1D", "C80165", "Murata", "220R@100MHz")
c("C1", S1, "10u"); c("C2", S1, "10u"); c("C3", S1, "100n"); c("C4", S1, "10u")
c("C5", S1, "100n"); c("C6", S1, "10u"); c("C7", S1, "100n"); c("C8", S1, "100n")
ic("U1", S1, "C6203", "AT24C02C-SSHM-T", "C6203", "Microchip", note="FRU EEPROM (VITA 57.1 IPMI)")
ic("U2", S1, "C27643", "SN74LVC8T245PWR", "C27643", "TI", note="VADJ -> 3.3 V slow controls")
c("C9", S1, "100n"); c("C10", S1, "100n")
r("R4", S1, "100k", note="HS_TERM_EN off while VADJ is down")
r("R5", S1, "100k", note="DAC deselected while VADJ is down")
ic("U3", S1, "C7843", "SN74LVC1T45DBVR", "C7843", "TI", note="VBUS_DET 3.3 V -> VADJ")
c("C11", S1, "100n"); c("C12", S1, "100n")
r("R1", S1, "47k"); r("R2", S1, "100k"); c("C15", S1, "1n")
ic("U4", S1, "C2877887", "SN74LVC1G00DBVRG4", "C2877887", "TI", note="SQUELCH_A = NAND(SQ_ACT, RX_EN), at VADJ")
c("C13", S1, "100n")
r("R6", S1, "33", note="series termination")
ic("U5", S1, "C7666", "SN74LVC1G08DBVR", "C7666", "TI", note="DISC_A = AND(DC_ACT, RX_EN), at VADJ")
c("C14", S1, "100n")
r("R7", S1, "33", note="series termination")
r("R8", S1, "100k", note="RX_EN low while the FPGA is unconfigured")
ic("D1", S1, "C12624", "KT-0603G", "C12624", "KENTO", "green LED")
r("R3", S1, "1k")

# ---- sheet 2: USB-B -> USB-A through line, ESD, termination switch, followers, HS RX ----
ic("J2", S2, "C46392", "USB-B-Female-90", "C46392", "JST-like (LCSC)", note="host side (upstream)")
ic("J3", S2, "C168707", "USB-A-F-90-BLK", "C168707", "LCSC", note="device side (downstream)")
ic("U6", S2, "C7519", "USBLC6-2SC6", "C7519", "ST")
ic("U8", S2, "C11355", "FSUSB42MUX", "C11355", "onsemi", note="HS termination switch (term mode)")
r("R13", S2, "40.2", note="HS termination D+ (+ Ron 4.5R = 45R)")
r("R14", S2, "40.2", note="HS termination D-")
c("C18", S2, "100n")
ic("Q1", S2, "C9994", "BFT92,215", "", "NXP", "BFT92",
   note="D+ follower, SOT-23 (Mouser/DigiKey; LCSC C9994 is the SOT-323 BFT92W)")
ic("Q2", S2, "C9994", "BFT92,215", "", "NXP", "BFT92", note="D- follower, as Q1")
r("R9", S2, "22", note="base stopper, at the line")
r("R10", S2, "22", note="base stopper, at the line")
r("R11", S2, "220", note="emitter pull-up, ~10 mA")
r("R12", S2, "220", note="emitter pull-up, ~10 mA")
ic("U7", S2, "C529293", "SN65LVDS100DGKR", "C529293", "TI", note="HS receiver, LVDS out (RX_OUT)")
c("C16", S2, "100n"); c("C17", S2, "100n")
r("R43", S2, "100", note="DNP: RX_OUT termination at the board, only if the FPGA bank cannot use DIFF_TERM")
DNP.add("R43")
c("C19", S2, "100n"); c("C20", S2, "100n"); c("C21", S2, "10u")

# ---- sheet 3: squelch and disconnect detectors ----
for k, u in enumerate(("U9", "U10", "U11", "U12", "U13", "U14")):
    ic(u, S3, "C5213955", "TLV3603DCKR", "C5213955", "TI",
       note=["window SQ+ (vd > +V_SQ/10), LE/HYS open: 3 mV",
             "window SQ- (vd < -V_SQ/10), LE/HYS open: 3 mV",
             "window DC+ (vd > +V_DISC/2), LE/HYS open: 3 mV",
             "window DC- (vd < -V_DISC/2), LE/HYS open: 3 mV",
             "squelch envelope comparator, 30 mV hysteresis",
             "disconnect envelope comparator, 30 mV hysteresis"][k])
for ref in ("R15", "R17", "R19", "R21"):
    r(ref, S3, "200", note="squelch offset network Ra")
for ref in ("R16", "R18", "R20", "R22"):
    r(ref, S3, "2k", note="squelch offset network Rb")
for ref in ("R23", "R25", "R27", "R29"):
    r(ref, S3, "499", note="disconnect offset network Ra")
for ref in ("R24", "R26", "R28", "R30"):
    r(ref, S3, "1k", note="disconnect offset network Rb")
r("R31", S3, "150", note="R_att"); r("R32", S3, "150", note="R_att")
ic("D2", S3, "C194653", "BAS70-05,215", "C194653", "Nexperia", note="squelch diode-OR")
c("C22", S3, "6.8p", note="C_env squelch (C0G)")
r("R33", S3, "1.5k", note="R_dec squelch")
r("R34", S3, "150k", note="R_HYST: 30 mV")
r("R35", S3, "150", note="R_att"); r("R36", S3, "150", note="R_att")
ic("D3", S3, "C194653", "BAS70-05,215", "C194653", "Nexperia", note="disconnect diode-OR")
c("C23", S3, "6.8p", note="C_env disconnect (C0G)")
r("R37", S3, "680", note="R_dec disconnect")
r("R38", S3, "150k", note="R_HYST: 30 mV")
r("R39", S3, "18k"); r("R40", S3, "10k"); c("C24", S3, "100n", note="V_ETH = 1.18 V")
for ref in ("C25", "C26", "C27", "C28", "C29", "C30"):
    c(ref, S3, "100n")
ic("J5", S3, "C124375", "Header 1x2 2.54mm", "C124375", "Ckmtw", note="test: SQ_ACT")
ic("J6", S3, "C124375", "Header 1x2 2.54mm", "C124375", "Ckmtw", note="test: DC_ACT")

# ---- sheet 4: thresholds ----
ic("U15", S4, "C16040", "MCP4822-E/SN", "C16040", "Microchip", note="A = V_SQ, B = V_DISC, 1 mV / LSB")
r("R41", S4, "100"); c("C31", S4, "100n", note="V_SQ filter / HF return")
r("R42", S4, "100"); c("C32", S4, "100n", note="V_DISC filter / HF return")
c("C33", S4, "100n")
ic("J7", S4, "C124375", "Header 1x2 2.54mm", "C124375", "Ckmtw", note="test: V_SQ / V_DISC")

# ---------------------------------------------------------------------------
# connectivity: ref -> {pin number: net}
# ---------------------------------------------------------------------------
NETS = {}


def con(ref, **pins):
    NETS.setdefault(ref, {}).update({k.lstrip("_"): v for k, v in pins.items()})


def two(ref, a, b):
    NETS[ref] = {"1": a, "2": b}


# J1 FMC LPC (VITA 57.1 rows C, D, G, H)
fmc = {
    "H7": "RX_OUT_P_F", "H8": "RX_OUT_N_F", "G9": "SQUELCH_A_F", "G10": "DISC_A_F",
    "H10": "RX_EN_F", "H11": "HS_TERM_EN_F", "D11": "DAC_CS_N_F", "D12": "DAC_SCK_F",
    "C10": "DAC_SDI_F", "C11": "VBUS_DET_F",
    "C39": "P3V3_FMC", "D36": "P3V3_FMC", "D38": "P3V3_FMC", "D40": "P3V3_FMC",
    "G39": "VADJ", "H40": "VADJ", "D32": "P3V3AUX",
    "H2": "GND",                                   # PRSNT_M2C_L
    "C30": "FMC_SCL", "C31": "FMC_SDA", "C34": "FMC_GA0", "D35": "FMC_GA1",
    "D30": "FMC_TDI_TDO", "D31": "FMC_TDI_TDO",    # JTAG chain pass-through
}
for p in ("C1 C4 C5 C8 C9 C12 C13 C16 C17 C20 C21 C24 C25 C28 C29 C32 C33 C36 C38 C40 "
          "D2 D3 D6 D7 D10 D13 D16 D19 D22 D25 D28 D37 D39 "
          "G1 G4 G5 G8 G11 G14 G17 G20 G23 G26 G29 G32 G35 G38 G40 "
          "H3 H6 H9 H12 H15 H18 H21 H24 H27 H30 H33 H36 H39").split():
    fmc[p] = "GND"
NETS["J1"] = {re.sub(r"^([A-Z])(\d)$", r"\g<1>0\2", k): v for k, v in fmc.items()}   # symbol: "H07"

two("FB1", "P3V3_FMC", "+3V3"); two("FB2", "P3V3_FMC", "+3V3A")
two("C1", "P3V3_FMC", "GND"); two("C2", "+3V3", "GND"); two("C3", "+3V3", "GND")
two("C4", "+3V3A", "GND"); two("C5", "+3V3A", "GND"); two("C6", "VADJ", "GND")
two("C7", "VADJ", "GND"); two("C8", "P3V3AUX", "GND")
con("U1", _1="FMC_GA0", _2="FMC_GA1", _3="GND", _4="GND", _5="FMC_SDA", _6="FMC_SCL",
    _7="GND", _8="P3V3AUX")
con("U2", _1="VADJ", _2="VADJ", _3="HS_TERM_EN_F", _4="DAC_CS_N_F", _5="DAC_SCK_F",
    _6="DAC_SDI_F", _7="GND", _8="GND", _9="GND", _10="GND", _11="GND", _12="GND", _13="GND",
    _21="HS_TERM_EN", _20="DAC_CS_N", _19="DAC_SCK", _18="DAC_SDI",
    _22="GND", _23="+3V3", _24="+3V3")
two("C9", "VADJ", "GND"); two("C10", "+3V3", "GND")
two("R4", "HS_TERM_EN", "GND"); two("R5", "+3V3", "DAC_CS_N")
con("U3", _1="VADJ", _2="GND", _3="VBUS_DET_F", _4="VBUS_DIV", _5="GND", _6="+3V3")
two("C11", "VADJ", "GND"); two("C12", "+3V3", "GND")
two("R1", "VBUS", "VBUS_DIV"); two("R2", "VBUS_DIV", "GND"); two("C15", "VBUS_DIV", "GND")
con("U4", _1="SQ_ACT", _2="RX_EN_F", _3="GND", _4="SQ_OUT", _5="VADJ")
two("C13", "VADJ", "GND"); two("R6", "SQ_OUT", "SQUELCH_A_F")
con("U5", _1="DC_ACT", _2="RX_EN_F", _3="GND", _4="DC_OUT", _5="VADJ")
two("C14", "VADJ", "GND"); two("R7", "DC_OUT", "DISC_A_F")
two("R8", "RX_EN_F", "GND")
two("R3", "+3V3", "LED_A"); con("D1", _1="GND", _2="LED_A")

# sheet 2
con("J2", _1="VBUS", _2="DM", _3="DP", _4="GND", _5="GND", _6="GND")
con("J3", _1="VBUS", _2="DM", _3="DP", _4="GND", _5="GND")
con("U6", _1="DP", _6="DP", _3="DM", _4="DM", _2="GND", _5="VBUS")
con("U8", _1="+3V3", _2="HS_TERM_EN", _3="DP", _4="DM", _5="GND",
    _8="TERM_M", _9="TERM_P", _10="GND")
two("R13", "TERM_P", "GND"); two("R14", "TERM_M", "GND"); two("C18", "+3V3", "GND")
two("R9", "DP", "BP"); two("R10", "DM", "BM")
con("Q1", _1="BP", _2="EP", _3="GND")          # BFT92: 1 B, 2 E, 3 C
con("Q2", _1="BM", _2="EM", _3="GND")
two("R11", "+3V3A", "EP"); two("R12", "+3V3A", "EM")
con("U7", _2="EP", _3="EM", _5="GND", _6="RX_OUT_N_F", _7="RX_OUT_P_F", _8="+3V3A")
two("R43", "RX_OUT_P_F", "RX_OUT_N_F")
two("C16", "+3V3A", "GND"); two("C17", "+3V3A", "GND")
two("C19", "+3V3A", "GND"); two("C20", "+3V3A", "GND"); two("C21", "+3V3A", "GND")

# sheet 3: window comparators (IN+ 3, IN- 4, OUT 1, VEE 2, VCC 6; LE/HYS 5 open)
WIN = [("U9", "SQA", "EP", "EM", "V_SQ", "SQ_A", ("R15", "R16", "R17", "R18")),
       ("U10", "SQB", "EM", "EP", "V_SQ", "SQ_B", ("R19", "R20", "R21", "R22")),
       ("U11", "DCA", "EP", "EM", "V_DISC", "DC_A", ("R23", "R24", "R25", "R26")),
       ("U12", "DCB", "EM", "EP", "V_DISC", "DC_B", ("R27", "R28", "R29", "R30"))]
for u, nm, pos, neg, vref, out, (ra1, rb1, ra2, rb2) in WIN:
    two(ra1, pos, nm + "_P"); two(rb1, nm + "_P", "GND")
    two(ra2, neg, nm + "_N"); two(rb2, nm + "_N", vref)
    con(u, _1=out, _2="GND", _3=nm + "_P", _4=nm + "_N", _6="+3V3A")
two("R31", "SQ_A", "SQ_A1"); two("R32", "SQ_B", "SQ_B1")
con("D2", _1="SQ_A1", _2="SQ_B1", _3="ENV_SQ")
two("C22", "ENV_SQ", "GND"); two("R33", "ENV_SQ", "GND")
con("U13", _1="SQ_ACT", _2="GND", _3="ENV_SQ", _4="V_ETH", _5="HYS_SQ", _6="+3V3A")
two("R34", "HYS_SQ", "GND")
two("R35", "DC_A", "DC_A1"); two("R36", "DC_B", "DC_B1")
con("D3", _1="DC_A1", _2="DC_B1", _3="ENV_DC")
two("C23", "ENV_DC", "GND"); two("R37", "ENV_DC", "GND")
con("U14", _1="DC_ACT", _2="GND", _3="ENV_DC", _4="V_ETH", _5="HYS_DC", _6="+3V3A")
two("R38", "HYS_DC", "GND")
two("R39", "+3V3A", "V_ETH"); two("R40", "V_ETH", "GND"); two("C24", "V_ETH", "GND")
for ref in ("C25", "C26", "C27", "C28", "C29", "C30"):
    two(ref, "+3V3A", "GND")
con("J5", _1="SQ_ACT", _2="GND"); con("J6", _1="DC_ACT", _2="GND")

# sheet 4
con("U15", _1="+3V3A", _2="DAC_CS_N", _3="DAC_SCK", _4="DAC_SDI", _5="GND", _6="V_DISC_D",
    _7="GND", _8="V_SQ_D")
two("R41", "V_SQ_D", "V_SQ"); two("C31", "V_SQ", "GND")
two("R42", "V_DISC_D", "V_DISC"); two("C32", "V_DISC", "GND")
two("C33", "+3V3A", "GND")
con("J7", _1="V_SQ", _2="V_DISC")


# ---------------------------------------------------------------------------
# EasyEDA Std shape handling
# ---------------------------------------------------------------------------
_id = [0]
_cache = {}


def gid():
    _id[0] += 1
    return "grx%05d" % _id[0]


def load(lcsc):
    if lcsc not in _cache:
        with open(os.path.join(LIB, lcsc + ".json")) as f:
            _cache[lcsc] = json.load(f)["result"]
    return _cache[lcsc]


NARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "A": 7, "C": 6, "Q": 4, "S": 4, "T": 2}


def tpath(d, dx, dy):
    """translate an SVG path: absolute commands moved, relative ones unchanged"""
    toks = re.findall(r"[A-Za-z]|-?\d*\.?\d+(?:e-?\d+)?", d)
    out, i, cmd = [], 0, None
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            out.append(t)
            i += 1
            continue
        n = NARGS.get(cmd)
        if n is None:
            out.append(t)
            i += 1
            continue
        v = [float(x) for x in toks[i:i + n]]
        if cmd == "H":
            v[0] += dx
        elif cmd == "V":
            v[0] += dy
        elif cmd == "A":
            v[5] += dx
            v[6] += dy
        else:
            for k in range(0, n, 2):
                v[k] += dx
                v[k + 1] += dy
        out += ["%g" % x for x in v]
        i += n
    return " ".join(out)


def fx(v, d):
    return "%g" % (float(v) + d) if v not in ("", None) else v


def tshape(s, dx, dy):
    kind = s.split("~", 1)[0]
    if kind == "P":
        seg = s.split("^^")
        f = seg[0].split("~"); f[4] = fx(f[4], dx); f[5] = fx(f[5], dy); f[7] = gid()
        seg[0] = "~".join(f)
        f = seg[1].split("~"); f[0] = fx(f[0], dx); f[1] = fx(f[1], dy); seg[1] = "~".join(f)
        f = seg[2].split("~"); f[0] = tpath(f[0], dx, dy); seg[2] = "~".join(f)
        for k in (3, 4, 5):
            f = seg[k].split("~"); f[1] = fx(f[1], dx); f[2] = fx(f[2], dy); seg[k] = "~".join(f)
        if len(seg) > 6:
            f = seg[6].split("~"); f[1] = tpath(f[1], dx, dy); seg[6] = "~".join(f)
        return "^^".join(seg)
    f = s.split("~")
    if kind in ("PL", "PG"):
        p = [float(x) for x in f[1].split()]
        f[1] = " ".join("%g" % (v + (dx if k % 2 == 0 else dy)) for k, v in enumerate(p))
        f[6] = gid()
    elif kind == "R":
        f[1] = fx(f[1], dx); f[2] = fx(f[2], dy); f[11] = gid()
    elif kind == "E":
        f[1] = fx(f[1], dx); f[2] = fx(f[2], dy); f[9] = gid()
    elif kind in ("A", "PT"):
        f[1] = tpath(f[1], dx, dy); f[7] = gid()
    else:
        raise ValueError("unhandled shape " + kind)
    return "~".join(f)


def sym_info(lcsc):
    """pins {num: (name, x, y, outward dx, dy)} and body bbox, library coordinates"""
    r = load(lcsc)
    pins, xs, ys = {}, [], []
    for s in r["dataStr"]["shape"]:
        if s.startswith("P~"):
            seg = s.split("^^")
            f = seg[0].split("~")
            num, x, y = f[3], float(f[4]), float(f[5])
            m = re.match(r"M\s*-?[\d.]+[\s,]+-?[\d.]+\s*([hv])\s*(-?[\d.]+)", seg[2].split("~")[0])
            body = float(m.group(2))
            o = (-1 if body > 0 else 1, 0) if m.group(1) == "h" else (0, -1 if body > 0 else 1)
            pins[num] = (seg[3].split("~")[4], x, y, o[0], o[1])
            xs.append(x); ys.append(y)
        elif s.startswith(("PL~", "PG~")):
            p = [float(v) for v in s.split("~")[1].split()]
            xs += p[0::2]; ys += p[1::2]
        elif s.startswith("R~"):
            f = s.split("~")
            xs += [float(f[1]), float(f[1]) + float(f[5])]
            ys += [float(f[2]), float(f[2]) + float(f[6])]
    return r, pins, (min(xs), min(ys), max(xs), max(ys))


def place(ref, X, Y):
    """LIB shape of part ref with its library origin at (X, Y); absolute pin data"""
    p = PARTS[ref]
    r, pins, bb = sym_info(p["sym"])
    h = r["dataStr"]["head"]
    dx, dy = X - float(h["x"]), Y - float(h["y"])
    cp = dict(h["c_para"])
    pre = re.sub(r"\?$", "", cp.pop("pre", "U?"))
    cp.pop("name", None)
    for k in ("JLCPCB Part Class", "Contributor", "spiceSymbolName"):
        cp.pop(k, None)
    cp.update({"Manufacturer Part": p["mpn"], "Manufacturer": p["mfr"],
               "Supplier": "LCSC" if p["lcsc"] else "Mouser/Samtec",
               "Supplier Part": p["lcsc"], "Value": p["value"], "spicePre": pre[:1]})
    if p["note"]:
        cp["Note"] = p["note"]
    if ref in DNP:
        cp["DNP"] = "yes"
    para = "`".join("%s`%s" % (k, str(v).replace("`", "'").replace("~", "-")) for k, v in cp.items())
    pkg = r.get("packageDetail") or {}
    head = "LIB~%g~%g~%s~~0~%s~%s~%s~0~~yes~yes~%s~%s~%s" % (
        X, Y, para, gid(), h.get("puuid", ""), r.get("uuid", ""), r.get("datastrid", ""),
        r.get("updateTime", ""), pkg.get("datastrid", ""))
    x0, y0 = bb[0] + dx, bb[1] + dy
    sub = ["T~P~%g~%g~0~#000080~Arial~~~~~comment~%s~1~start~%s~0~" % (x0, y0 - 11, ref, gid()),
           "T~N~%g~%g~0~#000080~Arial~~~~~comment~%s~1~start~%s~0~" % (
               x0, y0 - 3, p["value"] + (" DNP" if ref in DNP else ""), gid())]
    sub += [tshape(s, dx, dy) for s in r["dataStr"]["shape"]]
    apins = {n: (nm, x + dx, y + dy, ox, oy) for n, (nm, x, y, ox, oy) in pins.items()}
    return head + "#@$" + "#@$".join(sub), apins


STUB = 10
CH = 4.4        # approx. net label character width (7pt)


def label_len(net):
    return STUB + 4 + CH * len(net)


def connect(apins, nets):
    out = []
    for num, net in nets.items():
        nm, x, y, ox, oy = apins[num]
        x2, y2 = x + ox * STUB, y + oy * STUB
        out.append("W~%g %g %g %g~#008800~1~0~none~%s~0" % (x, y, x2, y2, gid()))
        if oy == 0:
            anchor = "start" if ox > 0 else "end"
            rot, tx, ty = 0, x2 + 2 * ox, y2 - 2
        else:
            anchor = "start" if oy < 0 else "end"
            rot, tx, ty = 90 if oy < 0 else 90, x2 - 2, y2 + 2 * oy
        out.append("N~%g~%g~%d~#0000FF~%s~%s~%s~%g~%g~Times New Roman~7pt~0" % (
            x2, y2, rot, net, gid(), anchor, tx, ty))
    return out


def extent(ref):
    """bbox relative to the library origin, including stubs, labels and texts"""
    r, pins, bb = sym_info(PARTS[ref]["sym"])
    h = r["dataStr"]["head"]
    hx, hy = float(h["x"]), float(h["y"])
    x0, y0, x1, y1 = bb[0] - hx, bb[1] - hy - 16, bb[2] - hx, bb[3] - hy
    x1 = max(x1, x0 + CH * len(PARTS[ref]["value"]) + 6)
    for num, net in NETS.get(ref, {}).items():
        _, x, y, ox, oy = pins[num]
        L = label_len(net)
        x, y = x - hx, y - hy
        x0, x1 = min(x0, x + min(ox, 0) * L), max(x1, x + max(ox, 0) * L)
        y0, y1 = min(y0, y + min(oy, 0) * L), max(y1, y + max(oy, 0) * L)
    return x0, y0, x1, y1


# ---------------------------------------------------------------------------
# sheets

TITLES = {S1: "FMC LPC, power, level translation, output gates (RX_EN), IPMI EEPROM",
          S2: "USB-B -> USB-A through line, ESD, HS termination switch, BFT92 taps, HS receiver (afe_hs_rx)",
          S3: "Squelch and disconnect detectors (afe_squelch)",
          S4: "Thresholds: MCP4822 V_SQ / V_DISC"}


def frame(w, h, title, no, n):
    s = ["R~0~%g~0~0~%g~%g~#880000~1~0~none~%s~0~" % (-h, w, h, gid()),
         "R~10~%g~0~0~%g~%g~#880000~1~0~none~%s~0~" % (-h + 10, w - 20, h - 20, gid())]
    bx, by = w - 520, -80
    s.append("R~%g~%g~0~0~510~70~#880000~1~0~none~%s~0~" % (bx, by, gid()))
    for x, y, t in [(bx + 8, by + 18, "USB 2.0 discrete receiver board (afe_receiver) - FMC LPC"),
                    (bx + 8, by + 36, "Sheet %d/%d: %s" % (no, n, title[:80])),
                    (bx + 8, by + 54, "Rev 0.1 - easyeda/gen_schematic.py - " + SOURCE_NOTE)]:
        s.append("T~L~%g~%g~0~#000080~Arial~~~~~comment~%s~1~start~%s~0~" % (x, y, t, gid()))
    return s


GROUPS = {
    S1: [("J1  FMC LPC (VITA 57.1) - LA pins, power, IPMI", ["J1"]),
         ("Power: FMC 3P3V -> +3V3 (digital) / +3V3A (taps, receivers)",
          ["FB1", "FB2", "C1", "C2", "C3", "C4", "C5", "C6", "C7"]),
         ("FRU EEPROM (IPMI)", ["U1", "C8"]),
         ("Slow controls VADJ -> 3.3 V", ["U2", "C9", "C10", "R4", "R5"]),
         ("SQUELCH_A / DISC_A at VADJ, gated by RX_EN", ["U4", "C13", "R6", "U5", "C14", "R7", "R8"]),
         ("VBUS detect 3.3 V -> VADJ", ["U3", "C11", "C12", "R1", "R2", "C15"]),
         ("Power LED", ["R3", "D1"])],
    S2: [("Through line: J2 (host, USB-B) -> J3 (device, USB-A), ESD", ["J2", "J3", "U6"]),
         ("HS termination switch: SEL = HS_TERM_EN (40.2R + Ron = 45R), HSD1 open",
          ["U8", "R13", "R14", "C18"]),
         ("Line taps: BFT92 emitter followers (22R base stoppers at the line, 220R pull-ups)",
          ["Q1", "Q2", "R9", "R10", "R11", "R12", "C19", "C20", "C21"]),
         ("HS receiver: SN65LVDS100 (25 mV hysteresis) -> RX_OUT (LVDS to the FPGA)",
          ["U7", "C16", "C17", "R43"])],
    S3: [("Squelch window: trip |vd| = V_SQ x 200 / 2k", ["U9", "R15", "R16", "R17", "R18",
                                                         "U10", "R19", "R20", "R21", "R22"]),
         ("Disconnect window: trip |vd| = V_DISC x 499 / 1k", ["U11", "R23", "R24", "R25", "R26",
                                                               "U12", "R27", "R28", "R29", "R30"]),
         ("Squelch envelope: diode-OR, 150R / 6.8p / 1.5k, comparator to V_ETH -> SQ_ACT",
          ["R31", "R32", "D2", "C22", "R33", "U13", "R34", "J5"]),
         ("Disconnect envelope: 150R / 6.8p / 680R -> DC_ACT", ["R35", "R36", "D3", "C23", "R37",
                                                                "U14", "R38", "J6"]),
         ("V_ETH = 1.18 V, decoupling", ["R39", "R40", "C24", "C25", "C26", "C27", "C28", "C29", "C30"])],
    S4: [("DAC: V_SQ (A), V_DISC (B), 1 mV / LSB", ["U15", "C33", "R41", "C31", "R42", "C32", "J7"])],
}

def flow(order, width, x=0.0, y=0.0, gap=25):
    """row-wise flow layout of parts; positions of the library origins, size"""
    x0f, cx, cy, row_h, pos, wmax = x, x, y, 0.0, [], 0.0
    for ref in order:
        ex0, ey0, ex1, ey1 = extent(ref)
        w, hgt = ex1 - ex0 + gap, ey1 - ey0 + 15
        if cx + w > x0f + width and cx > x0f:
            cx, cy, row_h = x0f, cy + row_h, 0.0
        pos.append((ref, cx - ex0, cy - ey0))
        cx += w
        wmax = max(wmax, cx - x0f)
        row_h = max(row_h, hgt)
    return pos, wmax, cy + row_h - y


def refkey(k):
    return re.sub(r"\d", "", k), int(re.sub(r"\D", "", k))


def sheet_doc(sheet, no, n):
    W = 1500
    groups = GROUPS[sheet]
    placed = [r for _, g in groups for r in g]
    missing = [k for k, v in PARTS.items() if v["sheet"] == sheet and k not in placed]
    if missing:
        groups = groups + [("other", missing)]
    shapes, parts = [], []
    gx, gy, row_h = 30.0, 30.0, 0.0
    for cap, refs in groups:
        gw = max(min(W - 60, 720), 300)
        pos, w, h = flow(refs, gw - 20)
        w, h = max(w, CH * len(cap) * 1.1 + 10, 120), h + 30
        if gx + w + 20 > W - 30 and gx > 30:
            gx, gy, row_h = 30.0, gy + row_h + 20, 0.0
        shapes.append(("box", gx, gy, w + 20, h, cap))
        parts += [(ref, gx + 10 + px, gy + 25 + py) for ref, px, py in pos]
        gx += w + 40
        row_h = max(row_h, h)
    H = max(gy + row_h + 120, 700)
    out = frame(W, H, TITLES[sheet], no, n)
    for _, x, y, w, h, cap in shapes:
        out.append("R~%g~%g~0~0~%g~%g~#808080~1~1~none~%s~0~" % (x, y - H, w, h, gid()))
        out.append("T~L~%g~%g~0~#404040~Arial~8pt~~bold~~comment~%s~1~start~%s~0~" % (
            x + 6, y - H + 14, cap, gid()))
    for ref, X, Y in parts:
        lib, apins = place(ref, X, Y - H)
        out.append(lib)
        out += connect(apins, NETS.get(ref, {}))
    return {"docType": "1", "title": sheet, "description": TITLES[sheet],
            "dataStr": {"head": {"docType": "1", "editorVersion": "6.5.61", "newgId": True,
                                 "c_para": {"Prefix Start": "1"}, "c_spiceCmd": None},
                        "canvas": "CA~%d~%d~#FFFFFF~yes~#CCCCCC~5~1000~1000~line~5~pixel~5~0~0"
                                  % (W + 200, H + 200),
                        "shape": out}}


def check():
    err, count = [], {}
    for ref, pins in NETS.items():
        if ref not in PARTS:
            err.append("%s: connections but no part" % ref)
            continue
        _, sp, _ = sym_info(PARTS[ref]["sym"])
        for num, net in pins.items():
            if num not in sp:
                err.append("%s: no pin %s" % (ref, num))
            count[net] = count.get(net, 0) + 1
    err += ["%s: no connections" % ref for ref in PARTS if ref not in NETS]
    return err, sorted(n for n, k in count.items() if k < 2), count


def write_bom():
    os.makedirs(BOMDIR, exist_ok=True)
    groups = {}
    for ref, p in PARTS.items():
        key = (p["mpn"], p["value"], p["lcsc"], ref in DNP)
        groups.setdefault(key, []).append(ref)
    rows = []
    for (mpn, val, lcsc, dnp), refs in groups.items():
        p = PARTS[refs[0]]
        fp = (load(p["sym"]).get("packageDetail") or {}).get("title", "")
        refs.sort(key=refkey)
        rows.append(dict(refs=refs, value=val, mpn=mpn, mfr=p["mfr"], lcsc=lcsc, footprint=fp,
                         dnp=dnp, note="; ".join(sorted({PARTS[k]["note"] for k in refs if PARTS[k]["note"]}))))
    rows.sort(key=lambda r: refkey(r["refs"][0]))
    with open(os.path.join(BOMDIR, "rx_board_bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Qty", "Value", "Manufacturer", "MPN", "LCSC", "Footprint", "Fitted", "Note"])
        for r in rows:
            w.writerow([",".join(r["refs"]), len(r["refs"]), r["value"], r["mfr"], r["mpn"],
                        r["lcsc"], r["footprint"], "DNP" if r["dnp"] else "yes", r["note"]])
    with open(os.path.join(BOMDIR, "rx_board_bom_jlcpcb.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for r in rows:
            if not r["dnp"]:
                w.writerow([r["value"], ",".join(r["refs"]), r["footprint"], r["lcsc"]])
    return rows


def main():
    err, single, count = check()
    for e in err:
        print("ERROR", e)
    if single:
        print("single-pin nets (inputs / test points):", " ".join(single))
    sheets = [S1, S2, S3, S4]
    proj = {"editorVersion": "6.5.61", "docType": "5", "title": "USB2 RX board",
            "description": "Discrete USB 2.0 receiver (afe_receiver) on FMC LPC",
            "colors": {}, "schematics": [sheet_doc(s, i + 1, len(sheets)) for i, s in enumerate(sheets)]}
    with open(os.path.join(HERE, "usb_rx_board_sch.json"), "w") as f:
        json.dump(proj, f, ensure_ascii=False, indent=1)
    with open(os.path.join(HERE, "netlist.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ref", "pin", "pin_name", "net", "sheet"])
        for ref in sorted(NETS, key=refkey):
            _, sp, _ = sym_info(PARTS[ref]["sym"])
            for num, net in sorted(NETS[ref].items()):
                w.writerow([ref, num, sp[num][0], net, PARTS[ref]["sheet"]])
    rows = write_bom()
    print("parts %d, BOM lines %d, nets %d, errors %d" % (len(PARTS), len(rows), len(count), len(err)))
    return 1 if err else 0


if __name__ == "__main__":
    raise SystemExit(main())
