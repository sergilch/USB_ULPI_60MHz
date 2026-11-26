//-----------------------------------------------------------------------------
// tb_aio_fpga_top.v - integration test of the all-in-one FPGA design
//
//   ./run_sim.sh   (iverilog -g2005 -DAIO_SIM -DTX_PISO_SIM prims_sim.v
//                   <repo>/afe_cdr_bm.v <repo>/usb_*.v <block>/fpga/rtl/*.v
//                   ../rtl/aio_*.v tb_aio_fpga_top.v; see run_sim.sh)
//
// The block designs have their own detailed testbenches (Transmitter /
// Receiver / PLL / CDR fpga/sim).  This one checks what the merge adds:
// the shared clocking, the UART block select, the shared SPI bus and the
// on-board loops.
//
// Board model (AFE/Discrete/All_in_one):
//   line      = TX_IN_P while TX_EN (HS driver), J (1) otherwise
//   RX        RX_OUT follows the line 0.9 ns late; SQUELCH_A falls 11 ns after
//             TX_EN rises and rises 20 ns after it falls; RX_EN = 0 forces 1
//   CDR       afe_cdr_bm on the EP57 output: D1 = DPAT (DSEL 01), D2 = the
//             line (DSEL 10, NB6L14 U216 Q1), D0 SMA not driven (J)
//   PLL       ideal 480 MHz CLK_BIT_A, CLK60_A = /8, REF_DIG 24 MHz
//   SPI       six CS# on one SCK / SDI: MCP4821 / MCP4822 frame decoders,
//             MCP3201 models with their own DOUT (PLL / CDR ADC codes)
// Checks
//   1 SPI after reset: TX DAC 1200, RX DAC 1320 / 1210, PLL DAC 3150, CDR
//     DAC 2600 / 3120 all arrive intact although all engines (and the PLL /
//     CDR ADC conversions) want the bus at once; never two CS# low; no SCK
//     edge without exactly one CS# low (whole run)
//   2 UART select: SW1:SW0 = 00 / 01 / 10 / 11 -> ID T / R / P / C
//   3 TX HS Test_Packets -> RX: capture triggered by SQUELCH_A, SQ_CNT > 0
//   4 TX -> line -> CDR (DSEL 10 via CTRL[6]): RXPKT > 0
//   5 CDR pattern loop (DSEL 01): RXOK > 0; CDR ADC read-back; DAC A write
//   6 PLL: pll_lock, FCNT = 2^FW x 60 / 24; PLL ADC read-back; DAC write
//   7 TX TRIM_TX -> DAC frame 1260
// Prints TEST PASSED / TEST FAILED: <reason> as the last line.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_aio_fpga_top;
    localparam integer BAUD   = 7500000;
    localparam real    TBIT   = 1.0e9 / BAUD;
    localparam integer PLL_FW = 10;
    localparam [11:0]  PLL_ADC = 12'd2345;
    localparam [11:0]  CDR_ADC = 12'd1987;

    reg        gclk = 0, btn_rst = 1, uart_rxd = 1;
    reg  [1:0] sw = 2'b00;
    wire [7:0] led;
    wire       uart_txd;
    always #5 gclk = ~gclk;

    wire tx_in_p_p, tx_in_p_n, tx_in_n_p, tx_in_n_n, tx_en, fs_oe, fs_dat, fs_se0, fs_ls;
    wire fs_suspnd, dp_pullup_en, hs_term_en, pd_en0, pd_en1, tx_dac_cs_n, spi_sck, spi_sdi;
    wire rx_en, rx_dac_cs_n;
    wire adf_clk, adf_data, adf_le, adf_ce, pll_vco_off, lf_dis, ol_en, cdcm_off;
    wire pll_dac_cs_n, pll_adc_cs_n, refsrc0, refsrc1, oe24, oe19;
    wire dpat_p, dpat_n, cdr_en, cdr_set, dsel0, dsel1, cdr_vco_off, csw_ext, csw_dac;
    wire cdr_dac_cs_n, cdr_adc_cs_n;
    reg  pll_adc_sdo = 1'b1, cdr_adc_sdo = 1'b1;

    // ---------------- board ----------------
    wire line = tx_en ? tx_in_p_p : 1'b1;
    reg  rx_out = 1'b1, sq = 1'b1;
    always @(line) rx_out <= #0.9 line;
    always @(tx_en) if (tx_en) sq <= #11 1'b0; else sq <= #20 1'b1;
    wire squelch_a = rx_en ? sq : 1'b1;

    reg clk_bit = 0, clk60a = 0, refc = 0;
    integer cb_n = 0;
    always #(1.0416667) clk_bit = ~clk_bit;
    always @(posedge clk_bit) begin cb_n = (cb_n + 1) % 8; if (cb_n == 0) clk60a = 1; if (cb_n == 4) clk60a = 0; end
    always #(20.8333333) refc = ~refc;

    wire cdr_data = ({dsel1, dsel0} == 2'b01) ? dpat_p : ({dsel1, dsel0} == 2'b10) ? line : 1'b1;
    wire clk_rx, hs_rxd;
    // The FPGA's BUFIO clock reaches the ISERDESE2 ~1.36 ns later than HS_RXD
    // at IDELAY tap 0 (Vivado: clock 2.81 ns, data 1.45 ns after the pins);
    // prims_sim has no insertion delays, so CLK_RX is delayed here (transport)
    // and the eye centre lands near the reset tap IDLY = 22, as on hardware.
    reg clk_rx_fp = 1'b0;
    always @(clk_rx) clk_rx_fp <= #(1.36) clk_rx;
    wire [31:0] n_up, n_dn, n_bits;
    afe_cdr_bm #(.PPM(500.0), .P_STEP(0.13), .T_AMB(0.25), .SEED(7)) u_cdr (
        .CDR_DATA(cdr_data), .CDR_EN(cdr_en & ~cdr_set), .clk_rx(clk_rx), .hs_rxd(hs_rxd),
        .n_up(n_up), .n_dn(n_dn), .n_bits(n_bits));

    aio_fpga_top #(.BAUD(BAUD), .AW(10), .PLL_FW(PLL_FW), .CDR_FW(12), .SETTLE_W(8)) dut (
        .gclk(gclk), .btn_rst(btn_rst), .sw(sw), .led(led), .uart_rxd(uart_rxd), .uart_txd(uart_txd),
        .tx_in_p_p(tx_in_p_p), .tx_in_p_n(tx_in_p_n), .tx_in_n_p(tx_in_n_p), .tx_in_n_n(tx_in_n_n),
        .tx_en(tx_en), .fs_oe(fs_oe), .fs_dat(fs_dat), .fs_se0(fs_se0), .fs_ls(fs_ls),
        .fs_suspnd(fs_suspnd), .dp_pullup_en(dp_pullup_en), .hs_term_en(hs_term_en),
        .pd_en0(pd_en0), .pd_en1(pd_en1), .rxrcv(1'b0), .rxdp(1'b0), .rxdm(1'b0), .vbus_det(1'b1),
        .tx_dac_cs_n(tx_dac_cs_n), .spi_sck(spi_sck), .spi_sdi(spi_sdi),
        .rx_out_p(rx_out), .rx_out_n(~rx_out), .squelch_a(squelch_a), .disc_a(1'b0),
        .rx_en(rx_en), .rx_dac_cs_n(rx_dac_cs_n),
        .clk_bit_a_p(clk_bit), .clk_bit_a_n(~clk_bit), .clk60_a_p(clk60a), .clk60_a_n(~clk60a),
        .ref_dig(refc), .muxout(1'b0),
        .adf_clk(adf_clk), .adf_data(adf_data), .adf_le(adf_le), .adf_ce(adf_ce),
        .pll_vco_off(pll_vco_off), .lf_dis(lf_dis), .ol_en(ol_en), .cdcm_off(cdcm_off),
        .pll_dac_cs_n(pll_dac_cs_n), .pll_adc_cs_n(pll_adc_cs_n), .pll_adc_sdo(pll_adc_sdo),
        .refsrc0(refsrc0), .refsrc1(refsrc1), .oe24(oe24), .oe19(oe19),
        .clk_rx_p(clk_rx_fp), .clk_rx_n(~clk_rx_fp), .hs_rxd_p(hs_rxd), .hs_rxd_n(~hs_rxd),
        .dpat_p(dpat_p), .dpat_n(dpat_n),
        .cdr_en(cdr_en), .cdr_set(cdr_set), .dsel0(dsel0), .dsel1(dsel1),
        .cdr_vco_off(cdr_vco_off), .csw_ext(csw_ext), .csw_dac(csw_dac),
        .cdr_dac_cs_n(cdr_dac_cs_n), .cdr_adc_cs_n(cdr_adc_cs_n), .cdr_adc_sdo(cdr_adc_sdo));

    integer errors = 0;
    task fail(input [8*72-1:0] msg);
        begin errors = errors + 1; $display("ERROR at %0t ns: %0s", $time, msg); end
    endtask

    // ---------------- shared SPI bus ----------------
    // CS# order: 0 TX DAC, 1 RX DAC, 2 PLL DAC, 3 PLL ADC, 4 CDR DAC, 5 CDR ADC
    wire [5:0] cs_n = {cdr_adc_cs_n, cdr_dac_cs_n, pll_adc_cs_n, pll_dac_cs_n, rx_dac_cs_n, tx_dac_cs_n};
    function integer nlow(input [5:0] v);
        integer i;
        begin nlow = 0; for (i = 0; i < 6; i = i + 1) if (!v[i]) nlow = nlow + 1; end
    endfunction
    integer n_overlap = 0, n_stray = 0;
    always @(cs_n) if (nlow(cs_n) > 1) begin
        n_overlap = n_overlap + 1;
        if (n_overlap < 4) fail("two CS# low on the shared SPI bus");
    end
    always @(posedge spi_sck) if (nlow(cs_n) != 1) begin
        n_stray = n_stray + 1;
        if (n_stray < 4) fail("SCK edge without exactly one CS# low");
    end

    // DAC frames (16 bits on SCK rising while CS# low), per DAC CS#
    reg [15:0] sr [0:5];
    integer    nb [0:5];
    integer    nfr [0:5];
    reg [15:0] last [0:5];
    reg [15:0] last_b [0:5];          // MCP4822 channel B (bit 15 = 1)
    integer k;
    initial for (k = 0; k < 6; k = k + 1) begin nb[k] = 0; nfr[k] = 0; last[k] = 0; last_b[k] = 0; end
    always @(posedge spi_sck)
        for (k = 0; k < 6; k = k + 1) if (!cs_n[k]) begin sr[k] = {sr[k][14:0], spi_sdi}; nb[k] = nb[k] + 1; end
    genvar g;
    generate for (g = 0; g < 6; g = g + 1) begin : g_dac
        always @(negedge cs_n[g]) nb[g] = 0;
        always @(posedge cs_n[g]) if (g != 3 && g != 5) begin
            if (nb[g] == 0) ;                         // power-up X -> 1
            else if (nb[g] != 16) fail("DAC frame not 16 bits");
            else begin
                nfr[g] = nfr[g] + 1;
                if (sr[g][15] && g != 0 && g != 2) last_b[g] = sr[g]; else last[g] = sr[g];
            end
        end
    end endgenerate

    // MCP3201: null bit after 2 clocks, then B11..B0, DOUT changes on SCK falling
    integer pa_n = 0, ca_n = 0;
    always @(negedge pll_adc_cs_n) begin pa_n = 0; pll_adc_sdo = 1'b1; end
    always @(negedge cdr_adc_cs_n) begin ca_n = 0; cdr_adc_sdo = 1'b1; end
    always @(negedge spi_sck) begin
        if (!pll_adc_cs_n) begin
            pa_n = pa_n + 1;
            pll_adc_sdo = (pa_n == 2) ? 1'b0 : (pa_n >= 3 && pa_n <= 14) ? PLL_ADC[14 - pa_n] : 1'b1;
        end
        if (!cdr_adc_cs_n) begin
            ca_n = ca_n + 1;
            cdr_adc_sdo = (ca_n == 2) ? 1'b0 : (ca_n >= 3 && ca_n <= 14) ? CDR_ADC[14 - ca_n] : 1'b1;
        end
    end

    // ---------------- UART ----------------
    task u_send(input [7:0] b);
        integer i;
        begin
            uart_rxd = 0; #(TBIT);
            for (i = 0; i < 8; i = i + 1) begin uart_rxd = b[i]; #(TBIT); end
            uart_rxd = 1; #(TBIT);
        end
    endtask
    task u_recv(output [7:0] b);
        integer i;
        begin
            @(negedge uart_txd); #(1.5 * TBIT);
            for (i = 0; i < 8; i = i + 1) begin b[i] = uart_txd; #(TBIT); end
        end
    endtask
    task wr(input [7:0] a, input [7:0] d);
        begin u_send(8'h57); u_send(a); u_send(d); #(2 * TBIT); end
    endtask
    task rd(input [7:0] a, output [7:0] d);
        begin u_send(8'h52); fork u_send(a); u_recv(d); join #(TBIT); end
    endtask
    task rd16(input [7:0] a, output [15:0] d);
        reg [7:0] l, h;
        begin rd(a, l); rd(a + 8'd1, h); d = {h, l}; end
    endtask
    task rd24(input [7:0] a, output [23:0] d);
        reg [7:0] l, m, h;
        begin rd(a, l); rd(a + 8'd1, m); rd(a + 8'd2, h); d = {h, m, l}; end
    endtask
    task select(input [1:0] s, input [7:0] id);
        reg [7:0] b;
        begin
            sw = s;
            #8000;                                        // 2 FF + 2^8 clk settling
            if (led[7:6] !== s) fail("LD7:LD6 do not show the selection");
            rd(8'h00, b);
            if (b !== id) begin
                fail("wrong block ID after the UART select");
                $display("  SW %b: ID %h, expected %h", s, b, id);
            end
        end
    endtask

    reg [7:0]  b;
    reg [15:0] r16;
    reg [23:0] r24;
    integer    i;

    initial begin
        $timeformat(-9, 0, " ns", 8);
        #200 btn_rst = 0;
        #40000;
        // ---- 1 SPI frames after reset ----
        $display("1 SPI after reset: frames TX %0d RX %0d PLL %0d CDR %0d",
                 nfr[0], nfr[1], nfr[2], nfr[4]);
        if (nfr[0] < 1 || last[0] !== 16'h34B0) fail("TX DAC frame after reset (code 1200)");
        if (nfr[1] < 2 || last[1] !== 16'h1528 || last_b[1] !== 16'h94BA) fail("RX DAC frames after reset (1320 / 1210)");
        if (nfr[2] < 1 || last[2] !== 16'h1C4E) fail("PLL DAC frame after reset (3150)");
        if (nfr[4] < 2 || last[4] !== 16'h1A28 || last_b[4] !== 16'h9C30) fail("CDR DAC frames after reset (2600 / 3120)");
        if (!locked_ok(1'b0)) fail("MMCM not locked / IDELAYCTRL not ready");

        // ---- 2 + 3 TX packets, RX capture ----
        $display("2 UART select, TX -> RX");
        select(2'b01, 8'h52);
        wr(8'h02, 8'h81);                                 // arm, trigger SQUELCH_A fall
        rd(8'h0B, b); if (!b[2]) fail("RX not armed");
        select(2'b00, 8'h54);
        wr(8'h01, 8'h03);                                 // go, repeat, HS, Test_Packet
        select(2'b11, 8'h43);
        wr(8'h01, 8'h41);                                 // CDR_EN, DSEL 10 (RX loop)
        if ({dsel1, dsel0} !== 2'b10) fail("DSEL not 10 with CTRL = 41h");
        #30000;
        rd24(8'h13, r24);
        $display("4 TX -> line -> CDR: RXPKT %0d", r24);
        if (r24 == 0) fail("CDR saw no SYNC from the TX loop");
        select(2'b01, 8'h52);
        rd(8'h0B, b);
        rd16(8'h0E, r16);
        $display("3 RX: STATUS %h, SQ_CNT %0d", b, r16);
        if (!b[3]) fail("RX capture not done");
        if (r16 == 0) fail("RX SQ_CNT = 0");
        if (!b[0] || !b[1] || !b[4]) fail("RX STATUS: locked / idelay_rdy / VBUS_DET");
        select(2'b00, 8'h54);
        wr(8'h01, 8'h00);                                 // TX stop

        // ---- 5 CDR pattern loop, ADC, DAC ----
        select(2'b11, 8'h43);
        wr(8'h02, 8'h01);                                 // TXMODE HS packets
        wr(8'h01, 8'h05);                                 // CDR_EN, DSRC pattern
        if ({dsel1, dsel0} !== 2'b01) fail("DSEL not 01 with CTRL = 05h");
        #40000;
        rd24(8'h16, r24);
        $display("5 CDR pattern loop: RXOK %0d", r24);
        if (r24 == 0) fail("CDR RXOK = 0 on the DPAT loop");
        rd16(8'h0B, r16);
        if (r16 !== {4'd0, CDR_ADC}) begin fail("CDR ADC read-back"); $display("  %0d", r16); end
        wr(8'h06, 8'h23); wr(8'h07, 8'h01);              // DAC A = 0123h
        #15000;                                           // token wait <= one ADC frame (10 us)
        if (last[4] !== 16'h1123) fail("CDR DAC A frame after the write");

        // ---- 6 PLL ----
        select(2'b10, 8'h50);
        i = 0;
        while (!dut.u_pll.pll_lock && i < 200) begin #1000; i = i + 1; end
        rd(8'h0C, b);
        $display("6 PLL: STATUS %h after %0d us", b, i);
        if (!b[1]) fail("PLL: no pll_lock");
        #(1024 * 41.6667 * 2.2);                          // a full FCNT gate
        rd24(8'h0F, r24);
        $display("  FCNT %0d (expected %0d)", r24, 1024 * 60 / 24);
        if (r24 < 2558 || r24 > 2562) fail("PLL FCNT");
        rd16(8'h0D, r16);
        if (r16 !== {4'd0, PLL_ADC}) begin fail("PLL ADC read-back"); $display("  %0d", r16); end
        wr(8'h0A, 8'h56); wr(8'h0B, 8'h04);              // DAC = 456h
        #15000;                                           // token wait <= one ADC frame (10 us)
        if (last[2] !== 16'h1456) fail("PLL DAC frame after the write");

        // ---- 7 TX DAC ----
        select(2'b00, 8'h54);
        wr(8'h0A, 8'h0A);                                 // TX_AMP 10 -> 1260
        #15000;                                           // token wait <= one ADC frame (10 us)
        if (last[0] !== 16'h34EC) fail("TX DAC frame after TRIM_TX = 10");

        $display("SPI: overlaps %0d, stray SCK edges %0d; frames TX %0d RX %0d PLL %0d CDR %0d",
                 n_overlap, n_stray, nfr[0], nfr[1], nfr[2], nfr[4]);
        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d errors", errors);
        $finish;
    end

    function locked_ok(input dummy);
        locked_ok = dut.locked && dut.idly_rdy;
    endfunction

    initial begin #2000000; $display("TEST FAILED: timeout"); $finish; end
endmodule
