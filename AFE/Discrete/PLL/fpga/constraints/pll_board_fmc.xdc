## pll_board_fmc.xdc - pin and timing constraints of pll_fpga_top for the
## discrete USB 2.0 PLL board on an FMC LPC carrier (AMD 7-Series).
##
## The FMC signal of every port is fixed by the PLL board (schematic sheet 1,
## connector J1; doc/pll_board.md section 4.7).  The FPGA package pin depends on
## the carrier: copy it from the carrier's master XDC (e.g. "FMC_LPC_CLK0_M2C_P").
##
## I/O standard: LA / CLK pins sit in the carrier's VADJ bank.
##   VADJ = 2.5 V (HR bank, AC701, Nexys Video): IOSTD_DIFF = LVDS_25, IOSTD_SE = LVCMOS25
##   VADJ = 1.8 V (HP bank, KC705 LPC):          IOSTD_DIFF = LVDS,    IOSTD_SE = LVCMOS18
## CLK_BIT_A / CLK60_A are AC-coupled and biased to 1.25 V on the board; they
## need the FPGA's 100 Ohm DIFF_TERM (set below).
## 480 MHz on a BUFG: Artix-7 -2 / -3 or Kintex-7 (doc section 7).

set IOSTD_DIFF LVDS_25
set IOSTD_SE   LVCMOS25

# ---- board clock / reset / UART / LEDs (carrier specific) ----
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports clkin_p]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports clkin_n]   ;# differential clocks only
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports rst_btn]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports uart_rxd]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports uart_txd]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports led_locked]
# set_property -dict {PACKAGE_PIN <PIN> IOSTANDARD <STD>} [get_ports led_pll]
create_clock -period 10.000 -name clkin [get_ports clkin_p]          ;# 100 MHz oscillator

# ---- FMC LPC (VITA 57.1) ----          port            FMC signal    FMC pin
# set_property PACKAGE_PIN <PIN> [get_ports clk_bit_a_p]  ;# CLK0_M2C_P   H4
# set_property PACKAGE_PIN <PIN> [get_ports clk_bit_a_n]  ;# CLK0_M2C_N   H5
# set_property PACKAGE_PIN <PIN> [get_ports clk60_a_p]    ;# CLK1_M2C_P   G2
# set_property PACKAGE_PIN <PIN> [get_ports clk60_a_n]    ;# CLK1_M2C_N   G3
# set_property PACKAGE_PIN <PIN> [get_ports ref_dig]      ;# LA00_P_CC    G6
# set_property PACKAGE_PIN <PIN> [get_ports muxout]       ;# LA00_N_CC    G7
# set_property PACKAGE_PIN <PIN> [get_ports adf_clk]      ;# LA01_P_CC    D8
# set_property PACKAGE_PIN <PIN> [get_ports adf_data]     ;# LA01_N_CC    D9
# set_property PACKAGE_PIN <PIN> [get_ports adf_le]       ;# LA02_P       H7
# set_property PACKAGE_PIN <PIN> [get_ports adf_ce]       ;# LA02_N       H8
# set_property PACKAGE_PIN <PIN> [get_ports vco_off]      ;# LA03_P       G9
# set_property PACKAGE_PIN <PIN> [get_ports lf_dis]       ;# LA03_N       G10
# set_property PACKAGE_PIN <PIN> [get_ports ol_en]        ;# LA04_P       H10
# set_property PACKAGE_PIN <PIN> [get_ports cdcm_off]     ;# LA04_N       H11
# set_property PACKAGE_PIN <PIN> [get_ports dac_cs_n]     ;# LA05_P       D11
# set_property PACKAGE_PIN <PIN> [get_ports adc_cs_n]     ;# LA05_N       D12
# set_property PACKAGE_PIN <PIN> [get_ports spi_sck]      ;# LA06_P       C10
# set_property PACKAGE_PIN <PIN> [get_ports spi_sdi]      ;# LA06_N       C11
# set_property PACKAGE_PIN <PIN> [get_ports adc_sdo]      ;# LA07_P       H13
# set_property PACKAGE_PIN <PIN> [get_ports refsrc0]      ;# LA07_N       H14
# set_property PACKAGE_PIN <PIN> [get_ports refsrc1]      ;# LA08_P       G12
# set_property PACKAGE_PIN <PIN> [get_ports oe24]         ;# LA08_N       G13
# set_property PACKAGE_PIN <PIN> [get_ports oe19]         ;# LA09_P       D14

set_property -dict [list IOSTANDARD $IOSTD_DIFF DIFF_TERM TRUE] \
    [get_ports {clk_bit_a_p clk_bit_a_n clk60_a_p clk60_a_n}]
set_property IOSTANDARD $IOSTD_SE [get_ports {ref_dig muxout adf_clk adf_data adf_le adf_ce vco_off \
    lf_dis ol_en cdcm_off dac_cs_n adc_cs_n spi_sck spi_sdi adc_sdo refsrc0 refsrc1 oe24 oe19}]

# ---- timing ----
create_clock -period 2.083 -name clk_bit_a [get_ports clk_bit_a_p]   ;# 480 MHz
create_clock -period 16.667 -name clk60_a  [get_ports clk60_a_p]     ;# 60 MHz (board /8)
create_clock -period 41.667 -name ref_dig  [get_ports ref_dig]       ;# 24 MHz (19.2 / 26 also fit)
# usb_clk_gen's clk60 (BUFG) is a generated clock of clk_bit_a (/8)
create_generated_clock -name clk60_gen -source [get_ports clk_bit_a_p] -divide_by 8 \
    [get_pins -hierarchical -filter {NAME =~ *u_cg*clk60_reg/Q}]
# The 60 <-> 480 boundary of usb_clk_gen: transfers on ld (E4), as in
# constraints/usb_phy.sdc of the PHY (multicycle 4 / 3).
set_multicycle_path -setup 4 -from [get_clocks clk60_gen] -to [get_clocks clk_bit_a]
set_multicycle_path -hold  3 -from [get_clocks clk60_gen] -to [get_clocks clk_bit_a]
set_multicycle_path -setup 4 -from [get_clocks clk_bit_a] -to [get_clocks clk60_gen] -end
set_multicycle_path -hold  3 -from [get_clocks clk_bit_a] -to [get_clocks clk60_gen] -end
# Everything else between clock domains goes through 2-FF synchronizers / toggle flags.
set_clock_groups -asynchronous \
    -group [get_clocks -include_generated_clocks clk_bit_a] \
    -group [get_clocks clk60_a] -group [get_clocks ref_dig] \
    -group [get_clocks -of_objects [get_pins u_mmcm/CLKOUT0]]
# CLK60_A as data into the clk_bit sampler (phase check): asynchronous by design.
set_false_path -to [get_pins -hierarchical -filter {NAME =~ *u_meas*bs_reg[0]/D}]
set_false_path -from [get_ports {muxout adc_sdo uart_rxd rst_btn}]
set_false_path -to   [get_ports {adf_* vco_off lf_dis ol_en cdcm_off dac_cs_n adc_cs_n spi_* refsrc* oe* uart_txd led_*}]
