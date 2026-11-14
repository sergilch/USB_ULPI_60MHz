#!/usr/bin/env bash
#-----------------------------------------------------------------------------
# run_sta.sh - static timing analysis with OpenSTA (Plan_60MHz.md P1, WORK_PLAN 9.1)
#
#   ./run_sta.sh                       all top levels below
#   ./run_sta.sh usb_clk_gen           only the named top level(s)
#   CORNER=typ ./run_sta.sh            xh018 corner: slow (default), typ, fast
#   ABC_D=2083 ./run_sta.sh            delay target of the mapping in ps
#
# Needs the X-FAB library (X-FAB/xh018_lib) and OpenSTA (sta); without them the
# script reports SKIPPED and exits 0.  Per top level:
#   * Yosys maps all usb_*.v for delay (synth -flatten, dfflibmap, abc -D) onto
#     the D_CELLS_JIHD cells of the same corner: build/sta/<top>_<corner>.v.
#     The mapping library is a copy of the corner's Liberty without the X0
#     cells (build/sta/map_<corner>.lib): Yosys does no gate sizing and always
#     picks the smallest flop, and X0 flops / gates cost about 0.5 ns per
#     stage at the slow corner, far from what a sizing flow would give.  X1
#     is the closer estimate (X2 as minimum is slower again: input load).
#     run_synth.sh is unchanged (area mapping, all cells).  STA itself reads
#     the complete library.
#   * OpenSTA reads that netlist and constraints/usb_phy.sdc and writes
#     build/sta/<top>_<corner>.rpt: clocks, setup / hold WNS and TNS, the
#     violating endpoints and the worst paths per clock group.
#
# Limits (read the numbers with them in mind): ideal clocks (no CTS), no wire
# load / parasitics, no I/O constraints yet, no hold fixing, no placement.  The
# legacy ce60 paths are timed as single-cycle 480 MHz paths (see the SDC).
#
# Exit code: 0 always for the analysis itself (timing violations are a result,
# not a script failure), 1 if a mapping or STA run breaks.
#-----------------------------------------------------------------------------
set -u
cd "$(dirname "$0")"
OUT=build/sta
mkdir -p "$OUT"
CORNER=${CORNER:-slow}
ABC_D=${ABC_D:-2083}
SDC=constraints/usb_phy.sdc

