# All-in-one AFE board: PCB (EasyEDA Std)

`gen_pcb.py` writes the EasyEDA Standard PCB `usb_aio_board_pcb.json` from the same merged design as the schematic (`../gen_schematic.py`: parts, nets, functional groups; footprints from the block boards' cached **JLCEDA/EasyEDA Official Library** data, https://lceda.cn/, https://easyeda.com).

The file contains:
- the board outline;
- the mounting holes;
- all 614 footprints, placed, with every pad on its net (the ratsnest shows);
- the ZedBoard outline and the FMC area on the Document layer, for reference.

**Routing, copper pours and silkscreen tidying are not done yet.** They are the next steps in the editor, listed below.

```sh
python3 gen_pcb.py     # -> usb_aio_board_pcb.json, placement.csv
python3 check_pcb.py   # -> CHECK PASSED, preview.svg / preview.png
```

`check_pcb.py` re-reads the JSON and checks it independently of the generator:
- every netlist pin is a pad on the right net;
- J1's pins sit at the carrier positions;
- every part is on the board, clear of the holes and of other parts (through-hole parts count on both sides);
- no bottom-side part is over the carrier.

The file was also loaded into EasyEDA Std 6.5.61 (desktop) through its source API, the path *File Source → Create New Document* uses:
- **Parsed:** 614 footprints, 108 of them on the bottom, and 1985 pads, 1925 of them on nets, matching the netlist.
- **J1:** pins C1, C40, D1, G1 and H1 land at the measured coordinates.
- **DRC:** only *Incomplete Connection (1574)*, i.e. the unrouted connections (1925 netted pads − 351 multi-pin nets).

## Open it

1. In EasyEDA Std, create a new PCB.
2. Choose Design → *File Source* (the `<>` button).
3. Paste the contents of `usb_aio_board_pcb.json` and click **Create New Document**.

You can also put the PCB in a project with the schematic (`../usb_aio_board_sch.json`, opened the same way). The designators match, so *Design → Update PCB* works later.

The canvas origin is the **ZedBoard's bottom-left corner**, in mm, so the rulers read ZedBoard coordinates. The Y axis points up in this document. EasyEDA shows Y increasing downward on screen, so the rulers count down.

## Mechanics (DOC/ZedBoard_RevC.1_MechDrawing.pdf)

These positions were measured from the drawing's vector data and agree with its dimensions (35.81 / 67.31 / 98.81 mm).

| Item | ZedBoard coordinates (mm) |
|---|---|
| Carrier FMC J1, rows C / D / G / H | x = 149.25 / 150.52 / 154.33 / 155.60 |
| Pin 1 / pin 40 | y = 43.18 / 92.71 (centre 67.31) |
| Carrier standoff holes (M2.5) | (154.38, 35.81), (154.38, 98.81) |
| ZedBoard | 160.02 × 134.62, right edge x = 160.02 |
| XADC header J2 (tall, keep clear) | about x 137–153, y 106–114 |

- **J1 (ASP-134604-01)** is on the **bottom** side, with pin C1 over the carrier's C1. The stack height is 10 mm (VITA 57.1).
- **Outline, 119 × 130 mm:**
  - a strip over the carrier around J1, x 143–160.5, y 30.31–104.31;
  - the main body hanging past the ZedBoard's right edge, x 160.5–262, y 2.31–132.31.

  The standard 69 × 76.5 mm VITA outline holds about a third of the parts (6900 mm² of footprints).
- **Holes:**
  - 2 × Ø2.7 mm plated (GND) at the carrier standoffs, for M2.5 × 10 mm standoffs;
  - 4 × Ø3.2 mm plated (GND) in the body corners, for support posts.

  The board is held by the FMC connector at one end. **Support the far end**, for example with posts from the bench or a base plate that also carries the ZedBoard. Do not let J1 carry a 119 × 130 mm lever.
- **No bottom-side parts over the carrier** (x < 160.5).

## Placement

Each block gets a region. The schematic's functional groups (the boxes on the sheets) are packed as units, so a circuit stays together with its passives.

| Block | Region (mm) | Placement notes |
|---|---|---|
| CDR | x 160.5–221, y 2.3–68 | SMA row on the bottom edge |
| PLL | x 160.5–221, y 73–132.3 | SMA row on the top edge |
| TX | x 221–262, y 2.3–90 | USB-C J102 at the right edge, y = 90, opening outward |
| RX | x 221–262, y 90–132.3 | line taps next to J102 |
| common | next to J1 | FRU EEPROM, power LED |

- **Routing channel:** a band at y 68–73 (x 186–221) is kept free for the FMC signals to TX/RX.
- **Bottom side:** the 100 nF caps that connect only a supply rail and GND go there, under their group's IC (108 parts).
- **VCOs:** the two VCOs are about 70 mm apart, PLL4 top-left and CDR4 bottom-centre (see the README's *Before layout* section).
- **Coordinates:** `placement.csv` lists every part with its side, centre, rotation and group.

This is a **starting placement**: grouped, legal and DRC-clean. It is not a tuned one. Before routing, rotate and nudge the parts inside each group for short critical loops.

## Layer stack (6 layers)

| Layer | EasyEDA layer | Use |
|---|---|---|
| L1 | TopLayer | signals, components |
| L2 | Inner1 | solid **GND** |
| L3 | Inner2 | signals (LVDS from the FMC, slow controls) |
| L4 | Inner3 | power islands: +3V3_*, +5V_A_*, VADJ, 12 V |
| L5 | Inner4 | solid **GND** |
| L6 | BottomLayer | signals, decoupling caps |

The inner layers are switched on in the layer list. Check the layer count in *Layer Manager* (6) before routing.

## Next steps in the editor

1. **Copper pours.** Add GND on Inner1 and Inner4 over the whole outline, then the Inner3 power islands under each block's rails, then GND on Top/Bottom after routing.
2. **Impedance.** Take track widths from the fab's 6-layer impedance calculator (for example JLCPCB JLC06161H-7628): **100 Ω differential** for the FMC LVDS pairs and **90 Ω differential** for USB D+/D− over unbroken GND. Then set net classes. `DRCRULE` already has *Default* (0.152 mm track / clearance, 0.508 / 0.254 mm via) and *Power* (0.406 mm, on all supply rails).
3. **Route critical nets first:**
   - USB D+/D− from J102 to the ESD, the FS/LS drivers, the HS switch and the RX taps, with stubs under 2 mm;
   - CLK_RX / HS_RXD and the other FMC LVDS pairs, length-matched within 0.5 mm;
   - the two VCO tanks and the ECL nets.

   Then the supplies, then everything else.
4. **Silkscreen.** Every designator sits at its part's centre (EasyEDA regenerates the glyphs). Arrange them, or hide them on the dense passives.
5. **3D models.** These were not copied (the footprints' 3D outlines are left out). Use *Tools → Footprint Manager → Update* to restore them if needed.

## Files

| File | Content |
|---|---|
| `gen_pcb.py` | generator: outline, holes, regions, group packing, footprint transforms (rotation / bottom mirror), EasyEDA PCB JSON |
| `check_pcb.py` | independent checks plus the preview |
| `usb_aio_board_pcb.json` | EasyEDA Std PCB source (open as above) |
| `placement.csv` | ref, value, package, block, side, x, y (ZedBoard mm), rotation, group |
| `preview.svg`, `preview.png` | placement overview (top solid, bottom dashed, ZedBoard edge grey) |
