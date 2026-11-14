# Makefile - test and synthesis entry points (the work is done by the two scripts)
#
#   make            same as make all
#   make test       all testbenches (Icarus Verilog), see run_tests.sh
#   make synth      Yosys synthesis smoke test of the top levels, see run_synth.sh
#   make sta        OpenSTA timing of the top levels, see run_sta.sh (CORNER default slow)
#   make all        test + synth
#   make clean      remove build/
#
# Variables: TB="ulpi_core rx_" selects testbenches, JOBS=n parallel simulations,
# TOPS="usb_ulpi_phy_top" selects top levels, CORNER=typ|slow|fast (xh018 Liberty,
# synthesis), STA_CORNER=slow|typ|fast (timing).

TB     ?=
TOPS   ?=
CORNER ?= typ
STA_CORNER ?= slow

.PHONY: all test synth sta clean

all: test synth

test:
	./run_tests.sh $(TB)

synth:
	CORNER=$(CORNER) ./run_synth.sh $(TOPS)

sta:
	CORNER=$(STA_CORNER) ./run_sta.sh $(TOPS)

clean:
	rm -rf build
