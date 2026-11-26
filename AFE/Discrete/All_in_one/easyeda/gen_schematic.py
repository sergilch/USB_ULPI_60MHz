#!/usr/bin/env python3
"""gen_schematic.py - EasyEDA Std schematic of the all-in-one discrete USB 2.0 AFE board

    python3 gen_schematic.py   -> usb_aio_board_sch.json  (EasyEDA Std project source, 17 sheets)
                                  netlist.csv             (ref, pin, pin name, net, sheet, block)
                                  fmc_pinmap.csv          (FMC LPC pin, LA signal, net, block, old pin)
                                  ../bom/aio_board_bom.csv, ../bom/aio_board_bom_jlcpcb.csv

One FMC LPC mezzanine with the four prototype boards of AFE/Discrete as
blocks, and one USB Type-C receptacle for both transmitter and receiver:

    TX  ../../Transmitter/easyeda/gen_schematic.py   designators +100  (R7 -> R107)
    RX  ../../Receiver/easyeda/gen_schematic.py      designators +200
    PLL ../../PLL/easyeda/pll_parts.py               designators +300
    CDR ../../CDR/easyeda/cdr_parts.py               designators +400
    common sheet 0: FMC connector J1, FRU EEPROM U1, power LED (taken from TX)

The parts and connectivity of each block are imported from the block's own
generator, so a change there is picked up here.  This file only holds the
integration: parts that the merged board no longer needs (REMOVE, checked
against the MPN, so a renumbering in a block fails loudly), the merged FMC
pin map (FMC), the nets that join blocks (LINK), pin edits (EDIT) and new
parts (ADD).  The block nets that are not joined keep their names when only
one block uses them, otherwise they get the block tag (+3V3 -> +3V3_TX,
VBIAS -> CDR_VBIAS).  Same drawing engine as the block generators (every
part unrotated, each connected pin gets a short wire stub and a net label;
net labels connect across sheets).

Symbols and footprints: JLCEDA/EasyEDA Official Library (https://lceda.cn/,
https://easyeda.com), read from the block lib/ caches.  The copyright of the
library data belongs to JLCEDA/EasyEDA; every sheet carries this source note.

Open in EasyEDA Std (desktop or web): new schematic > Design > "File Source"
(toolbar "<>" icon) > replace the text > "Create New Document".
"""
import csv
import importlib.util
import json
import os
import re
import sys

sys.dont_write_bytecode = True                 # no __pycache__ in the block directories
HERE = os.path.dirname(os.path.abspath(__file__))
DISC = os.path.dirname(os.path.dirname(HERE))                 # AFE/Discrete
BOMDIR = os.path.join(HERE, "..", "bom")
SOURCE_NOTE = ("Symbols / footprints: JLCEDA/EasyEDA Official Library - "
               "https://lceda.cn/ - https://easyeda.com")
BOARD = "USB 2.0 discrete AFE all-in-one board (TX + RX + PLL + CDR) - FMC LPC"
LIBS = [os.path.join(HERE, "lib")] + [os.path.join(DISC, d, "easyeda", "lib")
                                      for d in ("Transmitter", "Receiver", "PLL", "CDR")]
# (LCSC, pin number, pin name) -> corrected pin number (from PLL/easyeda/gen_schematic.py)
PIN_FIX = {("C914121", "24", "VSS"): "25"}


def _module(name, path):
    d = os.path.dirname(path)
    sys.path.insert(0, d)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        sys.path.remove(d)
    return m


#        tag    directory      source                         designator offset
BLOCKS = [("TX", "Transmitter", "easyeda/gen_schematic.py", 100),
          ("RX", "Receiver", "easyeda/gen_schematic.py", 200),
          ("PLL", "PLL", "easyeda/pll_parts.py", 300),
          ("CDR", "CDR", "easyeda/cdr_parts.py", 400)]
MOD = {t: _module("aio_src_" + t.lower(), os.path.join(DISC, d, f)) for t, d, f, _ in BLOCKS}
OFFSET = {t: o for t, _, _, o in BLOCKS}

# nets that keep their name in every block
GLOBAL = {"GND", "P3V3_FMC", "P12V_FMC", "VADJ", "P3V3AUX",
          "FMC_SCL", "FMC_SDA", "FMC_GA0", "FMC_GA1", "FMC_TDI_TDO"}

# ---------------------------------------------------------------------------
# integration
# ---------------------------------------------------------------------------
# block parts that the merged board does not need: ref -> MPN (checked)
REMOVE = {
    "TX": {},                                       # J1, U1, C8, D1, R3 -> common sheet (COMMON)
    "RX": {"J1": "ASP-134604-01",                   # one FMC connector (common J1)
           "U1": "AT24C02C-SSHM-T", "C8": "CC0603KRX7R7BB104",       # one FRU EEPROM (common U1)
           "D1": "KT-0603G", "R3": "0603WAF1001T5E",                 # one power LED
           "U2": "SN74LVC8T245PWR", "C9": "CC0603KRX7R7BB104", "C10": "CC0603KRX7R7BB104",
           # ^ RX slow controls: DAC SCK / SDI shared with TX U102, RX DAC CS# on TX U102 A7/B7,
           #   HS_TERM_EN only on TX (one termination on the line)
           "R4": "0603WAF1003T5E",                  # HS_TERM_EN pull-down (U2 gone)
           "U3": "SN74LVC1T45DBVR", "C11": "CC0603KRX7R7BB104", "C12": "CC0603KRX7R7BB104",
           "R1": "0603WAF4702T5E", "R2": "0603WAF1003T5E", "C15": "0603CG102J500NT",
           # ^ VBUS detect: one VBUS, detected by TX U104
           "J2": "USB-B-Female-90", "J3": "USB-A-F-90-BLK",          # USB-B / USB-A through line
           "U6": "USBLC6-2SC6",                     # ESD: TX U112 at the USB-C receptacle
           "U8": "FSUSB42MUX", "R13": "0603WAF402JT5E", "R14": "0603WAF402JT5E",
           "C18": "CC0603KRX7R7BB104",              # HS termination: TX U111 (+ R127/R128)
           "R43": "0603WAF1000T5E"},                # DNP RX_OUT termination: RX_OUT now from U216
    "PLL": {"J1": "ASP-134604-01", "U1": "AT24C02C-SSHM-T", "C6": "CC0603KRX7R7BB104",
            "D2": "KT-0603G", "R13": "0603WAF1001T5E"},
    "CDR": {"J1": "ASP-134604-01", "U2": "AT24C02C-SSHM-T", "C11": "CC0603KRX7R7BB104",
            "D1": "KT-0603G", "R12": "0603WAF1001T5E",
            "J6": "BWSMA-KE-Z001"},                 # SMA CDR_V_IN_2: on-board from PLL CDR_CH_OUT_PLL
}
# TX parts that become the common ones (sheet 0): block ref -> common ref
COMMON = {"J1": "J1", "U1": "U1", "C8": "C1", "D1": "D1", "R3": "R1"}

