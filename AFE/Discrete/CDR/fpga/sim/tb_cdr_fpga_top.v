//-----------------------------------------------------------------------------
// tb_cdr_fpga_top.v - testbench of the CDR-board FPGA design with the repo's
//                     CDR behavioural model as the board
//
//   ./run_sim.sh   (iverilog -g2005 -DCDR_SIM prims_sim.v <repo>/afe_cdr_bm.v
//                   <repo>/usb_tx_path.v <repo>/usb_bit_stuffer.v
//                   <repo>/usb_nrzi_encoder.v <repo>/usb_tx_serializer8.v
//                   <repo>/usb_rx_decoder8.v ../rtl/cdr_ctrl.v ../rtl/cdr_txgen.v
//                   ../rtl/cdr_rxchk.v ../rtl/cdr_fpga_top.v tb_cdr_fpga_top.v)
//
// Board model (doc/cdr_board.md sections 3 / 4):
//   EP57      CDR_DATA = DPAT (DSEL 01) or idle J (DSEL 00: SMA input not driven)
//   CDR       afe_cdr_bm (repo root; the model the board implements): free-run
//             offset PPM, prop step P_STEP, T_AMB 0.25 ns (samples that close to
//             an edge are random, about the EP29 setup / hold plus jitter, so the
//             lock transients lose SYNC bits); its CDR_EN = CDR_EN & ~CDR_SET (the
//             board's NB6L14 EN stops CLK_RX, the EP29 set inputs force
//             HS_RXD = 1; the model has one pin for both)
//   MCP4822 / MCP3201 SPI models (the ADC returns ADC_CODE)
// Checks: ID; free-running CLK_RX with an idle line: rx_alive, FCNT = 2^FW x
//   (1 + PPM) (the model's PPM lengthens the period); HS packets through usb_tx_path / usb_rx_decoder8: every packet
//   detected and correct, SYNC bits lost <= LOST_LIM (the gaps let the free-running
//   clock drift by up to one UI, so every packet starts with a phase error);
//   three packet lengths / gaps; PRBS7: no errors, psync; the clock pattern; DAC A / B
//   frames; ADC read-back; CDR_EN = 0: CLK_RX stops, rx_alive = 0, FCNT = 0,
//   CDR_SET follows; CLR.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_cdr_fpga_top;
    localparam integer BAUD     = 6000000;
    localparam integer FW       = 12;
    localparam real    TBIT     = 1.0e9 / BAUD;
    localparam real    PPM      = 2000.0;
    localparam integer LOST_LIM = 12;
    localparam [11:0]  ADC_CODE = 12'd1987;

    reg  clkin = 0, rst_btn = 1, uart_rxd = 1;
    wire uart_txd;
    always #5 clkin = ~clkin;

    wire dpat_p, dpat_n, cdr_en, cdr_set, dsel0, dsel1, vco_off, csw_ext, csw_dac;
    wire dac_cs_n, adc_cs_n, spi_sck, spi_sdi, led_alive, led_ok;
    reg  adc_sdo = 1'b1;
    wire clk_rx, hs_rxd;
    // The FPGA's BUFIO clock reaches the ISERDESE2 ~1.36 ns later than HS_RXD
    // at IDELAY tap 0 (Vivado: clock 2.81 ns, data 1.45 ns after the pins);
    // prims_sim has no insertion delays, so CLK_RX is delayed here (transport)
    // and the eye centre lands near the reset tap IDLY = 19, as on hardware.
    reg clk_rx_fp = 1'b0;
    always @(clk_rx) clk_rx_fp <= #(1.36) clk_rx;
    wire [31:0] n_up, n_dn, n_bits;

    cdr_fpga_top #(.BAUD(BAUD), .FW(FW)) dut (
        .clkin_p(clkin), .clkin_n(1'b0), .rst_btn(rst_btn),
        .uart_rxd(uart_rxd), .uart_txd(uart_txd),
        .clk_rx_p(clk_rx_fp), .clk_rx_n(~clk_rx_fp), .hs_rxd_p(hs_rxd), .hs_rxd_n(~hs_rxd),
        .dpat_p(dpat_p), .dpat_n(dpat_n),
        .cdr_en(cdr_en), .cdr_set(cdr_set), .dsel0(dsel0), .dsel1(dsel1), .vco_off(vco_off),
        .csw_ext(csw_ext), .csw_dac(csw_dac), .dac_cs_n(dac_cs_n), .adc_cs_n(adc_cs_n),
        .spi_sck(spi_sck), .spi_sdi(spi_sdi), .adc_sdo(adc_sdo),
        .led_alive(led_alive), .led_ok(led_ok));

    // ---------------- board ----------------
    wire cdr_data = (dsel1 == 1'b0 && dsel0 == 1'b1) ? dpat_p : 1'b1;
    afe_cdr_bm #(.PPM(PPM), .P_STEP(0.13), .T_AMB(0.25), .SEED(11)) u_cdr (
        .CDR_DATA(cdr_data), .CDR_EN(cdr_en & ~cdr_set), .clk_rx(clk_rx), .hs_rxd(hs_rxd),
        .n_up(n_up), .n_dn(n_dn), .n_bits(n_bits));

    integer errors = 0;
    task fail(input [8*72-1:0] msg);
        begin errors = errors + 1; $display("ERROR at %0t ns: %0s", $time, msg); end
    endtask

    // MCP4822: 16-bit frames on SCK rising while CS# low
    reg [15:0] d_sr;
    integer    d_n = 0;
    reg [11:0] dac_a = 0, dac_b = 0;
    integer    n_dac = 0;
    always @(negedge dac_cs_n) d_n = 0;
    always @(posedge spi_sck) if (!dac_cs_n) begin d_sr = {d_sr[14:0], spi_sdi}; d_n = d_n + 1; end
    always @(posedge dac_cs_n) if (d_n == 16) begin
        n_dac = n_dac + 1;
        if (d_sr[14:12] != 3'b001) fail("DAC control bits (BUF = 0, GA# = 0, SHDN# = 1)");
        if (d_sr[15]) dac_b = d_sr[11:0]; else dac_a = d_sr[11:0];
    end
    // MCP3201: null bit after 2 clocks, then B11..B0, DOUT changes on SCK falling
    integer a_n = 0;
    always @(negedge adc_cs_n) begin a_n = 0; adc_sdo = 1'b1; end
    always @(posedge adc_cs_n) adc_sdo = 1'b1;
    always @(negedge spi_sck) if (!adc_cs_n) begin
        a_n = a_n + 1;
        if (a_n == 2)                   adc_sdo = 1'b0;
        else if (a_n >= 3 && a_n <= 14) adc_sdo = ADC_CODE[14 - a_n];
        else                            adc_sdo = 1'b1;
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
        begin u_send(8'h52); fork u_send(a); u_recv(d); join end
    endtask
    task rd24(input [7:0] a, output [23:0] d);
        reg [7:0] l, m, h;
        begin rd(a, l); rd(a + 8'd1, m); rd(a + 8'd2, h); d = {h, m, l}; end
    endtask
    task rd32(input [7:0] a, output [31:0] d);
        reg [7:0] b0, b1, b2, b3;
        begin rd(a, b0); rd(a + 8'd1, b1); rd(a + 8'd2, b2); rd(a + 8'd3, b3); d = {b3, b2, b1, b0}; end
    endtask

    reg [7:0]  r8, lmax, lmin;
    reg [23:0] r24, txp, rxp, rxo, lsum, f;
    reg [31:0] pb, pe;
    real       fexp;

    task pkt_test(input [7:0] len, input [7:0] gap, input real us);
        begin
            wr(8'h03, len); wr(8'h04, gap); wr(8'h02, 8'h01);
            #(3000.0);                                   // first packets: start-up
            wr(8'h02, 8'h00); #(6000.0);                 // idle: CLR between packets
            wr(8'h01, 8'h85);                            // CLR (keep CDR_EN, DSRC)
            wr(8'h02, 8'h01);
            #(us * 1000.0);
            wr(8'h02, 8'h00);                            // stop: the last packet finishes
            #(6000.0);
            rd24(8'h10, txp); rd24(8'h13, rxp); rd24(8'h16, rxo); rd24(8'h19, lsum);
            rd(8'h1C, lmax); rd(8'h1D, lmin);
            $display("  len %0d gap %0d: TXPKT %0d RXPKT %0d RXOK %0d SYNC lost: max %0d min %0d mean %0.2f",
                     len, gap, txp, rxp, rxo, lmax, lmin, (rxp > 0) ? lsum * 1.0 / rxp : 0.0);
            if (txp < 5)                fail("packets: too few sent");
            if (rxp != txp)             fail("packets: RXPKT != TXPKT");
            if (rxo != rxp)             fail("packets: not all received correctly");
            if (lmax > LOST_LIM)        fail("packets: SYNC bits lost above the limit");
        end
    endtask

    initial begin
        $display("tb_cdr_fpga_top: CDR model PPM %0.0f, FCNT gate 2^%0d", PPM, FW);
        #200 rst_btn = 0;
        wait (dut.rst_n);
        #(2000);
        rd(8'h00, r8); if (r8 != 8'h43) fail("ID");
        if (cdr_en !== 1'b0 || cdr_set !== 1'b1) fail("reset: CDR_EN 0 / CDR_SET 1");
        if (n_dac < 2 || dac_a != 12'd2600 || dac_b != 12'd3120) fail("reset DAC values");

        // ---- free-running CLK_RX (idle J): FCNT ----
        wr(8'h01, 8'h05);                                // CDR_EN, DSRC = FPGA
        if (cdr_set !== 1'b0 || dsel0 !== 1'b1) fail("CTRL -> CDR_SET / DSEL0");
        #(3.5 * 68266.7);                                // > 3 gates of 2^12 clk cycles
        rd(8'h0A, r8);
        if (r8[1] !== 1'b1) fail("STATUS rx_alive");
        if (r8[2] !== 1'b1) fail("STATUS idelay_rdy");
        rd24(8'h0D, f);
        fexp = (1 << FW) / (1.0 + PPM * 1.0e-6);       // afe_cdr_bm: PPM scales the period
        $display("  FCNT %0d (expected %0.1f)", f, fexp);
        if (f < fexp - 3.0 || f > fexp + 3.0) fail("FCNT");

        // ---- HS packets ----
        pkt_test(8'd32, 8'd15, 40.0);
        pkt_test(8'd7,  8'd3,  20.0);
        pkt_test(8'd200, 8'd40, 30.0);

        // ---- PRBS7 ----
        wr(8'h02, 8'h02); #(2000.0);
        wr(8'h01, 8'h85); #(20000.0);
        rd32(8'h1E, pb); rd32(8'h22, pe); rd(8'h0A, r8);
        $display("  PRBS7: %0d words, %0d errors, psync %0d", pb, pe, r8[3]);
        if (pb < 32'd1000) fail("PRBS: words");
        if (pe != 0)       fail("PRBS: errors");
        if (r8[3] !== 1'b1) fail("PRBS: psync");
        // clock pattern: the PRBS checker must see errors (the pattern is not PRBS)
        wr(8'h02, 8'h03); #(2000.0); wr(8'h01, 8'h85); #(3000.0);
        rd32(8'h22, pe); rd(8'h0A, r8);
        if (pe == 0 || r8[3] !== 1'b0) fail("clock pattern seen as PRBS");

        // ---- DACs, coarse switch, ADC ----
        wr(8'h06, 8'h34); wr(8'h07, 8'h0A);              // DAC A 0A34h
        wr(8'h08, 8'hB8); wr(8'h09, 8'h0B);              // DAC B 0BB8h
        #(30000.0);                                      // behind an ADC frame (10 us)
        if (dac_a != 12'hA34 || dac_b != 12'hBB8) fail("DAC A / B");
        wr(8'h01, 8'h15);                                // CSRC = 2 (DAC B)
        #(200.0); if (csw_dac !== 1'b1 || csw_ext !== 1'b0) fail("CSRC DAC");
        wr(8'h01, 8'h0D);                                // CSRC = 1 (SMA)
        #(200.0); if (csw_dac !== 1'b0 || csw_ext !== 1'b1) fail("CSRC SMA");
        #(30000.0);
        rd(8'h0B, r8); r24[7:0] = r8; rd(8'h0C, r8); r24[15:8] = r8;
        if (r24[11:0] != ADC_CODE) fail("ADC read-back");

        // ---- FF_SET, CDR_EN = 0 ----
        wr(8'h01, 8'h07);
        #(200.0); if (cdr_set !== 1'b1 || cdr_en !== 1'b1) fail("FF_SET");
        wr(8'h01, 8'h04);
        #(200.0); if (cdr_set !== 1'b1 || cdr_en !== 1'b0) fail("CDR_EN = 0");
        #(25000.0);                                      // snapshot time-out 17 us
        rd(8'h0A, r8); if (r8[1] !== 1'b0 || r8[5] !== 1'b0) fail("STATUS after CDR_EN = 0");
        rd24(8'h0D, f); if (f != 0) fail("FCNT with CLK_RX stopped");

        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d errors", errors);
        $finish;
    end
    initial begin #20_000_000; $display("TEST FAILED: timeout"); $finish; end
endmodule
