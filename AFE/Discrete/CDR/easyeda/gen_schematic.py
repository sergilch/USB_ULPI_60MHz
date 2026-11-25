#!/usr/bin/env python3
"""gen_schematic.py - EasyEDA Std schematic of the discrete USB 2.0 CDR board

    python3 gen_schematic.py   -> usb_cdr_board_sch.json  (EasyEDA Std project source, 4 sheets)
                                  netlist.csv             (ref, pin, pin name, net, sheet)
                                  ../bom/cdr_board_bom.csv, ../bom/cdr_board_bom_jlcpcb.csv

Parts and connectivity: cdr_parts.py.  Symbols and footprints: JLCEDA/EasyEDA
Official Library (https://lceda.cn/, https://easyeda.com), cached in
lib/<LCSC>.json from the EasyEDA API (api/products/<LCSC>/components).  The
copyright of the library data belongs to JLCEDA/EasyEDA; every sheet carries
this source note.  Same engine as AFE/Discrete/Receiver/easyeda/gen_schematic.py
(every part unrotated, each connected pin gets a short wire stub and a net
label, one sheet per function); additions here: IC pins may be given by name
(resolved against the symbol, must be unique), and PIN_FIX corrects library
symbol pin numbers (none needed on this board; the NB6L14 C897855 symbol
numbers its exposed pad 17).  Pairs of pins tied together (e.g. the swapped
CLK1 legs of the first MC100EP29) are separate stubs on the same net labels.

Open in EasyEDA Std (desktop or web): new schematic > Design > "File Source"
(toolbar "<>" icon) > replace the text > "Create New Document".
"""
import csv
import json
import os
import re

from cdr_parts import DNP, GROUPS, NETS, PARTS, S1, S2, S3, S4, TITLES

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "lib")
BOMDIR = os.path.join(HERE, "..", "bom")
SOURCE_NOTE = ("Symbols / footprints: JLCEDA/EasyEDA Official Library - "
               "https://lceda.cn/ - https://easyeda.com")
# (LCSC, pin number, pin name) -> corrected pin number
PIN_FIX = {}


# ---------------------------------------------------------------------------
# EasyEDA Std shape handling
# ---------------------------------------------------------------------------
_id = [0]
_cache = {}


def gid():
    _id[0] += 1
    return "gpl%05d" % _id[0]


def load(lcsc):
    if lcsc not in _cache:
        with open(os.path.join(LIB, lcsc + ".json")) as f:
            r = json.load(f)["result"]
        sh = r["dataStr"]["shape"]
        for i, s in enumerate(sh):
            if s.startswith("P~"):
                seg = s.split("^^")
                f0 = seg[0].split("~")
                key = (lcsc, f0[3], seg[3].split("~")[4])
                if key in PIN_FIX:
                    f0[3] = PIN_FIX[key]
                    seg[0] = "~".join(f0)
                    sh[i] = "^^".join(seg)
        _cache[lcsc] = r
    return _cache[lcsc]


NARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "A": 7, "C": 6, "Q": 4, "S": 4, "T": 2}


def tpath(d, dx, dy):
    """translate an SVG path: absolute commands moved, relative ones unchanged"""
    toks = re.findall(r"[A-Za-z]|-?\d*\.?\d+(?:e-?\d+)?", d)
    out, i, cmd = [], 0, None
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            out.append(t)
            i += 1
            continue
        n = NARGS.get(cmd)
        if n is None:
            out.append(t)
            i += 1
            continue
        v = [float(x) for x in toks[i:i + n]]
        if cmd == "H":
            v[0] += dx
        elif cmd == "V":
            v[0] += dy
        elif cmd == "A":
            v[5] += dx
            v[6] += dy
        else:
            for k in range(0, n, 2):
                v[k] += dx
                v[k + 1] += dy
        out += ["%g" % x for x in v]
        i += n
    return " ".join(out)


def fx(v, d):
    return "%g" % (float(v) + d) if v not in ("", None) else v


