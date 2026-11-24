"""pll_parts.py - parts and connectivity of the discrete USB 2.0 PLL board
(imported by gen_schematic.py; keep in sync with sim/run_sims.py VAL and
doc/pll_board.md section 4)

PARTS[ref] = dict(sheet, sym (LCSC of the symbol), value, mpn, lcsc, mfr, note)
NETS[ref]  = {pin: net}; pins are symbol pin numbers, or pin names (resolved
             by gen_schematic.py against the cached symbol; a name must be
             unique in the symbol).
"""
import re

R0603, C0603 = "C25804", "C108079"          # symbols used for all 0603 R / C
RES = {  # value -> (MPN, LCSC)   UNI-ROYAL 0603 1 %
    "10": ("0603WAF100JT5E", "C22859"), "22": ("0603WAF220JT5E", "C23345"),
    "33": ("0603WAF330JT5E", "C23140"), "49.9": ("0603WAF499JT5E", "C23185"),
    "51": ("0603WAF510JT5E", "C23197"), "100": ("0603WAF1000T5E", "C22775"),
    "150": ("0603WAF1500T5E", "C22808"), "220": ("0603WAF2200T5E", "C22962"),
    "270": ("0603WAF2700T5E", "C22966"), "470": ("0603WAF4700T5E", "C23179"),
    "1k": ("0603WAF1001T5E", "C21190"), "2k": ("0603WAF2001T5E", "C22975"),
    "2.2k": ("0603WAF2201T5E", "C4190"), "4.7k": ("0603WAF4701T5E", "C23162"),
    "5.1k": ("0603WAF5101T5E", "C23186"), "6.8k": ("0603WAF6801T5E", "C23212"),
    "10k": ("0603WAF1002T5E", "C25804"), "16.5k": ("0603WAF1652T5E", "C22812"),
    "32.4k": ("0603WAF3242T5E", "C13187"), "60.4k": ("0603WAF6042T5E", "C23089"),
    "100k": ("0603WAF1003T5E", "C25803"), "220k": ("0603WAF2203T5E", "C22961"),
}
CAP = {  # value -> (MPN, LCSC, manufacturer)
    "100n": ("CC0603KRX7R7BB104", "C108079", "YAGEO"),
    "10u": ("CL10A106KP8NNNC", "C19702", "Samsung"),          # 10 V: 3.3 / 5 V rails only
    "2.2u": ("CL10A225KA8NNNC", "C57895", "Samsung"),         # 25 V: 12 V rail
    "1u": ("CL10A105KB8NNNC", "C15849", "Samsung"),
    "10n": ("CL10B103KB8NNNC", "C1589", "Samsung"),
    "1n": ("0603CG102J500NT", "C1636", "FH"),
    "1.5n": ("0603CG152J500NT", "C880279", "FH"),
    "100p": ("0603CG101J500NT", "C1635", "FH"),
    "16p": ("0603CG160J500NT", "C1646", "FH"),
    "15p": ("0603CG150J500NT", "C91703", "FH"),
    "10p": ("0603CG100J500NT", "C91367", "FH"),
    "3.3p": ("0603CG3R3C500NT", "C1660", "FH"),
    "1.5p": ("0603CG1R5C500NT", "C1639", "FH"),
}

PARTS = {}
DNP = set()
S1, S2, S3, S4 = "1_FMC_POWER_IO", "2_REFERENCE", "3_PFD_CP_LOOP_FILTER", "4_VCO_CLOCK_OUT"


def ic(ref, sheet, sym, mpn, lcsc, mfr, value=None, note=""):
    PARTS[ref] = dict(sheet=sheet, sym=sym, value=value or mpn, mpn=mpn, lcsc=lcsc, mfr=mfr, note=note)


def r(ref, sheet, val, note=""):
    mpn, lc = RES[val]
    PARTS[ref] = dict(sheet=sheet, sym=R0603, value=val if val[-1] in "kM" else val + "R",
                      mpn=mpn, lcsc=lc, mfr="UNI-ROYAL", note=note)


def c(ref, sheet, val, note=""):
    mpn, lc, mf = CAP[val]
    PARTS[ref] = dict(sheet=sheet, sym=C0603, value=val + "F", mpn=mpn, lcsc=lc, mfr=mf, note=note)


NETS = {}


