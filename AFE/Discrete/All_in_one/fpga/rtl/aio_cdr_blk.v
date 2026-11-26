//-----------------------------------------------------------------------------
// aio_cdr_blk.v - CDR block of the all-in-one FPGA design
//
// The body of ../../../CDR/fpga/rtl/cdr_fpga_top.v without its MMCM and
// IDELAYCTRL: the 60 MHz system clock, clk240 (OSERDESE2 CLK of DPAT), locked,
// idly_rdy and the reset come from aio_fpga_top.  Same modules (cdr_ctrl,
// cdr_txgen, cdr_rxchk, the repo's usb_tx_path / usb_rx_decoder8), same
// register map (ID 43h 'C'), same host script (CDR/host/cdr_host.py).
// CLK_RX (FMC CLK0_M2C) and HS_RXD (LA00_CC) are in bank 34 (BUFIO / BUFR
// clock the ISERDESE2 of their own bank only).
// Differences on the merged board:
//   - EP57 input D2 carries the RX block's line copy (NB6L14 U216 Q1): DSEL
//     = CTRL[2] ? 01 (FPGA pattern) : CTRL[6] ? 10 (RX loop) : 00 (SMA).
//     CTRL[6] was the LED bit of the CDR board; LED_OK now only shows RXOK != 0.
//   - the DAC / ADC SCK / SDI are the shared SPI_SCK / SPI_SDI (spi_gnt,
//     see aio_glue.v)
// Keep in sync with cdr_fpga_top.v.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module aio_cdr_blk #(
    parameter integer BAUD   = 921600,
    parameter integer FW     = 20,
    parameter integer SNAP_W = 7
) (
    input  wire clk,
    input  wire clk240,
    input  wire rst_n,
    input  wire locked,
    input  wire idly_rdy,
    input  wire uart_rxd,
    output wire uart_txd,
    input  wire spi_gnt,
    output wire spi_act,
    output wire spi_cs,

    input  wire clk_rx_p, clk_rx_n,
    input  wire hs_rxd_p, hs_rxd_n,
    output wire dpat_p,   dpat_n,
    output wire cdr_en,
    output wire cdr_set,
    output wire dsel0,
    output wire dsel1,
    output wire vco_off,
    output wire csw_ext,
    output wire csw_dac,
    output wire dac_cs_n,
    output wire adc_cs_n,
    output wire spi_sck,
    output wire spi_sdi,
    input  wire adc_sdo,
    output wire led_alive,
    output wire led_ok
);
    // reset / default IDELAY tap of HS_RXD: Vivado times the IDELAY at IDELAY_VALUE,
    // so it must equal the tap cdr_ctrl loads at reset (eye centre, see the XDC)
    localparam [4:0] IDLY0 = 5'd22;
    // ---------------- registers, DACs, ADC ----------------
    wire [7:0]  ctrl, txlen, txgap;
    wire [1:0]  txmode;
    wire [4:0]  idly;
    wire        idly_ld;
    wire [23:0] fcnt, txpkt;
    reg  [23:0] q_rxpkt, q_rxok, q_losts;
    reg  [7:0]  q_lostmax, q_lostmin;
    reg  [31:0] q_pbits, q_perr;
    wire        tx_busy;
    reg         rx_alive, snap_ok;
    reg  [1:0]  s_psync;
    wire        sck_i, sdi_i, dcs_i, acs_i;
    cdr_ctrl #(.CLK_HZ(60000000), .BAUD(BAUD), .IDLY_RST(IDLY0)) u_ctrl (
        .clk(clk), .rst_n(rst_n), .uart_rxd(uart_rxd), .uart_txd(uart_txd),
        .ctrl(ctrl), .txmode(txmode), .txlen(txlen), .txgap(txgap), .idly(idly), .idly_ld(idly_ld),
        .status({2'b00, snap_ok, tx_busy, s_psync[1], idly_rdy, rx_alive, locked}),
        .fcnt(fcnt), .txpkt(txpkt), .rxpkt(q_rxpkt), .rxok(q_rxok), .losts(q_losts),
        .lostmax(q_lostmax), .lostmin(q_lostmin), .pbits(q_pbits), .perr(q_perr),
        .spi_gnt(spi_gnt), .spi_sck(sck_i), .spi_sdi(sdi_i), .dac_cs_n(dcs_i), .adc_cs_n(acs_i), .adc_sdo(adc_sdo));
    wire clr = ctrl[7];

    // ---------------- pattern -> OSERDESE2 -> DPAT ----------------
    wire [7:0] lw;
    cdr_txgen u_tx (
        .clk(clk), .rst_n(rst_n), .mode(txmode), .txlen(txlen), .txgap(txgap), .clr(clr),
        .lw(lw), .txpkt(txpkt), .busy(tx_busy));
    reg [2:0] os_rst;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) os_rst <= 3'b111;
        else        os_rst <= {os_rst[1:0], 1'b0};
    wire dpat_o;
    OSERDESE2 #(
        .DATA_RATE_OQ("DDR"), .DATA_RATE_TQ("SDR"), .DATA_WIDTH(8), .TRISTATE_WIDTH(1),
        .SERDES_MODE("MASTER"), .INIT_OQ(1'b1), .SRVAL_OQ(1'b1)
    ) u_oser (
        .CLK(clk240), .CLKDIV(clk), .RST(os_rst[2]), .OCE(1'b1), .TCE(1'b0),
        .D1(lw[0]), .D2(lw[1]), .D3(lw[2]), .D4(lw[3]), .D5(lw[4]), .D6(lw[5]), .D7(lw[6]), .D8(lw[7]),
        .T1(1'b0), .T2(1'b0), .T3(1'b0), .T4(1'b0), .TBYTEIN(1'b0),
        .SHIFTIN1(1'b0), .SHIFTIN2(1'b0), .OQ(dpat_o), .TQ(), .OFB(), .TFB(), .TBYTEOUT(),
        .SHIFTOUT1(), .SHIFTOUT2());
    OBUFDS u_obpat (.I(dpat_o), .O(dpat_p), .OB(dpat_n));

    // ---------------- CLK_RX, HS_RXD -> IDELAYE2 -> ISERDESE2 ----------------
    wire crx_i, clk_rxio, clk_rxw, rxd_i, rxd_d;
    IBUFDS #(.DIFF_TERM("TRUE")) u_ibcrx (.I(clk_rx_p), .IB(clk_rx_n), .O(crx_i));
    BUFIO u_bio (.I(crx_i), .O(clk_rxio));
    BUFR #(.BUFR_DIVIDE("8"), .SIM_DEVICE("7SERIES")) u_bufr (.I(crx_i), .CE(1'b1), .CLR(1'b0), .O(clk_rxw));
    IBUFDS #(.DIFF_TERM("TRUE")) u_ibrxd (.I(hs_rxd_p), .IB(hs_rxd_n), .O(rxd_i));
    IDELAYE2 #(
        .IDELAY_TYPE("VAR_LOAD"), .DELAY_SRC("IDATAIN"), .HIGH_PERFORMANCE_MODE("TRUE"),
        .REFCLK_FREQUENCY(200.0), .IDELAY_VALUE(IDLY0), .SIGNAL_PATTERN("DATA"), .PIPE_SEL("FALSE"),
        .CINVCTRL_SEL("FALSE")
    ) u_idly (
        .C(clk), .LD(idly_ld), .CNTVALUEIN(idly), .CE(1'b0), .INC(1'b0), .LDPIPEEN(1'b0),
        .REGRST(1'b0), .CINVCTRL(1'b0), .DATAIN(1'b0), .IDATAIN(rxd_i), .DATAOUT(rxd_d),
        .CNTVALUEOUT());
    // clk_rxw domain reset: asynchronous assert, release after 3 clk_rxw edges
    reg [2:0] rr_sh;
    always @(posedge clk_rxw or negedge rst_n)
        if (!rst_n) rr_sh <= 3'b000;
        else        rr_sh <= {rr_sh[1:0], 1'b1};
    wire rst_r_n = rr_sh[2];
    wire [8:1] q;
    ISERDESE2 #(
        .INTERFACE_TYPE("NETWORKING"), .DATA_RATE("SDR"), .DATA_WIDTH(8), .NUM_CE(1),
        .IOBDELAY("IFD"), .SERDES_MODE("MASTER"), .OFB_USED("FALSE"), .DYN_CLKDIV_INV_EN("FALSE"),
        .DYN_CLK_INV_EN("FALSE")
    ) u_iser (
        .CLK(clk_rxio), .CLKB(~clk_rxio), .CLKDIV(clk_rxw), .CLKDIVP(1'b0), .OCLK(1'b0), .OCLKB(1'b0),
        .RST(~rst_r_n), .CE1(1'b1), .CE2(1'b1), .BITSLIP(1'b0), .D(1'b0), .DDLY(rxd_d), .OFB(1'b0),
        .DYNCLKDIVSEL(1'b0), .DYNCLKSEL(1'b0), .SHIFTIN1(1'b0), .SHIFTIN2(1'b0),
        .Q1(q[1]), .Q2(q[2]), .Q3(q[3]), .Q4(q[4]), .Q5(q[5]), .Q6(q[6]), .Q7(q[7]), .Q8(q[8]),
        .O(), .SHIFTOUT1(), .SHIFTOUT2());
    reg [7:0] w;
    always @(posedge clk_rxw) w <= {q[1], q[2], q[3], q[4], q[5], q[6], q[7], q[8]};

    // ---------------- RX checker (clk_rxw) ----------------
    reg  [1:0]  rq_s, clr_s;
    reg         clr_q;
    reg         snap_req, clr_t;
    wire        snap_ack, psync;
    wire [23:0] s_rxpkt, s_rxok, s_losts;
    wire [7:0]  s_lostmax, s_lostmin;
    wire [31:0] s_pbits, s_perr;
    always @(posedge clk_rxw or negedge rst_r_n)
        if (!rst_r_n) begin rq_s <= 2'b00; clr_s <= 2'b00; clr_q <= 1'b0; end
        else begin rq_s <= {rq_s[0], snap_req}; clr_s <= {clr_s[0], clr_t}; clr_q <= clr_s[1]; end
    cdr_rxchk u_chk (
        .clk(clk_rxw), .rst_n(rst_r_n), .w(w), .txlen(txlen), .clr(clr_s[1] ^ clr_q),
        .snap_req(rq_s[1]), .snap_ack(snap_ack),
        .s_rxpkt(s_rxpkt), .s_rxok(s_rxok), .s_losts(s_losts), .s_lostmax(s_lostmax),
        .s_lostmin(s_lostmin), .s_pbits(s_pbits), .s_perr(s_perr), .psync(psync));

    // ---------------- snapshot handshake (clk) ----------------
    reg [1:0]        ack_s;
    reg [SNAP_W-1:0] sn_cnt;
    reg [9:0]        sn_to;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ack_s <= 2'b00; snap_req <= 1'b0; clr_t <= 1'b0; sn_cnt <= 0; sn_to <= 0; snap_ok <= 1'b0;
            q_rxpkt <= 0; q_rxok <= 0; q_losts <= 0; q_lostmax <= 0; q_lostmin <= 8'hFF;
            q_pbits <= 0; q_perr <= 0; s_psync <= 2'b00;
        end else begin
            ack_s   <= {ack_s[0], snap_ack};
            s_psync <= {s_psync[0], psync};
            if (clr) clr_t <= ~clr_t;
            sn_cnt  <= sn_cnt + 1'b1;
            if (ack_s[1] == snap_req) begin
                if (sn_cnt == 0) begin
                    // shadow stable (ack seen, req not yet toggled): take it, request the next
                    q_rxpkt <= s_rxpkt; q_rxok <= s_rxok; q_losts <= s_losts;
                    q_lostmax <= s_lostmax; q_lostmin <= s_lostmin; q_pbits <= s_pbits; q_perr <= s_perr;
                    snap_req <= ~snap_req; sn_to <= 0; snap_ok <= 1'b1;
                end
            end else if (sn_to != 10'h3FF) sn_to <= sn_to + 10'd1;
            else snap_ok <= 1'b0;                          // CLK_RX stopped: keep the last values
        end
    end

    // ---------------- FCNT: CLK_RX / 8 against clk ----------------
    reg [23:0] g_bin, g_gray;
    always @(posedge clk_rxw or negedge rst_r_n)
        if (!rst_r_n) begin g_bin <= 24'd0; g_gray <= 24'd0; end
        else begin g_bin <= g_bin + 24'd1; g_gray <= (g_bin + 24'd1) ^ ((g_bin + 24'd1) >> 1); end
    reg  [23:0] gs1, gs2, f_last, f_out;
    reg  [FW-1:0] f_gate;
    reg  [23:0] gb;
    integer     b;
    always @(*) begin
        gb[23] = gs2[23];
        for (b = 22; b >= 0; b = b - 1) gb[b] = gb[b + 1] ^ gs2[b];
    end
    reg [5:0] al_cnt;
    reg       al_p;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            gs1 <= 0; gs2 <= 0; f_last <= 0; f_out <= 0; f_gate <= 0; al_cnt <= 0; al_p <= 0;
            rx_alive <= 1'b0;
        end else begin
            gs1 <= g_gray; gs2 <= gs1;
            f_gate <= f_gate + 1'b1;
            if (f_gate == 0) begin f_out <= gb - f_last; f_last <= gb; end
            al_p <= gb[2];
            if (gb[2] != al_p) begin al_cnt <= 0; rx_alive <= 1'b1; end
            else if (al_cnt != 6'h3F) al_cnt <= al_cnt + 6'd1;
            else rx_alive <= 1'b0;
        end
    end
    assign fcnt = rx_alive ? f_out : 24'd0;

    // ---------------- registered outputs to the board ----------------
    reg [11:0] oq;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) oq <= 12'b0110_0000_0110;           // CDR off, flip-flops set, VCO on, CS# high
        else begin
            oq[0]  <= ctrl[0];                          // cdr_en
            oq[1]  <= ~ctrl[0] | ctrl[1];               // cdr_set
            oq[2]  <= ctrl[2];                          // dsel0: EP57 D1 (FPGA pattern)
            oq[3]  <= ctrl[6] & ~ctrl[2];               // dsel1: EP57 D2 (RX loop, CTRL[6])
            oq[4]  <= ctrl[5];                          // vco_off
            oq[5]  <= (ctrl[4:3] == 2'd1);              // csw_ext
            oq[6]  <= (ctrl[4:3] == 2'd2);              // csw_dac
            oq[7]  <= sck_i;
            oq[8]  <= sdi_i;
            oq[9]  <= dcs_i;
            oq[10] <= acs_i;
            oq[11] <= (q_rxok != 24'd0);                // led_ok
        end
    assign cdr_en    = oq[0];
    assign cdr_set   = oq[1];
    assign dsel0     = oq[2];
    assign dsel1     = oq[3];
    assign vco_off   = oq[4];
    assign csw_ext   = oq[5];
    assign csw_dac   = oq[6];
    assign spi_sck   = oq[7];
    assign spi_sdi   = oq[8];
    assign dac_cs_n  = oq[9];
    assign adc_cs_n  = oq[10];
    assign led_ok    = oq[11];
    assign led_alive = rx_alive;
    assign spi_cs    = ~oq[9] | ~oq[10];
    assign spi_act   = ~dcs_i | ~acs_i | spi_cs;

endmodule