# block net -> global net (joins blocks)
LINK = {
    "TX": {"DP": "DP", "DM": "DM", "VBUS": "VBUS",                   # the USB line (one USB-C)
           "DAC_SCK": "SPI3V3_SCK", "DAC_SDI": "SPI3V3_SDI"},        # 3.3 V DAC bus, TX + RX DACs
    "RX": {"DP": "DP", "DM": "DM",                                   # line taps on the same line
           "DAC_SCK": "SPI3V3_SCK", "DAC_SDI": "SPI3V3_SDI", "DAC_CS_N": "RX_DAC_CS_N"},
    "PLL": {"CDR_CH_OUT_PLL": "CDR_CH_OUT_PLL"},
    "CDR": {"CVIN2_S": "CDR_CH_OUT_PLL"},           # CDR_V_IN_2 <- PLL buffer (was SMA J6 <- J4)
}
# pin edits in block net names; "@NAME" is a global net
EDIT = {
    "TX": {"U2": {"9": "@RX_DAC_CS_N_F", "15": "@RX_DAC_CS_N"}},  # spare A7 -> B7: RX DAC CS#
    "RX": {"U7": {"7": "RXO_P", "6": "RXO_N"}},     # LVDS100 -> NB6L14 fan-out (was the FPGA)
    "CDR": {"U6": {"6": "D2_P", "7": "D2_N"}},      # MC100EP57 D2 = on-board HS receiver
}
# new parts: (block, sheet index 1..4, group caption or None, ref, kind, args, nets, note)
RES_EXTRA = {"4.7k": ("0603WAF4701T5E", "C23162"), "220k": ("0603WAF2203T5E", "C22961"),
             "16.5k": ("0603WAF1652T5E", "C22812")}
NB6L14 = ("C897855", "NB6L14MNG", "C897855", "onsemi")
RX_FANOUT = ("HS data fan-out: NB6L14 (LVDS in, VT open = 100R) -> Q0 RX_OUT (FPGA, AC, VBIAS), "
             "Q1 -> CDR data mux D2")
CDR_D2 = "On-board HS receiver (RX block U216 Q1) -> 100 Ohm, AC-coupled, biased to VBB -> MC100EP57 D2"
ADD = [
    ("RX", 2, RX_FANOUT, "U16", "ic", NB6L14,
     {"12": "RXO_P", "9": "RXO_N", "8": "+3V3", "7": "+3V3", "14": "+3V3", "13": "GND", "17": "GND",
      "15": "FO0_P", "16": "FO0_N", "1": "@RX_CDR_P", "2": "@RX_CDR_N"},
     "1:4 data fan-out used 1:2: Q0 -> RX_OUT (FPGA), Q1 -> CDR MC100EP57 D2; Q2 / Q3 open "
     "(unused LVPECL outputs, no pull-downs); VT / VREF_AC open (LVDS input, 100 Ohm internal)"),
    ("RX", 2, RX_FANOUT, "C34", "c", "100n", ("+3V3", "GND"), ""),
    ("RX", 2, RX_FANOUT, "C35", "c", "100n", ("+3V3", "GND"), ""),
    ("RX", 2, RX_FANOUT, "C36", "c", "10u", ("+3V3", "GND"), ""),
    ("RX", 2, RX_FANOUT, "R44", "r", "150", ("FO0_P", "GND"), "LVPECL emitter pull-down"),
    ("RX", 2, RX_FANOUT, "R45", "r", "150", ("FO0_N", "GND"), "LVPECL emitter pull-down"),
    ("RX", 2, RX_FANOUT, "C37", "c", "100n", ("FO0_P", "RX_OUT_P_F"), "AC coupling to the FPGA"),
    ("RX", 2, RX_FANOUT, "C38", "c", "100n", ("FO0_N", "RX_OUT_N_F"), "AC coupling to the FPGA"),
    ("RX", 2, RX_FANOUT, "R46", "r", "4.7k", ("RX_OUT_P_F", "VBIAS"), "bias to VBIAS (FPGA side, DIFF_TERM)"),
    ("RX", 2, RX_FANOUT, "R47", "r", "4.7k", ("RX_OUT_N_F", "VBIAS"), "bias to VBIAS (FPGA side, DIFF_TERM)"),
    ("RX", 2, RX_FANOUT, "R48", "r", "220k", ("+3V3", "RX_OUT_P_F"), "offset: RX_OUT reads 1 (J) when idle"),
    ("RX", 2, RX_FANOUT, "R49", "r", "16.5k", ("+3V3", "VBIAS"), "VBIAS top"),
    ("RX", 2, RX_FANOUT, "R50", "r", "10k", ("VBIAS", "GND"), "VBIAS bottom: 1.245 V"),
    ("RX", 2, RX_FANOUT, "C39", "c", "100n", ("VBIAS", "GND"), ""),
    ("RX", 2, RX_FANOUT, "R51", "r", "150", ("@RX_CDR_P", "GND"), "LVPECL emitter pull-down (to CDR D2)"),
    ("RX", 2, RX_FANOUT, "R52", "r", "150", ("@RX_CDR_N", "GND"), "LVPECL emitter pull-down (to CDR D2)"),
    ("CDR", 2, CDR_D2, "R89", "r", "100", ("@RX_CDR_P", "@RX_CDR_N"), "100 Ohm termination (at U406)"),
    ("CDR", 2, CDR_D2, "C74", "c", "100n", ("@RX_CDR_P", "D2_P"), "AC coupling"),
    ("CDR", 2, CDR_D2, "C75", "c", "100n", ("@RX_CDR_N", "D2_N"), "AC coupling"),
    ("CDR", 2, CDR_D2, "R90", "r", "4.7k", ("D2_P", "MUX_VBB2"), "bias to VBB"),
    ("CDR", 2, CDR_D2, "R91", "r", "4.7k", ("D2_N", "MUX_VBB2"), "bias to VBB"),
    ("CDR", 2, CDR_D2, "R92", "r", "100k", ("D2_N", "GND"), "offset ~85 mV: idle reads 1 (J)"),
]

