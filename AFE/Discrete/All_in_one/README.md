# Discrete USB 2.0 AFE, all-in-one board (TX + RX + PLL + CDR)

This is one FMC LPC mezzanine that carries the four discrete prototype boards of `AFE/Discrete` as blocks. It has **one USB Type-C receptacle**, shared by the transmitter and the receiver. The blocks and their designators:

| Block | Source (parts + netlist) | Sheets | Designators |
|---|---|---|---|
| common | FMC connector, FRU EEPROM, power LED (taken from TX) | 0 | J1, U1, C1, D1, R1 |
| TX: HS current-steering driver, discrete FS/LS driver, terminations / pulls, ESD, **USB-C** | `../Transmitter/easyeda/gen_schematic.py` | TX1–TX4 | 1xx (R7 → R107) |
| RX: line taps, HS receiver, squelch / disconnect, threshold DAC | `../Receiver/easyeda/gen_schematic.py` | RX1–RX4 | 2xx |
| PLL: ADF4002, loop filter, BFR93A VCO, CDCM1804 | `../PLL/easyeda/pll_parts.py` | PLL1–PLL4 | 3xx |
| CDR: Alexander PD, prop driver, VCO, NB6L14 | `../CDR/easyeda/cdr_parts.py` | CDR1–CDR4 | 4xx |

`easyeda/gen_schematic.py` imports the parts and connectivity straight from the four block generators, so the block boards stay the single source. It then applies the integration listed below. Every removed part is checked against its MPN, and every text fix must still match, so a later change in a block board makes the generator fail instead of producing a silently wrong merge. A block net keeps its name when only one block uses it. Otherwise it gets the block tag: `+3V3` becomes `+3V3_TX` / `+3V3_RX` / `+3V3_PLL` / `+3V3_CDR`, and `VBIAS` becomes `RX_VBIAS` / `PLL_VBIAS` / `CDR_VBIAS`. Each block keeps its own rails, ferrite beads and LDOs. In particular, the two 480 MHz VCOs (PLL, CDR) keep separate `+5V_A_*` LDOs, so they do not pull each other through a shared supply.

## Integration

**USB line (one USB-C).** J102 (TX3) with ESD U112, HS termination switch U111 (40.2 Ω + Ron), the 1.5 k pull-up and the 15 k pull-downs is the only USB port. The RX taps Q201 / Q202 (BFT92 emitter followers, 22 Ω base stoppers) are on the same `DP` / `DM` nets. Removed from RX: the USB-B / USB-A through line (J2, J3), its ESD U6, the second termination switch U8 + R13 / R14, the VBUS detector, and the HS_TERM_EN path. The single termination is switched by the TX `HS_TERM_EN_F`.

**HS receive path RX → CDR.** The SN65LVDS100 (U207) no longer drives the FPGA directly. It drives a new NB6L14 fan-out U216 (LVDS input, VT open = 100 Ω internal), with two outputs used:
- Q0 → `RX_OUT` to the FPGA (LVPECL, 150 Ω pull-downs, AC-coupled, biased to `RX_VBIAS` 1.245 V, FPGA DIFF_TERM, 220 k offset: idle reads J). This is the same scheme as the CDR board's CLK_RX / HS_RXD outputs.
- Q1 → `RX_CDR_P/N` → CDR MC100EP57 U406 input **D2**, which was unused before. The input is terminated with 100 Ω, AC-coupled and biased to VBB2 with an offset, a copy of the D1 network. `DSEL1:DSEL0 = 10` selects it. D0 (SMA) and D1 (FPGA pattern) are unchanged.

This gives an on-board loop: TX driver → line → RX taps → CDR → `HS_RXD` / `CLK_RX`. For HS the line needs its far-end termination: either the host on the cable, or the DNP host-load resistors R134 / R135.

**Coarse tuning PLL → CDR.** `CDR_CH_OUT_PLL` (PLL buffer U314, R324) now goes on board through the CDR's 1 k R482 to the coarse-source switch U414 (`CSW_EXT`). This link used to be SMA J4 → SMA J6. CDR J6 is removed, and PLL J304 stays as a monitor / injection point.

**Shared FMC resources.** There is one FMC connector, one FRU EEPROM and one power LED. All DACs and ADCs share one SPI SCK / SDI pair from the FPGA (`SPI_SCK_F`, `SPI_SDI_F`) into the TX U102, PLL U304 and CDR U403 translators. Each device keeps its own CS#. Each ADC keeps its own DOUT, because the LVC1T45 outputs always drive. The RX translator U2 is removed: the RX DAC (U215) shares SCK / SDI with the TX DAC behind U102 (`SPI3V3_*`), and its CS# uses U102's spare channel A7 / B7.

