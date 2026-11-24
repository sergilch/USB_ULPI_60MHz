#!/bin/sh
# run_sim.sh - Icarus simulation of the PLL-board FPGA design with a behavioural
# board model (pass/fail: the last TEST PASSED / TEST FAILED line)
set -e
cd "$(dirname "$0")"
R=../../../../..                      # repo root: usb_clk_gen.v, usb_pll_lock_det.v
iverilog -g2005 -DPLL_SIM -o sim_pllfpga prims_sim.v $R/usb_clk_gen.v $R/usb_pll_lock_det.v \
    ../rtl/pll_ctrl.v ../rtl/pll_meas.v ../rtl/pll_fpga_top.v tb_pll_fpga_top.v
vvp -n sim_pllfpga | tee sim_pllfpga.log | tail -${TAIL:-40}
if grep -q "^TEST PASSED" sim_pllfpga.log; then echo "TEST PASSED"; else echo "TEST FAILED: testbench"; fi
