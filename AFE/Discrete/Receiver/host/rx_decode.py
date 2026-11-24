#!/usr/bin/env python3
"""rx_decode.py - decodes a capture of the receiver-board FPGA (rx_fpga_top)

    python3 rx_decode.py capture.txt [--expect expected.json] [--tap-m 0 --tap-s 7]

Capture file: one 32-bit word per line in hex (rx_host.py dump / testbench),
optional '# key=value' header lines (tap_m, tap_s).  Word = {dc, sq, s, m}, each
byte 8 samples, bit 0 = oldest:
  m, s   RX_OUT through the master / slave ISERDESE2, 960 MS/s each.  The slave
         path is delayed (tap_s - tap_m) * 78.1 ps, so with tap_s > tap_m its
         sample i is older than m[i]: interleaved stream s0 m0 s1 m1 ... = 4
         samples per HS bit (1.92 GS/s, 0.52 ns).
  sq, dc SQUELCH_A, DISC_A at 960 MS/s (1.04 ns).

Decoding (per burst of RX_OUT activity):
  clock / data recovery  bit centre half a period after each edge, phase
                          (gain 1/4) and period (gain 1/64) tracking
  NRZI (J = 1), SYNC (zeros ... 1), bit unstuffing, EOP = 7 ones (HS EOP)
  PID check, CRC5 (tokens) / CRC16 (data), and squelch / disconnect timing:
    t_on  first RX_OUT edge of the burst -> SQUELCH_A falls
    t_off end of the EOP (last RX_OUT edge + 8 bits) -> SQUELCH_A rises
With --expect: exit 0 only if the expected packets are found in order, CRC ok.
"""
import argparse
import json
import sys

SAMPLE_NS = 1e3 / 1920.0         # interleaved RX_OUT sample
SQ_NS = 1e3 / 960.0
P_NOM = 4.0                      # samples per bit
PID_NAMES = {0xE1: "OUT", 0x69: "IN", 0xA5: "SOF", 0x2D: "SETUP", 0xD2: "ACK", 0x5A: "NAK",
             0x1E: "STALL", 0x96: "NYET", 0xC3: "DATA0", 0x4B: "DATA1", 0x87: "DATA2",
             0x0F: "MDATA", 0x3C: "PRE/ERR", 0x78: "SPLIT", 0xB4: "PING"}


def crc16(data):
    c = 0xFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c ^ 0xFFFF


def crc5_ok(b1, b2):
    bits = [(b1 >> i) & 1 for i in range(8)] + [(b2 >> i) & 1 for i in range(8)]
    c = 0x1F
    for b in bits:
        fb = (c ^ b) & 1
        c >>= 1
        if fb:
            c ^= 0x14
    return c == 0x06                                 # residual 01100b (reflected)


def load(path):
    words, meta = [], {}
    for ln in open(path):
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("#"):
            for kv in ln[1:].split():
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    meta[k] = v
            continue
        words.append(int(ln, 16))
    return words, meta


def streams(words, slave_first=True):
    x, sq, dc = [], [], []
    for w in words:
        m, s = w & 0xFF, (w >> 8) & 0xFF
        for i in range(8):
            a, b = (s >> i) & 1, (m >> i) & 1
            x += [a, b] if slave_first else [b, a]
            sq.append((w >> (16 + i)) & 1)
            dc.append((w >> (24 + i)) & 1)
    return x, sq, dc


def recover(x, idle_bits=12):
    """bursts of activity -> list of (first_edge_idx, last_edge_idx, line bits)"""
    edges = [k for k in range(1, len(x)) if x[k] != x[k - 1]]
    bursts, i = [], 0
    while i < len(edges):
        j = i
        while j + 1 < len(edges) and edges[j + 1] - edges[j] < idle_bits * P_NOM:
            j += 1
        grp = edges[i:j + 1]
        if len(grp) >= 8:
            bits, p = [], P_NOM
            t = grp[0] - 0.5 + p / 2                   # centre of the first bit
            bits.append(x[min(int(round(t)), len(x) - 1)])
            ei = 1
            tend = grp[-1] + 8 * p                     # EOP: 7 bits after the last edge
            while t + p < min(tend, len(x) - 1):
                tn = t + p
                while ei < len(grp) and grp[ei] - 0.5 <= tn:
                    e = grp[ei] - 0.5
                    if e > t:
                        err = e - (t + p / 2)
                        tn += err / 4
                        p += err / 64
                    ei += 1
                t = tn
                bits.append(x[min(int(round(t)), len(x) - 1)])
            bursts.append((grp[0], grp[-1], bits))
        i = j + 1
    return bursts


