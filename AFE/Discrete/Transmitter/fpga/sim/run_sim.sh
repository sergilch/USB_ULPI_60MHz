#!/bin/sh
# run_sim.sh - Icarus simulation of the transmitter-board FPGA design
# (pass/fail: the last TEST PASSED / TEST FAILED line)
set -e
cd "$(dirname "$0")"
R=../../../../..
iverilog -g2005 -DTX_PISO_SIM -o sim_txfpga -I. prims_sim.v ../rtl/tx_ctrl.v ../rtl/tx_seq.v \
    ../rtl/tx_piso_7s.v ../rtl/tx_fpga_top.v \
    $R/usb_bit_stuffer.v $R/usb_nrzi_encoder.v $R/usb_tx_serializer8.v $R/usb_tx_path.v \
    $R/usb_afe_tx_if8.v tb_tx_fpga_top.v
vvp -n sim_txfpga | tail -${TAIL:-40}
