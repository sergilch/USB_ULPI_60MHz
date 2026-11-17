# USB 2.0 ULPI PHY — Description of the Verilog Modules

*Digital, PHY-side half of a USB 2.0 ULPI transceiver (HS / FS / LS), modelled on the Microchip USB3320. Target process: X-FAB xh018.*

Document date: 2026-11-17. Source: the Verilog files in the root of the `USB_60` repository and their header comments.

---

## 1. Introduction

### 1.1 What the design is

The repository contains synthesizable Verilog-2005 RTL for the **digital part of a USB 2.0 physical-layer transceiver (PHY)**. A PHY sits between a USB controller (the "Link", for example an SoC or FPGA) and the USB cable. It supports the three USB 2.0 speeds:

| Speed | Bit rate | XcvrSelect code |
|---|---|---|
| High-Speed (HS) | 480 Mbit/s | `00` |
| Full-Speed (FS) | 12 Mbit/s | `01` |
| Low-Speed (LS) | 1.5 Mbit/s | `10` |
| LS via FS preamble | sent at the FS rate | `11` |

The PHY translates between two very different worlds:

- **Link side:** the ULPI interface (UTMI+ Low Pin Interface). It has an 8-bit data bus, three control signals (DIR, NXT, STP) and a 60 MHz clock that the PHY drives. Data moves as bytes.
- **Cable side:** a serial, differential signal on the D+ / D− wires. On the wire the data is bit-stuffed, NRZI-encoded and framed by SYNC and EOP patterns.

The analog front end (AFE) — line drivers, receivers, PLL, clock/data recovery (CDR), terminations — is designed separately. This repository contains only behavioural models of the AFE, used by the testbenches.

The design follows the Microchip USB3320. Its default Vendor ID / Product ID are `0424h` / `0007h`.

### 1.2 Files covered

| Group | File pattern | Count | Purpose |
|---|---|---|---|
| RTL | `usb_*.v` | 39 | Synthesizable design. Only these files are read by synthesis. |
| Reference models | `ref_*.v` | 9 | Older bit-serial versions of blocks, kept as "golden" models for testbenches. |
| AFE models | `afe_*_bm.v` | 8 | Behavioural models of the analog front end (testbench only). |
| Helpers | `tx_vec2ser_bm.v`, `AFE/ams/ams_ulpi_phy.v`, `Tests/USB ULPI Mouse/*.v` | 4 | Testbench helpers and system-level assemblies. |
| Testbenches | `tb_*.v` | 44 | Self-checking simulations (Icarus Verilog). |

### 1.3 How to read this document

- Section 2 gives the big picture: the block hierarchy and how data flows.
- Section 3 explains the clocks, reset and common conventions. These are needed to understand almost every module.
- Section 4 describes each RTL module: what it does, where it sits, and its main interfaces.
- Section 5 describes the testbench-only models; Section 6 lists the testbenches.
- Section 7 lists what is not yet integrated or not implemented. Section 8 is a glossary.

Each Verilog file starts with a detailed header comment. That header is the authoritative specification of the module. This document summarises it in plain language.

---

## 2. Architecture overview

### 2.1 Module hierarchy

The integrated top level is `usb_ulpi_phy_pads`. It wraps the logic in I/O pad cells.

```
usb_ulpi_phy_pads            I/O pads (BBSUD8F), protection pulls, RESETB synchronizer, NAND tree
└── usb_ulpi_phy_top         ULPI side of the PHY + register files + mode/termination control
    ├── usb_mode_term_ctrl   pull-up / 45 Ohm termination / pull-down enables, OpMode framing
    ├── usb_afe_trim_regs    vendor registers 30h-3Fh: AFE trims, test, power status
    └── usb_ulpi_phy_if      complete ULPI interface
        ├── usb_ulpi_core
        │   ├── usb_ulpi_input_capture   registers the pins, decodes commands
        │   ├── usb_tx_datapath          transmit path, 60 MHz part
        │   │   ├── usb_tx_holding       4-byte FIFO, NXT pacing
        │   │   ├── usb_tx_sync_mux      SYNC + PID insertion
        │   │   └── usb_tx_path
        │   │       ├── usb_bit_stuffer
        │   │       ├── usb_nrzi_encoder
        │   │       └── usb_tx_serializer8   8 line bits per clock + EOP
        │   ├── usb_ulpi_reg_access      register read / write state machine
        │   ├── usb_ulpi_reg_file        ULPI register file
        │   ├── usb_ulpi_burst_mux       register data vs. PHY bursts
        │   └── usb_ulpi_bus_owner       DIR / NXT / DATA drivers, bus turnaround
        └── usb_ulpi_rx_path
            ├── usb_ulpi_rx_handler      RX data FIFO, RxActive / RxError
            ├── usb_ulpi_rxcmd_gen       RXCMD status bytes
            └── usb_ulpi_out_arbiter     RX data vs. RXCMD
```

The following blocks are complete and verified on their own (or through the AFE models), but are **not yet instantiated** in `usb_ulpi_phy_top`:

```
Transmit, bit-rate end    usb_afe_tx_if8 (60 MHz) -> usb_tx_piso (480 MHz) -> AFE TX pins
Receive datapath          usb_afe_rx_if, usb_rx_datapath
                            ├── usb_rx_hs_sipo (+ usb_rx_hs_frontend)
                            ├── usb_rx_elastic_buffer
                            ├── usb_rx_fsls_sampler, usb_rx_fsls_dpll
                            └── usb_rx_decoder8
Status                    usb_rx_status_sync (+ usb_rx_status_flt), usb_line_state
Clock / power             usb_clk_gen, usb_pll_lock_det, usb_pwr_seq
```

`usb_ulpi_tx_top` is an older, reduced top level (input capture, TX datapath and bus owner only).

### 2.2 Transmit data flow (Link → cable)

```
ULPI DATA/STP --> input capture --> TX holding FIFO --> SYNC/PID mux --> bit stuffer
   --> NRZI encoder --> serializer8 (+EOP) --> AFE TX interface (60 MHz)
   --> PISO 8:1 (480 MHz) --> analog HS / FS / LS drivers --> D+ / D-
```

1. The Link places a **TXCMD** byte on the bus. The PHY acknowledges it with NXT.
2. Payload bytes follow. The PHY paces them with NXT so its buffer never overflows.
3. The PHY adds the **SYNC** pattern and the **PID** byte, inserts **stuff bits** (a 0 after six 1s) and applies **NRZI** encoding.
4. The serializer produces 8 line bits per 60 MHz clock and appends the **EOP** (end-of-packet).
5. At the end, a parallel-to-serial shift register running at 480 MHz drives the analog pins.

### 2.3 Receive data flow (cable → Link)