def tshape(s, dx, dy):
    kind = s.split("~", 1)[0]
    if kind == "P":
        seg = s.split("^^")
        f = seg[0].split("~"); f[4] = fx(f[4], dx); f[5] = fx(f[5], dy); f[7] = gid()
        seg[0] = "~".join(f)
        f = seg[1].split("~"); f[0] = fx(f[0], dx); f[1] = fx(f[1], dy); seg[1] = "~".join(f)
        f = seg[2].split("~"); f[0] = tpath(f[0], dx, dy); seg[2] = "~".join(f)
        for k in (3, 4, 5):
            f = seg[k].split("~"); f[1] = fx(f[1], dx); f[2] = fx(f[2], dy); seg[k] = "~".join(f)
        if len(seg) > 6:
            f = seg[6].split("~"); f[1] = tpath(f[1], dx, dy); seg[6] = "~".join(f)
        return "^^".join(seg)
    f = s.split("~")
    if kind in ("PL", "PG"):
        p = [float(x) for x in f[1].split()]
        f[1] = " ".join("%g" % (v + (dx if k % 2 == 0 else dy)) for k, v in enumerate(p))
        f[6] = gid()
    elif kind == "R":
        f[1] = fx(f[1], dx); f[2] = fx(f[2], dy); f[11] = gid()
    elif kind == "E":
        f[1] = fx(f[1], dx); f[2] = fx(f[2], dy); f[9] = gid()
    elif kind in ("A", "PT"):
        f[1] = tpath(f[1], dx, dy); f[7] = gid()
    else:
        raise ValueError("unhandled shape " + kind)
    return "~".join(f)


def sym_info(lcsc):
    """pins {num: (name, x, y, outward dx, dy)} and body bbox, library coordinates"""
    r = load(lcsc)
    pins, xs, ys = {}, [], []
    for s in r["dataStr"]["shape"]:
        if s.startswith("P~"):
            seg = s.split("^^")
            f = seg[0].split("~")
            num, x, y = f[3], float(f[4]), float(f[5])
            m = re.match(r"M\s*-?[\d.]+[\s,]+-?[\d.]+\s*([hv])\s*(-?[\d.]+)", seg[2].split("~")[0])
            body = float(m.group(2))
            o = (-1 if body > 0 else 1, 0) if m.group(1) == "h" else (0, -1 if body > 0 else 1)
            pins[num] = (seg[3].split("~")[4], x, y, o[0], o[1])
            xs.append(x); ys.append(y)
        elif s.startswith(("PL~", "PG~")):
            p = [float(v) for v in s.split("~")[1].split()]
            xs += p[0::2]; ys += p[1::2]
        elif s.startswith("R~"):
            f = s.split("~")
            xs += [float(f[1]), float(f[1]) + float(f[5])]
            ys += [float(f[2]), float(f[2]) + float(f[6])]
    return r, pins, (min(xs), min(ys), max(xs), max(ys))


def place(ref, X, Y):
    """LIB shape of part ref with its library origin at (X, Y); absolute pin data"""
    p = PARTS[ref]
    r, pins, bb = sym_info(p["sym"])
    h = r["dataStr"]["head"]
    dx, dy = X - float(h["x"]), Y - float(h["y"])
    cp = dict(h["c_para"])
    pre = re.sub(r"\?$", "", cp.pop("pre", "U?"))
    cp.pop("name", None)
    for k in ("JLCPCB Part Class", "Contributor", "spiceSymbolName"):
        cp.pop(k, None)
    cp.update({"Manufacturer Part": p["mpn"], "Manufacturer": p["mfr"],
               "Supplier": "LCSC" if p["lcsc"] else "Mouser/Samtec",
               "Supplier Part": p["lcsc"], "Value": p["value"], "spicePre": pre[:1]})
    if p["note"]:
        cp["Note"] = p["note"]
    if ref in DNP:
        cp["DNP"] = "yes"
    para = "`".join("%s`%s" % (k, str(v).replace("`", "'").replace("~", "-")) for k, v in cp.items())
    pkg = r.get("packageDetail") or {}
    head = "LIB~%g~%g~%s~~0~%s~%s~%s~0~~yes~yes~%s~%s~%s" % (
        X, Y, para, gid(), h.get("puuid", ""), r.get("uuid", ""), r.get("datastrid", ""),
        r.get("updateTime", ""), pkg.get("datastrid", ""))
    x0, y0 = bb[0] + dx, bb[1] + dy
    sub = ["T~P~%g~%g~0~#000080~Arial~~~~~comment~%s~1~start~%s~0~" % (x0, y0 - 11, ref, gid()),
           "T~N~%g~%g~0~#000080~Arial~~~~~comment~%s~1~start~%s~0~" % (
               x0, y0 - 3, p["value"] + (" DNP" if ref in DNP else ""), gid())]
    sub += [tshape(s, dx, dy) for s in r["dataStr"]["shape"]]
    apins = {n: (nm, x + dx, y + dy, ox, oy) for n, (nm, x, y, ox, oy) in pins.items()}
    return head + "#@$" + "#@$".join(sub), apins


STUB = 10
CH = 4.4        # approx. net label character width (7pt)


def label_len(net):
    return STUB + 4 + CH * len(net)


