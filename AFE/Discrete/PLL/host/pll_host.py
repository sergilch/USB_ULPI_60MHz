#!/usr/bin/env python3
"""pll_host.py - PC side of the PLL-board FPGA (fpga/rtl/pll_ctrl.v), pyserial

    python3 pll_host.py PORT status
    python3 pll_host.py PORT set [--pll-en 0|1] [--refsel 0..3] [--real26] [--refsrc 0..2]
                                 [--open-loop 0|1] [--dac CODE] [--muxsel M]
    python3 pll_host.py PORT lock [-n 20] [--off-us 100]      PLL_EN 0 -> 1, T_LOCK / T_DLD
    python3 pll_host.py PORT sweep [--step 50] [-o vco.csv]   open-loop f(VTUNE)
    python3 pll_host.py PORT lolclr

UART 8N1, 921600 Bd: write 57h addr data; read 52h addr -> data (doc section 8).
f_bit = 8 x FCNT x f_ref / 2^14 (FCNT counts CLK60_A over 2^14 REF_DIG cycles).
"""
import argparse
import sys
import time

REFSRC_HZ = {0: 24.0e6, 1: 19.2e6, 2: 26.0e6, 3: 26.0e6}   # SMA: the frequency you feed (--fext)


class Pll:
    def __init__(self, port, baud=921600):
        import serial  # pyserial
        self.s = serial.Serial(port, baud, timeout=0.5)

    def wr(self, a, d):
        self.s.write(bytes([0x57, a & 0xFF, d & 0xFF]))

    def rd(self, a):
        self.s.write(bytes([0x52, a & 0xFF]))
        b = self.s.read(1)
        if len(b) != 1:
            raise IOError("no reply for register %02Xh" % a)
        return b[0]

    def rdn(self, a, n):
        return sum(self.rd(a + k) << (8 * k) for k in range(n))   # low byte first: latched

    def status(self):
        st = self.rd(0x0C)
        return dict(mmcm=st & 1, pll_lock=st >> 1 & 1, lol=st >> 2 & 1, refsel_err=st >> 3 & 1,
                    muxout=st >> 4 & 1, adf_busy=st >> 5 & 1, ph_valid=st >> 6 & 1,
                    clk_alive=st >> 7 & 1)


def f_bit(fcnt, fref):
    return 8.0 * fcnt * fref / 16384.0


def cmd_status(p, a):
    ctrl, rs = p.rd(0x01), p.rd(0x02)
    fref = a.fext if (ctrl >> 2 & 3) >= 2 else REFSRC_HZ[ctrl >> 2 & 3]
    fc = p.rdn(0x0F, 3)
    adc = p.rdn(0x0D, 2)
    print("ID %02Xh  CTRL %02Xh (PLL_EN %d, OPEN_LOOP %d, REFSRC %d)  REFSEL %02Xh" %
          (p.rd(0), ctrl, ctrl & 1, ctrl >> 1 & 1, ctrl >> 2 & 3, rs))
    print("R %d  N %d  CPI %d (ICP %.3f mA)  MUXSEL %d" %
          (p.rdn(0x04, 2), p.rdn(0x06, 2), p.rd(0x08), 0.625 * (p.rd(0x08) + 1), p.rd(0x03)))
    print("STATUS", p.status())
    print("FCNT %d -> CLK_BIT_A %.4f MHz (f_ref %.4f MHz)" % (fc, f_bit(fc, fref) / 1e6, fref / 1e6))
    print("VTUNE %.3f V (ADC %d)" % (adc * 5.02 / 4096, adc))
    print("T_LOCK %d us  T_DLD %d us  PHASE %02Xh  PH_ERR %d  FB_DIV %d" %
          (p.rdn(0x12, 2), p.rdn(0x14, 2), p.rd(0x16), p.rd(0x17), p.rd(0x18)))


def cmd_set(p, a):
    ctrl = p.rd(0x01)
    if a.pll_en is not None:
        ctrl = (ctrl & ~1) | a.pll_en
    if a.open_loop is not None:
        ctrl = (ctrl & ~2) | (a.open_loop << 1)
    if a.refsrc is not None:
        ctrl = (ctrl & ~0x0C) | (a.refsrc << 2)
    p.wr(0x01, ctrl & 0x1F)
    if a.muxsel is not None:
        p.wr(0x03, a.muxsel)
        p.wr(0x09, 0)
    if a.refsel is not None:
        p.wr(0x02, a.refsel | (0x80 if a.real26 else 0))
    if a.dac is not None:
        p.wr(0x0A, a.dac & 0xFF)
        p.wr(0x0B, a.dac >> 8)
    cmd_status(p, a)


