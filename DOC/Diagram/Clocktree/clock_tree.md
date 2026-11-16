# Clock tree – USB 2.0 ULPI PHY (digital half)

Diagram: [`clock_tree.drawio`](clock_tree.drawio) (open with draw.io / diagrams.net).

Sources: `usb_clk_gen.v`, `usb_rx_hs_sipo.v`, `usb_pll_lock_det.v`, `usb_pwr_seq.v`,
`usb_ulpi_phy_pads.v`, `constraints/usb_phy.sdc`, `Plan_60MHz.md` (3.1–3.4, 8.11),
`DOC/afe_interface_spec.md` section 2. Status as of `Plan_60MHz.md` P9 (2026-11-15).

> **Wiring status:** `usb_clk_gen`, the RX datapath, `usb_afe_rx_if`, `usb_afe_tx_if8` /
> `usb_tx_piso`, `usb_pll_lock_det`, `usb_pwr_seq`, `usb_rx_status_sync` and `usb_line_state` are
> not wired into `usb_ulpi_phy_top` yet (WORK_PLAN 8.1). Today `usb_ulpi_phy_top` / `_pads` take
> `clk60`, `clk_bit` and `clkout` as ports. The diagram shows the clock structure the blocks are
> designed and constrained for (the SDC already covers it).

## 1. Overview

```
                    AFE (analog)                         |                  Digital (this repo)
                                                         |
 Crystal / REFCLK ── CDR_FREF 24 MHz ──┬─> PLL (×20) ── CLK_BIT_A = clk_bit 480 MHz ──┬─> usb_clk_gen (÷8 Johnson)
                                       │      ┊ coarse loop                           │      ├─ clk60   60 MHz ──> core (1 137 FF)
                                       │      ┊                                       │      ├─ ld / phase_j  ──> clk_bit islands
                                       │      ▼                                       │      └─ clkout 60 MHz ─> CLK pad ─> Link
                                       │   CDR VCO ── clk_rx 480 MHz ±1000 ppm ──┐    └─> clk_bit islands (165 FF)
                                       │                                         └─> usb_afe_rx_if + usb_rx_hs_sipo (112 FF)
                                       │                                                   └─ clk_rxw = clk_rx/8 ─> HS word FIFO write
                                       └─> REF_DIG buffer ── ref_clk 24 MHz ──> usb_pwr_seq, usb_pll_lock_det window
```

## 2. Clock sources

| Clock (digital name) | Analog / pin name | Frequency | Source | Kind | SDC |
|---|---|---|---|---|---|
| `ref_clk` | `REF_DIG` (buffered `CDR_FREF`) | 24 MHz (±500 ppm) | Crystal oscillator / REFCLK buffer in the AFE | Primary, asynchronous to all others | `create_clock` 41.667 ns |
| `clk_bit` | `CLK_BIT_A` | 480 MHz | PLL lower loop (×20 from `CDR_FREF`), VCO 400–500 MHz | Primary | `create_clock` 2.0833 ns |
| `clk_rx` | CDR clock | 480 MHz ±1000 ppm | CDR VCO (bang-bang upper loop, held near 480 MHz by the PLL coarse loop; free-runs without data) | Primary, asynchronous to `clk_bit` | `create_clock` 2.081 ns (+1000 ppm) |
| `clk60` | – | 60 MHz, 50 % | `usb_clk_gen`: ÷8 Johnson counter on `clk_bit`, dedicated flop, rises at E0, falls at E4; free-running (not gated) | Generated, synchronous to `clk_bit` | `create_generated_clock -divide_by 8` |
| `clkout` | ULPI `CLK` (`PAD_ULPI_CLK`) | 60 MHz, 50 % | `usb_clk_gen`: rising-edge `clk_bit` flop, `CKO_LEAD` = 2 `clk_bit` cycles before E0; glitch-free gated by `clk_en` (PLL lock & not clock-suspend) | Generated, synchronous; reference only (clocks no flop) | `create_generated_clock -edges {1 9 17}` |
| `clk_rxw` | – | 60 MHz ±1000 ppm (`clk_rx` / 8) | `usb_rx_hs_sipo`: MSB of a 4-bit Johnson counter on `clk_rx` | Generated, synchronous to `clk_rx` | `create_generated_clock -divide_by 8` |
| `ulpi_clk` | – | 60 MHz | Virtual clock = the CLK pin edge (`clkout` + flop + pad delay) | Virtual, for ULPI I/O only | `create_clock` (offset `delta` ≈ −0.37 ns) |
| `ld`, `phase_j[3:0]` | – | 60 MHz strobe / phase | `usb_clk_gen` (registered, `ld` high in phase 3 → island flops update on E4) | Not clocks: enables / phase on `clk_bit` | – |
| `CLK60_A` *(proposed)* | `CLK60_A` | 60 MHz | PLL output divider ÷8 – alternative source of `clk60`, **not wired** | – | – |

