#!/usr/bin/env python3
"""route_rest.py - route everything route_critical.py leaves, add the GND planes.

Run after route_critical.py.  The critical nets' copper (USB D+ / D-, the LVDS
pairs) is kept as is; every other track, via and copper area is removed and
routed again, so the script can be re-run.

Order:
  0. Fanout of the fine-pitch parts (pitch <= 0.7 mm: QFN, TSSOP, MSOP...).
     Every pin gets an escape lane along its axis, out of a keep-out zone (pad
     extents + 1 mm), and a dog-bone: a 0.16 mm neck to a via at the lane end
     (every other lane 0.7 mm longer, so the vias stagger; slid outward, or
     offset sideways on a 45 degree neck, until it clears).  Pins without
     room for a via get a plain 0.3-0.6 mm stub.
  1. RF / ECL signal nets: every signal net with a pad in a VCO, VCO buffer,
     ECL (MC100EP, NB6L14, CDCM1804) or prop-driver group.  Shortest first, Top
     preferred.  They go first, so they get the short direct paths.
  2. GND: every SMD GND pad gets its own stitching via to the GND planes on
     Inner1 (L2) and Inner4 (L5): vias in the pad on exposed pads, else a
     0.25 mm stub to the nearest free spot within 3.5 mm, outside the fanout
     zones.  Fallbacks: a spot in the pad's own part zone, or a stub to GND
     copper that already has a via.  Through-hole GND pads join the planes
     directly; dog-boned GND pins already have their via.
  3. The other signal nets, shortest first.  Width 0.16 mm; Top / Inner2 /
     Bottom (Top cheapest).
     Steps 0-3 run PASSES times on a fresh board, the failed nets of a pass
     first in the next; the best pass is kept.
  4. Supply rails: on Inner3 (L4, the power layer), 0.41 mm, with Power vias
     (0.61 / 0.305 mm).  The pad stubs on Top / Bottom are 0.41 mm, or 0.254 mm
     where there is no room (DRCRULE Power).
  5. Retry of every incomplete net on the whole board, with a larger search
     limit and one more layer (signals Inner3, rails Inner2, at a higher cost).
  6. Copper areas: GND on Inner1 and Inner4 over the whole board (0.3 mm
     clearance).  EasyEDA fills them on Tools -> Copper Area -> Rebuild All
     (Shift+B).

Zones and lanes: a net that does not touch a fine-pitch part stays off Top
and places no via inside its zone; a net on the part may use Top and vias
there only along its own lanes.  Other nets' lanes are closed to a net's
tracks and vias everywhere.

Router: route_critical.py's A* grid router (0.1 mm, 8 directions, through vias,
line-of-sight smoothing).  Per net the obstacle maps are computed once in a
window around the net (net box + 8 mm, then the whole board on failure).
Track maps use a 0.08 mm grid margin, via maps 0.13 mm.  Every run is then
checked with exact geometry against pads and all routed copper; a path that
fails is searched again on the 0.13 mm track grid, and a net that still
fails is left unrouted (listed in route_rest_report.txt), never laid too close.

  python3 route_rest.py   -> usb_aio_board_pcb.json, route_rest_report.txt
"""
import csv
import json
import math
import os
import re
import sys
import time

import numpy as np

sys.dont_write_bytecode = True
import route_critical as R                                    # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
R.LAYERS = ("1", "2", "22", "23")        # Top, Bottom, Inner2 (signals), Inner3 (power)
R.NL = len(R.LAYERS)
TOP, BOT, IN2, IN3 = range(4)
GND_LAYERS = ("21", "24")                # Inner1, Inner4: GND copper areas

RAIL = re.compile(r"^(\+|P3V3|P12V|12P0V|VADJ|P5V|3P3V)")
RF_GROUP = re.compile(r"Colpitts VCO|^Buffer -> |VCO supply|MC100EP|Alexander|Decision XOR|"
                      r"NB6L14|Prop driver|CDCM1804|^Y1 \(VCO|CLK_RX monitor|HS receiver")

W_SIG = 0.16
W_GND = 0.25
W_RAIL, W_RAIL_MIN = 0.41, 0.254
VIA_SIG = (0.508, 0.254)
VIA_PWR = (0.61, 0.305)
GND_R = 3.5                              # mm, GND via search radius
ZONE = 1.0                               # mm, fanout keep-out around fine-pitch parts
MARGIN = 0.08                            # track grid margin; every laid run is checked exactly
MARGIN_SAFE = 0.13                       # conservative grid: vias always, tracks when a fine path fails
LANE_OUT = 0.3                           # mm, escape lane beyond the zone edge
LANE_STAGGER = 0.7                       # mm, extra length of every other lane
PASSES = 1                               # signal passes (failed nets first in the next)
WIN = 8.0                                # mm, window margin around a net


