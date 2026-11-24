//-----------------------------------------------------------------------------
// tx_fpga_top.v - AMD 7-Series FPGA design that drives the discrete USB 2.0
//                 transmitter board (AFE/Discrete/Transmitter) over FMC LPC
//
// The FPGA is the digital half of the PHY's TX path, built from the repo's RTL:
//
//   tx_ctrl (UART regs, DAC) ---------------------------------------------+
//   tx_seq (Test_Packet / user / Test_J / Test_K / chirp / PRBS7 bytes)   |
//     -> usb_tx_path      (repo: bit stuffer, NRZI, usb_tx_serializer8)   |
//     -> usb_afe_tx_if8   (repo: driver select, TX_LEAD / TX_LAG window)  |
//     -> tx_piso_7s       (OSERDESE2 x 7, replaces usb_tx_piso)           |
//     -> FMC: TX_IN_P, TX_IN_N (LVDS), TX_EN, FS_OE, FS_DAT, FS_SE0, FS_LS|
//   TERM register -> DP_PULLUP_EN, HS_TERM_EN, PD_EN0, PD_EN1, FS_SUSPND  |
//   MCP4821 SPI   -> HS amplitude (V_CTL)  <------------------------------+
//   FMC inputs RXRCV / RXDP / RXDM (TUSB1105), VBUS_DET -> STATUS register
//
// Board pin semantics are those of afe_transceiver.va (AFE/veriloga), i.e. of
// the ASIC's AFE pins; the board adds only the glue described in
// doc/tx_board.md section 4 (TX_IN_P/N via SN65LVDT101, VO = FS_DAT ^ FS_LS ...).
//
// Clocking: CLKIN (board oscillator, CLKIN_MHZ) -> MMCME2_BASE, VCO 960 MHz
//   -> clk60 (/16) and clk240 (/4), both on BUFG, phase-aligned.  OSERDESE2
//   DDR 8:1 gives 480 Mbit/s per pin.  The defaults cover a 100 MHz or a
//   200 MHz oscillator (MMCM_MULT / MMCM_DIV); set CLKIN_DIFF = 1 for a
//   differential oscillator (AC701 / KC705 SYSCLK).
// Reset: rst_btn (active high, any board button) or MMCM not locked.
//
// I/O standards (constraints/tx_board_fmc.xdc): the LA pins sit in the FMC
//   VADJ bank.  VADJ = 2.5 V: LVDS_25 + LVCMOS25 (HR bank);  VADJ = 1.8 V:
//   LVDS + LVCMOS18 (HP bank).  The board's translators accept 1.65 .. 3.6 V.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tx_fpga_top #(
    parameter        CLKIN_DIFF = 0,
    parameter real   CLKIN_MHZ  = 100.0,
    parameter real   MMCM_MULT  = 48.0,     // 100 MHz * 48 / 5 = 960 MHz VCO
    parameter integer MMCM_DIV  = 5,
    parameter integer BAUD      = 115200
) (
    input  wire clkin_p,          // single-ended clock: use clkin_p, tie clkin_n off
    input  wire clkin_n,
    input  wire rst_btn,
    input  wire uart_rxd,
    output wire uart_txd,

    // FMC LPC -> transmitter board (names as afe_transceiver.va)
    output wire tx_in_p_p, tx_in_p_n,   // TX_IN_P, LVDS pair
    output wire tx_in_n_p, tx_in_n_n,   // TX_IN_N, LVDS pair
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
    output wire led_locked,
    output wire led_active
);

    // ---------------- clocking ----------------
    wire clkin_i, clkfb, clk60_u, clk240_u, clk60, clk240, locked;
    generate
        if (CLKIN_DIFF) begin : g_diff
            IBUFDS u_ibuf (.I(clkin_p), .IB(clkin_n), .O(clkin_i));
        end else begin : g_se
            IBUF u_ibuf (.I(clkin_p), .O(clkin_i));
            wire unused_n = clkin_n;
        end
    endgenerate

