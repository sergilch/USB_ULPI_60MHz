#!/usr/bin/env python3
"""cdr_host.py - PC side of the CDR-board FPGA (fpga/rtl/cdr_ctrl.v), pyserial

    python3 cdr_host.py PORT status
    python3 cdr_host.py PORT set [--en 0|1] [--ffset 0|1] [--dsrc sma|fpga|rx] [--csrc open|sma|dac]
                                 [--vco-off 0|1] [--va MV] [--coarse MV] [--idly TAP]
    python3 cdr_host.py PORT cal [--target 480e6] [--tol-ppm 200]   free-running f -> 480 MHz (V_A)
    python3 cdr_host.py PORT sweep {va|coarse} [--from 0] [--to 4095] [--step 100] [-o f.csv]
    python3 cdr_host.py PORT packets [--len 32] [--gap 15] [-t 2]   SYNC bits lost, packet errors
    python3 cdr_host.py PORT ber [-t 10] [--mode prbs|clock]        PRBS7 BER
    python3 cdr_host.py PORT eye [-t 0.5]                            BER per IDELAY tap (0..31)

UART 8N1, 921600 Bd: write 57h addr data; read 52h addr -> data (doc section 8).
f(CLK_RX) = 8 x FCNT x 60 MHz / 2^20 (FCNT counts CLK_RX / 8 over 2^20 system
clock cycles; the system clock's tolerance, typically +-50 ppm, adds).
"""
import argparse
import sys
import time

F_SYS = 60.0e6
FW = 20
CSRC = {"open": 0, "sma": 1, "dac": 2}


class Cdr:
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

    def wr12(self, a, v):
        v = max(0, min(4095, int(v)))
        self.wr(a, v & 0xFF)
        self.wr(a + 1, v >> 8)

    def status(self):
        st = self.rd(0x0A)
        return dict(mmcm=st & 1, rx_alive=st >> 1 & 1, idelay_rdy=st >> 2 & 1, prbs_sync=st >> 3 & 1,
                    tx_busy=st >> 4 & 1, snap_ok=st >> 5 & 1)

    def freq(self, wait=True):
        if wait:
            time.sleep(2.2 * (1 << FW) / F_SYS)       # two FCNT gates
        return 8.0 * self.rdn(0x0D, 3) * F_SYS / (1 << FW)

    def clear(self):
        self.wr(0x01, self.rd(0x01) | 0x80)

    def counters(self):
        time.sleep(0.01)                               # > one snapshot period
        return dict(txpkt=self.rdn(0x10, 3), rxpkt=self.rdn(0x13, 3), rxok=self.rdn(0x16, 3),
                    losts=self.rdn(0x19, 3), lostmax=self.rd(0x1C), lostmin=self.rd(0x1D),
                    pbits=self.rdn(0x1E, 4), perr=self.rdn(0x22, 4))


def cmd_status(c, a):
    ctrl = c.rd(0x01)
    print("ID %02Xh  CTRL %02Xh (CDR_EN %d, FF_SET %d, DSRC %s, CSRC %d, VCO_OFF %d)" %
          (c.rd(0), ctrl, ctrl & 1, ctrl >> 1 & 1, "fpga" if ctrl >> 2 & 1 else "sma", ctrl >> 3 & 3,
           ctrl >> 5 & 1))
    print("TXMODE %d  TXLEN %d  TXGAP %d  IDLY %d" % (c.rd(0x02), c.rd(0x03), c.rd(0x04), c.rd(0x05)))
    print("DAC A (V_A) %d mV  DAC B (coarse) %d mV" % (c.rdn(0x06, 2), c.rdn(0x08, 2)))
    print("STATUS", c.status())
    f = c.freq(wait=False)
    print("CLK_RX %.4f MHz (%+.0f ppm)" % (f / 1e6, 1e6 * (f / 480e6 - 1)))
    adc = c.rdn(0x0B, 2)
    print("CDR_CH_OUT %.3f V (ADC %d)" % (adc * 5.02 / 4096, adc))
    print("counters", c.counters())


def cmd_set(c, a):
    ctrl = c.rd(0x01) & 0x7F
    if a.en is not None:
        ctrl = (ctrl & ~1) | a.en
    if a.ffset is not None:
        ctrl = (ctrl & ~2) | (a.ffset << 1)
    if a.dsrc is not None:
        # rx: EP57 D2 = the RX block's line copy, all-in-one board only (CTRL[6];
        # on the CDR board CTRL[6] is the LED bit)
        ctrl = (ctrl & ~0x44) | ((a.dsrc == "fpga") << 2) | ((a.dsrc == "rx") << 6)
    if a.csrc is not None:
        ctrl = (ctrl & ~0x18) | (CSRC[a.csrc] << 3)
    if a.vco_off is not None:
        ctrl = (ctrl & ~0x20) | (a.vco_off << 5)
    c.wr(0x01, ctrl)
    if a.va is not None:
        c.wr12(0x06, a.va)
    if a.coarse is not None:
        c.wr12(0x08, a.coarse)
    if a.idly is not None:
        c.wr(0x05, a.idly)
    cmd_status(c, a)


