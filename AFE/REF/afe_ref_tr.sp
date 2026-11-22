* afe_ref_tr.sp - reference / bias block of the analog section (AFE "REF")
*
* Transistor-level design, X-FAB xh018, isolated 3.3 V devices ne3i / pe3i and
* the p+/n-well diode dp3 (cathode on GND).  Generates the references the HS
* transceiver and receiver expect (AFE_INTEGRATION_PLAN I9 / interface spec
* Q9); description: AFE/REF/ref_description.md, datasheet:
* AFE/REF/datasheet/ref_datasheet.md.
*
*   VDD33     3.3 V analog supply (2.97-3.63 V)
*   GND       ground
*   BIAS_EN   enable from the power sequencer (bias_en), high-active,
*             absolute threshold ~0.8 V (1.8 V or 3.3 V logic)
*   TRIM3..0  reference trim code (AFE trim register), 1.8 V / 3.3 V logic;
*             1000b = nominal, 1 LSB = +0.6 % (more PTAT), monotonic
*   RBIAS     external precision resistor to GND, 12.0 kOhm 1 % (held at
*             VREF = 1.2 V: 100 uA)
*   TX_VREF   1.200 V reference for the HS transmitter (buffer, gate loads,
*             0-100 pF external; 2 pF on chip)
*   RX_VREF   1.200 V reference for the HS receiver (own buffer)
*   TX_I_5U   5 uA reference current = VREF / RBIAS / 20, sourced into the
*             load (compliance 0 .. VDD33 - 1.0 V)
*   BIAS_EN = 0: everything off (< 50 nA), TX_VREF = RX_VREF = 0 V, TX_I_5U = 0
*
* Blocks (subcircuit-internal node names in brackets)
*   bandgap   as in afe_ldo_tr: dp3 diodes 1x / 8x, PMOS mirror (5 uA units,
*             [pg]), PMOS-input op-amp with 4x larger devices (MA 40/4, MN
*             8/8: flicker noise and offset; CCB 4 pF); the PTAT resistor R2 is a string with
*             16 taps [t0..t15] (84.04 kOhm + 15 x 1.4325 kOhm): the tap
*             selects the PTAT gain, so the trim corrects the VBE spread in
*             value and temperature coefficient together
*   trim mux  binary tree of NMOS switches (no DC current) -> [vtap],
*             6 pF ripple filter (string resistance x CFL)
*   gain      two-stage amplifier A1 (PMOS input, NMOS output stage),
*             non-inverting gain 1 + RF / RG =
*             1.01133 (1.1866 V -> 1.200 V) -> [vrt]
*   buffers   B_TX / B_RX: NMOS-input single-stage OTAs as unity followers
*             (dominant pole at the output: stable for any capacitive load)
*   current   OTA A_I + NMOS source follower MNF force V(RBIAS) = [vrt];
*             the drain current goes through a wide-swing cascode PMOS mirror
*             MPI / MCI (20 units) -> MPO / MCO (1 unit) = TX_I_5U
* Resistors and capacitors are ideal here; intended devices: high-resistance
* poly (rhr) for the bandgap string, RF / RG; MIM (cmm4) for CC / CCB.

* ---------------------------------------------------------------- cells
.subckt ref_inv in out vdd vss
xp out in vdd vdd pe3i w=2u l=0.3u
xn out in vss vss ne3i w=1u l=0.35u
.ends ref_inv

* logic input with an absolute threshold (~0.8 V): NMOS against a weak PMOS
* load; gated by en (no current while disabled).  out = in (VDD33 levels)
.subckt ref_lin in out en vdd vss
xmi ib in s vss ne3i w=4u l=1u
xme s en vss vss ne3i w=4u l=1u
xml ib vss vdd vdd pe3i w=1u l=80u
xi1 ib out vdd vss ref_inv
.ends ref_lin

* 2:1 analog switch cell (NMOS, gates at VDD33 levels): y = sel ? b : a
.subckt ref_mux2 a b y sel selb vss
xa a selb y vss ne3i w=1u l=0.35u
xb b sel y vss ne3i w=1u l=0.35u
.ends ref_mux2

* NMOS-input OTA, 5T, tail from nb (mt x 2 x the 5 uA diode = mt x 10 uA):
* out rises with inp.  Off (en = 0): pull devices are in the users
.subckt ref_ota inp inn out nb vdd vss mt=1
xt tl nb vss vss ne3i w=8u l=4u m={mt}
xa m inp tl vss ne3i w=10u l=2u
xb out inn tl vss ne3i w=10u l=2u
xpa m m vdd vdd pe3i w=8u l=4u
xpb out m vdd vdd pe3i w=8u l=4u
.ends ref_ota

