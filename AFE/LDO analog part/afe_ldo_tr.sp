* afe_ldo_tr.sp - 3.3 V -> 1.8 V LDO for the analog 1.8 V domain (VDD18A)
*
* Transistor-level design, X-FAB xh018, isolated 3.3 V devices ne3i / pe3i and
* the p+/n-well diode dp3 (cathode on GND).  Same pins and function as the
* behavioural model AFE/veriloga/afe_ldo.va; description:
* AFE/LDO analog part/ldo_description.md, datasheet: datasheet/ldo_datasheet.md.
*
*   VIN       3.3 V supply (VDD33, 2.97-3.63 V)
*   VOUT      1.8 V output; external 1 uF ceramic capacitor (0.47-2.2 uF,
*             ESR <= 0.5 Ohm) to GND; load 0-20 mA (current limit ~75 mA)
*   GND       ground
*   LDO_EN    enable, threshold 0.66-0.83 V absolute (1.8 V or 3.3 V logic)
*   PWR_GOOD  1 (= VOUT) 10 us after VOUT > 1.62 V, 0 at once below 1.55 V
*   POR_N     1 (= VOUT) 100 us after PWR_GOOD, falls with it
*
* Blocks (subcircuit-internal node names in brackets)
*   bandgap   dp3 diodes 1x / 8x, PMOS mirror, PMOS-input op-amp, VBG =
*             VBE + 9.4 x Vt ln 8 = 1.187 V; PTAT bias 5 uA per mirror unit
*             (pg); start-up NMOS (MS1) gated by a VBG detector (MS2)
*   reference RC soft start VBG -> 5 Mohm -> [vr] with 10 pF (tau 50 us),
*             also filters the bandgap noise; discharged while off
*   regulator NMOS-input error amplifier (DC gain ~45 dB; REA + CEA set
*             the mid-band gain and a 1.6 kHz zero), 20 uA PMOS
*             source follower [gp], pass PMOS 2400 um / 0.5 um, divider
*             180 kOhm [fb] = VOUT x 0.659
*   limit     sense PMOS 1:1200 into 12 kOhm, NMOS detector pushes [eo] up
*   UVLO      VIN divider 1.5 MOhm vs VBG, 2.7 V rising / 2.5 V falling,
*             and VBG > ~0.85 V (bandgap running)
*   power good   VOUT divider taps vs VBG, 1.62 V rising / 1.55 V falling;
*             delays by current-charged capacitors + Schmitt triggers
*   outputs   inverters supplied by VOUT (swing 0 .. VOUT)
* Resistors and capacitors are ideal here; intended devices: high-resistance
* poly (rpp1k1 / rhr, divider and bandgap resistors), MIM (cmm4) capacitors.

* ---------------------------------------------------------------- cells
.subckt ldo_inv in out vdd vss
xp out in vdd vdd pe3i w=2u l=0.3u
xn out in vss vss ne3i w=1u l=0.35u
.ends ldo_inv

.subckt ldo_nand2 a b out vdd vss
xpa out a vdd vdd pe3i w=2u l=0.3u
xpb out b vdd vdd pe3i w=2u l=0.3u
xna out a m vss ne3i w=2u l=0.35u
xnb m b vss vss ne3i w=2u l=0.35u
.ends ldo_nand2

* Schmitt trigger (non-inverting output: in -> 6T stage -> inverter)
.subckt ldo_schmitt in out vdd vss
xp1 p1 in vdd vdd pe3i w=2u l=0.3u
xp2 sb in p1 vdd pe3i w=2u l=0.3u
xn2 sb in n1 vss ne3i w=1u l=0.35u
xn1 n1 in vss vss ne3i w=1u l=0.35u
xp3 p1 sb vss vdd pe3i w=1u l=0.3u
xn3 n1 sb vdd vss ne3i w=1u l=0.35u
xo sb out vdd vss ldo_inv
.ends ldo_schmitt

