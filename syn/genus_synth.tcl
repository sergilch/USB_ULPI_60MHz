#-----------------------------------------------------------------------------
# genus_synth.tcl - Cadence Genus (Common UI) synthesis of one top level
#
#   Normally started by ../run_genus.sh, which sets the environment:
#     TOP      top level (default usb_ulpi_phy_top), one of the tops of
#              DOC/genus_file_list.txt section 3 / run_synth.sh TOPS
#     CORNER   xh018 Liberty corner for mapping and timing: slow (default),
#              typ, fast
#     OUT      output directory (default build/genus/<TOP>_<CORNER>)
#     FLATTEN  1 (default): flatten after elaboration, hierarchy separator "."
#              (the same names as the Yosys / OpenSTA flow, see below);
#              0: keep the hierarchy (the SDC exceptions on rst_rx_m_n and
#              u_piso.cq are then not found - only for experiments)
#     IO_LIB   Liberty of the BBSUD8F IO cells (IO_CELLS_JIF3V, same corner);
#              required for TOP = usb_ulpi_phy_pads, not in the repository
#     EFFORT   syn_generic / syn_map / syn_opt effort: low, medium (default),
#              high
#   By hand:  genus -batch -files syn/genus_synth.tcl   (from the repo root)
#
# Files: exactly the list of DOC/genus_file_list.txt section 1 (RTL_FILES
#   below, keep both in sync).  All 39 files are read; elaborate picks the
#   modules of TOP.  The script stops if a listed file is missing and warns
#   about usb_*.v files in the repository root that are not in the list.
#
# Flow: single corner, setup only (hold is fixed after CTS):
#   read_libs -> read_hdl -> elaborate -> latch / design checks -> flatten ->
#   read_sdc constraints/usb_phy.sdc -> syn_generic -> syn_map -> syn_opt ->
#   reports, netlist, SDC, SDF.
#
# Constraints: constraints/usb_phy.sdc is shared with OpenSTA.  Its three
#   tool-specific queries (port direction, driver pin of a net, driver cells
#   of nets) are procs that the SDC only defines when the caller has not;
#   the Genus versions are defined below with get_db.  The SDC finds the
#   generated-clock pins (clk60, clkout, clk_rxw) and the exception
#   endpoints (rst_rx_m_n / rst_rx_m2_n, u_piso.cq) by net name in a
#   flattened design with "." as separator, as Yosys writes it; FLATTEN = 1
#   reproduces those names.  After read_sdc the script checks that every
#   clock the top needs was created and lists the exceptions it found.
#
# (* keep *) flops: the clk_rx islands have equal flop copies (reset copies,
#   fan-out replicas; CLAUDE.md "Reset", tb_usb_rx_hs_reset) that must not be
#   merged, so flop / latch merging is switched off for the whole design.
#
# Status: written for Genus 2x Common UI, NOT run here (no Genus in this
#   environment).  Expect to adjust attribute names to the installed version.
#   Confidential: the X-FAB Liberty / LEF files are read from X-FAB/ and the
#   outputs in build/ contain PDK cell names; neither may be committed.
#-----------------------------------------------------------------------------

proc usb_env {name default} {
    if {[info exists ::env($name)] && $::env($name) ne ""} { return $::env($name) }
    return $default
}

# repository root: parent of syn/
set ROOT    [file dirname [file dirname [file normalize [info script]]]]
set TOP     [usb_env TOP usb_ulpi_phy_top]
set CORNER  [usb_env CORNER slow]
set FLATTEN [usb_env FLATTEN 1]
set EFFORT  [usb_env EFFORT medium]
set OUT     [file normalize [usb_env OUT $ROOT/build/genus/${TOP}_$CORNER]]
set IO_LIB  [usb_env IO_LIB ""]
file mkdir $OUT $OUT/reports
cd $ROOT

set_db fail_on_error_mesg true
set_db information_level 7

