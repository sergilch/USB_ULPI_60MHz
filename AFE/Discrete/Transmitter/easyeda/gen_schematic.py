#!/usr/bin/env python3
"""gen_schematic.py - EasyEDA Std schematic of the discrete USB 2.0 transmitter board

    python3 gen_schematic.py   -> usb_tx_board_sch.json  (EasyEDA Std project source, 4 sheets)
                                  netlist.csv            (ref, pin, pin name, net, sheet)
                                  ../bom/tx_board_bom.csv, ../bom/tx_board_bom_jlcpcb.csv

The schematic uses symbols of the JLCEDA/EasyEDA official library
(https://easyeda.com, https://lceda.cn), cached in lib/<LCSC>.json from the
EasyEDA API (api/products/<LCSC>/components).  Every part is placed unrotated;
each connected pin gets a short wire stub and a net label, so the connectivity
is exactly the NETS table below (net-label style, one sheet per function).

Open in EasyEDA Std (desktop or web): new schematic > Edit... "File Source"
(Design menu / toolbar "<>" icon) > replace the text > "Create New Document",
or File > Open > EasyEDA Source File.  Passives share one 0603 symbol and
footprint; value, MPN and LCSC number are set per part (c_para), so
"Convert Project to PCB" and the JLCPCB BOM export carry them.
"""
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "lib")
BOMDIR = os.path.join(HERE, "..", "bom")

# ---------------------------------------------------------------------------
# parts
# ---------------------------------------------------------------------------
R0603, C0603 = "C25804", "C108079"          # symbols used for all 0603 R / C
RES = {  # value -> (MPN, LCSC)   UNI-ROYAL 0603 1 %
    "15": ("0603WAF150JT5E", "C22810"), "1.69k": ("0603WAF1691T5E", "C22846"),
    "3.57k": ("0603WAF3571T5E", "C22998"), "237": ("0603WAF2370T5E", "C23012"),
    "255": ("0603WAF2550T5E", "C23355"), "549": ("0603WAF5490T5E", "C23079"),
    "82": ("0603WAF820JT5E", "C23255"), "130": ("0603WAF1300T5E", "C22796"),
    "40.2": ("0603WAF402JT5E", "C23047"), "33": ("0603WAF330JT5E", "C23140"),
    "68": ("0603WAF680JT5E", "C27592"), "1.5k": ("0603WAF1501T5E", "C22843"),
    "15k": ("0603WAF1502T5E", "C22809"), "5.1k": ("0603WAF5101T5E", "C23186"),
    "120k": ("0603WAF1203T5E", "C25808"), "45.3": ("0603WAF453JT5E", "C23176"),
    "10k": ("0603WAF1002T5E", "C25804"), "100k": ("0603WAF1003T5E", "C25803"),
    "1k": ("0603WAF1001T5E", "C21190"), "47k": ("0603WAF4702T5E", "C25819"),
    "100": ("0603WAF1000T5E", "C22775"), "18": ("0603WAF180JT5E", "C22830"),
    "470": ("0603WAF4700T5E", "C23179"), "1.2k": ("0603WAF1201T5E", "C22765"), "13k": ("0603WAF1302T5E", "C22797"),
    "82k": ("0603WAF8202T5E", "C23254"), "560": ("0603WAF5600T5E", "C23204"),
    "43": ("0603WAF430JT5E", "C23173"),
}
CAP = {  # value -> (MPN, LCSC, manufacturer)
    "100n": ("CC0603KRX7R7BB104", "C108079", "YAGEO"),
    "10u": ("CL10A106KP8NNNC", "C19702", "Samsung"),
    "10n": ("CL10B103KB8NNNC", "C1589", "Samsung"),
    "6.8p": ("0603CG6R8C500NT", "C1679", "FH"),
    "1n": ("0603CG102J500NT", "C1636", "FH"),
    "8.2p": ("0603CG8R2C500NT", "C1685", "FH"), "10p": ("0603CG100J500NT", "C91367", "FH"),
    "47p": ("0603CG470J500NT", "C94904", "FH"), "150p": ("0603CG151J500NT", "C1645", "FH"),
    "39p": ("0603CG390J500NT", "C1666", "FH"),
}

# FS/LS driver gate network (sheet 3); keep equal to VAL in sim/run_fsls.py
FSV = dict(RLS_N="560", RLS_P="1.2k", RFS_N="18", RFS_P="43", CM_N="150p", CM_P="8.2p",
           CK_P="10p", CKF_N="39p", CM2_P="47p", RM2_P="470")