def connect(apins, nets):
    out = []
    for num, net in nets.items():
        nm, x, y, ox, oy = apins[num]
        x2, y2 = x + ox * STUB, y + oy * STUB
        out.append("W~%g %g %g %g~#008800~1~0~none~%s~0" % (x, y, x2, y2, gid()))
        if oy == 0:
            anchor = "start" if ox > 0 else "end"
            rot, tx, ty = 0, x2 + 2 * ox, y2 - 2
        else:
            anchor = "start" if oy < 0 else "end"
            rot, tx, ty = 90 if oy < 0 else 90, x2 - 2, y2 + 2 * oy
        out.append("N~%g~%g~%d~#0000FF~%s~%s~%s~%g~%g~Times New Roman~7pt~0" % (
            x2, y2, rot, net, gid(), anchor, tx, ty))
    return out


def extent(ref):
    """bbox relative to the library origin, including stubs, labels and texts"""
    r, pins, bb = sym_info(PARTS[ref]["sym"])
    h = r["dataStr"]["head"]
    hx, hy = float(h["x"]), float(h["y"])
    x0, y0, x1, y1 = bb[0] - hx, bb[1] - hy - 16, bb[2] - hx, bb[3] - hy
    x1 = max(x1, x0 + CH * len(PARTS[ref]["value"]) + 6)
    for num, net in NETS.get(ref, {}).items():
        _, x, y, ox, oy = pins[num]
        L = label_len(net)
        x, y = x - hx, y - hy
        x0, x1 = min(x0, x + min(ox, 0) * L), max(x1, x + max(ox, 0) * L)
        y0, y1 = min(y0, y + min(oy, 0) * L), max(y1, y + max(oy, 0) * L)
    return x0, y0, x1, y1


# ---------------------------------------------------------------------------
# sheets

def frame(w, h, title, no, n):
    s = ["R~0~%g~0~0~%g~%g~#880000~1~0~none~%s~0~" % (-h, w, h, gid()),
         "R~10~%g~0~0~%g~%g~#880000~1~0~none~%s~0~" % (-h + 10, w - 20, h - 20, gid())]
    bx, by = w - 520, -80
    s.append("R~%g~%g~0~0~510~70~#880000~1~0~none~%s~0~" % (bx, by, gid()))
    for x, y, t in [(bx + 8, by + 18, "USB 2.0 discrete CDR board (afe_cdr) - FMC LPC"),
                    (bx + 8, by + 36, "Sheet %d/%d: %s" % (no, n, title[:80])),
                    (bx + 8, by + 54, "Rev 0.1 - easyeda/gen_schematic.py - " + SOURCE_NOTE)]:
        s.append("T~L~%g~%g~0~#000080~Arial~~~~~comment~%s~1~start~%s~0~" % (x, y, t, gid()))
    return s




def resolve_pins():
    """IC pins given by name -> symbol pin numbers (names must be unique)"""
    err = []
    for ref, pins in NETS.items():
        if ref not in PARTS:
            continue
        _, sp, _ = sym_info(PARTS[ref]["sym"])
        byname = {}
        for num, (nm, *_r) in sp.items():
            byname.setdefault(nm, []).append(num)
        out = {}
        for k, net in pins.items():
            if k in sp:
                out[k] = net
            elif len(byname.get(k, [])) == 1:
                out[byname[k][0]] = net
            else:
                err.append("%s: pin %r not found or not unique" % (ref, k))
                out[k] = net
        NETS[ref] = out
    return err


def flow(order, width, x=0.0, y=0.0, gap=25):
    """row-wise flow layout of parts; positions of the library origins, size"""
    x0f, cx, cy, row_h, pos, wmax = x, x, y, 0.0, [], 0.0
    for ref in order:
        ex0, ey0, ex1, ey1 = extent(ref)
        w, hgt = ex1 - ex0 + gap, ey1 - ey0 + 15
        if cx + w > x0f + width and cx > x0f:
            cx, cy, row_h = x0f, cy + row_h, 0.0
        pos.append((ref, cx - ex0, cy - ey0))
        cx += w
        wmax = max(wmax, cx - x0f)
        row_h = max(row_h, hgt)
    return pos, wmax, cy + row_h - y


def refkey(k):
    return re.sub(r"\d", "", k), int(re.sub(r"\D", "", k))


