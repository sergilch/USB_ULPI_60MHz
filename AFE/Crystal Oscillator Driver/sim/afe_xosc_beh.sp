* afe_xosc_beh.sp - ngspice copy of the Verilog-A model AFE/veriloga/afe_xosc.va
*
* Same equations and parameter values as afe_xosc.va (keep in sync), written
* with B-sources so the transistor testbench can run them without a
* Verilog-A compiler:
*     python3 sim/tb_xosc_tr.py op ac ss start byp en --dut beh --tag _beh
* The subckt has the name and pins of the transistor netlist (afe_xosc_tr) so
* tb_xosc_tr.py instantiates it unchanged; nb, pb, sa are dummy nodes for its
* op probes, sb is the squarer comparator output.
* Differences to the .va, irrelevant at the time scales checked:
*   - the enable ramp is an RC (t_en / 2.2) instead of transition()'s line;
*   - the squarer comparator is the XSPICE hyst model, its delay an RC
*     (50 % point at t_sq; an ideal transmission line made ngspice's time
*     step collapse), the REF_CLK edge an RC (10-90 % = t_edge * 0.8 as the
*     linear 0-100 % edge of transition());
*   - no ideal-clock mode.

.subckt afe_xosc_tr XI XO XTAL_EN DRV1 DRV0 REF_CLK VDD VSS
+ i_s=235.4u n_ut=45.5m v_t=0.741 lambda=0.144 v_ref=0.85 v_dsn=0.1 v_dsp=0.2
+ r_f=1meg c_xi=0.385p c_xo=0.37p
+ i_unit0=250u i_step=125u i_scale=1 i_ovh=200u i_leak=0.2n
+ k_set=0.1 v_set_off=0.175 v_alc=25m tau_avg=2u g_att=1m c_pk=8p tau_dec=20u
+ tau_sq=0.25u k_sq_off=0.045 v_sq_hys=4m t_sq=0.85n t_edge=0.3n
+ vdd_min=1.4 r_off=1k t_en=0.5u

* ---- control ----
bend end VSS v = (v(XTAL_EN,VSS) > 0.5 * v(VDD,VSS)) * (v(VDD,VSS) > vdd_min)
ren end en 1k
cen en VSS {t_en / 2.2 / 1k}
bdrv drv VSS v = 2 * (v(DRV1,VSS) > 0.5 * v(VDD,VSS)) + (v(DRV0,VSS) > 0.5 * v(VDD,VSS))

* ---- ALC ----
bav VSS nav i = (v(XI,VSS) - v(nav,VSS)) / 1meg
cav nav VSS {tau_avg / 1meg}
cpk npk VSS {c_pk}
rdec npk VSS {tau_dec / c_pk}
batt VSS npk i = g_att * 0.5 * ((v(XI,VSS) - v(nav,VSS) - v(npk,VSS))
+   + sqrt((v(XI,VSS) - v(nav,VSS) - v(npk,VSS)) ^ 2 + 1e-8))
bpko npk VSS i = (1 - v(en,VSS)) * v(npk,VSS) / r_off
bib ib VSS v = v(en,VSS) * i_scale * (i_unit0 + i_step * v(drv,VSS))
+   / (1 + exp(min(30, (v(npk,VSS) - k_set * v(VDD,VSS) - v_set_off) / v_alc)))

* ---- amplifier ----
* softplus(u) = ln(1 + exp(u)), = u above 30 (no overflow while Newton iterates)
bsp sp VSS v = (v(XI,VSS) - v_t) / (2 * n_ut) > 30 ? (v(XI,VSS) - v_t) / (2 * n_ut)
+   : ln(1 + exp((v(XI,VSS) - v_t) / (2 * n_ut)))
bn XO VSS i = v(en,VSS) * i_scale * i_s * v(sp,VSS) ^ 2
+   * (1 + lambda * (v(XO,VSS) - v_ref)) * tanh(v(XO,VSS) / v_dsn)
bp VDD XO i = v(ib,VSS) * tanh((v(VDD,VSS) - v(XO,VSS)) / v_dsp)
rf XI XO {r_f}
cxi XI VSS {c_xi}
cxo XO VSS {c_xo}
boff XI VSS i = (1 - v(en,VSS)) * v(XI,VSS) / r_off

* ---- supply (bank current is drawn by bp) ----
bsup VDD VSS i = v(en,VSS) * i_ovh * i_scale + i_leak

* ---- squarer ----
bsqa VSS nsq i = (v(XI,VSS) - v(nsq,VSS)) / 1meg
csq nsq VSS {tau_sq / 1meg}
bsqi sqi VSS v = v(XI,VSS) - v(nsq,VSS) - k_sq_off * v(npk,VSS)
asq sqi sb hmod
.model hmod hyst(in_low=-2e-4 in_high=2e-4 hyst={v_sq_hys / 2} out_lower_limit=0
+   out_upper_limit=1 input_domain=0.01 fraction=TRUE)
rdel sb sbt 1k
cdel sbt VSS {t_sq / 0.693 / 1k}
bclk clkr VSS v = v(VDD,VSS) * (0.5 + 0.5 * tanh((v(sbt,VSS) - 0.5) / 0.01)) * v(end,VSS)
rclk clkr REF_CLK 10
cclk REF_CLK VSS {0.8 * t_edge / 2.2 / 10}

* dummy probe nodes of the transistor netlist
rnb nb VSS 1
rpb pb VSS 1
rsa sa VSS 1
.ends afe_xosc_tr
