//-----------------------------------------------------------------------------
// cdr_fpga_top.v - FPGA design for the discrete USB 2.0 CDR board (FMC LPC)
//
// Clocks
//   clk     60 MHz system clock (MMCM CLKOUT0 from the carrier oscillator,
//           VCO 1200 MHz): UART registers, SPI, pattern generator, OSERDESE2
//           CLKDIV.  clk240 (CLKOUT1) = OSERDESE2 CLK (DDR 8:1 -> 480 Mb/s),
//           clk200 (CLKOUT2) = IDELAYCTRL reference.
//   CLK_RX  the board's recovered clock (NB6L14 Q2, FMC CLK0_M2C): BUFIO ->
//           ISERDESE2 CLK, BUFR /8 -> clk_rxw = ISERDESE2 CLKDIV and the RX
//           checker (60 MHz when locked to 480 Mb/s).  CLK0_M2C and the
//           HS_RXD pair (LA00_CC) must be in the same I/O bank (BUFIO / BUFR
//           are regional; constraints/cdr_board_fmc.xdc).
// Data
//   DPAT    pattern (cdr_txgen) -> OSERDESE2 -> OBUFDS (LVDS_25, LA01) -> EP57 D1.
//   HS_RXD  (B of the board's phase detector, LA00) -> IBUFDS (DIFF_TERM) ->
//           IDELAYE2 (VAR_LOAD, tap IDLY) -> ISERDESE2 (1:8 SDR) -> cdr_rxchk.
//           ISERDESE2 delivers the first bit on Q8 (OSERDESE2 sends D1 first):
//           w[i] = Q[8 - i].
// Board controls: CDR_EN (NB6L14 EN), CDR_SET = ~CDR_EN | FF_SET (MC100EP29
//   set inputs), DSEL0/1 (EP57: 00 SMA, 01 FPGA pattern), VCO_OFF, CSW_EXT /
//   CSW_DAC (coarse source switch), SPI to the MCP4822 / MCP3201.
// RX -> system domain: snapshot handshake (snap_req / snap_ack toggles, 2-FF
//   synchronisers; the shadow registers are stable while req == ack); clr as
//   a toggle.  FCNT: 24-bit Gray counter on clk_rxw, synchronised and
//   differenced over a gate of 2^FW clk cycles.  rx_alive: clk_rxw counter bit
//   2 toggled within the last 64 clk cycles.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module cdr_fpga_top #(
    parameter         CLKIN_DIFF = 0,
    parameter real    CLKIN_MHZ  = 100.0,
    parameter real    MMCM_MULT  = 12.0,     // 100 MHz * 12 / 1 = 1200 MHz VCO
    parameter integer MMCM_DIV   = 1,
    parameter integer BAUD       = 921600,
    parameter integer FW         = 20,       // FCNT gate 2^FW clk cycles (17.5 ms)
    parameter integer SNAP_W     = 7         // snapshot request every 2^SNAP_W clk cycles
) (
    input  wire clkin_p,
    input  wire clkin_n,
    input  wire rst_btn,
    input  wire uart_rxd,
    output wire uart_txd,
    // FMC
    input  wire clk_rx_p, clk_rx_n,         // CLK_RX,  CLK0_M2C
    input  wire hs_rxd_p, hs_rxd_n,         // HS_RXD,  LA00_CC
    output wire dpat_p,   dpat_n,           // pattern, LA01_CC
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

    // ---------------- system clocks ----------------
    wire clkin_i, clkfb, c60_u, c240_u, c200_u, clk, clk240, clk200, locked;
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
        .CLKOUT0_DIVIDE_F (20.0),            // 60 MHz
        .CLKOUT1_DIVIDE   (5),               // 240 MHz
        .CLKOUT2_DIVIDE   (6)                // 200 MHz
    ) u_mmcm (
        .CLKIN1(clkin_i), .CLKFBIN(clkfb), .CLKFBOUT(clkfb), .CLKFBOUTB(),
        .CLKOUT0(c60_u), .CLKOUT0B(), .CLKOUT1(c240_u), .CLKOUT1B(),
        .CLKOUT2(c200_u), .CLKOUT2B(), .CLKOUT3(), .CLKOUT3B(),
        .CLKOUT4(), .CLKOUT5(), .CLKOUT6(),
        .LOCKED(locked), .PWRDWN(1'b0), .RST(rst_btn));
    BUFG u_bg60  (.I(c60_u),  .O(clk));
    BUFG u_bg240 (.I(c240_u), .O(clk240));
    BUFG u_bg200 (.I(c200_u), .O(clk200));
    reg [3:0] rst_sh;
    always @(posedge clk or negedge locked)
        if (!locked) rst_sh <= 4'h0;
        else         rst_sh <= {rst_sh[2:0], 1'b1};
    wire rst_n = rst_sh[3];

    // ---------------- registers, DACs, ADC ----------------
    wire [7:0]  ctrl, txlen, txgap;
    wire [1:0]  txmode;
    wire [4:0]  idly;
    wire        idly_ld;
    wire [23:0] fcnt, txpkt;
    reg  [23:0] q_rxpkt, q_rxok, q_losts;
    reg  [7:0]  q_lostmax, q_lostmin;
    reg  [31:0] q_pbits, q_perr;
    wire        idly_rdy, tx_busy;
    reg         rx_alive, snap_ok;
    reg  [1:0]  s_psync;
    wire        sck_i, sdi_i, dcs_i, acs_i;
    cdr_ctrl #(.CLK_HZ(60000000), .BAUD(BAUD)) u_ctrl (
        .clk(clk), .rst_n(rst_n), .uart_rxd(uart_rxd), .uart_txd(uart_txd),
        .ctrl(ctrl), .txmode(txmode), .txlen(txlen), .txgap(txgap), .idly(idly), .idly_ld(idly_ld),
        .status({2'b00, snap_ok, tx_busy, s_psync[1], idly_rdy, rx_alive, locked}),
        .fcnt(fcnt), .txpkt(txpkt), .rxpkt(q_rxpkt), .rxok(q_rxok), .losts(q_losts),
        .lostmax(q_lostmax), .lostmin(q_lostmin), .pbits(q_pbits), .perr(q_perr),
        .spi_gnt(1'b1), .spi_sck(sck_i), .spi_sdi(sdi_i), .dac_cs_n(dcs_i), .adc_cs_n(acs_i), .adc_sdo(adc_sdo));
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
    IDELAYCTRL u_idc (.REFCLK(clk200), .RST(~locked), .RDY(idly_rdy));
    IDELAYE2 #(
        .IDELAY_TYPE("VAR_LOAD"), .DELAY_SRC("IDATAIN"), .HIGH_PERFORMANCE_MODE("TRUE"),
        .REFCLK_FREQUENCY(200.0), .IDELAY_VALUE(0), .SIGNAL_PATTERN("DATA"), .PIPE_SEL("FALSE"),
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
            oq[3]  <= 1'b0;                             // dsel1
            oq[4]  <= ctrl[5];                          // vco_off
            oq[5]  <= (ctrl[4:3] == 2'd1);              // csw_ext
            oq[6]  <= (ctrl[4:3] == 2'd2);              // csw_dac
            oq[7]  <= sck_i;
            oq[8]  <= sdi_i;
            oq[9]  <= dcs_i;
            oq[10] <= acs_i;
            oq[11] <= ctrl[6] | (q_rxok != 24'd0);      // led_ok
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

endmodule
