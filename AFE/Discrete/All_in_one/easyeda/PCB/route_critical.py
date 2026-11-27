#!/usr/bin/env python3
"""route_critical.py - route the critical nets of the all-in-one PCB.

Reads usb_aio_board_pcb.json (as written by gen_pcb.py), removes any copper
tracks / vias from an earlier run, routes the nets below and writes the file
back (plus route_report.txt).  Routing layers: Top (L1), Inner2 (L3, the
stack's signal layer between L2 GND and L4 power) and Bottom (L6); Inner1 /
Inner4 stay free for the GND planes.

  1. USB D+ / D- (90 ohm differential): the corridor of gen_pcb.py.  Two 45 ohm
     microstrips on Top over L2 GND, w = 0.41 mm, 1.9 mm apart (loosely
     coupled), from J102 through U112 (flow-through) past every tap (stub
     < 1 mm) to U111.  The router finishes J102 (A6 / A7 cross) and U111 (DM
     above DP) with short stubs and vias.
  2. The LVDS pairs, 100 ohm differential: the FMC pairs CLK_RX, HS_RXD, DPAT,
     CLK60_A, CLK_BIT_A, TX_IN_P, TX_IN_N, RX_OUT and the on-board RX -> CDR
     pair RX_CDR.  Each is routed coupled (a wide centre line, then offset into
     P / N) on Inner2 from a launch point next to J1 (or the driver) to its
     receiver.  It falls back to Top / Bottom only if Inner2 has no room, and
     the retry passes route such pairs first.  The pins (J1 on the bottom) are
     finished with 0.16 mm stubs and dog-bone vias; the other pads of a pair net
     join its far end, never the connector breakout.

Widths (estimates, assuming JLC06161H-7628 class: 0.21 mm prepreg L1-L2,
er ~ 4.4, about 0.3 mm to each plane around L3; take the final values from
the fab's impedance calculator):
  outer (microstrip) w 0.20 / s 0.17 mm (~100 ohm diff),
  Inner2 (stripline) w 0.16 / s 0.22 mm (~100 ohm diff), USB w 0.41 mm (~45 ohm).

Router: A* on a 0.1 mm grid, 3 layers, 8 directions, through vias (0.508 /
0.254 mm, the DRCRULE default).  Obstacles are copper of other nets, grown by
half the track width plus the clearance.  Paths are straightened by line of
sight (any angle).  Afterwards, dangling track ends are trimmed back to the
last joint, and each pair's P / N copper length from the source pin to its
matched end (MATCH: the series AC caps or the receiver) is equalised to within
SKEW_TOL with rectangular bumps on the shorter line; route_report.txt lists the
lengths.  It is a first-pass router: check the result in EasyEDA (DRC) and tune
by hand.

  python3 route_critical.py      -> usb_aio_board_pcb.json (routed), route_report.txt
"""
import heapq
import json
import math
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, "usb_aio_board_pcb.json")
MM = 1 / 0.254
OX, OY = 4000.0, 3600.0
G = 0.1                                  # grid (mm)
X0, Y0, X1, Y1 = 142.5, 1.8, 262.5, 132.8
NX, NY = int(round((X1 - X0) / G)) + 1, int(round((Y1 - Y0) / G)) + 1
N = NX * NY
LAYERS = ("1", "2", "22")               # Top, Bottom, Inner2 (L3)
NL = len(LAYERS)
LNAME = {0: "Top", 1: "Bottom", 2: "Inner2", None: "-"}
MARGIN = 0.13                            # grid discretisation allowance (mm)

# rules (mm)
CLR = 0.16                               # copper clearance (DRC 0.152)
W_STUB = 0.16                            # finishing / breakout width
LVDS_W, LVDS_S, LVDS_CLR = 0.20, 0.17, 0.25     # outer layer (microstrip)
LVDS_W_IN, LVDS_S_IN = 0.16, 0.22                 # Inner2 (stripline)
USB_W = 0.41
VIA_D, VIA_HOLE = 0.508, 0.254                  # = DRCRULE Default via
VIA_COST = 30.0                          # in grid steps

PAIRS = ["CLK_RX", "HS_RXD", "DPAT", "CLK60_A", "CLK_BIT_A", "TX_IN_P", "TX_IN_N",
         "RX_OUT", "RX_CDR"]


def zb(x, y):
    return (x - OX) / MM, (OY - y) / MM


def E(x, y):
    return OX + x * MM, OY - y * MM


def f3(v):
    return ("%.4f" % v).rstrip("0").rstrip(".")


def cell(x, y):
    return int(round((x - X0) / G)), int(round((y - Y0) / G))


def cxy(ix, iy):
    return X0 + ix * G, Y0 + iy * G


