//-----------------------------------------------------------------------------
// tb_ams_msc_shadow.v - Icarus counterpart of the Spectre AMS system test
//                       AFE/ams/tb_ams_msc.vams: USB host enumeration of a
//                       full-speed mass-storage device (Bulk-Only Transport)
//                       through the PHY's ULPI interface
//
// Run (Icarus Verilog):
//   iverilog -g2005 -I AFE/ams -I "Tests/USB ULPI Mouse" -o sim_ams_msc_shadow \
//            usb_clk_gen.v usb_bit_stuffer.v usb_nrzi_encoder.v usb_tx_serializer8.v \
//            usb_tx_path.v usb_tx_holding.v usb_tx_sync_mux.v usb_tx_datapath.v \
//            usb_ulpi_input_capture.v usb_ulpi_reg_access.v usb_ulpi_reg_file.v \
//            usb_ulpi_burst_mux.v usb_ulpi_bus_owner.v usb_ulpi_core.v usb_ulpi_rx_handler.v \
//            usb_ulpi_rxcmd_gen.v usb_ulpi_out_arbiter.v usb_ulpi_rx_path.v usb_ulpi_phy_if.v \
//            usb_afe_trim_regs.v usb_mode_term_ctrl.v usb_ulpi_phy_top.v \
//            usb_afe_tx_if8.v usb_tx_piso.v usb_afe_rx_if.v usb_rx_elastic_buffer.v \
//            usb_rx_hs_frontend.v usb_rx_hs_sipo.v usb_rx_fsls_sampler.v usb_rx_fsls_dpll.v \
//            usb_rx_decoder8.v usb_rx_datapath.v usb_rx_status_flt.v usb_rx_status_sync.v \
//            usb_line_state.v \
//            afe_line_bm.v afe_term_bm.v afe_hs_tx_bm.v afe_fsls_bm.v afe_hs_rx_bm.v \
//            afe_squelch_bm.v afe_cdr_bm.v "Tests/USB mass-storage device/fs_msc_bm.v" \
//            AFE/ams/ams_ulpi_phy.v tb_ams_msc_shadow.v
//   vvp sim_ams_msc_shadow            (+dump for a VCD, tb_ams_msc_shadow.vcd)
//
// Same PHY (AFE/ams/ams_ulpi_phy.v: ULPI top + TX / RX datapaths + clock
// generator), same Link model and host sequence (AFE/ams/ams_msc_seq.vh,
// ulpi_link_bfm of Tests/USB ULPI Mouse/ulpi_tb_template.v) as the AMS
// testbench; here the AFE is afe_term_bm, afe_hs_tx_bm, afe_fsls_bm,
// afe_hs_rx_bm, afe_squelch_bm, afe_cdr_bm and the device is fs_msc_bm (the
// event-driven port of the Verilog-A model usb_fs_msc.va), all on one
// afe_line_bm (DP / DM).  So every regression run checks the digital half of
// the AMS testbench and its sequence; a failure only in Spectre AMS points at
// the Verilog-A models, the connect rules or the AMS netlist.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps
`include "ulpi_tb_template.v"

module tb_ams_msc_shadow;
    parameter real HALF = 1.0416667;            // clk_bit 480 MHz

    reg clk_bit = 1'b0;
    always #(HALF) clk_bit = ~clk_bit;
    reg por_n = 1'b0, resetb = 1'b0;

    wire       ulpi_clk, ulpi_dir, ulpi_nxt, ulpi_stp;
    wire [7:0] ulpi_data;

    wire [63:0] dp_v, dm_v;
    wire [63:0] h_g [0:5], h_i [0:5];           // host AFE: t / h / f, dp then dm
    wire [63:0] m_dpg, m_dpi, m_dmg, m_dmi;     // mass-storage device

    // ---------------- host PHY ----------------
    wire h_pu, h_pum, h_hst, h_pdp, h_pdm, h_hp, h_hn, h_hen, h_foe, h_fdat, h_fse0, h_fls;
    wire h_rxen, h_cdren, h_clkrx, h_rxd, h_sq, h_disc, h_rdp, h_rdm, h_rcv;
    ams_ulpi_phy u_phy (
        .clk_bit(clk_bit), .por_n(por_n), .resetb(resetb),
        .ulpi_clk(ulpi_clk), .ulpi_data(ulpi_data), .ulpi_dir(ulpi_dir), .ulpi_nxt(ulpi_nxt),
        .ulpi_stp(ulpi_stp),
        .dp_pullup_en(h_pu), .dm_pullup_en(h_pum), .hs_term_en(h_hst),
        .dp_pulldown_en(h_pdp), .dm_pulldown_en(h_pdm),
        .hs_tx_p(h_hp), .hs_tx_n(h_hn), .hs_tx_en(h_hen),
        .fs_oe(h_foe), .fs_dat(h_fdat), .fs_se0(h_fse0), .fs_ls(h_fls),
        .rx_en_hs(h_rxen), .cdr_en(h_cdren),
        .clk_rx(h_clkrx), .hs_rxd_a(h_rxd), .squelch_a(h_sq), .disc_a(h_disc),
        .rxdp_a(h_rdp), .rxdm_a(h_rdm), .rxrcv_a(h_rcv));
    msc_shadow_afe #(.SEED(37)) h_afe (
        .dp_pullup_en(h_pu), .dm_pullup_en(h_pum), .hs_term_en(h_hst),
        .dp_pulldown_en(h_pdp), .dm_pulldown_en(h_pdm),
        .hs_tx_p(h_hp), .hs_tx_n(h_hn), .hs_tx_en(h_hen),
        .fs_oe(h_foe), .fs_dat(h_fdat), .fs_se0(h_fse0), .fs_ls(h_fls),
        .rx_en_hs(h_rxen), .cdr_en(h_cdren),
        .clk_rx(h_clkrx), .hs_rxd_a(h_rxd), .squelch_a(h_sq), .disc_a(h_disc),
        .rxdp_a(h_rdp), .rxdm_a(h_rdm), .rxrcv_a(h_rcv),
        .dp_v(dp_v), .dm_v(dm_v),
        .t_dpg(h_g[0]), .t_dpi(h_i[0]), .t_dmg(h_g[3]), .t_dmi(h_i[3]),
        .h_dpg(h_g[1]), .h_dpi(h_i[1]), .h_dmg(h_g[4]), .h_dmi(h_i[4]),
        .f_dpg(h_g[2]), .f_dpi(h_i[2]), .f_dmg(h_g[5]), .f_dmi(h_i[5]));

    // ---------------- device: full-speed mass storage ----------------
    fs_msc_bm u_msc (.dp_v(dp_v), .dm_v(dm_v),
                     .dp_g(m_dpg), .dp_i(m_dpi), .dm_g(m_dmg), .dm_i(m_dmi));

    // ---------------- line ----------------
    afe_line_bm u_line (
        .dp_g0(h_g[0]), .dp_i0(h_i[0]), .dp_g1(h_g[1]), .dp_i1(h_i[1]),
        .dp_g2(h_g[2]), .dp_i2(h_i[2]), .dp_g3(m_dpg),  .dp_i3(m_dpi),
        .dp_g4(64'd0),  .dp_i4(64'd0),  .dp_g5(64'd0),  .dp_i5(64'd0),
        .dm_g0(h_g[3]), .dm_i0(h_i[3]), .dm_g1(h_g[4]), .dm_i1(h_i[4]),
        .dm_g2(h_g[5]), .dm_i2(h_i[5]), .dm_g3(m_dmg),  .dm_i3(m_dmi),
        .dm_g4(64'd0),  .dm_i4(64'd0),  .dm_g5(64'd0),  .dm_i5(64'd0),
        .dp_v(dp_v), .dm_v(dm_v));

    initial begin
        if ($test$plusargs("dump")) begin
            $dumpfile("tb_ams_msc_shadow.vcd");
            $dumpvars(0, tb_ams_msc_shadow);
        end
    end

    `define AMS_VDP $bitstoreal(dp_v)
    `define AMS_VDM $bitstoreal(dm_v)
    `include "ams_msc_seq.vh"