def decode_line(bits):
    """line levels -> packet bytes (None if no SYNC), status text"""
    d = [1 if bits[i] == bits[i - 1] else 0 for i in range(1, len(bits))]
    k, zeros = 0, 0
    while k < len(d) and not (d[k] == 1 and zeros >= 6):
        zeros = zeros + 1 if d[k] == 0 else 0
        k += 1
    if k >= len(d):
        return None, "no SYNC"
    out, run, i = [], 0, k + 1
    eop = False
    while i < len(d):
        b = d[i]
        if run == 6:
            if b == 1:
                eop = True
                break
            run = 0                                    # stuffed zero
            i += 1
            continue
        out.append(b)
        run = run + 1 if b else 0
        i += 1
    if not eop:
        return None, "no EOP"
    out = out[:-7] if len(out) >= 7 else []            # drop EOP's leading 0 + six 1s
    nb = len(out) // 8
    data = [sum(out[8 * j + i] << i for i in range(8)) for j in range(nb)]
    return data, "ok" if len(out) % 8 == 0 else "%d extra bits" % (len(out) % 8)


def check(data):
    if not data:
        return "empty"
    pid = data[0]
    if (pid & 0x0F) != (~pid >> 4) & 0x0F:
        return "PID error"
    name = PID_NAMES.get(pid, "?")
    if name in ("DATA0", "DATA1", "DATA2", "MDATA"):
        if len(data) < 3:
            return "short"
        return "CRC16 ok" if crc16(data[1:-2]) == data[-2] | (data[-1] << 8) else "CRC16 error"
    if name in ("OUT", "IN", "SOF", "SETUP", "SPLIT", "PING"):
        return "CRC5 ok" if len(data) == 3 and crc5_ok(data[1], data[2]) else "CRC5 error"
    return "ok" if len(data) == 1 else "length error"


def analyse(words, meta):
    tap_m, tap_s = int(meta.get("tap_m", 0)), int(meta.get("tap_s", 7))
    x, sq, dc = streams(words, slave_first=tap_s >= tap_m)
    res = []
    for e0, e1, bits in recover(x):
        data, st = decode_line(bits)
        t0, t1 = e0 * SAMPLE_NS, (e1 + 8 * P_NOM) * SAMPLE_NS     # t1: end of the 8-bit EOP
        # squelch: first fall at or after the burst start - 50 ns; first rise after the end
        j0 = int(t0 / SQ_NS)
        f = next((j for j in range(max(j0 - 48, 1), min(len(sq), j0 + 200))
                  if sq[j - 1] == 1 and sq[j] == 0), None)
        j1 = int(t1 / SQ_NS)
        r = next((j for j in range(j1, len(sq)) if sq[j - 1] == 0 and sq[j] == 1), None)
        dch = [j for j in range(max(j0, 1), min(len(dc), j1 + 100)) if dc[j - 1] == 0 and dc[j] == 1]
        res.append(dict(t_ns=round(t0, 2), bits=len(bits),
                        pid=PID_NAMES.get(data[0], "?") if data else None,
                        bytes=["%02X" % b for b in data] if data else None,
                        status=st if data is None else check(data) + ("" if st == "ok" else ", " + st),
                        t_on_ns=round(f * SQ_NS - t0, 2) if f is not None else None,
                        t_off_ns=round(r * SQ_NS - t1, 2) if r is not None else None,
                        disc_ns=[round(j * SQ_NS - t0, 2) for j in dch]))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("--expect")
    ap.add_argument("--tap-m", type=int)
    ap.add_argument("--tap-s", type=int)
    a = ap.parse_args()
    words, meta = load(a.capture)
    if a.tap_m is not None:
        meta["tap_m"] = a.tap_m
    if a.tap_s is not None:
        meta["tap_s"] = a.tap_s
    res = analyse(words, meta)
    for r in res:
        b = r["bytes"]
        print("%9.2f ns  %-6s %-18s %4s bytes  t_on %s ns  t_off %s ns  disc %s  %s" % (
            r["t_ns"], r["pid"], r["status"], len(b) if b else "-", r["t_on_ns"], r["t_off_ns"],
            r["disc_ns"], " ".join(b[:8]) + (" ..." if b and len(b) > 8 else "") if b else ""))
    if a.expect:
        exp = json.load(open(a.expect))
        got = [r["bytes"] for r in res if r["bytes"] and r["status"].split(",")[0].endswith("ok")]
        k = 0
        for g in got:
            if k < len(exp) and g == exp[k]:
                k += 1
        ok = k == len(exp)
        print("decoder: %d of %d expected packets found in order, CRC ok -> %s" % (
            k, len(exp), "PASS" if ok else "FAIL"))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