```
HS:    CDR (clk_rx) --> HS front end + 1:8 SIPO --> word FIFO (clk_rx/8 -> clk60) --+
FS/LS: receivers --> 480 MHz sampler (40x / 320x oversampling) --> DPLL (clk60) ---+
                                                                                   |
       usb_rx_decoder8 (NRZI decode, SYNC detect, unstuff, deserialize, EOP check) <+
          --> event FIFO --> rx_start / rx_valid+rx_data / rx_end / rx_error
          --> ULPI RX path (RX FIFO, RXCMD, arbiter) --> bus owner --> ULPI DATA (DIR = 1)
```

1. **HS:** the analog CDR recovers a bit clock `clk_rx` and retimed data. A small island on `clk_rx` packs 8 bits into a word. An asynchronous FIFO moves the words into the 60 MHz core.
2. **FS / LS:** there is no analog CDR. The receiver outputs are sampled at 480 MHz (40 samples per FS bit, 320 per LS bit). A digital PLL (DPLL) picks the bit centres.
3. **One decoder** (`usb_rx_decoder8`) handles both: it removes NRZI, finds SYNC, removes stuff bits, assembles bytes and checks EOP and errors — for up to 8 bits per clock.
4. The ULPI RX path announces the packet with an **RXCMD** (RxActive = 1), then sends the data bytes to the Link with NXT = 1.

### 2.4 Control and status

- The **register file** holds the ULPI registers. Function Control (speed, termination, operating mode) drives `usb_mode_term_ctrl`, which switches the analog pull-ups, pull-downs and HS terminations.
- **Status** from the analog comparators (VBUS, ID, squelch, disconnect) is synchronized and filtered, then reported to the Link in RXCMD bytes and in the interrupt registers.
- The **power sequencer** brings up bias, PLL and clocks in order and handles suspend.

---

## 3. Clocks, reset and conventions

### 3.1 Clocks

| Clock | Frequency | Source | Used by |
|---|---|---|---|
| `clk_bit` | 480 MHz | PLL | Only small "islands": `usb_clk_gen`, `usb_tx_piso`, the FS/LS sampler, squelch / disconnect / `tx_en` captures, the lock detector's sample word, parts of the power sequencer and pad reset. |
| `clk60` | 60 MHz | `usb_clk_gen` (`clk_bit` ÷ 8) | The core clock. Almost all logic runs on it. Also the ULPI CLKOUT. |
| `clk_rx` | ≈ 480 MHz | Analog CDR (recovered from the far transmitter) | HS receive island: `usb_afe_rx_if`, `usb_rx_hs_sipo`. |
| `clk_rxw` | `clk_rx` ÷ 8 | `usb_rx_hs_sipo` | Write side of the HS word FIFO. |
| `ref_clk` | 19.2 / 24 / 26 MHz | Reference crystal | Lock-detector window, power sequencer. |

The design was migrated from a single 480 MHz clock with a 1-in-8 enable (`ce60`) to a true 60 MHz core clock (plan document `Plan_60MHz.md`, phases P1–P9). Several headers still refer to this history.

### 3.2 The 60 ↔ 480 MHz boundary rule

`usb_clk_gen` divides `clk_bit` with an 8-state Johnson counter. The `clk_bit` edge on which `clk60` rises is called **E0**; the edge four cycles later is **E4**. The divider also provides a strobe **`ld`** that makes island registers update on E4.

The rule is:

- A 480 MHz register that is read by 60 MHz logic changes only on `ld` (edge E4).
- A 480 MHz register that samples 60 MHz data samples only on `ld`.

So data always crosses half a `clk60` period away from the `clk60` edges. This gives 4 `clk_bit` cycles (8.3 ns) of setup and hold margin in both directions, and it avoids zero-delay races in simulation. The timing constraints (`constraints/usb_phy.sdc`) use multicycle paths 4 / 3 that depend on this rule. The same rule applies on the CDR clock (`clk_rx` / `clk_rxw`).

### 3.3 Reset

- All flip-flops use an **active-low asynchronous reset** (`rst_n`), released synchronously.
- `PAD_RESETB` is synchronized to `clk60` in `usb_ulpi_phy_pads` (core reset `core_rst_n`). A second synchronizer on `clk_bit` gives `bit_rst_n` for the 480 MHz islands.
- The `clk_rx` islands have their own reset synchronizer. It is split into a fast copy (`rst_rx_n`) for the few flops that can change on the first clock edge after reset, and a multicycle copy (`rst_rx_m_n`) for the rest. `tb_usb_rx_hs_reset` checks this split.

### 3.4 Other conventions

- **Line encoding:** J = 1, K = 0. Bits are sent LSB first.
- **Handshakes:** most internal streams use valid / ready. A transfer happens on a clock edge with both high.
- **Tick enable `ce`:** a few leaf modules keep a clock-enable port so their testbenches can test random gaps. In the design it is tied to 1.
- **ULPI timing model:** NXT = 1 in a clock cycle consumes the byte that the Link drives in that cycle. Inputs are registered, so internal logic sees the pins one cycle late. Several modules plan their NXT outputs with this one-cycle latency in mind.

---

## 4. RTL modules (`usb_*.v`)

Each module entry lists its purpose, position in the design, main behaviour and key interfaces or parameters.

### 4.1 Top levels and pads

#### `usb_ulpi_phy_pads` — pad wrapper (chip top)

**Purpose:** Puts the ULPI pins and the external reset on X-FAB xh018 digital I/O cells (`BBSUD8F`: bidirectional, 8 mA, Schmitt-trigger input, switchable pull-up / pull-down). All other ports of `usb_ulpi_phy_top` pass straight through, because they connect on-chip.

| Chip pin | Direction | Connects to |
|---|---|---|
| `PAD_ULPI_CLK` | out | CLKOUT from `usb_clk_gen` |
| `PAD_ULPI_DATA[7:0]` | in/out | ULPI data bus |
| `PAD_ULPI_DIR`, `PAD_ULPI_NXT` | out | Bus owner |
| `PAD_ULPI_STP` | in | Input capture |
| `PAD_RESETB` | in | Reset synchronizer |

**Main behaviour:**

- **Interface protection (ULPI 1.1 §3.12):** while Interface Control bit 7 is 0 (the reset value), STP has a weak pull-up and DATA has weak pull-downs when the PHY is not driving. A Link that leaves its outputs floating is therefore seen as STP = 1 and DATA = 00h. Writing bit 7 = 1 turns the pulls off.
- **Reset:** `PAD_RESETB` resets the core asynchronously and is released on the second `clk60` edge (`core_rst_n`). `bit_rst_n` follows two `clk_bit` cycles later for the 480 MHz islands.
- **NAND tree (test):** all 13 pad cells are chained into a NAND tree for connectivity testing; the output is `nand_tree_out`.