## 3. Clock sinks

Register counts are from the sized STA of each top level (`Plan_60MHz.md` 8.11, standalone tops).

### 3.1 `clk_bit` (480 MHz) – small islands only

| Sink | Function | FF |
|---|---|---|
| `usb_clk_gen` | Johnson ÷8 counter, `clk60` / `ld` / `clkout` / `clk_on` flops | 11 |
| `usb_tx_piso` | TX 8:1 PISO per AFE pin, loaded on `ld`, idle clamp `cq` | 68 |
| `usb_rx_datapath` → `usb_rx_fsls_sampler` | FS/LS 2-FF + 1:8 SIPO (40× / 320× oversampling), word on `ld`; `tx_en` capture | 56 |
| `usb_pll_lock_det` | 8-sample window-end word (3 phase LSBs) | 17 |
| `usb_rx_status_sync` | Squelch / disconnect capture | 7 |
| `usb_line_state` | Input capture (`hs_tx_act`) | 2 |
| `usb_pwr_seq` | `clk_en_b` (CLKOUT gate copy) | 2 |
| `usb_ulpi_phy_pads` | `bit_rst_n` 2-FF reset synchronizer for the islands | 2 |

### 3.2 `clk60` (60 MHz) – core

| Sink | Function | FF |
|---|---|---|
| `usb_ulpi_phy_top` | ULPI core (`usb_ulpi_core`: input capture, TXCMD decode, `usb_tx_datapath`, reg access, burst mux, bus owner), `usb_ulpi_rx_path`, `usb_ulpi_reg_file`, `usb_afe_trim_regs`, `usb_mode_term_ctrl` | 503 |
| `usb_ulpi_phy_pads` | RESETB 2-FF synchronizer → `core_rst_n` | 2 |
| `usb_rx_datapath` | `usb_rx_fsls_dpll`, `usb_rx_decoder8`, event FIFO, output stage, word-FIFO read side | 278 |
| `usb_afe_tx_if8` | Driver select, lead / lag window, TX pin vectors | 205 |
| `usb_rx_status_sync` | Squelch / disconnect filters, VBUS / ID 2-FF | 86 |
| `usb_pll_lock_det` | Frequency count, range check, `lol` | 37 |
| `usb_line_state` | LineState, DISC window | 17 |
| `usb_pwr_seq` | Core-side release copies (`core_rst_n_c`, `iso_en_c`, `dir_hold_c`, `afe_en_c`) | 8 |
| `usb_afe_rx_if` | `rx_en_hs` / `cdr_en` enables | 1 |

### 3.3 `clk_rx` (480 MHz ±1000 ppm) – HS receive island

| Sink | Function | FF |
|---|---|---|
| `usb_afe_rx_if` | Squelch 2-FF, CDR lock / delay line, data delay; reset synchronizer (`rst_rx_n`, `rst_rx_m_n`, `rst_rx_m2_n`) | 54 |
| `usb_rx_hs_sipo` (in `usb_rx_datapath`) | `usb_rx_hs_frontend`, 1:8 SIPO of data + valid mask, Johnson ÷8 → `clk_rxw` | 58 |

### 3.4 `clk_rxw` (`clk_rx` / 8)

