//-----------------------------------------------------------------------------
// aio_rx_blk.v - receiver block of the all-in-one FPGA design
//
// The body of ../../../Receiver/fpga/rtl/rx_fpga_top.v without its MMCM and
// IDELAYCTRL: clk480 (BUFIO), clkdiv (BUFR / 4, 120 MHz), the 60 MHz system
// clock, locked and idly_rdy come from aio_fpga_top, whose MMCM must sit in
// the clock region of bank 34 (RX_OUT, SQUELCH_A, DISC_A).  Same modules
// (rx_sampler_7s, rx_capture, rx_ctrl), same register map (ID 52h 'R') and
// the same dump protocol as the receiver board (Receiver/host/rx_host.py).
// Differences on the merged board:
//   - no own VBUS detector: STATUS[4] reads the TX block's VBUS_DET
//   - no own HS termination: CTRL[1] (HS_TERM_EN) has no pin; the single
//     termination is the TX block's TERM[1]
//   - the DAC's SCK / SDI are the shared SPI_SCK / SPI_SDI (spi_gnt, as
//     aio_tx_blk); its CS# is RX_DAC_CS_N_F
// Keep in sync with rx_fpga_top.v.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module aio_rx_blk #(
    parameter integer BAUD      = 921600,
    parameter integer AW        = 13,
    parameter         DIFF_TERM = "TRUE"
) (
    input  wire clk,            // 60 MHz
    input  wire clk480,         // BUFIO
    input  wire clkdiv,         // BUFR / 4
    input  wire rst_n,          // clk domain
    input  wire locked,
    input  wire idly_rdy,
    input  wire uart_rxd,
    output wire uart_txd,
    input  wire spi_gnt,
    output wire spi_act,
    output wire spi_cs,

    input  wire rx_out_p, rx_out_n,
    input  wire squelch_a,
    input  wire disc_a,
    input  wire vbus_det,
    output wire rx_en,
    output wire dac_cs_n,
    output wire dac_sck,
    output wire dac_sdi,
    output wire led_active
);
    reg [3:0] rstd_sh = 4'hF;
    always @(posedge clkdiv) rstd_sh <= {rstd_sh[2:0], ~locked};
    wire rst_d = |rstd_sh;

    // ---------------- sampling and capture ----------------
    wire [4:0]    tap_m, tap_s;
    wire [7:0]    sm, ss, ssq, sdc;
    rx_sampler_7s #(.DIFF_TERM(DIFF_TERM)) u_smp (
        .clk480(clk480), .clkdiv(clkdiv), .rst(rst_d),
        .rx_out_p(rx_out_p), .rx_out_n(rx_out_n), .squelch_a(squelch_a), .disc_a(disc_a),
        .tap_m(tap_m), .tap_s(tap_s), .m(sm), .s(ss), .sq(ssq), .dc(sdc));

    wire          arm_tgl, c_armed, c_done;
    wire [1:0]    trig_src;
    wire [AW-1:0] pre, trig_addr, raddr;
    wire [15:0]   sq_cnt_g, dc_cnt_g;
    wire [31:0]   rdata;
    rx_capture #(.AW(AW)) u_cap (
        .clk(clkdiv), .rst(rst_d), .din({sdc, ssq, ss, sm}),
        .arm_tgl(arm_tgl), .src(trig_src), .pre(pre),
        .armed(c_armed), .done(c_done), .trig_addr(trig_addr),
        .sq_cnt_g(sq_cnt_g), .dc_cnt_g(dc_cnt_g),
        .rclk(clk), .raddr(raddr), .rdata(rdata));

    // ---------------- clkdiv -> clk synchronizers ----------------
    reg [1:0]  armed_s, done_s, sq_s, dc_s, vb_s, rdy_s;
    reg [15:0] sqc_s1, sqc_s2, dcc_s1, dcc_s2;
    always @(posedge clk) begin
        armed_s <= {armed_s[0], c_armed};
        done_s  <= {done_s[0],  c_done};
        sq_s    <= {sq_s[0], ssq[7]};
        dc_s    <= {dc_s[0], sdc[7]};
        vb_s    <= {vb_s[0], vbus_det};
        rdy_s   <= {rdy_s[0], idly_rdy};
        sqc_s1 <= sq_cnt_g; sqc_s2 <= sqc_s1;
        dcc_s1 <= dc_cnt_g; dcc_s2 <= dcc_s1;
    end

    // ---------------- registers, DAC, dump ----------------
    wire [7:0] ctrl;
    rx_ctrl #(.CLK_HZ(60000000), .BAUD(BAUD), .AW(AW)) u_ctrl (
        .clk(clk), .rst_n(rst_n), .uart_rxd(uart_rxd), .uart_txd(uart_txd),
        .ctrl(ctrl), .trig_src(trig_src), .arm_tgl(arm_tgl), .pre(pre),
        .tap_m(tap_m), .tap_s(tap_s),
        .status_in({dc_s[1], sq_s[1], vb_s[1], done_s[1], armed_s[1], rdy_s[1], locked}),
        .trig_addr(trig_addr), .sq_cnt(sqc_s2), .dc_cnt(dcc_s2),
        .raddr(raddr), .rdata(rdata),
        .spi_gnt(spi_gnt), .dac_cs_n(dac_cs_n), .dac_sck(dac_sck), .dac_sdi(dac_sdi));
    assign spi_act = ~dac_cs_n;
    assign spi_cs  = ~dac_cs_n;

    reg rx_en_q, led_q;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin rx_en_q <= 1'b0; led_q <= 1'b0; end
        else begin rx_en_q <= ctrl[0]; led_q <= ctrl[2] | armed_s[1]; end
    assign rx_en      = rx_en_q;
    assign led_active = led_q | ~sq_s[1];
endmodule
