#-----------------------------------------------------------------------------
# usb_phy.sdc - timing constraints (Plan_60MHz.md P1 / P9, 3.1 / 3.4; WORK_PLAN 9.1)
#
# Status (P9): clocks, generated clocks, the clk60 <-> clk_bit boundary rule,
# the clock-domain crossings (asynchronous groups, Gray-FIFO max-delay), the
# ULPI I/O constraints relative to the CLK pin, the AFE pin constraints and
# the exceptions of the boundary rule.  Values marked "placeholder" have no
# source yet (pad delays: the pad model carries no timing; CDR output timing:
# Q1 / Q2 of DOC/afe_interface_spec.md) and must be replaced for sign-off.
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
#   clkout   ULPI CLKOUT, rising-edge flop in usb_clk_gen (generated, /8),
#            CKO_LEAD clk_bit cycles before E0.
#            Only a reference for the ULPI I/O constraints, it clocks no flop.
#   clk_rx   480 MHz +- 1000 ppm CDR clock, asynchronous to clk_bit.  Timed at
#            +1000 ppm (period 2.081 ns).
#   clk_rxw  HS word clock, clk_rx / 8, a flop in usb_rx_hs_sipo (generated).
#            Writes the HS word FIFO; same boundary rule against clk_rx as
#            clk60 against clk_bit (word register on phase 3 = E4, clk_rxw
#            rises on E0), so clk_rx -> clk_rxw is a 4 / 3 multicycle.
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
#   Exception: the PISO clamp flop cq (usb_tx_piso) samples the clk60 levels
#   drv_dis / iso_en on every clk_bit edge (a level control, registered once),
#   so clk60 -> cq is a single-cycle clk_bit path, not 4 / 3 (see below).
#
# Since Plan_60MHz.md P9 no ce60-enabled logic is left (the tick enable is
# gone from usb_clk_gen and from every leaf that only ran with ce = 1; the
# leaves that keep a ce port for their stall tests get ce = 1 in the design).
#-----------------------------------------------------------------------------

set T_BIT   2.0833
set T_RX    [expr {$T_BIT / 1.001}]
set T_60    [expr {8.0 * $T_BIT}]
set T_REF   41.6667

# Tool-specific design queries.  These are the OpenSTA versions; a flow can
# define its own procs with the same names before it reads this file, and
# they are then kept (Genus: syn/genus_synth.tcl, get_db versions).
#   usb_net_driver net       driver pin of a net (the flop output in a
#                            flattened netlist), or "" if the net does not exist
#   usb_port_is_input port   1 if the port exists and is an input
#   usb_driver_cells pats    one element per net matching the patterns
#                            (hierarchical search) that has a driver pin: the
#                            driving cell(s)
if {[info procs usb_net_driver] eq ""} {
    proc usb_net_driver {net} {
        set n [get_nets -quiet $net]
        if {[llength $n] == 0} { return "" }
        return [get_pins -of_objects $n -filter "direction == output"]
    }
}
if {[info procs usb_port_is_input] eq ""} {
    proc usb_port_is_input {port} {
        if {[llength [get_ports -quiet $port]] == 0} { return 0 }
        return [expr {[get_property [get_ports $port] direction] == "input"}]
    }
}
if {[info procs usb_driver_cells] eq ""} {
    proc usb_driver_cells {pats} {
        set res {}
        foreach n [get_nets -quiet -hierarchical $pats] {
            set drv [get_pins -quiet -of_objects $n -filter "direction == output"]
            if {[llength $drv]} { lappend res [get_cells -of_objects $drv] }
        }
        return $res
    }
}

set has_bit 0
if {[llength [get_ports -quiet clk_bit]]} {
    create_clock -name clk_bit -period $T_BIT [get_ports clk_bit]
    set has_bit 1
}

set has_60 0
if {[usb_port_is_input clk60]} {
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
        # rising-edge flop (P9), 4 + 4 periods; its lead against clk60 is
        # CKO_LEAD below (the generated clock is only a reference)
        create_generated_clock -name clkout -source [get_ports clk_bit] \
            -edges {1 9 17} $drv
    }
}

