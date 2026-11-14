# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Synthesizable Verilog-2005 RTL for the digital, PHY-side half of a USB 2.0 ULPI transceiver (HS/FS/LS), modelled on the Microchip USB3320 (VID/PID defaults 0424h/0007h). Target process: X-FAB xh018 (D_CELLS_JIHD standard cells, BBSUD8F pads). The analog front end is designed separately; this repo only holds behavioural / Verilog-A models of it.

## Commands

```sh
./run_tests.sh                    # all tb_*.v with Icarus Verilog, in parallel (JOBS=n)
./run_tests.sh ulpi_core rx_      # only testbenches whose name contains one of the words
./run_synth.sh                    # Yosys smoke synthesis of all top levels
./run_synth.sh usb_ulpi_phy_top   # one top level
CORNER=slow ./run_synth.sh        # Liberty corner typ (default) / slow / fast
./run_sta.sh [top ...]            # OpenSTA with constraints/usb_phy.sdc, CORNER=slow (default) / typ / fast
make test | synth | sta | all | clean   # same, with TB= TOPS= CORNER= STA_CORNER= JOBS=
AFE/ams/run_ams_tests.sh [link|pwr]   # Spectre AMS (xrun -ams); no simulator here, only the static netlist check runs
```

- **The build command of each testbench lives in its header comment** (`// iverilog ...` line with `\` continuations). `run_tests.sh` extracts and runs exactly that command. When a testbench needs a new source file, add it to that header line — there is no other file list.
- To run one testbench by hand, copy its header command (e.g. `iverilog -g2005 -o sim_bs usb_bit_stuffer.v tb_usb_bit_stuffer.v && vvp sim_bs`).
- Pass/fail is the **last `TEST PASSED` / `TEST FAILED: ...` line** in the output, not the exit code. New testbenches must self-check and print this line.
- `tb_usb_ulpi_phy_pads` needs `-DDISPLAY_PD_PU_EN` for the pull checks; testbenches/tops that reference `X-FAB/` are skipped when that directory is absent.
- `run_synth.sh` reads every `usb_*.v` and fails on inferred latches or any `check -assert` problem (undriven, multiply driven, loops). With `X-FAB/xh018_lib` present it also maps to D_CELLS_JIHD and requires no generic cells left. New top levels must be added to the `TOPS` list in `run_synth.sh` (and of `run_sta.sh`).
- `run_sta.sh` maps each top for delay (corner Liberty without X0 cells; Yosys does no sizing/buffering), runs OpenSTA with `constraints/usb_phy.sdc` and prints WNS/TNS/#violations; reports in `build/sta/`. Numbers are unsized, ideal-clock estimates, not sign-off. Legacy `ce60` paths are timed single-cycle at 480 MHz on purpose. Timing violations do not fail the script.
- Outputs go to `build/`.

## File naming (all in repo root)

- `usb_*.v` — synthesizable RTL. Only these are read by synthesis.
- `tb_usb_*.v` — RTL testbenches; `tb_afe_*.v` — tests of the AFE models; `tb_ams_*_shadow.v` — Icarus shadows of the Spectre AMS testbenches in `AFE/ams/` (same `ams_phy_end.v` and `.vh` sequences, `afe_*_bm.v` models instead of Verilog-A). A failure only in AMS points at the Verilog-A models / connect rules, not the RTL.
- `constraints/usb_phy.sdc` — timing constraints (skeleton; every clock is created only if its port/net exists, so it works on any top).
- `afe_*_bm.v` — testbench-only, real-valued AFE behavioural models (line, terminations, HS TX/RX, squelch, CDR, FS/LS, PLL). Not synthesizable; must never be named `usb_*`.
- `AFE/veriloga/` Verilog-A models with the same pins/defaults as the `_bm` models; `AFE/spice/` transistor-level references; `AFE/ams/` AMS testbenches.
- Each module's header comment is its detailed spec (pipeline position, timing, corner cases). Read it before changing a module and keep it in sync.

## Architecture

Hierarchy: `usb_ulpi_phy_pads` (BBSUD8F pads, protection pulls, RESETB sync, NAND tree) → `usb_ulpi_phy_top` (reg file `usb_ulpi_reg_file` + `usb_afe_trim_regs` vendor 30h–3Fh, `usb_mode_term_ctrl`) → `usb_ulpi_phy_if` → `usb_ulpi_core` (input capture/TXCMD decode, `usb_tx_datapath`, reg access FSM, burst mux, bus owner) + `usb_ulpi_rx_path` (RX FIFO, RXCMD gen, out arbiter). `usb_ulpi_tx_top` is an older reduced top. The README has the full tree.

- **TX:** `usb_tx_holding` (4-byte FIFO, NXT pacing) → `usb_tx_sync_mux` → `usb_tx_path` = `usb_bit_stuffer` → `usb_nrzi_encoder` → (`SPLIT = 1`: `usb_tx_ser_bridge` →) `usb_tx_serializer` (+EOP) → `txd/tx_en/tx_se0` → `usb_afe_tx_if` (AFE boundary).
- **RX:** `usb_afe_rx_if` → `usb_rx_datapath`: HS via `usb_rx_hs_frontend` on the CDR clock `clk_rx`, FS/LS via `usb_rx_fsls_frontend` DPLL (40×/320× oversampling on 480 MHz) → `usb_rx_decoder` (NRZI decode, SYNC detect, unstuff, deserialize, EOP/error check) → `usb_rx_elastic_buffer` (CDC into `clk_bit`).
- **Not yet wired into `usb_ulpi_phy_top`:** the RX datapath, `usb_afe_tx_if`, `usb_afe_rx_if`, `usb_clk_gen`, `usb_pll_lock_det`, `usb_rx_status_sync`, `usb_line_state`, `usb_pwr_seq`. They are verified standalone / through AFE models. Not implemented at all: OpMode 11, soft_reset, SuspendM/low-power, LS-via-FS-preamble, OTG/VBUS control.

### Conventions

- **Clocks (migration in progress):** `clk_bit` = 480 MHz PLL clock; modules not migrated yet still run the 60 MHz domain as the enable `ce60` (one cycle in eight, 8-cycle multicycle paths). Second clock only `clk_rx` (CDR) up to the elastic buffer. `Plan_60MHz.md` moves the core to a real 60 MHz clock because 480 MHz fails timing at the slow corner; follow its status table (section 8). Done so far (P1, P2): `usb_clk_gen` generates `clk60` (rises at E0, the edge where `ce60` logic updates) and the island strobe `ld`; its CLKOUT port is `clkout`. The ULPI core (`usb_ulpi_phy_top` and everything under it, `usb_ulpi_tx_top`, `usb_ulpi_phy_pads`) runs on `clk60` with the leaves' `ce` tied to 1; those parents take `clk_bit` + `clk60` + `ld` (no `ce60`). Only the TX serializer stays on `clk_bit`, behind `usb_tx_ser_bridge` (`usb_tx_path` `SPLIT = 1`; `SPLIT = 0` is the old single-clock path, still used by the AFE-level TBs and `ams_phy_end.v`). The RX datapath, line state, status sync, AFE interfaces, lock detector and power sequencer are still `clk_bit` + `ce60`.
- **60↔480 boundary rule:** a `clk_bit` register read by `clk60` logic changes only on `ld`, and one that samples `clk60` data samples only on `ld` (edge E4). Never cross on E0: in simulation `clk60` rises one delta after `clk_bit`, so an E0 crossing is silently zero-cycle (see `usb_clk_gen` header, `tb_usb_clk_gen`). The SDC multicycles (4/3) assume this rule.
- **TB clocks for `clk60` DUTs:** generate `clk60` with a blocking assignment in an `always @(posedge clk_bit)` on the edge where `ce60` was high (`ce_cnt == 7` → 1, `ce_cnt == 3` → 0) and `ld = (ce_cnt == 3)`; then TB processes driving on `ce60` ticks of `clk_bit` behave like zero-skew clocks (see `tb_usb_ulpi_core`). Don't derive the TB's `clk60` with `<=`.
- Reset: active-low asynchronous `rst_n`.
- Speed = ULPI XcvrSelect: `00` HS, `01` FS, `10` LS, `11` sent at FS rate.
- Line encoding: J = 1 / K = 0, LSB first.
- Testbenches typically check against an independent reference/shadow model (e.g. register shadow, packet rebuilt from `txd` by de-NRZI/de-stuff) and vary `ce` patterns and backpressure.

## Planning documents

Progress is tracked by phase IDs in these docs; update their status tables when finishing work:
- `WORK_PLAN.md` — digital section (phases 0–9, discrepancies D*, risks R*).
- `AFE_INTEGRATION_PLAN.md` — AFE boundary (phases A0–A8, items I*); `DOC/afe_interface_spec.md` — draft AFE↔digital pin spec (Fixed/Proposed/TBC).
- `Plan_60MHz.md` — clock-domain migration plan.
- `DOC/` holds the ULPI 1.1 spec and USB3300/USB3320 datasheets (PDF).

## Confidential PDK data

`X-FAB/` (BBSUD8F.v, VLG_PRIMITIVES.v, IO_CELLS_JIF3V.v, xh018 Liberty/LEF/Verilog) is confidential X-FAB PDK data and must never be committed or published. `.gitignore` excludes it along with `build/`, `*.vcd` and `sim_*`; never force-add anything under `X-FAB/`.