# merged FMC LPC pin map: pin -> (global net, [(block, block net), ...], LA signal)
#   pairs: CLK_RX on CLK0_M2C and HS_RXD on LA00_CC (as on the CDR board): on the ZedBoard both
#   sit in bank 34, as the BUFIO / BUFR capture needs; CLK_BIT_A (BUFG only) on LA17_CC (bank 35)
FMC = [
    ("H4", "CLK_RX_P_F", "CDR:CLK_RX_P_F", "CLK0_M2C_P"),
    ("H5", "CLK_RX_N_F", "CDR:CLK_RX_N_F", "CLK0_M2C_N"),
    ("G2", "CLK60_A_P_F", "PLL:CLK60_A_P_F", "CLK1_M2C_P"),
    ("G3", "CLK60_A_N_F", "PLL:CLK60_A_N_F", "CLK1_M2C_N"),
    ("G6", "HS_RXD_P_F", "CDR:HS_RXD_P_F", "LA00_P_CC"),
    ("G7", "HS_RXD_N_F", "CDR:HS_RXD_N_F", "LA00_N_CC"),
    ("D8", "DPAT_P_F", "CDR:DPAT_P_F", "LA01_P_CC"),
    ("D9", "DPAT_N_F", "CDR:DPAT_N_F", "LA01_N_CC"),
    ("H7", "TX_IN_P_P", "TX:TX_IN_P_P", "LA02_P"),
    ("H8", "TX_IN_P_N", "TX:TX_IN_P_N", "LA02_N"),
    ("G9", "TX_IN_N_P", "TX:TX_IN_N_P", "LA03_P"),
    ("G10", "TX_IN_N_N", "TX:TX_IN_N_N", "LA03_N"),
    ("H10", "RX_OUT_P_F", "RX:RX_OUT_P_F", "LA04_P"),
    ("H11", "RX_OUT_N_F", "RX:RX_OUT_N_F", "LA04_N"),
    ("D20", "CLK_BIT_A_P_F", "PLL:CLK_BIT_A_P_F", "LA17_P_CC"),
    ("D21", "CLK_BIT_A_N_F", "PLL:CLK_BIT_A_N_F", "LA17_N_CC"),
    # TX
    ("D11", "TX_EN_F", "TX:TX_EN_F", "LA05_P"),
    ("D12", "FS_OE_F", "TX:FS_OE_F", "LA05_N"),
    ("C10", "FS_DAT_F", "TX:FS_DAT_F", "LA06_P"),
    ("C11", "FS_SE0_F", "TX:FS_SE0_F", "LA06_N"),
    ("H13", "FS_LS_F", "TX:FS_LS_F", "LA07_P"),
    ("H14", "FS_SUSPND_F", "TX:FS_SUSPND_F", "LA07_N"),
    ("G12", "DP_PULLUP_EN_F", "TX:DP_PULLUP_EN_F", "LA08_P"),
    ("G13", "HS_TERM_EN_F", "TX:HS_TERM_EN_F", "LA08_N"),
    ("D14", "PD_EN0_F", "TX:PD_EN0_F", "LA09_P"),
    ("D15", "PD_EN1_F", "TX:PD_EN1_F", "LA09_N"),
    ("C14", "RXRCV_F", "TX:RXRCV_F", "LA10_P"),
    ("C15", "RXDP_F", "TX:RXDP_F", "LA10_N"),
    ("H16", "RXDM_F", "TX:RXDM_F", "LA11_P"),
    ("H17", "VBUS_DET_F", "TX:VBUS_DET_F", "LA11_N"),
    ("G15", "TX_DAC_CS_N_F", "TX:DAC_CS_N_F", "LA12_P"),
    # shared SPI (SCK / SDI into TX U102, PLL U304, CDR U403)
    ("G16", "SPI_SCK_F", "TX:DAC_SCK_F PLL:SPI_SCK_F CDR:SPI_SCK_F", "LA12_N"),
    ("D17", "SPI_SDI_F", "TX:DAC_SDI_F PLL:SPI_SDI_F CDR:SPI_SDI_F", "LA13_P"),
    # RX
    ("D18", "RX_DAC_CS_N_F", "", "LA13_N"),         # via TX U102 A7 (EDIT)
    ("C18", "SQUELCH_A_F", "RX:SQUELCH_A_F", "LA14_P"),
    ("C19", "DISC_A_F", "RX:DISC_A_F", "LA14_N"),
    ("H19", "RX_EN_F", "RX:RX_EN_F", "LA15_P"),
    # PLL
    ("C22", "REF_DIG_F", "PLL:REF_DIG_F", "LA18_P_CC"),
    ("C23", "MUXOUT_F", "PLL:MUXOUT_F", "LA18_N_CC"),
    ("G18", "ADF_CLK_F", "PLL:ADF_CLK_F", "LA16_P"),
    ("G19", "ADF_DATA_F", "PLL:ADF_DATA_F", "LA16_N"),
    ("H22", "ADF_LE_F", "PLL:ADF_LE_F", "LA19_P"),
    ("H23", "ADF_CE", "PLL:ADF_CE", "LA19_N"),
    ("G21", "PLL_VCO_OFF_F", "PLL:VCO_OFF_F", "LA20_P"),
    ("G22", "LF_DIS_F", "PLL:LF_DIS_F", "LA20_N"),
    ("H25", "OL_EN_F", "PLL:OL_EN_F", "LA21_P"),
    ("H26", "CDCM_OFF_F", "PLL:CDCM_OFF_F", "LA21_N"),
    ("G24", "PLL_DAC_CS_N_F", "PLL:DAC_CS_N_F", "LA22_P"),
    ("G25", "PLL_ADC_CS_N_F", "PLL:ADC_CS_N_F", "LA22_N"),
    ("D23", "PLL_ADC_SDO_F", "PLL:ADC_SDO_F", "LA23_P"),
    ("D24", "REFSRC0_F", "PLL:REFSRC0_F", "LA23_N"),
    ("H28", "REFSRC1_F", "PLL:REFSRC1_F", "LA24_P"),
    ("H29", "OE24_F", "PLL:OE24_F", "LA24_N"),
    ("G27", "OE19_F", "PLL:OE19_F", "LA25_P"),
    # CDR
    ("D26", "CDR_EN_F", "CDR:CDR_EN_F", "LA26_P"),
    ("D27", "CDR_SET_F", "CDR:CDR_SET_F", "LA26_N"),
    ("C26", "DSEL0_F", "CDR:DSEL0_F", "LA27_P"),
    ("C27", "DSEL1_F", "CDR:DSEL1_F", "LA27_N"),
    ("H31", "CDR_VCO_OFF_F", "CDR:VCO_OFF_F", "LA28_P"),
    ("H32", "CSW_EXT_F", "CDR:CSW_EXT_F", "LA28_N"),
    ("G30", "CSW_DAC_F", "CDR:CSW_DAC_F", "LA29_P"),
    ("G31", "CDR_DAC_CS_N_F", "CDR:DAC_CS_N_F", "LA29_N"),
    ("H34", "CDR_ADC_CS_N_F", "CDR:ADC_CS_N_F", "LA30_P"),
    ("H35", "CDR_ADC_SDO_F", "CDR:ADC_SDO_F", "LA30_N"),
    # free: H20 (LA15_N), G28 (LA25_N), LA31..LA33 (G33/G34, H37/H38, G36/G37)
]
# block FMC nets that the merged board drops on purpose
FMC_DROP = {"RX": {"HS_TERM_EN_F": "one HS termination (TX U111), switched by the TX HS_TERM_EN_F",
                   "DAC_SCK_F": "shared SPI_SCK_F via TX U102", "DAC_SDI_F": "shared SPI_SDI_F via TX U102",
                   "DAC_CS_N_F": "RX_DAC_CS_N_F via TX U102 A7",
                   "VBUS_DET_F": "one VBUS detector (TX U104)"}}
