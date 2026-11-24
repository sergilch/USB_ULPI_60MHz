"""usbpat.py - USB 2.0 line patterns for the transmitter board (simulation and FPGA ROM)

Line convention as in the RTL: J = 1, K = 0, bit 0 of a byte sent first.
"""

# USB 2.0 section 7.1.20 Test_Packet payload (after the DATA0 PID; CRC16 appended)
TEST_PACKET = [0x00] * 9 + [0xAA] * 8 + [0xEE] * 8 + [0xFE] + [0xFF] * 11 + \
    [0x7F, 0xBF, 0xDF, 0xEF, 0xF7, 0xFB, 0xFD, 0xFC, 0x7E, 0xBF, 0xDF, 0xEF, 0xF7, 0xFB, 0xFD, 0x7E]
PID_DATA0 = 0xC3
HS_SYNC = [0x00, 0x00, 0x00, 0x80]       # 31 zeros, then a one (KJKJ...KK on the line)
FS_SYNC = [0x80]


def crc16(data):
    """USB CRC16 (x^16 + x^15 + x^2 + 1), reflected, init FFFFh, inverted."""
    c = 0xFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    c ^= 0xFFFF
    return [c & 0xFF, c >> 8]


def bits_lsb(data):
    return [(b >> i) & 1 for b in data for i in range(8)]


def stuff(bits):
    """Bit stuffing: a 0 after six consecutive 1s."""
    out, run = [], 0
    for b in bits:
        out.append(b)
        run = run + 1 if b else 0
        if run == 6:
            out.append(0)
            run = 0
    return out


def nrzi(bits, level=1):
    """NRZI: 0 = transition, 1 = no transition; starts from J (idle)."""
    out = []
    for b in bits:
        if not b:
            level ^= 1
        out.append(level)
    return out


def hs_packet_line(payload=None, pid=PID_DATA0):
    """Line levels (J=1) of one HS data packet: SYNC, PID, payload, CRC16, EOP."""
    payload = TEST_PACKET if payload is None else payload
    data = [pid] + list(payload) + crc16(payload)
    line = nrzi(stuff(bits_lsb(HS_SYNC + data)))
    # HS EOP: NRZI 01111111 without stuffing (one transition, then 7 bit times)
    lvl = line[-1] ^ 1
    return line + [lvl] * 8


if __name__ == "__main__":
    p = TEST_PACKET
    print(len(p), "payload bytes, CRC16 =", " ".join("%02X" % b for b in crc16(p)))
    print(len(hs_packet_line()), "line bits")