# --------------------------------------------------------------------------- board model
class Board:
    def __init__(self, doc, keep=frozenset()):
        """keep: nets whose existing tracks / vias stay (and are obstacles);
        all other routed copper and every copper area is removed."""
        self.doc = doc
        self.keep = set(keep)
        self.netid = {}
        self.cu = [np.zeros((NY, NX), np.int32) for _ in LAYERS]
        self.pads = {}                   # (ref, num) -> dict(net, layers, poly/circle, x, y)
        self.netpads = {}
        self.outline = None
        self.maxid = 0
        self.new = []                    # new shape strings
        self.tracks = []                 # dict(net, L, pts, w, idx): idx into self.new
        self.vias = []                   # (x, y, net)
        self.segs = []                   # all routed copper: (L or None = via, a, c, r, net)
        self.parse()

    def nid(self, net):
        if not net:
            return -1
        if net not in self.netid:
            self.netid[net] = len(self.netid) + 1
        return self.netid[net]

    def parse(self):
        keep, kept = [], []
        for s in self.doc["shape"]:
            for m in re.finditer(r"gge(\d+)", s):
                self.maxid = max(self.maxid, int(m.group(1)))
            f = s.split("~")
            if f[0] == "COPPERAREA":
                continue
            if f[0] == "VIA" or (f[0] == "TRACK" and f[2] in ("1", "2", "21", "22", "23", "24")
                                 and f[3]):
                net = f[4] if f[0] == "VIA" else f[3]
                if net in self.keep:     # earlier routing of a kept net: an obstacle
                    keep.append(s)
                    kept.append(f)
                continue                 # earlier routing: removed
            keep.append(s)
            if f[0] == "TRACK" and f[2] == "10":
                v = [float(t) for t in f[4].split()]
                self.outline = [zb(v[i], v[i + 1]) for i in range(0, len(v), 2)]
            if f[0] == "PAD":
                self.add_pad(None, f)
            if f[0] == "LIB":
                sub = s.split("#@$")
                ref = [t.split("~")[10] for t in sub[1:] if t.startswith("TEXT~P")][0]
                for t in sub[1:]:
                    if t.startswith("PAD~"):
                        self.add_pad(ref, t.split("~"))
        self.doc["shape"] = keep
        # outside the board: blocked for everyone
        xs = X0 + np.arange(NX) * G
        ys = Y0 + np.arange(NY) * G
        gx, gy = np.meshgrid(xs, ys)
        inside = pip(gx, gy, self.outline)
        self.outside = ~inside
        # unplated holes (HOLE~x~y~radius, top level or in a footprint) count as
        # outside: the board-edge clearance applies to them
        for s in self.doc["shape"]:
            for t in s.split("#@$"):
                if t.startswith("HOLE~"):
                    h = t.split("~")
                    x, y = zb(float(h[1]), float(h[2]))
                    mask, (i0, i1, j0, j1) = rast_circle(x, y, float(h[3]) / MM)
                    self.outside[j0:j1, i0:i1] |= mask
        for f in kept:
            if f[0] == "VIA":
                x, y = zb(float(f[1]), float(f[2]))
                mask, box = rast_circle(x, y, float(f[3]) / MM / 2)
                for L in range(NL):
                    self.paint(L, mask, box, self.nid(f[4]))
                self.vias.append((x, y, f[4]))
                self.segs.append((None, (x, y), (x, y), float(f[3]) / MM / 2, f[4]))
            elif f[2] in LAYERS:
                L = LAYERS.index(f[2])
                v = [float(t) for t in f[4].split()]
                pts = [zb(v[i], v[i + 1]) for i in range(0, len(v), 2)]
                for a, c in zip(pts, pts[1:]):
                    mask, box = rast_capsule(a, c, float(f[1]) / MM / 2)
                    self.paint(L, mask, box, self.nid(f[3]))
                    self.segs.append((L, a, c, float(f[1]) / MM / 2, f[3]))

    def add_pad(self, ref, f):
        net = f[7]
        n = self.nid(net)
        x, y = zb(float(f[2]), float(f[3]))
        w, h = float(f[4]) / MM, float(f[5]) / MM
        lay = list(range(NL)) if f[6] == "11" else \
            ([0] if f[6] == "1" else ([1] if f[6] == "2" else []))
        if not lay:
            return
        shape = f[1]
        if shape in ("RECT", "POLYGON") and f[10].strip():
            v = [float(t) for t in f[10].split()]
            poly = [zb(v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)]
            mask, box = rast_poly(poly)
        elif shape == "ELLIPSE":
            poly = None
            mask, box = rast_circle(x, y, max(w, h) / 2)
        else:                            # OVAL / RECT without points: rotated rectangle
            a = math.radians(-float(f[11] or 0))
            c, s_ = math.cos(a), math.sin(a)
            poly = [(x + c * dx - s_ * dy, y + s_ * dx + c * dy)
                    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]
            mask, box = rast_poly(poly)
        holer = float(f[9] or 0) / MM
        p = dict(ref=ref, num=f[8], net=net, nid=n, layers=lay, x=x, y=y, mask=mask, box=box,
                 hole=holer, poly=poly, w=w, h=h)
        if ref:
            self.pads[(ref, f[8])] = p
        if net:
            self.netpads.setdefault(net, []).append(p)
        for L in lay:
            self.paint(L, mask, box, n)

    def paint(self, L, mask, box, n):
        i0, i1, j0, j1 = box
        sub = self.cu[L][j0:j1, i0:i1]
        sub[(sub == 0) & mask] = n

    # ---------------- adding copper
    def gid(self):
        self.maxid += 1
        return "gge%d" % self.maxid

    def track(self, pts, w, L, net):
        n = self.nid(net)
        p = " ".join("%s %s" % tuple(f3(v) for v in E(x, y)) for x, y in pts)
        gid = self.gid()
        self.tracks.append(dict(net=net, L=L, pts=list(pts), w=w, idx=len(self.new), gid=gid))
        self.segs += [(L, a, c, w / 2, net) for a, c in zip(pts, pts[1:])]
        self.new.append("TRACK~%s~%s~%s~%s~%s~0" % (f3(w * MM), LAYERS[L], net, p, gid))
        cells = set()
        for a, b in zip(pts, pts[1:]):
            mask, box = rast_capsule(a, b, w / 2)
            self.paint(L, mask, box, n)
            cells |= mask_cells(mask, box, L)
        return cells

    def via(self, x, y, net):
        n = self.nid(net)
        ex, ey = E(x, y)
        self.vias.append((x, y, net))
        self.segs.append((None, (x, y), (x, y), VIA_D / 2, net))
        self.new.append("VIA~%s~%s~%s~%s~%s~%s~0" % (f3(ex), f3(ey), f3(VIA_D * MM), net,
                                                  f3(VIA_HOLE / 2 * MM), self.gid()))
        mask, box = rast_circle(x, y, VIA_D / 2)
        cells = set()
        for L in range(NL):              # through via
            self.paint(L, mask, box, n)
            cells |= mask_cells(mask, box, L)
        return cells

    # ---------------- obstacle maps
    def blocked(self, own, r, win=None):
        """per layer: cells closer than r (mm) to copper of other nets or the edge.
        win (i0, i1, j0, j1): compute only there, everything outside is blocked."""
        out = []
        ownarr = np.array(sorted(own), np.int32)
        for L in range(NL):
            if win is None:
                cu, osd = self.cu[L], self.outside
            else:
                i0, i1, j0, j1 = win
                cu, osd = self.cu[L][j0:j1, i0:i1], self.outside[j0:j1, i0:i1]
            foreign = (cu != 0) & ~np.isin(cu, ownarr)
            m = dilate(foreign, r) | dilate(osd, r + 0.3 - MARGIN)
            if win is not None:
                full = np.ones((NY, NX), bool)
                full[j0:j1, i0:i1] = m
                m = full
            out.append(m)
        return out


