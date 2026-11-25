"""cdr_parts.py - parts and connectivity of the discrete USB 2.0 CDR board
(imported by gen_schematic.py; keep in sync with sim/run_sims.py VAL and
doc/cdr_board.md section 4)

PARTS[ref] = dict(sheet, sym (LCSC of the symbol), value, mpn, lcsc, mfr, note)
NETS[ref]  = {pin: net}; pins are symbol pin numbers, or pin names (resolved
             by gen_schematic.py against the cached symbol; a name must be
             unique in the symbol).

LVPECL on +3V3 (VCC = 3.3 V, VEE = GND): every 100EP / NB6L14 output has
150 Ohm emitter pull-downs at the driver and 100 Ohm across the pair at the
(last) receiver; on-board traces are < 25 mm.  Nets ending _P / _N are pairs.
"""
import re

R0603, C0603 = "C25804", "C108079"          # symbols used for all 0603 R / C
RES = {  # value -> (MPN, LCSC)   UNI-ROYAL 0603 1 %
    "10": ("0603WAF100JT5E", "C22859"), "22": ("0603WAF220JT5E", "C23345"),
    "47": ("0603WAF470JT5E", "C23182"), "49.9": ("0603WAF499JT5E", "C23185"), "51": ("0603WAF510JT5E", "C23197"),
    "62": ("0603WAF620JT5E", "C23222"), "100": ("0603WAF1000T5E", "C22775"),
    "150": ("0603WAF1500T5E", "C22808"), "180": ("0603WAF1800T5E", "C22828"),
    "470": ("0603WAF4700T5E", "C23179"), "1k": ("0603WAF1001T5E", "C21190"),
    "2.2k": ("0603WAF2201T5E", "C4190"), "4.7k": ("0603WAF4701T5E", "C23162"),
    "6.8k": ("0603WAF6801T5E", "C23212"), "10k": ("0603WAF1002T5E", "C25804"),
    "16.5k": ("0603WAF1652T5E", "C22812"), "22k": ("0603WAF2202T5E", "C31850"),
    "32.4k": ("0603WAF3242T5E", "C13187"), "100k": ("0603WAF1003T5E", "C25803"),
    "220k": ("0603WAF2203T5E", "C22961"),
}
CAP = {  # value -> (MPN, LCSC, manufacturer)
    "100n": ("CC0603KRX7R7BB104", "C108079", "YAGEO"),
    "10u": ("CL10A106KP8NNNC", "C19702", "Samsung"),          # 10 V: 3.3 / 5 V rails only
    "2.2u": ("CL10A225KA8NNNC", "C57895", "Samsung"),         # 25 V: 12 V rail
    "1u": ("CL10A105KB8NNNC", "C15849", "Samsung"),
    "10n": ("CL10B103KB8NNNC", "C1589", "Samsung"),
    "1n": ("0603CG102J500NT", "C1636", "FH"),
    "100p": ("0603CG101J500NT", "C1635", "FH"),
    "18p": ("0603CG180J500NT", "C92671", "FH"),
    "12p": ("0603CG120J500NT", "C1642", "FH"),
    "10p": ("0603CG100J500NT", "C91367", "FH"),
    "3.3p": ("0603CG3R3C500NT", "C1660", "FH"),
    "1.5p": ("0603CG1R5C500NT", "C1639", "FH"),
    "0.3p": ("0603CG0R3B500NT", "C507054", "FH"),
}

PARTS = {}
DNP = set()
S1, S2, S3, S4 = "1_FMC_POWER_IO", "2_DATA_INPUT", "3_PHASE_DETECTOR_CLOCK", "4_VCO_DRIVER_TUNING"
_n = {"R": 0, "C": 0}


def ic(ref, sheet, sym, mpn, lcsc, mfr, value=None, note=""):
    PARTS[ref] = dict(sheet=sheet, sym=sym, value=value or mpn, mpn=mpn, lcsc=lcsc, mfr=mfr, note=note)
    return ref


def r(sheet, val, a, b, note=""):
    """next R: value val between nets a and b"""
    _n["R"] += 1
    ref = "R%d" % _n["R"]
    mpn, lc = RES[val]
    PARTS[ref] = dict(sheet=sheet, sym=R0603, value=val if val[-1] in "kM" else val + "R",
                      mpn=mpn, lcsc=lc, mfr="UNI-ROYAL", note=note)
    NETS[ref] = {"1": a, "2": b}
    return ref