**Open points:** pull polarity is taken from the simulation model only; unlike the USB3320, DIR / NXT / CLK stay driven during reset.

#### `usb_ulpi_phy_top` — digital ULPI side of the PHY

**Purpose:** Connects the complete ULPI interface (`usb_ulpi_phy_if`) to the register files and to the mode / termination control. It is the main integration level.

**Main behaviour:**

- Builds **VbusState** for RXCMD from the comparators: VbusValid → `11`, SessValid → `10`, SessEnd → `00`, otherwise `01`.
- Takes the **TX speed** from XcvrSelect of the Function Control register.
- Instantiates `usb_mode_term_ctrl` (terminations, OpMode framing) and `usb_afe_trim_regs` (vendor registers 30h–3Fh).
- Exports soft reset and SuspendM as they are; the blocks that react to them are not written yet.

**Parameters:** `FS_DIV` = 40, `LS_DIV` = 320 (`clk_bit` cycles per FS / LS bit), `DIV_W` = 9, `RX_DEPTH` = 8 (RX FIFO depth).

#### `usb_ulpi_phy_if` — complete ULPI interface

**Purpose:** Groups the ULPI interface controller core (`usb_ulpi_core`) with the RX side (`usb_ulpi_rx_path`). One side is the ULPI pins; the other side is the TX line vectors, the RX datapath, the status inputs and the register file. Everything runs on `clk60`.

#### `usb_ulpi_tx_top` — older reduced top level

**Purpose:** A smaller TX-only top: input capture, TX datapath and bus owner, without register access. Kept for its end-to-end testbench `tb_usb_ulpi_tx_top`.

### 4.2 ULPI interface controller

#### `usb_ulpi_core` — ULPI interface controller core

**Purpose:** The heart of the ULPI interface. It connects the pins to the transmit path, the register access logic and the bus driver.

```
pins --> input_capture --+--> tx_datapath --> txd_v / tx_en_v / tx_se0_v
                         +--> reg_access <--> reg_file
         PHY bursts --> burst_mux --> bus_owner --> DIR, NXT, DATA (+ output enable)
```

It also implements the **ULPI holding state**: while STP is high outside a transfer (the Link is not ready), no command is accepted and DIR stays low.

#### `usb_ulpi_input_capture` — input capture and command decode

**Purpose:** Registers the ULPI inputs (DATA, STP) and decodes commands from the Link.

**Main behaviour:**

- All captured signals describe the pin values of the **previous** clock cycle.
- `lnk_valid` = the captured byte really came from the Link (DIR was low in that cycle and the one before, i.e. not a turnaround cycle).
- `nxt_seen` = NXT was high when that byte was on the bus, so the PHY consumed it.
- `stp_abort` = STP seen while the PHY owns the bus (the Link aborts a receive).
- `stp_raw` = the current, unregistered STP, so the TX path can drop NXT one cycle earlier.

**Command decode** (only while `lnk_valid` = 1):

| Byte | Meaning | Output |
|---|---|---|
| `00h` | NOOP / idle | `cmd_noop` |
| `01 00 PPPP` | Transmit (PID = PPPP, 0 = NOPID) | `cmd_tx`, `cmd_pid` |
| `10 AAAAAA` | Register write (`2Fh` = extended) | `cmd_regw`, `cmd_addr`, `cmd_ext` |
| `11 AAAAAA` | Register read (`2Fh` = extended) | `cmd_regr`, `cmd_addr`, `cmd_ext` |

#### `usb_ulpi_reg_access` — register access state machine

**Purpose:** Carries out ULPI register writes and reads, both immediate (addresses 00h–3Fh) and extended (via address 2Fh, 00h–FFh).

**Protocol:**

| Operation | Sequence |
|---|---|
| Write | RegWrite command → data byte → STP; the register is written at STP. |
| Extended write | Command AFh → address byte → data byte → STP. |
| Read | RegRead command → PHY takes the bus (turnaround) → one data byte with NXT = 0 → bus released. |
| Extended read | Command EFh → address byte → read data as above. |

**Read timing is fixed** (ULPI 1.1 Figures 22 / 30): if NXT consumes the last byte in cycle N, DIR rises in N+1, the data is on the bus in N+2 and DIR falls in N+3. The register file must therefore answer in the same cycle (combinational read).

**Coordination:** register commands are not acknowledged while a TX packet is in progress (`tx_busy`). While a register transfer runs, `link_busy` blocks TXCMD decoding. `rd_pend` holds back RXCMDs so that the read data is always the first byte after the turnaround.

#### `usb_ulpi_reg_file` — ULPI register file

**Purpose:** Stores the standard ULPI registers and provides the configuration outputs.

| Address | Register | Reset | Notes |
|---|---|---|---|
| 00h–03h | Vendor ID L/H, Product ID L/H | 24h, 04h, 07h, 00h | Read-only; set by parameters `VID_*`, `PID_*`. |
| 04h–06h | Function Control | 45h | XcvrSelect [1:0], TermSelect [2], OpMode [4:3], Reset [5] (self-clearing → `soft_reset` pulse), SuspendM [6]. |
| 07h–09h | Interface Control | 00h | Passed on as `ifc_ctrl` (bit 7 = interface protect disable). |
| 0Ah–0Ch | OTG Control | 06h | Passed on as `otg_ctrl` (includes DpPulldown / DmPulldown). |
| 0Dh–0Fh | USB Interrupt Enable Rising | 1Fh | HostDisconnect, VbusValid, SessValid, SessEnd, IdGnd. |
| 10h–12h | USB Interrupt Enable Falling | 1Fh | Same bit order. |
| 13h | USB Interrupt Status | — | Live (synchronized) status. |
| 14h | USB Interrupt Latch | 00h | Set on an enabled edge, cleared by a read. |
| 15h | Debug | — | LineState [1:0]. |
| 16h–18h | Scratch | 00h | Free read/write. |
| 30h–3Fh | Vendor-specific | — | Forwarded to `usb_afe_trim_regs`. |

Read/write registers have a **SET** alias at address +1 (`q | value`) and a **CLEAR** alias at +2 (`q & ~value`). Extended addresses 00h–3Fh mirror the immediate set; extended 40h–FFh read 00h. Status inputs go through a 2-flip-flop synchronizer. Carkit registers are not implemented.

#### `usb_ulpi_burst_mux` — burst multiplexer

**Purpose:** Merges two byte sources that the PHY sends to the Link: register read data (always a single byte with NXT = 0) and all other PHY bursts (RX data and RXCMDs).

**Rules:** register data has priority, but a PHY burst that has already started is never interrupted. While a read is pending, no new PHY burst starts. The register byte is always followed by one idle cycle, so it forms its own burst. This block is a stand-in that will later be absorbed into the output arbiter.