def raw_runs(path):
    """cell path -> runs with a vertex at every direction change (no shortcuts)."""
    runs, cur = [], [path[0]]
    for q in path[1:]:
        if q[0] != cur[-1][0]:
            runs.append(cur)
            cur = [q]
        else:
            cur.append(q)
    runs.append(cur)
    out = []
    for run in runs:
        pts = [run[0]]
        for k in range(1, len(run) - 1):
            d1 = (run[k][1] - run[k - 1][1], run[k][2] - run[k - 1][2])
            d2 = (run[k + 1][1] - run[k][1], run[k + 1][2] - run[k][2])
            if d1 != d2:
                pts.append(run[k])
        if len(run) > 1:
            pts.append(run[-1])
        out.append((run[0][0], [R.cxy(q[2], q[1]) for q in pts]))
    return out


def seg_seg(a, b, c, d):
    """distance between segments a-b and c-d."""
    def sd(p, u, v):
        dx, dy = v[0] - u[0], v[1] - u[1]
        l2 = dx * dx + dy * dy
        t = 0 if l2 == 0 else max(0, min(1, ((p[0] - u[0]) * dx + (p[1] - u[1]) * dy) / l2))
        return math.hypot(p[0] - u[0] - t * dx, p[1] - u[1] - t * dy)

    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    if o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0:
        return 0.0
    return min(sd(a, c, d), sd(b, c, d), sd(c, a, b), sd(d, a, b))


def critical_nets(b):
    keep = {"DP", "DM"}
    for base in R.PAIRS:
        keep |= set(R.pair_nets(b, base))
    return keep


def set_via(v):
    R.VIA_D, R.VIA_HOLE = v


def window(pads, margin):
    xs = [p["x"] for p in pads]
    ys = [p["y"] for p in pads]
    return R.box_of(min(xs) - margin, max(xs) + margin, min(ys) - margin, max(ys) + margin)