def c(sheet, val, a, b="GND", note=""):
    _n["C"] += 1
    ref = "C%d" % _n["C"]
    mpn, lc, mf = CAP[val]
    PARTS[ref] = dict(sheet=sheet, sym=C0603, value=val + "F", mpn=mpn, lcsc=lc, mfr=mf, note=note)
    NETS[ref] = {"1": a, "2": b}
    return ref


NETS = {}


def con(ref, **pins):
    NETS.setdefault(ref, {}).update({k.lstrip("_"): v for k, v in pins.items()})


def sma(ref, sheet, value, net, note=""):
    ic(ref, sheet, "C496549", "BWSMA-KE-Z001", "C496549", "BAT WIRELESS", value, note=note)
    con(ref, _5=net, _1="GND", _2="GND", _3="GND", _4="GND")
    return ref


def pecl_out(sheet, p, n, note="LVPECL emitter pull-down"):
    return [r(sheet, "150", p, "GND", note), r(sheet, "150", n, "GND", note)]


def term(sheet, p, n, note="100 Ohm differential termination"):
    return r(sheet, "100", p, n, note)


GROUPS = {S1: [], S2: [], S3: [], S4: []}


def group(sheet, cap, refs):
    GROUPS[sheet].append((cap, [x for x in refs if x]))


# ===========================================================================
# sheet 1: FMC, power, level translation, IPMI EEPROM
# ===========================================================================
ic("J1", S1, "C5366873", "ASP-134604-01", "", "Samtec", "FMC LPC mezzanine",
   note="order from Samtec / Mouser; LCSC symbol C5366873")
