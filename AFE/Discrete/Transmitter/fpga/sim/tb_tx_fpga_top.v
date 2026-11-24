//-----------------------------------------------------------------------------
// tb_tx_fpga_top.v - self-checking test of the transmitter-board FPGA design
//
//   cd AFE/Discrete/Transmitter/fpga/sim && ./run_sim.sh
//   (iverilog -g2005 -DTX_PISO_SIM -o sim_txfpga -I. prims_sim.v ../rtl/*.v
//    ../../../../../usb_bit_stuffer.v ../../../../../usb_nrzi_encoder.v
//    ../../../../../usb_tx_serializer8.v ../../../../../usb_tx_path.v
//    ../../../../../usb_afe_tx_if8.v tb_tx_fpga_top.v && vvp sim_txfpga)
//
// DUT: tx_fpga_top with TX_PISO_SIM (behavioural OSERDESE2, ideal clocks:
// clk60 and a phase-aligned clk240) and a fast UART (BAUD = 7.5 Mbit/s).
// The serial pins are sampled in the middle of every 480 Mbit/s bit.
//
// Checks
//   1  UART read of ID (54h) and of TRIM_LEAD default (0Ah)
//   2  TX_AMP = 10 -> MCP4821 word 0011_0100_1110_1100 (code 1260); override 0FFFh
//   3  HS Test_Packet: the line bits while TX_EN = 1 equal sim/usbpat.py's
//      hs_packet_line() exactly (SYNC .. EOP), preceded by TX_LEAD = 10 bits of J;
//      TX_IN_N = ~TX_IN_P on every bit; FS pins idle
//   4  TX_LEAD = 4, TX_LAG = 3: lead 4 J bits, EOP level held 3 more bits
//   5  HS PRBS7 packet (len 20): decoded (NRZI, unstuff) -> SYNC, PID C3h,
//      22 bytes, CRC16 residual B001h
//   6  FS user packet (A5h 3Ch 0Fh): FS_OE / FS_DAT at 40 bit times per bit,
//      SYNC KJKJKJKK, bytes, EOP = 2 bits SE0 + 1 bit J; FS_LS = 0
//   7  LS user packet: 320 bit times per bit, FS_LS = 1 on every driven bit
//   8  chirp K (pattern 4, len 8): TX_EN on, TX_IN_P = 0 (K) from the first
//      enabled bit (lead_first) for 64 + TX_LEAD bits, no EOP
//   9  TERM register -> DP_PULLUP_EN_A, HS_TERM_EN_A, PD_EN_A0/1, FS_SUSPND
//  10  idle clamp (CTRL.drv_dis) during a Test_Packet: pins go idle and stay
//      idle for the rest of that packet
// Prints TEST PASSED / TEST FAILED: <reason> as the last line.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_tx_fpga_top;