def mask_cells(mask, box, L):
    i0, i1, j0, j1 = box
    jj, ii = np.nonzero(mask)
    return {(L, int(j + j0), int(i + i0)) for j, i in zip(jj, ii)}


# --------------------------------------------------------------------------- rasterising
def pip(px, py, poly):
    inside = np.zeros(px.shape, bool)
    n = len(poly)
    for k in range(n):
        x1, y1 = poly[k]
        x2, y2 = poly[(k + 1) % n]
        if y1 == y2:
            continue
        c = ((y1 > py) != (y2 > py)) & (px < (x2 - x1) * (py - y1) / (y2 - y1) + x1)
        inside ^= c
    return inside


def box_of(xmin, xmax, ymin, ymax):
    i0 = max(0, int(math.floor((xmin - X0) / G)))
    i1 = min(NX, int(math.ceil((xmax - X0) / G)) + 1)
    j0 = max(0, int(math.floor((ymin - Y0) / G)))
    j1 = min(NY, int(math.ceil((ymax - Y0) / G)) + 1)
    return i0, i1, j0, j1


def grid_of(box):
    i0, i1, j0, j1 = box
    xs = X0 + np.arange(i0, i1) * G
    ys = Y0 + np.arange(j0, j1) * G
    return np.meshgrid(xs, ys)