fmc = {
    "H4": "CLK_RX_P_F", "H5": "CLK_RX_N_F",            # CLK0_M2C: recovered clock
    "G6": "HS_RXD_P_F", "G7": "HS_RXD_N_F",            # LA00_CC: recovered data
    "D8": "DPAT_P_F", "D9": "DPAT_N_F",                # LA01_CC: FPGA test pattern (LVDS)
    "H7": "CDR_EN_F", "H8": "CDR_SET_F", "G9": "DSEL0_F", "G10": "DSEL1_F",
    "H10": "VCO_OFF_F", "H11": "CSW_EXT_F", "D11": "DAC_CS_N_F", "D12": "ADC_CS_N_F",
    "C10": "SPI_SCK_F", "C11": "SPI_SDI_F", "H13": "ADC_SDO_F", "H14": "CSW_DAC_F",
    "C39": "P3V3_FMC", "D36": "P3V3_FMC", "D38": "P3V3_FMC", "D40": "P3V3_FMC",
    "C35": "P12V_FMC", "C37": "P12V_FMC",
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
group(S1, "J1  FMC LPC (VITA 57.1) - CLK0_M2C, LA00/01 pairs, LA controls, power, IPMI", ["J1"])

ic("FB1", S1, "C80165", "BLM18PG221SN1D", "C80165", "Murata", "220R@100MHz", note="FMC 3P3V -> +3V3 (ECL, ~0.45 A)")
ic("FB2", S1, "C80165", "BLM18PG221SN1D", "C80165", "Murata", "220R@100MHz", note="FMC 12P0V -> +12V_F")
con("FB1", _1="P3V3_FMC", _2="+3V3"); con("FB2", _1="P12V_FMC", _2="+12V_F")
pw = ["FB1", "FB2", c(S1, "10u", "+3V3"), c(S1, "10u", "+3V3"), c(S1, "100n", "+3V3"),
      c(S1, "2.2u", "+12V_F", note="12 V input"), c(S1, "10u", "VADJ"), c(S1, "100n", "VADJ")]
ic("U1", S1, "C16430", "TPS7A4901DGNR", "C16430", "TI",
   note="+12V_F -> +5V_A (VCO, prop driver, op-amps, DAC / ADC), Vout = 1.185 V x (1 + R1/R2)")
con("U1", IN="+12V_F", EN="+12V_F", OUT="+5V_A", FB="LDO5_FB", **{"NR/SS": "LDO5_NR"},
    GND="GND", PwPd="GND")
pw += ["U1", r(S1, "32.4k", "+5V_A", "LDO5_FB", "TPS7A4901 FB top: 5.02 V"),
       r(S1, "10k", "LDO5_FB", "GND", "TPS7A4901 FB bottom"),
       c(S1, "10n", "LDO5_NR", note="NR/SS: noise filter / soft start"),
       c(S1, "10u", "+5V_A", note="+5V_A output (TPS7A4901 needs >= 2.2 uF)"), c(S1, "10u", "+5V_A"),
       c(S1, "100n", "+5V_A")]
group(S1, "Power: 3P3V -> +3V3 (100EP / NB6L14), 12P0V -> TPS7A4901 -> +5V_A", pw)

ic("U2", S1, "C6203", "AT24C02C-SSHM-T", "C6203", "Microchip", note="FRU EEPROM (VITA 57.1 IPMI)")
con("U2", A0="FMC_GA0", A1="FMC_GA1", A2="GND", GND="GND", SDA="FMC_SDA", SCL="FMC_SCL",
    WP="GND", VCC="P3V3AUX")
group(S1, "FRU EEPROM (IPMI)", ["U2", c(S1, "100n", "P3V3AUX")])

# U3: VADJ -> +5V_A (SPI, coarse switch, VCO_OFF)
ic("U3", S1, "C27643", "SN74LVC8T245PWR", "C27643", "TI", note="VADJ -> +5V_A controls")
con("U3", _1="VADJ", _2="VADJ", _3="DAC_CS_N_F", _4="ADC_CS_N_F", _5="SPI_SCK_F", _6="SPI_SDI_F",
    _7="CSW_EXT_F", _8="CSW_DAC_F", _9="VCO_OFF_F", _10="GND", _11="GND", _12="GND", _13="GND",
    _21="DAC_CS_N", _20="ADC_CS_N", _19="SPI_SCK", _18="SPI_SDI", _17="CSW_EXT", _16="CSW_DAC",
    _15="VCO_OFF", _22="GND", _23="+5V_A", _24="+5V_A")
group(S1, "Controls VADJ -> +5V_A (DAC / ADC SPI, coarse source switch, VCO_OFF)",
      ["U3", c(S1, "100n", "VADJ"), c(S1, "100n", "+5V_A"),
       r(S1, "100k", "+5V_A", "DAC_CS_N", "DAC CS# high"), r(S1, "100k", "+5V_A", "ADC_CS_N", "ADC CS# high"),
       r(S1, "100k", "CSW_EXT", "GND", "coarse switches open while VADJ is down"),
       r(S1, "100k", "CSW_DAC", "GND", "coarse switches open while VADJ is down"),
       r(S1, "100k", "+5V_A", "VCO_OFF", "VCO_OFF high (VCO off) while VADJ is down")])
# U4: VADJ -> +3V3 (100EP set, NB6L14 EN, EP57 select)
ic("U4", S1, "C27643", "SN74LVC8T245PWR", "C27643", "TI", note="VADJ -> +3V3 ECL controls")
con("U4", _1="VADJ", _2="VADJ", _3="CDR_EN_F", _4="CDR_SET_F", _5="DSEL0_F", _6="DSEL1_F",
    _7="GND", _8="GND", _9="GND", _10="GND", _11="GND", _12="GND", _13="GND",
    _21="CDR_EN", _20="CDR_SET", _19="DSEL0", _18="DSEL1", _22="GND", _23="+3V3", _24="+3V3")
group(S1, "Controls VADJ -> +3V3 (CDR_EN -> NB6L14 EN, CDR_SET -> 100EP29 S, EP57 SEL)",
      ["U4", c(S1, "100n", "VADJ"), c(S1, "100n", "+3V3"),
       r(S1, "10k", "CDR_EN", "GND", "CDR disabled (CLK_RX low) while VADJ is down"),
       r(S1, "10k", "+3V3", "CDR_SET", "flip-flops set (HS_RXD = 1, no pump) while VADJ is down"),
       r(S1, "100k", "DSEL0", "GND"), r(S1, "100k", "DSEL1", "GND")])
ic("U5", S1, "C7843", "SN74LVC1T45DBVR", "C7843", "TI", note="ADC DOUT +5V_A -> VADJ")
con("U5", VCCA="VADJ", GND="GND", A="ADC_SDO_F", B="ADC_SDO", DIR="GND", VCCB="+5V_A")
group(S1, "ADC DOUT -> VADJ", ["U5", c(S1, "100n", "VADJ"), c(S1, "100n", "+5V_A")])
ic("D1", S1, "C12624", "KT-0603G", "C12624", "KENTO", "green LED", note="+3V3 power")
con("D1", K="GND", A="LED_A")
group(S1, "Power LED", [r(S1, "1k", "+3V3", "LED_A"), "D1"])

# ===========================================================================
# sheet 2: data input CDR_DATA: SMA pair or FPGA pattern, MC100EP57 select
# ===========================================================================
g = [sma("J2", S2, "SMA DIN_P", "DIN_P", "external HS data (generator / AFE receiver board), 50 Ohm"),
     sma("J3", S2, "SMA DIN_N", "DIN_N", "external HS data, complement (terminate 50 Ohm if unused)"),
     r(S2, "49.9", "DIN_P", "DIN_CT", "50 Ohm termination"), r(S2, "49.9", "DIN_N", "DIN_CT", "50 Ohm termination"),
     c(S2, "100n", "DIN_CT", note="termination centre tap, AC ground"),
     c(S2, "100n", "DIN_P", "D0_P", "AC coupling"), c(S2, "100n", "DIN_N", "D0_N", "AC coupling"),
     r(S2, "1k", "D0_P", "MUX_VBB1", "bias to VBB"), r(S2, "1k", "D0_N", "MUX_VBB1", "bias to VBB"),
     r(S2, "22k", "D0_N", "GND", "offset ~90 mV: idle reads 1 (J)")]
group(S2, "SMA input (differential or single-ended), 50 Ohm, AC-coupled, biased to VBB", g)
g = [term(S2, "DPAT_P_F", "DPAT_N_F", "LVDS termination"),
     c(S2, "100n", "DPAT_P_F", "D1_P", "AC coupling"), c(S2, "100n", "DPAT_N_F", "D1_N", "AC coupling"),
     r(S2, "4.7k", "D1_P", "MUX_VBB2", "bias to VBB"), r(S2, "4.7k", "D1_N", "MUX_VBB2", "bias to VBB"),
     r(S2, "100k", "D1_N", "GND", "offset ~85 mV: idle reads 1 (J)")]
group(S2, "FPGA test pattern (LVDS 480 Mb/s, OSERDES) -> 100 Ohm, AC-coupled, biased to VBB", g)
ic("U6", S2, "C603231", "MC100EP57DTG", "C603231", "onsemi",
   note="4:1 differential mux: D0 SMA, D1 FPGA pattern (SEL1 SEL0 = 00 / 01)")
con("U6", _1="+3V3", _2="D0_P", _3="D0_N", _4="D1_P", _5="D1_N", _6="GND", _7="MUX_VBB1",
    _8="GND", _9="MUX_VBB1", _10="GND", _11="GND", _12="MUX_VBB2", _13="MUX_VBB1", _14="+3V3",
    _15="DAT_N", _16="DAT_P", _17="+3V3", _18="DSEL0", _19="DSEL1", _20="+3V3")
g = ["U6", c(S2, "100n", "+3V3"), c(S2, "100n", "+3V3"), c(S2, "10n", "MUX_VBB1", note="VBB"),
     c(S2, "10n", "MUX_VBB2", note="VBB")] + pecl_out(S2, "DAT_P", "DAT_N")
group(S2, "MC100EP57 data select -> CDR_DATA (DAT_P/N) to the phase detector; D2/D3 unused (read 0)", g)

# ===========================================================================
# sheet 3: Alexander phase detector (2 x MC100EP29, 2 x MC100EP08), NB6L14
# ===========================================================================
# U7 (EP29 #1): FF0 = A  (data, rising CLK)   FF1 = T' (data, falling CLK: clock legs swapped)
# U8 (EP29 #2): FF0 = B  (A + 1 bit)          FF1 = T  (T' retimed on the rising edge)
ic("U7", S3, "C603222", "MC100EP29DTG", "C603222", "onsemi",
   note="FF0 A = data on rising CLK_RX, FF1 T' = data on falling CLK_RX (CLK1 legs swapped)")
con("U7", _1="DAT_P", _2="DAT_N", _3="PD1_VBB", _4="CK1_P", _5="CK1_N", _6="CK1_N", _7="CK1_P",
    _8="DAT_P", _9="DAT_N", _10="+3V3", _11="GND", _12="GND", _13="CDR_SET", _14="TP_N", _15="TP_P",
    _16="A_N", _17="A_P", _18="CDR_SET", _19="GND", _20="+3V3")
ic("U8", S3, "C603222", "MC100EP29DTG", "C603222", "onsemi",
   note="FF0 B = A delayed one bit (= HS_RXD), FF1 T = T' retimed")
con("U8", _1="A_P", _2="A_N", _3="PD2_VBB", _4="CK2_P", _5="CK2_N", _6="CK2_P", _7="CK2_N",
    _8="TP_P", _9="TP_N", _10="+3V3", _11="GND", _12="GND", _13="CDR_SET", _14="T_N", _15="T_P",
    _16="B_N", _17="B_P", _18="CDR_SET", _19="GND", _20="+3V3")
g = ["U7", "U8", term(S3, "DAT_P", "DAT_N", "CDR_DATA termination (at U7 D1)"),
     c(S3, "100n", "+3V3"), c(S3, "100n", "+3V3"), c(S3, "100n", "+3V3"), c(S3, "100n", "+3V3"),
     c(S3, "10n", "PD1_VBB", note="VBB (unused)"), c(S3, "10n", "PD2_VBB", note="VBB (unused)")]
g += pecl_out(S3, "A_P", "A_N") + [term(S3, "A_P", "A_N", "A: U8 D0 + U10 D1, terminated at U10")]
g += pecl_out(S3, "TP_P", "TP_N") + [term(S3, "TP_P", "TP_N", "T' terminated at U8 D1")]
g += pecl_out(S3, "B_P", "B_N") + [term(S3, "B_P", "B_N", "B: U9 D0 + FPGA, terminated at U9")]
g += pecl_out(S3, "T_P", "T_N") + [term(S3, "T_P", "T_N", "T: U9 D1 + U10 D0, terminated at U10")]
group(S3, "Alexander sampler: MC100EP29 x 2 (A, T', B, T); CDR_SET -> S0/S1 (CDR_EN = 0: all 1)", g)
ic("U9", S3, "C897711", "MC100EP08DG", "C897711", "onsemi", "MC100EP08 UP", note="UP = B xor T (late)")
con("U9", _1="B_P", _2="B_N", _3="T_P", _4="T_N", _5="GND", _6="UP_N", _7="UP_P", _8="+3V3")
ic("U10", S3, "C897711", "MC100EP08DG", "C897711", "onsemi", "MC100EP08 DN", note="DN = T xor A (early)")
con("U10", _1="T_P", _2="T_N", _3="A_P", _4="A_N", _5="GND", _6="DN_N", _7="DN_P", _8="+3V3")
g = ["U9", "U10", c(S3, "100n", "+3V3"), c(S3, "100n", "+3V3")]
g += pecl_out(S3, "UP_P", "UP_N") + pecl_out(S3, "DN_P", "DN_N")
group(S3, "Decision XORs: UP = B xor T, DN = T xor A (1 UI pulses) -> prop driver (sheet 4)", g)
ic("U11", S3, "C897855", "NB6L14MNG", "C897855", "onsemi",
   note="1:4 clock fan-out: Q0 -> U7, Q1 -> U8, Q2 -> CLK_RX (FPGA), Q3 -> monitor; EN = CDR_EN")
con("U11", _1="CK2_P", _2="CK2_N", _3="CKF_P", _4="CKF_N", _5="CKM_P", _6="CKM_N", _7="+3V3",
    _8="CDR_EN", _9="NB_INN", _10="NB_VREF", _11="NB_VREF", _12="NB_IN", _13="GND", _14="+3V3",
    _15="CK1_P", _16="CK1_N", _17="GND")
g = ["U11", c(S3, "100n", "+3V3"), c(S3, "100n", "+3V3"), c(S3, "10u", "+3V3"),
     c(S3, "100n", "NB_INN", note="IN# AC ground (biased to VREF_AC via 50 Ohm)"),
     c(S3, "100n", "NB_VREF", note="VREF_AC = VT")]
g += pecl_out(S3, "CK1_P", "CK1_N") + [term(S3, "CK1_P", "CK1_N", "at U7 CLK1")]
g += pecl_out(S3, "CK2_P", "CK2_N") + [term(S3, "CK2_P", "CK2_N", "at U8 CLK1")]
group(S3, "NB6L14 clock fan-out (VCO, single-ended into IN, VT = VREF_AC)", g)
# CLK_RX, HS_RXD -> FPGA: AC-coupled, bias VBIAS (FPGA DIFF_TERM)
g = pecl_out(S3, "CKF_P", "CKF_N") + [
    c(S3, "100n", "CKF_P", "CLK_RX_P_F", "AC coupling to the FPGA"),
    c(S3, "100n", "CKF_N", "CLK_RX_N_F", "AC coupling to the FPGA"),
    r(S3, "4.7k", "CLK_RX_P_F", "VBIAS", "bias to VBIAS (FPGA side)"),
    r(S3, "4.7k", "CLK_RX_N_F", "VBIAS", "bias to VBIAS (FPGA side)"),
    r(S3, "220k", "+3V3", "CLK_RX_N_F", "offset: CLK_RX reads 0 when stopped")]
g += [c(S3, "100n", "B_P", "HS_RXD_P_F", "AC coupling to the FPGA"),
      c(S3, "100n", "B_N", "HS_RXD_N_F", "AC coupling to the FPGA"),
      r(S3, "4.7k", "HS_RXD_P_F", "VBIAS", "bias to VBIAS (FPGA side)"),
      r(S3, "4.7k", "HS_RXD_N_F", "VBIAS", "bias to VBIAS (FPGA side)"),
      r(S3, "220k", "+3V3", "HS_RXD_P_F", "offset: HS_RXD reads 1 (J) when idle / disabled"),
      r(S3, "16.5k", "+3V3", "VBIAS", "VBIAS top"), r(S3, "10k", "VBIAS", "GND", "VBIAS bottom: 1.245 V"),
      c(S3, "100n", "VBIAS")]
group(S3, "CLK_RX (Q2) -> CLK0_M2C, HS_RXD (B) -> LA00: LVPECL -> AC -> FPGA LVDS (VBIAS)", g)
g = pecl_out(S3, "CKM_P", "CKM_N") + [c(S3, "100n", "CKM_P", "CLK_MON", "AC coupling"),
                                      c(S3, "100n", "CKM_N", "CKM_NT", "AC coupling"),
                                      r(S3, "49.9", "CKM_NT", "GND", "dummy load (balance)"),
                                      sma("J4", S3, "SMA CLK_RX_MON", "CLK_MON", "CLK_RX monitor (50 Ohm scope)")]
group(S3, "CLK_RX monitor (Q3)", g)

# ===========================================================================
# sheet 4: VCO, prop driver ("charge pump"), fine / coarse tuning, CDR_CH_OUT
# ===========================================================================
g = [r(S4, "10", "+5V_A", "+5V_VCO", "+5V_A -> +5V_VCO filter (4.82 V)"), c(S4, "10u", "+5V_VCO"),
     c(S4, "100n", "+5V_VCO"), c(S4, "100p", "+5V_VCO")]
group(S4, "VCO supply", g)
ic("Q1", S4, "C513260", "BFR93AE6327HTSA1", "C513260", "Infineon", "BFR93A", note="Colpitts oscillator")
ic("Q2", S4, "C513260", "BFR93AE6327HTSA1", "C513260", "Infineon", "BFR93A", note="buffer, CE")
ic("Q3", S4, "C8545", "2N7002", "C8545", "CJ", note="VCO_OFF: base bias to GND")
ic("L1", S4, "C98083", "LQW18AN6N2C00D", "C98083", "Murata", "6.2nH 0.2nH", note="tank, wire-wound, Q ~ 40")
ic("D2", S4, "C2762669", "1SV305(TPH3,F)", "C2762669", "Toshiba", "1SV305", note="coarse varactor (CDR_V_IN_2)")
ic("D3", S4, "C2762669", "1SV305(TPH3,F)", "C2762669", "Toshiba", "1SV305",
   note="fine varactor: cathode = CDR_CH_OUT node F, anode = V_A")
con("Q1", C="VCO_C1", B="VCO_B1", E="VCO_E1"); con("Q2", C="VCO_C2", B="VCO_B2", E="VCO_E2")
con("Q3", G="VCO_OFF", S="GND", D="VCO_X")
con("L1", _1="VCO_T", _2="GND")
con("D2", A="GND", K="VCO_K"); con("D3", A="VA", K="CDR_F")
g = ["Q1", r(S4, "22", "+5V_VCO", "VCO_C1", "RC1 collector"), c(S4, "100p", "VCO_C1", note="collector RF ground"),
     c(S4, "10n", "VCO_C1"), r(S4, "4.7k", "+5V_VCO", "VCO_X", "RB1b"), r(S4, "4.7k", "VCO_X", "VCO_B1", "RB1a"),
     r(S4, "6.8k", "VCO_B1", "GND", "RB2"), "Q3", r(S4, "180", "VCO_E1", "GND", "RE1: ~ 9 mA"),
     c(S4, "10p", "VCO_B1", "VCO_E1", "C1 base-emitter (C0G)"), c(S4, "10p", "VCO_E1", "GND", "C2 emitter-GND (C0G)"),
     c(S4, "3.3p", "VCO_B1", "VCO_T", "C_cpl base - tank (C0G)"), "L1",
     c(S4, "0.3p", "VCO_T", "GND", "C_P tank trim (C0G)"),
     c(S4, "18p", "VCO_T", "VCO_K", "C_S coarse varactor series (C0G)"), "D2",
     r(S4, "2.2k", "VK", "VCO_K", "R_K coarse feed"),
     c(S4, "12p", "VCO_T", "CDR_F", "C_F fine varactor series (C0G)"), "D3"]
group(S4, "Colpitts VCO: BFR93A, 6.2 nH || 0.3 pF || (18 pF + 1SV305 coarse) || (12 pF + 1SV305 fine)", g)
ic("L2", S4, "C98076", "LQW18AN47NG00D", "C98076", "Murata", "47nH 2%",
   note="RF choke: prop node P -> fine varactor cathode F (SRF ~ 2.2 GHz)")
con("L2", _1="CDR_P", _2="CDR_F")
g = ["L2", r(S4, "62", "+5V_A", "CDR_P", "R_L: P = 4.0 V idle / 5.0 V UP / 2.9 V DN")]
for q, cc, b, e, nt in (("Q4", "CDR_P", "UP_N", "CP_EU", "UP pair: idle sinks 15 mA from P"),
                        ("Q5", "+5V_A", "UP_P", "CP_EU", "UP pair: UP steers the tail to +5V_A (P -> 5.0 V)"),
                        ("Q6", "CDR_P", "DN_P", "CP_ED", "DN pair: DN sinks a further 15 mA from P (P -> 2.9 V)"),
                        ("Q7", "+5V_A", "DN_N", "CP_ED", "DN pair: idle tail to +5V_A")):
    ic(q, S4, "C513260", "BFR93AE6327HTSA1", "C513260", "Infineon", "BFR93A", note=nt)
    con(q, C=cc, B=b + "_B", E=e)
    g += [q, r(S4, "47", b, b + "_B", "base stopper")]
g += [r(S4, "100", "CP_EU", "GND", "tail ~ 15 mA"), r(S4, "100", "CP_ED", "GND", "tail ~ 15 mA"),
     term(S4, "UP_P", "UP_N", "at the driver bases"), term(S4, "DN_P", "DN_N", "at the driver bases"),
     c(S4, "100n", "+5V_A"), c(S4, "10u", "+5V_A")]
group(S4, "Prop driver (model icp x R8): BFR93A current switches into R_L, 47 nH choke to node F", g)
g = [c(S4, "1.5p", "VCO_E1", "VCO_B2", "C_b2 coupling to the buffer (C0G)"), "Q2",
     r(S4, "10k", "+5V_VCO", "VCO_B2", "RB3"), r(S4, "4.7k", "VCO_B2", "GND", "RB4"),
     r(S4, "100", "VCO_E2", "GND", "RE2"), c(S4, "100p", "VCO_E2", note="RE2 bypass"),
     r(S4, "100", "+5V_VCO", "VCO_C2", "RC2 buffer load"),
     c(S4, "100p", "VCO_C2", "NB_IN", "to NB6L14 IN (sheet 3; 50 Ohm to VT inside)"),
     r(S4, "470", "VCO_C2", "VCO_MON", "VCO monitor tap (-20 dB into 50 Ohm)"),
     sma("J5", S4, "SMA VCO_MON", "VCO_MON", "VCO monitor")]
group(S4, "Buffer -> NB6L14; VCO monitor", g)
# tuning: DAC A = V_A (fine bias / frequency trim), DAC B = coarse (internal), SMA CDR_V_IN_2
ic("U12", S4, "C16040", "MCP4822-E/SN", "C16040", "Microchip",
   note="A: V_A trim, B: coarse (internal); 2.048 V ref, gain 2: 1 mV / LSB")
con("U12", VDD="+5V_A", **{"CS#": "DAC_CS_N", "LDAC#": "GND"}, SCK="SPI_SCK", SDI="SPI_SDI",
    VSS="GND", VOUTA="DAC_A", VOUTB="DAC_B")
ic("U13", S4, "C7377", "MCP6002T-I/SN", "C7377", "Microchip", note="A: V_A buffer, B: coarse buffer")
con("U13", OUTA="VA_BUF", **{"-INA": "VA_BUF", "+INA": "DAC_A", "-VSS": "GND", "+INB": "VK_SEL",
                             "-INB": "VK_BUF"}, OUTB="VK_BUF", VDD="+5V_A")
ic("U14", S4, "C49148", "TS5A23166DCUR", "C49148", "TI",
   note="coarse source: SW1 CSW_EXT (SMA CDR_V_IN_2), SW2 CSW_DAC (DAC B)")
con("U14", NO1="CVIN2", COM1="VK_SEL", IN1="CSW_EXT", NO2="DAC_B", COM2="VK_SEL", IN2="CSW_DAC",
    GND="GND", **{"V+": "+5V_A"})
g = ["U12", c(S4, "100n", "+5V_A"), "U13", c(S4, "100n", "+5V_A"),
     r(S4, "1k", "VA_BUF", "VA", "V_A feed"), c(S4, "100p", "VA", note="V_A RF bypass"),
     c(S4, "10n", "VA", note="V_A bypass"),
     sma("J6", S4, "SMA CDR_V_IN_2", "CVIN2_S", "coarse input from the PLL board J4 (CDR_CH_OUT_PLL), 0..4.5 V"),
     r(S4, "1k", "CVIN2_S", "CVIN2", "input protection"), r(S4, "100k", "CVIN2", "GND", "defined when open"),
     "U14", c(S4, "100n", "+5V_A"), r(S4, "100k", "VK_SEL", "GND", "defined with both switches open"),
     r(S4, "100", "VK_BUF", "VK", "coarse feed"), c(S4, "10n", "VK", note="coarse bypass")]
group(S4, "Tuning: V_A trim (DAC A), coarse = CDR_V_IN_2 (SMA) or DAC B, MCP6002 buffers", g)
ic("U15", S4, "C116490", "MCP6001T-I/OT", "C116490", "Microchip", note="CDR_CH_OUT buffer")
con("U15", VOUT="CH_BUF", VSS="GND", **{"VIN+": "CH_AVG", "VIN-": "CH_BUF"}, VDD="+5V_A")
ic("U16", S4, "C511293", "MCP3201-CI/SN", "C511293", "Microchip", note="CDR_CH_OUT ADC, 5.0 V reference")
con("U16", VREF="+5V_A", **{"IN+": "ADC_IN", "IN–": "GND", "CS#/SHDN": "ADC_CS_N"},
    VSS="GND", DOUT="ADC_SDO", CLK="SPI_SCK", VDD="+5V_A")
ic("J8", S4, "C124375", "Header 1x2 2.54mm", "C124375", "Ckmtw", note="test: CDR_CH_OUT (buffered) / GND")
con("J8", _1="CH_BUF", _2="GND")
g = [r(S4, "10k", "CDR_P", "CH_AVG", "averaging: tau 10 ns"), c(S4, "1n", "CH_AVG"), "U15", c(S4, "100n", "+5V_A"),
     r(S4, "100", "CH_BUF", "CH_SMA", "SMA series"),
     sma("J7", S4, "SMA CDR_CH_OUT", "CH_SMA", "CDR_CH_OUT monitor (averaged node P)"), "J8",
     r(S4, "1k", "CH_BUF", "ADC_IN", "ADC input filter"), c(S4, "1n", "ADC_IN"),
     "U16", c(S4, "100n", "+5V_A"), c(S4, "100n", "+5V_A")]
group(S4, "CDR_CH_OUT: node P averaged -> MCP6001 -> SMA / header / MCP3201", g)

TITLES = {S1: "FMC LPC, power (3.3 V ECL, 12 V -> 5 V analog), level translation, IPMI EEPROM",
          S2: "Data input CDR_DATA: SMA pair / FPGA LVDS pattern, MC100EP57 select",
          S3: "Alexander phase detector (MC100EP29 x 2, MC100EP08 x 2), NB6L14 fan-out, CLK_RX / HS_RXD",
          S4: "VCO (BFR93A Colpitts, coarse + fine 1SV305), prop driver, tuning DAC, CDR_CH_OUT ADC"}