#### `usb_ulpi_bus_owner` — bus ownership and output registers

**Purpose:** Decides who drives the ULPI data bus and drives the DIR, NXT and DATA pins (plus the output enable).

| State | DIR | Bus |
|---|---|---|
| LINK | 0 | Driven by the Link (idle state). |
| TURN_P | 1 | Turnaround, nobody drives. |
| PHY | 1 | The PHY drives one byte per cycle. |
| TURN_L | 0 | Turnaround back to the Link. |

**Main behaviour:**

- PHY bursts arrive with valid / ready. `arb_is_data` is the NXT value for that byte (1 = RX data, 0 = RXCMD or register data).
- The PHY only takes the bus when the TX path is completely quiet, so it never interrupts a transmit or a register access. If the Link is presenting a TXCMD that was not yet acknowledged, the PHY wins and the Link repeats the TXCMD later.
- For a register read (`rd_turn`) DIR rises in the cycle right after the last NXT, as ULPI requires.
- `dir_hold` keeps DIR high without driving data (low-power mode).

#### `usb_ulpi_rx_path` — ULPI receive side

**Purpose:** Groups the three RX-side blocks of the ULPI controller and produces the burst toward the bus owner.

```
RX datapath --> rx_handler --+--> out_arbiter --> ext_* burst
status      --> rxcmd_gen ---+    (RX data has priority over RXCMD)
```

Outputs `rx_active`, `rx_err` and `overrun` for status. Parameter `DEPTH` (default 8) sets the RX FIFO size.

#### `usb_ulpi_rx_handler` — RX data handler

**Purpose:** Buffers received packet bytes and keeps the packet framing.

ULPI has no flow control on receive: at HS a byte arrives every clock, but the PHY first needs a turnaround and an RXCMD. So the bytes wait in a small FIFO.

| Input event | Effect |
|---|---|
| `rx_start` | Packet starts (SYNC found); RxActive goes high. |
| `rx_valid` / `rx_data` | One byte, written to the FIFO. |
| `rx_error` | Receive error; RxError goes high. |
| `rx_end` | Packet over (EOP found). |
| `rx_abort` | Link asserted STP while the PHY owned the bus; remaining bytes are dropped. |

Data is released to the arbiter only after an RXCMD with RxActive = 1 has actually been sent. A FIFO overflow is reported as `overrun`.

#### `usb_ulpi_rxcmd_gen` — RXCMD generator

**Purpose:** Builds the RXCMD status byte and decides when one must be sent.

| Bits | Field |
|---|---|
| [1:0] | LineState |
| [3:2] | VbusState |
| [5:4] | RxEvent: `00` idle, `01` RxActive, `11` RxActive + RxError, `10` HostDisconnect |
| [6] | ID |
| [7] | ALT_INT |

It keeps a shadow copy of the last RXCMD sent. A new RXCMD is requested when LineState, ALT_INT, RxActive or RxError changes, or when a VBUS / ID / HostDisconnect change happens in a direction enabled by the interrupt-enable registers. The comparison is against what the Link was last told, so a glitch that returns to the reported value produces no RXCMD.

#### `usb_ulpi_out_arbiter` — output arbiter

**Purpose:** Purely combinational choice of the next byte the PHY sends.

1. RX data byte (NXT = 1) — only after RxActive was announced.
2. RXCMD byte (NXT = 0) — when requested, and as a filler while a packet is active but no data is ready (this keeps DIR high for the whole packet).
3. Nothing — the burst ends and DIR falls.

### 4.3 Configuration and control registers

#### `usb_mode_term_ctrl` — mode and termination control

**Purpose:** Turns the register settings (XcvrSelect, TermSelect, OpMode, DpPulldown, DmPulldown) into the enable signals for the analog terminations, and into TX framing controls.

**Termination decode** (USB3320 Table 5-1; "host" = both pull-downs set):

| Output | Condition |
|---|---|
| All off | OpMode `01` (non-driving) |
| `dp_pulldown_en` / `dm_pulldown_en` (15 kΩ) | DpPulldown / DmPulldown |
| `hs_term_en` (45 Ω on D+ and D−) | XcvrSelect `00` and TermSelect 0 |
| `dp_pullup_en` (1.5 kΩ on D+) | Peripheral, TermSelect 1, XcvrSelect ≠ `10` |
| `dm_pullup_en` (1.5 kΩ on D−) | Peripheral, TermSelect 1, XcvrSelect `10` (LS) |

**Break-before-make:** when some enables turn off and others turn on (for example FS → HS), the ones going off switch first, and nothing turns on until `BBM_TK` (default 2) clock cycles later. So the pull-up and the HS terminations are never on together.

**Other outputs:** OpMode `10` → no bit stuffing, no NRZI, no SYNC (`cfg_bypass`, `sync_dis`) and no EOP except for a host at FS/LS (resume K); OpMode `01` → `drv_dis` (drivers off); `host_mode` for `usb_line_state`. Reset and isolation (`iso_en`) turn all enables off.

#### `usb_afe_trim_regs` — AFE trim, test and power-status registers

**Purpose:** The ULPI vendor registers 30h–3Fh. They hold trim values for the analog blocks, test controls and power status.

| Addr | Name | Contents (default) |
|---|---|---|
| 30h | TRIM_TX | TX_AMP [3:0] (8) HS driver current; HS_TERM [6:4] (4) |
| 31h | TRIM_LEAD | TX_LEAD [4:0] (10) TX_EN lead in bit times; TX_LAG [7:5] (0) |
| 32h | TRIM_RX | RX_VTH [2:0] (4); RX_HYST [5:3] (4) |
| 33h | TRIM_SQ | SQ_VTH [2:0] (4) squelch; DISC_VTH [5:3] (4) disconnect |
| 34h | TRIM_CDR | CDR_ICP [2:0] (4); CDR_BAND [4:3] (1) |
| 35h | TRIM_PLL | PLL_ICP [2:0] (4) |
| 36h | TRIM_DLY | LOCK_DLY [2:0] (2); SQ_COMP [5:3] (0) |
| 3Ch | TEST | ATB_SEL [3:0] analog test bus; ANA_LPBK [4] analog loopback |
| 3Dh | PWR_STAT | Read-only: power-sequencer state, pll_lock, pll_err, lol (write 1 to bit 6 clears lol) |
| 3Eh | TRIM_CTRL | UPDATE [0], RDACT [1], "shadow ≠ active" [7] |

**Shadow / active sets:** writes go to a shadow copy. Writing UPDATE copies all trims to the active set at once, so the analog never sees a half-changed combination. Status inputs from other clock domains are synchronized and only updated when two samples agree.

### 4.4 Transmit path

#### `usb_tx_datapath` — TX datapath (60 MHz part)