`ifdef TX_PISO_SIM
    // simulation: ideal clocks from the testbench (clkin_p = clk60, clkin_n = clk240)
    assign clk60  = clkin_p;
    assign clk240 = clkin_n;
    assign locked = 1'b1;
`else
    MMCME2_BASE #(
        .CLKIN1_PERIOD    (1000.0 / CLKIN_MHZ),
        .CLKFBOUT_MULT_F  (MMCM_MULT),
        .DIVCLK_DIVIDE    (MMCM_DIV),
        .CLKOUT0_DIVIDE_F (16.0),          // 60 MHz
        .CLKOUT1_DIVIDE   (4)              // 240 MHz
    ) u_mmcm (
        .CLKIN1   (clkin_i),
        .CLKFBIN  (clkfb),
        .CLKFBOUT (clkfb),
        .CLKFBOUTB(),
        .CLKOUT0  (clk60_u),
        .CLKOUT0B (),
        .CLKOUT1  (clk240_u),
        .CLKOUT1B (),
        .CLKOUT2(), .CLKOUT2B(), .CLKOUT3(), .CLKOUT3B(),
        .CLKOUT4(), .CLKOUT5(), .CLKOUT6(),
        .LOCKED   (locked),
        .PWRDWN   (1'b0),
        .RST      (rst_btn)
    );
    BUFG u_bufg60  (.I(clk60_u),  .O(clk60));
    BUFG u_bufg240 (.I(clk240_u), .O(clk240));
`endif

    // reset: asynchronous assert, release synchronous to clk60
    reg [3:0] rst_sh;
    always @(posedge clk60 or negedge locked)
        if (!locked) rst_sh <= 4'h0; else rst_sh <= {rst_sh[2:0], ~rst_btn};
    wire rst_n = rst_sh[3];

    // ---------------- control ----------------
    wire [7:0]  ctrl, term, pkt_cnt;
    wire [2:0]  pattern, tx_lag;
    wire [15:0] len, gap;
    wire        buf_we;
    wire [5:0]  buf_waddr;
    wire [7:0]  buf_wdata;
    wire [4:0]  tx_lead;
    wire        seq_busy, tx_active;

    // input synchronizers (TUSB1105 receivers, VBUS detect)
    reg [3:0] rx_s1, rx_s2;
    always @(posedge clk60) begin
        rx_s1 <= {vbus_det, rxdm_a, rxdp_a, rxrcv_a};
        rx_s2 <= rx_s1;
    end
    // FS_RX_EN = 0 emulated on the FPGA side (afe_fsls_xcvr isolated values,
    // spec 3.4): RXDP = RXDM = 0, RXRCV = 1
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
        .dac_cs_n(dac_cs_n), .dac_sck(dac_sck), .dac_sdi(dac_sdi));

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

    wire p_ser, n_ser, en_ser, oe_ser, dat_ser, se0_ser, ls_ser;

    tx_piso_7s u_piso (
        .clk60(clk60), .clk240(clk240), .rst_n(rst_n),
        .hs_p_v(hs_p_v), .hs_en_v(hs_en_v), .fs_oe_v(fs_oe_v), .fs_dat_v(fs_dat_v),
        .fs_se0_v(fs_se0_v), .any_v(any_v), .fs_ls_q(fs_ls_q), .act(act),
        .drv_dis(ctrl[5]), .iso_en(ctrl[6]),
        .hs_tx_p(p_ser), .hs_tx_n(n_ser), .hs_tx_en(en_ser), .fs_oe(oe_ser),
        .fs_dat(dat_ser), .fs_se0(se0_ser), .fs_ls(ls_ser), .tx_active(tx_active));

    // ---------------- output buffers ----------------
    OBUFDS u_ob_p (.I(p_ser), .O(tx_in_p_p), .OB(tx_in_p_n));
    OBUFDS u_ob_n (.I(n_ser), .O(tx_in_n_p), .OB(tx_in_n_n));
    assign tx_en    = en_ser;
    assign fs_oe_a  = oe_ser;
    assign fs_dat_a = dat_ser;
    assign fs_se0_a = se0_ser;
    assign fs_ls_a  = ls_ser;

    reg [4:0] term_q;
    always @(posedge clk60 or negedge rst_n)
        if (!rst_n) term_q <= 5'd0; else term_q <= term[4:0];
    assign dp_pullup_en_a = term_q[0];
    assign hs_term_en_a   = term_q[1];
    assign pd_en_a0       = term_q[2];
    assign pd_en_a1       = term_q[3];
    assign fs_suspnd      = term_q[4];

    assign led_locked = locked;
    assign led_active = tx_active;

endmodule
