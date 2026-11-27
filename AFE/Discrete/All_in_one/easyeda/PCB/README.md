# All-in-one AFE board: PCB (EasyEDA Std)

`gen_pcb.py` writes the EasyEDA Standard PCB `usb_aio_board_pcb.json` from the same merged design as the schematic (`../gen_schematic.py`: parts, nets, functional groups; footprints from the block boards' cached **JLCEDA/EasyEDA Official Library** data, https://lceda.cn/, https://easyeda.com).

The file contains:
- the board outline;
- the mounting holes;
- all 614 footprints, placed, with every pad on its net (the ratsnest shows);
- the ZedBoard outline and the FMC area on the Document layer, for reference.

**The board is routed by script**, except for a remainder listed in `route_rest_report.txt`:
- `route_critical.py` does the critical nets (see *Critical routing* below);
- `route_rest.py` does the rest: fine-pitch fanout, RF / ECL nets, GND stitching vias, the other signals, the supply rails, and the GND planes (see *Routing the rest* below).

The unrouted remainder, the pour fill check and the silkscreen tidying are left for the editor.

```sh
python3 gen_pcb.py          # -> usb_aio_board_pcb.json (placed, unrouted), placement.csv
python3 route_critical.py   # -> usb_aio_board_pcb.json (critical nets routed), route_report.txt
python3 route_rest.py       # -> usb_aio_board_pcb.json (rest routed, GND planes), route_rest_report.txt
python3 check_pcb.py        # -> CHECK PASSED, preview.svg / preview.png
```

Each step rewrites the JSON, and each later one keeps the earlier one's copper, so run them in this order. `gen_pcb.py` drops all routing. `route_rest.py` takes about 1 h.

`check_pcb.py` re-reads the JSON and checks it independently of the generator:
- every netlist pin is a pad on the right net;
- J1's pins sit at the carrier positions;
- every part is on the board, clear of the holes and of other parts (through-hole parts count on both sides);
- no bottom-side part is over the carrier;
- every routed track / via is on a net and at least 0.152 mm from copper of other nets on its layer and from unplated holes. This uses exact geometry, with oval pads as capsules.

The file was also loaded into EasyEDA Std 6.5.61 (desktop) through its source API, the path *File Source → Create New Document* uses:
- **Parsed:** 614 footprints, 108 of them on the bottom, and 1985 pads, 1925 of them on nets, matching the netlist.
- **J1:** pins C1, C40, D1, G1 and H1 land at the measured coordinates.
- **DRC (unrouted):** only *Incomplete Connection (1574)*, i.e. the unrouted connections (1925 netted pads − 351 multi-pin nets).
- **DRC (critical nets routed):** only *Incomplete Connection (1510)*. That is 64 fewer, the connections of the 20 routed nets; there are no clearance, via or track errors.

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
| TX | x 221–262, y 2.3–88.4 | |
| RX | x 221–262, y 91.6–132.3 | |
| USB corridor | y 87.8–92.2, x 233.6–262 | J102 at the right edge (y = 90, opening outward), ESD U112, then every D+/D− tap on its line, then U111 at the west end; the taps' groups are packed next to it |
| common | next to J1 | FRU EEPROM, power LED |

- **Routing channel:** a band at y 68–73 (x 186–221) is kept free for the FMC signals to TX/RX.
- **Bottom side:** the 100 nF caps that connect only a supply rail and GND go there, under their group's IC (108 parts).
- **Fanout ring:** fine-pitch parts (pitch ≤ 0.7 mm: QFN, TSSOP, MSOP, SC-70) are packed with a free 0.7 mm ring around them, and their bottom decaps stay out of it, so the pins can escape (`RING`).
- **VCOs:** the two VCOs are about 70 mm apart, PLL4 top-left and CDR4 bottom-centre (see the README's *Before layout* section).
- **Pair blocks:** a P/N pair of equal two-pin parts, such as the AC-coupling caps of an LVDS pair, is packed as one block with P directly above N. Partners are found by the mirrored net (`…_P…` ↔ `…_N…`). The pair's lines then end side by side, which removes most of the skew before tuning.
- **Near J1:** groups on an FMC LVDS pair are packed as close to that pair's J1 pins as they fit, like the USB tap groups at their corridor.
- **Spill:** the CDR group *Tuning: V_A trim (DAC A)* no longer fits the CDR region. It sits just across the CDR/TX boundary, at x 222–243, y 4–11. It is a slow DAC path, but check its loop to the CDR VCO.
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

## Critical routing (`route_critical.py`)

| Nets | Layer | Geometry |
|---|---|---|
| USB D+ / D− (90 Ω diff) | Top over L2 GND | Two 0.41 mm (~45 Ω) lines at y = 90.95 / 89.05 from J102 through U112 to U111. Every tap (R134/135, D106/107, C118/119, R209/210, R155/156, R129/130, R131) sits on its line with a stub under 1 mm. J102 A6/B6 and A7/B7 and the D+/D− swap at U111 are finished with short stubs and vias. |
| FMC LVDS pairs CLK_RX, HS_RXD, DPAT, CLK60_A, CLK_BIT_A, TX_IN_P, TX_IN_N, RX_OUT; on-board RX_CDR (100 Ω diff) | Inner2 (L3), stripline | Coupled, w 0.16 / s 0.22 mm. On Top/Bottom only if Inner2 is full: w 0.20 / s 0.17 mm. Each pair runs from a launch point next to J1 (or U216) to its receiver group. J1 breakouts use 0.16 mm stubs with dog-bone vias; the other pads hang on the far end of the pair. |

**Vias:** 0.508 / 0.254 mm, the DRC rule default. `route_report.txt` lists the layer each pair took.

**Skew tuning:** after routing, the script measures each pair's copper length from the source pin to its matched end. The ends are the series AC caps, or U105 / U106 for TX_IN, so the shunt bias and termination branches don't count.
- Before measuring, it trims track ends that touch nothing back to the last joint.
- It adds rectangular bumps (pitch 0.6 mm, height 0.15–2.5 mm) to the shorter line on a free stretch of its path, until |P − N| ≤ 0.25 mm.

Current result (`route_report.txt`):

| Pair | Ends | Length | Skew untuned → tuned |
|---|---|---|---|
| CLK_RX | J1 → C440 / C441 | 16.0 mm | −1.97 → 0.00 mm |
| HS_RXD | J1 → C442 / C443 | 16.7 mm | −2.38 → 0.00 mm |
| DPAT | J1 → C421 / C422 | 11.8 mm | −0.76 → 0.00 mm |
| CLK60_A | J1 → C365 / C366 | 46.2 mm | −1.36 → 0.00 mm |
| CLK_BIT_A | J1 → C363 / C364 | 21.3 mm | +0.92 → 0.00 mm |
| TX_IN_P | J1 → U105 | 76.1 mm | −3.29 → 0.00 mm |
| TX_IN_N | J1 → U106 | 71.9 mm | −2.20 → 0.00 mm |
| RX_OUT | J1 → C237 / C238 | 91.8 mm | +0.74 → +0.01 mm |
| RX_CDR | U216 → C474 / C475 | 105.5 mm | −0.82 → 0.00 mm |

These are intra-pair lengths only. Skew between pairs (for example CLK_RX vs HS_RXD) is the FPGA IDELAY's job.

**Widths are estimates.** They assume a JLC06161H-7628-class stack: 0.21 mm prepreg L1–L2, εr ≈ 4.4, about 0.3 mm to each plane around L3. **Before ordering, take the final widths from the fab's impedance calculator** and re-run with the new values (`LVDS_W*`, `LVDS_S*`, `USB_W` at the top of the script).

**Still open:**
- **Plane reference:** L3 references L2 GND and L4 power. Keep the L4 islands solid under the pairs, or move the islands.

**Verification:**
- `check_pcb.py` reports CHECK PASSED with 0 clearance violations.
- In EasyEDA Std 6.5.61, DRC lists only *Incomplete Connection*. The count is 64 lower than in the unrouted file: exactly the connections of the 20 routed nets.

## Routing the rest (`route_rest.py`)

The script keeps the critical nets' copper and routes everything else. The module docstring has the details.

| Step | What | Where |
|---|---|---|
| 0. Fanout | Fine-pitch parts (pitch ≤ 0.7 mm) get a keep-out zone (pads + 1 mm) and one escape lane per pin. Each pin gets a **dog-bone**: a 0.16 mm neck to a 0.508 mm via at the lane end. Every other lane is 0.7 mm longer, so the vias stagger. A via that doesn't fit slides outward or sideways; pins with no room get a plain stub. | Top + via |
| 1. RF / ECL | Nets with a pad in a VCO, VCO-buffer, ECL (MC100EP*, NB6L14, CDCM1804) or prop-driver group, shortest first, so they get the direct paths | Top (preferred) / Inner2 / Bottom, 0.16 mm |
| 2. GND | One stitching via per SMD GND pad, to the planes on Inner1 / Inner4: vias in the pad on exposed pads, else a 0.25 mm stub to a via within 3.5 mm | 0.508 mm vias |
| 3. Signals | All other signal nets, shortest first | Top / Inner2 / Bottom, 0.16 mm |
| 4. Rails | The 17 supply nets | Inner3, 0.41 mm (0.254 mm where needed), 0.61 / 0.305 mm vias |
| 5. Retry | Each incomplete net once more on the whole board, with one extra layer | |
| 6. Planes | GND copper areas on Inner1 and Inner4 over the whole board, 0.3 mm clearance | |

**Router rules:**
- **Zones and lanes.** A net that doesn't touch a fine-pitch part keeps its Top tracks and vias out of that part's zone. The part's own nets may use the zone only along their own lanes. Lanes of other nets are closed to tracks and vias everywhere.
- **Exact check.** Track maps use a 0.08 mm grid margin, via maps 0.13 mm. Every path is checked with exact geometry against pads, unplated holes and all routed copper. A path that fails is searched again on a 0.13 mm grid. If that fails too, the pad is left unrouted, never laid too close.

**Current result** (`route_rest_report.txt`, about 1 h):

| | Nets | Incomplete after its stage |
|---|---|---|
| RF / ECL | 104 | 20 |
| Other signals | 214 | 44 |
| Rails | 17 | 9 |
| After the retry | | **58 nets** (+ 11 GND pads without a via) |

- 2232 new tracks and 1541 new vias.
- **Unrouted:** 106 pads, listed in the report. Most are on the dense fine-pitch ICs of the CDR / PLL blocks: U411, U408, U316 (6 each), U311, U304 (5), U216 (4). There are also 9 rail nets with one or two pads open each (+3V3_\*, +5V_A_\*, VADJ, P3V3_FMC, VBUS).

**Verification:**
- `check_pcb.py`: CHECK PASSED, 0 clearance violations on 14 562 track segments / via layers.
- EasyEDA Std 6.5.61, after *Rebuild All Copper Area* (Shift+B) fills both planes: DRC lists only **Incomplete Connection (112)**. That is the unrouted remainder above, counted per connection.
- No clearance, track-width or via errors.

## Next steps in the editor

1. **Finish the remainder** in `route_rest_report.txt`: 58 nets and 11 GND pads. Most need room around U411 / U408 / U316 / U311 / U304 / U216, so nudge the neighbouring passives first. Re-running the scripts after a placement change in `gen_pcb.py` re-routes everything.
2. **Impedance.** Take track widths from the fab's 6-layer impedance calculator (for example JLCPCB JLC06161H-7628): **100 Ω differential** for the FMC LVDS pairs and **90 Ω differential** for USB D+/D− over unbroken GND. Then set net classes. `DRCRULE` has:
   - *Default*: 0.152 mm track / clearance, 0.508 / 0.254 mm via.
   - *Power*: the rail nets. The minimums are the same as Default, because fine-pitch supply pins have 0.16 mm necks; the rails themselves run 0.41 mm.
3. **Check the planes.** L3 signals reference L2 GND and L4 power. Keep the Inner3 rail tracks away from under the LVDS pairs where possible, or pour the power islands solid.
4. **Silkscreen.** Every designator sits at its part's centre (EasyEDA regenerates the glyphs). Arrange them, or hide them on the dense passives.
5. **3D models.** These were not copied (the footprints' 3D outlines are left out). Use *Tools → Footprint Manager → Update* to restore them if needed.

## Files

| File | Content |
|---|---|
| `gen_pcb.py` | generator: outline, holes, regions, group packing, footprint transforms (rotation / bottom mirror), EasyEDA PCB JSON |
| `route_critical.py` | first-pass router for the critical nets (A* on a 0.1 mm grid; Top / Inner2 / Bottom, vias, coupled pairs), dangling-end trim and intra-pair skew tuning |
| `route_report.txt` | per pair: routed or not, the layer of the coupled section, P / N lengths and skew |
| `route_rest.py` | router for everything else: fine-pitch fanout (zones, lanes, dog-bones), RF / ECL nets, GND stitching vias, signals, Inner3 rails, retry, GND planes |
| `route_rest_report.txt` | per stage: nets and incomplete count; every unrouted pad |
| `check_pcb.py` | independent checks (placement + routed-copper clearance) plus the preview |
| `usb_aio_board_pcb.json` | EasyEDA Std PCB source (open as above) |
| `placement.csv` | ref, value, package, block, side, x, y (ZedBoard mm), rotation, group |
| `preview.svg`, `preview.png` | placement and routing overview (top solid, bottom dashed, ZedBoard edge grey; tracks Top red, Inner2 green, Inner3 orange, Bottom blue) |