def con(ref, **pins):
    NETS.setdefault(ref, {}).update({k.lstrip("_"): v for k, v in pins.items()})


def two(ref, a, b):
    NETS[ref] = {"1": a, "2": b}


# ===========================================================================
# sheet 1: FMC, power, level translation, IPMI EEPROM
# ===========================================================================
ic("J1", S1, "C5366873", "ASP-134604-01", "", "Samtec", "FMC LPC mezzanine",
   note="order from Samtec / Mouser; LCSC symbol C5366873")
ic("FB1", S1, "C80165", "BLM18PG221SN1D", "C80165", "Murata", "220R@100MHz", note="FMC 3P3V -> +3V3")
ic("FB2", S1, "C80165", "BLM18PG221SN1D", "C80165", "Murata", "220R@100MHz", note="FMC 12P0V -> +12V_F")
c("C1", S1, "10u"); c("C2", S1, "100n"); c("C3", S1, "2.2u", note="12 V input")
c("C4", S1, "10u"); c("C5", S1, "100n"); c("C6", S1, "100n", note="3P3VAUX")
ic("U1", S1, "C6203", "AT24C02C-SSHM-T", "C6203", "Microchip", note="FRU EEPROM (VITA 57.1 IPMI)")
ic("U2", S1, "C16430", "TPS7A4901DGNR", "C16430", "TI", note="+12V_F -> +5V_A, 15 uVrms, Vout = 1.185 V x (1 + R1/R2)")
r("R1", S1, "32.4k", note="TPS7A4901 FB top: 5.02 V"); r("R2", S1, "10k", note="TPS7A4901 FB bottom")
c("C7", S1, "10n", note="NR/SS: noise filter / soft start")
c("C8", S1, "10u", note="+5V_A output (TPS7A4901 needs >= 2.2 uF)"); c("C9", S1, "100n")
ic("U3", S1, "C475492", "LP5907MFX-3.0/NOPB", "C475492", "TI", note="+5V_A -> +3V0 (ADF4002 AVDD / DVDD)")
c("C10", S1, "1u"); c("C11", S1, "1u"); c("C12", S1, "100n")
ic("U4", S1, "C27643", "SN74LVC8T245PWR", "C27643", "TI", note="VADJ -> +5V_A controls")
ic("U5", S1, "C27643", "SN74LVC8T245PWR", "C27643", "TI", note="VADJ -> +3V3 reference controls")
c("C13", S1, "100n"); c("C14", S1, "100n"); c("C15", S1, "100n"); c("C16", S1, "100n")
ic("U6", S1, "C7843", "SN74LVC1T45DBVR", "C7843", "TI", note="MUXOUT +3V0 -> VADJ")
ic("U7", S1, "C7843", "SN74LVC1T45DBVR", "C7843", "TI", note="ADC DOUT +5V_A -> VADJ")
c("C17", S1, "100n"); c("C18", S1, "100n"); c("C19", S1, "100n"); c("C20", S1, "100n")
r("R3", S1, "100k", note="VCO_OFF high (VCO off) while VADJ is down")
r("R4", S1, "100k", note="LF_DIS high (filter discharged) while VADJ is down")
r("R5", S1, "100k", note="CDCM_OFF high (outputs off) while VADJ is down")
r("R6", S1, "100k", note="OL_EN low while VADJ is down")
r("R7", S1, "100k", note="DAC CS# high"); r("R8", S1, "100k", note="ADC CS# high")
r("R9", S1, "100k", note="ADF CE low (PLL off) while the FPGA is unconfigured")
r("R10", S1, "33", note="ADF CLK series"); r("R11", S1, "33", note="ADF DATA series")
r("R12", S1, "33", note="ADF LE series")
ic("D2", S1, "C12624", "KT-0603G", "C12624", "KENTO", "green LED", note="+3V3 power")
r("R13", S1, "1k")