**FMC LPC pin map.** `easyeda/fmc_pinmap.csv` lists every pin with its pin on the old board and its ZedBoard package pin, bank, clock-capable function and I/O standard:

| Signals | Pins |
|---|---|
| **CLK_RX (CDR)** | CLK0_M2C H4/H5 (as on the CDR board) |
| CLK60_A (PLL) | CLK1_M2C G2/G3 (as before) |
| HS_RXD, DPAT (CDR) | LA00_CC G6/G7, LA01_CC D8/D9 (as before) |
| **CLK_BIT_A (PLL)** | **LA17_CC D20/D21** (was CLK0_M2C, which the CDR's CLK_RX needs) |
| TX_IN_P / TX_IN_N (TX) | LA02 H7/H8, LA03 G9/G10 (as before) |
| RX_OUT (RX) | LA04 H10/H11 |
| TX slow / FS signals, RXRCV/RXDP/RXDM, VBUS_DET, TX DAC CS# | LA05–LA12_P |
| SPI_SCK_F, SPI_SDI_F, RX DAC CS# | LA12_N, LA13 |
| SQUELCH_A, DISC_A, RX_EN | LA14, LA15_P |
| PLL: REF_DIG / MUXOUT | LA18_CC C22/C23 |
| PLL: ADF bus, controls, DAC/ADC | LA16, LA19–LA25_P |
| CDR controls, DAC/ADC | LA26–LA30 |
| free (8 of 72) | LA15_N, LA25_N, LA31–LA33 |

The combined FPGA design in `fpga/` uses this table (see *FPGA design* below). The four single-board designs (`../*/fpga`) keep their own boards' pin maps.

## Carrier: Digilent ZedBoard Rev D.2 (XC7Z020CLG484-2)

Sources: `DOC/zedboard_sch.pdf` (sheets 2, 9, 15), `DOC/fpga_package_pin_to_fmc.pdf`, `DOC/ds187-XC7Z010-XC7Z020-Data-Sheet.pdf`.

- **Pins.** All 34 LA pairs and CLK0/CLK1_M2C are connected, 72 I/O in total; this board uses 64. LA00–LA16 and CLK0 go to bank 34, LA17–LA33 and CLK1 to bank 35. Both are HR banks at VADJ. Clock-capable pins: bank 34 CLK0 (MRCC), LA00 (MRCC), LA01 (SRCC), LA14 (SRCC); bank 35 CLK1 (MRCC), LA17 (MRCC), LA18 (SRCC), LA29 (SRCC).
- **Bank rule.** BUFIO and BUFR only clock the ISERDES of their own bank. So CLK_RX and HS_RXD share bank 34 (CDR capture), and RX_OUT, SQUELCH_A and DISC_A share bank 34 (RX sampler, with its MMCM in that bank's clock region). The generator checks both rules, and checks that CLK_RX, CLK_BIT_A, CLK60_A and REF_DIG are on clock-capable pins. CLK_BIT_A, CLK60_A and REF_DIG only feed BUFGs, so bank 35 works for them. The TX and DPAT OSERDES run on a 240 MHz BUFG and can go in any bank.
- **VADJ = 2.5 V** (jumper J18; the 3.3 V position is not fitted by default). LVDS_25 outputs (TX_IN, DPAT) require VCCO = 2.5 V (DS187 table 13), and so does DIFF_TERM on the LVDS inputs (UG471).
- **Speed** (DS187, -2 column): DDR LVDS with OSERDES / ISERDES 1250 Mb/s (-1: 950), BUFG 628 MHz (-1: 464), BUFIO 680 MHz, BUFR 375 MHz output (input up to the BUFIO limit), MMCM VCO 600–1440 MHz, IDELAY step 1/(64 F_REF) = 78 ps at 200 MHz. The block designs need TX 480 Mb/s (DDR, 240 MHz BUFG), RX 2 × 960 Mb/s (480 MHz BUFIO), PLL 480 MHz on a BUFG, CDR 480 MHz BUFIO, and an MMCM VCO of 960 / 1200 MHz. **All of these fit the -2 grade; the RX sampler and the PLL's 480 MHz BUFG would not fit a -1 part.**
- **No GTP transceivers.** The XC7Z020 has none (DS187: GTP only on XC7Z012S / XC7Z015), so FMC DP0 and GBTCLK0 are not connected. Every I/O pin still has its ISERDESE2 / OSERDESE2 / IDELAYE2, which is what the designs use. GTPs would not help anyway: their minimum line rate is 0.5 Gb/s.
- **Other FMC pins.** 12P0V comes from the board's 12 V input, which feeds the PLL and CDR TPS7A4901. 3P3VAUX is the board's VCC3V3. GA1 is grounded and GA0 is not connected, so the FRU EEPROM's A0 pin floats: check that the AT24C02C reads a floating address pin as low, or fit a pull-down on FMC_GA0. With PRSNT_M2C_L low, the ZedBoard routes JTAG through the mezzanine, so the TDI→TDO link (D30–D31) is required, and it is fitted. SCL / SDA go to bank 13 with 4.7 k pull-ups to 3.3 V. Banks 34 / 35 also carry ZedBoard buttons, switches and XADC header signals, but none on the FMC pins.

## FPGA design (`fpga/`, ZedBoard)

`fpga/rtl/aio_fpga_top.v` runs the four block designs side by side. Each `aio_*_blk.v` is the body of its board's `*_fpga_top.v` without the clocking, and uses the same modules (`tx_ctrl` … `cdr_rxchk`, plus the repo's `usb_*` RTL), the same register map and the same host script. The merge adds:

- **Clocking.** One MMCM (VCO 1200 MHz from GCLK Y9 through a BUFG) generates:
  - 480 MHz for the RX sampler (BUFIO, plus BUFR /4);
  - 240 MHz for the TX and DPAT OSERDESE2;
  - 200 MHz for one IDELAYCTRL;
  - 60 MHz for the system clock.

  CLK_RX goes to BUFIO / BUFR in bank 34, and the PLL board clocks go to BUFGs in bank 35, 8 BUFGs in all. The MMCM must sit in bank 34's clock region, and Vivado places it there because it drives that bank's BUFIO.
- **One UART.** The ZedBoard's USB-UART is wired to the PS (MIO48/49), so the PL uses a **PmodUSBUART on JA** (JA2 = FPGA TXD, JA3 = FPGA RXD). **SW1:SW0** select the block: 00 TX, 01 RX, 10 PLL, 11 CDR. The selection changes only after the switches and both UART lines have been quiet for 1.1 ms, so it never cuts a byte. Each block's register 00h returns its letter (T / R / P / C). All blocks run at 921600 baud (the TX board's default was 115200), so `rx_host.py`, `pll_host.py` and `cdr_host.py` work unchanged once the switches are set. LD7:LD6 show the selection.
- **Shared SPI.** The board has one SPI_SCK / SPI_SDI pair for six CS# lines. `aio_spi_arb` passes a grant token between the four SPI engines, so two frames never overlap. To support this, `tx_ctrl`, `rx_ctrl`, `pll_ctrl` and `cdr_ctrl` gained an input `spi_gnt`, which the single-board tops tie to 1 (their testbenches still pass). A DAC write can wait up to one ADC frame (10 µs).
- **CDR input D2.** DSEL = CTRL[2] ? 01 (FPGA pattern) : CTRL[6] ? 10 (RX loop) : 00 (SMA). On the CDR board, CTRL[6] was only the LED bit. Use `cdr_host.py PORT set --dsrc rx` to select D2.
- **RX block.** STATUS[4] reads the TX block's VBUS_DET. RX CTRL[1] (HS_TERM_EN) has no pin; the single termination is controlled by TX TERM[1].
- **LEDs.**

  | LED | Shows |
  |---|---|
  | LD0 | MMCM locked |
  | LD1 | TX active |
  | LD2 | RX squelch / armed |
  | LD3 | PLL lock |
  | LD4 | CDR CLK_RX alive |
  | LD5 | CDR packets OK |
  | LD7:LD6 | UART selection |

  BTNC resets everything.

`fpga/constraints/aio_zedboard.xdc` is generated by `fpga/gen_xdc.py` from `easyeda/fmc_pinmap.csv`. The port name is the board net in lower case without `_F`. The generator fails if a mapped net has no port or a port has no pin. The XDC sets:
- LVDS_25 with DIFF_TERM on the clock and HS_RXD inputs (RX_OUT gets DIFF_TERM in the RTL);
- LVCMOS25 for the FMC single-ended pins;
- LVCMOS33 for the GCLK, LED and Pmod pins;
- clocks, the usb_clk_gen multicycles, asynchronous clock groups and I/O false paths.

**Resources.** Yosys `synth_xilinx` reports about 5.3k LUT6-equivalents, 3.1k FFs, 8 RAMB36 (the RX capture), 8 OSERDESE2, 5 ISERDESE2, 3 IDELAYE2, 1 MMCM, 8 BUFG, 2 BUFIO and 2 BUFR. The XC7Z020 has 53k LUTs, 140 RAMB36 and 4 MMCMs. Vivado place and route and timing have **not** been run here.

The design is PL-only (no PS7 instance). Load the bitstream over JTAG; setting the boot-mode jumpers to JTAG is the simplest way. J18 must be set to 2.5 V.

## Before layout

- The two VCOs (PLL4, CDR4) run at the same frequency. Place them far apart, each with its own ground stitching / shield can, so they do not injection-lock.
- The RX taps and the TX receivers (1 k isolation) all load `DP` / `DM`. Keep the tap stubs as short as on the RX board, and re-check the HS eye with the combined load.
- 3P3V now feeds four blocks (the CDR ECL alone is about 0.45 A by its board notes). Check the sum against the carrier's 3.3 V budget (the ZedBoard feeds FMC 3P3V from its VCC3V3 regulator, sheet 15).
- NB6L14 U216: Q2 / Q3 are open (unused LVPECL outputs). VT and VREF_AC are open for the LVDS input.

## Files

| File | Content |
|---|---|
| `easyeda/gen_schematic.py` | Generator: integration tables (`REMOVE`, `FMC`, `LINK`, `EDIT`, `ADD`, `TEXT_FIX`) plus the drawing engine of the block boards |
| `easyeda/usb_aio_board_sch.json` | EasyEDA Std project source, 17 sheets |
| `easyeda/netlist.csv` | ref, pin, pin name, net, sheet, block |
| `easyeda/fmc_pinmap.csv` | merged FMC pin map, old pins, ZedBoard package pins / banks / I/O standards, free pins, dropped FMC signals |
| `bom/aio_board_bom.csv`, `bom/aio_board_bom_jlcpcb.csv` | BOM (with a Blocks column) and JLCPCB assembly BOM |
| `fpga/rtl/` | `aio_fpga_top.v` (ZedBoard top), `aio_tx_blk.v` / `aio_rx_blk.v` / `aio_pll_blk.v` / `aio_cdr_blk.v` (block bodies), `aio_glue.v` (UART select, SPI arbiter) |
| `fpga/gen_xdc.py`, `fpga/constraints/aio_zedboard.xdc` | XDC generator and the generated ZedBoard constraints |
| `fpga/build_vivado.tcl`, `fpga/synth_check.ys` | Vivado non-project build (xc7z020clg484-2), Yosys xc7 smoke synthesis |
| `fpga/sim/` | Icarus integration test (`run_sim.sh`, `tb_aio_fpga_top.v`, `prims_sim.v`) |

```sh
cd easyeda && python3 gen_schematic.py     # -> sheets 17, parts 614, ..., errors 0
cd fpga && python3 gen_xdc.py                # -> constraints/aio_zedboard.xdc (after a pin map change)
cd fpga/sim && ./run_sim.sh                  # -> TEST PASSED (about 20 s)
cd fpga && yosys -q -s synth_check.ys        # xc7 smoke synthesis (about 1 min)
cd fpga && vivado -mode batch -source build_vivado.tcl
```

`tb_aio_fpga_top.v` checks what the merge adds:
- all SPI frames after reset arrive intact while every engine wants the bus, with never two CS# low and no SCK edge outside a frame (the same test without the arbiter fails);
- the UART select (IDs T / R / P / C, LEDs);
- TX HS packets → line → RX capture (SQUELCH_A trigger) and → CDR over D2 (RXPKT);
- the CDR DPAT loop (RXOK);
- PLL lock and FCNT;
- the PLL and CDR ADC read-back and DAC writes;
- the TX DAC.

The block designs keep their own detailed testbenches.

The only single-pin net is `FS_SUSPND_F`, an FMC spare that was already unused on the TX board.

To open the schematic in EasyEDA Std:

1. Open a new schematic.
2. Choose Design → *File Source* (the `<>` toolbar button).
3. Paste the contents of `easyeda/usb_aio_board_sch.json` and click **Create New Document**.

Schematic symbols and footprints: **JLCEDA/EasyEDA Official Library** (https://lceda.cn/, https://easyeda.com), read from the block boards' `easyeda/lib/` caches. The copyright of the library data belongs to JLCEDA/EasyEDA, and every schematic sheet carries this note.
