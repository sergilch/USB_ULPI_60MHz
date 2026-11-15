# Plan: move the digital core to a 60 MHz clock

Status: in progress. P1 (clock generator, SDC skeleton, STA baseline), P2 (ULPI core on `clk60`),
P3 (parallel RX decoder), P4 (FS/LS receive on `clk60`) done 2026-11-14, P5 (HS receive), P6 (TX)
and P7 (lock detector, power sequencer, pads, status sync) done 2026-11-15; P0 open (D10 proposed,
waiting for the analog team). Progress and results:
section 8.
Related: `WORK_PLAN.md` (D1, D2, 5.2, 9.1, 9.3, risk R1), `AFE_INTEGRATION_PLAN.md` (I12),
`DOC/afe_interface_spec.md` 7.2 (480 MHz timing estimate on xh018).

## 1. Why

- **Timing.** `DOC/afe_interface_spec.md` 7.2 shows that at the slow corner (1.62 V, 125 °C) only
  about 0.6 ns of the 2.08 ns `clk_bit` period is left after flip-flop overhead. The per-bit HS RX
  chain (0.9–3.0 ns) fails, and `usb_pll_lock_det` (1.63 ns) and `usb_afe_tx_if` (1.49 ns) fail too.
  Risk R1 is open.
- **Power and clock tree.** All ~1 250 flip-flops (`usb_ulpi_phy_top` 491, `usb_rx_datapath` 436,
  `usb_afe_tx_if` 162, `usb_rx_status_sync` 96, `usb_pll_lock_det` 57, `usb_pwr_seq` 50, …, from
  `build/synth_*.stat`) sit on the 480 MHz clock tree. The ~85 % of them that only change on `ce60`
  still get clocked eight times per useful edge, with a recirculation mux in front of each D input.
- **STA.** The design is described as one clock plus "8-cycle multicycle paths" everywhere. A real
  60 MHz clock turns most of that into ordinary single-cycle paths and leaves a small, well-defined
  480 MHz boundary.
- **Simulation.** A 60 MHz core with a small 480 MHz island simulates faster. The large TBs
  (`tb_usb_afe_rx_if` about 1 min, `tb_usb_afe_fsls` about 30 s) gain the most.

## 2. Current clocking (what has to change)

One clock `clk_bit` (480 MHz) with the enable `ce60`. The second clock `clk_rx` (CDR) feeds the HS
RX chain up to the elastic buffer. By clocking behaviour, the modules fall into three groups:

| Group | Modules | Behaviour today | Move to 60 MHz |
|---|---|---|---|
| **A. Already ULPI-domain (ce-gated)** | `usb_ulpi_*` (capture, reg_access, reg_file, burst_mux, bus_owner, rx_handler, rxcmd_gen, out_arbiter), `usb_tx_holding`, `usb_tx_sync_mux`, `usb_bit_stuffer`, `usb_nrzi_encoder`, `usb_afe_trim_regs`, `usb_mode_term_ctrl` (except the `iso_en` clamp), `usb_line_state` (except the DISC window) | All state updates under `ce` / `ce60`. Several headers already say "tie ce to 1 on clk60". | Mechanical: clock = `clk60`, `ce` = 1. |
| **B. Per-cycle logic that only needs tick resolution** | `usb_rx_status_sync` / `usb_rx_status_flt` (squelch / disc filter in `clk_bit` cycles), `usb_line_state` DISC window (`DISC_TAIL` = 32 `clk_bit`), `usb_rx_datapath` output stage + `HOLDOFF` = 64 `clk_bit`, `usb_pll_lock_det` (`clk_bit` counter), `usb_pwr_seq` `clk_bit`-side copies, `usb_afe_rx_if` enables, RESETB synchronizer in `usb_ulpi_phy_pads`, FS/LS serializer timing (`FS_DIV` 40 = 5 ticks, `LS_DIV` 320 = 40 ticks) | Counts `clk_bit` cycles. | Rescale constants to ticks (÷8). A few cases lose resolution, see 4.6. |
| **C. Real bit-rate logic** | `usb_tx_serializer` (HS shift / bit counter / EOP), `usb_afe_tx_if` (lead / lag delay line, retiming), `usb_rx_fsls_frontend` (40× / 320× oversampling DPLL), `usb_rx_hs_frontend` + HS `usb_rx_decoder` + elastic-buffer write side (`clk_rx`), `usb_afe_rx_if` squelch / lock / delay (`clk_rx`), `usb_clk_gen` | Needs one action per bit or per sample. | **Split.** A thin 480 MHz shift-register layer stays; the decisions move to 60 MHz as 8-bit-wide logic. |

## 3. Target architecture

### 3.1 Clocks

| Clock | Frequency | Source | Contents |
|---|---|---|---|
| `clk_bit` | 480 MHz | PLL | **480 MHz island TX/FS-RX** (3.2): PISO, sampler, ÷8 counter, CLKOUT flop, lock-detector LSBs |
| `clk60` | 60 MHz, 50 % | `usb_clk_gen`, generated from `clk_bit` (÷8), free-running while `clk_bit` runs | **Everything else**: ULPI core, register files, TX byte path, RX decoders (HS and FS/LS), LineState, mode / termination control, status sync, output stage |
| `clk_rx` | 480 MHz ± 1000 ppm | CDR | **480 MHz island HS-RX** (3.3): capture, squelch sync, lock / delay, 1:8 SIPO |
| `clk_rxw` | `clk_rx` / 8 | generated in the HS-RX island | Write side of the HS word FIFO only |
| `ref_clk` | 24 MHz | REF_DIG | `usb_pwr_seq`, lock-detector reference side (unchanged) |
| `CLKOUT` | 60 MHz | gated copy of `clk60` (stops low in clock suspend, as today) | ULPI pad |

`clk60` and `clk_bit` are **synchronous** (generated clock, known phase). The 480↔60 boundary needs no
synchronizers, only a defined phase signal and SDC multicycle constraints on about 60 boundary flops
(3.4). `clk60` must keep running while CLKOUT is stopped. Today `ce60` keeps running whenever
`clk_bit` runs; the new design does the same.

**Recommendation: a real divided clock, not ICG gating.** Gating `clk_bit` with `ce60` (an ICG) would
give a 1.04 ns-wide pulse every 16.7 ns. That leaves the same 480 MHz insertion-delay and skew
problems and a min-pulse-width risk on xh018. A 50 % ÷8 clock from a flop, buffered by CTS as its own
tree, is the standard solution.

### 3.2 480 MHz island on `clk_bit` (target ≤ ~120 flops, every path flop → ≤ 1 gate → flop)

```
 clk60 domain (8-bit vectors per tick)          clk_bit island                   AFE pins
 ──────────────────────────────────────         ────────────────────             ─────────
 usb_tx_serializer60 ─ txd_v[7:0] ─┐
                    ─ en_v[7:0]  ──┤ usb_afe_tx_if60 ─ p_v, n_v, en_v, ┐
                    ─ se0_v[7:0] ──┘ (lead/lag as     fsoe_v, fsdat_v, ├─> usb_tx_piso ─> hs_tx_p/n, hs_tx_en,
                                      word delay +    fsse0_v [7:0]    ┘   (6 × 8:1,     fs_oe/dat/se0
                                      bit shift)                            load on phase) (+ iso clamp)

 usb_rx_fsls_dpll60 <─ rcv_v, dp_v, dm_v [7:0] ─ usb_rx_fsls_sampler <─ rxrcv, rxdp, rxdm (2-FF + 1:8 SIPO)

 usb_clk_gen: ÷8 Johnson counter (phase_j[3:0], ld = phase 3) ─> clk60 (core), CLKOUT (falling-edge flop, gated)
 usb_pll_lock_det: phase[2:0] reused as 3 LSBs of the frequency count
```

- **TX PISO** (`usb_tx_piso`, new): one 8-bit shift register per pin, loaded on the `clk_bit` edge that
  goes with the `clk60` edge (phase 7, the old `ce60` position), shifted on the other 7. `hs_tx_n`
  gets its own PISO, loaded with the complemented vector, so P and N still come from separate flops.
  The output flops stay the last stage. The idle clamp (`iso_en`, `drv_dis`) stays here as a
  synchronous force on the output flops, so the clamp keeps acting on "the second `clk_bit` edge"
  (spec 4.1).
- **FS/LS sampler** (`usb_rx_fsls_sampler`, new): 2-FF synchronizers for `rxrcv` / `rxdp` / `rxdm`
  (moved out of `usb_rx_status_sync` and `usb_rx_fsls_frontend`), then a 1:8 SIPO per signal, captured
  into a word register on phase 7. It delivers 8 samples per tick (40 per FS bit, as today). `usb_line_state`
  takes the newest sample of `dp_v` / `dm_v` (bit 7).
- **`usb_clk_gen`**: the ÷8 counter, the `clk60` generator and the CLKOUT falling-edge flop remain;
  `ld` (phase 3, island registers update on E4, see 3.4) is the phase signal for the islands; `ce60`
  stays for the modules not moved yet. CLKOUT stays a separate flop from the core `clk60` so it can
  stop low while the core clock runs. *Done in P1:* the counter is a 4-bit Johnson counter (every
  480 MHz path flop → ≤ 1 gate → flop; the binary counter missed the slow corner by 1 ns).
