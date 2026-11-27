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
    "TX": (221.0, 262.0, 2.31, 88.4),
    "RX": (221.0, 262.0, 91.6, 132.31),
    "common": (160.5, 180.0, 63.0, 78.0),
}
# corner the rows start from: (y side, x side); rows grow away from it
START = {"CDR": ("bottom", "left"), "PLL": ("top", "left"), "TX": ("top", "right"),
         "RX": ("bottom", "right"), "common": ("bottom", "left")}
GAP_PART, GAP_GROUP = 0.5, 1.4
RING = 0.7             # mm: free fanout ring around fine-pitch parts (top: no parts,
                       # bottom: no decaps), so every pin can escape
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


def fine_pitch(ds):
    """part with >= 4 SMD pads at <= 0.7 mm pitch (TSSOP, QFN, MSOP, SC-70...)."""
    pts = []
    for sh in ds["shape"]:
        f = sh.split("~")
        if f[0] == "PAD" and f[6] in ("1", "2"):
            pts.append((float(f[2]), float(f[3])))
    if len(pts) < 4:
        return False
    return min(math.hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(pts)
               for b in pts[i + 1:]) / MM <= 0.7


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


def near_fit(w, h, box, target, taken, step=0.5):
    """free w x h rect in box whose centre is nearest to target."""
    x0, x1, y0, y1 = box
    c = []
    for i in range(int((x1 - x0 - w) / step) + 1):
        for j in range(int((y1 - y0 - h) / step) + 1):
            x, y = x0 + i * step, y0 + j * step
            c.append(((x + w / 2 - target[0]) ** 2 + (y + h / 2 - target[1]) ** 2, x, y))
    for _, x, y in sorted(c):
        r = (x, x + w, y, y + h)
        if not any(overlap(r, t) for t in taken):
            return r
    return None


def pad_xy(ds, num):
    """pad centre relative to the footprint origin (EasyEDA units)."""
    ox, oy = float(ds["head"]["x"]), float(ds["head"]["y"])
    for sh in ds["shape"]:
        f = sh.split("~")
        if f[0] == "PAD" and f[8] == num:
            return float(f[2]) - ox, float(f[3]) - oy
    raise KeyError(num)


def pad_mm(ds, num, rot, mirror=False):
    """pad centre relative to the origin after rotation, ZedBoard mm (Y up)."""
    x, y = Xf(0, 0, rot, mirror).p(*pad_xy(ds, num))
    return x / MM, -y / MM


def fix_at_pad(ds, num, rot, x, y):
    """placement entry putting pad num at ZedBoard (x, y)."""
    dx, dy = pad_mm(ds, num, rot)
    ex, ey = E(x - dx, y - dy)
    r = board_rect(ds, Xf(ex, ey, rot))
    return ("fix", rot, False, r[0], r[2])


PAIR_RE = re.compile(r"^(.*)_([PN])(_F)?$")


def pair_key(nets, allnets):
    """(base, polarity) of the first differential-pair net among nets, else None."""
    for n in sorted(nets):
        m = PAIR_RE.match(n)
        if m:
            other = m.group(1) + "_" + ("N" if m.group(2) == "P" else "P") + (m.group(3) or "")
            if other in allnets:
                return m.group(1), m.group(2)
    return None


# USB D+ / D- corridor (top layer, ZedBoard mm): J102 at the right edge, the two
# 45 ohm lines (loosely coupled, 90 ohm differential) at y = 90.95 (DP) / 89.05 (DM)
# from the connector through U112 (flow-through ESD) to U111 (HS termination switch,
# common pins 3 / 4, DM above DP: one via) at the west end; every other part on DP / DM sits with its
# line pad right at its line (stub < 1 mm), DP parts above, DM parts below.
USB_Y = 90.0
USB_DP_Y, USB_DM_Y = 90.95, 89.05
USB_ESD_X = 250.6
USB_TAPS = [(247.5, "R134", "R135"), (245.6, "D106", "D107"), (243.7, "C118", "C119"),
            (241.8, "R209", "R210"), (239.9, "R155", "R156"), (238.0, "R129", "R130"),
            (236.1, "R131", None)]
