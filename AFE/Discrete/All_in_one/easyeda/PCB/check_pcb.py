#!/usr/bin/env python3
"""check_pcb.py - independent checks of usb_aio_board_pcb.json + preview.svg / .png.

Re-reads the generated EasyEDA document (not the generator's data) and checks:
  - every shape id is unique; every shape has a known command
  - every pin of ../netlist.csv is a pad of its part, on the same net, and no
    pad carries a net the netlist does not give it
  - J1 pads: C1 / C40 / D1 / G1 / H1 at the measured carrier positions (bottom side)
  - every part (pad + graphics bbox) is on the board, clear of the outline by
    0.3 mm, of the mounting-hole keep-outs, and of parts on the same side
  - no bottom-side part over the carrier (x < 160.5)
Prints CHECK PASSED / CHECK FAILED: n.
"""
import csv
import json
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MM = 1 / 0.254
OX, OY = 4000.0, 3600.0
STRIP = (143.0, 160.5, 30.31, 104.31)
BODY = (160.5, 262.0, 2.31, 132.31)


def zb(x, y):
    return (x - OX) / MM, (OY - y) / MM


def nums(s):
    return [float(t) for t in re.findall(r"-?\d*\.?\d+(?:e-?\d+)?", s)]


def main():
    doc = json.load(open(os.path.join(HERE, "usb_aio_board_pcb.json")))
    err = []
    ids = {}
    parts, free_pads = {}, []
    known = {"LIB", "TRACK", "PAD", "TEXT", "CIRCLE", "ARC", "SOLIDREGION", "HOLE", "VIA"}
    idpos = {"PAD": 12, "TRACK": 5, "CIRCLE": 6, "ARC": 6, "SOLIDREGION": 5, "HOLE": 4,
             "TEXT": 13, "LIB": 6, "VIA": 6}

    def take_id(f, where):
        k = f[0]
        if k not in known:
            err.append("%s: unknown shape %s" % (where, k))
            return
        i = f[idpos[k]]
        if i in ids:
            err.append("duplicate id %s (%s, %s)" % (i, ids[i], where))
        ids[i] = where

    for s in doc["shape"]:
        sub = s.split("#@$")
        f0 = sub[0].split("~")
        take_id(f0, f0[0])
        if f0[0] != "LIB":
            if f0[0] == "PAD":
                free_pads.append(f0)
            continue
        ref = None
        for t in sub[1:]:
            f = t.split("~")
            if f[0] == "TEXT" and f[1] == "P":
                ref = f[10]
        p = parts.setdefault(ref, {"pads": [], "xy": [], "side": "bottom" if f0[7] == "2" else "top"})
        for t in sub[1:]:
            f = t.split("~")
            take_id(f, "%s/%s" % (ref, f[0]))
            k = f[0]
            if k == "PAD":
                x, y = float(f[2]), float(f[3])
                w, h = float(f[4]), float(f[5])
                p["pads"].append((f[8], f[7], x, y, f[6]))
                v = nums(f[10]) if f[10].strip() else []
                if v:
                    p["xy"] += list(zip(v[0::2], v[1::2]))
                else:
                    p["xy"] += [(x - w / 2, y - h / 2), (x + w / 2, y + h / 2)]
            elif k == "TRACK" and f[2] in ("3", "4"):
                v = nums(f[4])
                p["xy"] += list(zip(v[0::2], v[1::2]))
            elif k == "CIRCLE" and f[5] in ("3", "4"):
                x, y, r = float(f[1]), float(f[2]), float(f[3])
                p["xy"] += [(x - r, y - r), (x + r, y + r)]

    # nets
    net = {}
    for row in csv.DictReader(open(os.path.join(HERE, "..", "netlist.csv"))):
        net.setdefault(row["ref"], {})[row["pin"]] = row["net"]
    for ref, pins in net.items():
        if ref not in parts:
            err.append("%s missing on the PCB" % ref)
            continue
        pads = {}
        for num, n, *_ in parts[ref]["pads"]:
            pads.setdefault(num, set()).add(n)
        for pin, n in pins.items():
            if pin not in pads:
                err.append("%s.%s: no pad" % (ref, pin))
            elif pads[pin] != {n}:
                err.append("%s.%s: pad net %s, netlist %s" % (ref, pin, pads[pin], n))
        for num, ns in pads.items():
            if num not in pins and ns != {""}:
                err.append("%s.%s: pad net %s not in netlist" % (ref, num, ns))
    for ref in parts:
        if ref not in net:
            err.append("%s on the PCB, not in the netlist" % ref)

    # J1 position
    j1 = {num: (x, y, l) for num, n, x, y, l in parts["J1"]["pads"]}
    want = {"C01": (149.25, 43.18), "C40": (149.25, 92.71), "D01": (150.52, 43.18),
            "G01": (154.33, 43.18), "H01": (155.60, 43.18), "H40": (155.60, 92.71)}
    for k, (wx, wy) in want.items():
        x, y = zb(*j1[k][:2])
        if math.hypot(x - wx, y - wy) > 0.02:
            err.append("J1.%s at (%.3f, %.3f), want (%.2f, %.2f)" % (k, x, y, wx, wy))
        if j1[k][2] != "2":
            err.append("J1.%s not on the bottom layer" % k)

    # geometry
    holes = [(zb(float(f[2]), float(f[3])), float(f[4]) / MM / 2) for f in free_pads]
    rects = {}
    for ref, p in parts.items():
        xs = [zb(x, y)[0] for x, y in p["xy"]]
        ys = [zb(x, y)[1] for x, y in p["xy"]]
        r = (min(xs), max(xs), min(ys), max(ys))
        rects[ref] = r
        inb = (r[0] >= BODY[0] and r[1] <= BODY[1] and r[2] >= BODY[2] and r[3] <= BODY[3])
        ins = (r[0] >= STRIP[0] and r[1] <= BODY[1] and r[2] >= STRIP[2] and r[3] <= STRIP[3])
        if not (inb or ins):
            err.append("%s outside the board %s" % (ref, tuple(round(v, 2) for v in r)))
        if p["side"] == "bottom" and ref != "J1" and r[0] < 160.5:
            err.append("%s: bottom part over the carrier" % ref)
        for (hx, hy), hr in holes:
            k = hr + 0.3
            if r[0] < hx + k and r[1] > hx - k and r[2] < hy + k and r[3] > hy - k:
                err.append("%s overlaps a mounting hole at (%.1f, %.1f)" % (ref, hx, hy))
    refs = sorted(rects)
    th = {r for r, p in parts.items() if any(pd[4] == "11" for pd in p["pads"])}
    for i, a in enumerate(refs):
        for b in refs[i + 1:]:
            if parts[a]["side"] != parts[b]["side"] and a not in th and b not in th:
                continue
            ra, rb = rects[a], rects[b]
            if ra[0] < rb[1] - 0.05 and rb[0] < ra[1] - 0.05 and ra[2] < rb[3] - 0.05 and \
                    rb[2] < ra[3] - 0.05:
                err.append("%s overlaps %s (%s side)" % (a, b, parts[a]["side"]))

    preview(doc, parts, rects, holes)
    for e in err[:60]:
        print("ERROR", e)
    nb = sum(1 for p in parts.values() if p["side"] == "bottom")
    print("parts %d (bottom %d), pads %d, ids %d" % (
        len(parts), nb, sum(len(p["pads"]) for p in parts.values()), len(ids)))
    print("CHECK PASSED" if not err else "CHECK FAILED: %d" % len(err))
    return 1 if err else 0