def sheet_doc(sheet, no, n):
    W = 1500
    groups = GROUPS[sheet]
    placed = [r for _, g in groups for r in g]
    missing = [k for k, v in PARTS.items() if v["sheet"] == sheet and k not in placed]
    if missing:
        groups = groups + [("other", missing)]
    shapes, parts = [], []
    gx, gy, row_h = 30.0, 30.0, 0.0
    for cap, refs in groups:
        gw = max(min(W - 60, 720), 300)
        pos, w, h = flow(refs, gw - 20)
        w, h = max(w, CH * len(cap) * 1.1 + 10, 120), h + 30
        if gx + w + 20 > W - 30 and gx > 30:
            gx, gy, row_h = 30.0, gy + row_h + 20, 0.0
        shapes.append(("box", gx, gy, w + 20, h, cap))
        parts += [(ref, gx + 10 + px, gy + 25 + py) for ref, px, py in pos]
        gx += w + 40
        row_h = max(row_h, h)
    H = max(gy + row_h + 120, 700)
    out = frame(W, H, TITLES[sheet], no, n)
    for _, x, y, w, h, cap in shapes:
        out.append("R~%g~%g~0~0~%g~%g~#808080~1~1~none~%s~0~" % (x, y - H, w, h, gid()))
        out.append("T~L~%g~%g~0~#404040~Arial~8pt~~bold~~comment~%s~1~start~%s~0~" % (
            x + 6, y - H + 14, cap, gid()))
    for ref, X, Y in parts:
        lib, apins = place(ref, X, Y - H)
        out.append(lib)
        out += connect(apins, NETS.get(ref, {}))
    return {"docType": "1", "title": sheet, "description": TITLES[sheet],
            "dataStr": {"head": {"docType": "1", "editorVersion": "6.5.61", "newgId": True,
                                 "c_para": {"Prefix Start": "1"}, "c_spiceCmd": None},
                        "canvas": "CA~%d~%d~#FFFFFF~yes~#CCCCCC~5~1000~1000~line~5~pixel~5~0~0"
                                  % (W + 200, H + 200),
                        "shape": out}}


def check():
    err, count = [], {}
    for ref, pins in NETS.items():
        if ref not in PARTS:
            err.append("%s: connections but no part" % ref)
            continue
        _, sp, _ = sym_info(PARTS[ref]["sym"])
        for num, net in pins.items():
            if num not in sp:
                err.append("%s: no pin %s" % (ref, num))
            count[net] = count.get(net, 0) + 1
    err += ["%s: no connections" % ref for ref in PARTS if ref not in NETS]
    return err, sorted(n for n, k in count.items() if k < 2), count


def write_bom():
    os.makedirs(BOMDIR, exist_ok=True)
    groups = {}
    for ref, p in PARTS.items():
        key = (p["mpn"], p["value"], p["lcsc"], ref in DNP)
        groups.setdefault(key, []).append(ref)
    rows = []
    for (mpn, val, lcsc, dnp), refs in groups.items():
        p = PARTS[refs[0]]
        fp = (load(p["sym"]).get("packageDetail") or {}).get("title", "")
        refs.sort(key=refkey)
        rows.append(dict(refs=refs, value=val, mpn=mpn, mfr=p["mfr"], lcsc=lcsc, footprint=fp,
                         dnp=dnp, note="; ".join(sorted({PARTS[k]["note"] for k in refs if PARTS[k]["note"]}))))
    rows.sort(key=lambda r: refkey(r["refs"][0]))
    with open(os.path.join(BOMDIR, "cdr_board_bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Qty", "Value", "Manufacturer", "MPN", "LCSC", "Footprint", "Fitted", "Note"])
        for r in rows:
            w.writerow([",".join(r["refs"]), len(r["refs"]), r["value"], r["mfr"], r["mpn"],
                        r["lcsc"], r["footprint"], "DNP" if r["dnp"] else "yes", r["note"]])
    with open(os.path.join(BOMDIR, "cdr_board_bom_jlcpcb.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for r in rows:
            if not r["dnp"]:
                w.writerow([r["value"], ",".join(r["refs"]), r["footprint"], r["lcsc"]])
    return rows


def main():
    rerr = resolve_pins()
    err, single, count = check()
    err = rerr + err
    for e in err:
        print("ERROR", e)
    if single:
        print("single-pin nets (inputs / test points):", " ".join(single))
    sheets = [S1, S2, S3, S4]
    proj = {"editorVersion": "6.5.61", "docType": "5", "title": "USB2 CDR board",
            "description": "Discrete USB 2.0 CDR (afe_cdr) on FMC LPC",
            "colors": {}, "schematics": [sheet_doc(s, i + 1, len(sheets)) for i, s in enumerate(sheets)]}
    with open(os.path.join(HERE, "usb_cdr_board_sch.json"), "w") as f:
        json.dump(proj, f, ensure_ascii=False, indent=1)
    with open(os.path.join(HERE, "netlist.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ref", "pin", "pin_name", "net", "sheet"])
        for ref in sorted(NETS, key=refkey):
            _, sp, _ = sym_info(PARTS[ref]["sym"])
            for num, net in sorted(NETS[ref].items()):
                w.writerow([ref, num, sp[num][0], net, PARTS[ref]["sheet"]])
    rows = write_bom()
    print("parts %d, BOM lines %d, nets %d, errors %d" % (len(PARTS), len(rows), len(count), len(err)))
    return 1 if err else 0


if __name__ == "__main__":
    raise SystemExit(main())