| Sink | Function | FF |
|---|---|---|
| `usb_rx_hs_sipo` write gate + `usb_rx_elastic_buffer` (ASYNC word FIFO, write side) | 8 × 17-bit word memory, Gray write pointer, write-side synchronizers | 148 |

### 3.5 `ref_clk` (24 MHz)

| Sink | Function | FF |
|---|---|---|
| `usb_pwr_seq` | Power-up / suspend sequencer (runs while the PLL is off); drives `bias_en`, `pll_en`, `iso_en` | 40 |
| `usb_pll_lock_det` | Reference window counter (2^NW cycles), dead-clock check of the `clk60`/16 heartbeat | 21 |

### 3.6 `clkout` (60 MHz)

| Sink | Function |
|---|---|
| `usb_ulpi_phy_pads` `u_pad_clk` (BBSUD8F) → `PAD_ULPI_CLK` | ULPI CLK to the Link (output-clock mode, ULPI 1.1). Stops low in clock suspend / before PLL lock; `clk_on` tells `usb_pwr_seq` when it has stopped. |

### 3.7 Flip-flop count per clock

Per-clock register counts (`all_registers -clock`) from `./run_sta.sh`, slow corner, 2026-11-16.
No double counting: `usb_afe_trim_regs` / `usb_mode_term_ctrl` are inside `usb_ulpi_phy_top`,
`usb_rx_decoder8` is inside `usb_rx_datapath`; the older reduced top `usb_ulpi_tx_top` is left
out. `usb_ulpi_phy_pads` is not in the STA run: its 4 flops are the Yosys flop count of
`usb_ulpi_phy_pads` (507) minus that of `usb_ulpi_phy_top` (503). Most blocks are counted
standalone (not wired into the chip top yet), so the final counts can change slightly.

| Clock | Frequency | Source | Flip-flops |
|---|---|---|---:|
| `clk60` | 60 MHz | `clk_bit` ÷ 8 (`usb_clk_gen`) | 1 137 |
| `clk_rxw` | 60 MHz ±1000 ppm | `clk_rx` ÷ 8 (`usb_rx_hs_sipo`) | 148 |
| **Subtotal 60 MHz** | | | **1 285 (79 %)** |
| `clk_bit` | 480 MHz | PLL | 165 |
| `clk_rx` | 480 MHz ±1000 ppm | CDR | 112 |
| **Subtotal 480 MHz** | | | **277 (17 %)** |
| `ref_clk` | 24 MHz | REF_DIG | 61 (4 %) |
| **Total** | | | **1 623** |

| Module | `clk60` | `clk_rxw` | `clk_bit` | `clk_rx` | `ref_clk` | Total |
|---|---:|---:|---:|---:|---:|---:|
| `usb_ulpi_phy_top` (ULPI core, register files, TX byte path, `usb_afe_trim_regs`, `usb_mode_term_ctrl`) | 503 | | | | | 503 |
| `usb_ulpi_phy_pads` (RESETB sync / `bit_rst_n` sync) | 2 | | 2 | | | 4 |
| `usb_rx_datapath` (decoder, DPLL, FS/LS sampler, HS SIPO, word FIFO) | 278 | 148 | 56 | 58 | | 540 |
| `usb_afe_tx_if8` | 205 | | | | | 205 |
| `usb_tx_piso` | | | 68 | | | 68 |
| `usb_afe_rx_if` | 1 | | | 54 | | 55 |
| `usb_clk_gen` | | | 11 | | | 11 |
| `usb_pll_lock_det` | 37 | | 17 | | 21 | 75 |
| `usb_rx_status_sync` | 86 | | 7 | | | 93 |
| `usb_line_state` | 17 | | 2 | | | 19 |
| `usb_pwr_seq` | 8 | | 2 | | 40 | 50 |
| **Total** | **1 137** | **148** | **165** | **112** | **61** | **1 623** |

## 4. Clock relationships and crossings