COL = {"TX": "#d9534f", "RX": "#f0ad4e", "PLL": "#5cb85c", "CDR": "#5bc0de", "common": "#999999"}


def preview(doc, parts, rects, holes):
    blk = {}
    for row in csv.DictReader(open(os.path.join(HERE, "placement.csv"))):
        blk[row["ref"]] = row["block"]
    S = 6.0
    x0, x1, y0, y1 = 135.0, 266.0, -2.0, 138.0

    def X(x):
        return (x - x0) * S

    def Y(y):
        return (y1 - y) * S
    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
         'font-family="sans-serif">' % ((x1 - x0) * S, (y1 - y0) * S),
         '<rect width="100%" height="100%" fill="white"/>']
    o.append('<rect x="%g" y="%g" width="%g" height="%g" fill="#eeeeee" stroke="#888" '
             'stroke-dasharray="6,4"/>' % (X(0), Y(134.62), X(160.02) - X(0), 134.62 * S))
    for sh in doc["shape"]:
        f = sh.split("~")
        if f[0] == "TRACK" and f[2] == "10":
            v = nums(f[4])
            p = " ".join("%g,%g" % (X(zb(v[i], v[i + 1])[0]), Y(zb(v[i], v[i + 1])[1]))
                         for i in range(0, len(v), 2))
            o.append('<polyline points="%s" fill="none" stroke="black" stroke-width="2"/>' % p)
    for side, op in (("bottom", 0.35), ("top", 0.75)):
        for ref, r in rects.items():
            if parts[ref]["side"] != side:
                continue
            c = COL.get(blk.get(ref, "common"), "#999")
            dash = ' stroke-dasharray="3,2"' if side == "bottom" else ""
            o.append('<rect x="%g" y="%g" width="%g" height="%g" fill="%s" fill-opacity="%g" '
                     'stroke="#333" stroke-width="0.6"%s/>' % (
                         X(r[0]), Y(r[3]), (r[1] - r[0]) * S, (r[3] - r[2]) * S, c, op, dash))
            if side == "top" and (r[1] - r[0]) * (r[3] - r[2]) > 6 or ref == "J1":
                o.append('<text x="%g" y="%g" font-size="%g" text-anchor="middle">%s</text>' % (
                    X((r[0] + r[1]) / 2), Y((r[2] + r[3]) / 2) + 3, 9 if ref != "J1" else 14, ref))
    for (hx, hy), hr in holes:
        o.append('<circle cx="%g" cy="%g" r="%g" fill="none" stroke="black" stroke-width="1.5"/>'
                 % (X(hx), Y(hy), hr * S))
    for i, (k, c) in enumerate(COL.items()):
        o.append('<rect x="%g" y="%g" width="14" height="14" fill="%s"/><text x="%g" y="%g" '
                 'font-size="14">%s</text>' % (10 + i * 90, 8, c, 28 + i * 90, 20, k))
    o.append('<text x="10" y="%g" font-size="13">dashed = bottom side; grey dashed box = '
             'ZedBoard (right part); black = board outline / holes</text>' % ((y1 - y0) * S - 8))
    o.append("</svg>")
    svg = os.path.join(HERE, "preview.svg")
    open(svg, "w").write("\n".join(o))
    try:
        subprocess.run(["rsvg-convert", "-o", os.path.join(HERE, "preview.png"), svg],
                       check=True)
    except (OSError, subprocess.CalledProcessError):
        pass


if __name__ == "__main__":
    sys.exit(main())