endmodule

//-----------------------------------------------------------------------------
// msc_shadow_afe: the event-driven AFE of the host PHY (the afe_*_bm.v
// models), in place of afe_transceiver + afe_receiver + afe_cdr of the AMS
// testbench (same as ams_shadow_afe in tb_ams_link_shadow.v and mouse_shadow_afe in
// tb_ams_mouse_shadow.v)
//-----------------------------------------------------------------------------
module msc_shadow_afe #(parameter SEED = 1) (
    input  wire dp_pullup_en, dm_pullup_en, hs_term_en, dp_pulldown_en, dm_pulldown_en,
    input  wire hs_tx_p, hs_tx_n, hs_tx_en, fs_oe, fs_dat, fs_se0, fs_ls,
    input  wire rx_en_hs, cdr_en,
    output wire clk_rx, hs_rxd_a, squelch_a, disc_a, rxdp_a, rxdm_a, rxrcv_a,
    input  wire [63:0] dp_v, dm_v,
    output wire [63:0] t_dpg, t_dpi, t_dmg, t_dmi,
    output wire [63:0] h_dpg, h_dpi, h_dmg, h_dmi,
    output wire [63:0] f_dpg, f_dpi, f_dmg, f_dmi
);
    wire hx_settled, rx_p, rx_n;
    wire [31:0] skew_err, c_up, c_dn, c_bits;
    afe_term_bm u_term (.dp_pullup_en(dp_pullup_en), .dm_pullup_en(dm_pullup_en), .hs_term_en(hs_term_en),
                        .dp_pulldown_en(dp_pulldown_en), .dm_pulldown_en(dm_pulldown_en),
                        .dp_g(t_dpg), .dp_i(t_dpi), .dm_g(t_dmg), .dm_i(t_dmi));
    afe_hs_tx_bm u_hstx (.TX_IN_P(hs_tx_p), .TX_IN_N(hs_tx_n), .TX_EN(hs_tx_en),
                         .dp_g(h_dpg), .dp_i(h_dpi), .dm_g(h_dmg), .dm_i(h_dmi),
                         .settled(hx_settled), .skew_err(skew_err));
    afe_fsls_bm u_fsls (.fs_oe(fs_oe), .fs_dat(fs_dat), .fs_se0(fs_se0), .fs_ls(fs_ls),
                        .dp_g(f_dpg), .dp_i(f_dpi), .dm_g(f_dmg), .dm_i(f_dmi),
                        .rx_en(1'b1), .dp_v(dp_v), .dm_v(dm_v),
                        .rxdp(rxdp_a), .rxdm(rxdm_a), .rxrcv(rxrcv_a));
    afe_hs_rx_bm   #(.SEED(SEED)) u_hsrx (.dp_v(dp_v), .dm_v(dm_v), .RX_EN(rx_en_hs), .RX_OUT_P(rx_p), .RX_OUT_N(rx_n));
    afe_squelch_bm u_sq (.dp_v(dp_v), .dm_v(dm_v), .en(rx_en_hs), .squelch(squelch_a), .disc(disc_a));
    afe_cdr_bm     #(.SEED(SEED + 1)) u_cdr (.CDR_DATA(rx_p), .CDR_EN(cdr_en), .clk_rx(clk_rx), .hs_rxd(hs_rxd_a),
                                             .n_up(c_up), .n_dn(c_dn), .n_bits(c_bits));
endmodule
