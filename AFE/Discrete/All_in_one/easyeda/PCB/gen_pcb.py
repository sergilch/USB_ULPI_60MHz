#!/usr/bin/env python3
"""gen_pcb.py - EasyEDA Standard (6.5.x) PCB of the all-in-one AFE board.

Reads the merged design of ../gen_schematic.py (parts, nets, functional groups,
footprints from the cached JLCEDA/EasyEDA Official Library, https://lceda.cn/,
https://easyeda.com) and writes usb_aio_board_pcb.json: board outline, mounting
holes, every footprint placed with its pads on their nets (ratsnest), and the
ZedBoard Rev D outline / FMC position on the Document layer for reference.
Routing, copper pours and silkscreen tidying are left to the EasyEDA editor.

Geometry is in ZedBoard coordinates (mm, origin = ZedBoard bottom-left corner,
Y up; DOC/ZedBoard_RevC.1_MechDrawing.pdf, measured from the vector data):
  FMC J1 (carrier) rows C / D / G / H at x = 149.25 / 150.52 / 154.33 / 155.60,
  pin 1 at y = 43.18, pin 40 at y = 92.71 (centre 67.31); standoff holes at
  (154.38, 35.81) and (154.38, 98.81); ZedBoard edge x = 160.02, height 134.62.
The mezzanine's J1 (ASP-134604-01) is on its BOTTOM side, pin C1 over the
carrier's C1.  Outline: a strip over the carrier around J1 (x 143..160.5,
y 30.31..104.31) and the main body off the ZedBoard edge (x 160.5..262,
y 2.31..132.31).  No bottom-side parts over the carrier.

  python3 gen_pcb.py            -> usb_aio_board_pcb.json, placement.csv, preview.svg
"""
import contextlib
import csv
import io
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(HERE))
import gen_schematic as G  # noqa: E402

MM = 1 / 0.254              # EasyEDA unit = 10 mil
OX, OY = 4000.0, 3600.0     # EasyEDA coordinates of the ZedBoard origin


def E(x, y):
    """ZedBoard mm -> EasyEDA units (Y down)."""
    return OX + x * MM, OY - y * MM


def f3(v):
    return ("%.4f" % v).rstrip("0").rstrip(".")


_gid = [0]


def gid():
    _gid[0] += 1
    return "gge%d" % _gid[0]


# --------------------------------------------------------------------------- board
ZED_W, ZED_H = 160.02, 134.62
J1_C1 = (149.25, 43.18)
STANDOFFS = [(154.38, 35.81), (154.38, 98.81)]           # carrier M2.5 standoffs
STRIP = (143.0, 160.5, 30.31, 104.31)                     # over the carrier
BODY = (160.5, 262.0, 2.31, 132.31)                       # off the ZedBoard edge
SUPPORTS = [(165.0, 6.81), (165.0, 127.81), (257.5, 6.81), (257.5, 127.81)]
OUTLINE = [(STRIP[0], STRIP[2]), (BODY[0], STRIP[2]), (BODY[0], BODY[2]), (BODY[1], BODY[2]),
           (BODY[1], BODY[3]), (BODY[0], BODY[3]), (BODY[0], STRIP[3]), (STRIP[0], STRIP[3])]
EDGE = 0.6                  # parts keep this far from the outline
HOLE_KEEP = {2.7: 3.3, 3.2: 3.6}   # hole diameter -> keep-out radius (standoff / washer)

# block regions (x0, x1, y0, y1) in the body; band y 68..73 = FMC routing channel
REGIONS = {
    "CDR": (160.5, 221.0, 2.31, 68.0),
    "PLL": (160.5, 221.0, 73.0, 132.31),
    "TX": (221.0, 262.0, 2.31, 90.0),
    "RX": (221.0, 262.0, 90.0, 132.31),
    "common": (160.5, 180.0, 63.0, 78.0),
}
# corner the rows start from: (y side, x side); rows grow away from it
START = {"CDR": ("bottom", "left"), "PLL": ("top", "left"), "TX": ("top", "right"),
         "RX": ("bottom", "right"), "common": ("bottom", "left")}
