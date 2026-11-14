#-----------------------------------------------------------------------------
# usb_phy.sdc - timing constraints skeleton (Plan_60MHz.md P1, 3.1 / 3.4; WORK_PLAN 9.1)
#
# Status: skeleton.  Clocks, generated clocks, the clk60 <-> clk_bit boundary
# rule and the asynchronous groups are in; ULPI I/O constraints, AFE pin
# constraints, the Gray-FIFO max-delay and the false paths through the 2-FF
# synchronizers follow with the modules that need them (P5, P8, WORK_PLAN 9.1).
#
# Written to work on any top level of the repository (run_sta.sh reads it for
# each one): a clock is only created if its port / net exists in the design.
#
# Clocks (Plan_60MHz.md 3.1)
#   clk_bit  480 MHz PLL clock (port).
#   clk60    60 MHz core clock.  Inside a design that contains usb_clk_gen it is
#            a generated clock (/8) on the clk60 flop; a top level that takes
#            clk60 as a port gets a primary clock with the same waveform, so
#            the core can be timed standalone.
#   clkout   ULPI CLKOUT, falling-edge flop in usb_clk_gen (generated, /8).
#            Only a reference for the ULPI I/O constraints, it clocks no flop.
#   clk_rx   480 MHz +- 1000 ppm CDR clock, asynchronous to clk_bit.  Timed at
#            +1000 ppm (period 2.081 ns).
#   ref_clk  24 MHz reference (usb_pwr_seq, usb_pll_lock_det), asynchronous.
#
# clk60 <-> clk_bit boundary (usb_clk_gen header, "boundary rule")
#   clk60 launches and samples on E0.  Island registers that the core reads,
#   and island registers that sample core data, change / sample only on ld,
#   i.e. on E4.  So both directions have 4 clk_bit cycles for setup and 4 for
#   hold:
#     clk60 -> clk_bit   setup 4 clk_bit cycles (-end), hold moved back 3
#     clk_bit -> clk60   setup 4 clk_bit cycles (-start), hold moved back 3
#   These multicycles are only correct while every crossing follows the rule.
#
# Legacy ce60 paths (single clk_bit domain, removed by Plan_60MHz.md P2..P9)
#   Paths between ce60-enabled flops really have 8 clk_bit cycles, but they
#   are not constrained as multicycle here: they are timed as single-cycle
#   480 MHz paths, which is pessimistic.  This is deliberate: the baseline
#   shows what the 480 MHz single-clock design asks for, and the violations
#   on those paths go away as the modules move to clk60.
#-----------------------------------------------------------------------------

set T_BIT   2.0833
set T_RX    [expr {$T_BIT / 1.001}]
set T_60    [expr {8.0 * $T_BIT}]
set T_REF   41.6667

# Driver pin of a net (the flop output in a flattened netlist), or "" if the
# net does not exist.
proc usb_net_driver {net} {
    set n [get_nets -quiet $net]
    if {[llength $n] == 0} { return "" }
    return [get_pins -of_objects $n -filter "direction == output"]
}

set has_bit 0
if {[llength [get_ports -quiet clk_bit]]} {
    create_clock -name clk_bit -period $T_BIT [get_ports clk_bit]
    set has_bit 1
}

set has_60 0
if {[llength [get_ports -quiet clk60]] && [get_property [get_ports clk60] direction] == "input"} {
    create_clock -name clk60 -period $T_60 [get_ports clk60]
    set has_60 1
} elseif {$has_bit} {
    set drv [usb_net_driver clk60]
    if {$drv != ""} {
        create_generated_clock -name clk60 -source [get_ports clk_bit] -divide_by 8 $drv
        set has_60 1
    }
    set drv [usb_net_driver clkout]
    if {$drv != ""} {
        # rises and falls on falling clk_bit edges, 4 + 4 periods
        create_generated_clock -name clkout -source [get_ports clk_bit] \
            -edges {2 10 18} $drv
    }
}

set has_rx 0
if {[llength [get_ports -quiet clk_rx]]} {
    create_clock -name clk_rx -period $T_RX [get_ports clk_rx]
    set has_rx 1
}

set has_ref 0
if {[llength [get_ports -quiet ref_clk]]} {
    create_clock -name ref_clk -period $T_REF [get_ports ref_clk]
    set has_ref 1
}

# clk60 <-> clk_bit boundary
if {$has_60 && $has_bit} {
    set_multicycle_path -setup -end   4 -from [get_clocks clk60]   -to [get_clocks clk_bit]
    set_multicycle_path -hold  -end   3 -from [get_clocks clk60]   -to [get_clocks clk_bit]
    set_multicycle_path -setup -start 4 -from [get_clocks clk_bit] -to [get_clocks clk60]
    set_multicycle_path -hold  -start 3 -from [get_clocks clk_bit] -to [get_clocks clk60]
}

# asynchronous clocks (all crossings go through synchronizers / the RX FIFO)
set sync_grp {}
foreach c {clk_bit clk60 clkout} {
    if {[llength [get_clocks -quiet $c]]} { lappend sync_grp $c }
}
set groups {}
if {[llength $sync_grp]} { lappend groups -group $sync_grp }
if {$has_rx}             { lappend groups -group {clk_rx} }
if {$has_ref}            { lappend groups -group {ref_clk} }
if {[llength $groups] > 2} {
    set_clock_groups -name usb_async -asynchronous {*}$groups
}

# Ideal clocks before CTS; a margin for jitter and skew.
foreach c [all_clocks] { set_clock_uncertainty 0.05 $c }

# TODO (WORK_PLAN 9.1 / Plan_60MHz.md P8):
#   * ULPI DATA / DIR / NXT / STP relative to clkout incl. BBSUD8F pad delays
#     (ULPI 1.1: 5 ns setup / 0 ns hold at the PHY);
#   * AFE pins (DOC/afe_interface_spec.md 4.1 / 4.2);
#   * set_max_delay -datapath_only on the RX word-FIFO Gray pointers (P5);
#   * false paths into the first flop of each 2-FF synchronizer.