- **Lock detector**: the frequency count = 8 × (`clk60` count) + phase difference at the window ends.
  The 3-bit phase comes from the `usb_clk_gen` counter, which already runs at 480 MHz. The resolution
  stays at 1 `clk_bit` (±5 of 5120, ±0.1 %) without a 13-bit 480 MHz counter. The heartbeat becomes
  `clk60` / 16 (same period, 128 `clk_bit`).

### 3.3 480 MHz island on `clk_rx` (target ≤ ~50 flops)

```
 hs_rxd_a, squelch_a ─> usb_afe_rx_if (iso, squelch 2-FF, lock_dly, 3+sq_comp delay)   [clk_rx]
                     ─> usb_rx_hs_sipo: 1:8 SIPO of data + "valid" mask, ÷8 counter → clk_rxw  [clk_rx]
                     ─> usb_rx_word_fifo (Gray, ASYNC, 8 entries × {d[7:0], v[7:0], last})   [clk_rxw → clk60]
                     ─> usb_rx_decoder8 (HS, 8 bits / tick)                                  [clk60]
```

- The bit-precise parts of `usb_afe_rx_if` (squelch synchronizer, `lock_dly` mask, `sq_comp` data delay)
  stay at bit rate, because the SYNC budget measured in A3 depends on them to the bit. The registered
  enables `rx_en_hs` / `cdr_en` move to `clk60`.
- The SIPO packs 8 recovered bits plus a per-bit valid mask (= `hs_cdr_lock` and not squelch, per bit)
  into one word on `clk_rxw`. The FIFO moves **raw words**, not events, so the HS decoder runs in the
  `clk60` domain.
- **Write only while the mask is not all-zero, plus one closing word on squelch.** The FIFO then
  carries no idle traffic between packets and cannot drift empty or full. Within one packet the drift
  is ≤ 1 000 ppm × ~1 100 words (max. 1024-byte packet) ≈ 1.1 words. The decoder consumes words when
  they are present and tolerates gaps (a slower far end), so the FIFO needs no pre-fill. 8 entries are
  enough. This replaces the `clk_rx` write side that currently fails at 2.98 ns slow.
- `clk_rxw` comes from a counter flop on the free-running CDR clock (D1). Its reset release
  synchronizer moves from `usb_rx_datapath` into the island.
- **Alternative (recommended to ask, I12 / Q1):** if the CDR can deliver 1:8 data plus a word clock,
  the SIPO moves into the AFE and the `clk_rx` island shrinks to the squelch / lock logic.
  The digital plan does not depend on it. Rephrase Q1 / I12 from "1:4 at 120 MHz" to "1:8 at 60 MHz,
  or serial as today", because a 120 MHz word clock would add a third digital frequency.

### 3.4 The 480↔60 boundary (synchronous)

*Decided in P1 (part of D10), replacing the first draft (load on phase 7 = the `clk60` edge,
multicycle 8 / 7):* island registers on the boundary use `ld` and change / sample on **E4**, half a
`clk60` period away from the `clk60` edge E0. Reasons: (1) in RTL simulation `clk60` is a flop output
and rises one delta after `clk_bit`, so a 480 → 60 register loaded on E0 would be seen at that very
`clk60` edge (zero cycles instead of eight; `tb_usb_clk_gen` shows it on every tick); (2) both
directions get 4 `clk_bit` cycles of setup **and** of hold, so up to about ±3 `clk_bit` cycles of skew
between the two clock trees are tolerated (K3).

- **60 → 480** (TX vectors, clamp, config): launched on `clk60` (E0), captured by the PISO load on
  `ld` (E4). SDC: `set_multicycle_path -setup -end 4` / `-hold -end 3` from `clk60` to `clk_bit`.
  Only ~50 flops.
- **480 → 60** (sampler words, lock-count LSBs): the word register is loaded on `ld` (E4) and held for
  8 `clk_bit` cycles; it is captured at the next `clk60` edge (E8 = E0). SDC:
  `set_multicycle_path -setup -start 4` / `-hold -start 3` from `clk_bit` to `clk60`.
- **Rule:** every crossing follows this; the multicycles in `constraints/usb_phy.sdc` are only
  correct then. A crossing on any other `clk_bit` edge is a bug.
- **Phase alignment:** E0 (`clk60` rising) and E4 (`ld` registers) come from the same counter, after
  CTS. `clk60` is a dedicated flop (copy of the counter MSB), so the relationship is fixed by
  construction. STA checks it with `create_generated_clock -divide_by 8`.