**Purpose:** Wraps the full transmit chain from the captured Link signals to the line vectors:

```
input capture -> usb_tx_holding -> usb_tx_sync_mux -> usb_tx_path -> txd_v / tx_en_v / tx_se0_v
```

**Configuration** (stable during a packet): `speed` (XcvrSelect), `bypass_en` (no stuffing, no NRZI), `sync_dis` (no SYNC), `eop_dis` (no EOP). Outputs `tx_done` and `tx_underrun` are one-cycle pulses. `nxt_n` goes to the bus owner as the NXT request.

#### `usb_tx_holding` — TX holding register and NXT pacing

**Purpose:** Accepts a TXCMD and its payload from the Link and buffers them in a **4-byte FIFO**, pacing the Link with NXT.

**Main behaviour:**

- Takes the TXCMD (PID or NOPID) once acknowledged with NXT.
- Ends the packet on STP. Because STP comes one cycle after the last byte, the newest byte is held back until the next byte or STP is known, so the "last byte" flag is always correct.
- Accounts for the one-cycle input latency: one byte is always "in flight", which is why the FIFO has 4 entries.
- Issues a header (PID, NOPID flag, "empty packet" flag) and then the payload stream to the SYNC/PID mux.

#### `usb_tx_sync_mux` — SYNC and PID insertion

**Purpose:** Builds the byte stream of one packet in front of the bit stuffer.

| Part | Content |
|---|---|
| SYNC (unless `sync_dis`) | HS: `00h 00h 00h 80h` (32 bits); FS / LS: `80h` (8 bits). NRZI later turns these into KJKJ…KK. |
| PID (unless NOPID) | `{~PID[3:0], PID[3:0]}` from the TXCMD. |
| DATA | Payload bytes unchanged. With NOPID the Link sends the PID itself. |

Marks the last byte with `out_last`. Sustains one byte per clock without gaps, which the HS serializer needs.

#### `usb_tx_path` — serial back end of the TX path

**Purpose:** Chains `usb_bit_stuffer` → `usb_nrzi_encoder` → `usb_tx_serializer8`.

- Input: packet bytes (SYNC, PID, payload) with valid / ready and `in_last`.
- Output: 8-bit line vectors per clock plus `tx_speed`.
- **Underrun handling:** if the serializer runs dry, it ends the packet with an EOP and pulses `tx_underrun`. The rest of the broken packet is then discarded so it is not sent as a second, bogus packet.
- `busy` is high from the first byte until the EOP is finished.

#### `usb_bit_stuffer` — bit stuffer

**Purpose:** Inserts a 0 after every six consecutive 1s (USB 2.0 §7.1.9), so the receiver always sees enough edges.

- The trailing 1 of SYNC counts as the first 1 of a run.
- A stuff bit is inserted even when the six 1s are the last bits of the packet.
- Each input byte expands to 8–10 bits into a 25-bit accumulator; output words carry 8 bits, except the last word (1–8 bits, `out_nbits`).
- `stuff_dis` passes the bits unchanged (OpMode `10`, chirp and test modes).
- Sustains one byte per clock; each stuffed bit costs at most one stall cycle.

#### `usb_nrzi_encoder` — NRZI encoder

**Purpose:** NRZI encoding (USB 2.0 §7.1.8): a 0 bit becomes a change of the line level, a 1 bit means no change. Each packet starts from the idle level J.

The block is a pass-through in the handshake; its only state is the current line level. `bypass_en` sends the data bits directly as line levels.

#### `usb_tx_serializer8` — serializer and EOP generator

**Purpose:** On every `clk60` edge it produces the **8 line bits** of the next clock as vectors (`txd_v`, `tx_en_v`, `tx_se0_v`, bit 0 first) and appends the EOP.

| Speed | Behaviour |
|---|---|
| HS | 8 bits per clock. EOP = 8 bits at the inverted level of the last data bit (NRZI `01111111`), spliced across two vectors if needed. No word in time → `tx_underrun` and an EOP. |
| FS / LS | One bit lasts 5 (FS) or 40 (LS) clocks; all 8 bits of a vector are equal. EOP = SE0, SE0, J. |

`eop_dis` releases the line right after the last data bit. It is bit-exact with the older bit-serial `ref_tx_serializer` (checked by `tb_usb_tx_vec`).

#### `usb_afe_tx_if8` — TX boundary to the AFE (60 MHz part)

**Purpose:** Prepares the per-pin vectors for the analog drivers, still on `clk60`.

- **Driver select** from `tx_speed`: `00` HS current driver, `01` / `11` FS, `10` LS.
- **TX_EN lead:** the HS enable rises `tx_lead` bit times before the first SYNC bit (data is delayed through a 40-bit window).
- **TX_EN lag:** the HS enable stays high `tx_lag` bits after the last bit.
- Builds `hs_tx_p`, `fs_oe`, `fs_dat`, `fs_se0`, and the LS slew-rate select.
- `act` tells the PISO that a driver is or will be active.

#### `usb_tx_piso` — 8:1 parallel-to-serial and idle clamp (480 MHz)

**Purpose:** The only bit-rate stage of the TX path. One 8-bit shift register per pin is loaded on `ld` and shifted on the other seven `clk_bit` edges.

| Pin | Meaning | Idle / reset |
|---|---|---|
| `hs_tx_p` / `hs_tx_n` | HS data (J = D+ high) and its complement (separate flops for low skew) | 1 / 0 |
| `hs_tx_en` | HS driver enable | 0 |
| `fs_oe`, `fs_dat`, `fs_se0` | FS/LS driver enable, data, SE0 | 0, 1, 0 |
| `fs_ls` | LS slew rate | 0 |

**Idle clamp:** `drv_dis` (OpMode `01`) or `iso_en` (isolation) forces all pins idle within two edges; the rest of an interrupted packet is dropped. `tx_active` reports driver activity to the receiver hold-off and the disconnect detector. The pins appear 9 `clk_bit` cycles later than in the old single-clock chain.

### 4.5 Receive path

#### `usb_afe_rx_if` — HS receive boundary to the AFE

**Purpose:** Connects the analog HS receiver, squelch detector and CDR to the digital receive path.

- **Enables:** `rx_en_hs` (HS receiver + squelch) and `cdr_en` are on only in HS mode, when reception is enabled and not isolated. Otherwise the CDR stops `clk_rx`.
- **Isolation:** `iso_en` forces the analog inputs to safe values.
- **Squelch synchronizer and lock:** `hs_cdr_lock` rises `lock_dly` bit times after squelch falls (the CDR has no lock detector of its own).
- **Latency compensation:** the data is delayed by 3 + `sq_comp` bit times, so bits received before the squelch detector released are not lost.
- Recommended settings: `lock_dly` = 2 with `HS_ZMIN` = 4; `sq_comp` = 0 unless squelch releases later than about 12 ns.