set has_rx 0
set has_rxw 0
if {[llength [get_ports -quiet clk_rx]]} {
    create_clock -name clk_rx -period $T_RX [get_ports clk_rx]
    set has_rx 1
    set drv [usb_net_driver clk_rxw]
    if {$drv != ""} {
        create_generated_clock -name clk_rxw -source [get_ports clk_rx] -divide_by 8 $drv
        set has_rxw 1
        set_multicycle_path -setup -start 4 -from [get_clocks clk_rx] -to [get_clocks clk_rxw]
        set_multicycle_path -hold  -start 3 -from [get_clocks clk_rx] -to [get_clocks clk_rxw]
    }
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

# ---------------------------------------------------------------------------
# Clock-domain crossings
#   ref_clk: asynchronous to everything (2-FF synchronizers only).
#   clk_rx / clk_rxw <-> clk_bit: no paths (cut).
#   clk_rx / clk_rxw <-> clk60: the HS word FIFO (Gray pointers through 2-FF
#     synchronizers, memory read after the synchronized write pointer) and
#     2-FF synchronizers.  Not cut: every such path is bounded by one clk_rxw
#     period (set_max_delay, ideal clocks, so it is a datapath bound), which
#     keeps the Gray-bus skew below one write-clock period and the memory read
#     inside the two synchronizer cycles; hold is not meaningful there.
set T_RXW [expr {8.0 * $T_RX}]
set sync_grp {}
foreach c {clk_bit clk60 clkout ulpi_clk} {
    if {[llength [get_clocks -quiet $c]]} { lappend sync_grp $c }
}
set rx_grp {}
foreach c {clk_rx clk_rxw} {
    if {[llength [get_clocks -quiet $c]]} { lappend rx_grp $c }
}
if {$has_ref && ([llength $sync_grp] || [llength $rx_grp])} {
    set_clock_groups -name usb_async_ref -asynchronous -group {ref_clk} \
        -group [concat $sync_grp $rx_grp]
}
if {[llength $rx_grp]} {
    foreach c {clk_bit clkout ulpi_clk} {
        if {[llength [get_clocks -quiet $c]]} {
            set_false_path -from [get_clocks $rx_grp] -to [get_clocks $c]
            set_false_path -from [get_clocks $c] -to [get_clocks $rx_grp]
        }
    }
    if {$has_60} {
        set_max_delay $T_RXW -from [get_clocks $rx_grp] -to [get_clocks clk60]
        set_max_delay $T_RXW -from [get_clocks clk60] -to [get_clocks $rx_grp]
        set_false_path -hold -from [get_clocks $rx_grp] -to [get_clocks clk60]
        set_false_path -hold -from [get_clocks clk60] -to [get_clocks $rx_grp]
    }
}

# ---------------------------------------------------------------------------
# clk_rx island reset release (usb_afe_rx_if, usb_rx_hs_sipo; Plan_60MHz.md P9)
#   Each island's clk_rx reset synchronizer has two second-stage copies that
#   release on the same edge.  rst_rx_n resets the few flops whose D input can
#   differ from their reset value at the first clk_rx edge after the release
#   (single-cycle recovery, as by default).  rst_rx_m_n (usb_afe_rx_if: and
#   its equal copy rst_rx_m2_n, fan-out) resets only flops whose
#   D equals their reset value at that edge (module headers), so a release
#   that lands one edge late cannot change them: recovery / removal as a
#   2-cycle path from that flop.  The fan-out of rst_rx_m_n (up to ~25) at
#   480 MHz does not fit one cycle even with an ideal buffer tree.
foreach c [usb_driver_cells {rst_rx_m_n *.rst_rx_m_n rst_rx_m2_n *.rst_rx_m2_n}] {
    set_multicycle_path -setup 2 -from $c
    set_multicycle_path -hold  1 -from $c
}

# ---------------------------------------------------------------------------
# Boundary-rule exception: PISO clamp flop (usb_tx_piso cq, Plan_60MHz.md 8.9)
#   drv_dis / iso_en are clk60 levels, sampled by cq on every clk_bit edge:
#   single cycle (undo the 4 / 3 boundary multicycle for this endpoint).  Only
#   matters in a top level that has both clk60 logic and the PISO.
if {$has_60 && $has_bit} {
    foreach c [usb_driver_cells {*u_piso.cq cq}] {
        set_multicycle_path -setup -end 1 -from [get_clocks clk60] -to $c
        set_multicycle_path -hold  -end 0 -from [get_clocks clk60] -to $c
    }
}

# ---------------------------------------------------------------------------
# ULPI I/O (output-clock mode, ULPI 1.1 Table 5: the PHY drives CLK)
#   At the PHY pins: Link -> PHY setup 6.0 ns / hold 0.0 ns before / after
#   the CLK edge; PHY -> Link output delay <= 9.0 ns after the CLK edge; the
#   PHY outputs must not change before the CLK edge (the Link's 0.0 ns hold).
#   The CLK pin edge c_k lies delta = CKO_FF + PAD_OUT - CKO_LEAD * T_BIT
#   after the clk60 edge E0_k (CLKOUT is a rising-edge clk_bit flop CKO_LEAD
#   cycles before E0; usb_clk_gen parameter CKO_LEAD, Plan_60MHz.md K2 / P9).
#   Budgets at the core: inputs 6.0 - delta - PAD_IN, outputs 9.0 - PAD_OUT
#   + delta; PHY input hold needs delta > -PAD_IN (min).  CKO_LEAD = 2 with
#   the placeholders below: delta = -0.37 ns.  The virtual clock ulpi_clk models the
#   CLK pin edge.  The core launches ULPI outputs on E0_k for the Link to
#   sample on c_(k+1), and samples ULPI inputs launched on c_k at E0_(k+1);
#   the setup multicycles below pick those edges for either sign of delta.
#   They correct the edge choice (the default pair is only |delta| apart), so
#   hold stays at its default, one period before the setup edge: inputs are
#   held against E0_k, outputs against c_k (no -hold multicycle).
#   Placeholders: PAD_IN / PAD_OUT (BBSUD8F, no timing model here) and CKO_FF
#   (CLKOUT flop clock-to-Q, slow-corner X1 value).  No board delay.
set ULPI_TSU  6.0
set ULPI_TH   0.0
set ULPI_TCO  9.0
set PAD_IN    1.0
set PAD_OUT   3.0
set CKO_FF    0.8
set CKO_LEAD  2                ;# must match usb_clk_gen CKO_LEAD
set ulpi_in  [get_ports -quiet {ulpi_data_in* ulpi_stp}]
set ulpi_out [get_ports -quiet {ulpi_data_out* ulpi_data_oe ulpi_dir ulpi_nxt}]
if {$has_60 && ([llength $ulpi_in] || [llength $ulpi_out])} {
    set delta [expr {$CKO_FF + $PAD_OUT - $CKO_LEAD * $T_BIT}]
    set r [expr {fmod($delta + 10.0 * $T_60, $T_60)}]
    create_clock -name ulpi_clk -period $T_60 -waveform [list $r [expr {$r + $T_60 / 2.0}]]
    if {[llength $ulpi_in]} {
        # data at the PHY pin: >= c_k + TH, <= c_(k+1) - TSU; the input pad adds PAD_IN
        set_input_delay -clock ulpi_clk -max [expr {$T_60 - $ULPI_TSU + $PAD_IN}] $ulpi_in
        set_input_delay -clock ulpi_clk -min [expr {$ULPI_TH + $PAD_IN}] $ulpi_in
        if {$delta < 0} {
            set_multicycle_path -setup 2 -from [get_clocks ulpi_clk] -to [get_clocks clk60]
        }
    }
    if {[llength $ulpi_out]} {
        # at the PHY pin: <= c_k + TCO for the Link edge c_(k+1), and not before c_k
        set_output_delay -clock ulpi_clk -max [expr {$T_60 - $ULPI_TCO + $PAD_OUT}] $ulpi_out
        set_output_delay -clock ulpi_clk -min [expr {$PAD_OUT - $ULPI_TH}] $ulpi_out
        if {$delta >= 0} {
            set_multicycle_path -setup 2 -from [get_clocks clk60] -to [get_clocks ulpi_clk]
        }
    }
}

# ---------------------------------------------------------------------------
# AFE pins (DOC/afe_interface_spec.md 3, 4.1, 4.2)
#   TX pins: each is a usb_tx_piso flop (at most one gate, spec 4.1); the AFE
#     input is taken as a capture point one clk_bit period later
#     (AFE_TX_SU placeholder = 0: flop -> pin within the cycle).
#   hs_rxd_a: CDR retimed data, launched by the CDR on the rising clk_rx edge;
#     CDR_CO_MAX / CDR_CO_MIN placeholders (Q1 / Q2) until the CDR has numbers.
#   Asynchronous AFE status inputs (squelch, disconnect, FS/LS receivers, VBUS /
#     ID) go to 2-FF synchronizers or the FS/LS sampler: false paths.
set AFE_TX_SU  0.0
set CDR_CO_MAX 0.5
set CDR_CO_MIN 0.1
set afe_tx [get_ports -quiet {hs_tx_p hs_tx_n hs_tx_en fs_oe fs_dat fs_se0 fs_ls}]
if {$has_bit && [llength $afe_tx]} {
    set_output_delay -clock clk_bit -max $AFE_TX_SU $afe_tx
    set_output_delay -clock clk_bit -min 0.0 $afe_tx
}
set cdr_in [get_ports -quiet {hs_rxd_a}]
if {$has_rx && [llength $cdr_in]} {
    set_input_delay -clock clk_rx -max $CDR_CO_MAX $cdr_in
    set_input_delay -clock clk_rx -min $CDR_CO_MIN $cdr_in
}
set afe_async [get_ports -quiet {squelch_a squelch disc rxdp rxdm rxrcv a_vbus_vld sess_vld sess_end id_gnd}]
if {[llength $afe_async]} { set_false_path -from $afe_async }

# Ideal clocks before CTS; a margin for jitter and skew.
foreach c [all_clocks] { set_clock_uncertainty 0.05 $c }

# Open for sign-off (WORK_PLAN 9.1): real pad / CDR numbers for the
# placeholders above; propagated clocks, CTS skew and the clk60 / clk_bit
# phase after CTS (Plan_60MHz.md K3); the full-chip top with the pads.
