//-----------------------------------------------------------------------------
// aio_tx_blk.v - transmitter block of the all-in-one FPGA design
//
// The body of ../../../Transmitter/fpga/rtl/tx_fpga_top.v without its MMCM:
// clk60 / clk240 (phase-aligned, OSERDESE2 CLKDIV / CLK) and the reset come
// from aio_fpga_top.  Same modules (tx_ctrl, tx_seq, usb_tx_path,
// usb_afe_tx_if8, tx_piso_7s), same register map (ID 54h 'T'); see the
// transmitter board's doc/tx_board.md.  Differences:
//   - the DAC's SCK / SDI are the board's shared SPI_SCK / SPI_SDI: tx_ctrl
//     starts a frame only with spi_gnt (aio_spi_arb); spi_act / spi_cs report
//     the frame to the arbiter
//   - VBUS_DET is also read by the RX block (one detector on the merged board)
// Keep in sync with tx_fpga_top.v.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module aio_tx_blk #(
    parameter integer BAUD = 921600
) (
    input  wire clk60,
    input  wire clk240,
    input  wire rst_n,
    input  wire locked,
    input  wire uart_rxd,
    output wire uart_txd,
    input  wire spi_gnt,
    output wire spi_act,
    output wire spi_cs,

    output wire tx_in_p_p, tx_in_p_n,
    output wire tx_in_n_p, tx_in_n_n,
    output wire tx_en,
    output wire fs_oe_a,
    output wire fs_dat_a,
    output wire fs_se0_a,
    output wire fs_ls_a,
    output wire fs_suspnd,
    output wire dp_pullup_en_a,
    output wire hs_term_en_a,
    output wire pd_en_a0,
    output wire pd_en_a1,
    output wire dac_cs_n,
    output wire dac_sck,
    output wire dac_sdi,
    input  wire rxrcv_a,
    input  wire rxdp_a,
    input  wire rxdm_a,
    input  wire vbus_det,
    output wire led_active
);
    // ---------------- control ----------------
    wire [7:0]  ctrl, term, pkt_cnt;
    wire [2:0]  pattern, tx_lag;
    wire [15:0] len, gap;
    wire        buf_we;
    wire [5:0]  buf_waddr;
    wire [7:0]  buf_wdata;
    wire [4:0]  tx_lead;
    wire        seq_busy, tx_active;

    reg [3:0] rx_s1, rx_s2;
    always @(posedge clk60) begin
        rx_s1 <= {vbus_det, rxdm_a, rxdp_a, rxrcv_a};
        rx_s2 <= rx_s1;
    end
    wire fs_rx_en = term[5];
    wire rcv_i = fs_rx_en ? rx_s2[0] : 1'b1;
    wire rdp_i = fs_rx_en ? rx_s2[1] : 1'b0;
    wire rdm_i = fs_rx_en ? rx_s2[2] : 1'b0;

    tx_ctrl #(.CLK_HZ(60000000), .BAUD(BAUD)) u_ctrl (
        .clk60(clk60), .rst_n(rst_n), .uart_rxd(uart_rxd), .uart_txd(uart_txd),
        .ctrl(ctrl), .pattern(pattern), .len(len), .gap(gap),
        .buf_we(buf_we), .buf_waddr(buf_waddr), .buf_wdata(buf_wdata),
        .tx_lead(tx_lead), .tx_lag(tx_lag), .term(term),
        .status_in({1'b0, rx_s2[3], rdm_i, rdp_i, rcv_i, locked, tx_active, seq_busy}),
        .pkt_cnt(pkt_cnt),
        .spi_gnt(spi_gnt), .dac_cs_n(dac_cs_n), .dac_sck(dac_sck), .dac_sdi(dac_sdi));
    assign spi_act = ~dac_cs_n;
    assign spi_cs  = ~dac_cs_n;

    // ---------------- TX chain ----------------
    wire [1:0] speed;
    wire       bypass_en, eop_dis, lead_first;
    wire       s_valid, s_last, s_ready;
    wire [7:0] s_data;
    wire       path_busy, tx_done, tx_underrun;
    wire [7:0] txd_v, tx_en_v, tx_se0_v;
    wire [1:0] tx_speed;

    tx_seq u_seq (
        .clk60(clk60), .rst_n(rst_n),
        .go(ctrl[0]), .rpt(ctrl[1]), .pattern(pattern), .speed_cfg(ctrl[3:2]),
        .sync_dis_cfg(ctrl[4]), .len(len), .gap(gap),
        .buf_we(buf_we), .buf_waddr(buf_waddr), .buf_wdata(buf_wdata),
        .speed(speed), .bypass_en(bypass_en), .eop_dis(eop_dis), .lead_first(lead_first),
        .in_valid(s_valid), .in_data(s_data), .in_last(s_last), .in_ready(s_ready),
        .path_busy(path_busy), .seq_busy(seq_busy), .pkt_cnt(pkt_cnt));

    usb_tx_path u_path (
        .clk(clk60), .rst_n(rst_n),
        .speed(speed), .bypass_en(bypass_en), .eop_dis(eop_dis),
        .in_valid(s_valid), .in_ready(s_ready), .in_data(s_data), .in_last(s_last),
        .txd_v(txd_v), .tx_en_v(tx_en_v), .tx_se0_v(tx_se0_v), .tx_speed(tx_speed),
        .busy(path_busy), .tx_done(tx_done), .tx_underrun(tx_underrun));

    wire [7:0] hs_p_v, hs_en_v, fs_oe_v, fs_dat_v, fs_se0_v, any_v;
    wire       fs_ls_q, act;

    usb_afe_tx_if8 u_txif (
        .clk60(clk60), .rst_n(rst_n),
        .txd_v(txd_v), .tx_en_v(tx_en_v), .tx_se0_v(tx_se0_v), .tx_speed(tx_speed),
        .tx_lead(tx_lead), .tx_lag(tx_lag), .lead_first(lead_first),
        .hs_p_v(hs_p_v), .hs_en_v(hs_en_v), .fs_oe_v(fs_oe_v), .fs_dat_v(fs_dat_v),
        .fs_se0_v(fs_se0_v), .any_v(any_v), .fs_ls_q(fs_ls_q), .act(act));

    wire p_ser, n_ser;
    tx_piso_7s u_piso (
        .clk60(clk60), .clk240(clk240), .rst_n(rst_n),
        .hs_p_v(hs_p_v), .hs_en_v(hs_en_v), .fs_oe_v(fs_oe_v), .fs_dat_v(fs_dat_v),
        .fs_se0_v(fs_se0_v), .any_v(any_v), .fs_ls_q(fs_ls_q), .act(act),
        .drv_dis(ctrl[5]), .iso_en(ctrl[6]),
        .hs_tx_p(p_ser), .hs_tx_n(n_ser), .hs_tx_en(tx_en), .fs_oe(fs_oe_a),
        .fs_dat(fs_dat_a), .fs_se0(fs_se0_a), .fs_ls(fs_ls_a), .tx_active(tx_active));

    OBUFDS u_ob_p (.I(p_ser), .O(tx_in_p_p), .OB(tx_in_p_n));
    OBUFDS u_ob_n (.I(n_ser), .O(tx_in_n_p), .OB(tx_in_n_n));

    reg [4:0] term_q;
    always @(posedge clk60 or negedge rst_n)
        if (!rst_n) term_q <= 5'd0; else term_q <= term[4:0];
    assign dp_pullup_en_a = term_q[0];
    assign hs_term_en_a   = term_q[1];
    assign pd_en_a0       = term_q[2];
    assign pd_en_a1       = term_q[3];
    assign fs_suspnd      = term_q[4];
    assign led_active     = tx_active;
endmodule
