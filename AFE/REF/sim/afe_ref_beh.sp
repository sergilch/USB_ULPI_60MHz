* afe_ref_beh.sp - ngspice copy of the Verilog-A model AFE/veriloga/afe_ref.va
*
* Same equations and parameter values as afe_ref.va (keep in sync), written
* with B-sources so the transistor testbench can run them without a
* Verilog-A compiler:
*     python3 AFE/REF/sim/tb_ref_tr.py op trim temp line zout comply rbias start tran \
*         --netlist AFE/REF/sim/afe_ref_beh.sp --tag _beh --code 8
* The subckt has the name and pins of the transistor netlist (afe_ref_tr) so
* tb_ref_tr.py instantiates it unchanged; vrt is the model's reference node,
* vtap / t8 / vcas are dummy nodes for the testbench's op probes.
* Differences to the .va, irrelevant at the time scales checked:
*   - the start-up delays come from a "time since enable" node ton (1 V/us,
*     reset while off) instead of transition(); the shut-down is an RC
*     (t_off / 2.2) instead of a linear ramp;
*   - no noise sources (B-sources are noiseless in ngspice).

.subckt afe_ref_tr VDD33 GND BIAS_EN TRIM0 TRIM1 TRIM2 TRIM3 RBIAS TX_VREF RX_VREF TX_I_5U
+ v0=1.200977 c1=31.7766u c2=-0.551225u c3=0.537794n line=0.44m lsb=7.2m code_nom=8 dv_proc=0
+ h_dr=-0.784 w_dr=0.341 k1=0.82 t_d1=0.35u t_r1=1.15u t_d2=4.3u tau2=0.6u t_off=20n
+ g_buf=137u i_buf=23u c_out=2p r_off=1k
+ v_rb_off=0.526m g_rb=0.05 i_rb_max=640u k_hd=149.4u v_hd=0.552 p_hd=5.44 ratio=20
+ r_o5=894meg v_o5=0.6 g_c=21.76u v_c=-0.0068 p_c=4.07
+ i_core=145.8u x_core=0.82 i_leak=0.6n v_th=0.8 vdd_min=1.5

* ---- control ----
bend end GND v = (v(BIAS_EN,GND) > v_th) * (v(VDD33,GND) > vdd_min)
ren end enf 1k
cen enf GND {t_off / 2.2 / 1k}
bcode code GND v = v(end,GND) * (8 * (v(TRIM3,GND) > v_th) + 4 * (v(TRIM2,GND) > v_th)
+   + 2 * (v(TRIM1,GND) > v_th) + (v(TRIM0,GND) > v_th))
* time since enable in us (1 V/us), reset in ~1 ns while off
cton ton GND 1p
bton GND ton i = v(end,GND) * 1u - (1 - v(end,GND)) * v(ton,GND) / 1k

* ---- reference ----
bvref vref GND v = (v0 + (temper - 27) * (c1 + (temper - 27) * (c2 + (temper - 27) * c3))
+   + line * (v(VDD33,GND) - 3.3) + (dv_proc + lsb * (v(code,GND) - code_nom)) * (temper + 273.15) / 300.15)
bvr vr GND v = v(vref,GND) - w_dr * ln(1 + exp(min((v(vref,GND) - (v(VDD33,GND) - h_dr)) / w_dr, 30)))

* ---- start-up ----
be1 e1 GND v = v(end,GND) * min(max((v(ton,GND) * 1u - t_d1) / t_r1, 0), 1)
be2 e2 GND v = v(end,GND) * 0.5 * (1 + tanh((v(ton,GND) * 1u - t_d2) / 10n))
rs2 e2 s2 1meg
cs2 s2 GND {tau2 / 1meg}
bbias bias GND v = k1 * v(e1,GND) + (1 - k1) * v(s2,GND)
bvrt vrt GND v = v(vr,GND) * v(bias,GND)

* ---- buffers ----
* tail current of the buffers follows the bias (bandgap) start-up (>= 5 % for the shut-down)
bib0 ibf GND v = i_buf * max(v(bias,GND), 0.05)
bbt GND TX_VREF i = v(enf,GND) * v(ibf,GND) * tanh(g_buf * (v(vrt,GND) - v(TX_VREF,GND)) / v(ibf,GND))
bbr GND RX_VREF i = v(enf,GND) * v(ibf,GND) * tanh(g_buf * (v(vrt,GND) - v(RX_VREF,GND)) / v(ibf,GND))
cot TX_VREF GND {c_out}
cor RX_VREF GND {c_out}
bot TX_VREF GND i = (1 - v(enf,GND)) * v(TX_VREF,GND) / r_off
bor RX_VREF GND i = (1 - v(enf,GND)) * v(RX_VREF,GND) / r_off

* ---- current reference (irb, i5o: the currents as voltages, 1 V = 1 A) ----
birb irb0 GND v = v(enf,GND) * i_rb_max * 0.5 * (tanh(g_rb * (v(vrt,GND) + v_rb_off - v(RBIAS,GND)) / i_rb_max)
+   + sqrt(tanh(g_rb * (v(vrt,GND) + v_rb_off - v(RBIAS,GND)) / i_rb_max) ^ 2 + 1e-12))
blhd lhd GND v = k_hd * (ln(1 + exp(min((v(VDD33,GND) - v(RBIAS,GND) - v_hd) * 50, 30))) / 50
+   + max((v(VDD33,GND) - v(RBIAS,GND) - v_hd) - 0.6, 0)) ^ 2
birb2 irb GND v = max(v(irb0,GND), 1e-15) / (1 + (max(v(irb0,GND), 1e-15) / max(v(lhd,GND), 1e-15)) ^ p_hd) ^ (1 / p_hd)
bib GND RBIAS i = v(irb,GND)
blc lc GND v = g_c * ln(1 + exp(min((v(VDD33,GND) - v(TX_I_5U,GND) - v_c) * 50, 30))) / 50
+   + g_c * max((v(VDD33,GND) - v(TX_I_5U,GND) - v_c) - 0.6, 0)
bi50 i50 GND v = max(v(irb,GND) / ratio - (v(TX_I_5U,GND) - v_o5) / r_o5, 0)
bi5o i5o GND v = max(v(i50,GND), 1e-18) / (1 + (max(v(i50,GND), 1e-18) / max(v(lc,GND), 1e-18)) ^ p_c) ^ (1 / p_c)
bi5 GND TX_I_5U i = v(i5o,GND)

* ---- supply ----
bdd VDD33 GND i = v(enf,GND) * i_core * ((temper + 273.15) / 300.15) ^ x_core + v(irb,GND) + v(i5o,GND)
+   + max(v(enf,GND) * v(ibf,GND) * tanh(g_buf * (v(vrt,GND) - v(TX_VREF,GND)) / v(ibf,GND)), 0)
+   + max(v(enf,GND) * v(ibf,GND) * tanh(g_buf * (v(vrt,GND) - v(RX_VREF,GND)) / v(ibf,GND)), 0) + i_leak

* ---- dummy probe nodes of tb_ref_tr.py (op) ----
bvtap vtap GND v = v(vrt,GND) / 1.01133
bt8 t8 GND v = v(vtap,GND)
rvcas vcas GND 1meg
.ends afe_ref_tr
