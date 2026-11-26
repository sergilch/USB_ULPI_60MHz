## cdr_board_fmc.xdc - pin and timing constraints of cdr_fpga_top for the
## discrete USB 2.0 CDR board on an FMC LPC carrier (AMD 7-Series).
##
## The FMC signal of every port is fixed by the CDR board (schematic sheet 1,
## connector J1; doc/cdr_board.md section 4.7).  The FPGA package pin depends on
## the carrier: copy it from the carrier's master XDC (e.g. "FMC_LPC_CLK0_M2C_P").
##
## CLK0_M2C (CLK_RX) drives BUFIO / BUFR: it must land on a clock-capable (MRCC /
## SRCC) pin in the same bank as LA00 (HS_RXD); this holds on the common LPC
## carriers (AC701, KC705, Nexys Video, ZC702) but check the carrier's pinout.
##
## I/O standard: LA / CLK pins sit in the carrier's VADJ bank.
##   VADJ = 2.5 V (HR bank, AC701, Nexys Video): IOSTD_DIFF = LVDS_25, IOSTD_SE = LVCMOS25
##   VADJ = 1.8 V (HP bank, KC705 LPC):          IOSTD_DIFF = LVDS,    IOSTD_SE = LVCMOS18
## CLK_RX / HS_RXD are AC-coupled and biased to 1.25 V on the board; they need
## the FPGA's 100 Ohm DIFF_TERM (set in the RTL and below).  DPAT is an LVDS
## output (the board terminates it with 100 Ohm and AC-couples it into the EP57).

set IOSTD_DIFF LVDS_25
set IOSTD_SE   LVCMOS25

# ---- board clock / reset / UART / LEDs (carrier specific) ----
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports clkin_p]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports clkin_n]   ;# differential clocks only
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports rst_btn]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports uart_rxd]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports uart_txd]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports led_alive]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports led_ok]
create_clock -period 10.000 -name clkin [get_ports clkin_p]          ;# 100 MHz oscillator

# ---- FMC LPC (VITA 57.1) ----          port            FMC signal    FMC pin
# set_property PACKAGE_PIN <PIN> [get_ports clk_rx_p]     ;# CLK0_M2C_P   H4
# set_property PACKAGE_PIN <PIN> [get_ports clk_rx_n]     ;# CLK0_M2C_N   H5
# set_property PACKAGE_PIN <PIN> [get_ports hs_rxd_p]     ;# LA00_P_CC    G6
# set_property PACKAGE_PIN <PIN> [get_ports hs_rxd_n]     ;# LA00_N_CC    G7
# set_property PACKAGE_PIN <PIN> [get_ports dpat_p]       ;# LA01_P_CC    D8
# set_property PACKAGE_PIN <PIN> [get_ports dpat_n]       ;# LA01_N_CC    D9
# set_property PACKAGE_PIN <PIN> [get_ports cdr_en]       ;# LA02_P       H7
# set_property PACKAGE_PIN <PIN> [get_ports cdr_set]      ;# LA02_N       H8
# set_property PACKAGE_PIN <PIN> [get_ports dsel0]        ;# LA03_P       G9
# set_property PACKAGE_PIN <PIN> [get_ports dsel1]        ;# LA03_N       G10
# set_property PACKAGE_PIN <PIN> [get_ports vco_off]      ;# LA04_P       H10
# set_property PACKAGE_PIN <PIN> [get_ports csw_ext]      ;# LA04_N       H11
# set_property PACKAGE_PIN <PIN> [get_ports dac_cs_n]     ;# LA05_P       D11
# set_property PACKAGE_PIN <PIN> [get_ports adc_cs_n]     ;# LA05_N       D12
# set_property PACKAGE_PIN <PIN> [get_ports spi_sck]      ;# LA06_P       C10
# set_property PACKAGE_PIN <PIN> [get_ports spi_sdi]      ;# LA06_N       C11
# set_property PACKAGE_PIN <PIN> [get_ports adc_sdo]      ;# LA07_P       H13
# set_property PACKAGE_PIN <PIN> [get_ports csw_dac]      ;# LA07_N       H14

set_property -dict [list IOSTANDARD $IOSTD_DIFF DIFF_TERM TRUE] \
    [get_ports {clk_rx_p clk_rx_n hs_rxd_p hs_rxd_n}]
set_property IOSTANDARD $IOSTD_DIFF [get_ports {dpat_p dpat_n}]
set_property IOSTANDARD $IOSTD_SE [get_ports {cdr_en cdr_set dsel0 dsel1 vco_off csw_ext csw_dac \
    dac_cs_n adc_cs_n spi_sck spi_sdi adc_sdo}]

# ---- timing ----
create_clock -period 2.083 -name clk_rx [get_ports clk_rx_p]         ;# 480 MHz recovered clock
# BUFR /8 (clk_rxw) is derived by Vivado from the BUFR_DIVIDE attribute.
# HS_RXD is launched by the board on the CLK_RX rising edge (EP29 tpd 0.42 ns
# + NB6L14 output skew); the capture is tuned with IDLY (eye scan, doc 8.3),
# so the input delay is only a sanity bound, not a sign-off.
# Window 0.25 .. 0.65 ns = EP29 tpd 0.42 ns typ +- 0.15 ns, Q1/Q2 skew <= 20 ps,
# matched traces.  Tap 0 fails hold by ~1.3 ns (BUFIO clock ~2.8 ns after the
# pin, data ~1.45 ns); Vivado times the IDELAY at IDELAY_VALUE = IDLY0 = 19.
set_input_delay -clock clk_rx -max 0.65 [get_ports {hs_rxd_p}]
set_input_delay -clock clk_rx -min 0.25 [get_ports {hs_rxd_p}]
# System clock domain <-> CLK_RX domain: toggle handshakes, 2-FF synchronisers,
# Gray-coded FCNT counter; TXLEN is static during a test.
set_clock_groups -asynchronous \
    -group [get_clocks -include_generated_clocks clk_rx] \
    -group [get_clocks -include_generated_clocks clkin]
set_false_path -from [get_ports {adc_sdo uart_rxd rst_btn}]
set_false_path -to   [get_ports {cdr_en cdr_set dsel* vco_off csw_* dac_cs_n adc_cs_n spi_* uart_txd led_*}]