FMC_POWER = {"C39": "P3V3_FMC", "D36": "P3V3_FMC", "D38": "P3V3_FMC", "D40": "P3V3_FMC",
             "C35": "P12V_FMC", "C37": "P12V_FMC", "G39": "VADJ", "H40": "VADJ", "D32": "P3V3AUX",
             "H2": "GND", "C30": "FMC_SCL", "C31": "FMC_SDA", "C34": "FMC_GA0", "D35": "FMC_GA1",
             "D30": "FMC_TDI_TDO", "D31": "FMC_TDI_TDO"}
for _p in ("C1 C4 C5 C8 C9 C12 C13 C16 C17 C20 C21 C24 C25 C28 C29 C32 C33 C36 C38 C40 "
           "D2 D3 D6 D7 D10 D13 D16 D19 D22 D25 D28 D37 D39 "
           "G1 G4 G5 G8 G11 G14 G17 G20 G23 G26 G29 G32 G35 G38 G40 "
           "H3 H6 H9 H12 H15 H18 H21 H24 H27 H30 H33 H36 H39").split():
    FMC_POWER[_p] = "GND"

# Carrier: Digilent ZedBoard Rev D.2, XC7Z020CLG484-2 (DOC/fpga_package_pin_to_fmc.pdf,
# DOC/zedboard_sch.pdf sheet 9).  LA00..LA16 + CLK0 -> bank 34, LA17..LA33 + CLK1 -> bank 35,
# both at VADJ (J18: 2.5 V needed for LVDS_25 outputs and DIFF_TERM).  DP0 / GBTCLK0: not
# connected (the XC7Z020 has no GTP transceivers).
ZED_PIN = {
    "C10": "L21", "C11": "L22", "C14": "R19", "C15": "T19", "C18": "K19", "C19": "K20", "C22": "D20",
    "C23": "C20", "C26": "E21", "C27": "D21", "D8": "N19", "D9": "N20", "D11": "J18", "D12": "K18",
    "D14": "R20", "D15": "R21", "D17": "L17", "D18": "M17", "D20": "B19", "D21": "B20", "D23": "E15",
    "D24": "D15", "D26": "F18", "D27": "E18", "G2": "D18", "G3": "C19", "G6": "M19", "G7": "M20",
    "G9": "N22", "G10": "P22", "G12": "J21", "G13": "J22", "G15": "P20", "G16": "P21", "G18": "J20",
    "G19": "K21", "G21": "G20", "G22": "G21", "G24": "G19", "G25": "F19", "G27": "D22", "G28": "C22",
    "G30": "C17", "G31": "C18", "G33": "B16", "G34": "B17", "G36": "B21", "G37": "B22", "H4": "L18",
    "H5": "L19", "H7": "P17", "H8": "P18", "H10": "M21", "H11": "M22", "H13": "T16", "H14": "T17",
    "H16": "N17", "H17": "N18", "H19": "J16", "H20": "J17", "H22": "G15", "H23": "G16", "H25": "E19",
    "H26": "E20", "H28": "A18", "H29": "A19", "H31": "A16", "H32": "A17", "H34": "C15", "H35": "B15",
    "H37": "A21", "H38": "A22"}
# clock-capable ZedBoard pins (FMC P pin -> function)
ZED_CC = {"H4": "IO_L12P_T1_MRCC_34", "G6": "IO_L13P_T2_MRCC_34", "D8": "IO_L14P_T2_SRCC_34",
          "C18": "IO_L11P_T1_SRCC_34", "G2": "IO_L12P_T1_MRCC_35", "D20": "IO_L13P_T2_MRCC_35",
          "C22": "IO_L14P_T2_SRCC_35", "G30": "IO_L11P_T1_SRCC_35"}


def zed_bank(la):
    """FMC LA / CLK signal name -> ZedBoard bank"""
    if la.startswith("CLK"):
        return 34 if la.startswith("CLK0") else 35
    return 34 if int(la[2:4]) <= 16 else 35


