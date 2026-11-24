#!/usr/bin/env python3
"""rx_host.py - PC side of the receiver-board FPGA (rx_fpga_top) over the
carrier's USB-UART (pyserial, 921600 Bd 8N1)

    python3 rx_host.py /dev/ttyUSB0 status
    python3 rx_host.py /dev/ttyUSB0 set --rx-en 1 --term 1 --vsq 1320 --vdisc 1210
    python3 rx_host.py /dev/ttyUSB0 capture --trig squelch --pre 256 -o cap.txt [--decode]
    python3 rx_host.py /dev/ttyUSB0 sweep-sq --from 1100 --to 1500 --step 20 --time 1

capture  arms, waits for `done`, dumps the whole buffer (2^AW words) into a
         text file for rx_decode.py (and decodes it with --decode)
sweep-sq steps the V_SQ code and counts SQUELCH_A falls per step (SQ_CNT): with a
         packet source of known amplitude (e.g. the transmitter board with TX_AMP
         trimmed), the code at which the count drops to 0 calibrates the squelch
         trip of this board (doc section 10)
Register map: fpga/rtl/rx_ctrl.v, doc/rx_board.md section 8.
"""
import argparse
import os
import sys
import time

TRIG = {"immediate": 0, "squelch": 1, "disc": 2, "edge": 3}


class Board:
    def __init__(self, port, baud=921600):
        import serial                       # pyserial
        self.s = serial.Serial(port, baud, timeout=2)

    def wr(self, a, d):
        self.s.write(bytes([0x57, a, d & 0xFF]))

    def rd(self, a):
        self.s.write(bytes([0x52, a]))
        b = self.s.read(1)
        if len(b) != 1:
            raise IOError("no reply from the FPGA (register %02Xh)" % a)
        return b[0]

    def rd16(self, a):
        lo = self.rd(a)
        return lo | (self.rd(a + 1) << 8)

    def status(self):
        st = self.rd(0x0B)
        names = ["locked", "idelay_rdy", "armed", "done", "vbus", "squelch", "disc", "dac_busy"]
        return {n: (st >> i) & 1 for i, n in enumerate(names)}

    def dac(self, vsq=None, vdisc=None):
        if vsq is not None:
            self.wr(0x07, vsq & 0xFF); self.wr(0x08, vsq >> 8)
        if vdisc is not None:
            self.wr(0x09, vdisc & 0xFF); self.wr(0x0A, vdisc >> 8)

    def capture(self, trig, pre, timeout=10.0):
        self.wr(0x03, pre & 0xFF); self.wr(0x04, pre >> 8)
        self.wr(0x02, 0x80 | TRIG[trig])
        t = time.time()
        while not self.status()["done"]:
            if time.time() - t > timeout:
                raise TimeoutError("no trigger within %.0f s" % timeout)
            time.sleep(0.01)
        n = 1 << self.rd(0x12)
        self.s.write(bytes([0x44, 0, 0, n & 0xFF, n >> 8]))
        raw = self.s.read(4 * n)
        if len(raw) != 4 * n:
            raise IOError("dump: %d of %d bytes" % (len(raw), 4 * n))
        return [int.from_bytes(raw[4 * i:4 * i + 4], "little") for i in range(n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("cmd", choices=["status", "set", "capture", "sweep-sq"])
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--rx-en", type=int)
    ap.add_argument("--term", type=int)
    ap.add_argument("--vsq", type=int)
    ap.add_argument("--vdisc", type=int)
    ap.add_argument("--tap-m", type=int)
    ap.add_argument("--tap-s", type=int)
    ap.add_argument("--trig", choices=list(TRIG), default="squelch")
    ap.add_argument("--pre", type=int, default=256)
    ap.add_argument("-o", "--out", default="capture.txt")
    ap.add_argument("--decode", action="store_true")
    ap.add_argument("--from", dest="c0", type=int, default=1100)
    ap.add_argument("--to", dest="c1", type=int, default=1500)
    ap.add_argument("--step", type=int, default=20)
    ap.add_argument("--time", type=float, default=1.0)
    a = ap.parse_args()
    b = Board(a.port, a.baud)
    if b.rd(0x00) != 0x52:
        sys.exit("unexpected ID: is rx_fpga_top loaded?")
    if a.rx_en is not None or a.term is not None:
        c = b.rd(0x01)
        if a.rx_en is not None:
            c = (c & ~1) | (a.rx_en & 1)
        if a.term is not None:
            c = (c & ~2) | ((a.term & 1) << 1)
        b.wr(0x01, c)
    if a.tap_m is not None:
        b.wr(0x05, a.tap_m)
    if a.tap_s is not None:
        b.wr(0x06, a.tap_s)
    b.dac(a.vsq, a.vdisc)
    if a.cmd == "status":
        print(b.status(), "CTRL %02Xh" % b.rd(0x01), "V_SQ %d" % b.rd16(0x07),
              "V_DISC %d" % b.rd16(0x09), "SQ_CNT %d" % b.rd16(0x0E), "DC_CNT %d" % b.rd16(0x10))
    elif a.cmd == "capture":
        w = b.capture(a.trig, a.pre)
        with open(a.out, "w") as f:
            f.write("# tap_m=%d tap_s=%d pre=%d trig=%s\n" % (b.rd(0x05), b.rd(0x06), a.pre, a.trig))
            f.write("\n".join("%08X" % x for x in w) + "\n")
        print("%d words -> %s" % (len(w), a.out))
        if a.decode:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import rx_decode
            words, meta = rx_decode.load(a.out)
            for r in rx_decode.analyse(words, meta):
                print(r)
    elif a.cmd == "sweep-sq":
        for code in range(a.c0, a.c1 + 1, a.step):
            b.dac(vsq=code)
            c0 = b.rd16(0x0E)
            time.sleep(a.time)
            n = (b.rd16(0x0E) - c0) & 0xFFFF
            print("V_SQ %4d (trip ~%.0f mV, simulated ratio 0.093)  squelch falls %d" % (code, code * 0.093, n), flush=True)


if __name__ == "__main__":
    main()