PARTS = {}
DNP = {"R34", "R35", "R40", "R41"}


def ic(ref, sheet, sym, mpn, lcsc, mfr, value=None, note=""):
    PARTS[ref] = dict(sheet=sheet, sym=sym, value=value or mpn, mpn=mpn, lcsc=lcsc, mfr=mfr, note=note)


def r(ref, sheet, val, note=""):
    mpn, lc = RES[val]
    PARTS[ref] = dict(sheet=sheet, sym=R0603, value=val if val[-1] in "kM" else val + "R",
                      mpn=mpn, lcsc=lc, mfr="UNI-ROYAL", note=note)


def c(ref, sheet, val, note=""):
    mpn, lc, mf = CAP[val]
    PARTS[ref] = dict(sheet=sheet, sym=C0603, value=val + "F", mpn=mpn, lcsc=lc, mfr=mf, note=note)


S1, S2, S3, S4 = "1_FMC_POWER", "2_HS_DRIVER", "3_FSLS_TERM_USB", "4_BIAS_DAC"

# ---- sheet 1: FMC, power, level translators, IPMI EEPROM ----
ic("J1", S1, "C5366873", "ASP-134604-01", "", "Samtec", "FMC LPC mezzanine",
   note="order from Samtec / Mouser; LCSC symbol C5366873")
ic("FB1", S1, "C80165", "BLM18PG221SN1D", "C80165", "Murata", "220R@100MHz")
ic("FB2", S1, "C80165", "BLM18PG221SN1D", "C80165", "Murata", "220R@100MHz")
c("C1", S1, "10u"); c("C2", S1, "10u"); c("C3", S1, "100n"); c("C4", S1, "10u")
c("C5", S1, "100n"); c("C6", S1, "10u"); c("C7", S1, "100n"); c("C8", S1, "100n")
ic("U1", S1, "C6203", "AT24C02C-SSHM-T", "C6203", "Microchip", note="FRU EEPROM (VITA 57.1 IPMI)")
ic("U2", S1, "C27643", "SN74LVC8T245PWR", "C27643", "TI", note="VADJ -> 3.3 V slow controls")
c("C9", S1, "100n"); c("C10", S1, "100n")
ic("U3", S1, "C7843", "SN74LVC1T45DBVR", "C7843", "TI", note="TX_EN VADJ -> +3V3A")
c("C11", S1, "100n"); c("C12", S1, "100n")
ic("U4", S1, "C7843", "SN74LVC1T45DBVR", "C7843", "TI", note="VBUS_DET 3.3 V -> VADJ")
c("C13", S1, "100n"); c("C14", S1, "100n")
r("R1", S1, "47k"); r("R2", S1, "100k"); c("C15", S1, "1n")
ic("D1", S1, "C12624", "KT-0603G", "C12624", "KENTO", "green LED")
r("R3", S1, "1k")
r("R4", S1, "100k"); r("R5", S1, "100k"); r("R6", S1, "100k")

# ---- sheet 2: HS current-steering driver ----
for u in ("U5", "U6"):
    ic(u, S2, "C1522686", "SN65LVDT101DGK", "C1522686", "TI",
       note="alt. SN65LVDS101DGK (C181531) + 100R across A/B")
ic("Q1", S2, "C9994", "BFT92,215", "", "NXP", "BFT92",
   note="Q_P, SOT-23 (Mouser); alt. MMBTH81 C190349 with R_B 33R and TX_CAP DNP")
