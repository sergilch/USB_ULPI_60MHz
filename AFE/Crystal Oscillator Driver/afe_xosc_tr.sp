* afe_xosc_tr.sp - 24 MHz Pierce crystal oscillator driver for the USB 2.0 ULPI PHY
*
* Transistor-level schematic (ngspice / Spectre 'simulator lang=spice').
* Devices: X-FAB xh018 isolated 3.3 V MOS ne3i / pe3i (thick oxide, the only
* MOS cards of X-FAB/spice).  Run on VDD18A = 1.8 V; the thick oxide also
* tolerates a 3.3 V level on XI in bypass mode (the pad ESD clamps to the
* pad supply, see the description).  Model include: the testbench
* (sim/tb_xosc_tr.py) includes build/xosc/models/xh018_<corner>.lib made by
* sim/xfab2ngspice.py.  Resistors and capacitors are ideal elements; the
* intended xh018 device is named in the comment.
*
* Pins
*   XI        crystal / external clock input (analog pad APR00F)
*   XO        crystal drive output (analog pad APR00F)
*   XTAL_EN   1 = oscillator on (1.8 V CMOS).  0 = bias off, XI / XO pulled to
*             VSS, REF_CLK low, < 1 uA
*   DRV1 DRV0 start-up (maximum) core current: 00 250 uA, 01 375 uA,
*             10 500 uA, 11 625 uA (nominal, tm / 27 C / 1.8 V); 11 is the
*             recommended setting for crystals with ESR up to 100 Ohm
*   REF_CLK   24 MHz CMOS clock 0 / VDD to the PLL (CDR_FREF of afe_pll)
*   VDD VSS   VDD18A / VSS18A
*
* Blocks (instance prefixes)
*   B  bias: I_REF = (VDD - VGS(MB1)) / RB ~ 40 uA, mirrored into the
*      PMOS current-source bank (unit 125 uA)
*   A  Pierce amplifier: NMOS MA1 (gm stage) with the PMOS bank as its load,
*      self-biased through RF (1 MOhm) from XO to XI
*   S  squarer: AC coupling CC from XI, self-biased inverter (RSB), Schmitt
*      trigger, gated output buffer
*   L  enable logic

.subckt afe_xosc_tr XI XO XTAL_EN DRV1 DRV0 REF_CLK VDD VSS

* ---------------------------------------------------------------- logic (L)
* ENB = !XTAL_EN, D0B / D1B = segment switch gates (low = segment on)
XL1P enb XTAL_EN VDD VDD pe3i w=2u l=0.3u
XL1N enb XTAL_EN VSS VSS ne3i w=1u l=0.35u
* D0B = NAND(XTAL_EN, DRV0)
XL2P d0b DRV0 VDD VDD pe3i w=2u l=0.3u
XL3P d0b XTAL_EN VDD VDD pe3i w=2u l=0.3u
XL2N d0b DRV0 l2m VSS ne3i w=2u l=0.35u
XL3N l2m XTAL_EN VSS VSS ne3i w=2u l=0.35u
* D1B = NAND(XTAL_EN, DRV1)
XL4P d1b DRV1 VDD VDD pe3i w=2u l=0.3u
XL5P d1b XTAL_EN VDD VDD pe3i w=2u l=0.3u
XL4N d1b DRV1 l4m VSS ne3i w=2u l=0.35u
XL5N l4m XTAL_EN VSS VSS ne3i w=2u l=0.35u

* ---------------------------------------------------------------- bias (B)
* RB: high-ohmic poly (rpp1k1), 18 kOhm.  MB0 = enable switch.
XMB0 b0 enb VDD VDD pe3i w=4u l=0.3u
RB   b0 nb 18k
XMB1 nb nb VSS VSS ne3i w=8u l=2u
* unregulated PMOS bias po (I_REF): MB7 -> PMOS diode MB6
XMB7 po nb VSS VSS ne3i w=8u l=2u
XMB6 po po VDD VDD pe3i w=20u l=1u
* regulated branch: MB10 sources I_REF into the NMOS diode MB9 (node nc);
* the ALC (MR5) takes up to I_REF of it away
XMB10 nc po VDD VDD pe3i w=20u l=1u
XMB9 nc nc VSS VSS ne3i w=8u l=2u
* NMOS mirror 1:1 into the PMOS diode MB3 (2 x 10u / 1u)
XMB2 pb nc VSS VSS ne3i w=8u l=2u
XMB3 pb pb VDD VDD pe3i w=20u l=1u
* pull pb / po to VDD and nb / nc to VSS when disabled (no floating gates)
XMB4 pb XTAL_EN VDD VDD pe3i w=1u l=0.3u
XMB8 po XTAL_EN VDD VDD pe3i w=1u l=0.3u
XMB5 nb enb VSS VSS ne3i w=1u l=0.35u
XMB11 nc enb VSS VSS ne3i w=1u l=0.35u