GAP_PART, GAP_GROUP = 0.5, 1.4
RAIL = re.compile(r"^(\+|P3V3|P12V|12P0V|VADJ|P5V)")


def inside(r, box, m=0.0):
    return r[0] >= box[0] + m and r[1] <= box[1] - m and r[2] >= box[2] + m and r[3] <= box[3] - m


def on_board(r):
    return inside(r, (STRIP[0], BODY[0] + 1e-6, STRIP[2], STRIP[3]), EDGE) or \
        inside(r, BODY, EDGE) or \
        (r[0] >= STRIP[0] + EDGE and r[1] <= BODY[1] - EDGE and r[2] >= STRIP[2] + EDGE and
         r[3] <= STRIP[3] - EDGE)


def overlap(a, b, g=0.0):
    return a[0] < b[1] + g and b[0] < a[1] + g and a[2] < b[3] + g and b[2] < a[3] + g


# --------------------------------------------------------------------------- design
def design():
    with contextlib.redirect_stdout(io.StringIO()):
        err = G.merge()
    if err:
        raise SystemExit("gen_schematic.merge(): %d errors" % len(err))
    fp = {}
    for ref, p in G.PARTS.items():
        r = G.load(p["sym"])
        pd = r.get("packageDetail")
        if not pd:
            raise SystemExit("no footprint for %s (%s)" % (ref, p["sym"]))
        fp[ref] = pd
    return fp


# --------------------------------------------------------------------------- transforms
class Xf:
    """footprint-local (EasyEDA units, origin = footprint origin, Y down) -> board."""

    def __init__(self, ox, oy, rot=0, mirror=False, mat=None):
        self.ox, self.oy, self.rot, self.mirror = ox, oy, rot % 360, mirror
        if mat is None:
            c, s = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[self.rot]
            m = -1 if mirror else 1
            mat = (c * m, -s, s * m, c)          # rotate(rot) . scale(m, 1)
        self.a, self.b, self.c, self.d = mat
        self.det = self.a * self.d - self.b * self.c

    def p(self, x, y):
        return self.ox + self.a * x + self.b * y, self.oy + self.c * x + self.d * y

    def angle(self, ang):
        """pad / text rotation (degrees, clockwise on screen)."""
        base = math.degrees(math.atan2(self.c, self.a))
        a = (-ang if self.det < 0 else ang) + base
        return int(round(a)) % 360


BOTTOM_LAYER = {"1": "2", "3": "4", "5": "6", "7": "8", "13": "14"}
DROP_BOTTOM = {"99", "100", "101"}


def lay(l, bottom):
    if not bottom:
        return l
    return BOTTOM_LAYER.get(l, l)


def pts(s, xf, ox, oy):
    v = [float(t) for t in s.split()]
    out = []
    for i in range(0, len(v) - 1, 2):
        out += xf.p(v[i] - ox, v[i + 1] - oy)
    return " ".join(f3(t) for t in out)


def path(d, xf, ox, oy):
    tok = re.findall(r"[MLAZmlaz]|-?\d*\.?\d+(?:e-?\d+)?", d)
    out, i, cmd = [], 0, None
    while i < len(tok):
        t = tok[i]
        if t.isalpha():
            cmd = t.upper()
            out.append(cmd)
            i += 1
            continue
        if cmd in ("M", "L"):
            x, y = xf.p(float(tok[i]) - ox, float(tok[i + 1]) - oy)
            out += [f3(x), f3(y)]
            i += 2
        elif cmd == "A":
            rx, ry, xr, la, sw = tok[i:i + 5]
            x, y = xf.p(float(tok[i + 5]) - ox, float(tok[i + 6]) - oy)
            if xf.det < 0:
                sw = "0" if sw == "1" else "1"
            out += [rx, ry, xr, la, sw, f3(x), f3(y)]
            i += 7
        else:
            raise ValueError("path command %s in %r" % (cmd, d[:80]))
    return " ".join(out)