| From → To | Relation | Mechanism | SDC |
|---|---|---|---|
| `clk60` ↔ `clk_bit` | Synchronous (`clk60` = `clk_bit`/8) | Boundary rule: island registers read by `clk60` change only on `ld` (E4); island registers sampling `clk60` data sample only on `ld`. Never cross on E0. Exception: PISO clamp `cq` samples `drv_dis` / `iso_en` every `clk_bit` edge. | `set_multicycle_path` setup 4 / hold 3 both ways; `cq` single cycle |
| `clk_rx` → `clk_rxw` | Synchronous (÷8) | Word register on phase 3 (E4), `clk_rxw` rises on E0 – same rule as above | multicycle 4 / 3 |
| `clk_rxw` / `clk_rx` ↔ `clk60` | Asynchronous (±1000 ppm) | HS word FIFO with Gray pointers + 2-FF synchronizers | `set_max_delay` 1 `clk_rxw` period, hold false |
| `clk_rx` ↔ `clk_bit` / `clkout` | Asynchronous | No paths | `set_false_path` |
| `ref_clk` ↔ everything | Asynchronous | 2-FF synchronizers only | `set_clock_groups -asynchronous` |
| `clk60` ↔ `ulpi_clk` (Link) | Synchronous, CLK pin edge `delta` = `CKO_FF` + `PAD_OUT` − `CKO_LEAD`·T_bit after E0 | `CKO_LEAD` in `usb_clk_gen` and the SDC must match | input / output delays (ULPI 1.1: setup 6.0 ns, hold 0, Tco 9.0 ns) |

## 5. Reset domains (per clock)

| Reset | Clock | Origin |
|---|---|---|
| `por_n` / `rst_n` | async | Power-on: `usb_clk_gen`, `usb_pll_lock_det`, `usb_pwr_seq` (CLKOUT keeps running while RESETB is low) |
| `core_rst_n` | `clk60` | RESETB pad → 2-FF on `clk60` (`usb_ulpi_phy_pads`), AND `core_rst_n_c` from `usb_pwr_seq` |
| `bit_rst_n` | `clk_bit` | `core_rst_n` → 2-FF on `clk_bit` (islands, e.g. `usb_tx_piso`) |
| `rst_rx_n`, `rst_rx_m_n`, `rst_rx_m2_n` | `clk_rx` | 2-FF per island (`usb_afe_rx_if`, `usb_rx_hs_sipo`); `_m` copies have 2-cycle recovery in the SDC |
| `clk_rxw` reset | `clk_rxw` | Release synchronized to `clk_rxw` in `usb_rx_hs_sipo` |

## 6. Clock control

- **`pll_en`** (`usb_pwr_seq`, `ref_clk`) starts / stops the PLL, hence `clk_bit`, `clk60`, `clkout`.
  The sequencer waits for `clk_on` = 0 before stopping the PLL, so no clock is cut mid-pulse.
- **`clk_en`** (`clk_en_b`, `clk_bit` copy from `usb_pwr_seq`, = PLL lock & not clock-suspend)
  gates only `clkout`, sampled once per period in phase 7 − `CKO_LEAD`; `clk60` keeps running.
- **`cdr_en`** (`usb_afe_rx_if`, `clk60`) enables the CDR; with `CDR_EN` = 0 `clk_rx` stops low.
- **Lock detection:** `usb_pll_lock_det` counts `clk_bit` cycles (8 × `clk60` count + phase LSBs)
  over a `ref_clk` window; a `clk60`/16 heartbeat checked on `ref_clk` detects a dead `clk_bit`.

## 7. Open items (from `Plan_60MHz.md` 8.11)

- Ideal clocks in STA: no CTS insertion delay, skew or jitter (P9-O4); the 4 / 3 multicycles assume
  ≤ ±3 `clk_bit` cycles of skew between the `clk_bit` and `clk60` trees (K3).
- `CKO_LEAD` = 2 is chosen on placeholder pad delays (P9-O3).
- Slow-corner setup on the 480 MHz islands still −0.07 … −0.40 ns (P9-O1).
- `CLK60_A` from the PLL divider is only a proposal (spec section 2).
