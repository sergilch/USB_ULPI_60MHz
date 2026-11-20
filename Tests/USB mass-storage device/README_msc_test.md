# Mass-storage enumeration test over ULPI (`tb_ams_msc`)

*Created 2026-11-20. Status: the Icarus shadow `tb_ams_msc_shadow` passes (109 checks, 0 errors, 0.95 ms simulated, about 50 s). The Spectre AMS top `AFE/ams/tb_ams_msc.vams` passes the static netlist check. It has not been run, because there is no AMS simulator on the development machine.*

Block diagram: [`tb_ams_msc_block_diagram.drawio`](tb_ams_msc_block_diagram.drawio). It has two pages: *Block diagram* and *Test sequence*. Open it in draw.io / diagrams.net. ADE XL file list: [`ams_msc_file_list.txt`](ams_msc_file_list.txt).

## Purpose

This is a system test of the complete digital PHY with the Verilog-A AFE models. A USB host enumerates a **full-speed mass-storage device** and runs Bulk-Only-Transport SCSI commands. The host is a ULPI Link model plus a host sequence. The device is the Verilog-A model `usb_fs_msc.va`. All traffic goes over the ULPI interface. Every packet makes the full round trip:

```
Link --TX CMD/data--> ULPI core --> TX datapath (stuff, NRZI, serialize) --> usb_afe_tx_if8 / usb_tx_piso
     --> afe_transceiver --> DP/DM --> usb_fs_msc
usb_fs_msc --> DP/DM --> afe_transceiver (FS receivers) --> usb_afe_rx_if --> usb_rx_datapath
     (FS sampler, DPLL, decoder8) --> RX FIFO / RXCMD --> ULPI --> Link
```

The setup is the same as the mouse test (`tb_ams_mouse`, low speed), with the device and the host sequence changed. This test covers the **full-speed** paths: 12 Mbit/s TX timing, the FS receive DPLL, and 64-byte packets. It also covers bulk transfers with DATA0/DATA1 toggling and multi-packet data stages (512 bytes = 8 packets).

## Structure

| Instance | Module / file | Domain | Role |
|---|---|---|---|
| — | `tb_ams_msc` (`AFE/ams/tb_ams_msc.vams`) | Verilog-AMS | Top: 480 MHz `clk_bit`, `por_n`, `resetb`, supplies, nets |
| `u_link` | `ulpi_link_bfm` (`Tests/USB ULPI Mouse/ulpi_tb_template.v`, `` `include``d) | digital | ULPI Link: register access, TX CMD + packet transmit, RX monitor (RXCMD / USB data) |
| — | `AFE/ams/ams_msc_seq.vh` (`` `include``d inside the top) | digital | Host sequence, USB host tasks (tokens, CRC5/CRC16, control and bulk transfers, BOT), all checks, verdict |
| `u_phy` | `ams_ulpi_phy` (`AFE/ams/ams_ulpi_phy.v` + 35 `usb_*.v`) | digital RTL | The PHY from the ULPI pins to the AFE pins: `usb_ulpi_phy_top`, TX `usb_afe_tx_if8` + `usb_tx_piso`, RX `usb_afe_rx_if` + `usb_rx_datapath`, `usb_line_state`, `usb_rx_status_sync`, `usb_clk_gen` (60 MHz CLKOUT), reset synchronizers |
| `H_XCVR` | `afe_transceiver.va` | Verilog-A | FS/LS driver and receivers, HS driver, 45 Ω terminations, 15 kΩ pull-downs |
| `H_RX` | `afe_receiver.va` | Verilog-A | HS receiver, squelch, disconnect (enabled only during the bus reset) |
| `H_CDR` | `afe_cdr.va` | Verilog-A | CDR (`clk_rx`, `hs_rxd`) |
| `V33`, `V18`, `V18A`, `VREF`, `VCO` | `ams_vdc` (`AFE/ams/lib/ams_prims.va`) | Verilog-A | 3.3 V, 1.8 V, 1.8 V, 1.2 V, 0.9 V |
| `u_msc` | `usb_fs_msc` (`Tests/USB mass-storage device/usb_fs_msc.va`) | Verilog-A | Device: 1.5 kΩ D+ pull-up after 20 µs, 8× oversampling receiver, transmitter, EP0 / EP1 OUT / EP2 IN, SCSI |
| (inserted) | `usb_l2e` / `usb_e2l` (`AFE/ams/lib/usb_connect.vams`, rules `usb_cr`) | connect | Logic ↔ electrical at every PHY–AFE pin: 0 / 1.8 V, thresholds 0.8 / 1.0 V |

The sequence reads the line voltages through `` `AMS_VDP`` / `` `AMS_VDM``. In AMS these are `$cds_get_analog_value("tb_ams_msc.dp" / ".dm")`. In the shadow they are the real buses of `afe_line_bm`.

### Icarus shadow

`tb_ams_msc_shadow.v` (repository root) has the same `ams_ulpi_phy` and the same `ams_msc_seq.vh`. It replaces the Verilog-A parts as follows:
- **AFE:** the `afe_*_bm.v` models on one `afe_line_bm`.
- **Device:** `fs_msc_bm.v`, the event-driven port of `usb_fs_msc.va`. Its engine was copied from the Verilog-A file by text substitution only. Keep the two files in sync.

