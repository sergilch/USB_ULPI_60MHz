//-----------------------------------------------------------------------------
// tb_rx_fpga_top.v - testbench of the receiver-board FPGA design (Icarus,
//                    RX_SIM primitives; run_sim.sh builds and runs it)
//
// Board model: RX_OUT follows the HS line (J = 1) 0.9 ns late and holds its
// level while the line is idle (SN65LVDS100 with SE0 at its input).  Bits are
// sent with a per-packet rate offset (+-400 ppm) and +-40 ps uniform edge
// jitter.  SQUELCH_A falls 11 ns after the first edge and rises 20 ns after
// the end of the EOP; DISC_A pulses once (host-mode disconnect).  RX_EN = 0
// forces SQUELCH_A = 1 and DISC_A = 0, as the board's 74LVC1G00 / 1G08.
//
// Checks
//   1 ID register, MMCM lock / IDELAYCTRL ready
//   2 MCP4822 frames after reset (V_SQ 1320, V_DISC 1210) and after a write
//   3 capture triggered by SQUELCH_A: done, trigger word = PRE, the fall is in it
//   4 counters: SQ_CNT = 4 packets, DC_CNT = 1
//   5 UART dump of the capture -> capture.txt; rx_decode.py (run_sim.sh) must
//     find the 4 packets bit-exact with valid CRCs
//   6 RX_EN = 0: a further packet does not count
//   7 TAP_M / TAP_S read back
// Prints TEST PASSED / TEST FAILED: ... (run_sim.sh appends the decoder result).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_rx_fpga_top;
    `include "packets.vh"

    localparam integer AW = 10;
    localparam integer BAUD = 15000000;            // clk 60 MHz / 4
    localparam real    TBIT = 1000.0 / 15.0;       // UART bit, ns
    localparam real    UI = 1000.0 / 480.0;

    reg  clkin = 0;
    always #5 clkin = ~clkin;                      // 100 MHz
    reg  rst_btn = 1'b1;
    reg  uart_rxd = 1'b1;
    wire uart_txd;
    reg  rx_line = 1'b0;                           // RX_OUT level (J = 1)
    reg  sq_raw = 1'b1, dc_raw = 1'b0;
    wire rx_en, hs_term_en, dac_cs_n, dac_sck, dac_sdi, led_locked, led_active;
    wire squelch_a = rx_en ? sq_raw : 1'b1;
    wire disc_a    = rx_en & dc_raw;
    wire rx_out_p, rx_out_n;
    assign #0.9 rx_out_p = rx_line;
    assign #0.9 rx_out_n = ~rx_line;

    rx_fpga_top #(.BAUD(BAUD), .AW(AW)) dut (
        .clkin_p(clkin), .clkin_n(1'b0), .rst_btn(rst_btn), .uart_rxd(uart_rxd),
        .uart_txd(uart_txd), .rx_out_p(rx_out_p), .rx_out_n(rx_out_n), .squelch_a(squelch_a),
        .disc_a(disc_a), .rx_en(rx_en), .hs_term_en(hs_term_en), .dac_cs_n(dac_cs_n),
        .dac_sck(dac_sck), .dac_sdi(dac_sdi), .vbus_det(1'b1), .led_locked(led_locked),
        .led_active(led_active));

    integer errors = 0;
    task fail(input [8*64-1:0] msg);
        begin errors = errors + 1; $display("ERROR %0t: %0s", $time, msg); end
    endtask

    // ---------------- UART host side ----------------
    task uart_send(input [7:0] b);
        integer i;
        begin
            uart_rxd = 1'b0; #(TBIT);
            for (i = 0; i < 8; i = i + 1) begin uart_rxd = b[i]; #(TBIT); end
            uart_rxd = 1'b1; #(TBIT);
        end
    endtask
    task uart_recv(output [7:0] b);
        integer i;
        begin
            @(negedge uart_txd); #(TBIT * 1.5);
            for (i = 0; i < 8; i = i + 1) begin b[i] = uart_txd; #(TBIT); end
        end
    endtask
    task wr(input [7:0] a, input [7:0] d);
        begin uart_send(8'h57); uart_send(a); uart_send(d); #(TBIT * 4); end
    endtask
    reg [7:0] rb;
    task rd(input [7:0] a, output [7:0] d);
        begin
            fork
                begin uart_send(8'h52); uart_send(a); end
                uart_recv(d);
            join
        end
    endtask

    // ---------------- MCP4822 monitor ----------------
    reg [15:0] spi_sh;
    integer    spi_n = 0;
    reg [15:0] spi_frames [0:15];
    integer    nframes = 0;
    always @(negedge dac_cs_n) spi_n = 0;
    always @(posedge dac_sck) if (!dac_cs_n) begin spi_sh = {spi_sh[14:0], dac_sdi}; spi_n = spi_n + 1; end
    always @(posedge dac_cs_n) if (spi_n == 16) begin
        spi_frames[nframes] = spi_sh; nframes = nframes + 1;
    end

    // ---------------- line model ----------------
    task send_pkt(input integer k, input real ppm);
        integer i, n;
        reg [0:1023] bits;
        real ui, t0;
        begin
            case (k)
                0: begin n = PKT0_N; bits[0:PKT0_N - 1] = PKT0; end
                1: begin n = PKT1_N; bits[0:PKT1_N - 1] = PKT1; end
                2: begin n = PKT2_N; bits[0:PKT2_N - 1] = PKT2; end
                default: begin n = PKT3_N; bits[0:PKT3_N - 1] = PKT3; end
            endcase
            ui = UI * (1.0 + ppm * 1e-6);
            t0 = $realtime + 0.05;             // jitter must not make the first delay negative
            fork
                begin #(11.0); sq_raw = 1'b0; end
                begin #(n * ui + 20.0); sq_raw = 1'b1; end
                for (i = 0; i < n; i = i + 1) begin
                    #(t0 + i * ui + 0.04 * ($random % 1000) / 1000.0 - $realtime);
                    rx_line = bits[i];
                end
            join
        end
    endtask

    reg [7:0]  b0, b1, b2, b3;
    reg [15:0] v16;
    integer    i, fd, ta;
    initial begin
        $timeformat(-9, 1, " ns", 10);
        #200 rst_btn = 1'b0;
        wait (led_locked);
        #3000;
        // 1 ID, status
        rd(8'h00, rb); if (rb !== 8'h52) fail("ID");
        rd(8'h0B, rb); if (rb[1:0] !== 2'b11) fail("MMCM lock / IDELAYCTRL ready");
        $display("%t step 1 done", $realtime);
        // 2 DAC
        if (nframes != 2 || spi_frames[0] !== 16'h1528 || spi_frames[1] !== 16'h94BA)
            fail("DAC frames after reset");
        wr(8'h07, 8'h14); wr(8'h08, 8'h05);                       // V_SQ = 1300
        #2000;
        if (nframes != 3 || spi_frames[2] !== 16'h1514) fail("DAC frame after write");
        $display("%t step 2 done, frames %0d", $realtime, nframes);
        // 3 capture
        wr(8'h03, 8'd16); wr(8'h04, 8'd0);                        // PRE = 16 words
        wr(8'h02, 8'h81);                                         // squelch trigger, arm
        #500;
        rd(8'h0B, rb); if (!rb[2]) fail("not armed");
        send_pkt(0, 400.0);  #150;
        send_pkt(1, -400.0); #150;
        send_pkt(2, 250.0);  #150;
        fork
            send_pkt(3, -250.0);
            begin #40; dc_raw = 1'b1; #30; dc_raw = 1'b0; end      // disconnect pulse
        join
        $display("%t packets sent", $realtime);
        wait (dut.u_cap.done);
        $display("%t capture done", $realtime);
        #200;
        rd(8'h0B, rb); if (!rb[3] || rb[2]) fail("capture not done");
        rd(8'h0C, b0); rd(8'h0D, b1);
        ta = {b1, b0};
        // 4 counters
        rd(8'h0E, b0); rd(8'h0F, b1); if ({b1, b0} !== 16'd4) begin fail("SQ_CNT"); $display("SQ_CNT %0d (%0d)", {b1, b0}, dut.u_cap.sq_cnt); end
        rd(8'h10, b0); rd(8'h11, b1); if ({b1, b0} !== 16'd1) begin fail("DC_CNT"); $display("DC_CNT %0d (%0d)", {b1, b0}, dut.u_cap.dc_cnt); end
        // 7 taps
        rd(8'h06, rb); if (rb !== 8'd7) fail("TAP_S");
        // 5 dump 400 words (3.3 us) from the start of the capture
        dut.u_mmcm.fast_off = 1'b1;                               // no capture any more: stop 480/200 MHz
        fd = $fopen("capture.txt", "w");
        $fdisplay(fd, "# tap_m=0 tap_s=7 trig_addr=%0d pre=16", ta);
        fork
            begin uart_send(8'h44); uart_send(8'd0); uart_send(8'd0);
                  uart_send(8'd144); uart_send(8'd1); end           // 400 words
            for (i = 0; i < 400; i = i + 1) begin
                uart_recv(b0); uart_recv(b1); uart_recv(b2); uart_recv(b3);
                $fdisplay(fd, "%02X%02X%02X%02X", b3, b2, b1, b0);
                if (i == 16 && b2 == 8'hFF) fail("trigger word without SQUELCH_A fall");
                if (i < 16 && b2 != 8'hFF) fail("SQUELCH_A active before the trigger word");
            end
        join
        $fclose(fd);
        dut.u_mmcm.fast_off = 1'b0;
        #100;
        // 6 RX_EN = 0
        wr(8'h01, 8'h00);
        #200;
        send_pkt(2, 0.0);
        #300;
        rd(8'h0E, b0); rd(8'h0F, b1); if ({b1, b0} !== 16'd4) fail("SQ_CNT counted with RX_EN = 0");
        if (errors == 0) $display("TEST PASSED");
        else $display("TEST FAILED: %0d errors", errors);
        $finish;
    end

    initial begin #3_000_000; $display("TEST FAILED: timeout"); $finish; end
endmodule