USB_END = (233.6, 89.75)          # U111 pin 3 (DP); pin 4 (DM) 0.5 mm above


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
    corridor = {"J102"}

    def best_rot(ref, ok):
        for rot in (0, 90, 180, 270):
            if ok({n: pad_mm(ds[ref], n, rot) for n in G.NETS[ref]}):
                return rot
        raise SystemExit("no orientation for " + ref)
    # U112 flow-through: DP pins 1 / 6 in the upper row, DM 3 / 4 in the lower row
    rot = best_rot("U112", lambda q: abs(q["1"][1] - q["6"][1]) < 0.01 and
                   q["1"][1] > q["3"][1])
    dx = (pad_mm(ds["U112"], "1", rot)[0] - pad_mm(ds["U112"], "6", rot)[0]) / 2
    place["U112"] = fix_at_pad(ds["U112"], "1", rot, USB_ESD_X + dx, USB_DP_Y)
    corridor.add("U112")
    for x, rp, rm in USB_TAPS:
        for ref, net, side in ((rp, "DP", 1), (rm, "DM", -1)):
            if not ref:
                continue
            pin = [n for n, v in G.NETS[ref].items() if v == net][0]
            other = [n for n in G.NETS[ref] if n != pin][0]
            rot = best_rot(ref, lambda q: abs(q[pin][0] - q[other][0]) < 0.01 and
                           (q[other][1] - q[pin][1]) * side > 0)
            ly = USB_DP_Y if side > 0 else USB_DM_Y
            place[ref] = fix_at_pad(ds[ref], pin, rot, x, ly + side * 0.6)
            corridor.add(ref)
    # U111: common pins 3 (DP) / 4 (DM) facing east; its pinout puts DM above DP,
    # so the router swaps them with a via in the last millimetre
    rot = best_rot("U111", lambda q: q["3"][0] >= max(v[0] for v in q.values()) - 0.01 and
                   abs(q["3"][0] - q["4"][0]) < 0.01)
    place["U111"] = fix_at_pad(ds["U111"], "3", rot, *USB_END)
    corridor.add("U111")
    for ref in corridor - {"J102"}:
        _, rot, _, x0, y0 = place[ref]
        w, h = size_mm(ds[ref], rot)
        rects["top"].append((x0 - 0.15, x0 + w + 0.15, y0 - 0.15, y0 + h + 0.15))
    rects["top"].append((USB_END[0], BODY[1], USB_DM_Y - 0.6, USB_DP_Y + 0.6))   # the lines
    rects["bottom"].append((251.0, 255.2, 87.8, 92.2))     # J102 A6 / A7 jumpers
    corr_target = {}                   # group -> points it packs toward (USB corridor, J1)
    for ref in corridor:
        gi = group_of[ref]
        _, rot, _, x0, y0 = place[ref]
        w, h = size_mm(ds[ref], rot)
        corr_target.setdefault(gi, []).append((x0 + w / 2, y0 + h / 2))
    # groups on an FMC LVDS pair pack as close to that pair's J1 pins as they can
    nets_all = {n for p in G.NETS.values() for n in p.values()}
    j1y = {}
    for pin, n in G.NETS["J1"].items():
        if pair_key([n], nets_all):
            j1y[n] = J1_C1[1] + (int(pin[1:]) - 1) * 1.27
    for gi, g in enumerate(groups):
        if gi in corr_target or "J1" in g["refs"]:
            continue
        ys = [j1y[n] for r in g["refs"] for n in G.NETS.get(r, {}).values() if n in j1y]
        if ys:
            corr_target[gi] = [(BODY[0] + 4.0, sum(ys) / len(ys))]

    # decoupling 100 nF caps with only a rail + GND go to the bottom under their group
    def is_decap(ref):                 # 100 nF between a supply rail and GND only
        p = G.PARTS[ref]
        n = set(G.NETS.get(ref, {}).values())
        return ref.startswith("C") and p["value"] == "100nF" and "GND" in n and len(n) == 2 \
            and all(x == "GND" or RAIL.match(x) for x in n)
    bottom_caps = {r for r in G.PARTS if is_decap(r)}

    allnets = {n for p in G.NETS.values() for n in p.values()}
    report = []
    for blk in ("common", "CDR", "PLL", "TX", "RX"):
        box = REGIONS[blk]
        st = START[blk]
        bg = [i for i, g in enumerate(groups) if g["block"] == blk]
        # groups with SMA / edge connectors first (they land on the outer rows)
        def gkey(i):
            g = groups[i]
            if i in corr_target:
                return (-1, i)
            sma = any(ds[r]["head"]["c_para"]["package"].startswith("SMA") for r in g["refs"])
            usbg = "J102" in g["refs"] or g["cap"].startswith(("Line taps", "FS/LS driver",
                                                                 "HS termination"))
            return (0 if (sma or usbg) else 1, i)
        for gi in sorted(bg, key=gkey):
            g = groups[gi]
            refs = [r for r in g["refs"] if r not in place and r not in bottom_caps]
            if not refs:
                continue
            def skey(r):
                pk = pair_key(G.NETS.get(r, {}).values(), allnets)
                return (0 if r[0] in "UJQY" else 1, 0 if pk else 1, pk or ("", ""),
                        -size_mm(ds[r], 0)[1], G.refkey(r))
            refs.sort(key=skey)
            ring = {r: RING if fine_pitch(ds[r]) else 0.0 for r in refs}
            items = [(r,) + tuple(v + GAP_PART + 2 * ring[r] for v in size_mm(ds[r], 0))
                     for r in refs]
            # a P / N pair of equal two-pin parts (AC caps, series resistors) is one
            # block, P directly above N, so the pair's lines end side by side.  The
            # partner carries the mirrored pair net (..._P.. <-> ..._N..).
            def mirror(n):
                m = PAIR_RE.match(n)
                if not m:
                    return None
                return m.group(1) + "_" + ("N" if m.group(2) == "P" else "P") + (m.group(3) or "")
            two = {r: set(G.NETS.get(r, {}).values()) for r, _, _ in items
                   if len(G.NETS.get(r, {})) == 2}
            size = {r: (w, h) for r, w, h in items}
            partner = {}
            for r in two:
                if r in partner:
                    continue
                mir = {mirror(n) for n in two[r]} & allnets
                for r2 in two:
                    if r2 != r and r2 not in partner and mir & two[r2] and \
                            all(abs(u - v) < 0.01 for u, v in zip(size[r], size[r2])):
                        partner[r], partner[r2] = r2, r
                        break
            merged, done = [], set()
            for r, w, h in items:
                if r in done:
                    continue
                if r in partner:
                    r2 = partner[r]
                    pr = PAIR_RE.match(sorted(n for n in two[r] if mirror(n) in two[r2])[0])
                    rp, rn = (r, r2) if pr.group(2) == "P" else (r2, r)
                    merged.append((("pair", rp, rn), w, 2 * h))
                    done |= {r, r2}
                else:
                    merged.append((r, w, h))
            items = merged
            area = sum(w * h for _, w, h in items)
            width = max(max(w for _, w, _ in items), math.sqrt(area * 1.5))
            pos, W, H = shelf(items, width, 0.0)
            ok = None
            tgt = corr_target.get(gi)
            for wf in (1.0, 0.75, 1.35, 0.6, 1.8):     # retry narrower / wider if no room
                pos, W, H = shelf(items, max(max(w for _, w, _ in items), width * wf), 0.0)
                if tgt:                                 # next to its USB-corridor parts
                    t = (sum(p[0] for p in tgt) / len(tgt), sum(p[1] for p in tgt) / len(tgt))
                    ok = near_fit(W + GAP_GROUP, H + GAP_GROUP, box, t, rects["top"])
                else:
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
                if isinstance(r, tuple):        # pair block: N below, P above
                    hn = h / 2
                    place[r[2]] = ("fix", 0, False, gx + px + GAP_PART / 2, y + GAP_PART / 2)
                    place[r[1]] = ("fix", 0, False, gx + px + GAP_PART / 2,
                                   y + hn + GAP_PART / 2)
                else:
                    place[r] = ("fix", 0, False, gx + px + GAP_PART / 2 + ring[r],
                                y + GAP_PART / 2 + ring[r])
                    if ring[r]:                 # no bottom decaps in the fanout ring
                        w0, h0 = size_mm(ds[r], 0)
                        x0_, y0_ = place[r][3], place[r][4]
                        rects["bottom"].append((x0_ - RING, x0_ + w0 + RING,
                                                y0_ - RING, y0_ + h0 + RING))
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
                    # Power: the rail nets as a class.  route_rest.py runs them
                    # 0.41 mm with 0.61 / 0.305 mm vias; the minimums equal Default
                    # for the 0.16 mm dog-bone necks / 0.508 mm vias of fine-pitch
                    # supply pins
                    "Power": {"trackWidth": 0.6, "clearance": 0.6, "viaHoleDiameter": 2.0,
                              "viaHoleD": 1.0,
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
