#!/usr/bin/env bash
#-----------------------------------------------------------------------------
# run_genus.sh - Cadence Genus synthesis of the top levels (syn/genus_synth.tcl)
#
#   ./run_genus.sh                        all tops below (slow corner)
#   ./run_genus.sh usb_ulpi_phy_top       only the named top level(s)
#   CORNER=typ ./run_genus.sh             xh018 corner: slow (default), typ, fast
#   EFFORT=high ./run_genus.sh            syn_* effort: low, medium (default), high
#   IO_LIB=/path/BBSUD8F_slow.lib ./run_genus.sh usb_ulpi_phy_pads
#                                         the pad top needs the IO-cell Liberty
#   FLATTEN=0 ./run_genus.sh ...          keep the hierarchy (see the Tcl header)
#
# File list: DOC/genus_file_list.txt (the same list is in syn/genus_synth.tcl).
# Outputs: build/genus/<top>_<corner>/ (netlist <top>.v, .sdc, .sdf, .db,
#   reports/), log genus.log.  build/ is git-ignored; the netlists contain
#   X-FAB cell names (confidential PDK, never commit).
# Needs genus in PATH and X-FAB/xh018_lib; without them: SKIPPED, exit 0.
# A top passes when Genus prints GENUS_SYNTH_DONE (the Tcl stops on any Error
# message: fail_on_error_mesg).  Timing violations do not fail the script;
# the summary shows the worst slack from reports/qor.rpt.
#-----------------------------------------------------------------------------
set -u
cd "$(dirname "$0")"
CORNER=${CORNER:-slow}

# usb_ulpi_phy_pads only with IO_LIB (the BBSUD8F Liberty is not in X-FAB/)
TOPS=(usb_ulpi_phy_top usb_rx_datapath usb_rx_decoder8 usb_ulpi_tx_top usb_afe_tx_if8 usb_tx_piso usb_afe_rx_if usb_clk_gen usb_pll_lock_det usb_rx_status_sync usb_line_state usb_mode_term_ctrl usb_pwr_seq usb_afe_trim_regs)
[ -n "${IO_LIB:-}" ] && TOPS=(usb_ulpi_phy_pads "${TOPS[@]}")
[ $# -gt 0 ] && TOPS=("$@")

command -v genus >/dev/null || { echo "SKIPPED: genus not found"; exit 0; }
[ -d X-FAB/xh018_lib ] || { echo "SKIPPED: X-FAB/xh018_lib not present"; exit 0; }

echo "Genus, corner $CORNER"
pass=0; fail=0
for top in "${TOPS[@]}"; do
    out=build/genus/${top}_$CORNER
    mkdir -p "$out"
    log=$out/genus.log
    if TOP=$top CORNER=$CORNER OUT=$out genus -batch -no_gui -overwrite \
            -log "$out/genus" -files syn/genus_synth.tcl > "$out/stdout.txt" 2>&1 &&
       grep -q "GENUS_SYNTH_DONE $top" "$log" "$out/stdout.txt" 2>/dev/null; then
        wns=$(awk -F'[ \t]+' '/Worst slack|WNS/ { v = $NF } END { print v }' "$out/reports/qor.rpt" 2>/dev/null)
        printf '  %-20s PASSED  WNS %s  (%s)\n' "$top" "${wns:-?}" "$out"
        pass=$((pass + 1))
    else
        why=$(grep -h -m1 -E '^(Error|ERROR)' "$log" "$out/stdout.txt" 2>/dev/null)
        printf '  %-20s FAILED  %s (see %s)\n' "$top" "${why:-genus error}" "$log"
        fail=$((fail + 1))
    fi
done
echo "--------------------------------------------------"
echo "genus: $pass passed, $fail failed (corner $CORNER)"
[ $fail -eq 0 ]