#-----------------------------------------------------------------------------
# File list (DOC/genus_file_list.txt section 1, leaves first)
#-----------------------------------------------------------------------------
set RTL_FILES {
    usb_clk_gen.v
    usb_pll_lock_det.v
    usb_pwr_seq.v
    usb_rx_status_flt.v
    usb_rx_status_sync.v
    usb_line_state.v

    usb_bit_stuffer.v
    usb_nrzi_encoder.v
    usb_tx_serializer8.v
    usb_tx_path.v
    usb_tx_holding.v
    usb_tx_sync_mux.v
    usb_tx_datapath.v
    usb_afe_tx_if8.v
    usb_tx_piso.v

    usb_rx_hs_frontend.v
    usb_rx_hs_sipo.v
    usb_rx_elastic_buffer.v
    usb_rx_fsls_sampler.v
    usb_rx_fsls_dpll.v
    usb_rx_decoder8.v
    usb_rx_datapath.v
    usb_afe_rx_if.v

    usb_ulpi_input_capture.v
    usb_ulpi_reg_access.v
    usb_ulpi_reg_file.v
    usb_ulpi_burst_mux.v
    usb_ulpi_bus_owner.v
    usb_ulpi_core.v
    usb_ulpi_rx_handler.v
    usb_ulpi_rxcmd_gen.v
    usb_ulpi_out_arbiter.v
    usb_ulpi_rx_path.v
    usb_ulpi_phy_if.v

    usb_afe_trim_regs.v
    usb_mode_term_ctrl.v
    usb_ulpi_phy_top.v
    usb_ulpi_phy_pads.v
    usb_ulpi_tx_top.v
}

set TOPS {usb_ulpi_phy_pads usb_ulpi_phy_top usb_rx_datapath usb_rx_decoder8
          usb_ulpi_tx_top usb_afe_tx_if8 usb_tx_piso usb_afe_rx_if usb_clk_gen
          usb_pll_lock_det usb_rx_status_sync usb_line_state usb_mode_term_ctrl
          usb_pwr_seq usb_afe_trim_regs}
if {[lsearch -exact $TOPS $TOP] < 0} {
    error "TOP '$TOP' is not a synthesis top (DOC/genus_file_list.txt section 3)"
}

foreach f $RTL_FILES {
    if {![file exists $ROOT/$f]} { error "file of the list missing: $f" }
}
foreach f [glob -nocomplain -tails -directory $ROOT usb_*.v] {
    if {[lsearch -exact $RTL_FILES $f] < 0} {
        puts "WARNING: $f is not in the file list (DOC/genus_file_list.txt, syn/genus_synth.tcl)"
    }
}

#-----------------------------------------------------------------------------
# Libraries (X-FAB xh018, confidential)
#-----------------------------------------------------------------------------
set LIBDIR $ROOT/X-FAB/xh018_lib
set LIB [glob -nocomplain $LIBDIR/D_CELLS_JIHD_LPMOS_${CORNER}_*.lib]
if {[llength $LIB] != 1} {
    error "no (unique) D_CELLS_JIHD Liberty for corner '$CORNER' in $LIBDIR"
}
set LIBS $LIB
if {$TOP eq "usb_ulpi_phy_pads"} {
    if {$IO_LIB eq "" || ![file exists $IO_LIB]} {
        error "usb_ulpi_phy_pads needs the BBSUD8F Liberty (IO_LIB=...), which is not in X-FAB/;\
               synthesize usb_ulpi_phy_top instead"
    }
    lappend LIBS $IO_LIB
}
read_libs $LIBS

# Physical-aware synthesis would add read_physical -lef {...} here
# (X-FAB/xh018_lef/xh018_xx31_HD_MET3_METMID.lef, xh018_D_CELLS_JIHD.lef)
# plus a QRC / cap table, which is not available (DOC/genus_file_list.txt 4.3).

#-----------------------------------------------------------------------------
# RTL
#-----------------------------------------------------------------------------
set_db init_hdl_search_path $ROOT
set_db hdl_track_filename_row_col true
read_hdl -v2001 $RTL_FILES
elaborate $TOP
current_design $TOP

check_design -unresolved > $OUT/reports/check_unresolved.rpt
check_design -all        > $OUT/reports/check_design.rpt

# run_synth.sh asserts: no latches
set latches [get_db insts -if {.is_latch == true}]
if {[llength $latches]} {
    puts "ERROR: [llength $latches] latch(es) inferred: [get_db $latches .name]"
    error "latches inferred in $TOP"
}

# no flop / latch merging: (* keep *) copies in the clk_rx islands
set_db optimize_merge_flops   false
set_db optimize_merge_latches false

if {$FLATTEN} {
    set_db ungroup_separator .
    ungroup -all -flatten
}