def cmd_lock(p, a):
    ctrl = p.rd(0x01) | 1
    res = []
    for k in range(a.n):
        p.wr(0x01, ctrl & ~1)
        time.sleep(a.off_us * 1e-6 + 0.002)
        p.wr(0x01, ctrl)
        time.sleep(0.01)
        tl, td = p.rdn(0x12, 2), p.rdn(0x14, 2)
        res.append((tl, td))
        print("%3d  T_LOCK %5d us  T_DLD %5d us" % (k, tl, td))
    ok = [r for r in res if r[0] != 0xFFFF]
    if ok:
        print("T_LOCK min / max %d / %d us, T_DLD min / max %d / %d us (%d of %d locked)" %
              (min(r[0] for r in ok), max(r[0] for r in ok), min(r[1] for r in ok),
               max(r[1] for r in ok), len(ok), len(res)))


def cmd_sweep(p, a):
    ctrl = p.rd(0x01)
    fref = a.fext if (ctrl >> 2 & 3) >= 2 else REFSRC_HZ[ctrl >> 2 & 3]
    p.wr(0x01, (ctrl | 3) & 0x1F)                  # PLL_EN, OPEN_LOOP
    rows = []
    for code in range(0, 4096, a.step):
        p.wr(0x0A, code & 0xFF)
        p.wr(0x0B, code >> 8)
        time.sleep(0.003)                          # settle + > 2 FCNT windows (2 x 0.68 ms)
        fc = p.rdn(0x0F, 3)
        adc = p.rdn(0x0D, 2)
        rows.append((code / 1000.0, adc * 5.02 / 4096, f_bit(fc, fref)))
        print("DAC %.3f V  VTUNE %.3f V  f %.3f MHz" % (rows[-1][0], rows[-1][1], rows[-1][2] / 1e6))
    p.wr(0x01, ctrl & 0x1D)                        # back to closed loop
    if a.o:
        with open(a.o, "w") as f:
            f.write("v_dac,v_tune,f_hz\n")
            for r in rows:
                f.write("%.4f,%.4f,%.1f\n" % r)
    vs, fs = [r[1] for r in rows], [r[2] for r in rows]
    for i in range(1, len(rows)):
        if fs[i - 1] < 480e6 <= fs[i]:
            v480 = vs[i - 1] + (480e6 - fs[i - 1]) / (fs[i] - fs[i - 1]) * (vs[i] - vs[i - 1])
            print("480 MHz at %.3f V, Kvco %.1f MHz/V" %
                  (v480, (fs[i] - fs[i - 1]) / (vs[i] - vs[i - 1]) / 1e6))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port")
    ap.add_argument("--fext", type=float, default=26.0e6, help="SMA reference frequency (Hz)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("status")
    s = sp.add_parser("set")
    s.add_argument("--pll-en", type=int, choices=(0, 1))
    s.add_argument("--open-loop", type=int, choices=(0, 1))
    s.add_argument("--refsel", type=int, choices=range(4))
    s.add_argument("--real26", action="store_true")
    s.add_argument("--refsrc", type=int, choices=range(4))
    s.add_argument("--dac", type=int)
    s.add_argument("--muxsel", type=int)
    s = sp.add_parser("lock")
    s.add_argument("-n", type=int, default=20)
    s.add_argument("--off-us", type=float, default=100.0)
    s = sp.add_parser("sweep")
    s.add_argument("--step", type=int, default=50)
    s.add_argument("-o")
    sp.add_parser("lolclr")
    a = ap.parse_args()
    p = Pll(a.port)
    if a.cmd == "status":
        cmd_status(p, a)
    elif a.cmd == "set":
        cmd_set(p, a)
    elif a.cmd == "lock":
        cmd_lock(p, a)
    elif a.cmd == "sweep":
        cmd_sweep(p, a)
    elif a.cmd == "lolclr":
        p.wr(0x01, (p.rd(0x01) & 0x1F) | 0x20)
    return 0


if __name__ == "__main__":
    sys.exit(main())