# FPGA constraints the pin map must meet on the ZedBoard
ZED_CLOCK_PINS = ["CLK_RX_P_F", "CLK_BIT_A_P_F", "CLK60_A_P_F", "REF_DIG_F"]   # on CC pins
ZED_SAME_BANK = [
    ("CDR capture: CLK_RX -> BUFIO / BUFR -> ISERDESE2 (HS_RXD); DPAT OSERDESE2 at 240 MHz BUFG",
     ["CLK_RX_P_F", "HS_RXD_P_F"]),
    ("RX sampler: MMCM -> BUFIO 480 MHz -> ISERDESE2 x 2 (RX_OUT), SQUELCH_A / DISC_A at 960 MS/s",
     ["RX_OUT_P_F", "SQUELCH_A_F", "DISC_A_F"]),
]

# text fixes in captions / notes / titles: (old, new); {X} = new designator of block ref X.
# Each old text must still occur, so a changed block text is noticed.
TEXT_FIX = {
    "TX": [("Q1 = Q_P", "{Q1} = Q_P"), ("Q2 = Q_N", "{Q2} = Q_N"), ("Q3 = Q_D", "{Q3} = Q_D"),
           ("(U7A, Q4)", "({U7}A, {Q4})"), ("(U7B, Q5)", "({U7}B, {Q5})"), ("D+ (Q7)", "D+ ({Q7})"),
           ("D- (Q8)", "D- ({Q8})"), ("(Q9, DP", "({Q9}, DP"), ("(J3: 1-2", "({J3}: 1-2"),
           ("as Q1", "as {Q1}"), ("Q4 base", "{Q4} base"), ("as D6", "as {D6}"),
           ("by Q9", "by {Q9}"), ("Q9 P gate", "{Q9} P gate"),
           ("Slow controls VADJ -> 3.3 V", "Slow controls VADJ -> 3.3 V (A7 / B7: RX DAC CS#)"),
           ("ESD, USB-C receptacle,", "ESD, USB-C receptacle (the board's only USB port, also the RX taps' line),")],
    "RX": [("as Q1", "as {Q1}"),
           ("Power: FMC 3P3V -> +3V3 (digital) / +3V3A (taps, receivers)",
            "Power: FMC 3P3V -> +3V3_RX (NB6L14 fan-out, CS# pull-up) / +3V3A_RX (taps, receivers)"),
           ("Line taps: BFT92 emitter followers",
            "Line taps on DP / DM (USB-C J102, sheet TX3): BFT92 emitter followers"),
           ("-> RX_OUT (LVDS to the FPGA)", "-> NB6L14 fan-out")],
    "PLL": [("VP = 4.5 V, U17", "VP = 4.5 V, {U17}"), ("U17 input", "{U17} input"),
            ("x (1 + R1/R2)", "x (1 + {R1}/{R2})"),
            ("VTUNE buffer -> CDR_CH_OUT_PLL (SMA), ADC", "VTUNE buffer -> CDR_CH_OUT_PLL (SMA + CDR block), ADC"),
            ("to the CDR board's CDR_V_IN_2", "to the CDR block's CDR_V_IN_2 (on-board; SMA = monitor / injection)")],
    "CDR": [("x (1 + R1/R2)", "x (1 + {R1}/{R2})"),
            ("(generator / AFE receiver board)", "(generator / external receiver)"),
            ("D0 SMA, D1 FPGA pattern (SEL1 SEL0 = 00 / 01)",
             "D0 SMA, D1 FPGA pattern, D2 on-board HS receiver (SEL1 SEL0 = 00 / 01 / 10)"),
            ("D2/D3 unused (read 0)", "D2 on-board HS receiver, D3 unused (reads 0)"),
            ("(at U7 D1)", "(at {U7} D1)"), ("U8 D0 + U10 D1, terminated at U10", "{U8} D0 + {U10} D1, terminated at {U10}"),
            ("terminated at U8 D1", "terminated at {U8} D1"), ("U9 D0 + FPGA, terminated at U9", "{U9} D0 + FPGA, terminated at {U9}"),
            ("U9 D1 + U10 D0, terminated at U10", "{U9} D1 + {U10} D0, terminated at {U10}"),
            ("Q0 -> U7, Q1 -> U8", "Q0 -> {U7}, Q1 -> {U8}"), ("at U7 CLK1", "at {U7} CLK1"),
            ("at U8 CLK1", "at {U8} CLK1"), ("(sheet 3;", "(sheet CDR3;"), ("(sheet 4)", "(sheet CDR4)"),
            ("(SMA CDR_V_IN_2)", "(CDR_V_IN_2 = PLL block CDR_CH_OUT_PLL)"),
            ("coarse = CDR_V_IN_2 (SMA) or DAC B", "coarse = CDR_V_IN_2 (PLL block, on-board) or DAC B"),
            ("SMA pair / FPGA LVDS pattern,", "SMA pair / FPGA LVDS pattern / on-board HS receiver,"),
            ("input protection", "series / input protection (from PLL {U14} via {R24})", "PLL")],
}
# sheet 1 of each block loses the FMC connector: new titles
SHEET1_TITLE = {
    "TX": "TX: power (+3V3_TX / +3V3A_TX), slow controls, TX_EN, VBUS detect",
    "RX": "RX: power (+3V3_RX / +3V3A_RX), SQUELCH_A / DISC_A output gates (RX_EN)",
    "PLL": "PLL: power (12 V -> +5V_A_PLL / +3V0), level translation",
    "CDR": "CDR: power (+3V3_CDR ECL, 12 V -> +5V_A_CDR), level translation",
}
COMMON_SHEET = "0_FMC_COMMON"
COMMON_TITLE = "FMC LPC connector, FRU EEPROM, power LED, block interconnect"
COMMON_GROUPS = [("J1  FMC LPC (VITA 57.1): merged pin map of the four blocks (fmc_pinmap.csv)", ["J1"]),
                 ("FRU EEPROM (IPMI)", ["U1", "C1"]), ("Power LED (+3V3_TX)", ["R1", "D1"])]