#-----------------------------------------------------------------------------
# Constraints: Genus versions of the tool-specific SDC queries
# (constraints/usb_phy.sdc defines its OpenSTA versions only if these are
# missing).  Return "" / {} when nothing is found, as the SDC expects.
#-----------------------------------------------------------------------------
# 1 if port exists and is an input
proc usb_port_is_input {port} {
    set p [get_db ports $port]
    if {[llength $p] == 0} { return 0 }
    return [expr {[get_db $p .direction] eq "in"}]
}
# leaf driver pin of a top-level net (the flop output), or ""
proc usb_net_driver {net} {
    set n [get_db nets $net]
    if {[llength $n] == 0} { return "" }
    set d [get_db [get_db $n .drivers] -if {.obj_type == pin}]
    if {[llength $d] == 0} { return "" }
    return $d
}
# one element per net matching one of the patterns that has a leaf driver:
# the driving instance(s)
proc usb_driver_cells {patterns} {
    set res {}
    foreach pat $patterns {
        foreach n [get_db nets $pat] {
            set d [get_db [get_db $n .drivers] -if {.obj_type == pin}]
            if {[llength $d]} { lappend res [get_db $d .inst] }
        }
    }
    return $res
}

read_sdc $ROOT/constraints/usb_phy.sdc

# clocks the top must have (from its ports / generated clock nets)
set want {}
if {[llength [get_db ports clk_bit]]}  { lappend want clk_bit }
if {[llength [get_db ports clk_rx]]}   { lappend want clk_rx }
if {[llength [get_db ports ref_clk]]}  { lappend want ref_clk }
set has_bit [llength [get_db ports clk_bit]]
if {[usb_port_is_input clk60] || ($has_bit && [usb_net_driver clk60] ne "")} { lappend want clk60 }
if {[llength [get_db ports clk_rx]] && [usb_net_driver clk_rxw] ne ""}      { lappend want clk_rxw }
if {$has_bit && ![usb_port_is_input clk60] && [usb_net_driver clkout] ne ""} { lappend want clkout }
set have {}
foreach c [get_db clocks] { lappend have [get_db $c .base_name] }
foreach c $want {
    if {[lsearch -exact $have $c] < 0} {
        error "clock $c not created by constraints/usb_phy.sdc (check the usb_* query procs / net names)"
    }
}
puts "INFO: clocks: $have"
puts "INFO: rst_rx_m_n exception sources: [usb_driver_cells {rst_rx_m_n *.rst_rx_m_n rst_rx_m2_n *.rst_rx_m2_n}]"
puts "INFO: PISO clamp flop: [usb_driver_cells {*u_piso.cq cq}]"
check_timing_intent -verbose > $OUT/reports/check_timing_intent.rpt
report_clocks               > $OUT/reports/clocks.rpt

#-----------------------------------------------------------------------------
# Synthesis
#-----------------------------------------------------------------------------
set_db syn_generic_effort $EFFORT
set_db syn_map_effort     $EFFORT
set_db syn_opt_effort     $EFFORT

syn_generic
write_snapshot -outdir $OUT/snap_generic -tag generic
syn_map
write_snapshot -outdir $OUT/snap_map -tag map
syn_opt

#-----------------------------------------------------------------------------
# Reports and outputs
#-----------------------------------------------------------------------------
report_qor                      > $OUT/reports/qor.rpt
report_area                     > $OUT/reports/area.rpt
report_gates                    > $OUT/reports/gates.rpt
report_timing -max_paths 50     > $OUT/reports/timing.rpt
report_timing -lint -verbose    > $OUT/reports/timing_lint.rpt
report_clocks                   > $OUT/reports/clocks_final.rpt
report_power                    > $OUT/reports/power.rpt
report_messages -all            > $OUT/reports/messages.rpt

# registers per clock (compare Plan_60MHz.md 8.11)
set fh [open $OUT/reports/registers_per_clock.rpt w]
foreach c [all_clocks] {
    if {[catch {llength [all_registers -clock $c]} n]} { set n "?" }
    puts $fh [format "%-10s %5s" [get_db $c .base_name] $n]
}
close $fh

write_hdl > $OUT/${TOP}.v
write_sdc > $OUT/${TOP}.sdc
write_sdf -edges check_edge > $OUT/${TOP}.sdf
write_db  $OUT/${TOP}.db

puts "GENUS_SYNTH_DONE $TOP $CORNER"