fmc = {
    "H4": "CLK_BIT_A_P_F", "H5": "CLK_BIT_A_N_F", "G2": "CLK60_A_P_F", "G3": "CLK60_A_N_F",
    "G6": "REF_DIG_F", "G7": "MUXOUT_F", "D8": "ADF_CLK_F", "D9": "ADF_DATA_F",
    "H7": "ADF_LE_F", "H8": "ADF_CE", "G9": "VCO_OFF_F", "G10": "LF_DIS_F",
    "H10": "OL_EN_F", "H11": "CDCM_OFF_F", "D11": "DAC_CS_N_F", "D12": "ADC_CS_N_F",
    "C10": "SPI_SCK_F", "C11": "SPI_SDI_F", "H13": "ADC_SDO_F", "H14": "REFSRC0_F",
    "G12": "REFSRC1_F", "G13": "OE24_F", "D14": "OE19_F",
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

two("FB1", "P3V3_FMC", "+3V3"); two("FB2", "P12V_FMC", "+12V_F")
two("C1", "+3V3", "GND"); two("C2", "+3V3", "GND"); two("C3", "+12V_F", "GND")
two("C4", "VADJ", "GND"); two("C5", "VADJ", "GND"); two("C6", "P3V3AUX", "GND")
con("U1", A0="FMC_GA0", A1="FMC_GA1", A2="GND", GND="GND", SDA="FMC_SDA", SCL="FMC_SCL",
    WP="GND", VCC="P3V3AUX")
con("U2", IN="+12V_F", EN="+12V_F", OUT="+5V_A", FB="LDO5_FB", **{"NR/SS": "LDO5_NR"},
    GND="GND", PwPd="GND")
two("R1", "+5V_A", "LDO5_FB"); two("R2", "LDO5_FB", "GND"); two("C7", "LDO5_NR", "GND")
two("C8", "+5V_A", "GND"); two("C9", "+5V_A", "GND")
con("U3", IN="+5V_A", GND="GND", EN="+5V_A", OUT="+3V0")
two("C10", "+5V_A", "GND"); two("C11", "+3V0", "GND"); two("C12", "+3V0", "GND")
# U4: A = VADJ, B = +5V_A, DIR = H (A -> B), OE# = GND
con("U4", _1="VADJ", _2="VADJ", _3="VCO_OFF_F", _4="LF_DIS_F", _5="OL_EN_F", _6="CDCM_OFF_F",
    _7="DAC_CS_N_F", _8="ADC_CS_N_F", _9="SPI_SCK_F", _10="SPI_SDI_F",
    _11="GND", _12="GND", _13="GND",
    _21="VCO_OFF", _20="LF_DIS", _19="OL_EN", _18="CDCM_OFF", _17="DAC_CS_N", _16="ADC_CS_N",
    _15="SPI_SCK", _14="SPI_SDI", _22="GND", _23="+5V_A", _24="+5V_A")
# U5: A = VADJ, B = +3V3; A5..A8 unused (GND)
con("U5", _1="VADJ", _2="VADJ", _3="REFSRC0_F", _4="REFSRC1_F", _5="OE24_F", _6="OE19_F",
    _7="GND", _8="GND", _9="GND", _10="GND", _11="GND", _12="GND", _13="GND",
    _21="REFSRC0", _20="REFSRC1", _19="OE24", _18="OE19", _22="GND", _23="+3V3", _24="+3V3")
two("C13", "VADJ", "GND"); two("C14", "+5V_A", "GND"); two("C15", "VADJ", "GND"); two("C16", "+3V3", "GND")
con("U6", VCCA="VADJ", GND="GND", A="MUXOUT_F", B="MUXOUT", DIR="GND", VCCB="+3V0")
con("U7", VCCA="VADJ", GND="GND", A="ADC_SDO_F", B="ADC_SDO", DIR="GND", VCCB="+5V_A")
two("C17", "VADJ", "GND"); two("C18", "+3V0", "GND"); two("C19", "VADJ", "GND"); two("C20", "+5V_A", "GND")
two("R3", "+5V_A", "VCO_OFF"); two("R4", "+5V_A", "LF_DIS"); two("R5", "+5V_A", "CDCM_OFF")
two("R6", "OL_EN", "GND"); two("R7", "+5V_A", "DAC_CS_N"); two("R8", "+5V_A", "ADC_CS_N")
two("R9", "ADF_CE", "GND")
two("R10", "ADF_CLK_F", "ADF_CLK"); two("R11", "ADF_DATA_F", "ADF_DATA"); two("R12", "ADF_LE_F", "ADF_LE")
two("R13", "+3V3", "LED_A"); con("D2", K="GND", A="LED_A")

# ===========================================================================
# sheet 2: reference (CDR_FREF), REF_DIG
# ===========================================================================
ic("Y1", S2, "C160455", "HSO321S 24MHZ 3.3V", "C160455", "HUAXIN", "24 MHz", note="CMOS XO, +-50 ppm, OE")
ic("Y2", S2, "C2831371", "OT201619.2MJBA4SL", "C2831371", "YXC", "19.2 MHz", note="CMOS XO, +-20 ppm, tri-state")
c("C21", S2, "100n"); c("C22", S2, "100n")
ic("J2", S2, "C496549", "BWSMA-KE-Z001", "C496549", "BAT WIRELESS", "SMA REF_EXT",
   note="external reference (26 MHz, generator); 1..3.3 Vpp")
r("R14", S2, "49.9", note="50 Ohm termination"); c("C23", S2, "100n")
r("R15", S2, "10k", note="bias VDD/2"); r("R16", S2, "10k", note="bias VDD/2")
ic("U8", S2, "C135822", "74LVC1G157GW,125", "C135822", "Nexperia", note="I0 24 MHz / I1 19.2 MHz")
ic("U9", S2, "C135822", "74LVC1G157GW,125", "C135822", "Nexperia", note="I0 on-board / I1 SMA -> CDR_FREF")
c("C24", S2, "100n"); c("C25", S2, "100n")
r("R17", S2, "33", note="REFIN series"); c("C26", S2, "100n", note="REFIN AC coupling (ADF4002 self-bias)")
ic("U10", S2, "C840096", "SN74LVC1G34DBVR", "C840096", "TI", note="REF_DIG buffer at VADJ")
c("C27", S2, "100n"); r("R18", S2, "33", note="REF_DIG series")
ic("J3", S2, "C124375", "Header 1x2 2.54mm", "C124375", "Ckmtw", note="test: CDR_FREF")

con("Y1", OE="OE24", GND="GND", OUT="OSC24", VCC="+3V3")
con("Y2", **{"Tri-State": "OE19"}, GND="GND", OUTPUT="OSC19", VDD="+3V3")
two("C21", "+3V3", "GND"); two("C22", "+3V3", "GND")
con("J2", _5="REF_EXT", _1="GND", _2="GND", _3="GND", _4="GND")
two("R14", "REF_EXT", "GND"); two("C23", "REF_EXT", "REF_EXT_B")
two("R15", "+3V3", "REF_EXT_B"); two("R16", "REF_EXT_B", "GND")
con("U8", I0="OSC24", I1="OSC19", S="REFSRC0", Y="REF_INT", VCC="+3V3", GND="GND")
con("U9", I0="REF_INT", I1="REF_EXT_B", S="REFSRC1", Y="CDR_FREF", VCC="+3V3", GND="GND")
two("C24", "+3V3", "GND"); two("C25", "+3V3", "GND")
two("R17", "CDR_FREF", "REFIN_S"); two("C26", "REFIN_S", "REFIN")
con("U10", NC="GND", A="CDR_FREF", GND="GND", Y="REF_DIG", VCC="VADJ")
two("C27", "VADJ", "GND"); two("R18", "REF_DIG", "REF_DIG_F")
con("J3", _1="CDR_FREF", _2="GND")

# ===========================================================================
# sheet 3: ADF4002 PFD / charge pump, loop filter, switches, DAC, ADC, buffer
# ===========================================================================
ic("U11", S3, "C578975", "ADF4002BCPZ-RL7", "C578975", "ADI",
   note="PFD + CP + R / N counters; RF in = CDCM1804 Y1 (VCO / 2)")
r("R19", S3, "5.1k", note="RSET: ICP max 5 mA")
ic("U17", S3, "C475492", "LP5907MFX-4.5/NOPB", "C529554", "TI",
   note="VP = 4.5 V: CP compliance caps VTUNE at ~4.4 V, so 26 MHz x 20 = 520 MHz cannot lock")
c("C70", S3, "1u", note="U17 input")
c("C28", S3, "1u"); c("C29", S3, "100n"); c("C30", S3, "100n"); c("C31", S3, "100n")
c("C32", S3, "10n"); c("C33", S3, "100p", note="RFINB decoupling (datasheet: 100 pF)")
c("C34", S3, "15p", note="C4 loop filter shunt (C0G)")
r("R21", S3, "2.2k", note="R2 loop filter")
c("C35", S3, "1.5n", note="C3 loop filter (C0G)")
ic("U12", S3, "C49148", "TS5A23166DCUR", "C49148", "TI",
   note="SW1 LF_DIS (discharge), SW2 OL_EN (DAC -> VTUNE)")
r("R22", S3, "100", note="discharge"); r("R23", S3, "1k", note="DAC injection")
c("C36", S3, "100n")
ic("U13", S3, "C36865", "MCP4821-E/SN", "C36865", "Microchip", note="open-loop tuning DAC, 1 mV / LSB, 0..4.095 V")
c("C37", S3, "100n")
ic("U14", S3, "C116490", "MCP6001T-I/OT", "C116490", "Microchip", note="VTUNE buffer, 1 pA bias")
c("C38", S3, "100n")
r("R24", S3, "100", note="CDR_CH_OUT_PLL series")
r("R25", S3, "1k", note="ADC input filter"); c("C39", S3, "1n")
ic("U15", S3, "C511293", "MCP3201-CI/SN", "C511293", "Microchip", note="VTUNE ADC, 5.0 V reference")
c("C40", S3, "100n"); c("C41", S3, "100n")
ic("J4", S3, "C496549", "BWSMA-KE-Z001", "C496549", "BAT WIRELESS", "SMA CDR_CH_OUT_PLL",
   note="control voltage (buffered) to the CDR board's CDR_V_IN_2")
ic("J5", S3, "C124375", "Header 1x2 2.54mm", "C124375", "Ckmtw", note="test: VTUNE (buffered) / GND")

con("U11", CPGND="GND", _2="GND", _3="GND", RFINB="RFINB", RFINA="RFINA", _6="+3V0", _7="+3V0",
    REFIN="REFIN", _9="GND", _10="GND", CE="ADF_CE", CLOCK="ADF_CLK", DATA="ADF_DATA",
    LE="ADF_LE", MUXOUT="MUXOUT", _16="+3V0", _17="+3V0", VP="VP", RSET="RSET", CP="VTUNE", EP="GND")
two("R19", "RSET", "GND")
con("U17", IN="+5V_A", GND="GND", EN="+5V_A", OUT="VP"); two("C70", "+5V_A", "GND")
two("C28", "VP", "GND"); two("C29", "VP", "GND"); two("C30", "+3V0", "GND"); two("C31", "+3V0", "GND")
two("C32", "+3V0", "GND"); two("C33", "RFINB", "GND")
two("C34", "VTUNE", "GND"); two("R21", "VTUNE", "LF_Z"); two("C35", "LF_Z", "GND")
con("U12", NO1="DIS_R", COM1="VTUNE", IN1="LF_DIS", NO2="DAC_INJ", COM2="VTUNE", IN2="OL_EN",
    GND="GND", **{"V+": "+5V_A"})
two("R22", "DIS_R", "GND"); two("R23", "DAC_OUT", "DAC_INJ"); two("C36", "+5V_A", "GND")
con("U13", VDD="+5V_A", **{"CS#": "DAC_CS_N", "LDAC#": "GND", "SHDN#": "+5V_A"}, SCK="SPI_SCK",
    SDI="SPI_SDI", VSS="GND", VOUT="DAC_OUT")
two("C37", "+5V_A", "GND")
con("U14", VOUT="VT_BUF", VSS="GND", **{"VIN+": "VTUNE", "VIN-": "VT_BUF"}, VDD="+5V_A")
two("C38", "+5V_A", "GND")
two("R24", "VT_BUF", "CDR_CH_OUT_PLL"); two("R25", "VT_BUF", "ADC_IN"); two("C39", "ADC_IN", "GND")
con("U15", VREF="+5V_A", **{"IN+": "ADC_IN", "IN–": "GND", "CS#/SHDN": "ADC_CS_N"},
    VSS="GND", DOUT="ADC_SDO", CLK="SPI_SCK", VDD="+5V_A")
two("C40", "+5V_A", "GND"); two("C41", "+5V_A", "GND")
con("J4", _5="CDR_CH_OUT_PLL", _1="GND", _2="GND", _3="GND", _4="GND")
con("J5", _1="VT_BUF", _2="GND")

# ===========================================================================
# sheet 4: VCO, CDCM1804 dividers / fan-out, outputs
# ===========================================================================
r("R26", S4, "10", note="+5V_A -> +5V_VCO filter"); c("C42", S4, "10u"); c("C43", S4, "100n")
c("C44", S4, "100p")
ic("Q3", S4, "C513260", "BFR93AE6327HTSA1", "C513260", "Infineon", "BFR93A", note="Colpitts oscillator")
ic("Q4", S4, "C513260", "BFR93AE6327HTSA1", "C513260", "Infineon", "BFR93A", note="buffer, CE")
ic("Q5", S4, "C8545", "2N7002", "C8545", "CJ", note="VCO_OFF: base bias to GND")
ic("L1", S4, "C86131", "LQW18AN10NG00D", "C86131", "Murata", "10nH 2%", note="tank, wire-wound, Q ~ 50")
ic("D1", S4, "C2762669", "1SV305(TPH3,F)", "C2762669", "Toshiba", "1SV305", note="varactor C1V 18.3 pF / C4V 6.1 pF")
r("R27", S4, "22", note="RC1 collector"); c("C45", S4, "100p", note="collector RF ground")
c("C46", S4, "10n")
r("R28", S4, "4.7k", note="RB1b"); r("R29", S4, "4.7k", note="RB1a"); r("R30", S4, "6.8k", note="RB2")
r("R31", S4, "270", note="RE1: ~5.6 mA")
c("C47", S4, "10p", note="C1 base-emitter (C0G)"); c("C48", S4, "10p", note="C2 emitter-GND (C0G)")
c("C49", S4, "3.3p", note="C_cpl base - tank (C0G)"); c("C50", S4, "1.5p", note="C_P tank (C0G)")
c("C51", S4, "16p", note="C_S varactor series (C0G)")
r("R32", S4, "2.2k", note="R_K varactor feed")
c("C52", S4, "1.5p", note="C_b2 coupling to the buffer (C0G)")
r("R33", S4, "10k", note="RB3"); r("R34", S4, "4.7k", note="RB4")
r("R35", S4, "100", note="RE2"); c("C53", S4, "100p", note="RE2 bypass")
r("R36", S4, "220", note="RC2 buffer load")
c("C54", S4, "100p", note="to CDCM1804 IN"); r("R37", S4, "2k", note="IN bias to VBB")
r("R38", S4, "470", note="VCO monitor tap (-20 dB into 50 Ohm)")
ic("J6", S4, "C496549", "BWSMA-KE-Z001", "C496549", "BAT WIRELESS", "SMA VCO_MON", note="VCO monitor")
ic("U16", S4, "C914121", "CDCM1804RGER", "C914121", "TI",
   note="mode 40: Y0 /1, Y1 /2, Y2 /8, Y3 /8 (EN = S2 = S1 = VDD/2, S0 = 0)")
r("R39", S4, "60.4k", note="EN = VDD/2"); r("R40", S4, "60.4k", note="S2 = VDD/2")
r("R41", S4, "60.4k", note="S1 = VDD/2")
ic("Q6", S4, "C8545", "2N7002", "C8545", "CJ", note="CDCM_OFF: EN -> 0 (outputs high-Z)")
for ref in ("C55", "C56", "C57", "C58", "C59", "C60"):
    c(ref, S4, "100n")
c("C61", S4, "10u"); c("C62", S4, "10n", note="VBB")
for ref in ("R42", "R43", "R44", "R45", "R46", "R47"):
    r(ref, S4, "150", note="LVPECL emitter pull-down")
for ref in ("C63", "C64", "C65", "C66"):
    c(ref, S4, "100n", note="AC coupling to the FPGA")
for ref in ("R48", "R49", "R50", "R51"):
    r(ref, S4, "4.7k", note="bias to VBIAS (FPGA side)")
r("R52", S4, "220k", note="offset: CLK_BIT_A reads 0 when stopped")
r("R53", S4, "220k", note="offset: CLK60_A reads 0 when stopped")
r("R54", S4, "16.5k", note="VBIAS top"); r("R55", S4, "10k", note="VBIAS bottom: 1.245 V")
c("C67", S4, "100n")
c("C68", S4, "100p", note="Y1 AC coupling"); r("R56", S4, "100", note="RF attenuator series")
r("R57", S4, "51", note="RF attenuator shunt: ~ -7 dBm at RFINA"); c("C69", S4, "100p", note="RFINA coupling")
r("R58", S4, "33", note="Y3 series"); ic("J7", S4, "C496549", "BWSMA-KE-Z001", "C496549", "BAT WIRELESS",
                                         "SMA CLK60_MON", note="CLK60 LVCMOS monitor")

two("R26", "+5V_A", "+5V_VCO"); two("C42", "+5V_VCO", "GND"); two("C43", "+5V_VCO", "GND")
two("C44", "+5V_VCO", "GND")
con("Q3", C="VCO_C1", B="VCO_B1", E="VCO_E1")
con("Q4", C="VCO_C2", B="VCO_B2", E="VCO_E2")
con("Q5", G="VCO_OFF", S="GND", D="VCO_X")
two("L1", "VCO_T", "GND")
con("D1", A="GND", K="VCO_K")
two("R27", "+5V_VCO", "VCO_C1"); two("C45", "VCO_C1", "GND"); two("C46", "VCO_C1", "GND")
two("R28", "+5V_VCO", "VCO_X"); two("R29", "VCO_X", "VCO_B1"); two("R30", "VCO_B1", "GND")
two("R31", "VCO_E1", "GND"); two("C47", "VCO_B1", "VCO_E1"); two("C48", "VCO_E1", "GND")
two("C49", "VCO_B1", "VCO_T"); two("C50", "VCO_T", "GND"); two("C51", "VCO_T", "VCO_K")
two("R32", "VTUNE", "VCO_K")
two("C52", "VCO_E1", "VCO_B2"); two("R33", "+5V_VCO", "VCO_B2"); two("R34", "VCO_B2", "GND")
two("R35", "VCO_E2", "GND"); two("C53", "VCO_E2", "GND"); two("R36", "+5V_VCO", "VCO_C2")
two("C54", "VCO_C2", "CDCM_IN"); two("R37", "CDCM_IN", "CDCM_VBB")
two("R38", "VCO_C2", "VCO_MON")
con("J6", _5="VCO_MON", _1="GND", _2="GND", _3="GND", _4="GND")
con("U16", EN="CDCM_EN", _2="+3V3", IN="CDCM_IN", **{"IN#": "CDCM_VBB", "Y0#": "Y0_N",
                                                      "Y1#": "Y1_N", "Y2#": "Y2_N"},
    _5="+3V3", VBB="CDCM_VBB", _7="GND", _8="+3V3", Y2="Y2_P", _11="+3V3", Y3="Y3",
    VDD3="+3V3", _14="+3V3", Y1="Y1_P", _17="+3V3", S0="GND", S1="CDCM_S1", _20="+3V3",
    Y0="Y0_P", _23="+3V3", S2="CDCM_S2", _25="GND")
two("R39", "CDCM_EN", "GND"); two("R40", "CDCM_S2", "GND"); two("R41", "CDCM_S1", "GND")
con("Q6", G="CDCM_OFF", S="GND", D="CDCM_EN")
for ref in ("C55", "C56", "C57", "C58", "C59", "C60"):
    two(ref, "+3V3", "GND")
two("C61", "+3V3", "GND"); two("C62", "CDCM_VBB", "GND")
two("R42", "Y0_P", "GND"); two("R43", "Y0_N", "GND"); two("R44", "Y2_P", "GND"); two("R45", "Y2_N", "GND")
two("R46", "Y1_P", "GND"); two("R47", "Y1_N", "GND")
two("C63", "Y0_P", "CLK_BIT_A_P_F"); two("C64", "Y0_N", "CLK_BIT_A_N_F")
two("C65", "Y2_P", "CLK60_A_P_F"); two("C66", "Y2_N", "CLK60_A_N_F")
two("R48", "CLK_BIT_A_P_F", "VBIAS"); two("R49", "CLK_BIT_A_N_F", "VBIAS")
two("R50", "CLK60_A_P_F", "VBIAS"); two("R51", "CLK60_A_N_F", "VBIAS")
two("R52", "+3V3", "CLK_BIT_A_N_F"); two("R53", "+3V3", "CLK60_A_N_F")
two("R54", "+3V3", "VBIAS"); two("R55", "VBIAS", "GND"); two("C67", "VBIAS", "GND")
two("C68", "Y1_P", "RF_ATT"); two("R56", "RF_ATT", "RF_IN"); two("R57", "RF_IN", "GND")
two("C69", "RF_IN", "RFINA")
two("R58", "Y3", "CLK60_MON"); con("J7", _5="CLK60_MON", _1="GND", _2="GND", _3="GND", _4="GND")

# ---------------------------------------------------------------------------
TITLES = {S1: "FMC LPC, power (12 V -> 5 V / 3.0 V), level translation, IPMI EEPROM",
          S2: "Reference CDR_FREF: 24 / 19.2 MHz oscillators, SMA input, muxes, REF_DIG",
          S3: "ADF4002 PFD / charge pump, loop filter C4 || (R2 + C3), PLL_EN / open-loop switches, DAC, ADC",
          S4: "VCO (BFR93A Colpitts, 1SV305), CDCM1804 /1 /2 /8, CLK_BIT_A / CLK60_A outputs"}

GROUPS = {
    S1: [("J1  FMC LPC (VITA 57.1) - CLK0/1_M2C, LA pins, power, IPMI", ["J1"]),
         ("Power: 3P3V -> +3V3, 12P0V -> TPS7A4901 -> +5V_A -> LP5907 -> +3V0",
          ["FB1", "FB2", "C1", "C2", "C3", "C4", "C5", "U2", "R1", "R2", "C7", "C8", "C9",
           "U3", "C10", "C11", "C12"]),
         ("FRU EEPROM (IPMI)", ["U1", "C6"]),
         ("Controls VADJ -> +5V_A (PLL_EN fan-out, SPI)", ["U4", "C13", "C14", "R3", "R4", "R5", "R6",
                                                           "R7", "R8"]),
         ("Controls VADJ -> +3V3 (reference select)", ["U5", "C15", "C16"]),
         ("MUXOUT / ADC DOUT -> VADJ", ["U6", "C17", "C18", "U7", "C19", "C20"]),
         ("ADF4002 3-wire bus (VADJ logic, VIH 1.4 V), CE", ["R9", "R10", "R11", "R12"]),
         ("Power LED", ["R13", "D2"])],
    S2: [("Oscillators: 24 MHz (REFSEL 01), 19.2 MHz (REFSEL 00)", ["Y1", "C21", "Y2", "C22"]),
         ("SMA reference input (26 MHz / generator)", ["J2", "R14", "C23", "R15", "R16"]),
         ("Reference select -> CDR_FREF", ["U8", "C24", "U9", "C25", "J3"]),
         ("CDR_FREF -> ADF4002 REFIN; REF_DIG at VADJ", ["R17", "C26", "U10", "C27", "R18"])],
    S3: [("ADF4002: R / N counters, PFD, charge pump (VP = 4.5 V, U17)",
          ["U11", "R19", "U17", "C70", "C28", "C29", "C30", "C31", "C32", "C33"]),
         ("Loop filter on VTUNE (= CDR_CH_OUT_PLL): C4 15 pF || (R2 2.2k + C3 1.5 nF)",
          ["C34", "R21", "C35"]),
         ("PLL_EN discharge / open-loop injection", ["U12", "R22", "R23", "C36", "U13", "C37"]),
         ("VTUNE buffer -> CDR_CH_OUT_PLL (SMA), ADC", ["U14", "C38", "R24", "J4", "J5", "R25", "C39",
                                                       "U15", "C40", "C41"])],
    S4: [("VCO supply", ["R26", "C42", "C43", "C44"]),
         ("Colpitts VCO: BFR93A, 10 nH || 1.5 pF || (16 pF + 1SV305), tuning via R_K",
          ["Q3", "R27", "C45", "C46", "R28", "R29", "R30", "Q5", "R31", "C47", "C48", "C49", "L1",
           "C50", "C51", "D1", "R32"]),
         ("Buffer -> CDCM1804 IN; VCO monitor", ["C52", "Q4", "R33", "R34", "R35", "C53", "R36", "C54",
                                                 "R37", "R38", "J6"]),
         ("CDCM1804 mode 40, CDCM_OFF", ["U16", "R39", "R40", "R41", "Q6", "C55", "C56", "C57", "C58",
                                         "C59", "C60", "C61", "C62"]),
         ("CLK_BIT_A (Y0) / CLK60_A (Y2): LVPECL -> AC -> FPGA LVDS (VBIAS)",
          ["R42", "R43", "C63", "C64", "R48", "R49", "R52", "R44", "R45", "C65", "C66", "R50", "R51",
           "R53", "R54", "R55", "C67"]),
         ("Y1 (VCO / 2) -> ADF4002 RFINA (-7 dBm); Y3 monitor",
          ["R46", "R47", "C68", "R56", "R57", "C69", "R58", "J7"])],
}
