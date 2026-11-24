# build_vivado.tcl - non-project Vivado build of pll_fpga_top
#   vivado -mode batch -source build_vivado.tcl -tclargs <part> [<clkin_mhz> <mmcm_mult> <mmcm_div> <clkin_diff>]
#   e.g.  -tclargs xc7a200tfbg676-2 200 6 1 1        (AC701, 200 MHz differential SYSCLK)
#         -tclargs xc7a200tsbg484-2 100 12 1 0       (Nexys Video -2, 100 MHz)
#   VCO = clkin * mmcm_mult / mmcm_div must be 1200 MHz (60 MHz system clock).
# Edit constraints/pll_board_fmc.xdc (package pins of the carrier) first.
set part [lindex $argv 0]
set clk  [expr {[llength $argv] > 1 ? [lindex $argv 1] : 100.0}]
set mul  [expr {[llength $argv] > 2 ? [lindex $argv 2] : 12.0}]
set div  [expr {[llength $argv] > 3 ? [lindex $argv 3] : 1}]
set dif  [expr {[llength $argv] > 4 ? [lindex $argv 4] : 0}]
set here [file dirname [file normalize [info script]]]
set repo [file normalize $here/../../../..]
file mkdir $here/build
read_verilog [list $repo/usb_clk_gen.v $repo/usb_pll_lock_det.v \
    $here/rtl/pll_ctrl.v $here/rtl/pll_meas.v $here/rtl/pll_fpga_top.v]
read_xdc $here/constraints/pll_board_fmc.xdc
synth_design -top pll_fpga_top -part $part \
    -generic CLKIN_MHZ=$clk -generic MMCM_MULT=$mul -generic MMCM_DIV=$div -generic CLKIN_DIFF=$dif
opt_design; place_design; route_design
report_timing_summary -file $here/build/timing.rpt
report_utilization    -file $here/build/util.rpt
write_bitstream -force $here/build/pll_fpga_top.bit