ic("Q2", S2, "C9994", "BFT92,215", "", "NXP", "BFT92", note="Q_N, as Q1")
ic("Q3", S2, "C9994", "BFT92,215", "", "NXP", "BFT92", note="Q_D (dump), as Q1")
ic("Q4", S2, "C53444", "MMBT3906LT1G", "C53444", "onsemi", note="tail current source")
ic("Q5", S2, "C20526", "MMBT3904", "C20526", "CJ", note="I_CTL generator")
ic("U7", S2, "C47081", "MCP6V02-E/SN", "C47081", "Microchip", note="alt. OPA2333AIDR")
r("R7", S2, "130"); r("R8", S2, "82"); r("R9", S2, "130"); r("R10", S2, "82")
r("R11", S2, "130"); r("R12", S2, "82"); r("R13", S2, "130"); r("R14", S2, "82")
r("R15", S2, "68", note="R_B Q_P (33R with MMBTH81)")
r("R16", S2, "68", note="R_B Q_N (33R with MMBTH81)")
r("R17", S2, "237", note="Ra"); r("R18", S2, "255", note="Rb"); r("R19", S2, "549", note="Rc")
r("R20", S2, "15", note="Rs (0.1 %, 25 ppm/K preferred)")
r("R21", S2, "1.69k", note="Rr"); r("R22", S2, "3.57k", note="Rg")
r("R23", S2, "1k"); r("R24", S2, "1k")
r("R40", S2, "100", note="DNP; fit only with SN65LVDS101 (no internal termination)")
r("R41", S2, "100", note="DNP; fit only with SN65LVDS101 (no internal termination)")
c("C16", S2, "100n", note="across Rr"); c("C17", S2, "10n", note="Q4 base to +3V3A")
c("C18", S2, "6.8p", note="TX_CAP_P (DNP with MMBTH81)")
c("C19", S2, "6.8p", note="TX_CAP_N (DNP with MMBTH81)")
c("C20", S2, "100n"); c("C21", S2, "100n"); c("C22", S2, "100n"); c("C23", S2, "10u")
ic("D6", S2, "C477990", "RB751S40,115", "C477990", "Nexperia", "RB751S40",
   note="HS collector blocking diode D+ (FS/LS high level must not forward-bias Q_P's C-B junction)")
ic("D7", S2, "C477990", "RB751S40,115", "C477990", "Nexperia", "RB751S40", note="as D6, D-")

# ---- sheet 3: FS/LS transceiver, HS termination switch, pull-downs, ESD, USB-C ----
ic("U8", S3, "C27643", "SN74LVC8T245PWR", "C27643", "TI", note="FS_OE/DAT/SE0/LS, DP_PULLUP_EN VADJ -> +3V3")
ic("U9", S3, "C485077", "SN74LVC138APWR", "C485077", "TI", note="FS/LS line-state decoder")
for u, n in (("U10", "GP_P: P gate D+ (Y1# & Y2#)"), ("U14", "GN_P: N gate D+ (OE & Y1# & Y2#)"),
             ("U15", "GP_M: P gate D- (Y0# & Y3#)"), ("U16", "GN_M: N gate D- (OE & Y0# & Y3#)")):
    ic(u, S3, "C22046", "SN74LVC1G11DBVR", "C22046", "TI", note=n)
ic("U17", S3, "C7813", "SN74LVC125APWR", "C7813", "TI", note="FS gate-drive path, enabled while FS_LS = 0")
ic("Q7", S3, "C456076", "NX3008CBKS,115", "C456076", "Nexperia", note="D+ driver: TR1 N to GND, TR2 P to +3V3")
ic("Q8", S3, "C456076", "NX3008CBKS,115", "C456076", "Nexperia", note="D- driver")
ic("Q9", S3, "C456076", "NX3008CBKS,115", "C456076", "Nexperia",
   note="DP pull-up switch: TR2 P switch, TR1 N gate inverter")
for k, d in (("2", "P"), ("3", "N"), ("4", "P"), ("5", "N")):
    ic("D" + k, S3, "C124205", "BAT54WS-7-F", "C124205", "Diodes Inc", "BAT54WS",
       note="fast gate turn-off (%s gate)" % d)
ic("U18", S3, "C48618", "TLV3502AIDCNR", "C48618", "TI", note="single-ended receivers VP / VM (Schmitt)")
ic("U19", S3, "C193413", "TLV3501AIDBVR", "C193413", "TI", note="differential receiver RCV")
ic("U20", S3, "C139324", "SN74LVC3G04DCTR", "C139324", "TI", note="receiver outputs 3.3 V -> VADJ (inverting)")
ic("U21", S3, "C113520", "SN74LVC1G02DCKR", "C113520", "TI",
   note="FSUSB42 OE# = NOR(FS_OE, HS_TERM_EN): FS driver off the line in receive mode")
