//-----------------------------------------------------------------------------
// ams_ulpi_phy.v - complete PHY for system testbenches: ULPI pins <-> AFE pins
//
// Used by both
//   * AFE/ams/tb_ams_mouse.vams   (Spectre AMS: the AFE pins go through connect
//     modules into afe_transceiver / afe_receiver / afe_cdr), and
//   * tb_ams_mouse_shadow.v       (Icarus: the same pins drive the event-driven
//     models afe_*_bm.v).
// Plain Verilog-2005, no AMS constructs.  Testbench assembly, not RTL: the
// top-level wiring of these blocks into usb_ulpi_phy_top / _pads is WORK_PLAN 8.1
// and not done yet.  This file shows one way to do it and checks it end to end.
//
//   clk_bit (PLL) -> usb_clk_gen -> clk60, ld, clkout (CLKOUT, CKO_LEAD 2)
//   RESETB -> 2-FF on clk60 -> core_rst_n -> 2-FF on clk_bit -> bit_rst_n
//            (as usb_ulpi_phy_pads)
//   ULPI pins <-> usb_ulpi_phy_top (ULPI core, register file, TX byte path,
//                 usb_mode_term_ctrl, usb_afe_trim_regs)
//     txd_v / tx_en_v / tx_se0_v -> usb_afe_tx_if8 (clk60; TX_LEAD / TX_LAG from
//       the trim registers) -> usb_tx_piso (clk_bit) -> HS / FS / LS driver pins
//     terminations: dp/dm_pullup_en, hs_term_en, dp/dm_pulldown_en from
//       usb_mode_term_ctrl inside usb_ulpi_phy_top
//   clk_rx, hs_rxd_a, squelch_a -> usb_afe_rx_if (LOCK_DLY / SQ_COMP trims)
//     -> usb_rx_datapath; rxdp_a / rxdm_a / rxrcv_a -> FS/LS sampler in
//     usb_rx_datapath -> ls_* -> usb_line_state; squelch_a / disc_a ->
//     usb_rx_status_sync -> usb_line_state -> LineState / HostDisconnect
//     -> usb_ulpi_phy_top (RXCMD, Debug register)
//
// Fixed inputs (blocks not in this assembly): VBUS comparators a_vbus_vld /
//   sess_vld = 1, sess_end = 0 (VBUS present), id_gnd = ID_GND (parameter),
//   alt_int = 0; usb_pwr_seq / usb_pll_lock_det replaced by constants
//   (iso_en 0, PLL locked, power state 0, dir_hold 0); CLKOUT enabled.
//
// ULPI pin timing: the RTL has no delays, so the pads are modelled here with
//   the placeholder values of constraints/usb_phy.sdc: CLK pin = clkout +
//   T_CKO (CKO_FF 0.8 + PAD_OUT 3.0 ns), outputs DIR / NXT / DATA + T_OUT
//   (PAD_OUT), inputs STP / DATA + T_IN (PAD_IN).  With CKO_LEAD = 2 the CLK pin
//   edge comes 0.37 ns before the clk60 edge E0, as in the SDC: a Link that
//   launches on the CLK pin edge with a clock-to-out > 0 is sampled one clk60
//   edge later (hold) and the PHY outputs reach the Link well before its next
//   CLK edge (setup).  With T_CKO = 0 the CLK pin would lead E0 by 4.2 ns and a
//   Link output with TCQ < 4.2 ns would be sampled in the same cycle.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module ams_ulpi_phy #(
    parameter      ID_GND = 1'b1,      // ID pin grounded: A-device (host)
    parameter real T_CKO  = 3.8,       // ns, CLKOUT flop + CLK pad (SDC CKO_FF + PAD_OUT)
    parameter real T_OUT  = 3.0,       // ns, output pads (SDC PAD_OUT)
    parameter real T_IN   = 1.0        // ns, input pads (SDC PAD_IN)
) (
    input  wire       clk_bit,         // 480 MHz PLL clock
    input  wire       por_n,           // power-on reset (clock generator)
    input  wire       resetb,          // ULPI RESETB pin

    // ULPI pins
    output wire       ulpi_clk,
    inout  wire [7:0] ulpi_data,
    output wire       ulpi_dir,
    output wire       ulpi_nxt,
    input  wire       ulpi_stp,

    // terminations
    output wire       dp_pullup_en,
    output wire       dm_pullup_en,
    output wire       hs_term_en,
    output wire       dp_pulldown_en,
    output wire       dm_pulldown_en,
    // HS transmitter
    output wire       hs_tx_p,
    output wire       hs_tx_n,
    output wire       hs_tx_en,
    // FS / LS transmitter
    output wire       fs_oe,
    output wire       fs_dat,
    output wire       fs_se0,
    output wire       fs_ls,
    // HS receiver / CDR control
    output wire       rx_en_hs,
    output wire       cdr_en,
    // from the AFE
    input  wire       clk_rx,
    input  wire       hs_rxd_a,
    input  wire       squelch_a,
    input  wire       disc_a,
    input  wire       rxdp_a,
    input  wire       rxdm_a,
    input  wire       rxrcv_a
);
    // ---------------- clocks ----------------
    wire       clk60, ld, clkout, clk_on;
    wire [3:0] phase_j;
    usb_clk_gen u_clk (
        .clk_bit(clk_bit), .rst_n(por_n), .clk_en(1'b1),
        .clk60(clk60), .phase_j(phase_j), .ld(ld), .clkout(clkout), .clk_on(clk_on));

    // ---------------- resets (as usb_ulpi_phy_pads) ----------------
    wire      resetb_y;
    reg [1:0] rst_sync;
    always @(posedge clk60 or negedge resetb_y) begin
        if (!resetb_y) rst_sync <= 2'b00;
        else           rst_sync <= {rst_sync[0], 1'b1};
    end
    wire core_rst_n = rst_sync[1];
    reg [1:0] bit_sync;
    always @(posedge clk_bit or negedge core_rst_n) begin
        if (!core_rst_n) bit_sync <= 2'b00;
        else             bit_sync <= {bit_sync[0], 1'b1};
    end
    wire bit_rst_n = bit_sync[1];

    // ---------------- ULPI pads (delays only) ----------------
    wire [7:0] data_out, data_in;
    wire       data_oe, dir_c, nxt_c, stp_c;
    assign #(T_CKO) ulpi_clk = clkout;
    assign #(T_OUT) ulpi_dir = dir_c;
    assign #(T_OUT) ulpi_nxt = nxt_c;
    wire [7:0] data_out_p;
    wire       data_oe_p;
    assign #(T_OUT) data_out_p = data_out;
    assign #(T_OUT) data_oe_p  = data_oe;
    assign ulpi_data = data_oe_p ? data_out_p : 8'bz;
    assign #(T_IN) data_in  = ulpi_data;
    assign #(T_IN) stp_c    = ulpi_stp;
    assign #(T_IN) resetb_y = resetb;

    // ---------------- ULPI core, registers, mode / termination control ----------------
    wire       r_start, r_valid, r_end, r_error;
    wire [7:0] r_data;
    wire [1:0] linestate;
    wire       host_disc;
    wire [1:0] xcvrselect, opmode, cfg_speed, tx_speed;
    wire       termselect, suspendm, soft_reset, cfg_bypass, drv_dis, host_mode;
    wire [7:0] ifc_ctrl, otg_ctrl;
    wire [7:0] txd_v, tx_en_v, tx_se0_v;
    wire       lol_clr, ana_lpbk;
    wire [3:0] trim_tx_amp, atb_sel;
    wire [2:0] trim_hs_term, trim_tx_lag, trim_rx_vth, trim_rx_hyst, trim_sq_vth, trim_disc_vth;
    wire [2:0] trim_cdr_icp, trim_pll_icp, trim_lock_dly, trim_sq_comp;
    wire [4:0] trim_tx_lead;
    wire [1:0] trim_cdr_band;
    wire       busy, tx_done, tx_underrun, rx_active, rx_err, rx_overrun;

    usb_ulpi_phy_top u_core (
        .rst_n(core_rst_n), .clk60(clk60),
        .ulpi_data_in(data_in), .ulpi_stp(stp_c), .ulpi_dir(dir_c), .ulpi_nxt(nxt_c),
        .ulpi_data_out(data_out), .ulpi_data_oe(data_oe),
        .rx_start(r_start), .rx_valid(r_valid), .rx_data(r_data), .rx_end(r_end), .rx_error(r_error),
        .linestate(linestate), .host_disc(host_disc),
        .a_vbus_vld(1'b1), .sess_vld(1'b1), .sess_end(1'b0), .id_gnd(ID_GND), .alt_int(1'b0),
        .dir_hold(1'b0),
        .iso_en(1'b0), .pwr_state(4'd0), .pll_err(1'b0), .pll_lock(1'b1), .lol(1'b0),
        .xcvrselect(xcvrselect), .termselect(termselect), .opmode(opmode), .suspendm(suspendm),
        .soft_reset(soft_reset), .ifc_ctrl(ifc_ctrl), .otg_ctrl(otg_ctrl),
        .cfg_speed(cfg_speed), .cfg_bypass(cfg_bypass),
        .dp_pullup_en(dp_pullup_en), .dm_pullup_en(dm_pullup_en), .hs_term_en(hs_term_en),
        .dp_pulldown_en(dp_pulldown_en), .dm_pulldown_en(dm_pulldown_en),
        .drv_dis(drv_dis), .host_mode(host_mode),
        .lol_clr(lol_clr), .trim_tx_amp(trim_tx_amp), .trim_hs_term(trim_hs_term),
        .trim_tx_lead(trim_tx_lead), .trim_tx_lag(trim_tx_lag),
        .trim_rx_vth(trim_rx_vth), .trim_rx_hyst(trim_rx_hyst),
        .trim_sq_vth(trim_sq_vth), .trim_disc_vth(trim_disc_vth),
        .trim_cdr_icp(trim_cdr_icp), .trim_cdr_band(trim_cdr_band), .trim_pll_icp(trim_pll_icp),
        .trim_lock_dly(trim_lock_dly), .trim_sq_comp(trim_sq_comp),
        .atb_sel(atb_sel), .ana_lpbk(ana_lpbk),
        .txd_v(txd_v), .tx_en_v(tx_en_v), .tx_se0_v(tx_se0_v), .tx_speed(tx_speed),
        .busy(busy), .tx_done(tx_done), .tx_underrun(tx_underrun),
        .rx_active(rx_active), .rx_err(rx_err), .rx_overrun(rx_overrun));

    // ---------------- TX: line vectors -> pins ----------------
    wire [7:0] tx_pp, tx_phen, tx_poe, tx_pdat, tx_pse0, tx_pany;
    wire       tx_pls, tx_pact, tx_act;
    usb_afe_tx_if8 u_afe_tx8 (
        .clk60(clk60), .rst_n(core_rst_n),
        .txd_v(txd_v), .tx_en_v(tx_en_v), .tx_se0_v(tx_se0_v), .tx_speed(tx_speed),
        .tx_lead(trim_tx_lead), .tx_lag(trim_tx_lag), .lead_first(cfg_bypass),
        .hs_p_v(tx_pp), .hs_en_v(tx_phen), .fs_oe_v(tx_poe), .fs_dat_v(tx_pdat), .fs_se0_v(tx_pse0),
        .any_v(tx_pany), .fs_ls_q(tx_pls), .act(tx_pact));
    usb_tx_piso u_piso (
        .clk_bit(clk_bit), .rst_n(bit_rst_n), .ld(ld),
        .hs_p_v(tx_pp), .hs_en_v(tx_phen), .fs_oe_v(tx_poe), .fs_dat_v(tx_pdat), .fs_se0_v(tx_pse0),
        .any_v(tx_pany), .fs_ls_q(tx_pls), .act(tx_pact), .drv_dis(drv_dis), .iso_en(1'b0),
        .hs_tx_p(hs_tx_p), .hs_tx_n(hs_tx_n), .hs_tx_en(hs_tx_en),
        .fs_oe(fs_oe), .fs_dat(fs_dat), .fs_se0(fs_se0), .fs_ls(fs_ls), .tx_active(tx_act));

    // ---------------- RX ----------------
    wire hs_rxd, hs_sq, hs_lock;
    usb_afe_rx_if u_afe_rx (
        .clk60(clk60), .rst_n(core_rst_n), .speed(xcvrselect), .rx_en(1'b1), .iso_en(1'b0),
        .lock_dly(trim_lock_dly), .sq_comp(trim_sq_comp), .rx_en_hs(rx_en_hs), .cdr_en(cdr_en),
        .clk_rx(clk_rx), .hs_rxd_a(hs_rxd_a), .squelch_a(squelch_a),
        .hs_rxd(hs_rxd), .hs_squelch(hs_sq), .hs_cdr_lock(hs_lock));

    wire s_dp, s_dm, s_rcv, s_sq, s_disc, s_avv, s_sv, s_se, s_id;
    usb_rx_status_sync u_ss (
        .clk_bit(clk_bit), .rst_n(core_rst_n), .clk60(clk60), .ld(ld),
        .squelch(squelch_a), .disc(disc_a),
        .a_vbus_vld(1'b1), .sess_vld(1'b1), .sess_end(1'b0), .id_gnd(ID_GND),
        .sq_flt(4'd1), .disc_flt(4'd0), .vb_flt(16'd0),
        .squelch_s(s_sq), .disc_s(s_disc),
        .a_vbus_vld_s(s_avv), .sess_vld_s(s_sv), .sess_end_s(s_se), .id_gnd_s(s_id));

    usb_line_state u_ls (
        .clk_bit(clk_bit), .rst_n(core_rst_n), .clk60(clk60), .ld(ld),
        .rxdp_s(s_dp), .rxdm_s(s_dm), .rxrcv_s(s_rcv), .squelch_s(s_sq), .disc_s(s_disc),
        .xcvrselect(xcvrselect), .opmode(opmode), .host_mode(host_mode), .hs_tx_act(tx_act),
        .linestate(linestate), .host_disc(host_disc));

    wire r_busy;
    usb_rx_datapath u_rx (
        .clk_bit(clk_bit), .rst_n(core_rst_n), .clk60(clk60), .ld(ld), .speed(xcvrselect),
        .rx_en(1'b1), .tx_en(tx_act),
        .clk_rx(clk_rx), .hs_rxd(hs_rxd), .hs_squelch(hs_sq), .hs_cdr_lock(hs_lock),
        .rxrcv(rxrcv_a), .rxdp(rxdp_a), .rxdm(rxdm_a),
        .ls_dp(s_dp), .ls_dm(s_dm), .ls_rcv(s_rcv),
        .rx_start(r_start), .rx_valid(r_valid), .rx_data(r_data), .rx_end(r_end),
        .rx_error(r_error), .rx_busy(r_busy));
endmodule
