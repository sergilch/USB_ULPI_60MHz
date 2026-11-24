## rx_board_fmc.xdc - pin and timing constraints of rx_fpga_top for the discrete
## USB 2.0 receiver board on an FMC LPC carrier (AMD 7-Series).
##
## The FMC signal of every port is fixed by the receiver board (schematic sheet
## 1, connector J1; doc/rx_board.md section 4.7).  The FPGA package pin of an
## FMC LA signal depends on the carrier: copy it from the carrier's master XDC /
## schematic (e.g. "FMC_LPC_LA02_P") into the <PIN> fields below.
##
## I/O standard: the LA pins sit in the bank powered by the carrier's VADJ.
##   VADJ = 2.5 V (HR bank, e.g. AC701, Nexys Video):  IOSTD_DIFF = LVDS_25, IOSTD_SE = LVCMOS25
##   VADJ = 1.8 V (HP bank, e.g. KC705 LPC):           IOSTD_DIFF = LVDS,    IOSTD_SE = LVCMOS18
## RX_OUT is terminated inside the FPGA (DIFF_TERM, rx_fpga_top parameter): both
## cases above allow it.  Other VADJ values: DIFF_TERM = "FALSE" and the DNP
## 100 Ohm R43 fitted across RX_OUT on the receiver board (a source-end
## termination: acceptable only for a short FMC route, check the eye on the bench).
##
## Clocking: the 480 MHz BUFIO and the BUFR must sit in the clock region of the
## RX_OUT / SQUELCH_A / DISC_A bank, and the MMCM must drive them directly:
## place the MMCM in that clock region, e.g.
##   set_property LOC MMCME2_ADV_X1Y1 [get_cells u_mmcm]
## (ISERDESE2 at 960 Mb/s: Artix-7 HR bank -2 or -3; Kintex-7 HP bank any grade.)

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
# set_property PACKAGE_PIN <PIN> [get_ports rx_out_p]       ;# LA02_P      H7
# set_property PACKAGE_PIN <PIN> [get_ports rx_out_n]       ;# LA02_N      H8
# set_property PACKAGE_PIN <PIN> [get_ports squelch_a]      ;# LA03_P      G9
# set_property PACKAGE_PIN <PIN> [get_ports disc_a]         ;# LA03_N      G10
# set_property PACKAGE_PIN <PIN> [get_ports rx_en]          ;# LA04_P      H10
# set_property PACKAGE_PIN <PIN> [get_ports hs_term_en]     ;# LA04_N      H11
# set_property PACKAGE_PIN <PIN> [get_ports dac_cs_n]       ;# LA05_P      D11
# set_property PACKAGE_PIN <PIN> [get_ports dac_sck]        ;# LA05_N      D12
# set_property PACKAGE_PIN <PIN> [get_ports dac_sdi]        ;# LA06_P      C10
# set_property PACKAGE_PIN <PIN> [get_ports vbus_det]       ;# LA06_N      C11

set_property IOSTANDARD $IOSTD_DIFF [get_ports {rx_out_p rx_out_n}]
set_property IOSTANDARD $IOSTD_SE   [get_ports {squelch_a disc_a rx_en hs_term_en dac_cs_n dac_sck dac_sdi vbus_det}]

# ---- timing ----
# RX_OUT, SQUELCH_A and DISC_A are asynchronous to the FPGA clocks: they are
# oversampled by the ISERDESE2s, not captured with a setup / hold window.
set_false_path -from [get_ports {rx_out_p rx_out_n squelch_a disc_a vbus_det uart_rxd rst_btn}]
set_false_path -to   [get_ports {rx_en hs_term_en dac_cs_n dac_sck dac_sdi uart_txd led_*}]
# 120 MHz capture domain (BUFR) <-> 60 MHz system domain: 2-FF synchronizers,
# Gray-coded counters, the dual-port BRAM is read only after `done`.
set_clock_groups -asynchronous \
    -group [get_clocks -of_objects [get_pins u_bufr/O]] \
    -group [get_clocks -of_objects [get_pins u_mmcm/CLKOUT2]]