ic("U11", S3, "C11355", "FSUSB42MUX", "C11355", "onsemi", note="HS termination switch")
ic("Q6", S3, "C194045", "2N7002DW-TP", "C194045", "MCC")
ic("U12", S3, "C7519", "USBLC6-2SC6", "C7519", "ST")
ic("J2", S3, "C165948", "TYPE-C-31-M-12", "C165948", "Korean Hroparts")
r("R25", S3, "33", note="R_S D+ (driver 1.2 / 3.8 Ohm + 33 + Ron 4.5 = 38.7 / 41.3 Ohm)")
r("R26", S3, "33", note="R_S D-")
r("R27", S3, "40.2", note="HS termination D+ (+ Ron 4.5R = 45R)")
r("R28", S3, "40.2", note="HS termination D-")
r("R29", S3, "15k"); r("R30", S3, "15k")
r("R31", S3, "1.5k", note="FS pull-up (switched by Q9)")
r("R32", S3, "5.1k"); r("R33", S3, "5.1k")
r("R34", S3, "45.3", note="DNP: host load emulation")
r("R35", S3, "45.3", note="DNP: host load emulation")
c("C24", S3, "100n"); c("C25", S3, "100n"); c("C26", S3, "10u"); c("C27", S3, "100n")
c("C28", S3, "100n"); c("C29", S3, "100n"); c("C30", S3, "100n")
# FS/LS gate networks: R42-R45 R_LS, R46-R49 R_FS, C34-C37 C_M, C38/C39 C_K (P), C40/C41 C_M2 (P)
#   + R50/R51 R_M2 (P); gates in the order GP_P, GN_P, GP_M, GN_M
for k, (g, t) in enumerate((("GP_P", "P"), ("GN_P", "N"), ("GP_M", "P"), ("GN_M", "N"))):
    r("R%d" % (42 + k), S3, FSV["RLS_" + t], note="R_LS %s (LS edge rate, always in)" % g)
    r("R%d" % (46 + k), S3, FSV["RFS_" + t], note="R_FS %s (FS path, LVC125)" % g)
    c("C%d" % (34 + k), S3, FSV["CM_" + t], note="C_M %s Miller drain-gate, C0G" % g)
c("C38", S3, FSV["CK_P"], note="C_K across R_LS GP_P (LS crossover), C0G")
c("C39", S3, FSV["CK_P"], note="C_K across R_LS GP_M, C0G")
c("C40", S3, FSV["CM2_P"], note="C_M2 GP_P: LS Miller capacitor behind R_M2, C0G")
c("C41", S3, FSV["CM2_P"], note="C_M2 GP_M, C0G")
c("C53", S3, FSV["CKF_N"], note="C_KF across R_FS GN_P (FS crossover: N turns on earlier), C0G")
c("C54", S3, FSV["CKF_N"], note="C_KF across R_FS GN_M, C0G")
r("R50", S3, FSV["RM2_P"], note="R_M2 GP_P (isolates C_M2 from the FS edges)")
r("R51", S3, FSV["RM2_P"], note="R_M2 GP_M")
r("R52", S3, "100k", note="FS_OE pull-down (driver off while VADJ is down)")
r("R53", S3, "100k", note="PU_EN pull-down")
r("R54", S3, "10k", note="Q9 P gate pull-up")
r("R55", S3, "1k", note="receiver input isolation D+ (hides the comparator inputs from HS)")
r("R56", S3, "1k", note="receiver input isolation D-")
r("R57", S3, "13k"); r("R58", S3, "10k"); r("R59", S3, "82k", note="Schmitt VP: 1.56 / 1.34 V")
r("R60", S3, "13k"); r("R61", S3, "10k"); r("R62", S3, "82k", note="Schmitt VM: 1.56 / 1.34 V")
for k in range(42, 53):
    c("C%d" % k, S3, "100n")
c("C55", S3, "100n")

# ---- sheet 4: amplitude bias (DAC / TX_VREF / TX_I_5U) ----
ic("U13", S4, "C36865", "MCP4821-E/SN", "C36865", "Microchip")
ic("J3", S4, "C65114", "Header 2x3 2.54mm", "C65114", "BOOMELE", note="V_CTL source, one jumper")
ic("J4", S4, "C124375", "Header 1x2 2.54mm", "C124375", "Ckmtw", note="TX_VREF input")
ic("J5", S4, "C124375", "Header 1x2 2.54mm", "C124375", "Ckmtw", note="TX_I_5U input")
r("R36", S4, "10k"); r("R37", S4, "10k"); r("R38", S4, "120k"); r("R39", S4, "1k")
c("C31", S4, "100n"); c("C32", S4, "100n"); c("C33", S4, "100n")

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
    "H7": "TX_IN_P_P", "H8": "TX_IN_P_N", "G9": "TX_IN_N_P", "G10": "TX_IN_N_N",
    "H10": "TX_EN_F", "H11": "FS_OE_F", "D11": "FS_DAT_F", "D12": "FS_SE0_F",
    "C10": "FS_LS_F", "C11": "FS_SUSPND_F", "H13": "DP_PULLUP_EN_F", "H14": "HS_TERM_EN_F",
    "G12": "PD_EN0_F", "G13": "PD_EN1_F", "D14": "DAC_CS_N_F", "D15": "DAC_SCK_F",
    "C14": "DAC_SDI_F", "C15": "VBUS_DET_F", "H16": "RXRCV_F", "H17": "RXDP_F", "G15": "RXDM_F",
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
con("U2", _1="VADJ", _2="VADJ", _3="HS_TERM_EN_F", _4="PD_EN0_F", _5="PD_EN1_F",
    _6="DAC_CS_N_F", _7="DAC_SCK_F", _8="DAC_SDI_F", _9="GND", _10="GND",
    _11="GND", _12="GND", _13="GND",
    _21="HS_TERM_EN", _20="PD_EN0", _19="PD_EN1", _18="DAC_CS_N", _17="DAC_SCK", _16="DAC_SDI",
    _22="GND", _23="+3V3", _24="+3V3")
