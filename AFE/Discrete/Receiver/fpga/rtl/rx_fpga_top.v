//-----------------------------------------------------------------------------
// rx_fpga_top.v - AMD 7-Series FPGA design for the discrete USB 2.0 receiver
//                 board (AFE/Discrete/Receiver) over FMC LPC
//
// The board implements afe_receiver.va (AFE/veriloga): HS receiver RX_OUT,
// squelch SQUELCH_A, disconnect DISC_A, enable RX_EN.  The FPGA is a
// logic-analyser-style test set for it:
//
//   rx_sampler_7s  RX_OUT 4x oversampled (2 ISERDESE2 + IDELAYE2, 1.92 GS/s),
//                  SQUELCH_A / DISC_A 2x (960 MS/s)
//   rx_capture     triggered ring buffer (2^AW words, 120 MHz), event counters
//   rx_ctrl        UART registers, MCP4822 thresholds (V_SQ, V_DISC), dump
//   host/rx_host.py + rx_decode.py (PC): clock / data recovery, NRZI, unstuff,
//                  PID / CRC check, squelch and disconnect timing
//
// RX_EN gates the board's SQUELCH_A / DISC_A outputs (74LVC1G00 / 1G08); the
// SN65LVDS100 has no enable, so RX_OUT is not gated on the board (doc 6, D2).
//
// Clocking: CLKIN (CLKIN_MHZ) -> MMCME2_BASE, VCO 1200 MHz:
//   CLKOUT0 480 MHz (/2.5) -> BUFIO (ISERDESE2 CLK) and BUFR /4 (120 MHz CLKDIV,
//           capture write side); the MMCM must sit in the clock region of the
//           RX_OUT bank (constraints/rx_board_fmc.xdc)
//   CLKOUT1 200 MHz (/6)   -> BUFG -> IDELAYCTRL reference
//   CLKOUT2  60 MHz (/20)  -> BUFG -> UART, registers, DAC, capture read side
// ISERDESE2 at 960 Mb/s (DDR, 480 MHz BUFIO) needs speed grade -2 in an Artix-7
// HR bank (-1: 950 Mb/s); Kintex-7 HP banks: any grade (doc section 7).
// Reset: rst_btn (active high) or MMCM not locked.
// RX_SIM (Icarus): primitives from fpga/sim/prims_sim.v.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module rx_fpga_top #(
    parameter         CLKIN_DIFF = 0,
    parameter real    CLKIN_MHZ  = 100.0,
    parameter real    MMCM_MULT  = 12.0,     // 100 MHz * 12 / 1 = 1200 MHz VCO
    parameter integer MMCM_DIV   = 1,
    parameter integer BAUD       = 921600,
    parameter integer AW         = 13,
    parameter         DIFF_TERM  = "TRUE"    // "FALSE" when the RX_OUT bank cannot terminate (then fit R43 on the board)
) (
    input  wire clkin_p,
    input  wire clkin_n,
    input  wire rst_btn,
    input  wire uart_rxd,
    output wire uart_txd,

    // FMC LPC <-> receiver board (names as afe_receiver.va)
    input  wire rx_out_p, rx_out_n,     // RX_OUT, LVDS
    input  wire squelch_a,
    input  wire disc_a,
    output wire rx_en,
    output wire hs_term_en,
    output wire dac_cs_n,
    output wire dac_sck,
    output wire dac_sdi,
    input  wire vbus_det,
    output wire led_locked,
    output wire led_active
);

    // ---------------- clocking ----------------
    wire clkin_i, clkfb, c480_u, c200_u, c60_u, clk480, clkdiv, clk200, clk, locked;
    generate
        if (CLKIN_DIFF) begin : g_diff
            IBUFDS u_ibuf (.I(clkin_p), .IB(clkin_n), .O(clkin_i));
        end else begin : g_se
            IBUF u_ibuf (.I(clkin_p), .O(clkin_i));
        end
    endgenerate

    MMCME2_BASE #(
        .CLKIN1_PERIOD    (1000.0 / CLKIN_MHZ),
        .CLKFBOUT_MULT_F  (MMCM_MULT),
        .DIVCLK_DIVIDE    (MMCM_DIV),
        .CLKOUT0_DIVIDE_F (2.5),            // 480 MHz
        .CLKOUT1_DIVIDE   (6),              // 200 MHz
        .CLKOUT2_DIVIDE   (20)              // 60 MHz
    ) u_mmcm (
        .CLKIN1(clkin_i), .CLKFBIN(clkfb), .CLKFBOUT(clkfb), .CLKFBOUTB(),
        .CLKOUT0(c480_u), .CLKOUT0B(), .CLKOUT1(c200_u), .CLKOUT1B(),
        .CLKOUT2(c60_u), .CLKOUT2B(), .CLKOUT3(), .CLKOUT3B(),
        .CLKOUT4(), .CLKOUT5(), .CLKOUT6(),
        .LOCKED(locked), .PWRDWN(1'b0), .RST(rst_btn));
    BUFIO u_bufio (.I(c480_u), .O(clk480));
    BUFR #(.BUFR_DIVIDE("4"), .SIM_DEVICE("7SERIES")) u_bufr (
        .I(c480_u), .O(clkdiv), .CE(1'b1), .CLR(~locked));
    BUFG u_bufg200 (.I(c200_u), .O(clk200));
    BUFG u_bufg60  (.I(c60_u),  .O(clk));

    // resets: clk domain (async assert, sync release), clkdiv domain (sync)
    reg [3:0] rst_sh;
    always @(posedge clk or negedge locked)
        if (!locked) rst_sh <= 4'h0;
        else         rst_sh <= {rst_sh[2:0], 1'b1};
    wire rst_n = rst_sh[3];
    reg [3:0] rstd_sh = 4'hF;                 // configuration value: reset for the first 4 cycles
    always @(posedge clkdiv) rstd_sh <= {rstd_sh[2:0], ~locked};
    wire rst_d = |rstd_sh;

    wire idly_rdy;
    IDELAYCTRL u_idlyctrl (.REFCLK(clk200), .RST(~locked), .RDY(idly_rdy));

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
    wire vbus_i;
    IBUF u_ibvb (.I(vbus_det), .O(vbus_i));
    reg [1:0]  armed_s, done_s, sq_s, dc_s, vb_s, rdy_s;
    reg [15:0] sqc_s1, sqc_s2, dcc_s1, dcc_s2;
    always @(posedge clk) begin
        armed_s <= {armed_s[0], c_armed};
        done_s  <= {done_s[0],  c_done};
        sq_s    <= {sq_s[0], ssq[7]};
        dc_s    <= {dc_s[0], sdc[7]};
        vb_s    <= {vb_s[0], vbus_i};
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
        .spi_gnt(1'b1), .dac_cs_n(dac_cs_n), .dac_sck(dac_sck), .dac_sdi(dac_sdi));

    // registered outputs to the board
    reg rx_en_q, term_q, led_q;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin rx_en_q <= 1'b0; term_q <= 1'b0; led_q <= 1'b0; end
        else begin rx_en_q <= ctrl[0]; term_q <= ctrl[1]; led_q <= ctrl[2] | armed_s[1]; end
    assign rx_en      = rx_en_q;
    assign hs_term_en = term_q;
    assign led_locked = locked;
    assign led_active = led_q | ~sq_s[1];

endmodule