* comparator: PMOS-input OTA (5 uA tail), NMOS common-source second stage
* with a 1.25 uA current-source load (rail-to-rail, no shoot-through),
* inverter; output high when inp > inm.  en = 0 (enb = 1): co pulled low,
* o2 pulled high, out = 0 (no floating node while the bias is off).  Before
* the bandgap runs the output is undefined: every use is gated
.subckt ldo_comp inp inm out pg en enb vdd vss
xt tl pg vdd vdd pe3i w=8u l=4u
xa da inp tl tl pe3i w=10u l=2u
xb co inm tl tl pe3i w=10u l=2u
xna da da vss vss ne3i w=4u l=4u
xnb co da vss vss ne3i w=4u l=4u
xs o2 co vss vss ne3i w=2u l=1u
xl o2 pg vdd vdd pe3i w=2u l=4u
xdc co enb vss vss ne3i w=1u l=0.35u
xdo o2 en vdd vdd pe3i w=1u l=0.3u
xi1 o2 out vdd vss ldo_inv
.ends ldo_comp

* ---------------------------------------------------------------- LDO
.subckt afe_ldo_tr VIN VOUT GND LDO_EN PWR_GOOD POR_N

* ---- enable input (threshold ~0.8 V) and logic -----------------------
xmi eib LDO_EN GND GND ne3i w=4u l=1u
xmil eib GND VIN VIN pe3i w=1u l=40u
xi_en eib en_in VIN GND ldo_inv
xi_enb en_in en_inb VIN GND ldo_inv

* ---- bandgap ----------------------------------------------------------
xmp0 pg pg VIN VIN pe3i w=8u l=4u
xmp1 a pg VIN VIN pe3i w=8u l=4u
xmp2 b pg VIN VIN pe3i w=8u l=4u
xmp3 vbg pg VIN VIN pe3i w=8u l=4u
xmp4 tlb pg VIN VIN pe3i w=8u l=4u
xd1 a GND dp3 area=100p perimeter=40u
r1 b bd 10.8k
xd2 bd GND dp3 area=800p perimeter=320u
r2 vbg cd 95.5k
xd3 cd GND dp3 area=100p perimeter=40u
xma1 m1 a tlb tlb pe3i w=20u l=2u
xma2 o1 b tlb tlb pe3i w=20u l=2u
xmn1 m1 m1 GND GND ne3i w=4u l=4u
xmn2 o1 m1 GND GND ne3i w=4u l=4u
xmn3 pg o1 GND GND ne3i w=8u l=4u
ccb o1 GND 2p
* start-up: while VBG < ~0.86 V, MS2 is off, the long PMOS MS3 pulls sg to VIN
* and MS1 pulls pg down (full mirror current); above it MS2 grounds sg;
* MSO grounds sg while disabled
xms3 sg en_inb VIN VIN pe3i w=1u l=40u
xms2 sg vbg GND GND ne3i w=2u l=2u
xms1 pg sg a GND ne3i w=2u l=2u
xmso sg en_inb GND GND ne3i w=1u l=0.35u
* off: pg to VIN, o1 to GND
xmbg_off pg en_in VIN VIN pe3i w=2u l=0.3u
xmbg_o1 o1 en_inb GND GND ne3i w=2u l=0.35u
* NMOS bias (5 uA diode) for the error amplifier tail
xmpn nb pg VIN VIN pe3i w=8u l=4u
xmnb nb nb GND GND ne3i w=4u l=4u
* bandgap running: VBG > ~0.85 V (bg_ok = 0 while disabled: MGO)
xmg bgb vbg GND GND ne3i w=2u l=2u
xmgl bgb en_inb VIN VIN pe3i w=1u l=40u
xmgo bgb en_in VIN VIN pe3i w=1u l=0.3u
xi_bg bgb bg_ok VIN GND ldo_inv

* ---- UVLO: VIN x 0.4395 (rising) / 0.4746 (falling) vs VBG ------------
rua VIN utf 788k
rub utf utr 52.7k
ruc utr usw 659.3k
xmus usw en_in GND GND ne3i w=2u l=0.35u
xsu1 utr uv_okb utap GND ne3i w=1u l=0.35u
xsu2 utf uv_ok utap GND ne3i w=1u l=0.35u
xcu utap vbg uv_raw pg en_in en_inb VIN GND ldo_comp
xnu uv_raw bg_ok uvn VIN GND ldo_nand2
xiu uvn uv_ok VIN GND ldo_inv
xiub uv_ok uv_okb VIN GND ldo_inv
* regulator on = en_in & uv_ok
xne en_in uv_ok onb VIN GND ldo_nand2
xie onb on VIN GND ldo_inv

