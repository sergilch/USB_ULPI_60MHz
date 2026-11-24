#!/bin/sh
# run_sim.sh - Icarus simulation of the receiver-board FPGA design, then the PC
# decoder on the captured data (pass/fail: the last TEST PASSED / TEST FAILED line)
set -e
cd "$(dirname "$0")"
python3 gen_vectors.py
iverilog -g2005 -DRX_SIM -o sim_rxfpga -I. prims_sim.v ../rtl/rx_sampler_7s.v ../rtl/rx_capture.v \
    ../rtl/rx_ctrl.v ../rtl/rx_fpga_top.v tb_rx_fpga_top.v
vvp -n sim_rxfpga | tee sim_rxfpga.log | tail -${TAIL:-20}
if grep -q "^TEST PASSED" sim_rxfpga.log; then
    if python3 ../../host/rx_decode.py capture.txt --expect expected.json; then
        echo "TEST PASSED"
    else
        echo "TEST FAILED: decoder"
    fi
else
    echo "TEST FAILED: testbench"
fi
