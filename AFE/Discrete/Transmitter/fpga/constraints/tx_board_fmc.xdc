## tx_board_fmc.xdc - pin constraints of tx_fpga_top for the discrete USB 2.0
## transmitter board on an FMC LPC carrier (AMD 7-Series).
##
## The FMC signal of every port is fixed by the transmitter board (schematic
## sheet 1, connector J1; doc/tx_board.md section 4.6).  The FPGA package pin of
## an FMC LA signal depends on the carrier: copy it from the carrier's master
## XDC / schematic (e.g. "FMC_LPC_LA02_P") into the <PIN> fields below.
##
## I/O standard: all LA pins sit in the bank powered by the carrier's VADJ.
##   VADJ = 2.5 V (HR bank, e.g. AC701, Nexys Video at 2.5 V): IOSTD_DIFF = LVDS_25, IOSTD_SE = LVCMOS25
##   VADJ = 1.8 V (HP bank, e.g. KC705 LPC):                   IOSTD_DIFF = LVDS,    IOSTD_SE = LVCMOS18
## The board's translators (SN74LVC8T245, SN74LVC1T45, TUSB1105 VCC(I/O),
## SN74LVC2G86) run from VADJ, 1.65 .. 3.6 V.  LVDS outputs need no
## termination on the carrier: the SN65LVDT101 inputs carry 110 Ohm.

set IOSTD_DIFF LVDS_25
set IOSTD_SE   LVCMOS25

# ---- board clock / reset / UART (carrier specific; see the carrier's master XDC) ----
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports clkin_p]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports clkin_n]   ;# differential clocks only
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports rst_btn]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports uart_rxd]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports uart_txd]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports led_locked]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports led_active]
create_clock -period 10.000 -name clkin [get_ports clkin_p]          ;# 100 MHz oscillator

# ---- FMC LPC (VITA 57.1) ----        port              FMC signal   FMC pin
#  480 Mbit/s LVDS pairs (route the carrier side as delivered: 100 Ohm differential)
# set_property PACKAGE_PIN <PIN> [get_ports tx_in_p_p]     ;# LA02_P      H7
# set_property PACKAGE_PIN <PIN> [get_ports tx_in_p_n]     ;# LA02_N      H8
# set_property PACKAGE_PIN <PIN> [get_ports tx_in_n_p]     ;# LA03_P      G9
# set_property PACKAGE_PIN <PIN> [get_ports tx_in_n_n]     ;# LA03_N      G10
#  480 Mbit/s single-ended (TX_EN) and 12 / 1.5 Mbit/s FS/LS controls
# set_property PACKAGE_PIN <PIN> [get_ports tx_en]          ;# LA04_P      H10
# set_property PACKAGE_PIN <PIN> [get_ports fs_oe_a]        ;# LA04_N      H11
# set_property PACKAGE_PIN <PIN> [get_ports fs_dat_a]       ;# LA05_P      D11
# set_property PACKAGE_PIN <PIN> [get_ports fs_se0_a]       ;# LA05_N      D12
# set_property PACKAGE_PIN <PIN> [get_ports fs_ls_a]        ;# LA06_P      C10
# set_property PACKAGE_PIN <PIN> [get_ports fs_suspnd]      ;# LA06_N      C11
#  static controls
# set_property PACKAGE_PIN <PIN> [get_ports dp_pullup_en_a] ;# LA07_P      H13
# set_property PACKAGE_PIN <PIN> [get_ports hs_term_en_a]   ;# LA07_N      H14
# set_property PACKAGE_PIN <PIN> [get_ports pd_en_a0]       ;# LA08_P      G12
# set_property PACKAGE_PIN <PIN> [get_ports pd_en_a1]       ;# LA08_N      G13
# set_property PACKAGE_PIN <PIN> [get_ports dac_cs_n]       ;# LA09_P      D14
# set_property PACKAGE_PIN <PIN> [get_ports dac_sck]        ;# LA09_N      D15
# set_property PACKAGE_PIN <PIN> [get_ports dac_sdi]        ;# LA10_P      C14
#  inputs from the board
# set_property PACKAGE_PIN <PIN> [get_ports vbus_det]       ;# LA10_N      C15
# set_property PACKAGE_PIN <PIN> [get_ports rxrcv_a]        ;# LA11_P      H16
# set_property PACKAGE_PIN <PIN> [get_ports rxdp_a]         ;# LA11_N      H17
# set_property PACKAGE_PIN <PIN> [get_ports rxdm_a]         ;# LA12_P      G15

set_property IOSTANDARD $IOSTD_DIFF [get_ports {tx_in_p_p tx_in_p_n tx_in_n_p tx_in_n_n}]
set_property IOSTANDARD $IOSTD_SE   [get_ports {tx_en fs_oe_a fs_dat_a fs_se0_a fs_ls_a fs_suspnd \
    dp_pullup_en_a hs_term_en_a pd_en_a0 pd_en_a1 dac_cs_n dac_sck dac_sdi vbus_det rxrcv_a rxdp_a rxdm_a}]
set_property SLEW FAST [get_ports {tx_en fs_oe_a fs_dat_a fs_se0_a fs_ls_a}]
set_property DRIVE 8   [get_ports {tx_en fs_oe_a fs_dat_a fs_se0_a fs_ls_a}]

# ---- timing ----
# The OSERDESE2 outputs need no output delay constraints (fixed CLK-to-OQ).
# Static / slow pins and the asynchronous inputs are false paths.
set_false_path -to   [get_ports {dp_pullup_en_a hs_term_en_a pd_en_a0 pd_en_a1 fs_suspnd dac_cs_n dac_sck dac_sdi uart_txd led_*}]
set_false_path -from [get_ports {vbus_det rxrcv_a rxdp_a rxdm_a uart_rxd rst_btn}]
