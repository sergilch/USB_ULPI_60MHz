//-----------------------------------------------------------------------------
// aio_pll_blk.v - PLL block of the all-in-one FPGA design
//
// The body of ../../../PLL/fpga/rtl/pll_fpga_top.v without its MMCM: the 60
// MHz system clock, locked and the reset come from aio_fpga_top.  Same modules
// (pll_ctrl, the repo's usb_clk_gen / usb_pll_lock_det, pll_meas), same
// register map (ID 50h 'P'), same host script (PLL/host/pll_host.py).
// Board clocks, all on BUFGs (bank 35 of the ZedBoard):
//   CLK_BIT_A  FMC LA17_CC (was CLK0_M2C on the PLL board) -> IBUFDS -> BUFG
//   CLK60_A    FMC CLK1_M2C -> IBUFDS -> BUFG (FCNT) and as data (phase)
//   REF_DIG    FMC LA18_P_CC -> IBUF -> BUFG
// Difference: the DAC / ADC SCK / SDI are the board's shared SPI_SCK /
// SPI_SDI (spi_gnt, see aio_glue.v).  Keep in sync with pll_fpga_top.v.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module aio_pll_blk #(
    parameter integer BAUD = 921600,
    parameter integer FW   = 14
) (
    input  wire clk,
    input  wire rst_n,
    input  wire locked,
    input  wire uart_rxd,
    output wire uart_txd,
    input  wire spi_gnt,
    output wire spi_act,
    output wire spi_cs,

    input  wire clk_bit_a_p, clk_bit_a_n,
    input  wire clk60_a_p,   clk60_a_n,
    input  wire ref_dig,
    input  wire muxout,
    output wire adf_clk,
    output wire adf_data,
    output wire adf_le,
    output wire adf_ce,
    output wire vco_off,
    output wire lf_dis,
    output wire cdcm_off,
    output wire ol_en,
    output wire dac_cs_n,
    output wire adc_cs_n,
    output wire spi_sck,
    output wire spi_sdi,
    input  wire adc_sdo,
    output wire refsrc0,
    output wire refsrc1,
    output wire oe24,
    output wire oe19,
    output wire led_pll
);
    // ---------------- board clocks ----------------
    wire cb_i, c60a_i, ref_i, clk_bit, clk60a, ref_clk;
    IBUFDS u_ibcb  (.I(clk_bit_a_p), .IB(clk_bit_a_n), .O(cb_i));
    IBUFDS u_ib60  (.I(clk60_a_p),   .IB(clk60_a_n),   .O(c60a_i));
    IBUF   u_ibref (.I(ref_dig), .O(ref_i));
    BUFG   u_bgcb  (.I(cb_i),   .O(clk_bit));
    BUFG   u_bg60a (.I(c60a_i), .O(clk60a));
    BUFG   u_bgref (.I(ref_i),  .O(ref_clk));

    // ---------------- registers, ADF4002, DAC, ADC ----------------
    wire [7:0]  ctrl;
    wire [1:0]  refsel;
    wire        lol_tgl;
    wire        pll_lock, lol, refsel_err;
    wire [4:0]  fb_div;
    wire [23:0] fcnt;
    wire [15:0] t_lock, t_dld;
    wire [2:0]  phase;
    wire [7:0]  ph_err;
    wire        ph_valid, clk_alive;
    reg  [1:0]  s_lk, s_lol, s_re, s_mx;
    always @(posedge clk) begin
        s_lk <= {s_lk[0], pll_lock}; s_lol <= {s_lol[0], lol};
        s_re <= {s_re[0], refsel_err}; s_mx <= {s_mx[0], muxout};
    end
    wire adf_clk_i, adf_data_i, adf_le_i, sck_i, sdi_i, dcs_i, acs_i;
    pll_ctrl #(.CLK_HZ(60000000), .BAUD(BAUD)) u_ctrl (
        .clk(clk), .rst_n(rst_n), .uart_rxd(uart_rxd), .uart_txd(uart_txd),
        .ctrl(ctrl), .refsel(refsel), .lol_clr_tgl(lol_tgl),
        .status_in({s_mx[1], s_re[1], s_lol[1], s_lk[1], locked}),
        .ph_valid(ph_valid), .clk_alive(clk_alive),
        .fcnt(fcnt), .t_lock(t_lock), .t_dld(t_dld), .phase(phase), .ph_err(ph_err),
        .fb_div(fb_div),
        .adf_clk(adf_clk_i), .adf_data(adf_data_i), .adf_le(adf_le_i),
        .spi_gnt(spi_gnt), .spi_sck(sck_i), .spi_sdi(sdi_i), .dac_cs_n(dcs_i), .adc_cs_n(acs_i),
        .adc_sdo(adc_sdo));

    // ---------------- the PHY's clock generation and lock detector ----------------
    reg [2:0] rb_sh;
    always @(posedge clk_bit or negedge rst_n)
        if (!rst_n) rb_sh <= 3'b000;
        else        rb_sh <= {rb_sh[1:0], 1'b1};
    wire rst_b_n = rb_sh[2];
    wire clk60_u, clk60, ld;
    usb_clk_gen u_cg (
        .clk_bit(clk_bit), .rst_n(rst_b_n), .clk_en(1'b0),
        .clk60(clk60_u), .phase_j(), .ld(ld), .clkout(), .clk_on());
    BUFG u_bg60 (.I(clk60_u), .O(clk60));

    reg [2:0] lc_s;
    always @(posedge clk60 or negedge rst_n)
        if (!rst_n) lc_s <= 3'b000;
        else        lc_s <= {lc_s[1:0], lol_tgl};
    wire lol_clr = lc_s[2] ^ lc_s[1];

    usb_pll_lock_det u_ld (
        .clk_bit(clk_bit), .clk60(clk60), .ld(ld), .ref_clk(ref_clk), .rst_n(rst_n),
        .pll_en(ctrl[0]), .refsel(refsel), .lol_clr(lol_clr),
        .pll_lock(pll_lock), .lol(lol), .fb_div(fb_div), .refsel_err(refsel_err));

    pll_meas #(.FW(FW), .CLK_HZ(60000000)) u_meas (
        .clk(clk), .rst_n(rst_n), .clk60a(clk60a), .ref_clk(ref_clk),
        .clk_bit(clk_bit), .clk60(clk60), .ld(ld), .clk60a_d(c60a_i),
        .pll_en(ctrl[0]), .pll_lock(pll_lock), .muxout(muxout),
        .fcnt(fcnt), .t_lock(t_lock), .t_dld(t_dld),
        .phase(phase), .ph_valid(ph_valid), .ph_err(ph_err), .clk_alive(clk_alive));

    // ---------------- registered outputs to the board ----------------
    reg [15:0] oq;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) oq <= 16'b0000_0000_0011_1100;      // PLL off, outputs inactive
        else begin
            oq[0]  <= ctrl[0];                          // adf_ce
            oq[1]  <= 1'b0;
            oq[2]  <= ~ctrl[0];                         // vco_off
            oq[3]  <= ~ctrl[0];                         // lf_dis
            oq[4]  <= ~ctrl[0];                         // cdcm_off
            oq[5]  <= ~(ctrl[0] & ctrl[1]);             // ol_en (active low below)
            oq[6]  <= (ctrl[3:2] == 2'd1);              // refsrc0
            oq[7]  <= ctrl[3];                          // refsrc1
            oq[8]  <= (ctrl[3:2] == 2'd0);              // oe24
            oq[9]  <= (ctrl[3:2] == 2'd1);              // oe19
            oq[10] <= ctrl[4] | s_lk[1];                // led_pll
            oq[11] <= adf_clk_i;
            oq[12] <= adf_data_i;
            oq[13] <= adf_le_i;
            oq[14] <= sck_i;
            oq[15] <= sdi_i;
        end
    reg dcs_q, acs_q;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin dcs_q <= 1'b1; acs_q <= 1'b1; end
        else begin dcs_q <= dcs_i; acs_q <= acs_i; end
    assign adf_ce   = oq[0];
    assign vco_off  = oq[2];
    assign lf_dis   = oq[3];
    assign cdcm_off = oq[4];
    assign ol_en    = ~oq[5];
    assign refsrc0  = oq[6];
    assign refsrc1  = oq[7];
    assign oe24     = oq[8];
    assign oe19     = oq[9];
    assign led_pll  = oq[10];
    assign adf_clk  = oq[11];
    assign adf_data = oq[12];
    assign adf_le   = oq[13];
    assign spi_sck  = oq[14];
    assign spi_sdi  = oq[15];
    assign dac_cs_n = dcs_q;
    assign adc_cs_n = acs_q;
    assign spi_cs   = ~dcs_q | ~acs_q;
    assign spi_act  = ~dcs_i | ~acs_i | spi_cs;
endmodule
