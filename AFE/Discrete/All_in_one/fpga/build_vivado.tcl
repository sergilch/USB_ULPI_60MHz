# build_vivado.tcl - non-project Vivado build of aio_fpga_top for the ZedBoard
#   vivado -mode batch -source build_vivado.tcl [-tclargs <part>]
#   default part xc7z020clg484-2 (ZedBoard Rev D.2 with the -2 grade; the RX
#   sampler's 2 x 960 Mb/s ISERDESE2 and the PLL block's 480 MHz BUFG do not
#   meet the -1 limits, DS187)
# Regenerate the XDC first when the board pin map changed: python3 gen_xdc.py
# The design is PL only (no PS7 instance): load the bitstream over JTAG
# (Hardware Manager); the ZedBoard boot-mode jumpers JP7-JP11 on JTAG is simplest.
set part [expr {[llength $argv] > 0 ? [lindex $argv 0] : "xc7z020clg484-2"}]
set here [file dirname [file normalize [info script]]]
set disc [file normalize $here/../..]
set root [file normalize $here/../../../..]
file mkdir $here/build
read_verilog [list \
    $disc/Transmitter/fpga/rtl/tx_ctrl.v $disc/Transmitter/fpga/rtl/tx_seq.v $disc/Transmitter/fpga/rtl/tx_piso_7s.v \
    $disc/Receiver/fpga/rtl/rx_ctrl.v $disc/Receiver/fpga/rtl/rx_sampler_7s.v $disc/Receiver/fpga/rtl/rx_capture.v \
    $disc/PLL/fpga/rtl/pll_ctrl.v $disc/PLL/fpga/rtl/pll_meas.v \
    $disc/CDR/fpga/rtl/cdr_ctrl.v $disc/CDR/fpga/rtl/cdr_txgen.v $disc/CDR/fpga/rtl/cdr_rxchk.v \
    $root/usb_bit_stuffer.v $root/usb_nrzi_encoder.v $root/usb_tx_serializer8.v $root/usb_tx_path.v \
    $root/usb_afe_tx_if8.v $root/usb_rx_decoder8.v $root/usb_clk_gen.v $root/usb_pll_lock_det.v \
    $here/rtl/aio_glue.v $here/rtl/aio_tx_blk.v $here/rtl/aio_rx_blk.v $here/rtl/aio_pll_blk.v \
    $here/rtl/aio_cdr_blk.v $here/rtl/aio_fpga_top.v]
read_xdc $here/constraints/aio_zedboard.xdc
synth_design -top aio_fpga_top -part $part
opt_design; place_design; phys_opt_design; route_design
report_clock_utilization -file $here/build/clock_util.rpt
report_timing_summary    -file $here/build/timing.rpt
report_utilization       -file $here/build/util.rpt
report_io                -file $here/build/io.rpt
write_bitstream -force $here/build/aio_fpga_top.bit