COMMON_NOTES = [
    "Blocks: TX = sheets TX1-TX4 (designators 1xx), RX = RX1-RX4 (2xx), PLL = PLL1-PLL4 (3xx), "
    "CDR = CDR1-CDR4 (4xx); each block keeps its own rails, beads and LDOs.",
    "USB line: one USB-C receptacle J102 (TX3) with ESD U112, termination switch U111, pulls; "
    "the RX taps Q201 / Q202 (RX2) sit on the same DP / DM.",
    "HS receive path: RX taps -> SN65LVDS100 U207 -> NB6L14 U216: Q0 -> RX_OUT (FPGA LA04), "
    "Q1 -> RX_CDR_P/N -> CDR MC100EP57 U406 D2 (DSEL1:0 = 10).",
    "Coarse tuning: PLL CDR_CH_OUT_PLL (U314 buffer, R324) -> CDR R482 -> CDR_V_IN_2 switch U414 "
    "(CSW_EXT); PLL SMA J304 stays as monitor.",
    "FMC: one SPI SCK / SDI for the TX, RX, PLL and CDR DACs / ADCs (separate CS#, separate ADC "
    "DOUT); CLK_BIT_A moved from CLK0_M2C to LA17_CC (ZedBoard: CLK_RX + HS_RXD in bank 34).",
]


# ---------------------------------------------------------------------------
# EasyEDA Std shape handling (same engine as the block generators)
# ---------------------------------------------------------------------------
_id = [0]
_cache = {}


def gid():
    _id[0] += 1
    return "gai%05d" % _id[0]


def load(lcsc):
    if lcsc not in _cache:
        for d in LIBS:
            p = os.path.join(d, lcsc + ".json")
            if os.path.exists(p):
                break
        else:
            raise FileNotFoundError("symbol %s not in %s" % (lcsc, LIBS))
        with open(p) as f:
            r = json.load(f)["result"]
        sh = r["dataStr"]["shape"]
        for i, s in enumerate(sh):
            if s.startswith("P~"):
                seg = s.split("^^")
                f0 = seg[0].split("~")
                key = (lcsc, f0[3], seg[3].split("~")[4])
                if key in PIN_FIX:
                    f0[3] = PIN_FIX[key]
                    seg[0] = "~".join(f0)
                    sh[i] = "^^".join(seg)
        _cache[lcsc] = r
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


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------
PARTS, NETS, DNP, GROUPS, TITLES, SHEETS = {}, {}, set(), {}, {}, []
REFMAP = {}                     # (block, block ref) -> board ref
BLOCK_OF = {}                   # board ref -> block tag ("" = common)


def newref(tag, ref):
    if tag == "TX" and ref in COMMON:
        return COMMON[ref]
    m = re.match(r"^([A-Z]+)(\d+)$", ref)
    return "%s%d" % (m.group(1), int(m.group(2)) + OFFSET[tag])


def resolve(lcsc, ref, pins, err):
    """pins given by name -> symbol pin numbers (names must be unique)"""
    _, sp, _ = sym_info(lcsc)
    byname = {}
    for num, (nm, *_r) in sp.items():
        byname.setdefault(nm, []).append(num)
    out = {}
    for k, net in pins.items():
        if k in sp:
            out[k] = net
        elif len(byname.get(k, [])) == 1:
            out[byname[k][0]] = net
        else:
            err.append("%s: pin %r not found or not unique" % (ref, k))
            out[k] = net
    return out


def block_sources():
    """per block: parts, nets (pin numbers, block net names), groups, titles, sheets"""
    allres, allcap = dict(RES_EXTRA), {}
    for m in MOD.values():
        allres.update(m.RES)
        allcap.update(m.CAP)
    src, err = {}, []
    for tag, *_ in BLOCKS:
        m = MOD[tag]
        sheets = [m.S1, m.S2, m.S3, m.S4]
        parts = {k: dict(v) for k, v in m.PARTS.items()}
        nets = {k: resolve(parts[k]["sym"], "%s %s" % (tag, k), v, err) if k in parts else dict(v)
                for k, v in m.NETS.items()}
        fmcnets = dict(nets.get("J1", {}))
        for ref, mpn in REMOVE[tag].items():
            if ref not in parts or parts[ref]["mpn"] != mpn:
                err.append("%s %s: REMOVE expects MPN %s, block has %s" % (
                    tag, ref, mpn, parts.get(ref, {}).get("mpn")))
            parts.pop(ref, None)
            nets.pop(ref, None)
        if tag == "TX":
            nets.pop("J1")                          # common J1 gets the merged FMC map
        for ref, pins in EDIT.get(tag, {}).items():
            nets[ref].update(pins)
        groups = {s: [(cap, list(refs)) for cap, refs in m.GROUPS[s]] for s in sheets}
        for t, sh, cap, ref, kind, a, n, note in ADD:
            if t != tag:
                continue
            if ref in parts:
                err.append("%s %s: ADD ref already used" % (tag, ref))
            if kind == "ic":
                sym, mpn, lc, mf = a
                parts[ref] = dict(sheet=sheets[sh - 1], sym=sym, value=mpn, mpn=mpn, lcsc=lc, mfr=mf, note=note)
                nets[ref] = dict(n)
            elif kind == "r":
                mpn, lc = allres[a]
                parts[ref] = dict(sheet=sheets[sh - 1], sym="C25804", value=a if a[-1] in "kM" else a + "R",
                                  mpn=mpn, lcsc=lc, mfr="UNI-ROYAL", note=note)
                nets[ref] = {"1": n[0], "2": n[1]}
            else:
                mpn, lc, mf = allcap[a]
                parts[ref] = dict(sheet=sheets[sh - 1], sym="C108079", value=a + "F", mpn=mpn, lcsc=lc,
                                  mfr=mf, note=note)
                nets[ref] = {"1": n[0], "2": n[1]}
            g = groups[sheets[sh - 1]]
            for k, (c, refs) in enumerate(g):
                if c == cap:
                    refs.append(ref)
                    break
            else:
                g.append((cap, [ref]))
        src[tag] = dict(parts=parts, nets=nets, groups=groups, titles=dict(m.TITLES), sheets=sheets,
                        dnp=set(m.DNP), fmc=fmcnets)
    return src, err