#### `usb_rx_datapath` — RX datapath

**Purpose:** The full receive path from the AFE receiver outputs to the ULPI RX handler, for all speeds (see §2.3).

**Main behaviour:**

- HS through `usb_rx_hs_sipo` and the word FIFO; FS/LS through `usb_rx_fsls_sampler` and `usb_rx_fsls_dpll`; both into one `usb_rx_decoder8`.
- An 8-entry **event FIFO** follows the decoder (it can produce up to four events per clock).
- **Mode change:** the decoder gets one inactive bit, so an open packet ends with an error and bits of two modes are never mixed.
- **Local transmitter hold-off:** while the PHY itself transmits, and for `HOLDOFF` cycles after, reception is disabled, so the PHY does not report its own packets.
- Exports the newest D+ / D− / rxrcv samples (`ls_*`) for `usb_line_state`.
- Outputs `rx_start`, `rx_valid` + `rx_data`, `rx_end`, `rx_error` (one-cycle pulses on `clk60`).

**Parameters:** `FS_DIV` = 40, `LS_DIV` = 320, `HS_ZMIN` = 6 (SYNC zeros needed at HS, 4..8), `FS_ZMIN` = 4, `HS_AW` = 3 (8-word FIFO), `HOLDOFF` = 64.

**Errors detected:** bit-stuff violation, EOP not on a byte boundary, signal lost before EOP, buffer overflow. The design tolerates ±1000 ppm at HS, the FS ±0.25 % / LS ±1.5 % clock limits, and lost SYNC bits (12-bit minimum SYNC).

#### `usb_rx_hs_frontend` — HS data capture

**Purpose:** Captures the CDR data on `clk_rx` and synchronizes the asynchronous qualifiers (`squelch`, `cdr_lock`, `enable`) with 2-flop synchronizers. It delays the data to match, so each bit gets a correct "active" flag: `b_act` = not squelch AND CDR locked AND enabled. One bit per `clk_rx` cycle; no SE0 at HS.

#### `usb_rx_hs_sipo` — HS receive island (1:8 SIPO)

**Purpose:** The only part of the HS receive path that runs at bit rate (about 50 flops on `clk_rx`).

- Contains the `clk_rx` reset synchronizer and `usb_rx_hs_frontend`.
- 1:8 shift registers for the bit level and the "active" flag.
- A Johnson counter generates the word clock `clk_rxw` = `clk_rx` / 8 (same E0 / E4 boundary rule as `usb_clk_gen`).
- **Write gate:** a word is written to the FIFO only while it contains active bits, plus one closing inactive word. So the FIFO carries no idle traffic and drains between packets. If a word does not fit, the next word is replaced by an all-inactive word, so the decoder ends the packet with an error instead of decoding a gap.

#### `usb_rx_elastic_buffer` — dual-clock FIFO

**Purpose:** A generic FIFO. In the design it is the HS word FIFO from `clk_rxw` to `clk60` (width 16 = 8 levels + 8 active flags, 8 entries).

- `ASYNC = 1`: unrelated clocks, Gray-coded pointers, 2-flop synchronizers both ways. Flags are conservative.
- `ASYNC = 0`: one clock (used only in its own testbench).
- Write while full is dropped and pulses `w_ovf`.

#### `usb_rx_fsls_sampler` — FS/LS sampler (480 MHz)

**Purpose:** The only 480 MHz part of the FS/LS receive path. Each receiver output (`rxrcv`, `rxdp`, `rxdm`) goes through a 2-flop synchronizer and a 1:8 shift register; a word register takes the 8 samples on `ld`. This gives 40 samples per FS bit and 320 per LS bit. 54 flops; every path is flop → at most one mux → flop.

#### `usb_rx_fsls_dpll` — FS/LS digital PLL

**Purpose:** Recovers FS/LS bits from the 8 samples per clock.

- Classifies each sample as SE0 (both single-ended receivers low) or J / K (from the differential receiver; FS: J = 1, LS: J = 0).
- A bit-time counter restarts on every change and strobes the bit in the middle of the bit time.
- At most one bit per clock. Bit-exact with the reference `ref_rx_fsls_frontend`.

#### `usb_rx_decoder8` — RX bit decoder (up to 8 bits per clock)

**Purpose:** The complete RX bit chain for up to 8 bits per `clk60` clock, used for HS (0–8 bits per clock) and FS/LS (0 or 1 bit).

| Stage | Function |
|---|---|
| 1 | NRZI decode and SYNC detect (a run of at least ZMIN zeros followed by a 1) |
| 2 | Bit unstuffing (remove the 0 after six 1s; seven 1s = error) |
| 3 | Deserialize 1:8 to bytes, EOP and RxError check |

Each stage computes all per-bit decisions of a clock in closed form (no bit-to-bit ripple), so it meets timing at 60 MHz. It outputs up to four events per clock (BYTE, END, START…). It is checked event for event against the serial reference `ref_rx_decoder`.

#### `usb_rx_status_sync` — receiver status synchronizer and glitch filter

**Purpose:** Synchronization point for the slow analog status outputs.

| Signal | Handling |
|---|---|
| `squelch`, `disc` (HS disconnect) | 2-flop sync on `clk_bit`, one value per clock taken on `ld` (disconnect is ORed over all 8 samples), then a glitch filter of `flt` + 1 clocks. Recommended `sq_flt` = 1, `disc_flt` = 0. |
| `a_vbus_vld`, `sess_vld`, `sess_end`, `id_gnd` | 2-flop sync on `clk60`, then a debounce of up to 2^16 clocks (≈ 1 ms). |

Reset values equal the "isolated" values, so a status that already differs at reset release produces the correct RXCMD.

#### `usb_rx_status_flt` — inertial filter

**Purpose:** Small helper used by `usb_rx_status_sync`. The output takes a new input value only after it differs on `len` + 1 consecutive enabled cycles. `len` = 0 means one cycle of delay.

#### `usb_line_state` — line state and disconnect detector

**Purpose:** Produces the ULPI **LineState** (bit 0 = D+, bit 1 = D−) and **HostDisconnect**.

| Mode | LineState source |
|---|---|
| FS / LS | Single-ended receivers `{D−, D+}` |
| HS | Squelch → `00` (SE0), otherwise `01` (J) |
| Chirp (HS, OpMode `10`) | Squelch → SE0, otherwise the differential receiver gives J or K |

**Filtering:** J / K are shown at once; SE0 / SE1 caused by D+/D− skew must persist for `SE_FS` = 2 (FS) or `SE_LS` = 14 (LS) clocks; chirp values need `CH_TK` = 2 clocks.

**HostDisconnect:** in HS host mode, the disconnect detector is ORed over each transmitted packet plus `DISC_TAIL` clocks. A detached device doubles the line amplitude, which the detector sees.

