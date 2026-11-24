# build_vivado.tcl - non-project Vivado build of tx_fpga_top
#   vivado -mode batch -source build_vivado.tcl -tclargs <part> [<clkin_mhz> <mmcm_mult> <mmcm_div> <clkin_diff>]
#   e.g.  -tclargs xc7a200tfbg676-2                 (AC701, 200 MHz differential: 200 24 5 1)
#         -tclargs xc7a200tsbg484-1 100 48 5 0       (Nexys Video, 100 MHz)
# Edit constraints/tx_board_fmc.xdc (package pins of the carrier) first.
set part [lindex $argv 0]
set clk  [expr {[llength $argv] > 1 ? [lindex $argv 1] : 100.0}]
set mul  [expr {[llength $argv] > 2 ? [lindex $argv 2] : 48.0}]
set div  [expr {[llength $argv] > 3 ? [lindex $argv 3] : 5}]
set dif  [expr {[llength $argv] > 4 ? [lindex $argv 4] : 0}]
set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../..]
file mkdir $here/build
read_verilog [list $here/rtl/tx_ctrl.v $here/rtl/tx_seq.v $here/rtl/tx_piso_7s.v $here/rtl/tx_fpga_top.v \
    $root/usb_bit_stuffer.v $root/usb_nrzi_encoder.v $root/usb_tx_serializer8.v \
    $root/usb_tx_path.v $root/usb_afe_tx_if8.v]
read_xdc $here/constraints/tx_board_fmc.xdc
synth_design -top tx_fpga_top -part $part \
    -generic CLKIN_MHZ=$clk -generic MMCM_MULT=$mul -generic MMCM_DIV=$div -generic CLKIN_DIFF=$dif
opt_design; place_design; route_design
report_timing_summary -file $here/build/timing.rpt
report_utilization    -file $here/build/util.rpt
write_bitstream -force $here/build/tx_fpga_top.bit