* --------------------------------------------- amplitude regulation (R)
* Peak detector: XI is AC-coupled (CD, RD) onto vbl = vb - V_SET (divider
* RV1 / RVS / RV2, gated by MRV; vb = 0.6 VDD, V_SET = 0.1 VDD = 0.18 V);
* follower MR1 holds its peak on CPK, sink I_PK = I_REF / 16 (MR3).
* Reference: matched follower MR2 on vb, same sink (MR4).
* V(pk) - V(rf) = A_XI - V_SET - (peak conduction offset), so the loop holds
* the XI amplitude near V_SET.  Follower and pair bodies on their sources
* (isolated devices: no body effect).
* RV1, RVS, RV2, RD: rpp1k1; CD, CPK, CVB, CVBL: MIM
RV1  VDD vb 600k
RVS  vb vbl 150k
RV2  vbl rv 750k
XMRV rv XTAL_EN VSS VSS ne3i w=1u l=0.35u
CVB  vb VSS 2p
CVBL vbl VSS 2p
CD   XI dI 1p
RD   dI vbl 2meg
XMR1 VDD dI pk pk ne3i w=4u l=1u
CPK  pk VSS 8p
XMR3 pk npk VSS VSS ne3i w=8u l=2u
XMR2 VDD vb rf rf ne3i w=4u l=1u
XMR4 rf npk VSS VSS ne3i w=8u l=2u
* I_PK reference: PMOS copy of po (1 / 16) into the NMOS diode MRD
XMRP npk po VDD VDD pe3i w=1.25u l=1u
XMRD npk npk VSS VSS ne3i w=8u l=2u
XMR8 npk enb VSS VSS ne3i w=1u l=0.35u
* error amplifier: PMOS pair, tail I_REF (MRT); the current of MRB (gate
* rf) rises from 0 to I_REF as the amplitude passes V_SET; mirrored by
* MR6 / MR5 out of node nc: I_core = 12.5 x (I_REF - I(MR5)) x DRV units
XMRT rt po VDD VDD pe3i w=20u l=1u
XMRA VSS pk rt rt pe3i w=80u l=1u
XMRB nq rf rt rt pe3i w=80u l=1u
XMR6 nq nq VSS VSS ne3i w=8u l=2u
XMR5 nc nq VSS VSS ne3i w=8u l=2u
XMR7 nq enb VSS VSS ne3i w=1u l=0.35u
* gate filter of the current-source bank (MOS cap / MIM, 2 pF)
CB   pb VDD 2p

* ------------------------------------------- PMOS current-source bank (A)
* unit = 3.125 x I_REF = 125 uA: W = 62.5u / L = 1u per unit
* base: 2 units, always on when enabled (gate pb is pulled up when off)
XMC1 XO pb VDD VDD pe3i w=125u l=1u
* DRV0 segment: 1 unit, series switch MS0
XMC2 c2 pb VDD VDD pe3i w=62.5u l=1u
XMS0 XO d0b c2 VDD pe3i w=25u l=0.3u
* DRV1 segment: 2 units, series switch MS1
XMC3 c3 pb VDD VDD pe3i w=125u l=1u
XMS1 XO d1b c3 VDD pe3i w=50u l=0.3u

* ------------------------------------------------------ amplifier (A)
* MA1: 20 fingers x 10u / 0.5u
XMA1 XO XI VSS VSS ne3i w=200u l=0.5u
* RF: feedback / bias resistor 1 MOhm (rpp1k1, ~ 1000 squares; or a
* long-channel MOS pseudo-resistor)
RF   XO XI 1meg
* disable: XI to VSS (MA1 off, XO follows through RF)
XMA2 XI enb VSS VSS ne3i w=2u l=0.35u

* --------------------------------------------------------- squarer (S)
* CC: MIM (cmm4), 0.5 pF.  RSB: self-bias of INV1, 500 kOhm (rpp1k1)
CC   XI sa 0.5p
* MS1H: header, off when disabled (no crowbar current in INV1)
XS1H s1v enb VDD VDD pe3i w=12u l=0.3u
XS1P sb sa s1v VDD pe3i w=6u l=0.3u
XS1N sb sa VSS VSS ne3i w=2u l=0.35u
RSB  sb sa 500k
* Schmitt trigger (6T): input sb, output sc
XS2P1 s2p sb VDD VDD pe3i w=4u l=0.3u
XS2P2 sc sb s2p VDD pe3i w=4u l=0.3u
XS2P3 s2p sc VSS VDD pe3i w=1u l=0.3u
XS2N1 s2n sb VSS VSS ne3i w=2u l=0.35u
XS2N2 sc sb s2n VSS ne3i w=2u l=0.35u
XS2N3 s2n sc VDD VSS ne3i w=0.5u l=0.35u
* output gate: sd = NAND(sc, XTAL_EN), REF_CLK = !sd
XS3P1 sd sc VDD VDD pe3i w=4u l=0.3u
XS3P2 sd XTAL_EN VDD VDD pe3i w=4u l=0.3u
XS3N1 sd sc s3m VSS ne3i w=4u l=0.35u
XS3N2 s3m XTAL_EN VSS VSS ne3i w=4u l=0.35u
XS4P REF_CLK sd VDD VDD pe3i w=12u l=0.3u
XS4N REF_CLK sd VSS VSS ne3i w=6u l=0.35u
* hold sb (and through RSB sa) low while disabled
XS5 sb enb VSS VSS ne3i w=1u l=0.35u

.ends afe_xosc_tr