def cmd_cal(c, a):
    """free-running CLK_RX (idle line: no transitions, no pump) to the target by V_A
    (fine varactor anode: higher V_A = more capacitance = lower f).  Secant search."""
    c.wr(0x02, 0)                                     # TXMODE idle
    c.wr(0x01, (c.rd(0x01) & 0x7E) | 1)               # CDR_EN
    va = c.rdn(0x06, 2)
    pts = []
    for _ in range(12):
        c.wr12(0x06, va)
        f = c.freq()
        pts.append((va, f))
        print("V_A %4d mV: %.4f MHz (%+.0f ppm)" % (va, f / 1e6, 1e6 * (f / a.target - 1)))
        if abs(f / a.target - 1) * 1e6 < a.tol_ppm:
            print("calibrated: V_A = %d mV" % va)
            return 0
        if len(pts) >= 2 and pts[-1][1] != pts[-2][1]:
            (v1, f1), (v2, f2) = pts[-2], pts[-1]
            va = int(round(v2 + (a.target - f2) * (v2 - v1) / (f2 - f1)))
        else:
            va += 200 if f > a.target else -200
        if not 0 <= va <= 4095:
            print("V_A out of range: trim the coarse input (DAC B / CDR_V_IN_2) first")
            return 1
    print("no convergence")
    return 1


def cmd_sweep(c, a):
    c.wr(0x02, 0)
    c.wr(0x01, (c.rd(0x01) & 0x7E) | 1)
    reg = 0x06 if a.what == "va" else 0x08
    rows = []
    for v in range(a.start, a.stop + 1, a.step):
        c.wr12(reg, v)
        time.sleep(0.005)
        f = c.freq()
        adc = c.rdn(0x0B, 2)
        rows.append((v, f, adc * 5.02 / 4096))
        print("%s %4d mV: %.4f MHz  CDR_CH_OUT %.3f V" % (a.what, v, f / 1e6, rows[-1][2]))
    if a.o:
        with open(a.o, "w") as fo:
            fo.write("%s_mV,f_Hz,cdr_ch_out_V\n" % a.what)
            for r in rows:
                fo.write("%d,%.1f,%.4f\n" % r)


def cmd_packets(c, a):
    c.wr(0x03, a.len)
    c.wr(0x04, a.gap)
    c.wr(0x02, 1)
    time.sleep(0.05)
    c.wr(0x02, 0)
    time.sleep(0.01)
    c.clear()
    c.wr(0x02, 1)
    time.sleep(a.t)
    c.wr(0x02, 0)
    time.sleep(0.01)
    k = c.counters()
    n = max(k["rxpkt"], 1)
    print("TXPKT %d RXPKT %d (missed %d) RXOK %d (bad %d)" %
          (k["txpkt"], k["rxpkt"], k["txpkt"] - k["rxpkt"], k["rxok"], k["rxpkt"] - k["rxok"]))
    print("SYNC bits lost: mean %.2f  max %d  min %d   (USB 2.0: >= 12 SYNC bits after 5 hubs; "
          "the PHY's HS_ZMIN = 4 leaves 8 for locking)" % (k["losts"] / n, k["lostmax"], k["lostmin"]))
    return 0 if k["rxok"] == k["txpkt"] else 1


def ber(c, t):
    c.clear()
    time.sleep(t)
    k = c.counters()
    bits = 8 * k["pbits"]
    return bits, k["perr"] / 3.0                      # PRBS7 self-sync checker: 3 counts per error


def cmd_ber(c, a):
    c.wr(0x02, 2 if a.mode == "prbs" else 3)
    time.sleep(0.01)
    bits, err = ber(c, a.t)
    print("%.3g bits, %.0f errors, BER %s, prbs_sync %d" %
          (bits, err, ("%.2g" % (err / bits)) if err else "< %.2g (95 %%)" % (3.0 / bits), c.status()["prbs_sync"]))


def cmd_eye(c, a):
    c.wr(0x02, 2)
    for tap in range(32):
        c.wr(0x05, tap)
        time.sleep(0.002)
        bits, err = ber(c, a.t)
        print("IDLY %2d (%4.0f ps): BER %.2g %s" % (tap, tap * 78.125, max(err, 0.5) / bits,
                                                   "#" * min(40, int(err ** 0.25))))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("status")
    s = sp.add_parser("set")
    s.add_argument("--en", type=int, choices=(0, 1))
    s.add_argument("--ffset", type=int, choices=(0, 1))
    s.add_argument("--dsrc", choices=("sma", "fpga", "rx"))
    s.add_argument("--csrc", choices=tuple(CSRC))
    s.add_argument("--vco-off", type=int, choices=(0, 1))
    s.add_argument("--va", type=int)
    s.add_argument("--coarse", type=int)
    s.add_argument("--idly", type=int)
    s = sp.add_parser("cal")
    s.add_argument("--target", type=float, default=480e6)
    s.add_argument("--tol-ppm", type=float, default=200.0)
    s = sp.add_parser("sweep")
    s.add_argument("what", choices=("va", "coarse"))
    s.add_argument("--from", dest="start", type=int, default=0)
    s.add_argument("--to", dest="stop", type=int, default=4095)
    s.add_argument("--step", type=int, default=100)
    s.add_argument("-o")
    s = sp.add_parser("packets")
    s.add_argument("--len", type=int, default=32)
    s.add_argument("--gap", type=int, default=15)
    s.add_argument("-t", type=float, default=2.0)
    s = sp.add_parser("ber")
    s.add_argument("-t", type=float, default=10.0)
    s.add_argument("--mode", choices=("prbs", "clock"), default="prbs")
    s = sp.add_parser("eye")
    s.add_argument("-t", type=float, default=0.5)
    a = ap.parse_args()
    c = Cdr(a.port)
    fn = {"status": cmd_status, "set": cmd_set, "cal": cmd_cal, "sweep": cmd_sweep,
          "packets": cmd_packets, "ber": cmd_ber, "eye": cmd_eye}[a.cmd]
    return fn(c, a) or 0


if __name__ == "__main__":
    sys.exit(main())