# usb_ulpi_phy_pads is left out: the BBSUD8F pads have no timing model here.
TOPS=(usb_ulpi_phy_top usb_rx_datapath usb_ulpi_tx_top usb_afe_tx_if usb_afe_rx_if usb_clk_gen usb_pll_lock_det usb_rx_status_sync usb_line_state usb_mode_term_ctrl usb_pwr_seq usb_afe_trim_regs)
[ $# -gt 0 ] && TOPS=("$@")

LIB=$(ls X-FAB/xh018_lib/D_CELLS_JIHD_LPMOS_${CORNER}_*.lib 2>/dev/null | head -1)
if [ -z "$LIB" ] || ! command -v sta >/dev/null || ! command -v yosys >/dev/null; then
    echo "SKIPPED: needs X-FAB/xh018_lib (corner '$CORNER'), yosys and sta"; exit 0
fi
RTL=$(ls usb_*.v | tr '\n' ' ')

# mapping library: the corner's Liberty without the X0 cells (see the header)
MAPLIB=$OUT/map_$CORNER.lib
if [ ! -s "$MAPLIB" ] || [ "$LIB" -nt "$MAPLIB" ]; then
    python3 -I - "$LIB" "$MAPLIB" '.*X0' <<'PY' || { echo "cannot write $MAPLIB"; exit 1; }
import re, sys
src, dst, pat = sys.argv[1], sys.argv[2], re.compile(sys.argv[3])
txt = open(src).read()
cre = re.compile(r'^[ \t]*cell[ \t]*\([ \t]*"?([A-Za-z0-9_]+)"?[ \t]*\)[ \t]*\{', re.M)
out, i = [], 0
while True:
    m = cre.search(txt, i)
    if not m:
        out.append(txt[i:]); break
    depth, j = 1, m.end()
    while depth:
        depth += {'{': 1, '}': -1}.get(txt[j], 0); j += 1
    out.append(txt[i:m.start()] if pat.fullmatch(m.group(1)) else txt[i:j])
    i = j
open(dst, 'w').write(''.join(out))
PY
fi

echo "OpenSTA $(sta -version), corner $CORNER ($(basename "$LIB")), abc -D $ABC_D"
printf '  %-20s %9s %10s %6s %9s %6s  %s\n' top "WNS(ns)" "TNS(ns)" "#viol" "hold WNS" "#viol" "worst setup group"
rc=0
for top in "${TOPS[@]}"; do
    net=$OUT/${top}_$CORNER.v
    rpt=$OUT/${top}_$CORNER.rpt
    log=$OUT/${top}_$CORNER.log
    ys="read_verilog $RTL; hierarchy -check -top $top; synth -top $top -flatten;"
    ys+=" dfflibmap -liberty $MAPLIB; abc -D $ABC_D -liberty $MAPLIB; opt_clean;"
    ys+=" select -assert-none t:\$_*; write_verilog -noattr $net"
    if ! yosys -q -l "$log" -p "$ys" > /dev/null 2>&1; then
        printf '  %-20s MAPPING FAILED (see %s)\n' "$top" "$log"; rc=1; continue
    fi

    tcl=$OUT/${top}_$CORNER.tcl
    cat > "$tcl" <<EOF
read_liberty $LIB
read_verilog $net
link_design $top
read_sdc $SDC
puts "== clocks"
report_clock_properties
puts "== summary"
puts "setup_wns [sta::format_time [sta::worst_slack_cmd max] 3]"
puts "setup_tns [sta::format_time [sta::total_negative_slack_cmd max] 3]"
puts "hold_wns [sta::format_time [sta::worst_slack_cmd min] 3]"
puts "== setup violators (endpoint, slack)"
report_checks -path_delay max -slack_max 0 -group_path_count 100000 -endpoint_path_count 1 -format end
puts "== hold violators (endpoint, slack)"
report_checks -path_delay min -slack_max 0 -group_path_count 100000 -endpoint_path_count 1 -format end
puts "== worst setup path per group"
report_checks -path_delay max -group_path_count 1 -fields {fanout cap slew net}
puts "== worst hold path per group"
report_checks -path_delay min -group_path_count 1
EOF
    if ! sta -no_splash -exit "$tcl" > "$rpt" 2>&1 || grep -q '^Error' "$rpt"; then
        printf '  %-20s STA FAILED (see %s)\n' "$top" "$rpt"; rc=1; continue
    fi
    # strip the Liberty wire-load warnings (the library names tables it lacks)
    sed -i '/^Warning 1187: .*wireload .* not found\./d' "$rpt"

    wns=$(awk '$1 == "setup_wns" { print $2 }' "$rpt")
    tns=$(awk '$1 == "setup_tns" { print $2 }' "$rpt")
    hwns=$(awk '$1 == "hold_wns" { print $2 }' "$rpt")
    # endpoint lines of the -format end tables: "<pin> <req> <arr> <slack> (VIOLATED)"
    nviol=$(awk '/^== setup violators/ { s = 1; next } /^== / { s = 0 } s && /\(VIOLATED\)/' "$rpt" | wc -l)
    nhviol=$(awk '/^== hold violators/ { s = 1; next } /^== / { s = 0 } s && /\(VIOLATED\)/' "$rpt" | wc -l)
    grp=$(awk '/^== worst setup path per group/ { s = 1; next } /^== / { s = 0 }
               s && /^Path Group:/ { g = $3 }
               s && /slack \(/ { if (best == "" || $1 + 0 < best + 0) { best = $1; bg = g } }
               END { print bg }' "$rpt")
    printf '  %-20s %9s %10s %6s %9s %6s  %s\n' "$top" "${wns:-?}" "${tns:-?}" "$nviol" "${hwns:-?}" "$nhviol" "${grp:--}"
done
echo "--------------------------------------------------"
echo "reports: $OUT/<top>_$CORNER.rpt"
exit $rc