- **ULPI I/O:** the core now samples and launches on its own `clk60` tree, not on a `clk_bit` edge
  ~1 ns after CLKOUT. Hold for the Link becomes CLKOUT-pad delay vs. core-clock insertion delay plus
  the input pad delay. WORK_PLAN 9.1 has to be redone for that case (ULPI 1.1: 5 ns setup / 0 ns hold
  at the PHY). Option if the margin is too small: launch CLKOUT from a `clk_bit` flop that leads the
  core clock by one or more `clk_bit` cycles (selectable, like today's half-cycle).

## 4. Module-by-module changes

### 4.1 Group A: clock swap only (no functional change)

`usb_ulpi_core` and its submodules, `usb_ulpi_rx_path` and submodules, `usb_ulpi_reg_file`,
`usb_afe_trim_regs`, `usb_tx_holding`, `usb_tx_sync_mux`, `usb_bit_stuffer`, `usb_nrzi_encoder`,
`usb_mode_term_ctrl`, `usb_line_state`.

- Step 1: in the parents (`usb_ulpi_phy_if`, `usb_ulpi_phy_top`, `usb_tx_datapath`), connect `clk60`
  and tie `ce` / `ce60` to `1'b1`. No change in the leaves: all their state is already under `ce`.
  Synthesis removes the enable muxes.
- Step 2 (later, optional cleanup): remove the `ce` ports and the `ce &&` terms. Keep the port in the
  submodules if the TBs still use it (it costs nothing once tied).
- Checks: `usb_mode_term_ctrl` clamps on `iso_en` immediately. That becomes a `clk60` edge, up to
  16.7 ns instead of 2.08 ns: acceptable (break-before-make is already 2 ticks), but update the header.
  In `usb_line_state`, `DISC_TAIL` = 32 `clk_bit` becomes 4 ticks (range 1..63 → 1..7 ticks, or keep the
  6-bit counter in ticks).
- **The ULPI read-timing rule (Fig. 22 / 30), the TX/register interlocks and the holding state
  depend only on ticks and are not affected.**

### 4.2 TX path

| Module | Change |
|---|---|
| `usb_tx_serializer` | Rewrite as **`usb_tx_serializer`(60 MHz) producing 8-bit vectors per tick**: `txd_v`, `en_v`, `se0_v` (bit 0 = first `clk_bit` of the tick). **HS:** the input word goes straight into `txd_v` for 8-bit words. For the last word (`in_nbits` < 8) and the EOP, the 8 EOP bits (or `eop_dis`) are spliced in at bit position `in_nbits`: a two-word window with a barrel shift (≤ 8 → 16 bits). `tx_underrun`, `tx_done`, `in_ready` keep their meaning in ticks. **FS/LS:** the bit timer counts ticks (`FS_TK` = 5, `LS_TK` = 40, exact since 40 = 5 × 8 and 320 = 40 × 8); all 8 bits of each vector are equal. `FS_DIV` / `LS_DIV` / `DIV_W` turn into tick parameters (`DIV_W` 6). |
| `usb_tx_path`, `usb_tx_datapath`, `usb_ulpi_core`, `usb_ulpi_tx_top` | Pass the vectors; `tx_en` / `tx_se0` / `txd` scalar outputs disappear in favour of the vector bus. `tx_en_any` (= \|`en_v`) is still needed for the RX hold-off and LineState. |
| `usb_afe_tx_if` | Split: **`usb_afe_tx_if`(60 MHz)** with driver select, `lead_first`, lead / lag and the idle logic; the lead becomes a delay of ⌊lead/8⌋ words plus a (lead mod 8)-bit shift across the previous word (16-bit window). `hs_tx_en` rises `tx_lead` bits ahead as before, and the lag is counted in bits the same way. Output: 7 vectors (`p`, `n`, `en`, `fs_oe`, `fs_dat`, `fs_se0`, plus static `fs_ls`). **`usb_tx_piso` (new, 480 MHz)**: shift and clamp. The latency contract changes from "data `tx_lead` + 3 bits, TX_EN 3" to "`tx_lead` + 8·k + c bits" with a fixed, documented c; recompute it and update spec 4.1. Lead ≤ 31 → 4 words of delay line × 8 bits × 6 pins in 60 MHz flops (cheap). |

### 4.3 RX path

| Module | Change |
|---|---|
| `usb_rx_fsls_frontend` | **`usb_rx_fsls_sampler`** (480 MHz, new, 3.2) + **`usb_rx_fsls_dpll`** (60 MHz): per tick it finds the first symbol change in the 8-sample vectors (priority encoder over `sym_v[i] != sym_v[i-1]`), restarts the bit-phase counter (counted in samples, 9 bits) at that sample index, and emits a strobe when the half-bit point falls inside the current tick, selecting the sample at that index. At FS / LS there is at most one strobe per tick, so the decoder sees ≤ 1 bit per tick. Same behaviour as today (edge-to-centre, glitches < ½ bit never sampled); the phase resolution stays one `clk_bit` sample. |
| `usb_rx_decoder` (+ `nrzi_decoder`, `sync_detect`, `bit_unstuffer`, `deserializer`, `eop_check`) | **New `usb_rx_decoder8`** on `clk60`: input per tick {`d[7:0]`, `v[7:0]`/`n`, `se0`}, n = 0..8 valid bits. NRZI: XOR with the bit shifted by one (8 parallel XORs). SYNC detect: zero-run counter over the vector (`ZMIN` check per bit position, ≤ 8 positions). Unstuff: mark stuff positions (run of 6 ones; ≤ 2 per 8 bits), compact the vector (8→6..8 bits) and append to a 16-bit accumulator; emit a byte when ≥ 8 bits. EOP: HS = stuff violation with exactly 7 residual bits, FS/LS = SE0 with 0 residual bits, unchanged rules. **One instance serves both HS (8 bits/tick) and FS/LS (≤ 1 bit/tick)**, selected by speed. This removes one decoder copy and the FS/LS elastic buffer. Expect ~10–14 ns of logic at the slow corner: comfortable in 16.7 ns, but check SYNC/unstuff at the slow corner first (prototype in step P3). |
| Events per tick | At HS one tick can produce two events (last byte + END, or START + first byte). Keep a 4-entry synchronous event FIFO in front of the `usb_rx_datapath` output stage, so the "one event per tick" contract to `usb_ulpi_rx_handler` is unchanged. The rate is unchanged (on average < 1 event/tick). |
| `usb_rx_elastic_buffer` | Reused as `usb_rx_word_fifo` (ASYNC = 1, W = 17, AW = 3), `clk_rxw` → `clk60`. ASYNC = 0 mode no longer needed. |
| `usb_rx_hs_frontend` | Absorbed into `usb_rx_hs_sipo` (clk_rx) + decoder input stage (clk60). |
| `usb_afe_rx_if` | Squelch / lock / delay stay on `clk_rx` (unchanged logic); `rx_en_hs` / `cdr_en` registers move to `clk60`; the data and mask go to the SIPO. |
| `usb_rx_datapath` | New structure: sampler + HS SIPO/FIFO → mux → `decoder8` → event FIFO → output stage. `HOLDOFF` = 64 `clk_bit` → 8 ticks. The `clk_rx` reset synchronizer moves to the HS island. Output contract to `usb_ulpi_rx_path` unchanged. |
| `usb_rx_status_sync` / `usb_rx_status_flt` | `rxdp` / `rxdm` / `rxrcv` groups move to the sampler. Squelch / disc filters on `clk60`: `sq_flt` default 2 `clk_bit` (6.25 ns total) → 0–1 ticks. The resolution drops from 2.08 to 16.7 ns, which only affects HS LineState and HostDisconnect (both reported per tick anyway). VBUS / ID: unchanged (already ticks). |

### 4.4 Clocks, reset, power

| Module | Change |
|---|---|
| `usb_clk_gen` | ✅ P1: `clk60` core-clock output (50 %, free-running, not gated), `phase_j[3:0]` (Johnson code) and `ld` (phase 3) for the islands; `ce60` kept for the modules not moved yet. CLKOUT behaviour unchanged (stops low, `clk_on`); the port is now `clkout`. |
| `usb_pll_lock_det` | `clk60` counter (10 bits) + 3 phase LSBs from `usb_clk_gen` at the window ends; range check unchanged in `clk_bit` units. Heartbeat from `clk60`. Removes the 1.63 ns slow-corner failure. |
| `usb_pwr_seq` | `clk_bit`-side copies (`core_rst_n_b`, `iso_en_b`, `dir_hold_b`, `afe_en_b`, `clk_en_b`) → `clk60` side, released after 2 `clk60` edges (33 ns instead of 4 ns; the power-up times in spec 5 change by < 0.1 µs). Async assert unchanged. `clk_en_b` feeds the CLKOUT gate in `usb_clk_gen`, which runs at 480: keep that one copy on `clk_bit`. |
| `usb_ulpi_phy_pads` | RESETB synchronizer on `clk60` (core reset) plus a separate synchronizer per island clock (`clk_bit`, `clk_rx`). `clk60` / `ce60` inputs are replaced by `clk_bit` → `usb_clk_gen` when Phase 8.1 wires it in. |
| Reset domains | `por_n` (clk gen, lock det, pwr_seq) / core reset on `clk60` / island resets on `clk_bit` and `clk_rx` (async assert, sync release, 2 FF each). |

### 4.5 Parameter / constant rescaling summary

| Constant | Today (`clk_bit`) | New (`clk60` ticks) |
|---|---|---|
| `FS_DIV` / `LS_DIV` (TX) | 40 / 320 | `FS_TK` 5 / `LS_TK` 40 (TX), samples 40 / 320 stay in the RX DPLL |
| `HOLDOFF` | 64 | 8 |
| `DISC_TAIL` | 32 | 4 |
| `sq_flt` / `disc_flt` | cycles (default 2) | ticks (default 0 or 1, see 4.3) |
| `usb_pll_lock_det` `CW` | 13-bit `clk_bit` counter | 10-bit `clk60` + 3-bit phase |
| `BBM_TK`, `SE_FS`, `SE_LS`, `CH_TK`, `vb_flt` | already ticks | unchanged |
| `tx_lead` / `tx_lag`, `lock_dly` / `sq_comp` | bits | bits (unchanged, implemented across word boundaries) |

### 4.6 Behaviour that changes (documentation and spec updates)

1. TX latency from ULPI to the line grows by up to one word (PISO load). Check the PHY TX start-delay
   budget (ULPI / USB 2.0 HS: the inter-packet and response-time budget, 192 bit times for a device
   response) with the new numbers.
2. The `iso_en` / `drv_dis` clamp keeps bit-rate latency on the pins (clamp in the PISO), but the
   60 MHz logic behind it reacts one tick later.
3. Squelch / disconnect glitch filters have 16.7 ns resolution.
4. RX latency changes (SIPO + word FIFO + parallel decoder). The SYNC budget (A3 results) is not
   affected, because the squelch / lock / delay alignment stays bit-exact on `clk_rx`. Re-run the A3
   sweep to confirm.
5. ULPI I/O timing reference changes from "`clk_bit` edge ~1 ns after CLKOUT" to the `clk60` tree
   (3.4).

## 5. Verification impact

- **25 testbenches** (`tb_*.v` plus `AFE/ams` shadows / `.vh`) reference `clk_bit` or `ce60`. Most
  only generate the clock; switching them to `usb_clk_gen` or a 60 MHz generator with an
  aligned 480 MHz clock is mechanical.
- **Cycle-exact checks need new numbers:** `tb_usb_afe_tx_if` (data / TX_EN latency, lead / lag),
  `tb_usb_tx_serializer` (EOP and bit timing at `txd`: rebuild the serial stream from the vectors
  in the TB, or observe after the PISO), `tb_usb_line_state` / `tb_usb_afe_fsls` (LineState latency in
  `clk_bit` cycles, limit 124 at LS), `tb_usb_pwr_seq` / `tb_ams_pwr_shadow` (release times),
  `tb_usb_pll_lock_det` (lock timing), `tb_usb_rx_status_sync` (filter lengths).
- **Keep the line-level checkers unchanged:** the testbenches that rebuild packets from the line
  (de-NRZI, de-stuff, EOP timing) and the reference decoders in `tb_usb_afe_tx_if` /
  `tb_usb_afe_chirp` are the regression oracle. They must pass unchanged, apart from documented
  latency constants.
- **New unit TBs:** `tb_usb_tx_piso`, `tb_usb_rx_fsls_sampler` (+ DPLL), `tb_usb_rx_hs_sipo`,
  `tb_usb_rx_decoder8` (compare bit-for-bit against the existing serial `usb_rx_decoder` on random
  streams, stuff patterns, all 8 SYNC/EOP phase positions within a word, FS SE0 glitches), and
  `tb_usb_clk_gen` if `clk60` / phase are added there.
- **Equivalence strategy:** keep the old serial `usb_rx_decoder` and `usb_tx_serializer` in the repo
  as reference models (`ref_*` or TB-only) until the new ones pass the integration TBs, then remove
  them.
- **AMS rule (CLAUDE.md):** the TX/RX AFE boundary modules change, so update `AFE/ams/ams_phy_end.v`,
  the `.vh` sequences, the shadows `tb_ams_link_shadow` / `tb_ams_pwr_shadow`, the `xrun` headers and
  the `run_ams_tests.sh` entries in the same step.
- **Synthesis:** `run_synth.sh` gets the new tops (`usb_tx_piso`, `usb_rx_fsls_sampler`,
  `usb_rx_hs_sipo`, `usb_rx_decoder8`) and a per-clock flop report (expect ≤ ~170 flops at 480 MHz
  in total, against ~1 250 today).
- **STA (new, needed before claiming success):** OpenSTA with an SDC: `clk_bit` 2.08 ns, generated
  `clk60` ÷8, `clk_rx` 2.08 ns ± 1000 ppm, generated `clk_rxw` ÷8, the boundary multicycles of 3.4,
  false paths through the 2-FF synchronizers and the Gray FIFO (max-delay on the Gray buses), and
  ULPI I/O constraints relative to CLKOUT. Slow corner first. This is WORK_PLAN 9.1, done earlier
  and with fewer multicycle exceptions.

## 6. Action plan (phases)

Each step leaves `./run_tests.sh` green and `./run_synth.sh` passing. Steps P1–P2 are pure
refactoring with no behaviour change on the pins.

| Step | Content | Done when |
|---|---|---|
| **P0 — Decisions** | Confirm with the analog team: serial CDR data + digital 1:8 SIPO (this plan) vs. 1:8 from the CDR (reword I12 / Q1). Agree on the ULPI I/O timing reference (3.4). Record as decision D10 in `WORK_PLAN.md`. | D10 recorded; I12 updated. |
| **P1 — Clock generator** | `usb_clk_gen`: add `clk60` (core clock) and `phase` / `ld`; new `tb_usb_clk_gen` (or extend `tb_usb_pll_lock_det`). Add SDC skeleton `constraints/usb_phy.sdc` with the generated clocks. Install / script OpenSTA if possible and run it on the existing design as a baseline. | `clk60` is 50 %, aligned with `ce60`; baseline STA report in `build/`. |
| **P2 — Group A swap** | `usb_ulpi_phy_top` / `usb_ulpi_phy_if` / `usb_tx_datapath` ULPI blocks on `clk60` with `ce` = 1; rescale `DISC_TAIL`; `usb_mode_term_ctrl` / `usb_afe_trim_regs` / `usb_line_state` on `clk60`. For this step the TX serializer stays on `clk_bit` and takes its bytes via the 3.4 boundary (the byte interface is already a ce60 handshake). TBs: generate `clk60` from `clk_bit` with the same alignment. | All ULPI-level TBs (`tb_usb_ulpi_*`, `tb_usb_tx_holding`, `tb_usb_ulpi_phy_pads`) pass unchanged in ticks. |
| **P3 — RX decoder (biggest technical risk first)** | `usb_rx_decoder8` + `tb_usb_rx_decoder8` with bit-for-bit comparison against `usb_rx_decoder`. Synthesize alone at the slow corner and check the longest path. | Equivalent on ≥ 10⁵ random packets; path < ~14 ns slow. |
| **P4 — FS/LS RX** | `usb_rx_fsls_sampler` + `usb_rx_fsls_dpll`; take `rxdp` / `rxdm` / `rxrcv` out of `usb_rx_status_sync`; feed `usb_line_state` from the sampler. Rebuild the FS/LS half of `usb_rx_datapath` with the decoder8. | `tb_usb_rx_fsls_frontend` (rewritten), `tb_usb_rx_datapath` FS/LS cases, `tb_usb_afe_fsls` pass; LineState latency within the UTMI limits. |
| **P5 — HS RX** | `usb_rx_hs_sipo` (with `usb_afe_rx_if`'s bit-exact squelch / lock / delay on `clk_rx`), `usb_rx_word_fifo`, HS through decoder8, event FIFO, `HOLDOFF` in ticks. Remove the FS/LS elastic buffer and the second decoder instance. | `tb_usb_rx_datapath` (all ppm cases), `tb_usb_afe_rx_if` sweep with the same or better A3 results, `tb_usb_afe_chirp` pass. |
| **P6 — TX** | `usb_tx_serializer` (vectors, 60 MHz), `usb_afe_tx_if` (60 MHz, word lead / lag), `usb_tx_piso` (480 MHz) + clamp. New latency constants in spec 4.1 and the TB checks. | `tb_usb_tx_serializer`, `tb_usb_tx_path`, `tb_usb_afe_tx_if`, `tb_usb_ulpi_tx_top`, `tb_usb_ulpi_core`, `tb_usb_afe_chirp` pass; the line-level decoders see identical packets. |
| **P7 — Lock detector, power sequencer, pads, status sync** | `usb_pll_lock_det` (60 MHz + phase LSBs), `usb_pwr_seq` `clk60`-side copies, RESETB / island reset synchronizers, `usb_rx_status_sync` filters in ticks. | `tb_usb_pll_lock_det`, `tb_usb_pwr_seq`, `tb_usb_rx_status_sync`, `tb_ams_pwr_shadow` pass with updated timing. |
| **P8 — AMS and docs** | Update `ams_phy_end.v`, `.vh`, shadows, AMS tops / control files; `CLAUDE.md` ("one clock" rule → "three clocks + one generated"), module headers, `DOC/afe_interface_spec.md` (2, 4.1, 4.2, 7.2), `WORK_PLAN.md` (D1, 5.2, 9.1, 9.3, R1), `AFE_INTEGRATION_PLAN.md` (I12). | All 38+ TBs pass; `run_ams_tests.sh` runs (SKIP without `xrun`); docs consistent. |
| **P9 — Cleanup and STA sign-off** | Remove the `ce` ports where unused and the old serial reference models (or move them to TB-only `ref_*.v`); full SDC; OpenSTA slow / typ / fast. | No setup / hold violations at the slow corner on `clk_bit` / `clk_rx` islands and `clk60`; flop count per clock reported. |

Order: P0 and P1 first; P2 is independent and gives early power numbers; P3 before P4 / P5 because
the parallel decoder is the main unknown; P6 can run in parallel with P4 / P5. P7 and P8 close the
work. This plan should be done **before** Phase 8.1 (top-level wiring of the clock / power / AFE
blocks), so that wiring is done once, on the new clock structure.

## 7. Risks and open points

| # | Risk | Mitigation |
|---|---|---|
| K1 | Parallel unstuffer / SYNC detector longer than expected at the slow corner. | P3 measures it first; fallback: pipeline the decoder by one tick (latency only). **P3: happened** (a direct unrolling: 33.6 ns); closed with closed-form per-bit logic in three stages, 13.7 ns (8.5). |
| K2 | ULPI hold time once the core uses its own `clk60` tree instead of a `clk_bit` edge. | 3.4: CLKOUT launch selectable in `clk_bit` steps; check in STA with pad delays. |
| K3 | PISO load phase and `clk60` edge misaligned after CTS. | Generate both from the same ÷8 counter; constrain with `create_generated_clock`; the multicycle covers up to 7 `clk_bit` cycles of skew in data, not the clock itself. |
| K4 | TX start latency grows beyond the USB / ULPI budget. | Recompute in P6; the lead delay line already costs `tx_lead` bits, the PISO adds ≤ 8. **P6:** +9 bit times against the single-clock chain (+13 against P2), data `tx_lead` + 12 after the serializer bit (spec 4.1, 8.8); check against the budget with the full chain. |
| K5 | `clk_rxw` from a CDR clock that glitches when the CDR re-locks. | Confirm D1 (free-running, glitch-free) with the analog team in P0; the FIFO is reset while squelched. |
| K6 | Many TBs depend on `clk_bit`-cycle counts. | Change them per step, keep line-level oracles fixed, and document every changed constant in the TB header. |
| K7 | LS LineState latency limit (124 `clk_bit`, measured 117) with the new sampler path. | The sampler adds ≤ 8 + 2 cycles; recheck in `tb_usb_afe_fsls`. If it is too slow, take LineState from the newest sample in the vector (bit 7, not the word register). |
| K8 | *(new, P1)* The 480 MHz islands themselves are marginal at the slow corner. X1 flop overhead is ≈ 1.6 ns of the 2.03 ns budget (clock-to-Q 0.9–1.2 ns with a few loads, setup 0.7 ns): a flop-to-flop path with fan-out ≈ 0 ns slack, one gate is negative, and a half-cycle path (CLKOUT falling-edge flop) fails by 0.46 ns with no logic at all. A PISO with a load mux in front of every flop does not close as written. | Numbers are from an unsized mapping (no buffering, no sizing, section 8): get sized numbers first (a real synthesis flow or OpenROAD `repair_timing`). Design options: PISO without a mux in the shift path (e.g. 8 parallel phase flops and an AND-OR into a final retiming flop, or two 4:1 halves at 240 MHz), CLKOUT from a rising-edge flop (K2), and ask the analog team for an 8:1 TX serializer next to the 1:8 RX question (I12). Decide before P6. |
| K9 | *(new, P1)* The register-read path (`u_reg.st` → read mux → `u_bus.data_r`) is ≈ 17 ns unsized at the slow corner, longer than the 16.7 ns `clk60` period. Most of it is two unbuffered nets with fan-out 18–20 (≈ 6 ns). | Check it with sizing / buffering before P2 closes; fallback: register the read address decode (the D7 read timing leaves no spare tick, so only within the tick). |

## 8. Status and results

| Step | Status |
|---|---|
| P0 | Open. D10 proposed in `WORK_PLAN.md` (serial CDR data + digital 1:8 SIPO; ULPI I/O reference; boundary convention of 3.4). I12 / Q1 reworded in `AFE_INTEGRATION_PLAN.md`. Needs the analog team's answer. |
| P1 | ✅ 2026-11-14. `usb_clk_gen`: Johnson ÷8 counter, `clk60`, `phase_j`, `ld`, CLKOUT port renamed `clkout`; `tb_usb_clk_gen` (reference model, reset mid-period, every illegal counter state, 60↔480 loopback). `constraints/usb_phy.sdc` skeleton; `run_sta.sh` (OpenSTA); baseline below. All 39 TBs pass, `run_synth.sh` passes. |
| P2 | ✅ 2026-11-14, with the deviations of 8.3. `usb_ulpi_phy_top` / `usb_ulpi_phy_if` / `usb_ulpi_core` / `usb_tx_datapath` / `usb_ulpi_tx_top` / `usb_ulpi_phy_pads` take `clk60` + `ld` instead of `ce60`; all ULPI-domain leaves (core, RX path, reg file, trim regs, mode / termination control) on `clk60` with `ce` = 1; the TX serializer stays on `clk_bit` behind the new `usb_tx_ser_bridge` (`usb_tx_path` parameter `SPLIT`). New `tb_usb_tx_path_split`. All 40 TBs pass; the ULPI-level TBs give the same packet / retry counts as before. |
| P3 | ✅ 2026-11-14, see 8.5. New `usb_rx_decoder8` (3-stage parallel RX bit chain, one instance for HS and FS/LS) + `tb_usb_rx_decoder8` (event-for-event against `usb_rx_decoder`, exact backpressure). Slow corner: 13.7 ns worst path (+2.9 ns slack at 16.7 ns), typ +9.8 ns. Equivalent on the 1000-packet default run and in mutation tests; exit criterion met: 10⁵ packets (seeds 11 and 22, 5·10⁴ each, 0 errors; 4989 two-event ticks incl. 768 END+START). Wired in for FS/LS in P4; HS in P5. |
| P4 | ✅ 2026-11-14, see 8.6. New `usb_rx_fsls_sampler` (clk_bit island, 54 flops) + `usb_rx_fsls_dpll` (clk60); FS/LS half of `usb_rx_datapath` = sampler → DPLL → `usb_rx_decoder8` → 4-entry event FIFO; output stage and hold-off on clk60; `usb_line_state` on clk60 fed from the sampler; `rxdp` / `rxdm` / `rxrcv` out of `usb_rx_status_sync`. `tb_usb_rx_fsls_frontend` rewritten (sample-exact against the old front end), `tb_usb_rx_datapath`, `tb_usb_afe_fsls`, `tb_usb_afe_chirp` pass with unchanged packet counts; LineState J/K latency 19 cycles (≤ 3 ticks). |
| P5 | ✅ 2026-11-15, see 8.7. New `usb_rx_hs_sipo` (`clk_rx` island: `usb_rx_hs_frontend` unchanged, 1:8 SIPO, Johnson word clock `clk_rxw`, write gate) + word FIFO (`usb_rx_elastic_buffer` W 16 / AW 3, `clk_rxw` → `clk60`); one `usb_rx_decoder8` for HS and FS/LS, generalized to `ZMIN_HS` 4..8 (two SYNCs / four events per tick, K11 closed); 8-entry event FIFO with four write ports and a direct output path. Serial HS decoder and HS event buffer removed from the datapath. A3 sweep (`tb_usb_afe_rx_if`) and `tb_afe_hs_chain`, `tb_usb_afe_chirp`, AMS shadow: output identical to before P5. HS RX latency +2 ticks (K12). |
| P6 | ✅ 2026-11-15, see 8.8. New `usb_tx_serializer8` (clk60, 8 line bits per tick, HS EOP splice, FS/LS tick bit timer), `usb_afe_tx_if8` (clk60: driver select, 40-bit lead window, lag dilation, pin vectors) and `usb_tx_piso` (clk_bit: 8:1 shift loaded on `ld`, idle clamp, 68 flops). `usb_tx_path` is clk60 only (`SPLIT` and `usb_tx_ser_bridge` removed); the ULPI tops lose `clk_bit` / `ld` and output `txd_v` / `tx_en_v` / `tx_se0_v`. New `tb_usb_tx_vec`: bit-exact against the bit-serial chain, pins LAT = 9 cycles later. All 42 TBs pass with unchanged packet checks; the bit-serial `usb_tx_serializer` / `usb_afe_tx_if` stay as reference models. |
| P7 | ✅ 2026-11-15, see 8.9. `usb_pll_lock_det` on `clk60` (count = ticks × 8 + position of the window-end flag change in an 8-sample `clk_bit` word, 17-flop island; heartbeat `clk60` / 16); `usb_pwr_seq` core-side copies on `clk60` (`core_rst_n_c`, `iso_en_c`, `dir_hold_c`, `afe_en_c`; `clk_en_b` stays on `clk_bit`); `usb_ulpi_phy_pads` exports the `clk_bit` island reset `bit_rst_n`; `usb_rx_status_sync` outputs on `clk60` with squelch / disconnect filters in ticks (the squelch / disconnect island moved in from `usb_line_state`). `tb_usb_pll_lock_det` (every window count exact against a bit-rate counter), `tb_usb_pwr_seq`, `tb_usb_rx_status_sync` (rewritten, tick reference), `tb_ams_pwr_shadow` pass; all 42 TBs pass. |
| P8–P9 | Not started. |

### 8.1 P1 notes

- **First tick after reset:** the Johnson counter resets into phase 4, so the first `clk60` edge (and
  the first `ce60` tick) comes 4 `clk_bit` edges after the reset release instead of 8. No testbench
  depends on it.
- **STA flow (`run_sta.sh`):** Yosys maps for delay onto the corner's Liberty **without the X0 cells**;
  STA reads the full library. Yosys 0.33 does no gate sizing and no buffering on this library (every
  cell ends up X1 at any `abc -D` target), and X0 cells add ≈ 0.5 ns per stage at the slow corner.
  Ideal clocks, no wires, no I/O constraints. So the numbers are pessimistic on high-fan-out nets and
  optimistic on wires and clocks: use them to compare designs and find structural problems, not
  for sign-off.
- **Legacy `ce60` paths** are timed single-cycle at 480 MHz (deliberately, see the SDC), so the large
  negative numbers of the ULPI tops are mostly 8-cycle paths. They are the work list of P2–P7.

### 8.2 Baseline STA, before any module moves (2026-11-14, slow corner 1.62 V / 125 °C)

`./run_sta.sh` (setup WNS / TNS in ns, violating endpoints; hold: no violations in any top level at
any corner):

| Top | WNS | TNS | #viol | Typ WNS | Fast WNS |
|---|---|---|---|---|---|
| `usb_ulpi_phy_top` | −16.06 | −4461 | 477 | −6.59 | −4.52 |
| `usb_rx_datapath` | −10.83 | −2143 | 482 | −3.75 | −2.58 |
| `usb_ulpi_tx_top` | −12.17 | −989 | 169 | −4.84 | −3.35 |
| `usb_afe_tx_if` | −3.29 | −258 | 157 | −0.68 | −0.01 |
| `usb_afe_rx_if` | −1.82 | −42 | 40 | +0.29 | +0.60 |
| `usb_clk_gen` (binary counter) | −0.97 | −4.3 | 8 | +0.12 | +0.38 |
| `usb_clk_gen` (Johnson, P1) | −0.46 | −1.9 | 6 | +0.24 | +0.46 |
| `usb_pll_lock_det` | −3.58 | −76 | 50 | −0.68 | +0.05 |
| `usb_rx_status_sync` | −6.92 | −456 | 78 | −2.31 | −1.11 |
| `usb_line_state` | −3.57 | −33 | 19 | −0.75 | +0.00 |
| `usb_mode_term_ctrl` | −2.74 | −23 | 9 | −0.28 | +0.33 |
| `usb_pwr_seq` | +0.55 | 0 | 0 | +1.29 | +1.50 |
| `usb_afe_trim_regs` | −3.06 | −46 | 102 | −0.42 | +0.21 |

The binary-counter row is the clock generator before P1 (the "worst hold" of −0.03 ns at the fast
corner there was a clock-as-data artefact of the CLKOUT flop's feedback, gone with the new
structure). The remaining `usb_clk_gen` violations at the slow corner are the half-cycle CLKOUT path
(−0.46 ns, no logic) and the `hi` / `clk_on` muxes (K8).

### 8.3 P2 notes and deviations

- **Serializer bridge instead of "bytes via the 3.4 boundary".** The serializer's `in_ready` is
  combinational from bit-rate flops and `tx_done` / `tx_underrun` are 1-cycle pulses, so the clk60
  side cannot read them directly. `usb_tx_ser_bridge` runs the serializer with `ce60` = `ld` (it
  takes words on E4), gives the clk60 side a registered "word taken" (`acc_q`) as ready, and
  collects the pulses into one-tick `tx_done_t` / `tx_underrun_t`. Result: the serializer's whole
  schedule is the old one shifted by −4 `clk_bit` cycles, every clk60-side handshake falls into the
  same tick, and **packets leave 4 bits earlier on the line** (4.6 item 1 gets better, not worse, in
  this step). Two corner cases needed care and are covered by `tb_usb_tx_path_split` (6 seeds, ~100
  HS underruns each): an underrun with `eop_dis` must block the accept until it is published, and
  the one-tick underrun can coincide with the discard of the last word (release of `drop` wins).
- **`usb_tx_path` has a `SPLIT` parameter** (0 = single clock, used by the AFE-level TBs and
  `ams_phy_end.v`; 1 = clk60 byte side + bridge, used by `usb_tx_datapath`). Both go away in P6.
- **Testbench clocks:** the ULPI-level TBs generate `clk60` with a blocking assignment on the
  `clk_bit` edge where their `ce60` was high (E0), i.e. in the same simulation region as that edge
  (ideal zero-skew clocks), and `ld` = phase 3. The Link models stay unchanged (they still act on
  `ce60` ticks of `clk_bit`). Do the same in new TBs; a `clk60` from a `usb_clk_gen` flop needs the
  boundary rule instead.
- **RESETB synchronizer moved to `clk60`** (from P7): `core_rst_n` is released on the second `clk60`
  edge after the pin (was: second `clk_bit` edge). `tb_usb_ulpi_phy_pads` checks the new timing.
- **`usb_line_state` not moved** (deferred to P4): it is not inside `usb_ulpi_phy_top`, and its inputs
  come from `usb_rx_status_sync` on `clk_bit`; it moves together with the FS/LS sampler. Its
  `DISC_TAIL` rescale moves with it.
- **Leaves unchanged.** `usb_mode_term_ctrl` / `usb_afe_trim_regs` keep their `clk_bit` / `ce` port
  names and run on `clk60` with `ce` = 1 inside `usb_ulpi_phy_top` (port renames: P9). Their
  standalone TBs and the AFE-level TBs still use them on `clk_bit` + `ce60`.
- **Inputs of `usb_ulpi_phy_top`** (RX events, LineState, status, `iso_en`, power state) are now
  clk60-domain inputs; the modules that produce them are still on `clk_bit` and are not wired in
  yet (P4–P7 move them, Phase 8.1 wires them).

### 8.4 STA after P2 (slow corner, unsized, same flow as 8.2)

| Top | WNS | TNS | #viol | Worst group |
|---|---|---|---|---|
| `usb_ulpi_phy_top` | −8.37 | −484 | 137 | `clk_bit` (serializer bit timer, P6) |
| `usb_ulpi_tx_top` | −5.20 | −334 | 89 | `clk60` |

Before P2: −16.06 / −4461 / 477 and −12.17 / −989 / 169. By path class in `usb_ulpi_phy_top`:
`clk60` → `clk60` −1.21 ns (the register-read path, K9, now against a real 16.7 ns period);
`clk60` → `clk_bit` +0.38 ns (met); `clk_bit` → `clk60` −5.28 ns (K10); `clk_bit` → `clk_bit` −8.37 ns
(the bit-serial serializer, unchanged, replaced in P6). At typ: −2.99 ns, 54 endpoints.

| # | Risk (new in P2) | Mitigation |
|---|---|---|
| K11 | *(new, P4)* `usb_rx_decoder8` needs `ZMIN_HS` ≥ 6 (two events per tick), but the AFE spec recommends `HS_ZMIN` = 4 (`tb_usb_afe_chirp`, AMS). With 4, a squelch glitch can give END, START, END in one tick. | **Closed in P5:** stage 3 handles two SYNCs per tick and four event slots (BYTE END START END / START END START END at `ZMIN_HS` = 4); `tb_usb_rx_decoder8` runs at `ZMIN_HS` 4, 5, 6 and covers every 3- and 4-event tick; long runs 2026-11-15: 25 000 packets each at `ZMIN_HS` 4 (seed 11: 120 three-event and 116 four-event ticks, 10 ticks with two drops) and 6 (seed 22), 0 errors. |
| K12 | *(new, P5)* HS receive latency vs ULPI 1.1 Table 9 (RX Start / End Delay 3–8 clocks; UTMI+ RxEndDelay ≤ 63 HS bit times). `tb_usb_rx_datapath`, ideal CDR, far-end EOP end → RxActive low (`usb_ulpi_rx_handler`): before P5 32.8–61.0 bit times, after 49.8–75.8; first SYNC bit → RxActive high 64.6–72.4 → 81.6–89.1 (incl. the 32-bit SYNC; already above 64 before P5). Cost: word assembly (≤ 8 + 4 bits) and 3 decoder ticks instead of 5 bits. | Already cut in P5: no decoder input register, direct output path (−3 ticks of the first version). Options left: first word-FIFO synchronizer flop on the falling `clk60` edge (−½ tick), write pointer on `clk_rx` (−½ tick), merging two decoder stages after sizing (−1 tick, needs sized STA). Decide with the full PHY chain once the RX datapath is wired into `usb_ulpi_phy_top` (the RXCMD path and the CDR latency add to it). |
| K10 | Island → core paths
| K10 | Island → core paths have half a tick (8.3 ns, E4 → E0). The bridge's `acc_q` / `tx_underrun_t` feed the whole combinational ready chain of the stuffer / NRZI encoder: 12.9 ns unsized, of which 6.6 ns is one unbuffered net with fan-out 34 (≈ +0.5 ns slack with a buffer tree). | Interim only: the bridge goes away in P6 (the 60 MHz serializer and the PISO boundary carry data only). Rule for P3–P6: an island register read by the core feeds a clk60 flop or only shallow logic. **Closed in P6** (8.8): bridge removed, no TX signal crosses clk_bit → clk60. |

### 8.5 P3 notes (`usb_rx_decoder8`)

- **First attempt failed timing, as K1 feared.** The serial per-bit code unrolled over the 8 slots
  of a tick is equivalent but a ripple through all slots: 33.6 ns at the slow corner; split into two
  halves still 24 ns. The decoder now computes every per-bit decision in closed form from the
  carried state (header of `usb_rx_decoder8`): zero-run windows for SYNC, a prefix rule for
  "hunting", "exactly six ones in front" windows for the stuff bits (at most two per tick, the second
  only in slot 7), balanced popcounts compared against `~n` / `-n` instead of adders, and a fixed
  order of at most four event candidates per tick (BYTE, END, START, END).
- **Three pipeline stages, one per recurrence of the serial chain** (NRZI + SYNC detect / unstuff /
  deserializer + EOP check). Worst path 13.7 ns (stage 3, data bits → event word); stages 1 and 2
  ≈ 9 ns. Latency: events in tick t+3 for bits of tick t (≈ 50 ns; serial decoder ≈ 10 ns).
- **Input format** as in 4.3 (one slot per bit instead of `d` + `n`): n = 0..8 bits per tick in slots 0..n−1 (thermometer `s_en`), with
  per-bit level / SE0 / active. **FS / LS: at most one bit per tick** (checked in simulation): eight
  FS bits could hold three events (SE0, SYNC, SE0).
- **Event output: up to two events per tick** (`ev0`, `ev1`; pairs BYTE+END and END+START occur).
  The event FIFO of P4 must take two writes per tick; `buf_afull` = fewer than 3 free entries,
  from the FIFO's current count, used in the tick in which stage 3 assembles the bits.
- **Facts the closed form relies on** (all from the serial rules, ZMIN_HS ≥ 6, ≤ 8 bits per tick):
  at most one SYNC per tick; no SYNC while a packet is open (the rearm bit in front of it ends the
  packet); at most 6 data bits behind a SYNC in its tick. Mutation tests confirm the testbench
  catches errors in each stage; the three surviving mutants are equivalent under these facts.
- **Area:** 19.8 k (924 cells, 145 flops) vs 11.6 k for the two serial decoders it replaces; the
  FS/LS elastic buffer it makes unnecessary is removed in P4.

### 8.6 P4 notes (FS/LS receive on `clk60`)

- **`usb_rx_fsls_sampler`** (clk_bit): 2-FF synchronizers, 1:8 shift registers, word register on `ld`
  (boundary rule; plan 3.2 said "phase 7", superseded by D10(d)). 54 flops, flop → ≤ 1 mux → flop.
- **`usb_rx_fsls_dpll`** (clk60): the per-sample rule of `usb_rx_fsls_frontend` in closed form.
  Because half a bit is ≥ 8 samples, a strobe within a tick can only come from the carried count:
  `strobe[i] = no change in samples 0..i && cnt == half − i`. At most one bit per tick, as
  `usb_rx_decoder8` requires for FS/LS. The "last J/K level held through SE0" of the old front end is
  equivalent to comparing with the previous sample (a sample after SE0 is a change anyway), which
  removes a mux chain. The sampler word gets a clk60 input register first (K10: island → core only
  into flops), so data reach the decoder 2 ticks after the word. `tb_usb_rx_fsls_frontend` checks
  every strobe against the old front end (same symbols, in order) and the strobe position: always
  20–27 clk_bit cycles behind the reference, so a one-sample phase error fails.
- **`usb_rx_datapath`**: ports `clk60` + `ld` instead of `ce60`; `rxdp` / `rxdm` / `rxrcv` are now
  the raw AFE outputs (the sampler synchronizes them) and new outputs `ls_dp` / `ls_dm` / `ls_rcv`
  (newest samples) feed `usb_line_state`. FS/LS chain = sampler → DPLL → `usb_rx_decoder8` (hs = 0) →
  4-entry event FIFO (two writes, one pop per tick); the FS elastic buffer and `FS_AW` are gone.
  The HS chain is unchanged on clk_rx; its elastic buffer reads on clk60. The output stage runs
  every tick. TX hold-off: a 2-flop island ORs `tx_en` per tick; the counter runs on clk60 in
  ⌈HOLDOFF / 8⌉ ticks (`HOLDOFF` stays in clk_bit cycles). The 480 MHz hold-off counter (−3.5 ns)
  is gone.
- **`usb_line_state`** on clk60 (+ `clk_bit` / `ld` for a 5-flop input island: squelch on `ld`,
  `disc` / `hs_tx_act` ORed per tick). `DISC_TAIL` is in ticks now (4 = the old 32 cycles); the
  disconnect window ends 24–32 cycles after `hs_tx_act` falls, by tick alignment. Two directed
  edge-exact cases of `tb_usb_line_state` became "late in the tail" / "after the latest window end";
  the tick reference covers the rest exactly.
- **LineState latency** (FS/LS J/K, `tb_usb_afe_fsls`): 14 → 19 clk_bit cycles (word taken on `ld`,
  read at the next E0); SE0/SE1 117 → 123. The testbench limits were 2 ticks; now 3 ticks (24 cycles),
  the "2–3 clocks" of ULPI 1.1, and the SE limits + 1 tick.
- **`usb_rx_status_sync`** keeps squelch / disconnect / VBUS / ID (the squelch / disconnect filters
  move in P7). Its testbench keeps the 9-bit vectors with the FS/LS bits tied off.
- `usb_rx_fsls_frontend` is not used by the design any more; it stays as the testbench reference
  (remove in P9 with the other single-clock leftovers).

STA, slow corner (unsized, as 8.2):

| Top | Before P4 | After P4 | Remaining violations |
|---|---|---|---|
| `usb_rx_datapath` | −10.83 / −2143 / 482 | −9.40 / −1628 / 340 | async-reset recovery on clk_rx (−9.4, rst_rx_n fan-out), clk_rx bit chain (−6.2): HS, P5; clk_bit −0.13 (single-gate island, K8); clk60 +2.53 |
| `usb_line_state` | −3.57 / −33 / 19 | −0.33 / −0.6 / 5 | clk_bit input island accumulators (single gate, K8); clk60 +1.12 |
| `usb_rx_status_sync` | −6.92 / −456 / 78 | −5.86 / −369 / 78 | squelch / disc filters at 480 MHz (P7) |

Typ corner: `usb_rx_datapath` −2.98, `usb_line_state` +0.84, `usb_rx_status_sync` −1.80. Area:
`usb_rx_datapath` 37.1 k → 41.2 k (the decoder8 replaces the serial FS decoder + FS elastic buffer).

### 8.7 P5 notes (HS receive on `clk60`)

- **`usb_rx_hs_sipo`** (`clk_rx` island, 53 flops + 4 on `clk_rxw`): the reset synchronizer (moved
  from the datapath), `usb_rx_hs_frontend` **unchanged** (so every recovered bit gets the same
  `{b_lvl, b_act}` as before and the A3 squelch / lock / delay settings keep their meaning), 1:8 shift
  registers, a 4-bit Johnson counter whose MSB is the word clock `clk_rxw`, a one-hot load flag
  `ld_rx` (the word register loads on E4 of `clk_rxw`, the boundary rule of 3.4 on the CDR clock) and
  the write gate on `clk_rxw`: a word is written while it has an active bit, plus one closing
  all-inactive word, so the FIFO drains between packets (no idle traffic, no pre-fill, no drift
  between packets). A lost word (FIFO full; does not happen while the reader takes a word per tick) is
  replaced by an all-inactive word, so the packet ends with an error instead of decoding a gap.
  `tb_usb_rx_hs_sipo` (new) checks the words bit for bit against the front end, the write rule, the
  replacement and the E4 rule (three mutants caught).
- **Word FIFO:** `usb_rx_elastic_buffer` with W = 16, AW = 3, ASYNC = 1, `clk_rxw` → `clk60`. Its
  write side now computes the next pointer / full flags for "write" and "no write" in parallel (the
  late `w_en` only selects); `tb_usb_rx_elastic_buffer` unchanged and passing.
- **`usb_rx_decoder8`:** `ZMIN_HS` 4..8. Stage 3 now handles two SYNCs per tick (the bit count of the
  packet left open is that behind the *last* SYNC) and up to four events (`ev0`..`ev3`, thermometer);
  `ovf` became a 0..2 count (the serial EOP check pulses once per drop). The five flag-only events
  are compacted first and the late BYTE (it depends on the data bit counts) shifts them by one slot:
  slow-corner slack +3.83 ns (P3: +2.9). Per stage (inputs registered): +6.9 / +8.0 / +3.8 ns. So
  no two stages can be merged in the unsized flow. `buf_afull` = fewer than 4 free FIFO entries,
  counting the writes in flight.
- **`usb_rx_datapath`:** one decoder for all speeds. Its input is combinational from registers: the
  word-FIFO head (HS), the DPLL's registered bit (FS/LS), or one inactive bit in the old mode in the
  tick after a speed change (ends an open packet with an error; HS words outside HS mode are
  discarded). The event FIFO has 8 entries and four write ports; the output stage shows the FIFO head
  or, while it is empty, the decoder's `ev0` directly, and `rx_*` are combinational from registers.
  The rule "a START while a packet is open waits" is gone (unreachable: the decoder ends a packet
  before the next SYNC). The FS/LS path is one tick faster than in P4. `HS_AW` is now the word FIFO
  (8 words). The serial `usb_rx_decoder` chain stays as the reference model of `tb_usb_rx_decoder8`
  and of `tb_usb_rx_hs_frontend` / unit tests.
- **SDC:** `clk_rxw` = generated clock `clk_rx` / 8 on the `clk_rxw` flop, multicycle 4 / 3 from
  `clk_rx`, in the `clk_rx` asynchronous group.
- **Results:** `tb_usb_afe_rx_if` (A3 sweep), `tb_afe_hs_chain`, `tb_usb_afe_chirp` and
  `tb_ams_link_shadow` print exactly the same output as before P5. `tb_usb_rx_datapath` receives all
  128 packets (the byte count differs: the idle-line noise draws `$random` every clock, so its
  stream depends on the RX latency). Regression: 42 testbenches pass (225 s instead of 451 s).
- **HS latency** (K12): +15–17 bit times (≈ 2 ticks) at both packet start and end, after the cuts
  above (the first version: +40–49 at the end).

STA, slow corner (unsized, as 8.2):

| Top | Before P5 (P4) | After P5 | Remaining violations |
|---|---|---|---|
| `usb_rx_datapath` | −9.40 / −1628 / 340 | −2.32 / −96 / 68 | async-reset recovery of the `clk_rx` island (−2.3, `rst_rx_n` fan-out ≈ 30 at 480 MHz) and `clk_rx` (−1.7, `ld_rx` fan-out 17): no logic in either path, buffering in P&R; `clk_bit` −0.13 (K8); `clk60` +0.58, `clk_rxw` +2.17 |
| `usb_rx_decoder8` | +2.9 (P3) | +3.83 | — |

Typ corner: `usb_rx_datapath` +0.06 (P4: −2.98), fast +0.42; `usb_rx_decoder8` typ +10.3. Area:
`usb_rx_datapath` 41.2 k → 53.0 k, 464 → 533 flops (the decoder keeps its HS logic, which P4 pruned
with `hs` = 0; word FIFO 128 and event FIFO 80 flops; the serial HS decoder and the 16-entry HS
event buffer are gone).

### 8.8 P6 notes (TX on `clk60`)

- **`usb_tx_serializer8`** (clk60): states IDLE / RUN / EOP / REL; vector of tick T = the bits the
  bit-serial serializer (ce60 on the clk60 edges) puts out after `clk_bit` edges 8T + 2 + i.
  HS: a last word with n bits carries n EOP bits into the next vector, release at that position;
  a release at bit ≥ 6 needs one more not-ready tick (REL). Underrun: an all-EOP vector (or idle
  with `eop_dis`). FS/LS: bit timer in ticks (`FS_TK` = `FS_DIV` / 8 = 5, `LS_TK` = 40; `FS_DIV` /
  `LS_DIV` must be multiples of 8), all 8 vector bits equal. `in_ready`, `busy`, `tx_speed`,
  `tx_done`, `tx_underrun` (one-tick pulses) equal the old ones tick for tick.
- **`usb_afe_tx_if8`** (clk60): the lead is a 40-bit window (this vector + 4 previous) read at
  offset `tx_lead`, one 32:1 mux per output bit; the lag dilates the delayed HS enable with the
  previous vector; `hs_tx_p` during lead / lag and the first-bit level are 8-step chains with a carry
  from the previous tick. `tx_lead` / `tx_lag` are taken over after 16 idle ticks (128 bits, window
  empty; the old block: 128 idle bits). The lead register is kept as 8 copies (`nlead_b`, own
  `(* keep *)` process, so `opt_merge` does not fold them): with one copy `lead_q[0]` had fan-out 114
  and the block failed by −8.5 ns unsized; now +1.53 ns slow.
- **`usb_tx_piso`** (clk_bit): 7 shift registers (P and N separate), loaded on `ld` = E4, bit i on the
  pin after E5 + i; the clamp moved here completely: `cq` = `drv_dis | iso_en` registered, pins
  idle from the second edge, then dropped (`kq`) until the packet's enables have fallen;
  `fq` = `cq | kq` has its own flop so every pin flop has one gate. `fs_ls` 0 under the clamp, held
  until the next FS/LS bit. **Behaviour change:** the 60 MHz side does not see the clamp, and
  `tx_active` (`act` of `usb_afe_tx_if8` sampled on `ld`, or a driven enable) stays high until the
  interrupted packet would have ended (the old block cleared it with the dropped bits).
- **Latency (K4):** pins LAT = 9 `clk_bit` cycles after the single-clock chain (data
  `tx_lead` + 12 bit times after the serial-equivalent serializer bit), +13 against the P2
  interim (the bridge was 4 bits early). Spec 4.1 updated.
- **K10 closed:** the bridge is gone; only data vectors and `act` cross clk60 → clk_bit (E4, 4 / 3
  multicycle), nothing crosses back.
- **Testbenches:** `tb_usb_tx_vec` (new): the old serializer + `usb_afe_tx_if` as reference,
  3000 packets, random speed, lead / lag (> 100 configurations), random clamp pulses (> 1000),
  FS/LS underruns; vectors bit for bit, pins cycle for cycle; seeds 1–5 pass. TBs that check the
  serial line use the TB-only `tx_vec2ser_bm` (vectors → serial `txd` / `tx_en` / `tx_se0` with the
  old timing), so their line oracles are unchanged; `tb_usb_afe_tx_if`'s pin model shifts the old
  pins by LAT and applies the PISO clamp, and reads the DUT's lead register for takeover (checked
  separately: no change within 110 bits of a packet, taken over while idle); mutants LAT = 8 and a
  PISO without `kq` are caught. AFE-level TBs and `ams_phy_end.v` moved from `SPLIT = 0` +
  `usb_afe_tx_if` to the new chain. Regression: 42 TBs pass (316 s).

STA (unsized, as 8.2):

| Top | Before P6 | After P6, slow | typ / fast | Remaining violations |
|---|---|---|---|---|
| `usb_ulpi_phy_top` | −8.37 / −484 / 137 (8.4) | −1.44 / −60 / 64 | +8.01 / +9.67 | `clk60` only: the register-read path (K9); no `clk_bit` logic left in the core |
| `usb_ulpi_tx_top` | −5.20 / −334 / 89 (8.4) | −0.89 / −1.8 / 2 | +7.95 / +9.73 | one unbuffered net, fan-out 34 (7.3 ns), sync mux → holding → bus owner; +2.24 in another mapping of the same RTL |
| `usb_afe_tx_if8` (replaces `usb_afe_tx_if`) | −3.29 / −258 / 157 | +1.53 | +9.40 / +11.16 | — |
| `usb_tx_piso` | — | −0.45 / −2.4 / 34 | +0.76 / +1.14 | K8: `fq` (2 gates) −0.45, pins with the clamp gate −0.36, every load-mux shift flop −0.03 (flop + one MUX2 does not fit 2.08 ns unsized at slow) |

Area: `usb_afe_tx_if8` 25.5 k, 205 flops (old `usb_afe_tx_if` 13.3 k, 162; 35 of the new flops are
the lead copies) + `usb_tx_piso` 5.1 k, 68 flops at 480 MHz (the old TX had ≈ 160 + the serializer at
480 MHz). K8 stays open for the PISO: decide with sized numbers whether the load-mux PISO is kept
or replaced by a mux-free structure (K8 options).

### 8.9 P7 notes (lock detector, power sequencer, pads, status sync)

- **`usb_pll_lock_det`** (clk60 + a 17-flop `clk_bit` island): the island is the 2-FF synchronizer
  of the reference-window flag, a 7-bit shift register and an 8-sample word register loaded on
  `ld`, so every island flop has at most the `ld` mux in front of it. On clk60 the word gets an
  input register (K10 rule: the E4 → E0 path has half a tick; without it the range check failed
  by −3.6 ns), the window end is the sample where the flag changes (at most one per word), and
  the count is 8 × ticks + p − p_start in `clk_bit` cycles: the same number as a bit-rate
  counter, which `tb_usb_pll_lock_det` checks for every window (mutants: no p_start, wrong carry
  bit, reversed word: all caught). **Deviation from 3.2 / 4.4:** the LSBs come from the sample
  word, not from `phase_j` of `usb_clk_gen`; an enable-captured phase needs two gates in front of
  the island flops (K8). Timeout 1023 ticks (8184 cycles, was 8191), heartbeat `clk60` / 16
  (same 128-cycle period), reset synchronizers and `lol` on clk60 (`lol_clr` is now a clk60
  pulse, which is what `usb_afe_trim_regs` on clk60 delivers). The decision comes 2–3 ticks after
  the window end instead of 3 cycles; every lock / loss time of the testbench is unchanged at its
  printed resolution (lock 72.7 / 69.6 / 77.8 / 72.7 µs; reference stop 19.4 µs, was 19.5;
  dead clock 1.36 µs, was 1.40).
- **`usb_pwr_seq`:** the core-side copies are released on the second clk60 edge and renamed
  `core_rst_n_c`, `iso_en_c`, `dir_hold_c`, `afe_en_c` (were `_b`, clk_bit); assertion stays
  asynchronous. `clk_en_b` stays a clk_bit 2-FF (`usb_clk_gen` samples it at bit rate). New
  port `clk60`. `tb_usb_pwr_seq`: lock +30 ns, core release +10 ns, DIR / RX_EN +30 ns;
  `tb_ams_pwr_shadow` lock → RUN 0.23 µs (was 0.24). `iso_en_c` also feeds the PISO clamp,
  which captures it with one clk_bit flop (a level control, like `drv_dis` since P6; the
  clk60 → `cq` path is single-cycle in reality, not the 4 / 3 multicycle: give it a false path
  or max-delay with the full SDC in P9).
- **`usb_ulpi_phy_pads`:** new input `clk_bit` and output `bit_rst_n` = `core_rst_n` through a
  2-FF synchronizer on `clk_bit` (released 2 `clk_bit` edges after the core), for the
  clk_bit-only islands (`usb_tx_piso`) when Phase 8.1 wires them. A reset released by a clk60
  flop would reach clk_bit flops after one `clk_bit` cycle (recovery not covered by the
  boundary multicycle). Mixed blocks (status sync, line state, RX datapath) keep `core_rst_n`:
  their island flops leave reset with inputs equal to their reset values. `tb_usb_ulpi_phy_pads`
  checks the release edges.
- **`usb_rx_status_sync`:** all outputs are clk60 registers. Squelch / disconnect: 2-FF on
  `clk_bit`, one value per tick on `ld` (squelch: the E4 sample; disc: OR of the 8 samples, so a
  one-cycle pulse counts), filter on clk60 in ticks. This is the island that was in
  `usb_line_state` (which keeps only the 2-flop `hs_tx_act` OR) moved one block up, so the
  status sync has 7 clk_bit flops (was 96, all on clk_bit with the filters on `ce60`). VBUS / ID: 2-FF
  and debounce on clk60. **Filter defaults change units:** `sq_flt` 2 → 1 tick (two E4 samples
  16.7 ns apart must agree), `disc_flt` 2 → 0 (a disconnect inside an EOP can be shorter than
  two ticks); set so in the AFE-level testbenches and `ams_phy_end.v`. HS LineState latency
  (squelch → `linestate`): 2 + ≤ 8 + 4 cycles + 1 + `sq_flt` ticks, 13 cycles (≈ 1.6 ticks)
  more than before with the new default (old: 2 + 3 filter cycles + ≤ 8 + 4). `tb_usb_rx_status_sync` rewritten against a tick-level reference
  (per-edge sample history), with directed one-cycle pulses at all 8 phases (disc: all shown;
  squelch: only the one on the E4 sample); four mutants caught. `tb_usb_afe_chirp`: same checks
  and packet count, absolute times after the HS part ≤ 0.1 µs later; `tb_usb_afe_fsls`,
  `tb_ams_link_shadow`: output identical.
- **Not in P7:** `usb_afe_rx_if` (its `rx_en_hs` / `cdr_en` registers, 4.3) is still
  `clk_bit` + `ce60`; it is not in the P7 list of section 6 and moves with the wiring (P8 / 8.1).

STA (unsized, as 8.2):

| Top | Before P7 | After P7, slow | typ / fast | Remaining violations |
|---|---|---|---|---|
| `usb_pll_lock_det` | −3.58 / −76 / 50 (8.2) | −0.11 / −0.87 / 8 | +0.95 / +1.26 | K8: the 8 word flops (`ld` mux, `ld` fan-out 8); clk60 +4.75 |
| `usb_rx_status_sync` | −5.86 / −369 / 78 (8.6) | −0.12 / −0.25 / 3 | +0.96 / +1.26 | K8: the disc OR accumulator; clk60 +5.33 |
| `usb_line_state` | −0.33 / −0.6 / 5 (8.6) | −0.33 / −0.38 / 2 | +0.84 / +1.17 | K8: the `hs_tx_act` OR accumulator; clk60 +4.62 |
| `usb_pwr_seq` | +0.55 | +0.55 | +1.29 / +1.50 | — (clk_bit: `clk_en_b` only; clk60 +15.1) |

Flops at 480 MHz: lock detector 57 → 17 (75 in total), status sync 96 → 7 (93), line state
5 → 2, power sequencer 9 → 2; pads + 2 (`bit_rst_n`).
