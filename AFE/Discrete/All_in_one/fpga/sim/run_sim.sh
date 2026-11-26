#!/bin/sh
# run_sim.sh - Icarus test of the all-in-one FPGA design (tb_aio_fpga_top.v)
set -e
cd "$(dirname "$0")"
R=../../../../..                      # repo root: afe_cdr_bm.v, usb_*.v
D=../../..                            # AFE/Discrete: the block designs
iverilog -g2005 -DAIO_SIM -DTX_PISO_SIM -o sim_aiofpga prims_sim.v $R/afe_cdr_bm.v \
    $R/usb_bit_stuffer.v $R/usb_nrzi_encoder.v $R/usb_tx_serializer8.v $R/usb_tx_path.v \
    $R/usb_afe_tx_if8.v $R/usb_rx_decoder8.v $R/usb_clk_gen.v $R/usb_pll_lock_det.v \
    $D/Transmitter/fpga/rtl/tx_ctrl.v $D/Transmitter/fpga/rtl/tx_seq.v $D/Transmitter/fpga/rtl/tx_piso_7s.v \
    $D/Receiver/fpga/rtl/rx_ctrl.v $D/Receiver/fpga/rtl/rx_sampler_7s.v $D/Receiver/fpga/rtl/rx_capture.v \
    $D/PLL/fpga/rtl/pll_ctrl.v $D/PLL/fpga/rtl/pll_meas.v \
    $D/CDR/fpga/rtl/cdr_ctrl.v $D/CDR/fpga/rtl/cdr_txgen.v $D/CDR/fpga/rtl/cdr_rxchk.v \
    ../rtl/aio_glue.v ../rtl/aio_tx_blk.v ../rtl/aio_rx_blk.v ../rtl/aio_pll_blk.v ../rtl/aio_cdr_blk.v \
    ../rtl/aio_fpga_top.v tb_aio_fpga_top.v
vvp -n sim_aiofpga | tee sim_aiofpga.log | tail -${TAIL:-40}
if grep -q "^TEST PASSED" sim_aiofpga.log; then echo "TEST PASSED"; else echo "TEST FAILED: testbench"; fi