* ---- reference with RC soft start -------------------------------------
rss vbg vr 5meg
css vr GND 10p
xmss vr onb GND GND ne3i w=1u l=0.35u

* ---- error amplifier: NMOS pair, PMOS mirror, gain set by REA ---------
* fb (divider) -> vinj (0 V, AC loop-gain injection point) -> fbe
vinj fbe fb dc 0 ac 0
xme0 te nb GND GND ne3i w=8u l=4u
xme1 ed fbe te GND ne3i w=20u l=1u
xme2 eo vr te GND ne3i w=20u l=1u
xme3 ed ed VIN VIN pe3i w=8u l=2u
xme4 eo ed VIN VIN pe3i w=8u l=2u
* REA + CEA: full DC gain (~45 dB) for regulation accuracy; above the zero
* 1 / (2 pi REA CEA) = 1.6 kHz the gain is gm x REA, which keeps the phase
* margin >= 59 deg from no load to 50 mA (CEA: MOS or MIM capacitor)
rea eo ea 2meg
cea ea ed 50p
* ---- gate buffer: PMOS source follower --------------------------------
xmb0 gp pg VIN VIN pe3i w=32u l=4u
xmb1 GND eo gp gp pe3i w=20u l=1u
xmgd gp on VIN VIN pe3i w=4u l=0.3u
xmeo eo on VIN VIN pe3i w=1u l=0.3u
* ---- pass device and current limit ------------------------------------
xmpass VOUT gp VIN VIN pe3i w=20u l=0.5u m=120
xmsen cs gp VIN VIN pe3i w=2u l=0.5u
rcs cs GND 12k
xmcl cl cs GND GND ne3i w=4u l=1u
xmcl1 cl cl VIN VIN pe3i w=4u l=1u
xmcl2 eo cl VIN VIN pe3i w=8u l=1u
* ---- feedback divider with power-good taps ----------------------------
* VOUT - 42.20k - pf (x0.7656, 1.55 V) - 5.96k - pr (x0.7325, 1.62 V)
*      - 13.18k - fb (x0.6592, 1.80 V) - 118.66k - GND
rda VOUT pf 42.20k
rdd pf pr 5.96k
rdb pr fb 13.18k
rdc fb GND 118.66k
* ---- output discharge while off (~0.6 kOhm typ, ~1 kOhm at ws 125 C) ----
xmdis VOUT onb GND GND ne3i w=6u l=1u

* ---- power good ---------------------------------------------------------
xsp1 pr pg_rawb ptap GND ne3i w=1u l=0.35u
xsp2 pf pg_raw ptap GND ne3i w=1u l=0.35u
xcp ptap vbg pgc pg en_in en_inb VIN GND ldo_comp
xnp pgc on pgn VIN GND ldo_nand2
xip pgn pg_raw VIN GND ldo_inv
xipb pg_raw pg_rawb VIN GND ldo_inv
* delay 10 us: Ipg (~0.3 uA) charges cpgd; discharged at once by pg_rawb
xmpd1 pgd pg VIN VIN pe3i w=1u l=8u
cpgd pgd GND 1.6p
xmpd2 pgd pg_rawb GND GND ne3i w=1u l=0.35u
xspg pgd pg_d VIN GND ldo_schmitt
xipgdb pg_d pg_db VIN GND ldo_inv
* delay 100 us
xmrd1 prd pg VIN VIN pe3i w=1u l=8u
cprd prd GND 16p
xmrd2 prd pg_db GND GND ne3i w=1u l=0.35u
xspr prd por_d VIN GND ldo_schmitt
xiprb por_d por_db VIN GND ldo_inv

* ---- outputs (VOUT supply) ----------------------------------------------
xopg pg_db PWR_GOOD VOUT GND ldo_inv
xopr por_db POR_N VOUT GND ldo_inv
.ends afe_ldo_tr