### 4.6 Clocking, PLL and power

#### `usb_clk_gen` — clock generator

**Purpose:** Derives the 60 MHz core clock, the island strobe and the ULPI CLKOUT from the 480 MHz PLL clock.

- **Divider:** a 4-bit self-correcting Johnson counter (8 states). Each phase is decoded from two adjacent bits, so the 480 MHz paths stay short.
- **`clk60`:** a dedicated flop, 50 % duty cycle, rises at E0. Runs whenever `clk_bit` runs.
- **`phase_j`, `ld`:** the phase code and the strobe for the islands (high in phase 3, so island flops update at E4).
- **CLKOUT:** gated, leads E0 by `CKO_LEAD` = 2 `clk_bit` cycles; the SDC must use the same value. It can be stopped cleanly for suspend (`clk_on` reports its state).

#### `usb_pll_lock_det` — PLL lock detector and REFSEL decode

**Purpose:** The PLL has no lock output, so lock is judged digitally by counting `clk_bit` cycles over a window of 2^NW reference cycles.

- Expected count = 480 MHz / f_ref × 2^8 (6400 / 5120 / 4726 for 19.2 / 24 / 26 MHz), tolerance ±5.
- `GOOD_N` (4) consecutive good windows → `pll_lock` = 1. One bad window → `pll_lock` = 0 and the sticky loss-of-lock flag `lol` = 1.
- Only the 3 LSBs of the count are found at 480 MHz (a 17-flop island); the rest is counted on `clk60`.
- A heartbeat check on `ref_clk` resets the detector if `clk_bit` stops completely.
- **REFSEL decode:** `00` → 19.2 MHz (feedback divider 25), `01` → 24 MHz (divider 20, default). `10` = 26 MHz needs a fractional divider and sets `refsel_err`; `11` is reserved (treated as 24 MHz, `refsel_err` = 1).

Lock is reported at most about 53 µs after the PLL settles (24 MHz); loss of lock within about 21 µs.

#### `usb_pwr_seq` — power-up and suspend sequencer

**Purpose:** Brings up the PHY in the right order and handles suspend. It runs on `ref_clk`, because `clk_bit` is not available while the PLL is off. Reset is `por_n` (not ULPI RESETB).

| State | Action |
|---|---|
| OFF | Everything off: isolation on, core in reset, DIR held. → BIAS when supplies are good. |
| BIAS | `bias_en` = 1, wait `BIAS_CYC` (10 µs). |
| PLL | `pll_en` = 1, wait for lock. Timeout `LOCK_TO` (200 µs) → `pll_err`, retry after `OFF_CYC`. |
| REL | Release core reset, isolation off, enable CLKOUT. |
| RUN | `afe_en` = 1, DIR released. Normal operation. |
| SUSPC | Suspend with clock running. |
| CSTOP | Wait for CLKOUT to stop, then turn the PLL off. |
| SUSP | PLL off. Leave on wake-up. |
| RPLL / RCLK | Re-lock the PLL, restart the clock, back to RUN. |

Loss of power (`pwr_good` or `pg18a` low) goes to OFF at once. Loss of PLL lock stops the clock and re-locks while the core keeps its state. Outputs: `bias_en`, `ldo_en`, `pll_en`, `iso_en` to the AFE; `core_rst_n_c`, `iso_en_c`, `dir_hold_c`, `afe_en_c` to the core; `clk_en_b` to the clock generator; state and `pll_err` for status.

---

## 5. Testbench-only models

These files are **not synthesizable** and are never read by synthesis.

### 5.1 Reference models (`ref_*.v`)

The older, bit-serial (one bit per `clk_bit` cycle) versions of blocks that the 60 MHz design replaced. They serve as golden references: the testbenches check the new blocks against them cycle by cycle or event by event.

| File | Models | Used as reference by |
|---|---|---|
| `ref_tx_serializer.v` | Bit-serial TX serializer + EOP | `tb_usb_tx_vec`, `tb_ref_tx_serializer` |
| `ref_afe_tx_if.v` | Bit-serial TX boundary to the AFE (incl. clamp) | `tb_usb_tx_vec` |
| `ref_rx_decoder.v` | Complete serial RX bit chain (wraps the five blocks below) | `tb_usb_rx_decoder8` |
| `ref_rx_nrzi_decoder.v` | NRZI decoder | `tb_ref_rx_nrzi_decoder` |
| `ref_rx_sync_detect.v` | SYNC detector | `tb_ref_rx_sync_detect` |
| `ref_rx_bit_unstuffer.v` | Bit unstuffer | `tb_ref_rx_bit_unstuffer` |
| `ref_rx_deserializer.v` | Deserializer 1:8 | `tb_ref_rx_deserializer` |
| `ref_rx_eop_check.v` | EOP detect and RxError check | `tb_ref_rx_eop_check` |
| `ref_rx_fsls_frontend.v` | FS/LS synchronizer + DPLL | `tb_usb_rx_fsls_frontend` |

### 5.2 AFE behavioural models (`afe_*_bm.v`)

Real-valued, event-driven models of the analog front end. They share an electrical convention: each block that drives or loads a wire exports a Norton equivalent (conductance and current) per wire, and `afe_line_bm` resolves the wire voltage.

| File | Models |
|---|---|
| `afe_line_bm.v` | The D+ / D− wires (resolves voltages from all drivers and loads) |
| `afe_term_bm.v` | Switchable terminations: 1.5 kΩ pull-ups, 45 Ω HS terminations, 15 kΩ pull-downs |
| `afe_hs_tx_bm.v` | HS current-mode transmitter |
| `afe_hs_rx_bm.v` | HS differential receiver (Schmitt trigger) |
| `afe_squelch_bm.v` | HS squelch and disconnect detectors |
| `afe_cdr_bm.v` | PLL-assisted bang-bang CDR (recovered clock `clk_rx` and data) |
| `afe_fsls_bm.v` | FS / LS transceiver (drivers and receivers) |
| `afe_pll_bm.v` | PLL lower loop (frequency only) producing `clk_bit` |

The same pins and defaults exist as Verilog-A models in `AFE/veriloga/` for Spectre AMS simulation.

### 5.3 Helpers and system assemblies

| File | Purpose |
|---|---|
| `tx_vec2ser_bm.v` | Turns the 60 MHz TX line vectors back into serial `txd` / `tx_en` / `tx_se0` with the old bit-serial timing, so line checkers keep their cycle numbers. |
| `AFE/ams/ams_ulpi_phy.v` | A complete PHY (ULPI pins ↔ AFE pins) for system testbenches; used by the LS mouse enumeration tests. |
| `Tests/USB ULPI Mouse/ulpi_tb_template.v` | ULPI Link bus-functional model (BFM) template for building testbenches. |
| `Tests/USB ULPI Mouse/ls_mouse_bm.v` | Icarus port of the Verilog-A low-speed HID mouse `usb_ls_mouse.v` (kept in sync). |