two("C9", "VADJ", "GND"); two("C10", "+3V3", "GND")
con("U3", _1="VADJ", _2="GND", _3="TX_EN_F", _4="TX_EN_3V3", _5="VADJ", _6="+3V3A")
two("C11", "VADJ", "GND"); two("C12", "+3V3A", "GND")
con("U4", _1="VADJ", _2="GND", _3="VBUS_DET_F", _4="VBUS_DIV", _5="GND", _6="+3V3")
two("C13", "VADJ", "GND"); two("C14", "+3V3", "GND")
two("R1", "VBUS", "VBUS_DIV"); two("R2", "VBUS_DIV", "GND"); two("C15", "VBUS_DIV", "GND")
two("R3", "+3V3", "LED_A"); con("D1", _1="GND", _2="LED_A")
two("R4", "HS_TERM_EN", "GND"); two("R5", "PD_EN0", "GND"); two("R6", "PD_EN1", "GND")

# sheet 2
con("U5", _2="TX_IN_P_P", _3="TX_IN_P_N", _5="GND", _6="BP_T", _7="YP_T", _8="+3V3A")
con("U6", _2="TX_IN_N_P", _3="TX_IN_N_N", _5="GND", _6="BN_T", _7="YN_T", _8="+3V3A")
two("R7", "+3V3A", "BP_T"); two("R8", "BP_T", "GND")
two("R9", "+3V3A", "YP_T"); two("R10", "YP_T", "GND")
two("R11", "+3V3A", "BN_T"); two("R12", "BN_T", "GND")
two("R13", "+3V3A", "YN_T"); two("R14", "YN_T", "GND")
two("R15", "BP_T", "BP"); two("R16", "BN_T", "BN")
two("R40", "TX_IN_P_P", "TX_IN_P_N"); two("R41", "TX_IN_N_P", "TX_IN_N_N")
con("Q1", _1="BP", _2="NEM", _3="DP_C")        # BFT92: 1 B, 2 E, 3 C
con("Q2", _1="BN", _2="NEM", _3="DM_C")
con("D6", _2="DP_C", _1="DP")                   # RB751S40: 1 K, 2 A
con("D7", _2="DM_C", _1="DM")
con("Q3", _1="BD", _2="NEM", _3="GND")
two("R17", "TX_EN_3V3", "BD"); two("R18", "BD", "GND"); two("R19", "+3V3A", "BD")
con("Q4", _1="QT_B", _2="ET", _3="NEM")        # MMBT3906: 1 B, 2 E, 3 C
two("R20", "+3V3A", "ET")
con("U7", _1="QT_O", _2="ET", _3="VR", _4="GND", _5="V_CTL", _6="EG", _7="QG_O", _8="+3V3A")
two("R23", "QT_O", "QT_B"); two("C17", "QT_B", "+3V3A")
two("R24", "QG_O", "QG_B")
con("Q5", _1="QG_B", _2="EG", _3="VR")         # MMBT3904: 1 B, 2 E, 3 C
two("R22", "EG", "GND"); two("R21", "+3V3A", "VR"); two("C16", "+3V3A", "VR")
two("C18", "DP", "GND"); two("C19", "DM", "GND")
two("C20", "+3V3A", "GND"); two("C21", "+3V3A", "GND"); two("C22", "+3V3A", "GND")
two("C23", "+3V3A", "GND")

# sheet 3
con("U8", _1="VADJ", _2="VADJ", _3="FS_OE_F", _4="FS_DAT_F", _5="FS_SE0_F", _6="FS_LS_F",
    _7="DP_PULLUP_EN_F", _8="GND", _9="GND", _10="GND", _11="GND", _12="GND", _13="GND",
    _21="FS_OE", _20="FS_DAT", _19="FS_SE0", _18="FS_LS", _17="PU_EN",
    _22="GND", _23="+3V3", _24="+3V3")