class Rest:
    def __init__(self, b):
        self.b = b
        self.rt = R.Router(b)
        self.rep = []
        self.unrouted = []
        self.esc = {}
        self.zones = []                  # (ref, grid box, nets of the part)
        self.lanes = {}                  # ref -> escape lanes of its fine-pitch pins
        self.dog = set()                 # (ref, num) of pins with a dog-bone via
        self.nseg = 0                    # routed-copper bucket index (exact checks)
        self.sbucket = {}
        self.padlist = list(b.pads.values()) + [p for p in b.netpads.get("", [])]
        self.pbucket = {}
        for k, p in enumerate(self.padlist):
            self.pbucket.setdefault((int(p["x"] // 2), int(p["y"] // 2)), []).append(k)
            if not p["poly"]:
                r = max(p["w"], p["h"]) / 2
                p["xpoly"] = [(p["x"] + r * math.cos(t * math.pi / 8),
                               p["y"] + r * math.sin(t * math.pi / 8)) for t in range(16)]
        self.padmask = [np.zeros((R.NY, R.NX), bool) for _ in range(R.NL)]
        for p in b.pads.values():
            i0, i1, j0, j1 = p["box"]
            for L in p["layers"]:
                self.padmask[L][j0:j1, i0:i1] |= p["mask"]

    def cells(self, p):
        """copper cells of pad p plus its fanout stub."""
        return self.rt.pad_cells(p) | self.esc.get((p["ref"], p["num"]), set())

    # ------------------------------------------------------------ fine-pitch fanout
    def fanout(self, skip):
        """fine-pitch parts (pitch <= 0.7 mm): keep-out zone, an escape lane per
        pin and a dog-bone (neck + via) or stub, all checked with exact
        geometry (see the module docstring).  The grid router then starts from
        the via or stub tip, where its discretisation margin no longer closes
        the gap between the pins.  Returns the number of dog-bones + stubs."""
        b = self.b
        byref = {}
        for (ref, num), p in b.pads.items():
            byref.setdefault(ref, []).append(p)
        for p in b.pads.values():       # round pads: 16-gon for the exact check
            if not p["poly"]:
                r = max(p["w"], p["h"]) / 2
                p["xpoly"] = [(p["x"] + r * math.cos(k * math.pi / 8),
                               p["y"] + r * math.sin(k * math.pi / 8)) for k in range(16)]
        foreign_pads = list(b.pads.values())
        made = 0
        pins = []
        for ref, ps in byref.items():
            smd = [p for p in ps if len(p["layers"]) == 1]
            if len(smd) < 4:
                continue
            pitch = min(math.hypot(a["x"] - c["x"], a["y"] - c["y"])
                        for i, a in enumerate(smd) for c in smd[i + 1:])
            if pitch > 0.7:
                continue
            cx = sum(p["x"] for p in smd) / len(smd)
            cy = sum(p["y"] for p in smd) / len(smd)
            # keep-out zone: pad extents + ZONE; other nets: no Top track, no via
            ext = [(q[0], q[1]) for p in smd for q in (p["poly"] or [(p["x"], p["y"])])]
            x0 = min(q[0] for q in ext) - ZONE
            x1 = max(q[0] for q in ext) + ZONE
            y0 = min(q[1] for q in ext) - ZONE
            y1 = max(q[1] for q in ext) + ZONE
            self.zones.append((ref, R.box_of(x0, x1, y0, y1), {p["net"] for p in ps}))
            for p in smd:
                if not p["net"] or not p["poly"] or \
                        (abs(p["x"] - cx) < 0.3 and abs(p["y"] - cy) < 0.3):
                    continue             # exposed pad / no net
                L = p["layers"][0]
                poly = p["poly"]
                ed = [(math.dist(poly[k], poly[(k + 1) % len(poly)]), k) for k in range(len(poly))]
                l, k = max(ed)
                ux = (poly[(k + 1) % len(poly)][0] - poly[k][0]) / l
                uy = (poly[(k + 1) % len(poly)][1] - poly[k][1]) / l
                if (p["x"] - cx) * ux + (p["y"] - cy) * uy < 0:
                    ux, uy = -ux, -uy
                if abs((p["x"] - cx) * ux + (p["y"] - cy) * uy) < 0.2:
                    continue             # pad axis not pointing away from the body
                # alternate lane lengths along a side, so neighbouring via
                # sites at the lane ends are staggered
                odd = int(round((p["x"] * abs(uy) + p["y"] * abs(ux)) / pitch)) % 2
                t_site = self.add_lane(ref, p, ux, uy, (x0, x1, y0, y1), LANE_STAGGER * odd)
                if p["net"] in skip:
                    continue             # kept net: lane only, no stub
                pins.append((p, L, ux, uy, l, t_site))
        # dog-bones: W_SIG neck along the lane (rails / GND too: it is short) + via.
        # Pass 0: via at the (staggered) lane end, slid outward until it clears
        # exactly.  Pass 1 (pins still without one): via offset sideways on a 45
        # degree neck.  Else a plain stub.
        todo = pins
        for lateral in (False, True):
            left = []
            for p, L, ux, uy, l, t_site in todo:
                a = (p["x"], p["y"])
                cands = []
                for k in range(21):
                    t = t_site + 0.1 * k
                    if not lateral:
                        cands.append([a, (p["x"] + ux * t, p["y"] + uy * t)])
                        continue
                    for off in (0.35, -0.35, 0.7, -0.7):
                        m = (p["x"] + ux * (t - abs(off)), p["y"] + uy * (t - abs(off)))
                        cands.append([a, m, (m[0] + ux * abs(off) - uy * off,
                                             m[1] + uy * abs(off) + ux * off)])
                for pts in cands:
                    if self.runs_ok([(L, pts), (L, pts[-1:])], W_SIG, p["net"]):
                        c = pts[-1]
                        cells = b.track(pts, W_SIG, L, p["net"]) | b.via(c[0], c[1], p["net"])
                        self.esc[(p["ref"], p["num"])] = cells
                        self.dog.add((p["ref"], p["num"]))
                        made += 1
                        break
                else:
                    left.append((p, L, ux, uy, l, t_site))
            todo = left
        for p, L, ux, uy, l, t_site in todo:
            w = W_RAIL_MIN if RAIL.match(p["net"]) else (W_GND if p["net"] == "GND" else W_SIG)
            a = (p["x"], p["y"])
            for ext in (0.6, 0.45, 0.3):
                tip = (p["x"] + ux * (l / 2 + ext), p["y"] + uy * (l / 2 + ext))
                if self.clear(a, tip, w, L, p, foreign_pads):
                    cells = b.track([a, tip], w, L, p["net"])
                    self.esc[(p["ref"], p["num"])] = cells
                    made += 1
                    break
        return made

    def near_pads(self, a, c):
        """pads in the 2 mm buckets the segment a-c touches (+1 bucket)."""
        out = set()
        for i in range(int(min(a[0], c[0]) // 2) - 1, int(max(a[0], c[0]) // 2) + 2):
            for j in range(int(min(a[1], c[1]) // 2) - 1, int(max(a[1], c[1]) // 2) + 2):
                out.update(self.pbucket.get((i, j), ()))
        return [self.padlist[k] for k in out]

    def index_segs(self):
        """add new routed copper of the board to the 2 mm bucket index."""
        segs = self.b.segs
        for k in range(self.nseg, len(segs)):
            L, a, c, r, n = segs[k]
            for i in range(int((min(a[0], c[0]) - r) // 2), int((max(a[0], c[0]) + r) // 2) + 1):
                for j in range(int((min(a[1], c[1]) - r) // 2),
                               int((max(a[1], c[1]) + r) // 2) + 1):
                    self.sbucket.setdefault((i, j), []).append(k)
        self.nseg = len(segs)

    def copper_ok(self, a, c, w, L, net):
        """exact clearance of segment a-c (layer L, None = via) to routed copper of
        other nets."""
        segs = self.b.segs
        seen = set()
        for i in range(int(min(a[0], c[0]) // 2) - 1, int(max(a[0], c[0]) // 2) + 2):
            for j in range(int(min(a[1], c[1]) // 2) - 1, int(max(a[1], c[1]) // 2) + 2):
                for k in self.sbucket.get((i, j), ()):
                    if k in seen:
                        continue
                    seen.add(k)
                    L2, p, q, r, n = segs[k]
                    if n == net or (L is not None and L2 is not None and L2 != L):
                        continue
                    if seg_seg(a, c, p, q) - r - w / 2 < R.CLR:
                        return False
        return True

    def runs_ok(self, runs, w, net):
        """exact clearance of the runs to other-net pads and routed copper."""
        self.index_segs()
        own = {"net": net}
        for k, (L, pts) in enumerate(runs):
            for a, c in zip(pts, pts[1:]):
                if not self.copper_ok(a, c, w, L, net):
                    return False
            if k + 1 < len(runs) and not self.copper_ok(pts[-1], pts[-1], R.VIA_D, None, net):
                return False
        for k, (L, pts) in enumerate(runs):
            segs = list(zip(pts, pts[1:]))
            if k + 1 < len(runs):
                segs.append((pts[-1], pts[-1]))
            for a, c in segs:
                ww = R.VIA_D if a == c and k + 1 < len(runs) and c == pts[-1] else w
                lays = range(R.NL) if ww == R.VIA_D and a == c else (L,)
                for LL in lays:
                    if not self.clear(a, c, ww, LL, own, self.near_pads(a, c), grid=False):
                        return False
        return True

    def clear(self, a, c, w, L, own, pads, grid=True):
        """exact clearance of segment a-c (width w, layer L) to other-net pads, and
        (on the grid) to other-net copper."""
        for q in pads:
            if q["net"] == own["net"] and q["net"] or L not in q["layers"]:
                continue
            if abs(q["x"] - a[0]) > 4 or abs(q["y"] - a[1]) > 4:
                continue
            pl = q["poly"] or q["xpoly"]
            g = min(seg_seg(a, c, pl[k], pl[(k + 1) % len(pl)]) for k in range(len(pl)))
            if g - w / 2 < R.CLR or R.pip(np.array([c[0]]), np.array([c[1]]), pl)[0]:
                return False
        if not grid:
            return True
        mask, box = R.rast_capsule(a, c, w / 2 + R.CLR + 0.08)
        i0, i1, j0, j1 = box
        cu = self.b.cu[L][j0:j1, i0:i1]
        return not np.any(mask & (cu != 0) & (cu != self.b.nid(own["net"]))) \
            or self.only_pad_cells(mask, box, L, own)

    def only_pad_cells(self, mask, box, L, own):
        """True if the foreign cells under mask all belong to pads (checked exactly)."""
        i0, i1, j0, j1 = box
        cu = self.b.cu[L][j0:j1, i0:i1]
        bad = mask & (cu != 0) & (cu != self.b.nid(own["net"]))
        return not np.any(bad & ~self.padmask[L][j0:j1, i0:i1])

    def add_lane(self, ref, p, ux, uy, box, extra=0.0):
        """escape lane of a fine-pitch pin: from the pad centre along its axis to
        LANE_OUT (+ extra) beyond the zone edge, ending in a reserved via site.
        Kept as grid masks: centre line (open to the pin's net inside the zone),
        track block and via block along the lane and around the site (closed to
        the other nets; the site on all layers)."""
        x0, x1, y0, y1 = box
        ts = [t for t in (((x1 - p["x"]) / ux if ux > 1e-9 else None),
                          ((x0 - p["x"]) / ux if ux < -1e-9 else None),
                          ((y1 - p["y"]) / uy if uy > 1e-9 else None),
                          ((y0 - p["y"]) / uy if uy < -1e-9 else None)) if t is not None]
        t = min(ts) + LANE_OUT + extra
        a, c = (p["x"], p["y"]), (p["x"] + ux * t, p["y"] + uy * t)
        self.lanes.setdefault(ref, []).append(dict(
            net=p["net"], L=p["layers"][0],
            centre=R.rast_capsule(a, c, 0.06),
            trk=R.rast_capsule(a, c, W_SIG + R.CLR),
            via=R.rast_capsule(a, c, R.VIA_D / 2 + R.CLR + W_SIG / 2),
            site_trk=R.rast_circle(c[0], c[1], R.VIA_D / 2 + R.CLR + W_SIG / 2),
            site_via=R.rast_circle(c[0], c[1], R.VIA_D + R.CLR)))
        return t

    def block_lanes(self, net, bl, vbl):
        """lanes of other nets: closed to this net's tracks on the lane's layer
        and to its vias."""
        for ref, lanes in self.lanes.items():
            for ln in lanes:
                if ln["net"] == net:
                    continue
                mask, (i0, i1, j0, j1) = ln["trk"]
                bl[ln["L"]][j0:j1, i0:i1] |= mask
                mask, (i0, i1, j0, j1) = ln["via"]
                for L in range(R.NL):
                    vbl[L][j0:j1, i0:i1] |= mask
                mask, (i0, i1, j0, j1) = ln["site_trk"]
                for L in range(R.NL):
                    bl[L][j0:j1, i0:i1] |= mask
                mask, (i0, i1, j0, j1) = ln["site_via"]
                for L in range(R.NL):
                    vbl[L][j0:j1, i0:i1] |= mask

    def apply_zones(self, net, pads, bl, vbl):
        """fanout zones of fine-pitch parts.  A part's own net may use Top and
        vias inside the zone only on its own lanes; a net that does not touch
        the part (and has no pad in the zone) stays off Top and vias there.
        Other nets' lanes are closed everywhere (block_lanes).  Own pad and
        stub cells keep their pre-zone state."""
        own = set()
        for p in pads:
            own |= self.cells(p)
        keep = [(L, j, i, bl[L][j, i]) for L, j, i in own]
        for ref, (i0, i1, j0, j1), nets in self.zones:
            if net in nets:
                sub = [bl[TOP][j0:j1, i0:i1].copy()] + [vbl[L][j0:j1, i0:i1].copy()
                                                       for L in range(R.NL)]
                bl[TOP][j0:j1, i0:i1] = True
                for L in range(R.NL):
                    vbl[L][j0:j1, i0:i1] = True
                for ln in self.lanes.get(ref, ()):
                    if ln["net"] != net:
                        continue
                    mask, (a0, a1, b0, b1) = ln["centre"]
                    # the lane cells inside this zone get their pre-zone state back
                    for jj, ii in zip(*np.nonzero(mask)):
                        j, i = b0 + jj, a0 + ii
                        if i0 <= i < i1 and j0 <= j < j1:
                            bl[TOP][j, i] = sub[0][j - j0, i - i0]
                            for L in range(R.NL):
                                vbl[L][j, i] = sub[1 + L][j - j0, i - i0]
                continue
            if any(i0 <= R.cell(p["x"], p["y"])[0] < i1 and
                   j0 <= R.cell(p["x"], p["y"])[1] < j1 for p in pads):
                continue
            bl[TOP][j0:j1, i0:i1] = True
            for L in range(R.NL):
                vbl[L][j0:j1, i0:i1] = True
        self.block_lanes(net, bl, vbl)
        for L, j, i, v in keep:
            bl[L][j, i] = v

    # ------------------------------------------------------------ one net
    def route_net(self, net, width, layers, lcost, vias, win_margin=WIN, limit=1_500_000):
        """connect all pads of net (nearest to the tree first).  Returns the pads
        that could not be connected.  Each pad is searched on the fine grid
        (MARGIN) first; if that path fails the exact clearance check, it is
        searched again on the conservative grid (MARGIN_SAFE)."""
        b, rt = self.b, self.rt
        pads = [p for p in b.netpads[net] if p["layers"]]
        if len(pads) < 2:
            return []
        set_via(vias)
        own = {b.nid(net)}
        left = []

        def maps(win, m):
            old = R.MARGIN
            R.MARGIN = m
            bl = b.blocked(own, width / 2 + R.CLR, win)
            R.MARGIN = max(m, MARGIN_SAFE)   # vias: always the conservative margin
            vbl = b.blocked(own, R.VIA_D / 2 + R.CLR, win)
            R.MARGIN = old
            self.apply_zones(net, pads, bl, vbl)
            via_ok = (~np.logical_or.reduce([vbl[L] for L in range(R.NL)])).ravel() \
                .astype(np.uint8).tobytes()
            return bl, R.to_bytes(bl), via_ok

        def search(p, allc, tree, mp):
            bl, blb, via_ok = mp
            start = {c for c in allc if not bl[c[0]][c[1], c[2]] and c[0] in layers}
            blb = list(blb)
            if not start:
                j, i = R.cell(p["x"], p["y"])[::-1]
                start = {(L, j, i) for L in p["layers"] if L in layers}
                for L, j_, i_ in start:
                    k = j_ * R.NX + i_
                    blb[L] = blb[L][:k] + b"\x00" + blb[L][k + 1:]
            tg = {c for c in tree - allc if not bl[c[0]][c[1], c[2]] and c[0] in layers}
            if not (start and tg):
                return None, False
            path = R.astar(blb, start, tg, layers, via_ok, limit=limit, lcost=lcost)
            if not path:
                return None, False
            runs = R.smooth(path, mp[1])
            if self.runs_ok(runs, width, net):
                return runs, True
            runs = raw_runs(path)        # the grid path itself, no shortcuts
            if self.runs_ok(runs, width, net):
                return runs, True
            return None, True            # found, but too close: try the safe grid

        for it, margin in enumerate((win_margin, None) if win_margin else (None,)):
            win = window(pads, margin) if margin else None
            fine = maps(win, MARGIN)
            safe = None
            tree = rt.tree.setdefault(net, set())
            if it == 0:
                todo = list(pads)
                if not tree:             # seed only an empty tree
                    tree |= self.cells(todo[0])
                    todo = todo[1:]
            else:
                todo = left
            left = []
            while todo:
                tj = np.array([c[1] for c in tree])
                ti = np.array([c[2] for c in tree])

                def dist(p):
                    j, i = R.cell(p["x"], p["y"])[::-1]
                    return float(np.min(np.hypot(tj - j, ti - i)))
                todo.sort(key=dist)
                p = todo.pop(0)
                allc = self.cells(p)
                if allc & tree:
                    continue
                runs, found = search(p, allc, tree, fine)
                if runs is None and found:
                    if safe is None:
                        safe = maps(win, MARGIN_SAFE)
                    runs, _ = search(p, allc, tree, safe)
                if runs is None:
                    left.append(p)
                    continue
                cells = set()
                for k, (L, pts) in enumerate(runs):
                    if len(pts) > 1:
                        cells |= b.track(pts, width, L, net)
                    if k + 1 < len(runs):
                        x, y = pts[-1]
                        cells |= b.via(x, y, net)
                tree |= cells | allc
            if not left:
                break
        return left

    # ------------------------------------------------------------ GND stitching
    def gnd_vias(self):
        """a via to the GND planes for every SMD GND pad: in the pad for exposed
        pads, else at the end of a short 0.25 mm stub (A* within GND_R), outside
        the fanout zones.  Pads that find no via site then get one in their own
        part's zone, or a stub to GND copper that already has a via."""
        b = self.b
        set_via(VIA_SIG)
        own = {b.nid("GND")}
        bl = b.blocked(own, W_GND / 2 + R.CLR)
        R.MARGIN = MARGIN_SAFE
        vbl = b.blocked(own, R.VIA_D / 2 + R.CLR)
        R.MARGIN = MARGIN
        self.block_lanes("GND", bl, vbl)
        vok0 = ~np.logical_or.reduce(vbl)            # via sites, zones allowed
        vok = vok0.copy()
        for ref, (i0, i1, j0, j1), nets in self.zones:   # keep the fanout zones clear
            vok[j0:j1, i0:i1] = False
        blb = R.to_bytes(bl)
        k = int(GND_R / R.G)
        conn = set()                                 # GND copper with a via
        n_ok, fail = 0, []

        def put_via(x, y):
            cells = b.via(x, y, "GND")
            self.index_segs()
            mask, box = R.rast_circle(x, y, R.VIA_D + R.CLR)   # no via on top of it
            i0_, i1_, j0_, j1_ = box
            vok[j0_:j1_, i0_:i1_] &= ~mask
            vok0[j0_:j1_, i0_:i1_] &= ~mask
            return cells

        def stub(p, sites, to_cu):
            """A* from pad p to a via site (sites mask) or, with to_cu, to
            connected GND copper; lays the stub (+ via).  True on success."""
            L = p["layers"][0]
            allc = self.cells(p)
            start = {c for c in allc if not bl[L][c[1], c[2]]}
            if not start:
                j, i = R.cell(p["x"], p["y"])[::-1]
                start = {(L, j, i)}
            cj, ci = R.cell(p["x"], p["y"])[::-1]
            j0, j1 = max(0, cj - k), min(R.NY, cj + k + 1)
            i0, i1 = max(0, ci - k), min(R.NX, ci + k + 1)
            jj, ii = np.nonzero(sites[j0:j1, i0:i1])
            tg = {(L, int(j + j0), int(i + i0)) for j, i in zip(jj, ii)
                  if (j + j0 - cj) ** 2 + (i + i0 - ci) ** 2 <= k * k}
            cu = set()
            if to_cu:
                cu = {c for c in conn if c[0] == L and (c[1] - cj) ** 2 + (c[2] - ci) ** 2 <= k * k
                      and not bl[L][c[1], c[2]]}
                tg |= cu
            tg -= allc
            if not tg:
                return False
            path = R.astar(blb, start, tg, (L,), None, limit=200_000)
            if not path:
                return False
            end_cu = path[-1] in cu
            for runs in (R.smooth(path, blb), raw_runs(path)):
                chk = runs if end_cu else runs + [(L, runs[0][1][-1:])]
                if self.runs_ok(chk, W_GND, "GND"):
                    break
            else:
                return False
            pts = runs[0][1]
            cells = set(allc)
            if len(pts) > 1:
                cells |= b.track(pts, W_GND, L, "GND")
            if not end_cu:
                cells |= put_via(*pts[-1])
            conn.update(cells)
            return True

        for p in b.netpads["GND"]:
            if not p["ref"] or len(p["layers"]) != 1:
                continue                 # through-hole: joins the planes directly
            if (p["ref"], p["num"]) in self.dog:
                n_ok += 1                # dog-bone via from the fanout
                continue
            L = p["layers"][0]
            if min(p["w"], p["h"]) >= 1.5:
                # exposed / thermal pad: vias in the pad (2 x 2 grid on larger pads)
                d = 0.5 if min(p["w"], p["h"]) >= 2.0 else 0.0
                spots = [(p["x"] + dx, p["y"] + dy) for dx in ((-d, d) if d else (0,))
                         for dy in ((-d, d) if d else (0,))]
                put = 0
                for x, y in spots:
                    if self.copper_ok((x, y), (x, y), R.VIA_D, None, "GND") and \
                            self.clear((x, y), (x, y), R.VIA_D, L, p,
                                       self.near_pads((x, y), (x, y)), grid=False):
                        conn.update(put_via(x, y))
                        put += 1
                if put:
                    conn.update(self.cells(p))
                    n_ok += 1
                    continue
            if stub(p, vok, False):
                n_ok += 1
            else:
                fail.append(p)
        # fallback: own part's zone allowed, or join connected GND copper
        while fail:
            left = []
            for p in fail:
                sites = vok.copy()
                for ref, (i0, i1, j0, j1), nets in self.zones:
                    if ref == p["ref"]:
                        sites[j0:j1, i0:i1] = vok0[j0:j1, i0:i1]
                if stub(p, sites, True):
                    n_ok += 1
                else:
                    left.append(p)
            if len(left) == len(fail):
                break
            fail = left
        return n_ok, fail

    # ------------------------------------------------------------ copper areas
    def planes(self):
        out = []
        pts = self.b.outline
        path = "M " + " L ".join("%s %s" % tuple(R.f3(v) for v in R.E(x, y)) for x, y in pts) + " Z"
        for L in GND_LAYERS:
            out.append("COPPERAREA~1~%s~GND~%s~%s~solid~%s~spoke~none~~0~~~1~1~1~0~0" % (
                L, path, R.f3(0.3 * R.MM), self.b.gid()))
        self.b.new += out


def group_nets():
    """signal nets with a pad in an RF / ECL group."""
    grp = {r["ref"]: r["group"] for r in csv.DictReader(open(os.path.join(HERE, "placement.csv")))}
    rf = set()
    for r in csv.DictReader(open(os.path.join(HERE, "..", "netlist.csv"))):
        if RF_GROUP.search(grp.get(r["ref"], "")):
            rf.add(r["net"])
    return rf


def main():
    t0 = time.time()
    R.MARGIN = MARGIN
    src = json.load(open(R.PCB))
    probe = R.Board(json.loads(json.dumps(src)))
    keep = critical_nets(probe)
    del probe

    def attempt(prio):
        """fanout, RF / ECL signals, GND vias, other signals on a fresh copy of
        the critical-only board; nets in prio go first in their stage."""
        doc = json.loads(json.dumps(src))
        b = R.Board(doc, keep)
        rs = Rest(b)
        rep = rs.rep
        nets = [n for n, ps in b.netpads.items() if n and n not in keep and n != "GND"
                and len([p for p in ps if p["layers"]]) > 1]
        rails = [n for n in nets if RAIL.match(n)]
        sig = [n for n in nets if n not in rails]

        def span(n):
            ps = b.netpads[n]
            return (max(p["x"] for p in ps) - min(p["x"] for p in ps) +
                    max(p["y"] for p in ps) - min(p["y"] for p in ps))

        def order(ns):
            return sorted(ns, key=lambda n: (n not in prio, span(n)))
        rf = group_nets()
        first = order(n for n in sig if n in rf)
        rest = order(n for n in sig if n not in rf)
        failed = {}

        def run(names, label, width, layers, lcost, vias):
            bad = 0
            for k, n in enumerate(names):
                left = rs.route_net(n, width, layers, lcost, vias)
                if left and width > W_RAIL_MIN and label == "rails":
                    left = rs.route_net(n, W_RAIL_MIN, layers, lcost, vias)
                if left:
                    bad += 1
                    failed[n] = (width, vias)
                if k % 25 == 0:
                    print("  %s %d/%d (%.0f s)" % (label, k, len(names), time.time() - t0),
                          flush=True)
            rep.append("%s: %d nets, %d incomplete" % (label, len(names), bad))
            print(rep[-1], flush=True)

        nf = rs.fanout(keep)
        rep.append("fine-pitch fanout (dog-bones + stubs): %d" % nf)
        print(rep[-1], flush=True)
        run(first, "RF / ECL signals", W_SIG, (TOP, BOT, IN2),
            {TOP: 1.0, BOT: 1.3, IN2: 1.2}, VIA_SIG)
        n_ok, fail = rs.gnd_vias()
        rep.append("GND stitching vias: %d, pads without a via: %d" % (n_ok, len(fail)))
        rs.unrouted += ["GND %s.%s (no via)" % (p["ref"], p["num"]) for p in fail]
        print(rep[-1], flush=True)
        run(rest, "other signals", W_SIG, (TOP, BOT, IN2),
            {TOP: 1.0, BOT: 1.15, IN2: 1.1}, VIA_SIG)
        return doc, b, rs, rails, span, failed, run

    # signal passes: failed nets of the previous passes are routed first
    prio, best = set(), None
    for k in range(PASSES):
        res = attempt(prio)
        nfail = len(res[5]) + sum(1 for u in res[2].unrouted if u.startswith("GND"))
        print("signal pass %d: %d failed nets / GND pads" % (k + 1, nfail), flush=True)
        if best is None or nfail < best[0]:
            best = (nfail, k + 1, res)
        if not nfail:
            break
        prio |= set(res[5])
    nfail, kbest, (doc, b, rs, rails, span, failed, run) = best
    rep = rs.rep
    rep.append("signal passes: %d, best pass %d (%d failed nets / GND pads)" % (
        k + 1, kbest, nfail))
    run(sorted(rails, key=span), "rails", W_RAIL, (TOP, BOT, IN3),
        {TOP: 3.0, BOT: 3.0, IN3: 1.0}, VIA_PWR)
    # retry: incomplete nets on the whole board, larger search, one more layer
    # (signals may use Inner3, rails Inner2, both at a higher step cost)
    still = 0
    for n, (width, vias) in list(failed.items()):
        if RAIL.match(n):
            left = rs.route_net(n, W_RAIL_MIN, (TOP, BOT, IN2, IN3),
                                {TOP: 3.0, BOT: 3.0, IN2: 2.0, IN3: 1.0}, VIA_PWR,
                                win_margin=None, limit=4_000_000)
        else:
            left = rs.route_net(n, W_SIG, (TOP, BOT, IN2, IN3),
                                {TOP: 1.0, BOT: 1.15, IN2: 1.1, IN3: 2.0}, VIA_SIG,
                                win_margin=None, limit=4_000_000)
        if left:
            still += 1
            rs.unrouted += ["%s %s.%s" % (n, p["ref"], p["num"]) for p in left]
    rep.append("retry: %d nets, %d still incomplete" % (len(failed), still))
    print(rep[-1], flush=True)
    rs.planes()
    set_via(VIA_SIG)
    doc["shape"] = doc["shape"] + b.new
    with open(R.PCB, "w") as f:
        json.dump(doc, f, ensure_ascii=False)
    nt = sum(1 for s in b.new if s.startswith("TRACK"))
    nv = sum(1 for s in b.new if s.startswith("VIA"))
    rep.append("new tracks %d, vias %d, copper areas %d; %.0f s" % (
        nt, nv, len(GND_LAYERS), time.time() - t0))
    rep.append("unrouted pads: %d" % len(rs.unrouted))
    rep += ["  " + u for u in rs.unrouted]
    with open(os.path.join(HERE, "route_rest_report.txt"), "w") as f:
        f.write("\n".join(rep) + "\n")
    print("\n".join(rep[:8]))
    return 0 if not rs.unrouted else 1


if __name__ == "__main__":
    sys.exit(main())