* ---------------------------------------------------------------- REF
.subckt afe_ref_tr VDD33 GND BIAS_EN TRIM0 TRIM1 TRIM2 TRIM3 RBIAS TX_VREF RX_VREF TX_I_5U

* ---- enable and trim inputs ------------------------------------------
xmi eib BIAS_EN GND GND ne3i w=4u l=1u
xmil eib GND VDD33 VDD33 pe3i w=1u l=40u
xi_en eib en_in VDD33 GND ref_inv
xi_enb en_in en_inb VDD33 GND ref_inv
* trim bits: tk = TRIMk (0 while disabled), tnk = !tk
xl0 TRIM0 t0b en_in VDD33 GND ref_lin
xl1 TRIM1 t1b en_in VDD33 GND ref_lin
xl2 TRIM2 t2b en_in VDD33 GND ref_lin
xl3 TRIM3 t3b en_in VDD33 GND ref_lin
xi_t0 t0b tn0 VDD33 GND ref_inv
xi_t1 t1b tn1 VDD33 GND ref_inv
xi_t2 t2b tn2 VDD33 GND ref_inv
xi_t3 t3b tn3 VDD33 GND ref_inv
xi_u0 tn0 tt0 VDD33 GND ref_inv
xi_u1 tn1 tt1 VDD33 GND ref_inv
xi_u2 tn2 tt2 VDD33 GND ref_inv
xi_u3 tn3 tt3 VDD33 GND ref_inv

* ---- bandgap (afe_ldo_tr core, R2 as a tapped string) ------------------
xmp0 pg pg VDD33 VDD33 pe3i w=8u l=4u
xmp1 a pg VDD33 VDD33 pe3i w=8u l=4u
xmp2 b pg VDD33 VDD33 pe3i w=8u l=4u
xmp3 t15 pg VDD33 VDD33 pe3i w=8u l=4u
xmp4 tlb pg VDD33 VDD33 pe3i w=8u l=4u
xd1 a GND dp3 area=100p perimeter=40u
r1 b bd 10.8k
xd2 bd GND dp3 area=800p perimeter=320u
xd3 cd GND dp3 area=100p perimeter=40u
* PTAT string: cd - 84.04k - t0 - 15 x 1.4325k - t15 (t8 = 95.5 kOhm)
r2b t0 cd 84.04k
rs0 t1 t0 1.4325k
rs1 t2 t1 1.4325k
rs2 t3 t2 1.4325k
rs3 t4 t3 1.4325k
rs4 t5 t4 1.4325k
rs5 t6 t5 1.4325k
rs6 t7 t6 1.4325k
rs7 t8 t7 1.4325k
rs8 t9 t8 1.4325k
rs9 t10 t9 1.4325k
rs10 t11 t10 1.4325k
rs11 t12 t11 1.4325k
rs12 t13 t12 1.4325k
rs13 t14 t13 1.4325k
rs14 t15 t14 1.4325k
xma1 m1 a tlb tlb pe3i w=40u l=4u
xma2 o1 b tlb tlb pe3i w=40u l=4u
xmn1 m1 m1 GND GND ne3i w=8u l=8u
xmn2 o1 m1 GND GND ne3i w=8u l=8u
xmn3 pg o1g GND GND ne3i w=8u l=4u
* loop-gain injection point of the bandgap loop (0 V in operation)
vinjb o1 o1g 0
ccb o1 GND 4p
* start-up: while the string top t15 < ~0.86 V, MS2 is off, MS3 pulls sg up
* and the weak MS1 pulls pg down (and lifts node a, so the op-amp output
* rises); MS3 (1/10) is strong enough to re-engage the kick at once and weak
* enough for MS2 to hold sg at ~20 mV in operation; MSO grounds sg while off
xms3 sg en_inb VDD33 VDD33 pe3i w=1u l=10u
xms2 sg t15 GND GND ne3i w=2u l=2u
xms1 pg sg a GND ne3i w=1u l=4u
xmso sg en_inb GND GND ne3i w=1u l=0.35u
* off: pg to VDD33, o1 to GND
xmbg_off pg en_in VDD33 VDD33 pe3i w=2u l=0.3u
xmbg_o1 o1 en_inb GND GND ne3i w=2u l=0.35u
* NMOS bias: 5 uA diode [nb] for every tail / sink
xmpn nb pg VDD33 VDD33 pe3i w=8u l=4u
xmnb nb nb GND GND ne3i w=4u l=4u
xmnbo nb en_inb GND GND ne3i w=1u l=0.35u