def place_shapes(ds, xf, bottom, nets):
    """footprint dataStr shapes -> board shapes (strings), pads on their nets."""
    ox, oy = float(ds["head"]["x"]), float(ds["head"]["y"])
    out, padnums = [], []
    for s in ds["shape"]:
        f = s.split("~")
        k = f[0]
        if k == "SVGNODE":
            continue                                    # 3D outline: not transformed
        if k == "PAD":
            f[6] = lay(f[6], bottom)
            x, y = xf.p(float(f[2]) - ox, float(f[3]) - oy)
            f[2], f[3] = f3(x), f3(y)
            f[7] = nets.get(f[8], "")
            if f[10].strip():
                f[10] = pts(f[10], xf, ox, oy)
            f[11] = str(xf.angle(float(f[11] or 0)))
            f[12] = gid()
            if len(f) > 14 and f[14].strip():
                f[14] = pts(f[14], xf, ox, oy)
            if len(f) > 19 and "," in f[19]:
                hx, hy = (float(t) for t in f[19].split(","))
                hx, hy = xf.p(hx - ox, hy - oy)
                f[19] = "%s,%s" % (f3(hx), f3(hy))
            padnums.append(f[8])
        elif k == "TRACK":
            if bottom and f[2] in DROP_BOTTOM:
                continue
            f[2] = lay(f[2], bottom)
            f[4] = pts(f[4], xf, ox, oy)
            f[5] = gid()
        elif k == "CIRCLE":
            if bottom and f[5] in DROP_BOTTOM:
                continue
            f[5] = lay(f[5], bottom)
            x, y = xf.p(float(f[1]) - ox, float(f[2]) - oy)
            f[1], f[2] = f3(x), f3(y)
            f[6] = gid()
        elif k == "ARC":
            if bottom and f[2] in DROP_BOTTOM:
                continue
            f[2] = lay(f[2], bottom)
            f[4] = path(f[4], xf, ox, oy)
            f[5] = ""
            f[6] = gid()
        elif k == "SOLIDREGION":
            if bottom and f[1] in DROP_BOTTOM:
                continue
            f[1] = lay(f[1], bottom)
            f[3] = path(f[3], xf, ox, oy)
            f[5] = gid()
        elif k == "RECT":                                # unfilled rectangle -> track
            if bottom and f[5] in DROP_BOTTOM:
                continue
            x, y, w, h = (float(t) for t in f[1:5])
            c = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
            p = " ".join("%g %g" % q for q in c)
            f = ["TRACK", f[8] or "1", lay(f[5], bottom), "", pts(p, xf, ox, oy), gid(), "0"]
        elif k == "HOLE":
            x, y = xf.p(float(f[1]) - ox, float(f[2]) - oy)
            f[1], f[2] = f3(x), f3(y)
            f[4] = gid()
        else:
            raise ValueError("unhandled footprint shape " + k)
        out.append("~".join(f))
    return out, padnums


def local_bbox(ds):
    bb = ds["BBox"]
    ox, oy = float(ds["head"]["x"]), float(ds["head"]["y"])
    return bb["x"] - ox, bb["y"] - oy, bb["x"] + bb["width"] - ox, bb["y"] + bb["height"] - oy


def size_mm(ds, rot):
    x0, y0, x1, y1 = local_bbox(ds)
    w, h = (x1 - x0) / MM, (y1 - y0) / MM
    return (h, w) if rot in (90, 270) else (w, h)


