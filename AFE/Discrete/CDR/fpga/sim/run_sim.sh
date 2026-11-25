#!/bin/sh
# run_sim.sh - Icarus simulation of the CDR-board FPGA design with the repo's
# CDR behavioural model as the board (pass/fail: the last TEST PASSED / TEST FAILED line)
set -e
cd "$(dirname "$0")"
R=../../../../..                      # repo root: afe_cdr_bm.v, usb_tx_path.v, usb_rx_decoder8.v, ...
iverilog -g2005 -DCDR_SIM -o sim_cdrfpga prims_sim.v $R/afe_cdr_bm.v \
    $R/usb_tx_path.v $R/usb_bit_stuffer.v $R/usb_nrzi_encoder.v $R/usb_tx_serializer8.v \
    $R/usb_rx_decoder8.v ../rtl/cdr_ctrl.v ../rtl/cdr_txgen.v ../rtl/cdr_rxchk.v \
    ../rtl/cdr_fpga_top.v tb_cdr_fpga_top.v
vvp -n sim_cdrfpga | tee sim_cdrfpga.log | tail -${TAIL:-40}
if grep -q "^TEST PASSED" sim_cdrfpga.log; then echo "TEST PASSED"; else echo "TEST FAILED: testbench"; fi