def fmc_links(src, err):
    """merged FMC map -> LINK entries; every block FMC signal must be mapped or dropped"""
    j1, seen, link = dict(FMC_POWER), {}, {t: {} for t, *_ in BLOCKS}
    for pin, net, uses, _la in FMC:
        if pin in j1:
            err.append("FMC %s used twice" % pin)
        j1[pin] = net
        for u in uses.split():
            t, bn = u.split(":")
            link[t][bn] = net
            seen.setdefault(t, set()).add(bn)
    for t, s in src.items():
        for pin, bn in s["fmc"].items():
            if bn in GLOBAL or bn in seen.get(t, set()) or bn in FMC_DROP.get(t, {}):
                continue
            err.append("%s FMC %s (%s): not in the merged pin map" % (t, pin, bn))
    byname = {net: (pin, la) for pin, net, _u, la in FMC}
    for net in ZED_CLOCK_PINS:
        if byname[net][0] not in ZED_CC:
            err.append("ZedBoard: %s on %s is not a clock-capable pin" % (net, byname[net][0]))
    for why, nets in ZED_SAME_BANK:
        if len({zed_bank(byname[n][1]) for n in nets}) > 1:
            err.append("ZedBoard: %s must share one bank (%s)" % (" / ".join(nets), why))
    for pin, net, _u, la in FMC:
        if pin not in ZED_PIN:
            err.append("ZedBoard: FMC %s (%s) not connected on the carrier" % (pin, net))
    NETS["J1"] = {re.sub(r"^([A-Z])(\d)$", r"\g<1>0\2", k): v for k, v in j1.items()}   # symbol: "H07"
    return link


def merge():
    src, err = block_sources()
    flink = fmc_links(src, err)
    # nets after LINK; "@" marks a global net
    for t, s in src.items():
        lk = dict(LINK.get(t, {}), **flink[t])
        for ref, pins in s["nets"].items():
            s["nets"][ref] = {p: ("@" + lk[n] if n in lk else n) for p, n in pins.items()}
    used = {}
    for t, s in src.items():
        for pins in s["nets"].values():
            for n in pins.values():
                if not n.startswith("@") and n not in GLOBAL:
                    used.setdefault(n, set()).add(t)
    gnames = set(GLOBAL) | {n[1:] for s in src.values() for p in s["nets"].values() for n in p.values()
                            if n.startswith("@")} | set(NETS["J1"].values())

    def rename(t, n):
        if n.startswith("@"):
            return n[1:]
        if n in GLOBAL or len(used[n]) == 1:
            return n
        return n + "_" + t if n.startswith("+") else t + "_" + n

    final = {}
    for t, s in src.items():
        for n in used:
            if t in used[n]:
                fn = rename(t, n)
                if fn in final and final[fn] != (t, n):
                    err.append("net name %s from %s and %s" % (fn, final[fn], (t, n)))
                if fn in gnames and fn != n:
                    err.append("net name %s (%s %s) collides with a global net" % (fn, t, n))
                final[fn] = (t, n)
    for n, ts in used.items():
        if len(ts) == 1 and n in gnames:
            err.append("block net %s (%s) has a global net's name" % (n, ",".join(ts)))
    # designators, parts, sheets
    for t, s in src.items():
        for ref in s["parts"]:
            REFMAP[(t, ref)] = newref(t, ref)

    def fixtext(t, text):
        for fix in TEXT_FIX.get(t, []):
            old, new = fix[0], fix[1]
            rt = fix[2] if len(fix) > 2 else t           # block whose refs {X} refers to
            if old in text:
                text = text.replace(old, re.sub(r"\{(\w+)\}", lambda m: REFMAP[(rt, m.group(1))], new))
                FIX_USED.add((t, old))
        return text

    TITLES[COMMON_SHEET] = COMMON_TITLE
    SHEETS.append(COMMON_SHEET)
    GROUPS[COMMON_SHEET] = COMMON_GROUPS
    for t, s in src.items():
        smap = {}
        for i, sh in enumerate(s["sheets"]):
            name = "%s%d_%s" % (t, i + 1, "POWER_IO" if i == 0 else sh.split("_", 1)[1])
            smap[sh] = name
            SHEETS.append(name)
            TITLES[name] = SHEET1_TITLE[t] if i == 0 else "%s: %s" % (t, fixtext(t, s["titles"][sh]))
            gl = []
            for cap, refs in s["groups"][sh]:
                refs = [REFMAP[(t, r)] for r in refs if r in s["parts"] and not (t == "TX" and r in COMMON)]
                if refs:
                    gl.append((fixtext(t, cap), refs))
            GROUPS[name] = gl
        for ref, p in s["parts"].items():
            nr = REFMAP[(t, ref)]
            if nr in PARTS:
                err.append("designator %s twice" % nr)
            q = dict(p, note=fixtext(t, p["note"]))
            q["sheet"] = COMMON_SHEET if (t == "TX" and ref in COMMON) else smap[p["sheet"]]
            PARTS[nr] = q
            BLOCK_OF[nr] = "" if (t == "TX" and ref in COMMON) else t
            if ref in s["dnp"]:
                DNP.add(nr)
            if ref in s["nets"]:
                NETS[nr] = {p_: rename(t, n) for p_, n in s["nets"][ref].items()}
    for t, fixes in TEXT_FIX.items():
        for fix in fixes:
            if (t, fix[0]) not in FIX_USED:
                err.append("TEXT_FIX %s %r: text not found" % (t, fix[0]))
    return err


FIX_USED = set()


# ---------------------------------------------------------------------------
# drawing
# ---------------------------------------------------------------------------
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
    if BLOCK_OF.get(ref):
        cp["Block"] = BLOCK_OF[ref]
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
            rot, tx, ty = 90, x2 - 2, y2 + 2 * oy
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