* ---- trim mux: vtap = t<code> -----------------------------------------
xa0 t0 t1 u0 tt0 tn0 GND ref_mux2
xa1 t2 t3 u1 tt0 tn0 GND ref_mux2
xa2 t4 t5 u2 tt0 tn0 GND ref_mux2
xa3 t6 t7 u3 tt0 tn0 GND ref_mux2
xa4 t8 t9 u4 tt0 tn0 GND ref_mux2
xa5 t10 t11 u5 tt0 tn0 GND ref_mux2
xa6 t12 t13 u6 tt0 tn0 GND ref_mux2
xa7 t14 t15 u7 tt0 tn0 GND ref_mux2
xb0 u0 u1 v0 tt1 tn1 GND ref_mux2
xb1 u2 u3 v1 tt1 tn1 GND ref_mux2
xb2 u4 u5 v2 tt1 tn1 GND ref_mux2
xb3 u6 u7 v3 tt1 tn1 GND ref_mux2
xc0 v0 v1 w0 tt2 tn2 GND ref_mux2
xc1 v2 v3 w1 tt2 tn2 GND ref_mux2
xd0 w0 w1 vtap tt3 tn3 GND ref_mux2
* ripple filter: the string (~90 kOhm) with CFL is a ~300 kHz low pass for the
* supply ripple that MP3 couples into the string at high frequency (PSRR
* minimum ~40 dB near 0.9 MHz, tm); it costs ~2 us of the settling time
cfl vtap GND 6p

* ---- A1: vrt = vtap x (1 + RF / RG) --------------------------------------
* PMOS-input first stage (o1a rises with the MA gate), NMOS common-source
* second stage: VDD33 only reaches the output through current sources, so
* the supply rejection holds at high frequency (a PMOS output stage with
* Miller compensation would pass VDD33 ripple above its GBW)
xga_t ta pg VDD33 VDD33 pe3i w=8u l=4u m=2
xga_a ma fbe ta ta pe3i w=20u l=2u
xga_b o1a vtap ta ta pe3i w=20u l=2u
xga_na ma ma GND GND ne3i w=4u l=4u
xga_nb o1a ma GND GND ne3i w=4u l=4u
* second stage: NMOS common source, 20 uA PMOS load; Miller CC + RZ
xga_o vrt o1a GND GND ne3i w=8u l=1u
xga_s vrt pg VDD33 VDD33 pe3i w=8u l=4u m=4
rz o1a cz 40k
cc cz vrt 1.5p
rf vrt fbn 2.266k
rg fbn GND 200k
* loop-gain injection point (0 V in operation)
vinja fbn fbe 0
* off: o1a and vrt to GND
xga_off o1a en_inb GND GND ne3i w=1u l=0.35u
xga_vo vrt en_inb GND GND ne3i w=2u l=0.35u

* ---- output buffers (unity followers) ------------------------------------
* 30 uA tails (slew rate with 100 pF: 0.3 V/us); 2 pF on-chip at each output
xbt vrt ftx TX_VREF nb VDD33 GND ref_ota mt=3
vinjt TX_VREF ftx 0
xbr vrt frx RX_VREF nb VDD33 GND ref_ota mt=3
vinjr RX_VREF frx 0
cot TX_VREF GND 2p
cor RX_VREF GND 2p
xbt_o TX_VREF en_inb GND GND ne3i w=2u l=0.35u
xbr_o RX_VREF en_inb GND GND ne3i w=2u l=0.35u

* ---- reference current: V(RBIAS) = vrt, I = vrt / RBIAS, TX_I_5U = I / 20
* A_I drives the NMOS source follower MNF, whose source is the RBIAS pin: the
* pin is a low-impedance node (1 / gm of MNF), so the board / pad capacitance
* of RBIAS stays a high-frequency pole.  The drain current goes through the
* wide-swing cascode mirror MPI / MCI (diode at [gi] = [dn], 20 units) to
* MPO / MCO (1 unit) = TX_I_5U.  A_I: out [gf] falls when V(RBIAS) rises.
xai vrt rbf gf nb VDD33 GND ref_ota
vinji RBIAS rbf 0
cgf gf GND 5p
xmnf gi gf RBIAS GND ne3i w=20u l=1u
xmpi di gi VDD33 VDD33 pe3i w=4u l=2u m=20
xmci gi vcas di VDD33 pe3i w=4u l=1u m=20
xmpo do gi VDD33 VDD33 pe3i w=4u l=2u m=1
xmco TX_I_5U vcas do VDD33 pe3i w=4u l=1u m=1
* cascode bias: 5 uA (nb) out of a PMOS diode: vcas = VDD33 - ~1.6 V
xmcb vcas vcas VDD33 VDD33 pe3i w=1u l=3u
xmcs vcas nb GND GND ne3i w=4u l=4u
* off: gf to GND (MNF off), gi and vcas to VDD33 (no output current)
xai_o gf en_inb GND GND ne3i w=1u l=0.35u
xgi_o gi en_in VDD33 VDD33 pe3i w=1u l=0.3u
xcb_o vcas en_in VDD33 VDD33 pe3i w=1u l=0.3u

.ends afe_ref_tr