con("U9", _1="FS_DAT", _2="FS_LS", _3="FS_SE0", _4="GND", _5="GND", _6="FS_OE", _8="GND",
    _15="Y0_N", _14="Y1_N", _13="Y2_N", _12="Y3_N", _16="+3V3")
con("U10", _1="Y1_N", _3="Y2_N", _6="+3V3", _4="GPP_X", _2="GND", _5="+3V3")   # LVC1G11: 1 A 3 B 6 C 4 Y
con("U14", _1="FS_OE", _3="Y1_N", _6="Y2_N", _4="GNP_X", _2="GND", _5="+3V3")
con("U15", _1="Y0_N", _3="Y3_N", _6="+3V3", _4="GPM_X", _2="GND", _5="+3V3")
con("U16", _1="FS_OE", _3="Y0_N", _6="Y3_N", _4="GNM_X", _2="GND", _5="+3V3")
con("U17", _1="FS_LS", _2="GPP_X", _3="GPP_F", _4="FS_LS", _5="GNP_X", _6="GNP_F", _7="GND",
    _10="FS_LS", _9="GPM_X", _8="GPM_F", _13="FS_LS", _12="GNM_X", _11="GNM_F", _14="+3V3")
for k, (g, x, f, dr) in enumerate((("GP_P", "GPP_X", "GPP_F", "FSDP"), ("GN_P", "GNP_X", "GNP_F", "FSDP"),
                                   ("GP_M", "GPM_X", "GPM_F", "FSDM"), ("GN_M", "GNM_X", "GNM_F", "FSDM"))):
    two("R%d" % (42 + k), x, g)
    two("R%d" % (46 + k), f, g)
    two("C%d" % (34 + k), dr, g)
    if g.startswith("GP"):                         # BAT54WS: 1 K, 2 A; P gate pulled up
        con("D%d" % (2 + k), _2=x, _1=g)
    else:                                          # N gate pulled down
        con("D%d" % (2 + k), _2=g, _1=x)
two("C38", "GPP_X", "GP_P"); two("C39", "GPM_X", "GP_M")
two("C53", "GNP_F", "GN_P"); two("C54", "GNM_F", "GN_M")
two("C40", "FSDP", "M2_P"); two("R50", "M2_P", "GP_P")
two("C41", "FSDM", "M2_M"); two("R51", "M2_M", "GP_M")
con("Q7", _1="GND", _2="GN_P", _6="FSDP", _4="+3V3", _5="GP_P", _3="FSDP")   # 1 S1 2 G1 6 D1 (N), 4 S2 5 G2 3 D2 (P)
con("Q8", _1="GND", _2="GN_M", _6="FSDM", _4="+3V3", _5="GP_M", _3="FSDM")
con("Q9", _1="GND", _2="PU_EN", _6="PU_G", _4="+3V3", _5="PU_G", _3="VPU")
two("R52", "FS_OE", "GND"); two("R53", "PU_EN", "GND"); two("R54", "+3V3", "PU_G")
two("R55", "DP", "RX_P"); two("R56", "DM", "RX_M")
con("U18", _1="VTH_P", _2="RX_P", _3="VTH_M", _4="RX_M", _5="GND", _6="VM_N", _7="VP_N", _8="+3V3")
two("R57", "+3V3", "VTH_P"); two("R58", "VTH_P", "GND"); two("R59", "VP_N", "VTH_P")
two("R60", "+3V3", "VTH_M"); two("R61", "VTH_M", "GND"); two("R62", "VM_N", "VTH_M")
con("U19", _1="RX_P", _2="GND", _3="RX_M", _4="+3V3", _5="RCV_N", _6="GND")
con("U20", _1="VP_N", _7="RXDP_F", _3="VM_N", _5="RXDM_F", _6="RCV_N", _2="RXRCV_F", _4="GND", _8="VADJ")
two("R25", "FSDP", "HSD1P"); two("R26", "FSDM", "HSD1M")
con("U11", _1="+3V3", _2="HS_TERM_EN", _3="DP", _4="DM", _5="GND",
    _6="HSD1M", _7="HSD1P", _8="TERM_M", _9="TERM_P", _10="SW_OE_N")