def frame(w, h, title, no, n):
    s = ["R~0~%g~0~0~%g~%g~#880000~1~0~none~%s~0~" % (-h, w, h, gid()),
         "R~10~%g~0~0~%g~%g~#880000~1~0~none~%s~0~" % (-h + 10, w - 20, h - 20, gid())]
    bx, by = w - 520, -80
    s.append("R~%g~%g~0~0~510~70~#880000~1~0~none~%s~0~" % (bx, by, gid()))
    for x, y, t in [(bx + 8, by + 18, BOARD),
                    (bx + 8, by + 36, "Sheet %d/%d: %s" % (no, n, title[:80])),
                    (bx + 8, by + 54, "Rev 0.1 - easyeda/gen_schematic.py - " + SOURCE_NOTE)]:
        s.append("T~L~%g~%g~0~#000080~Arial~~~~~comment~%s~1~start~%s~0~" % (x, y, t, gid()))
    return s


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
    missing = sorted((k for k, v in PARTS.items() if v["sheet"] == sheet and k not in placed), key=refkey)
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
        shapes.append((gx, gy, w + 20, h, cap))
        parts += [(ref, gx + 10 + px, gy + 25 + py) for ref, px, py in pos]
        gx += w + 40
        row_h = max(row_h, h)
    notes = COMMON_NOTES if sheet == COMMON_SHEET else []
    ny = gy + row_h + 30
    H = max(ny + 16 * len(notes) + 130, 700)
    out = frame(W, H, TITLES[sheet], no, n)
    for x, y, w, h, cap in shapes:
        out.append("R~%g~%g~0~0~%g~%g~#808080~1~1~none~%s~0~" % (x, y - H, w, h, gid()))
        out.append("T~L~%g~%g~0~#404040~Arial~8pt~~bold~~comment~%s~1~start~%s~0~" % (
            x + 6, y - H + 14, cap, gid()))
    for k, t in enumerate(notes):
        out.append("T~L~%g~%g~0~#404040~Arial~8pt~~~~comment~%s~1~start~%s~0~" % (
            36, ny + 16 * k - H, t, gid()))
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
        rows.append(dict(refs=refs, value=val, mpn=mpn, mfr=p["mfr"], lcsc=lcsc, footprint=fp, dnp=dnp,
                         blocks=" ".join(b for b in ("TX", "RX", "PLL", "CDR") if any(BLOCK_OF[k] == b for k in refs))
                         or "common",
                         note="; ".join(sorted({PARTS[k]["note"] for k in refs if PARTS[k]["note"]}))))
    rows.sort(key=lambda r: refkey(r["refs"][0]))
    with open(os.path.join(BOMDIR, "aio_board_bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Qty", "Value", "Manufacturer", "MPN", "LCSC", "Footprint", "Fitted",
                    "Blocks", "Note"])
        for r in rows:
            w.writerow([",".join(r["refs"]), len(r["refs"]), r["value"], r["mfr"], r["mpn"],
                        r["lcsc"], r["footprint"], "DNP" if r["dnp"] else "yes", r["blocks"], r["note"]])
    with open(os.path.join(BOMDIR, "aio_board_bom_jlcpcb.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for r in rows:
            if not r["dnp"]:
                w.writerow([r["value"], ",".join(r["refs"]), r["footprint"], r["lcsc"]])
    return rows


def _old(fmc, net):
    return [re.sub(r"^([A-Z])0", r"\1", p) for p, n in fmc.items() if n == net]


def _pair(la, net):
    """differential: the other pin of the same LA / CLK pair carries the complementary net"""
    def strip(x):
        i = max(x.rfind("_P"), x.rfind("_N"))
        return x[:i] + x[i + 2:] if i >= 0 else None
    other = la.replace("_P", "_X").replace("_N", "_P").replace("_X", "_N")
    nets = [n for _p, n, _u, l2 in FMC if l2 == other]
    return bool(nets) and strip(nets[0]) == strip(net) and strip(net) is not None


def _ppin(pin, la):
    """N pin of a clock-capable pair -> its P pin (the CC function is listed on P)"""
    if "_N" not in la:
        return pin
    for p, _n, _u, l2 in FMC:
        if l2 == la.replace("_N", "_P"):
            return p
    return pin


def write_pinmap(src_fmc):
    with open(os.path.join(HERE, "fmc_pinmap.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fmc_pin", "la_signal", "net", "block", "block_net", "pin_on_block_board",
                    "zedboard_pin", "zedboard_bank", "zedboard_clock_capable", "iostandard"])
        for pin, net, uses, la in FMC:
            cc = ZED_CC.get(pin) or ZED_CC.get(_ppin(pin, la), "").replace("P_T", "N_T")
            zed = [ZED_PIN[pin], zed_bank(la), cc, "LVDS_25" if _pair(la, net) else "LVCMOS25"]
            if not uses:
                w.writerow([pin, la, net, "RX", "DAC_CS_N_F", "D11 (via TX U102 A7 here)"] + zed)
            for u in uses.split():
                t, bn = u.split(":")
                w.writerow([pin, la, net, t, bn, " ".join(_old(src_fmc[t], bn))] + zed)
        used = {p for p, *_r in FMC}
        for pin in sorted(set(ZED_PIN) - used, key=lambda p: (p[0], int(p[1:]))):
            w.writerow([pin, "", "(free)", "", "", "", ZED_PIN[pin], "", ZED_CC.get(pin, ""), ""])
        for t, d in FMC_DROP.items():
            for bn, why in d.items():
                w.writerow(["-", "-", "-", t, bn, " ".join(_old(src_fmc[t], bn)) + " (dropped: %s)" % why,
                            "", "", "", ""])


def main():
    err = merge()
    cerr, single, count = check()
    err += cerr
    for e in err:
        print("ERROR", e)
    if single:
        print("single-pin nets (inputs / test points):", " ".join(single))
    proj = {"editorVersion": "6.5.61", "docType": "5", "title": "USB2 AFE all-in-one board",
            "description": "Discrete USB 2.0 AFE (TX, RX, PLL, CDR) on one FMC LPC, one USB-C",
            "colors": {}, "schematics": [sheet_doc(s, i + 1, len(SHEETS)) for i, s in enumerate(SHEETS)]}
    with open(os.path.join(HERE, "usb_aio_board_sch.json"), "w") as f:
        json.dump(proj, f, ensure_ascii=False, indent=1)
    with open(os.path.join(HERE, "netlist.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ref", "pin", "pin_name", "net", "sheet", "block"])
        for ref in sorted(NETS, key=refkey):
            _, sp, _ = sym_info(PARTS[ref]["sym"])
            for num, net in sorted(NETS[ref].items()):
                w.writerow([ref, num, sp[num][0], net, PARTS[ref]["sheet"], BLOCK_OF[ref] or "common"])
    write_pinmap({t: {p: n for p, n in MOD[t].NETS["J1"].items()} for t in MOD})
    rows = write_bom()
    print("sheets %d, parts %d, BOM lines %d, nets %d, errors %d" % (
        len(SHEETS), len(PARTS), len(rows), len(count), len(err)))
    return 1 if err else 0


if __name__ == "__main__":
    raise SystemExit(main())