---

## 6. Testbenches (`tb_*.v`)

All testbenches are self-checking. The build command is in each file's header; `./run_tests.sh` runs them all. The result is the last `TEST PASSED` / `TEST FAILED` line of the output.

### 6.1 ULPI interface and registers

| Testbench | Checks |
|---|---|
| `tb_usb_ulpi_input_capture` | Pin alignment, bus-ownership qualification, command decode |
| `tb_usb_ulpi_bus_owner` | DIR / NXT / DATA protocol seen from the pins, turnaround, burst handling |
| `tb_usb_ulpi_reg_file` | Reset values, SET / CLEAR aliases, read-only registers, interrupt latch, against a shadow model |
| `tb_usb_ulpi_core` | End-to-end: a ULPI Link model runs transmits and register accesses; the packet is rebuilt from the line |
| `tb_usb_ulpi_phy_if` | RX side: packets and status changes → RXCMDs and RX data at the pins |
| `tb_usb_ulpi_phy_pads` | Register read / write through the BBSUD8F pads, protection pulls (needs `X-FAB/`) |
| `tb_usb_ulpi_tx_top` | End-to-end test of the older TX-only top |
| `tb_usb_afe_trim_regs` | Vendor register map, shadow / active update, status |
| `tb_usb_mode_term_ctrl` | Every row of USB3320 Table 5-1, break-before-make |

### 6.2 Transmit path

| Testbench | Checks |
|---|---|
| `tb_usb_tx_holding` | FIFO, NXT pacing, STP handling with a pin-level Link model |
| `tb_usb_tx_sync_mux` | SYNC / PID / data stream for all speeds and NOPID, with back-pressure |
| `tb_usb_bit_stuffer` | Against a reference stuffer and an independent de-stuffer |
| `tb_usb_nrzi_encoder` | NRZI encoding with random gaps and back-pressure |
| `tb_usb_tx_path` | Full serial back end, packets rebuilt from the line |
| `tb_usb_tx_vec` | 60 MHz TX chain vs. bit-serial reference, cycle for cycle |
| `tb_usb_afe_tx_if` | TX boundary through the AFE models |
| `tb_ref_tx_serializer` | The reference serializer itself |

### 6.3 Receive path

| Testbench | Checks |
|---|---|
| `tb_usb_rx_hs_frontend` | HS capture and synchronizer alignment |
| `tb_usb_rx_hs_sipo` | HS island words, write gate, FIFO-full handling |
| `tb_usb_rx_hs_reset` | Split reset release of the `clk_rx` islands |
| `tb_usb_rx_elastic_buffer` | Async and sync FIFO with random writers / readers |
| `tb_usb_rx_fsls_frontend` | FS/LS sampler + DPLL vs. reference |
| `tb_usb_rx_decoder8` | Parallel decoder vs. serial reference, event for event |
| `tb_usb_rx_datapath` | Loopback: a far-end TX path with its own clock and ppm offset into the RX datapath |
| `tb_usb_rx_status_sync` | Status synchronization and filtering |
| `tb_usb_line_state` | LineState encoding, filtering, HostDisconnect window |
| `tb_ref_rx_*` (5 files) | The serial reference blocks |

### 6.4 Clocking, power and AFE / system tests

| Testbench | Checks |
|---|---|
| `tb_usb_clk_gen` | Divider phases, `clk60`, `ld`, CLKOUT |
| `tb_usb_pll_lock_det` | Lock / loss of lock with the PLL model, reference stop |
| `tb_usb_pwr_seq` | Power-up, suspend, failure sequences |
| `tb_usb_afe_rx_if` | HS receive boundary with squelch and CDR models, ±1000 ppm |
| `tb_usb_afe_fsls` | FS / LS loopback and LineState through the AFE models |
| `tb_usb_afe_chirp` | Attach, reset, HS chirp handshake, HS traffic, disconnect, suspend / resume |
| `tb_afe_line`, `tb_afe_hs_rx`, `tb_afe_cdr`, `tb_afe_hs_chain` | The AFE models themselves |
| `tb_ams_link_shadow`, `tb_ams_pwr_shadow`, `tb_ams_mouse_shadow` | Icarus versions of the Spectre AMS tests; `tb_ams_mouse_shadow` enumerates an LS HID mouse over ULPI |

---

## 7. Integration status and open items

**Verified standalone but not yet wired into `usb_ulpi_phy_top`:** the RX datapath, `usb_afe_tx_if8` + `usb_tx_piso`, `usb_afe_rx_if`, `usb_clk_gen`, `usb_pll_lock_det`, `usb_rx_status_sync`, `usb_line_state`, `usb_pwr_seq`. A complete system assembly exists only as a testbench (`AFE/ams/ams_ulpi_phy.v`).

**Not implemented:**

- OpMode `11`
- Soft reset reaction (the Reset bit is only exported)
- SuspendM / low-power mode (including combinational LineState on DATA[1:0])
- LS via FS preamble
- OTG / VBUS control
- Carkit registers

**Known open points** (from module headers): pad pull polarity confirmed only from the simulation model; DIR / NXT / CLK not tri-stated during reset; several trim widths and defaults are proposals awaiting the analog team.

---

## 8. Glossary

| Term | Meaning |
|---|---|
| AFE | Analog front end: drivers, receivers, PLL, CDR, terminations |
| CDR | Clock and data recovery: recovers the bit clock from the received HS signal |
| Chirp | HS handshake signalling (K / J chirps) during bus reset |
| DPLL | Digital phase-locked loop: digital bit-timing recovery for FS / LS |
| EOP | End of packet. HS: 8 bits of inverted NRZI level; FS/LS: SE0, SE0, J |
| J / K | The two differential line states (FS: J = D+ high) |
| Link | The USB controller on the other side of ULPI |
| NRZI | Non-return-to-zero inverted: 0 = level change, 1 = no change |
| PID | Packet identifier (4 bits + 4 check bits) |
| PISO / SIPO | Parallel-in serial-out / serial-in parallel-out shift register |
| RXCMD | Status byte that the PHY sends to the Link (NXT = 0) |
| SE0 / SE1 | Both D+ and D− low / high |
| Squelch | Detector that indicates no valid HS signal on the line |
| SYNC | Start-of-packet pattern (KJKJ…KK) |
| TXCMD | Command byte from the Link to the PHY (transmit, register access) |
| ULPI | UTMI+ Low Pin Interface: 12-pin PHY–Link interface at 60 MHz |
| XcvrSelect | Function Control field selecting the speed (HS / FS / LS) |
