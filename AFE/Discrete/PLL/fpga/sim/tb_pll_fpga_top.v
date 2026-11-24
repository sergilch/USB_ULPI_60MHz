//-----------------------------------------------------------------------------
// tb_pll_fpga_top.v - testbench of the PLL-board FPGA design with a
//                     behavioural board model
//
//   ./run_sim.sh   (iverilog -g2005 -DPLL_SIM prims_sim.v <repo>/usb_clk_gen.v
//                   <repo>/usb_pll_lock_det.v ../rtl/pll_ctrl.v ../rtl/pll_meas.v
//                   ../rtl/pll_fpga_top.v tb_pll_fpga_top.v)
//
// Board model (doc/pll_board.md sections 3 / 4, simulated values of section 5):
//   ADF4002   24-bit shift register on CLK rising, latch on LE rising (C2 C1:
//             00 R, 01 N, 10 function, 11 init); decodes R, N, CPI, F3
//             (three-state), MUXOUT select; MUXOUT = digital lock detect
//             (|f - target| < 0.1 % for 2 us) when M = 001
//   VCO       tuning voltage v (0 .. 4.6 V), f = 388 MHz + 24.2 MHz/V * v
//             (linear fit of the 27 C curve), clamped to the range; closed
//             loop: v moves to the target (f_ref / R * 2 N) with tau = 2 us;
//             LF_DIS: v -> 0 (tau 0.2 us); OL_EN: v -> DAC voltage (tau 1 us);
//             VCO_OFF: no edges.  Edges are scheduled on an absolute real time
//             base, so the 1 ps precision does not bias the frequency.
//   CDCM1804  CLK_BIT_A = VCO, CLK60_A = VCO / 8 from a counter with an
//             arbitrary start state (it keeps its state while the VCO stops);
//             CDCM_OFF: both low
//   references 24 / 19.2 MHz oscillators (OE), 26 MHz on the SMA input, the
//             two 74LVC1G157 muxes; REF_DIG = selected reference
//   MCP4821 / MCP3201 SPI models (ADC: VTUNE = v, 5.0 V reference)
// Checks: ADF4002 words after reset and for each REFSEL; lock (usb_pll_lock_det)
//   at 24 and 19.2 MHz with T_LOCK / T_DLD; FCNT; REFSEL 10 (26 MHz, /20): no
//   lock, refsel_err; PLL_EN = 0: outputs off, no lol, CLK_BIT_A stops;
//   CLK60_A phase register against usb_clk_gen across two relocks; open loop:
//   DAC frame, CP three-state word, FCNT at the DAC voltage; ADC read-back.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_pll_fpga_top;
    localparam integer BAUD = 3000000;
    localparam integer FW   = 10;
    localparam real    TBIT = 1.0e9 / BAUD;

    reg  clkin = 0, rst_btn = 1, uart_rxd = 1;
    wire uart_txd;
    always #5 clkin = ~clkin;

    wire adf_clk, adf_data, adf_le, adf_ce, vco_off, lf_dis, cdcm_off, ol_en;
    wire dac_cs_n, adc_cs_n, spi_sck, spi_sdi, refsrc0, refsrc1, oe24, oe19;
    wire led_locked, led_pll;
    reg  adc_sdo = 1'b1;
    reg  muxout = 1'b0;
    wire clk_bit_a, clk60_a, ref_dig;

    pll_fpga_top #(.BAUD(BAUD), .FW(FW)) dut (
        .clkin_p(clkin), .clkin_n(1'b0), .rst_btn(rst_btn),
        .uart_rxd(uart_rxd), .uart_txd(uart_txd),
        .clk_bit_a_p(clk_bit_a), .clk_bit_a_n(~clk_bit_a),
        .clk60_a_p(clk60_a), .clk60_a_n(~clk60_a),
        .ref_dig(ref_dig), .muxout(muxout),
        .adf_clk(adf_clk), .adf_data(adf_data), .adf_le(adf_le), .adf_ce(adf_ce),
        .vco_off(vco_off), .lf_dis(lf_dis), .cdcm_off(cdcm_off), .ol_en(ol_en),
        .dac_cs_n(dac_cs_n), .adc_cs_n(adc_cs_n), .spi_sck(spi_sck), .spi_sdi(spi_sdi),
        .adc_sdo(adc_sdo), .refsrc0(refsrc0), .refsrc1(refsrc1), .oe24(oe24), .oe19(oe19),
        .led_locked(led_locked), .led_pll(led_pll));

    integer errors = 0;
    task fail(input [8*72-1:0] msg);
        begin errors = errors + 1; $display("ERROR at %0t ns: %0s", $time, msg); end
    endtask

    // ---------------- references ----------------
    reg osc24 = 0, osc19 = 0, ext26 = 0;
    real t24 = 3.0, t19 = 7.0, t26 = 11.0;
    always begin t24 = t24 + 1.0e3 / 48.0; #(t24 - $realtime) osc24 = ~osc24 & oe24; end
    always begin t19 = t19 + 1.0e3 / 38.4; #(t19 - $realtime) osc19 = ~osc19 & oe19; end
    always begin t26 = t26 + 1.0e3 / 52.0; #(t26 - $realtime) ext26 = ~ext26; end
    wire mux1 = refsrc0 ? osc19 : osc24;
    wire ref_sel = refsrc1 ? ext26 : mux1;
    assign ref_dig = ref_sel;
    real f_ref;
    always @(*) f_ref = refsrc1 ? 26.0e6 : (refsrc0 ? 19.2e6 : 24.0e6);

    // ---------------- ADF4002 ----------------
    reg [23:0] a_sr = 0;
    reg [13:0] a_r = 0;
    reg [12:0] a_n = 0;
    reg [2:0]  a_cpi = 0, a_mux = 0;
    reg        a_tri = 0, a_pol = 0;
    reg [23:0] a_last_f = 0, a_last_r = 0, a_last_n = 0;
    integer    a_words = 0;
    always @(posedge adf_clk) a_sr <= {a_sr[22:0], adf_data};
    always @(posedge adf_le) begin
        a_words = a_words + 1;
        case (a_sr[1:0])
            2'b00: begin a_r = a_sr[15:2]; a_last_r = a_sr; end
            2'b01: begin a_n = a_sr[20:8]; a_last_n = a_sr; end
            default: begin
                a_mux = a_sr[6:4]; a_pol = a_sr[7]; a_tri = a_sr[8]; a_cpi = a_sr[17:15];
                a_last_f = a_sr;
            end
        endcase
    end

    // ---------------- DAC / ADC ----------------
    reg [15:0] d_sr = 0, d_word = 0;
    integer    d_frames = 0;
    always @(posedge spi_sck) if (!dac_cs_n) d_sr <= {d_sr[14:0], spi_sdi};
    always @(posedge dac_cs_n) begin d_word = d_sr; d_frames = d_frames + 1; end
    real v;                                   // tuning voltage
    integer adc_code, adc_fall;
    always @(negedge adc_cs_n) begin
        adc_fall = 0; adc_code = $rtoi(v / 5.0 * 4096.0 + 0.5);
        if (adc_code > 4095) adc_code = 4095;
    end
    always @(negedge spi_sck) if (!adc_cs_n) begin
        adc_fall = adc_fall + 1;
        if (adc_fall == 2) adc_sdo <= 1'b0;
        else if (adc_fall >= 3 && adc_fall <= 14) adc_sdo <= adc_code[14 - adc_fall];
    end
    always @(posedge adc_cs_n) adc_sdo <= 1'b1;

    // ---------------- VCO, loop, CDCM1804 ----------------
    localparam real F0 = 388.0e6, KV = 24.2e6, VMAX = 4.6;
    real f, f_t, v_t, dt_ok;
    initial begin v = 0.0; dt_ok = 0.0; f = F0; end
    always #5 begin
        f_t = f_ref / ((a_r == 0) ? 1 : a_r) * 2.0 * a_n;
        if (lf_dis)
            v = v - v * 5.0 / 200.0;
        else if (ol_en)
            v = v + (d_word[11:0] / 1000.0 - v) * 5.0 / 1000.0;
        else if (adf_ce && !a_tri) begin
            v_t = (f_t - F0) / KV;
            if (v_t > VMAX) v_t = VMAX;
            if (v_t < 0.0) v_t = 0.0;
            v = v + (v_t - v) * 5.0 / 2000.0;
        end
        f = F0 + KV * v;
        if (adf_ce && !a_tri && (f - f_t < 1.0e-3 * f_t) && (f_t - f < 1.0e-3 * f_t))
            dt_ok = dt_ok + 5.0;
        else dt_ok = 0.0;
        muxout = (a_mux == 3'd1) ? (dt_ok >= 2000.0) : 1'b0;
    end
    reg  vco = 0;
    real tv;
    initial tv = 0.0;
    always begin
        if (vco_off || f < 1.0e8) begin vco = 0; wait (!vco_off && f >= 1.0e8); tv = $realtime; end
        tv = tv + 0.5e9 / f;
        #(tv - $realtime) vco = ~vco;
    end
    reg [2:0] c8;
    reg       q60 = 0;
    initial c8 = 3'd5;                        // arbitrary divider state at power-up
    always @(posedge vco) begin c8 = c8 + 3'd1; q60 = (c8 < 3'd4); end
    assign clk_bit_a = vco & ~cdcm_off;
    assign clk60_a   = q60 & ~cdcm_off;

    // ---------------- UART host ----------------
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
    task rd16(input [7:0] a, output [15:0] d);
        reg [7:0] l, h;
        begin rd(a, l); rd(a + 8'd1, h); d = {h, l}; end
    endtask
    task rd24(input [7:0] a, output [23:0] d);
        reg [7:0] l, m, h;
        begin rd(a, l); rd(a + 8'd1, m); rd(a + 8'd2, h); d = {h, m, l}; end
    endtask

    // expected ADF4002 words, assembled bit by bit from the datasheet maps
    function [23:0] fw_func(input [2:0] cpi, input tris, input [2:0] mux);
        reg [23:0] w;
        begin
            w = 0; w[1:0] = 2'b11;            // init latch
            w[3] = 1'b0; w[2] = 1'b0;         // PD1, F1
            w[6:4] = mux; w[7] = 1'b1;        // M3..M1, F2 positive
            w[8] = tris;                      // F3 three-state
            w[17:15] = cpi; w[20:18] = cpi;   // current settings 1 and 2
            fw_func = w;
        end
    endfunction
    function [23:0] fw_r(input [13:0] r);
        begin fw_r = 0; fw_r[15:2] = r; fw_r[20] = 1'b1; end   // ABP 00, LDP 1, C 00
    endfunction
    function [23:0] fw_n(input [12:0] n);
        begin fw_n = 0; fw_n[20:8] = n; fw_n[1:0] = 2'b01; end
    endfunction

    task check_adf(input [13:0] r, input [12:0] n, input [2:0] cpi, input tris);
        begin
            if (a_last_f !== fw_func(cpi, tris, 3'd1)) fail("ADF4002 function / init word");
            if (a_last_r !== fw_r(r)) fail("ADF4002 R word");
            if (a_last_n !== fw_n(n)) fail("ADF4002 N word");
            $display("  ADF4002: F %h R %h N %h (R %0d N %0d CPI %0d tri %0d)",
                     a_last_f, a_last_r, a_last_n, a_r, a_n, a_cpi, a_tri);
        end
    endtask

    // CLK60_A rising edge position in usb_clk_gen phases, observed directly
    integer obs_ph;
    always @(posedge dut.clk_bit) if (clk60_a && !q60_d) obs_ph = ph_of(dut.u_cg.phase_j);
    reg q60_d = 0;
    always @(posedge dut.clk_bit) q60_d <= clk60_a;
    function integer ph_of(input [3:0] j);
        case (j)
            4'b1111: ph_of = 0; 4'b1110: ph_of = 1; 4'b1100: ph_of = 2; 4'b1000: ph_of = 3;
            4'b0000: ph_of = 4; 4'b0001: ph_of = 5; 4'b0011: ph_of = 6; default: ph_of = 7;
        endcase
    endfunction

    reg [7:0]  b, st;
    reg [15:0] w16, tl, td;
    reg [23:0] w24;
    integer    k, ph1, ph2, d1, d2, cnt_edges;
    real       t0;

    task wait_lock(input integer max_us);
        integer i;
        begin
            i = 0;
            while (!dut.pll_lock && i < max_us) begin #1000; i = i + 1; end
        end
    endtask

    initial begin
        $timeformat(-9, 0, " ns", 8);
        #200 rst_btn = 0;
        // ---- reset: programming, defaults ----
        #20000;
        rd(8'h00, b); if (b !== 8'h50) fail("ID");
        if (a_words != 3) fail("ADF4002: 3 words after reset");
        check_adf(14'd1, 13'd10, 3'd1, 1'b0);
        if (d_frames < 1 || d_word !== 16'h1C4E) fail("DAC frame after reset (code 3150)");
        if (!adf_ce || vco_off || lf_dis || cdcm_off || ol_en || !oe24 || oe19 || refsrc0 || refsrc1)
            fail("board controls after reset");

        // ---- 24 MHz: lock ----
        $display("24 MHz, REFSEL 01");
        wait_lock(150);
        if (!dut.pll_lock) fail("no lock at 24 MHz");
        $display("  pll_lock at %t", $time);
        #50000;
        rd16(8'h12, tl); rd16(8'h14, td);
        $display("  T_LOCK %0d us, T_DLD %0d us", tl, td);
        if (tl > 120 || tl < 40) fail("T_LOCK out of range");
        if (td > 30) fail("T_DLD out of range");
        rd24(8'h0F, w24);
        $display("  FCNT %0d (expected 2560)", w24);
        if (w24 < 2559 || w24 > 2561) fail("FCNT at 24 MHz");
        rd(8'h0C, st); $display("  STATUS %h", st);
        if (st[3:0] !== 4'b0011 || !st[4] || !st[7]) fail("STATUS locked at 24 MHz");
        rd(8'h16, b); ph1 = b[2:0]; d1 = (b[2:0] - obs_ph + 8) % 8;
        $display("  PHASE %h, observed CLK60_A edge at phase %0d (offset %0d)", b, obs_ph, d1);
        if (!b[7]) fail("PHASE not valid");
        if (d1 != 0) fail("PHASE differs from the usb_clk_gen phase of the CLK60_A edge");
        rd16(8'h0D, w16);
        $display("  ADC %0d (v = %f V)", w16, v);
        if (w16 < $rtoi(v / 5.0 * 4096.0) - 2 || w16 > $rtoi(v / 5.0 * 4096.0) + 2) fail("ADC read-back");

        // ---- PLL_EN = 0 ----
        $display("PLL_EN = 0");
        wr(8'h01, 8'h00);
        #3000;
        if (adf_ce || !vco_off || !lf_dis || !cdcm_off) fail("PLL_EN = 0 controls");
        if (dut.pll_lock) fail("pll_lock with PLL_EN = 0");
        cnt_edges = 0;
        fork : cnt
            begin repeat (1000) @(posedge clk_bit_a) cnt_edges = cnt_edges + 1; end
            #2000 disable cnt;
        join
        if (cnt_edges != 0) fail("CLK_BIT_A runs with PLL_EN = 0");
        if (v > 0.1) fail("loop filter not discharged");
        rd(8'h0C, st); if (st[2]) fail("lol set by PLL_EN = 0");
        // advance the divider by an odd number of VCO edges while it is stopped
        c8 = c8 + 3'd3;
        wr(8'h01, 8'h01);
        wait_lock(150);
        if (!dut.pll_lock) fail("no relock");
        #20000;
        rd(8'h16, b); ph2 = b[2:0]; d2 = (b[2:0] - obs_ph + 8) % 8;
        $display("  relock: PHASE %h, observed %0d (offset %0d)", b, obs_ph, d2);
        if (ph2 == ph1) fail("PHASE did not follow the divider state");
        if (d2 != d1) fail("PHASE offset not constant");

        // ---- 19.2 MHz ----
        $display("19.2 MHz, REFSEL 00");
        wr(8'h01, 8'h05);                     // PLL_EN, REFSRC = 1 (19.2 MHz oscillator)
        wr(8'h02, 8'h00);
        #15000;
        check_adf(14'd2, 13'd25, 3'd4, 1'b0);
        if (!oe19 || oe24 || !refsrc0 || refsrc1) fail("reference select 19.2 MHz");
        wr(8'h01, 8'h04); #2000; wr(8'h01, 8'h05);
        wait_lock(150);
        if (!dut.pll_lock) fail("no lock at 19.2 MHz");
        #30000;
        rd(8'h18, b); if (b !== 8'd25) fail("fb_div 25");
        rd24(8'h0F, w24); $display("  FCNT %0d (expected 3200)", w24);
        if (w24 < 3199 || w24 > 3201) fail("FCNT at 19.2 MHz");
        rd16(8'h12, tl); $display("  T_LOCK %0d us", tl);

        // ---- 26 MHz with /20: no lock ----
        $display("26 MHz, REFSEL 10 (model /20)");
        wr(8'h01, 8'h09);                     // PLL_EN, REFSRC = 2 (SMA)
        wr(8'h02, 8'h02);
        #15000;
        check_adf(14'd1, 13'd10, 3'd1, 1'b0);
        wr(8'h01, 8'h08); #2000; wr(8'h01, 8'h09);
        #150000;
        rd(8'h0C, st); $display("  STATUS %h, f = %f MHz", st, f / 1e6);
        if (st[1]) fail("lock at 26 MHz / 20");
        if (!st[3]) fail("refsel_err at REFSEL 10");
        rd16(8'h12, tl); if (tl !== 16'hFFFF && tl < 140) fail("T_LOCK at 26 MHz");
        // REAL26: R = 13, N = 120 -> 480 MHz
        wr(8'h02, 8'h82);
        #15000;
        check_adf(14'd13, 13'd120, 3'd7, 1'b0);

        // ---- open loop ----
        $display("open loop, DAC 2000 (24 MHz reference)");
        wr(8'h02, 8'h01);
        wr(8'h01, 8'h03);                     // PLL_EN, OPEN_LOOP, 24 MHz oscillator
        #15000;
        check_adf(14'd1, 13'd10, 3'd1, 1'b1);
        if (!ol_en) fail("OL_EN");
        wr(8'h0A, 8'hD0); wr(8'h0B, 8'h07);
        #10000;
        if (d_word !== 16'h17D0) fail("DAC frame 2000");
        #110000;                              // two FCNT windows
        rd24(8'h0F, w24);
        $display("  FCNT %0d (expected %0d), f = %f MHz", w24,
                 $rtoi((F0 + KV * 2.0) / 8.0 / 24.0e6 * 1024.0), f / 1e6);
        if (w24 < $rtoi((F0 + KV * 2.0) / 8.0 / 24.0e6 * 1024.0) - 2 ||
            w24 > $rtoi((F0 + KV * 2.0) / 8.0 / 24.0e6 * 1024.0) + 2) fail("FCNT in open loop");
        wr(8'h01, 8'h01);
        #15000;
        check_adf(14'd1, 13'd10, 3'd1, 1'b0);

        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d errors", errors);
        $finish;
    end

    initial begin #20_000_000; $display("TEST FAILED: timeout"); $finish; end
endmodule