con("U21", _2="FS_OE", _1="HS_TERM_EN", _4="SW_OE_N", _3="GND", _5="+3V3")   # LVC1G02: 2 A 1 B 4 Y
two("C55", "+3V3", "GND")
two("R27", "TERM_P", "GND"); two("R28", "TERM_M", "GND")
con("Q6", _1="GND", _2="PD_EN0", _6="PD_P", _4="GND", _5="PD_EN1", _3="PD_M")
two("R29", "DP", "PD_P"); two("R30", "DM", "PD_M")
two("R31", "VPU", "DP")
con("U12", _1="DP", _6="DP", _3="DM", _4="DM", _2="GND", _5="VBUS")
con("J2", A1B12="GND", B1A12="GND", A4B9="VBUS", B4A9="VBUS", A5="CC1", B5="CC2",
    A6="DP", B6="DP", A7="DM", B7="DM", _1="GND", _2="GND", _3="GND", _4="GND")
# J2 symbol pin numbers are "A6" etc.; DP2/DN2 are B6/B7
two("R32", "CC1", "GND"); two("R33", "CC2", "GND")
two("R34", "DP", "GND"); two("R35", "DM", "GND")
two("C24", "VADJ", "GND"); two("C25", "+3V3", "GND"); two("C26", "+3V3", "GND")   # U8, bulk
two("C27", "VADJ", "GND"); two("C28", "+3V3", "GND"); two("C29", "+3V3", "GND")   # U20, U9, U11
two("C30", "VBUS", "GND")
for k in range(42, 53):                            # U10 U14-U19 (U18 x2), Q7-Q9 sources
    two("C%d" % k, "+3V3", "GND")

# sheet 4
con("U13", _1="+3V3A", _2="DAC_CS_N", _3="DAC_SCK", _4="DAC_SDI", _5="GND", _6="+3V3A",
    _7="GND", _8="V_DAC")
con("J3", _1="V_DAC", _2="V_CTL_J", _3="V_VREF2", _4="V_CTL_J", _5="TX_I_5U", _6="V_CTL_J")
con("J4", _1="TX_VREF", _2="GND")
con("J5", _1="TX_I_5U", _2="GND")
two("R36", "TX_VREF", "V_VREF2"); two("R37", "V_VREF2", "GND"); two("R38", "TX_I_5U", "GND")
two("R39", "V_CTL_J", "V_CTL"); two("C31", "V_CTL", "GND")
two("C32", "+3V3A", "GND"); two("C33", "V_VREF2", "GND")

# ---------------------------------------------------------------------------
# EasyEDA Std shape handling
# ---------------------------------------------------------------------------
_id = [0]
_cache = {}


def gid():
    _id[0] += 1
    return "gtx%05d" % _id[0]


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
# ---------------------------------------------------------------------------
TITLES = {S1: "FMC LPC, power, level translation, IPMI EEPROM",
          S2: "HS current-steering driver (afe_hs_tx)",
          S3: "Discrete FS/LS driver and receivers, HS termination, pulls, ESD, USB-C (afe_fsls_xcvr, afe_term)",
          S4: "HS amplitude bias: MCP4821 DAC / TX_VREF / TX_I_5U"}


def frame(w, h, title, no, n):
    s = ["R~0~%g~0~0~%g~%g~#880000~1~0~none~%s~0~" % (-h, w, h, gid()),
         "R~10~%g~0~0~%g~%g~#880000~1~0~none~%s~0~" % (-h + 10, w - 20, h - 20, gid())]
    bx, by = w - 470, -80
    s.append("R~%g~%g~0~0~460~70~#880000~1~0~none~%s~0~" % (bx, by, gid()))
    for x, y, t in [(bx + 8, by + 18, "USB 2.0 discrete transmitter board (afe_transceiver TX) - FMC LPC"),
                    (bx + 8, by + 36, "Sheet %d/%d: %s" % (no, n, title)),
                    (bx + 8, by + 54, "Rev 0.1 - generated by easyeda/gen_schematic.py - "
                                      "symbols: JLCEDA/EasyEDA official library")]:
        s.append("T~L~%g~%g~0~#000080~Arial~~~~~comment~%s~1~start~%s~0~" % (x, y, t, gid()))
    return s