`./run_tests.sh msc_shadow` runs the shadow. If a test fails only in Spectre AMS, the cause is in the Verilog-A models, the connect rules or the netlist, not in the RTL or the sequence.

## Test sequence

| # | Step | What is checked |
|---|---|---|
| 1 | Power-up, RESETB, 200 ULPI clocks | Vendor ID 0424h, Product ID 0007h, scratch register write/read |
| 2 | Host mode: OTG Control 66h, Function Control 45h (FS) | LineState SE0 before attach; LineState J (01) after the device's pull-up, stable after a 10 µs debounce; line DP 2.7–3.4 V, DM < 0.3 V |
| 3 | Bus reset: Function Control 50h (45 Ω terminations on) for 10 µs, then 45h | SE0 on the line (DP ≈ 0.1 V); the device reports the reset; LineState J and the line J again after recovery |
| 4 | GET_DESCRIPTOR(device, 8) at address 0 | SETUP ACK, data CRC16, DATA1 toggle, status ACK; bMaxPacketSize0 = 64 |
| 5 | SET_ADDRESS(7) | IN status ZLP (DATA1); the device takes address 7 |
| 6 | GET_DESCRIPTOR(device, 18) | bcdUSB 1.10, VID 1234h, PID 5680h, one configuration |
| 7 | GET_DESCRIPTOR(configuration, 9 then 32) | wTotalLength 32; two endpoints; class 08h / subclass 06h / protocol 50h; EP 01h OUT bulk and 82h IN bulk, 64 B |
| 8 | SET_CONFIGURATION(1), GET_MAX_LUN | Max LUN = 0 |
| 9 | BOT: TEST UNIT READY | CBW on EP1 OUT (31 B), CSW on EP2 IN (13 B): "USBS", tag, residue 0, status 0 |
| 10 | BOT: INQUIRY (36 B) | Data stage length, direct-access device, removable medium, "ACME", "VA", "1.00"; CSW |
| 11 | BOT: READ CAPACITY(10) | Last LBA 0000FFFFh, block length 512; CSW |
| 12 | BOT: READ(10), LBA 0, one block | 8 × 64-byte packets (CRC16 and toggle of each one), bytes 0–509 = n, 55 AAh at 510/511; CSW |
| 13 | Verdict | Sequence errors + Link BFM errors = 0 → `TEST PASSED` |

A SOF goes out before each control transfer and each BOT command. The times are scaled against USB 2.0 so the analog run stays short: debounce, reset, reset recovery and SET_ADDRESS recovery are 10 µs each. The device model detects a reset after 2.5 µs of SE0 and does not model suspend. The watchdog stops the run with `TEST FAILED: timeout` after 20 ms.

## Differences from the template `tb_usb3300_fs_msc_enum.vams`

- The DUT is this repository's PHY (`ams_ulpi_phy` + AFE models), not a USB3300 model. Product ID 0007h (USB3320) is checked instead of 0004h.
- **Bus reset:** the template used OpMode 10 + NOPID zero bytes. This test turns on the 45 Ω HS terminations instead (Function Control 50h), the way the USB3320 does it and the same as the mouse test. SE0 is checked on the line.
- There are extra checks: line levels, CSW residue, INQUIRY byte 1 and revision, and all 510 pattern bytes of READ(10).
- The result line uses the repository format `TEST PASSED` / `TEST FAILED: …`.
- `ulpi_defs.vh` is not needed: the constants are in `ulpi_tb_template.v`.

## Link model change: TX CMD retry

At full speed, the PHY ends every received packet with two RX CMDs. The first has RxActive = 0, sent during the SE0 of the EOP. The second reports LineState J at the end of the EOP. ULPI 1.1 §3.8.2 lets the Link start the next packet as soon as it sees the first one. The PHY then asserts `dir` for the second RX CMD in the cycle the Link drives its TX CMD. ULPI allows this: it is a TX CMD aborted by the PHY, and the Link must retry when the bus is idle (§3.8.3).

The template's `ulpi_link_bfm` counted such an abort as an error. `link_cmd_phase` now retries the TX CMD byte of every transfer, up to `CMD_RETRIES` = 16 times in a row, and counts it in `cmd_retry_cnt`. It is not an error. Aborts during the payload bytes are still errors. The MSC test sees 37 retries per run; the mouse test (low speed) sees none.

## Observation about the PHY (not fixed)

The PHY sends LineState RX CMDs while its own FS packet is still on the line, after the Link's STP: 31 079 RX CMDs in this test. ULPI 1.1 §3.8.2.2 says that all RX CMD changes during a USB transmit should be replaced by one RX CMD at the end of the transmit. `usb_ulpi_bus_owner` only holds the bus while `usb_tx_holding` is busy. The Link model ignores these RX CMDs, so the test passes. A real Link controller might not.

## Running

```sh
./run_tests.sh msc_shadow                 # Icarus shadow (~50 s)
python3 AFE/ams/check_ams_netlist.py      # static check of the AMS netlist
AFE/ams/run_ams_tests.sh msc              # Spectre AMS (needs xrun)
```

For Cadence ADE XL, see `ams_msc_file_list.txt`.