def board_rect(ds, xf):
    """footprint bbox on the board, ZedBoard mm (x0, x1, y0, y1)."""
    x0, y0, x1, y1 = local_bbox(ds)
    c = [xf.p(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    xs = [(p[0] - OX) / MM for p in c]
    ys = [(OY - p[1]) / MM for p in c]
    return min(xs), max(xs), min(ys), max(ys)


def xf_at(ds, rot, mirror, x0, y0):
    """transform that puts the footprint bbox's lower-left (ZedBoard mm) at x0, y0."""
    r = board_rect(ds, Xf(OX, OY, rot, mirror))      # footprint origin at ZedBoard (0, 0)
    ex, ey = E(x0 - r[0], y0 - r[2])
    return Xf(ex, ey, rot, mirror)


# --------------------------------------------------------------------------- packing
def shelf(items, width, gap):
    """items [(key, w, h)] -> {key: (x, y)} rows from y = 0 upwards, width limit."""
    pos, x, y, row = {}, 0.0, 0.0, 0.0
    for k, w, h in items:
        if x > 0 and x + w > width:
            x, y, row = 0.0, y + row + gap, 0.0
        pos[k] = (x, y)
        x += w + gap
        row = max(row, h)
    W = max((pos[k][0] + w for k, w, h in items), default=0)
    H = max((pos[k][1] + h for k, w, h in items), default=0)
    return pos, W, H


def first_fit(w, h, box, start, taken, step=0.25):
    """raster first-fit of a w x h rect in box from the start corner, avoiding taken."""
    x0, x1, y0, y1 = box
    ys = [y0 + i * step for i in range(int((y1 - y0 - h) / step) + 1)]
    xs = [x0 + i * step for i in range(int((x1 - x0 - w) / step) + 1)]
    if start[0] == "top":
        ys = [y1 - h - (y - y0) for y in ys]
    if start[1] == "right":
        xs = [x1 - w - (x - x0) for x in xs]
    for y in ys:
        for x in xs:
            r = (x, x + w, y, y + h)
            if not any(overlap(r, t) for t in taken):
                return r
    return None


# --------------------------------------------------------------------------- main
def main():
    fp = design()
    ds = {ref: fp[ref]["dataStr"] for ref in fp}
    sheet_order = list(G.GROUPS)
    group_of, groups = {}, []
    for sh in sheet_order:
        for cap, refs in G.GROUPS[sh]:
            blk = G.BLOCK_OF.get(refs[0]) or "common"
            groups.append(dict(sheet=sh, cap=cap, refs=list(refs), block=blk))
            for r in refs:
                group_of[r] = len(groups) - 1

    place = {}                     # ref -> (rot, mirror, x0, y0) lower-left of bbox, ZedBoard mm
    rects = {"top": [], "bottom": []}

    # J1: bottom side, C1 over the carrier's C1.  footprint pads: Cn at u = 625 - 5n,
    # rows C / D / G / H at v = 382.5 / 387.5 / 402.5 / 407.5 -> x = C1x + 0.254 (v - 382.5),
    # y = C1y + 0.254 (620 - u), i.e. Xe = ex0 + (v - 382.5), Ye = ey0 + (u - 620) (mirror).
    j1 = ds["J1"]
    jx, jy = float(j1["head"]["x"]), float(j1["head"]["y"])
    ex0, ey0 = E(*J1_C1)
    j1xf = Xf(ex0 + (jy - 382.5), ey0 + (jx - 620.0), mat=(0, 1, 1, 0))
    place["J1"] = ("J1", j1xf, True)
    rects["bottom"].append(board_rect(j1, j1xf))      # SMD, bottom side only

    # keep-outs: holes (both sides), carrier zone (bottom), routing band (top)
    holes = [(x, y, 2.7) for x, y in STANDOFFS] + [(x, y, 3.2) for x, y in SUPPORTS]
    for x, y, d in holes:
        k = HOLE_KEEP[d]
        for s in rects:
            rects[s].append((x - k, x + k, y - k, y + k))
    rects["bottom"].append((STRIP[0] - 5, BODY[0] + 0.5, STRIP[2] - 5, STRIP[3] + 5))
    rects["top"].append((186.0, 221.0, 68.3, 72.7))   # FMC -> TX / RX routing channel

    # fixed: USB-C J102 at the right edge, TX/RX boundary, opening +X
    usb = ds["J102"]
    w, h = size_mm(usb, 270)
    r = (BODY[1] - w, BODY[1], 90.0 - h / 2, 90.0 + h / 2)     # shell flush with the edge
    place["J102"] = ("fix", 270, False, r[0], r[2])
    rects["top"].append(r)

    # decoupling 100 nF caps with only a rail + GND go to the bottom under their group
    def is_decap(ref):                 # 100 nF between a supply rail and GND only
        p = G.PARTS[ref]
        n = set(G.NETS.get(ref, {}).values())
        return ref.startswith("C") and p["value"] == "100nF" and "GND" in n and len(n) == 2 \
            and all(x == "GND" or RAIL.match(x) for x in n)
    bottom_caps = {r for r in G.PARTS if is_decap(r)}

    report = []
    for blk in ("common", "CDR", "PLL", "TX", "RX"):
        box = REGIONS[blk]
        st = START[blk]
        bg = [i for i, g in enumerate(groups) if g["block"] == blk]
        # groups with SMA / edge connectors first (they land on the outer rows)
        def gkey(i):
            g = groups[i]
            sma = any(ds[r]["head"]["c_para"]["package"].startswith("SMA") for r in g["refs"])
            usbg = "J102" in g["refs"] or g["cap"].startswith(("Line taps", "FS/LS driver",
                                                                 "HS termination"))
            return (0 if (sma or usbg) else 1, i)
        for gi in sorted(bg, key=gkey):
            g = groups[gi]
            refs = [r for r in g["refs"] if r not in place and r not in bottom_caps]
            if not refs:
                continue
            refs.sort(key=lambda r: (0 if r[0] in "UJQY" else 1, -size_mm(ds[r], 0)[1],
                                     G.refkey(r)))
            items = [(r,) + tuple(v + GAP_PART for v in size_mm(ds[r], 0)) for r in refs]
            area = sum(w * h for _, w, h in items)
            width = max(max(w for _, w, _ in items), math.sqrt(area * 1.5))
            pos, W, H = shelf(items, width, 0.0)
            ok = None
            for wf in (1.0, 0.75, 1.35, 0.6, 1.8):     # retry narrower / wider if no room
                pos, W, H = shelf(items, max(max(w for _, w, _ in items), width * wf), 0.0)
                ok = first_fit(W + GAP_GROUP, H + GAP_GROUP, box, st, rects["top"], 0.5)
                if ok:
                    break
            if not ok:
                # spill into any body area
                ok = first_fit(W + GAP_GROUP, H + GAP_GROUP, BODY, st, rects["top"])
                report.append("group %r of %s did not fit its region: placed in body" %
                              (g["cap"][:40], blk))
            if not ok:
                raise SystemExit("no room for group %r" % g["cap"])
            gx = ok[0] + GAP_GROUP / 2
            gy = ok[2] + GAP_GROUP / 2
            flipy = st[0] == "top"
            for r, w, h in items:
                px, py = pos[r]
                y = gy + (H - py - h if flipy else py)
                place[r] = ("fix", 0, False, gx + px + GAP_PART / 2, y + GAP_PART / 2)
            rects["top"].append(ok)
            g["rect"] = ok
            for r in refs:                     # through-hole pads block the bottom side too
                if any(sh.startswith("PAD~") and sh.split("~")[6] == "11" for sh in ds[r]["shape"]):
                    _, rot, _, x0, y0 = place[r]
                    w, h = size_mm(ds[r], rot)
                    rects["bottom"].append((x0, x0 + w, y0, y0 + h))

    # bottom decaps: a grid centred under the group's largest IC, spiral search
    for ref in sorted(bottom_caps, key=G.refkey):
        g = groups[group_of[ref]]
        ics = [r for r in g["refs"] if r[0] == "U" and r in place] or \
              [r for r in g["refs"] if r in place and place[r][0] == "fix"]
        if ics:
            a = max(ics, key=lambda r: size_mm(ds[r], 0)[0] * size_mm(ds[r], 0)[1])
            _, rot, mir, x0, y0 = place[a]
            w, h = size_mm(ds[a], rot)
            cx, cy = x0 + w / 2, y0 + h / 2
        else:
            r0 = g.get("rect") or REGIONS[g["block"]]
            cx, cy = (r0[0] + r0[1]) / 2, (r0[2] + r0[3]) / 2
        w, h = size_mm(ds[ref], 90)
        done = False
        for rad in range(0, 60):
            for k in range(max(1, 8 * rad)):
                a = 2 * math.pi * k / max(1, 8 * rad)
                x = cx + rad * 0.9 * math.cos(a) - w / 2
                y = cy + rad * 0.9 * math.sin(a) - h / 2
                rr = (x - 0.25, x + w + 0.25, y - 0.25, y + h + 0.25)
                if inside(rr, BODY, EDGE) and \
                        not any(overlap(rr, t) for t in rects["bottom"]):
                    place[ref] = ("fix", 90, True, x, y)
                    rects["bottom"].append(rr)
                    done = True
                    break
            if done:
                break
        if not done:
            raise SystemExit("no bottom room for " + ref)

    # ---------------------------------------------------------------- shapes
    shapes = []
    # board outline
    p = " ".join("%s %s" % tuple(f3(v) for v in E(x, y)) for x, y in OUTLINE + OUTLINE[:1])
    shapes.append("TRACK~1~10~~%s~%s~0" % (p, gid()))
    # mounting holes: plated, GND
    for i, (x, y, d) in enumerate(holes):
        ex, ey = E(x, y)
        pad = 5.0 if d == 2.7 else 6.0
        shapes.append("PAD~ELLIPSE~%s~%s~%s~%s~11~GND~MH%d~%s~~0~%s~0~~Y~0~0~0~%s,%s" % (
            f3(ex), f3(ey), f3(pad * MM), f3(pad * MM), i + 1, f3(d / 2 * MM), gid(),
            f3(ex), f3(ey)))
    # Document layer: ZedBoard reference
    zb = [(0, 0), (ZED_W, 0), (ZED_W, ZED_H), (0, ZED_H), (0, 0)]
    shapes.append("TRACK~0.6~12~~%s~%s~0" % (
        " ".join("%s %s" % tuple(f3(v) for v in E(x, y)) for x, y in zb), gid()))
    for x, y in [(0.15 * 25.4, 0.15 * 25.4), (6.15 * 25.4, 0.15 * 25.4),
                 (0.15 * 25.4, 5.15 * 25.4), (6.15 * 25.4, 5.15 * 25.4)] + STANDOFFS:
        ex, ey = E(x, y)
        shapes.append("CIRCLE~%s~%s~%s~0.6~12~%s~0" % (f3(ex), f3(ey), f3(1.6 * MM), gid()))
    j1c = [(145.0, 38.9), (159.8, 38.9), (159.8, 96.0), (145.0, 96.0), (145.0, 38.9)]
    shapes.append("TRACK~0.6~12~~%s~%s~0" % (
        " ".join("%s %s" % tuple(f3(v) for v in E(x, y)) for x, y in j1c), gid()))
    xadc = [(137.0, 106.0), (153.0, 106.0), (153.0, 114.0), (137.0, 114.0), (137.0, 106.0)]
    shapes.append("TRACK~0.6~12~~%s~%s~0" % (
        " ".join("%s %s" % tuple(f3(v) for v in E(x, y)) for x, y in xadc), gid()))
    notes = [(20.0, 125.0, "ZEDBOARD REV D OUTLINE (REFERENCE, NOT FABRICATED)"),
             (110.0, 116.0, "XADC HEADER J2 (TALL)"),
             (100.0, 26.0, "NO BOTTOM PARTS OVER THE CARRIER (X < 160.5)"),
             (187.0, 70.5, "FMC ROUTING CHANNEL")]
    for x, y, t in notes:
        ex, ey = E(x, y)
        shapes.append("TEXT~L~%s~%s~0.6~0~~12~~6~%s~~~%s~~0" % (f3(ex), f3(ey), t, gid()))

    # footprints
    rows = []
    for ref in sorted(place, key=G.refkey):
        d = ds[ref]
        pr = place[ref]
        if pr[0] == "J1":
            xf, bottom, rot = pr[1], True, 0
        else:
            _, rot, bottom, x0, y0 = pr
            xf = xf_at(d, rot, bottom, x0, y0)
        sub, padnums = place_shapes(d, xf, bottom, G.NETS.get(ref, {}))
        miss = set(G.NETS.get(ref, {})) - set(padnums)
        if miss:
            raise SystemExit("%s: netlist pins without pad: %s" % (ref, sorted(miss)))
        r = board_rect(d, xf)
        cx, cy = E((r[0] + r[1]) / 2, (r[2] + r[3]) / 2)
        part = G.PARTS[ref]
        cp = dict(d["head"]["c_para"])
        cp.update({"package": cp.get("package", ""), "pre": re.sub(r"\d+$", "?", ref),
                   "Manufacturer Part": part["mpn"], "Supplier Part": part["lcsc"],
                   "Value": part["value"]})
        para = "`".join("%s`%s" % (k, str(v).replace("`", "'").replace("~", "-")
                                   .replace("#@$", "")) for k, v in cp.items())
        ox_, oy_ = xf.p(0, 0)
        head = "LIB~%s~%s~%s~%d~~%s~%s~%s~%s~0~~yes~%s~" % (
            f3(ox_), f3(oy_), para, rot, gid(), "2" if bottom else "1", fp[ref]["uuid"],
            fp[ref].get("updateTime", ""), fp[ref].get("datastrid", ""))
        tl = "4" if bottom else "3"
        txt = ["TEXT~P~%s~%s~0.4~0~%s~%s~~2.5~%s~~~%s~~0" % (
            f3(cx), f3(cy + 1), "1" if bottom else "", tl, ref, gid()),
            "TEXT~N~%s~%s~0.4~0~%s~%s~~2.5~%s~~none~%s~~0" % (
            f3(cx), f3(cy + 4), "1" if bottom else "", tl, part["value"], gid())]
        shapes.append("#@$".join([head] + txt + sub))
        rows.append([ref, part["value"], cp.get("package", ""), G.BLOCK_OF.get(ref) or "common",
                     "bottom" if bottom else "top", "%.3f" % ((r[0] + r[1]) / 2),
                     "%.3f" % ((r[2] + r[3]) / 2), rot,
                     groups[group_of[ref]]["cap"][:60]])

    layers = list(ds["C1"]["layers"])
    for i, l in enumerate(layers):
        n = l.split("~")
        if n[0] in ("21", "22", "23", "24"):
            n[3:6] = ["true", "false", "true"]
            n[1] = {"21": "Inner1_GND", "22": "Inner2_SIG", "23": "Inner3_PWR",
                    "24": "Inner4_GND"}[n[0]]
            layers[i] = "~".join(n)
    oxs, oys = E(0, 0)
    doc = {
        "head": {"docType": "3", "editorVersion": "6.5.61", "newgId": True,
                 "c_para": {}, "x": f3(oxs), "y": f3(oys), "hasIdFlag": True,
                 "importFlag": 0, "transformList": ""},
        "canvas": "CA~2400~2400~#000000~yes~#FFFFFF~3.937~2400~2400~line~0.5~mm~0.6~45~visible~"
                  "0.5~%s~%s~0~yes" % (f3(oxs), f3(oys)),
        "shape": shapes,
        "layers": layers,
        "BBox": {"x": f3(E(STRIP[0] - 150, 0)[0]), "y": f3(E(0, ZED_H)[1]),
                 "width": f3((BODY[1] + 5) * MM), "height": f3((ZED_H + 5) * MM)},
        "preference": {"hideFootprints": "", "hideNets": ""},
        "DRCRULE": {"Default": {"trackWidth": 0.6, "clearance": 0.6, "viaHoleDiameter": 2.0,
                                "viaHoleD": 1.0},
                    "Power": {"trackWidth": 1.6, "clearance": 0.6, "viaHoleDiameter": 2.4,
                              "viaHoleD": 1.2,
                              "nets": sorted({n for p in G.NETS.values() for n in p.values()
                                              if RAIL.match(n)})},
                    "isRealtime": True, "checkObjectToCopperarea": True,
                    "showDRCRangeLine": True},
        "netColors": {},
    }
    with open(os.path.join(HERE, "usb_aio_board_pcb.json"), "w") as f:
        json.dump(doc, f, ensure_ascii=False)
    with open(os.path.join(HERE, "placement.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ref", "value", "package", "block", "side", "x_mm", "y_mm", "rot", "group"])
        w.writerows(rows)
    for l in report:
        print("NOTE", l)
    nb = sum(1 for r in rows if r[4] == "bottom")
    print("parts %d (top %d, bottom %d), shapes %d, board %.1f x %.1f mm" % (
        len(rows), len(rows) - nb, nb, len(shapes), BODY[1] - STRIP[0], BODY[3] - BODY[2]))
    return rows


if __name__ == "__main__":
    main()