GROUPS = {
    S1: [("J1  FMC LPC (VITA 57.1) - LA pins, power, IPMI", ["J1"]),
         ("Power: FMC 3P3V -> +3V3 (digital, FS) / +3V3A (HS driver)",
          ["FB1", "FB2", "C1", "C2", "C3", "C4", "C5", "C6", "C7"]),
         ("FRU EEPROM (IPMI)", ["U1", "C8"]),
         ("Slow controls VADJ -> 3.3 V", ["U2", "C9", "C10", "R4", "R5", "R6"]),
         ("TX_EN VADJ -> +3V3A (dump base)", ["U3", "C11", "C12"]),
         ("VBUS detect 3.3 V -> VADJ", ["U4", "C13", "C14", "R1", "R2", "C15"]),
         ("Power LED", ["R3", "D1"])],
    S2: [("TX_IN_P / TX_IN_N: LVDS -> LVPECL (Z = inverted), Thevenin 130/82 = 50R to VCC-2, base resistors R_B",
          ["U5", "U6", "R7", "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15", "R16", "R40", "R41", "C20", "C21"]),
         ("Current steering: Q1 = Q_P -> DP, Q2 = Q_N -> DM (RB751S40 blocking diodes), Q3 = Q_D dump; TX_CAP_P/N",
          ["Q1", "Q2", "Q3", "D6", "D7", "C18", "C19"]),
         ("Dump base: TX_EN = 0 -> 0.60 V, TX_EN = 1 -> 2.00 V", ["R17", "R18", "R19"]),
         ("Tail current I = V(Rr) / Rs  (U7A, Q4)", ["U7", "Q4", "R20", "R23", "C17", "C22", "C23"]),
         ("I_CTL = V_CTL / Rg into Rr  (U7B, Q5)", ["Q5", "R21", "R22", "R24", "C16"])],
    S3: [("FS/LS logic: VADJ -> 3.3 V, LVC138 decode, LVC1G11 gate commands, LVC125 FS path",
          ["U8", "C24", "C25", "C26", "R52", "U9", "C28", "U10", "U14", "U15", "U16", "U17",
           "C42", "C43", "C44", "C45", "C46"]),
         ("FS/LS driver D+ (Q7): R_LS, R_FS, BAT54WS turn-off, C_M, C_K (P, LS), C_M2+R_M2 (P), C_KF (N, FS)",
          ["Q7", "R42", "R46", "D2", "C34", "C38", "C40", "R50", "R43", "R47", "C53", "D3", "C35", "C47"]),
         ("FS/LS driver D- (Q8)",
          ["Q8", "R44", "R48", "D4", "C36", "C39", "C41", "R51", "R45", "R49", "C54", "D5", "C37", "C48"]),
         ("DP pull-up switch (Q9, DP_PULLUP_EN)", ["Q9", "R53", "R54", "R31", "C49"]),
         ("Receivers: TLV3502 VP/VM (Schmitt 1.56/1.34 V), TLV3501 RCV, LVC3G04 to VADJ",
          ["R55", "R56", "U18", "R57", "R58", "R59", "R60", "R61", "R62", "U19", "U20",
           "C50", "C51", "C52", "C27"]),
         ("HS termination switch: SEL = HS_TERM_EN (40.2R + Ron = 45R), OE# = NOR(FS_OE, HS_TERM_EN)",
          ["U11", "U21", "R25", "R26", "R27", "R28", "C29", "C55"]),
         ("15k pull-downs (PD_EN0 = DP, PD_EN1 = DM)", ["Q6", "R29", "R30"]),
         ("ESD, USB-C receptacle, host-load emulation (DNP)",
          ["U12", "J2", "R32", "R33", "R34", "R35", "C30"])],
    S4: [("DAC: V_DAC = code x 0.5 mV (TX_AMP trim)", ["U13", "C32"]),
         ("V_CTL source select (J3: 1-2 DAC, 3-4 TX_VREF/2, 5-6 TX_I_5U x 120k) and filter",
          ["J3", "R39", "C31"]),
         ("Reference inputs from the AFE reference block (afe_ref)", ["J4", "J5", "R36", "R37", "R38", "C33"])],
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
    with open(os.path.join(BOMDIR, "tx_board_bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Qty", "Value", "Manufacturer", "MPN", "LCSC", "Footprint", "Fitted", "Note"])
        for r in rows:
            w.writerow([",".join(r["refs"]), len(r["refs"]), r["value"], r["mfr"], r["mpn"],
                        r["lcsc"], r["footprint"], "DNP" if r["dnp"] else "yes", r["note"]])
    with open(os.path.join(BOMDIR, "tx_board_bom_jlcpcb.csv"), "w", newline="") as f:
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
    proj = {"editorVersion": "6.5.61", "docType": "5", "title": "USB2 TX board",
            "description": "Discrete USB 2.0 transmitter (afe_transceiver TX) on FMC LPC",
            "colors": {}, "schematics": [sheet_doc(s, i + 1, len(sheets)) for i, s in enumerate(sheets)]}
    with open(os.path.join(HERE, "usb_tx_board_sch.json"), "w") as f:
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