def rast_poly(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    box = box_of(min(xs), max(xs), min(ys), max(ys))
    gx, gy = grid_of(box)
    return pip(gx, gy, poly), box


def rast_circle(x, y, r):
    box = box_of(x - r, x + r, y - r, y + r)
    gx, gy = grid_of(box)
    return (gx - x) ** 2 + (gy - y) ** 2 <= r * r, box


def rast_capsule(a, b, r):
    box = box_of(min(a[0], b[0]) - r, max(a[0], b[0]) + r, min(a[1], b[1]) - r,
                 max(a[1], b[1]) + r)
    gx, gy = grid_of(box)
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = np.clip(((gx - a[0]) * dx + (gy - a[1]) * dy) / L2, 0, 1) if L2 > 0 else 0
    px, py = a[0] + t * dx, a[1] + t * dy
    return (gx - px) ** 2 + (gy - py) ** 2 <= r * r, box


_disk = {}


def dilate(mask, r):
    k = int(math.ceil((r + MARGIN) / G - 1e-9))
    if k <= 0:
        return mask.copy()
    if k not in _disk:
        rr = (r + MARGIN) / G
        _disk[k] = [(dj, di) for dj in range(-k, k + 1) for di in range(-k, k + 1)
                    if dj * dj + di * di <= rr * rr]
    out = np.zeros_like(mask)
    ny, nx = mask.shape
    for dj, di in _disk[k]:
        out[max(0, dj):ny + min(0, dj), max(0, di):nx + min(0, di)] |= \
            mask[max(0, -dj):ny + min(0, -dj), max(0, -di):nx + min(0, -di)]
    return out


# --------------------------------------------------------------------------- A*
DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
        (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]


def astar(blocked, starts, targets, layers=(0, 1, 2), via_ok=None, limit=3_000_000,
          lcost=None, via_cost=None):
    """blocked: [bytes per layer]; starts / targets: sets of (L, j, i).  lcost: step
    cost factor per layer (>= 1).  Returns the cell path (list of (L, j, i)) or None."""
    vc = VIA_COST if via_cost is None else via_cost
    if not targets:
        return None
    tj = [t[1] for t in targets]
    ti = [t[2] for t in targets]
    bj0, bj1, bi0, bi1 = min(tj), max(tj), min(ti), max(ti)
    tset = {(L * NY + j) * NX + i for L, j, i in targets}

    def h(j, i):
        dj = 0 if bj0 <= j <= bj1 else min(abs(j - bj0), abs(j - bj1))
        di = 0 if bi0 <= i <= bi1 else min(abs(i - bi0), abs(i - bi1))
        return max(dj, di) + 0.4142 * min(dj, di)
    gs = {}
    prev = {}
    pq = []
    for L, j, i in starts:
        if L not in layers:
            continue
        k = (L * NY + j) * NX + i
        gs[k] = 0.0
        prev[k] = -1
        heapq.heappush(pq, (h(j, i) * 1.001, k))
    n = 0
    while pq:
        f, k = heapq.heappop(pq)
        if k in tset:
            path = []
            while k != -1:
                L, r = divmod(k, NY * NX)
                path.append((L, r // NX, r % NX))
                k = prev[k]
            return path[::-1]
        n += 1
        if n > limit:
            return None
        gk = gs[k]
        L, r = divmod(k, NY * NX)
        j, i = divmod(r, NX)
        bl = blocked[L]
        for di, dj, c in DIRS:
            jj, ii = j + dj, i + di
            if not (0 <= jj < NY and 0 <= ii < NX):
                continue
            kk = (L * NY + jj) * NX + ii
            if bl[jj * NX + ii] and kk not in tset:
                continue
            g2 = gk + (c * lcost[L] if lcost else c)
            if g2 < gs.get(kk, 1e18):
                gs[kk] = g2
                prev[kk] = k
                heapq.heappush(pq, (g2 + h(jj, ii) * 1.001, kk))
        if via_ok is not None and len(layers) > 1 and via_ok[r]:
            for L2 in layers:
                if L2 == L or blocked[L2][r]:
                    continue
                kk = (L2 * NY + j) * NX + i
                g2 = gk + vc
                if g2 < gs.get(kk, 1e18):
                    gs[kk] = g2
                    prev[kk] = k
                    heapq.heappush(pq, (g2 + h(j, i) * 1.001, kk))
    return None


def free_line(bl, a, b):
    """straight segment a -> b (cells, same layer) clear in bl (bytes)?"""
    (j0, i0), (j1, i1) = a, b
    n = int(max(abs(j1 - j0), abs(i1 - i0)) * 2) + 1
    for t in range(n + 1):
        j = int(round(j0 + (j1 - j0) * t / n))
        i = int(round(i0 + (i1 - i0) * t / n))
        if bl[j * NX + i]:
            return False
    return True


def smooth(path, blocked, ends_free=False):
    """cell path -> [(layer, [(x, y), ...]), ...] runs, straightened by line of sight."""
    runs, cur = [], [path[0]]
    for p in path[1:]:
        if p[0] != cur[-1][0]:
            runs.append(cur)
            cur = [p]
        else:
            cur.append(p)
    runs.append(cur)
    out = []
    for run in runs:
        L = run[0][0]
        bl = blocked[L]
        pts = [run[0]]
        k = 0
        while k < len(run) - 1:
            best = k + 1
            for m in range(len(run) - 1, k + 1, -1):
                if free_line(bl, run[k][1:], run[m][1:]):
                    best = m
                    break
            pts.append(run[best])
            k = best
        out.append((L, [cxy(p[2], p[1]) for p in pts]))
    return out


def to_bytes(masks):
    return [m.ravel().astype(np.uint8).tobytes() for m in masks]


# --------------------------------------------------------------------------- routing ops
class Router:
    def __init__(self, board):
        self.b = board
        self.tree = {}                   # net -> set of (L, j, i) copper cells of the routed tree
        self.report = []

    def pad_cells(self, p):
        cells = set()
        for L in p["layers"]:
            cells |= mask_cells(p["mask"], p["box"], L)
        return cells

    def connect(self, net, pad, width=W_STUB, layers=(0, 1, 2), excl=frozenset()):
        """single-ended route from pad to the net's routed tree (minus excl)."""
        b = self.b
        own = {b.nid(net)}
        hw = width / 2
        bl = b.blocked(own, hw + CLR)
        vbl = b.blocked(own, VIA_D / 2 + CLR)
        via_ok = (~np.logical_or.reduce(vbl)).ravel().astype(np.uint8).tobytes()
        allc = self.pad_cells(pad)
        # leave / enter pads only from cells a track centre may use: on a fine-pitch
        # pad that is the middle; if none is free, the pad centre cell
        start = {c for c in allc if not bl[c[0]][c[1], c[2]]}
        if not start:
            j, i = cell(pad["x"], pad["y"])[::-1]
            start = {(L, j, i) for L in pad["layers"]}
            for L, j, i in start:
                bl[L][j, i] = False
        blb = to_bytes(bl)
        tree = self.tree.get(net, set()) - allc - excl
        tgt = {c for c in tree if not bl[c[0]][c[1], c[2]]}
        if not tgt:
            tgt = tree
        path = astar(blb, start, tgt, layers, via_ok)
        if not path:
            return False
        self.lay(net, path, blb, hw * 2)
        self.tree[net] |= allc
        return True

    def lay(self, net, path, blb, width):
        cells = set()
        runs = smooth(path, blb)
        for k, (L, pts) in enumerate(runs):
            if len(pts) > 1:
                cells |= self.b.track(pts, width, L, net)
            if k + 1 < len(runs):
                x, y = pts[-1]
                cells |= self.b.via(x, y, net)
        self.tree.setdefault(net, set()).update(cells)

    def finish(self, net, src=None):
        """connect every pad of the net to its tree, nearest first.  The source pad
        (J1 / the driver) goes first, and the others may not join its breakout:
        they hang on the far end of the coupled line, not back at the connector."""
        todo = list(self.b.netpads[net])
        ok = True
        excl = set()
        sp = [p for p in todo if p["ref"] == src]
        if sp and self.tree.get(net):
            todo.remove(sp[0])
            before = set(self.tree[net])
            if not (self.pad_cells(sp[0]) & before) and not self.connect(net, sp[0]):
                self.report.append("UNROUTED %s %s.%s" % (net, src, sp[0]["num"]))
                ok = False
            excl = (self.tree[net] - before) | self.pad_cells(sp[0])
            self.tree[net] |= self.pad_cells(sp[0])
        while todo:
            t = self.tree.get(net, set())
            if not t:
                p = todo.pop(0)
                self.tree[net] = set(self.pad_cells(p))
                continue
            tj = np.array([c[1] for c in t])
            ti = np.array([c[2] for c in t])

            def dist(p):
                j, i = cell(p["x"], p["y"])[::-1]
                return float(np.min(np.hypot(tj - j, ti - i)))
            todo.sort(key=dist)
            p = todo.pop(0)
            if self.pad_cells(p) & t:
                continue                 # already touching
            if not self.connect(net, p, excl=excl) and not self.connect(net, p):
                self.report.append("UNROUTED %s %s.%s" % (net, p["ref"], p["num"]))
                ok = False
        return ok

    # ---------------- coupled pair
    def pair(self, base, pn, nn, start_xy, end_xy, layers_try=(2, 0, 1)):
        b = self.b
        for L in layers_try:
            w, sp = (LVDS_W_IN, LVDS_S_IN) if L == 2 else (LVDS_W, LVDS_S)
            d = sp + w                       # centre-to-centre
            hw = d / 2 + w / 2               # centre line to the outer edge
            bl = b.blocked(set(), hw + LVDS_CLR)  # its own pads too: the lines are P / N
            blb = to_bytes(bl)
            def disc(xy, R):
                cj, ci = cell(*xy)[::-1]
                k = int(R / G)
                return {(L, j, i) for j in range(cj - k, cj + k + 1)
                        for i in range(ci - k, ci + k + 1)
                        if 0 <= j < NY and 0 <= i < NX and (j - cj) ** 2 + (i - ci) ** 2 <= k * k
                        and not bl[L][j, i]}
            starts = disc(start_xy, 0.3) or disc(start_xy, 1.5) or disc(start_xy, 3.0)
            if not starts:
                continue
            for R in (1.5, 2.5, 4.0, 6.0):
                tg = disc(end_xy, R)
                path = astar(blb, starts, tg, (L,), None)
                if path:
                    runs = smooth(path, blb)
                    pts = runs[0][1]
                    self.split(base, pn, nn, pts, L, d, w)
                    return L
        return None

    def split(self, base, pn, nn, pts, L, d, w):
        """offset the centre line by +-d/2; P on the side nearer to its first pin."""
        if len(pts) < 2:
            return
        lines = {side: offset(pts, side * d / 2) for side in (1, -1)}
        pp = [p for p in self.b.netpads[pn] if p["ref"] == "J1"] or self.b.netpads[pn]
        p0 = min(pp, key=lambda p: math.hypot(p["x"] - pts[0][0], p["y"] - pts[0][1]))
        sp = min((1, -1), key=lambda s: math.hypot(lines[s][0][0] - p0["x"], lines[s][0][1] - p0["y"]))
        for net, side in ((pn, sp), (nn, -sp)):
            cells = self.b.track(lines[side], w, L, net)
            self.tree.setdefault(net, set()).update(cells)


def offset(pts, o):
    """polyline offset by o (left of the direction of travel > 0); mitred on the
    inner side of a bend, bevelled on the outer side so the line stays inside the
    swept band of the centre line."""
    nrm = []
    for a, c in zip(pts, pts[1:]):
        dx, dy = c[0] - a[0], c[1] - a[1]
        l = math.hypot(dx, dy) or 1
        nrm.append((-dy / l, dx / l))
    out = [(pts[0][0] + o * nrm[0][0], pts[0][1] + o * nrm[0][1])]
    for k in range(1, len(pts) - 1):
        n1, n2 = nrm[k - 1], nrm[k]
        p = pts[k]
        turn = n1[0] * n2[1] - n1[1] * n2[0]           # > 0: left turn
        outer = (turn > 0) == (o < 0)
        sx, sy = n1[0] + n2[0], n1[1] + n2[1]
        ls = math.hypot(sx, sy)
        cosh = (sx * n1[0] + sy * n1[1]) / ls if ls > 1e-9 else 0
        if outer and cosh < 0.999:
            out.append((p[0] + o * n1[0], p[1] + o * n1[1]))
            out.append((p[0] + o * n2[0], p[1] + o * n2[1]))
        else:
            c = max(cosh, 0.5)
            out.append((p[0] + o * sx / ls / c, p[1] + o * sy / ls / c))
    out.append((pts[-1][0] + o * nrm[-1][0], pts[-1][1] + o * nrm[-1][1]))
    return out


# --------------------------------------------------------------------------- USB corridor
def usb(router):
    b = router.b
    pads = b.pads
    dp_y = pads[("U112", "1")]["y"]
    dm_y = pads[("U112", "3")]["y"]
    x_east = 253.3
    dp_west = min(p["x"] for p in b.netpads["DP"] if p["ref"] not in ("U111", "J102"))
    dm_west = min(p["x"] for p in b.netpads["DM"] if p["ref"] not in ("U111", "J102"))
    for net, y, xw in (("DP", dp_y, dp_west), ("DM", dm_y, dm_west)):
        cells = b.track([(x_east, y), (xw, y)], USB_W, 0, net)
        router.tree.setdefault(net, set()).update(cells)
        for p in b.netpads[net]:         # tap stubs: line centre -> pad centre
            if p["ref"] in ("U111", "J102", "U112"):
                continue
            cells = b.track([(p["x"], y), (p["x"], p["y"])], 0.3, 0, net)
            router.tree[net] |= cells | router.pad_cells(p)
        for p in b.netpads[net]:
            if p["ref"] == "U112":
                router.tree[net] |= router.pad_cells(p)
    ok = True
    for net in ("DP", "DM"):
        for p in sorted(b.netpads[net], key=lambda p: p["ref"]):
            if p["ref"] in ("J102", "U111"):
                if not router.connect(net, p):
                    router.report.append("UNROUTED %s %s.%s" % (net, p["ref"], p["num"]))
                    ok = False
    return ok


# --------------------------------------------------------------------------- length / skew
# matched pins of each pair: (source part, P end pin, N end pin).  The ends are the
# series AC-coupling caps or the receiver IC; the shunt parts (bias, termination)
# are branches and do not count.
MATCH = {
    "CLK_RX": ("J1", "C440.2", "C441.2"), "HS_RXD": ("J1", "C442.2", "C443.2"),
    "DPAT": ("J1", "C421.1", "C422.1"), "CLK60_A": ("J1", "C365.2", "C366.2"),
    "CLK_BIT_A": ("J1", "C363.2", "C364.2"), "TX_IN_P": ("J1", "U105.2", "U105.3"),
    "TX_IN_N": ("J1", "U106.2", "U106.3"), "RX_OUT": ("J1", "C237.2", "C238.2"),
    "RX_CDR": ("U216", "C474.1", "C475.1"),
}
SKEW_TOL = 0.25                          # mm, target |P - N|
TUNE_P = 0.6                             # bump pitch (mm)
TUNE_AMIN, TUNE_AMAX = 0.15, 1.2          # bump amplitude (mm)


def seg_point(p, a, b):
    """(distance, t) of point p to segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy), t


def pad_touch(pad, p, r):
    """copper of pad within r of point p?"""
    i0, i1, j0, j1 = pad["box"]
    jj, ii = np.nonzero(pad["mask"])
    if not len(jj):
        return False
    xs = X0 + (ii + i0) * G
    ys = Y0 + (jj + j0) * G
    return bool(np.min(np.hypot(xs - p[0], ys - p[1])) <= r + G * 0.75)


def net_graph(b, net):
    """copper graph of a net: nodes are track vertices, vias and pads.  Returns
    (adjacency, attach) where attach[ti] lists positions (k, t) on track ti
    where other copper joins."""
    T = [(ti, t) for ti, t in enumerate(b.tracks) if t["net"] == net]
    V = [(vi, v) for vi, v in enumerate(b.vias) if v[2] == net]
    P = [p for p in b.netpads.get(net, []) if p["ref"]]
    adj = {}
    attach = {}

    def add(u, v, w, tag=None):          # tag: (track, segment, f0, f1) along the copper
        adj.setdefault(u, []).append((v, w, tag))
        adj.setdefault(v, []).append((u, w, tag))
    for ti, t in T:
        pts = t["pts"]
        for k in range(len(pts) - 1):
            add(("t", ti, k), ("t", ti, k + 1), math.dist(pts[k], pts[k + 1]), (ti, k, 0.0, 1.0))
    for ti, t in T:
        pts = t["pts"]
        for k in (0, len(pts) - 1):
            p = pts[k]
            node = ("t", ti, k)
            for tj, u in T:
                if tj == ti or u["L"] != t["L"]:
                    continue
                q = u["pts"]
                for m in range(len(q) - 1):
                    dd, tt = seg_point(p, q[m], q[m + 1])
                    if dd <= (t["w"] + u["w"]) / 2 + 0.02:
                        l = math.dist(q[m], q[m + 1])
                        add(node, ("t", tj, m), tt * l, (tj, m, 0.0, tt))
                        add(node, ("t", tj, m + 1), (1 - tt) * l, (tj, m, tt, 1.0))
                        attach.setdefault(tj, []).append((m, tt))
            for vi, v in V:
                if math.hypot(v[0] - p[0], v[1] - p[1]) <= VIA_D / 2 + t["w"] / 2:
                    add(node, ("v", vi), 0.0)
            for pd in P:
                if t["L"] in pd["layers"] and pad_touch(pd, p, t["w"] / 2):
                    add(node, ("p", "%s.%s" % (pd["ref"], pd["num"])), 0.0)
    for vi, v in V:                      # via-in-pad
        for pd in P:
            if pad_touch(pd, v[:2], VIA_D / 2):
                add(("v", vi), ("p", "%s.%s" % (pd["ref"], pd["num"])), 0.0)
    return adj, attach


def set_pts(b, ti, pts):
    t = b.tracks[ti]
    t["pts"] = pts
    pstr = " ".join("%s %s" % tuple(f3(v) for v in E(x, y)) for x, y in pts)
    b.new[t["idx"]] = "TRACK~%s~%s~%s~%s~%s~0" % (f3(t["w"] * MM), LAYERS[t["L"]], t["net"],
                                                 pstr, t["gid"])


def trim_dangling(b, nets):
    """cut track ends that touch nothing (e.g. a coupled line running on past the
    stub that joins it) back to the last joint.  Returns the length removed."""
    cut = 0.0
    for net in nets:
        for _ in range(6):
            adj, attach = net_graph(b, net)
            changed = False
            for ti, t in enumerate(b.tracks):
                if t["net"] != net or t["pts"] is None:
                    continue
                pts = t["pts"]
                last = len(pts) - 1
                for end in (0, last):
                    deg = len(adj.get(("t", ti, end), []))
                    if deg > 1 or (deg == 1 and last == 0):
                        continue
                    # joints on this track as arc positions
                    acc = [0.0]
                    for k in range(last):
                        acc.append(acc[-1] + math.dist(pts[k], pts[k + 1]))
                    js = [acc[m] + tt * (acc[m + 1] - acc[m]) for m, tt in attach.get(ti, [])]
                    for k in range(last + 1):
                        if k != end and any(v[0] != "t" or v[1] != ti
                                            for v, _, _ in adj.get(("t", ti, k), [])):
                            js.append(acc[k])
                    if not js:
                        continue
                    pos = min(js) if end == last else max(js)
                    pos = max(js) if end == last else min(js)
                    # keep [0, pos] when trimming the far end, [pos, total] for the start
                    keep = (0.0, pos) if end == last else (pos, acc[-1])
                    if keep[1] - keep[0] >= acc[-1] - 1e-6:
                        continue

                    def at(x):
                        for k in range(last):
                            if acc[k] <= x <= acc[k + 1] + 1e-9:
                                f = 0 if acc[k + 1] == acc[k] else (x - acc[k]) / (acc[k + 1] - acc[k])
                                return (pts[k][0] + f * (pts[k + 1][0] - pts[k][0]),
                                        pts[k][1] + f * (pts[k + 1][1] - pts[k][1]))
                        return pts[-1]
                    newp = [at(keep[0])] + [pts[k] for k in range(last + 1)
                                            if keep[0] < acc[k] < keep[1]] + [at(keep[1])]
                    cut += acc[-1] - (keep[1] - keep[0])
                    set_pts(b, ti, newp)
                    changed = True
                    break
                if changed:
                    break
            if not changed:
                break
    return cut


def path_len(b, net, src_ref, dst):
    """shortest copper length (mm) from any pad of src_ref to pad dst, and the
    (track, segment) list of that path; (None, []) if not connected."""
    adj, attach = net_graph(b, net)
    srcs = [("p", "%s.%s" % (p["ref"], p["num"])) for p in b.netpads[net] if p["ref"] == src_ref]
    dist = {}
    prev = {}
    pq = []
    for s_ in srcs:
        if s_ in adj:
            dist[s_] = 0.0
            heapq.heappush(pq, (0.0, s_))
    goal = ("p", dst)
    while pq:
        dv, u = heapq.heappop(pq)
        if dv > dist.get(u, 1e18):
            continue
        if u == goal:
            break
        for v, w, tag in adj.get(u, []):
            if dv + w < dist.get(v, 1e18):
                dist[v] = dv + w
                prev[v] = (u, tag)
                heapq.heappush(pq, (dv + w, v))
    if goal not in dist:
        return None, [], attach
    segs = []                            # (track, segment, f0, f1) on the path
    u = goal
    while u in prev:
        v, tag = prev[u]
        if tag and tag[3] - tag[2] > 1e-6:
            segs.append(tag)
        u = v
    return dist[goal], segs, attach


def tune(b, net, segs, attach, need):
    """add up to need (mm) to net with rectangular bumps on one segment of its
    path; returns the length added (0 if no segment had room)."""
    own = {b.nid(net)}
    cands = []
    for ti, k, g0, g1 in segs:
        t = b.tracks[ti]
        a, c = t["pts"][k], t["pts"][k + 1]
        l = math.dist(a, c)
        if (g1 - g0) * l < 2 * TUNE_P:
            continue
        # forbidden: 0.5 mm at the vertices, around every joint on this segment and
        # the part the path does not run along
        cuts = [(-1.0, max(0.5, g0 * l)), (min(l - 0.5, g1 * l), l + 1.0)]
        for m, tt in attach.get(ti, []):
            if m == k:
                cuts.append((tt * l - 0.6, tt * l + 0.6))
        for vx, vy, vn in b.vias:
            if vn == net:
                dd, tt = seg_point((vx, vy), a, c)
                if dd < VIA_D:
                    cuts.append((tt * l - 0.6, tt * l + 0.6))
        cuts.sort()
        free, x = [], 0.0
        for c0, c1 in cuts:
            if c0 > x:
                free.append((x, c0))
            x = max(x, c1)
        for f0, f1 in free:
            if f1 - f0 >= TUNE_P * 1.5:
                cands.append((f1 - f0, ti, k, f0, f1))
    cands.sort(reverse=True)
    for _, ti, k, f0, f1 in cands:
        t = b.tracks[ti]
        w, L = t["w"], t["L"]
        bl = b.blocked(own, w / 2 + CLR)[L]
        a, c = t["pts"][k], t["pts"][k + 1]
        l = math.dist(a, c)
        ux, uy = (c[0] - a[0]) / l, (c[1] - a[1]) / l
        nmax = int((f1 - f0 + TUNE_P) / (2 * TUNE_P))
        for amax in (2.5, 1.8, TUNE_AMAX, 0.8, 0.5, 0.3):
            n = min(nmax, max(1, math.ceil(need / (2 * amax))))
            A = min(amax, need / (2 * n))
            if A < TUNE_AMIN:
                n = max(1, int(need / (2 * TUNE_AMIN)))
                A = max(TUNE_AMIN, min(amax, need / (2 * n)))
            span = n * 2 * TUNE_P - TUNE_P
            s0 = f0 + (f1 - f0 - span) / 2
            for side in (1, -1):
                nx, ny = -uy * side, ux * side
                pts = []
                for m in range(n):
                    s1 = s0 + m * 2 * TUNE_P
                    for ss, hh in ((s1, 0), (s1, A), (s1 + TUNE_P, A), (s1 + TUNE_P, 0)):
                        pts.append((a[0] + ux * ss + nx * hh, a[1] + uy * ss + ny * hh))
                ok = True
                for m in range(n):          # the three new sides of each bump, from
                    q = pts[4 * m:4 * m + 4]    # 0.12 mm off the base line (which may
                    h0 = min(0.12, A)           # sit inside the partner's keep-out)
                    q = [(q[0][0] + nx * h0, q[0][1] + ny * h0), q[1], q[2],
                         (q[3][0] + nx * h0, q[3][1] + ny * h0)]
                    for p0, p1 in zip(q, q[1:]):
                        mask, box = rast_capsule(p0, p1, w / 2)
                        i0, i1, j0, j1 = box
                        if np.any(bl[j0:j1, i0:i1] & mask):
                            ok = False
                            break
                    if not ok:
                        break
                if not ok:
                    continue
                set_pts(b, ti, t["pts"][:k + 1] + pts + t["pts"][k + 1:])
                n_ = b.nid(net)
                for p0, p1 in zip(pts, pts[1:]):
                    mask, box = rast_capsule(p0, p1, w / 2)
                    b.paint(L, mask, box, n_)
                return 2 * A * n
    return 0.0


def match_lengths(b, b_pairs, rep):
    """measure and tune the intra-pair skew; one report line per pair."""
    for base in b_pairs:
        if base not in MATCH:
            continue
        pn, nn = pair_nets(b, base)
        c = trim_dangling(b, (pn, nn))
        if c > 0.05:
            rep.append("%s: %.1f mm of dangling track trimmed" % (base, c))
        src, ep, en = MATCH[base]
        before = None
        for it in range(8):
            lp, sp, ap = path_len(b, pn, src, ep)
            ln, sn, an = path_len(b, nn, src, en)
            if lp is None or ln is None:
                rep.append("%s: length not measurable (path %s-%s / %s-%s)" % (
                    base, src, ep, src, en))
                break
            if before is None:
                before = lp - ln
            sk = lp - ln
            if abs(sk) <= SKEW_TOL:
                break
            if sk < 0:
                added = tune(b, pn, sp, ap, -sk)
            else:
                added = tune(b, nn, sn, an, sk)
            if added <= 0:
                break
        else:
            lp, _, _ = path_len(b, pn, src, ep)
            ln, _, _ = path_len(b, nn, src, en)
        if lp is not None and ln is not None:
            rep.append("%s skew %s->%s / %s: P %.2f mm, N %.2f mm, skew %+.2f mm "
                       "(untuned %+.2f)%s" % (base, src, ep, en, lp, ln, lp - ln, before,
                                              "" if abs(lp - ln) <= SKEW_TOL else "  OVER"))


# --------------------------------------------------------------------------- main
def pair_nets(b, base):
    for sp, sn in (("_P_F", "_N_F"), ("_P", "_N")):
        if base + sp in b.netpads and base + sn in b.netpads:
            return base + sp, base + sn
    raise KeyError(base)


def route_all(doc, order):
    """one routing pass on a fresh copy of the placed board, pairs in this order."""
    d = dict(doc)
    d["shape"] = list(doc["shape"])
    b = Board(d)
    r = Router(b)
    rep = r.report
    ok = usb(r)
    rep.append("USB DP / DM corridor: %s" % ("routed" if ok else "INCOMPLETE"))
    failed, soft = [], []
    for base in order:
        n0 = len(rep)
        pn, nn = pair_nets(b, base)
        pp = {p["ref"]: p for p in b.netpads[pn]}
        npd = {p["ref"]: p for p in b.netpads[nn]}
        j1p, j1n = pp.get("J1"), npd.get("J1")
        if j1p:                          # launch next to J1, east of its pad field
            s = (157.4, (j1p["y"] + j1n["y"]) / 2)
            far = [(p, q) for p in b.netpads[pn] for q in b.netpads[nn]
                   if p["ref"] != "J1" and q["ref"] != "J1"]
            dest = min(far, key=lambda pq: math.hypot(pq[0]["x"] - s[0], pq[0]["y"] - s[1]) +
                       math.hypot(pq[1]["x"] - s[0], pq[1]["y"] - s[1]))
            e = ((dest[0]["x"] + dest[1]["x"]) / 2, (dest[0]["y"] + dest[1]["y"]) / 2)
            layers = (2, 0, 1)
            src = "J1"
        else:                            # on-board pair: driver -> farthest receiver group
            drv = [p for p in b.netpads[pn] if p["ref"].startswith("U")][0]
            drvn = [p for p in b.netpads[nn] if p["ref"] == drv["ref"]][0]
            s = ((drv["x"] + drvn["x"]) / 2, (drv["y"] + drvn["y"]) / 2)
            far = max(b.netpads[pn], key=lambda p: math.hypot(p["x"] - s[0], p["y"] - s[1]))
            farn = min((q for q in b.netpads[nn] if q["ref"] != drv["ref"]),
                       key=lambda q: math.hypot(q["x"] - far["x"], q["y"] - far["y"]))
            e = ((far["x"] + farn["x"]) / 2, (far["y"] + farn["y"]) / 2)
            layers = (2, 1, 0)
            src = drv["ref"]
        L = r.pair(base, pn, nn, s, e, layers)
        if L is None:
            rep.append("%s: coupled route FAILED, routing P / N single-ended" % base)
        f1 = r.finish(pn, src)
        f2 = r.finish(nn, src)
        rep.append("%s (%s / %s): %s, coupled on %s" % (
            base, pn, nn, "routed" if f1 and f2 else "INCOMPLETE",
            LNAME[L]))
        if any("UNROUTED" in x or "FAILED" in x for x in rep[n0:]):
            failed.append(base)
        elif L != 2:
            soft.append(base)            # complete, but not on Inner2
    return d, b, rep, failed, soft


def main():
    doc = json.load(open(PCB))
    order = list(PAIRS)
    best = None
    for attempt in range(8):         # rip-up and retry: failed / outer-layer pairs go first
        d, b, rep, failed, soft = route_all(doc, order)
        print("pass %d: %s%s" % (attempt + 1, "complete" if not failed else
                                  "incomplete: " + " ".join(failed),
                                  "; not on Inner2: " + " ".join(soft) if soft else ""),
              flush=True)
        if best is None or (len(failed), len(soft)) < (len(best[3]), len(best[4])):
            best = (d, b, rep, failed, soft)
        if not failed and not soft:
            break
        bad = failed + soft
        order = bad + [x for x in order if x not in bad]
    d, b, rep, failed, soft = best
    match_lengths(b, PAIRS, rep)
    d["shape"] = d["shape"] + b.new
    with open(PCB, "w") as f:
        json.dump(d, f, ensure_ascii=False)
    nt = sum(1 for s in b.new if s.startswith("TRACK"))
    nv = sum(1 for s in b.new if s.startswith("VIA"))
    rep.append("tracks %d, vias %d" % (nt, nv))
    with open(os.path.join(HERE, "route_report.txt"), "w") as f:
        f.write("\n".join(rep) + "\n")
    print("\n".join(x for x in rep if not x.startswith("UNROUTED") or failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