`include "test_packet_line.vh"

    localparam real T240 = 1000.0 / 240.0;    // 4.1667 ns
    localparam integer UDIV = 8;               // clk60 cycles per UART bit (7.5 Mbit/s)

    reg clk240 = 1'b0, clk60 = 1'b0;
    reg [1:0] cc = 2'd0;
    always #(T240 / 2.0) clk240 = ~clk240;
    // clk60 rises with every 4th rising clk240 edge (blocking, same time step)
    always @(posedge clk240) begin
        if (cc == 2'd0) clk60 = 1'b1;
        if (cc == 2'd2) clk60 = 1'b0;
        cc = cc + 2'd1;
    end

    reg rst_btn = 1'b1, uart_rxd = 1'b1;
    wire uart_txd;
    wire tpp, tpn, tnp, tnn, ten, foe, fdat, fse0, fls, fsus, dppu, hst, pd0, pd1;
    wire dcs, dsck, dsdi, l1, l2;

    tx_fpga_top #(.BAUD(7500000)) dut (
        .clkin_p(clk60), .clkin_n(clk240), .rst_btn(rst_btn),
        .uart_rxd(uart_rxd), .uart_txd(uart_txd),
        .tx_in_p_p(tpp), .tx_in_p_n(tpn), .tx_in_n_p(tnp), .tx_in_n_n(tnn),
        .tx_en(ten), .fs_oe_a(foe), .fs_dat_a(fdat), .fs_se0_a(fse0), .fs_ls_a(fls),
        .fs_suspnd(fsus), .dp_pullup_en_a(dppu), .hs_term_en_a(hst),
        .pd_en_a0(pd0), .pd_en_a1(pd1), .dac_cs_n(dcs), .dac_sck(dsck), .dac_sdi(dsdi),
        .rxrcv_a(1'b1), .rxdp_a(1'b1), .rxdm_a(1'b0), .vbus_det(1'b1),
        .led_locked(l1), .led_active(l2));

    // ---------------- failure bookkeeping ----------------
    integer errors = 0;
    reg [8*80-1:0] first_err;
    task fail(input [8*80-1:0] msg);
        begin
            if (errors == 0) first_err = msg;
            errors = errors + 1;
            $display("%t ERROR: %0s", $time, msg);
        end
    endtask

    // ---------------- serial capture (mid-bit sampling) ----------------
    localparam integer NCAP = 40000;
    reg cap_p [0:NCAP-1];
    reg cap_n [0:NCAP-1];
    reg cap_en[0:NCAP-1];
    reg cap_oe[0:NCAP-1];
    reg cap_dt[0:NCAP-1];
    reg cap_s0[0:NCAP-1];
    reg cap_ls[0:NCAP-1];
    integer ncap = 0;
    reg capturing = 1'b0;
    always @(clk240) begin
        #(T240 / 4.0);
        if (capturing && ncap < NCAP) begin
            cap_p[ncap] = tpp;  cap_n[ncap] = tnp;  cap_en[ncap] = ten;
            cap_oe[ncap] = foe; cap_dt[ncap] = fdat; cap_s0[ncap] = fse0; cap_ls[ncap] = fls;
            if (tpn !== ~tpp || tnn !== ~tnp) fail("OBUFDS pair not complementary");
            ncap = ncap + 1;
        end
    end

    // ---------------- UART BFM ----------------
    task uart_byte(input [7:0] b);
        integer i;
        begin
            uart_rxd = 1'b0; repeat (UDIV) @(posedge clk60);
            for (i = 0; i < 8; i = i + 1) begin
                uart_rxd = b[i]; repeat (UDIV) @(posedge clk60);
            end
            uart_rxd = 1'b1; repeat (UDIV + 2) @(posedge clk60);
        end
    endtask
    task wr(input [7:0] a, input [7:0] d);
        begin uart_byte(8'h57); uart_byte(a); uart_byte(d); end
    endtask
    task rd(input [7:0] a, output [7:0] d);
        integer i;
        begin
            uart_byte(8'h52); uart_byte(a);
            @(negedge uart_txd);
            repeat (UDIV / 2) @(posedge clk60);
            for (i = 0; i < 8; i = i + 1) begin
                repeat (UDIV) @(posedge clk60);
                d[i] = uart_txd;
            end
            repeat (UDIV * 2) @(posedge clk60);
        end
    endtask

    // ---------------- DAC SPI monitor ----------------
    reg [15:0] spi_sh;
    reg [15:0] spi_word;
    integer    spi_n = 0, spi_words = 0;
    reg        spi_in = 1'b0;               // inside a frame (started by a falling CS)
    always @(posedge dsck) if (!dcs) begin spi_sh = {spi_sh[14:0], dsdi}; spi_n = spi_n + 1; end
    always @(negedge dcs) begin spi_n = 0; spi_in = 1'b1; end
    always @(posedge dcs) if (spi_in) begin
        spi_in = 1'b0;
        if (spi_n != 16) fail("SPI frame not 16 bits");
        spi_word = spi_sh; spi_words = spi_words + 1;
    end

    // ---------------- helpers ----------------
    task start_capture;
        begin ncap = 0; capturing = 1'b1; end
    endtask
    task go_and_wait(input integer cycles);
        reg [7:0] st;
        begin
            start_capture;
            repeat (4) @(posedge clk60);
            repeat (cycles) @(posedge clk60);
            capturing = 1'b0;
        end
    endtask

    // first / last index where cap_en (HS) or cap_oe (FS) is 1
    function integer first_on(input integer fs);
        integer i;
        begin
            first_on = -1;
            for (i = ncap - 1; i >= 0; i = i - 1)
                if (fs ? cap_oe[i] : cap_en[i]) first_on = i;
        end
    endfunction
    function integer last_on(input integer fs);
        integer i;
        begin
            last_on = -1;
            for (i = 0; i < ncap; i = i + 1)
                if (fs ? cap_oe[i] : cap_en[i]) last_on = i;
        end
    endfunction

    // NRZI decode + unstuff of a line bit array (HS: cap_p) from index s,
    // one sample per bit every `per` samples; bytes into dec[], count into ndec
    reg [7:0] dec [0:255];
    integer   ndec;
    task decode(input integer s, input integer e, input integer per, input integer fs);
        integer i, run, nb;
        reg prev, cur, bit_v;
        reg [7:0] sh;
        begin
            ndec = 0; run = 0; nb = 0; sh = 8'h00;
            prev = 1'b1;                           // idle J
            i = s;
            while (i <= e) begin
                cur = fs ? cap_dt[i] : cap_p[i];
                if (fs && cap_s0[i]) i = e + 1;    // FS EOP
                else begin
                    bit_v = (cur == prev);         // NRZI: no transition = 1
                    prev = cur;
                    if (run == 6) begin            // stuffed bit
                        if (bit_v) i = e + 1;      // 7 ones: HS EOP (stuff error)
                        run = 0;
                    end else begin
                        run = bit_v ? run + 1 : 0;
                        sh = {bit_v, sh[7:1]}; nb = nb + 1;
                        if (nb == 8) begin dec[ndec] = sh; ndec = ndec + 1; nb = 0; end
                    end
                    i = i + per;
                end
            end
        end
    endtask

    function [15:0] crc_res(input integer from, input integer to);
        integer i, k;
        reg [15:0] c;
        begin
            c = 16'hFFFF;
            for (i = from; i <= to; i = i + 1) begin
                c = c ^ {8'h00, dec[i]};
                for (k = 0; k < 8; k = k + 1) c = c[0] ? ((c >> 1) ^ 16'hA001) : (c >> 1);
            end
            crc_res = c;
        end
    endfunction

    // ---------------- test sequence ----------------
    reg [7:0] r;
    integer i, f, l, k, j, lead, errs0;

    initial begin
        first_err = "";
        repeat (20) @(posedge clk60);
        rst_btn = 1'b0;
        repeat (40) @(posedge clk60);

        // ---- 1 register access ----
        rd(8'h00, r); if (r !== 8'h54) fail("ID register");
        rd(8'h09, r); if (r !== 8'h0A) fail("TRIM_LEAD default");
        if (spi_words < 1 || spi_word !== {4'b0011, 12'd1200}) fail("DAC word after reset (1200)");

        // ---- 2 DAC ----
        wr(8'h0A, 8'd10); repeat (200) @(posedge clk60);
        if (spi_word !== 16'h34EC) fail("DAC word for TX_AMP = 10");
        wr(8'h0B, 8'hFF); wr(8'h0C, 8'h8F); repeat (200) @(posedge clk60);
        if (spi_word !== 16'h3FFF) fail("DAC override 0FFFh");
        wr(8'h0C, 8'h00); wr(8'h0A, 8'd8); repeat (200) @(posedge clk60);
        if (spi_word !== {4'b0011, 12'd1200}) fail("DAC back to 1200");

        // ---- 3 HS Test_Packet ----
        wr(8'h02, 8'd0);                       // pattern Test_Packet
        wr(8'h01, 8'h00);
        fork
            begin wr(8'h01, 8'h01); end        // go, HS, single shot
            begin go_and_wait(700); end
        join
        f = first_on(0); l = last_on(0);
        if (f < 0) fail("Test_Packet: TX_EN never high");
        else begin
            for (i = f; i <= l; i = i + 1)
                if (cap_n[i] !== ~cap_p[i]) fail("TX_IN_N != ~TX_IN_P");
            lead = 0;
            while (cap_p[f + lead] === 1'b1 && lead < 40) lead = lead + 1;
            if (lead != 10) begin
                $display("lead = %0d", lead); fail("Test_Packet: TX_LEAD != 10 bits of J");
            end
            if (l - f + 1 != 10 + EXP_N) begin
                $display("enabled bits %0d, expected %0d", l - f + 1, 10 + EXP_N);
                fail("Test_Packet: TX_EN length");
            end
            for (i = 0; i < EXP_N; i = i + 1)
                if (cap_p[f + 10 + i] !== EXP_LINE[i]) begin
                    if (errors < 5) $display("bit %0d: got %b exp %b", i, cap_p[f + 10 + i], EXP_LINE[i]);
                    fail("Test_Packet line bits differ from usbpat.py");
                end
            for (i = 0; i < ncap; i = i + 1)
                if (cap_oe[i] !== 1'b0) fail("Test_Packet: FS_OE active in HS");
        end
        wr(8'h01, 8'h00);

        // ---- 4 TX_LEAD = 4, TX_LAG = 3 ----
        wr(8'h09, {3'd3, 5'd4});
        repeat (2200) @(posedge clk60);        // taken over after 16 idle ticks (window empty)
        fork
            begin wr(8'h01, 8'h01); end
            begin go_and_wait(700); end
        join
        f = first_on(0); l = last_on(0);
        lead = 0;
        while (cap_p[f + lead] === 1'b1 && lead < 40) lead = lead + 1;
        if (lead != 4) begin $display("lead = %0d", lead); fail("TX_LEAD = 4"); end
        if (l - f + 1 != 4 + EXP_N + 3) begin
            $display("enabled %0d", l - f + 1); fail("TX_LAG = 3: TX_EN length");
        end
        for (i = 0; i < 3; i = i + 1)
            if (cap_p[l - i] !== EXP_LINE[EXP_N - 1]) fail("TX_LAG: EOP level not held");
        wr(8'h01, 8'h00);
        wr(8'h09, 8'h0A);
        repeat (2200) @(posedge clk60);

        // ---- 5 HS PRBS7 ----
        wr(8'h02, 8'd5); wr(8'h03, 8'd20); wr(8'h04, 8'd0);
        fork
            begin wr(8'h01, 8'h01); end
            begin go_and_wait(500); end
        join
        f = first_on(0); l = last_on(0);
        while (cap_p[f] === 1'b1 && f < l) f = f + 1;     // skip the TX_LEAD J bits
        decode(f, l, 1, 0);
        // SYNC = 00 00 00 80, then PID, 20 bytes, CRC
        if (ndec != 4 + 1 + 20 + 2) begin $display("PRBS bytes %0d", ndec); fail("PRBS7: byte count"); end
        else begin
            if (dec[0] !== 8'h00 || dec[3] !== 8'h80) fail("PRBS7: SYNC");
            if (dec[4] !== 8'hC3) fail("PRBS7: PID");
            if (crc_res(5, ndec - 1) !== 16'hB001) fail("PRBS7: CRC16 residual");
        end
        wr(8'h01, 8'h00);

        // ---- 6 FS user packet ----
        wr(8'h07, 8'd0); wr(8'h08, 8'hA5); wr(8'h08, 8'h3C); wr(8'h08, 8'h0F);
        wr(8'h02, 8'd1); wr(8'h03, 8'd3); wr(8'h04, 8'd0);
        fork
            begin wr(8'h01, {4'b0000, 2'b01, 2'b01}); end      // go, FS
            begin go_and_wait(3000); end
        join
        f = first_on(1); l = last_on(1);
        if (f < 0) fail("FS: FS_OE never high");
        else begin
            // bit centres every 40 samples, starting 20 into the first bit (TX_LEAD
            // delays FS data too, but FS_OE and FS_DAT are delayed together)
            decode(f + 20, l, 40, 1);
            if (ndec != 4 || dec[0] !== 8'h80 || dec[1] !== 8'hA5 || dec[2] !== 8'h3C || dec[3] !== 8'h0F) begin
                $display("FS bytes %0d: %h %h %h %h", ndec, dec[0], dec[1], dec[2], dec[3]);
                fail("FS: decoded bytes");
            end
            // EOP: last 3 bits = SE0, SE0, J
            k = 0; for (i = f; i <= l; i = i + 1) if (cap_s0[i]) k = k + 1;
            if (k < 2 * 40 - 2 || k > 2 * 40 + 2) begin $display("SE0 samples %0d", k); fail("FS: EOP SE0 length"); end
            if (cap_dt[l - 5] !== 1'b1 || cap_s0[l - 5] !== 1'b0) fail("FS: EOP J bit");
            for (i = f; i <= l; i = i + 1) if (cap_ls[i] !== 1'b0) fail("FS: FS_LS set");
            for (i = 0; i < ncap; i = i + 1) if (cap_en[i] !== 1'b0) fail("FS: TX_EN active");
        end
        wr(8'h01, 8'h00);

        // ---- 7 LS user packet ----
        fork
            begin wr(8'h01, {4'b0000, 2'b10, 2'b01}); end      // go, LS
            begin go_and_wait(22000); end
        join
        f = first_on(1); l = last_on(1);
        if (f < 0) fail("LS: FS_OE never high");
        else begin
            decode(f + 160, l, 320, 1);
            if (ndec != 4 || dec[1] !== 8'hA5 || dec[3] !== 8'h0F) begin
                $display("LS bytes %0d", ndec); fail("LS: decoded bytes");
            end
            for (i = f; i <= l; i = i + 1) if (cap_oe[i] && cap_ls[i] !== 1'b1) fail("LS: FS_LS not set");
        end
        wr(8'h01, 8'h00);

        // ---- 8 chirp K ----
        wr(8'h02, 8'd4); wr(8'h03, 8'd8); wr(8'h04, 8'd0);
        fork
            begin wr(8'h01, 8'h01); end
            begin go_and_wait(300); end
        join
        f = first_on(0); l = last_on(0);
        if (l - f + 1 != 64 + 10) begin $display("chirp enabled %0d", l - f + 1); fail("chirp: length"); end
        for (i = f; i <= l; i = i + 1) if (cap_p[i] !== 1'b0) fail("chirp: TX_IN_P not K on every enabled bit");
        wr(8'h01, 8'h00);

        // ---- 9 TERM ----
        wr(8'h0D, 8'h1F); repeat (10) @(posedge clk60);
        if ({fsus, pd1, pd0, hst, dppu} !== 5'b11111) fail("TERM all on");
        wr(8'h0D, 8'h02); repeat (10) @(posedge clk60);
        if ({fsus, pd1, pd0, hst, dppu} !== 5'b00010) fail("TERM HS_TERM_EN only");
        rd(8'h0E, r);
        if (r[2] !== 1'b1 || r[6] !== 1'b1 || r[3] !== 1'b1) fail("STATUS bits");
        wr(8'h0D, 8'h00); rd(8'h0E, r);
        if (r[3] !== 1'b1 || r[4] !== 1'b0) fail("FS_RX_EN = 0 isolation emulation");

        // ---- 10 idle clamp in the middle of a Test_Packet ----
        wr(8'h02, 8'd0);
        fork
            begin wr(8'h01, 8'h01); end
            begin
                start_capture;
                @(posedge ten);
                repeat (10) @(posedge clk60);
                force dut.u_piso.drv_dis = 1'b1;
                repeat (3) @(posedge clk60);
                release dut.u_piso.drv_dis;
                repeat (600) @(posedge clk60);
                capturing = 1'b0;
            end
        join
        f = first_on(0); l = last_on(0);
        if (l - f + 1 >= 10 + EXP_N) fail("clamp: packet not cut");
        for (i = l + 1; i < ncap; i = i + 1)
            if (cap_en[i] !== 1'b0 || cap_p[i] !== 1'b1) fail("clamp: pins not idle after the clamp");
        wr(8'h01, 8'h00);

        if (errors == 0) $display("TEST PASSED");
        else $display("TEST FAILED: %0s (%0d errors)", first_err, errors);
        $finish;
    end

    initial begin
        #20_000_000;
        $display("TEST FAILED: timeout");
        $finish;
    end

endmodule
