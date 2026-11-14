//-----------------------------------------------------------------------------
// tb_usb_tx_path_split.v - usb_tx_path SPLIT = 1 (clk60 + bridge) against
//                          SPLIT = 0 (single clock) (Plan_60MHz.md P2)
//
//   iverilog -g2005 -o sim_tx_path_split usb_bit_stuffer.v usb_nrzi_encoder.v \
//            usb_tx_serializer.v usb_tx_ser_bridge.v usb_tx_path.v tb_usb_tx_path_split.v
//   vvp sim_tx_path_split
//
// Both instances get the same byte stream.  The reference (SPLIT = 0) runs on
// clk_bit + ce60, the DUT (SPLIT = 1) on clk60 + ld.  Checked:
//   * clk60 side, at every tick: in_ready and busy are equal (the stimulus
//     follows the reference's handshake, so any difference is an error);
//   * line side: txd, tx_en, tx_se0, tx_speed, tx_done, tx_underrun of the DUT
//     at clk_bit cycle k equal the reference at cycle k + 4 (the bridge takes
//     every word 4 cycles earlier, usb_tx_ser_bridge header).
// Stimulus: random packets at HS / FS / LS, with bypass_en and eop_dis, and
// random gaps in the byte stream, so HS underruns (abort + discard of the rest
// of the packet) happen too.  1-byte packets and back-to-back packets included.
//
// Clocks: clk60 and the strobes are generated in the clk_bit process itself
// (blocking), so both clocks change in the same simulation region, like ideal
// zero-skew hardware.  ce60 = phase 7 (logic updates on E0), ld = phase 3
// (updates on E4), clk60 rises on E0.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_usb_tx_path_split;

    localparam real HALF = 1.0417;
    localparam integer NPKT = 700;

    reg       clk_bit = 1'b0, clk60 = 1'b0;
    reg [2:0] ph = 3'd0;                 // phase of the cycle that ends at the next edge
    wire      ce60 = (ph == 3'd7);
    wire      ld   = (ph == 3'd3);
    always begin
        #(HALF) clk_bit = 1'b1;
        if (ph == 3'd7)      clk60 = 1'b1;       // E0
        else if (ph == 3'd3) clk60 = 1'b0;       // E4
        ph <= ph + 3'd1;
        #(HALF) clk_bit = 1'b0;
    end

    reg        rst_n = 1'b0;
    reg [1:0]  speed = 2'b00;
    reg        bypass_en = 1'b0, eop_dis = 1'b0;
    reg        in_valid = 1'b0, in_last = 1'b0;
    reg [7:0]  in_data = 8'h00;

    wire       r_ready, r_txd, r_en, r_se0, r_busy, r_done, r_under;
    wire       d_ready, d_txd, d_en, d_se0, d_busy, d_done, d_under;
    wire [1:0] r_spd, d_spd;

    usb_tx_path #(.SPLIT(0)) u_ref (
        .clk_bit(clk_bit), .rst_n(rst_n), .ce60(ce60), .clk60(1'b0), .ld(1'b0),
        .speed(speed), .bypass_en(bypass_en), .eop_dis(eop_dis),
        .in_valid(in_valid), .in_ready(r_ready), .in_data(in_data), .in_last(in_last),
        .txd(r_txd), .tx_en(r_en), .tx_se0(r_se0), .tx_speed(r_spd),
        .busy(r_busy), .tx_done(r_done), .tx_underrun(r_under));

    usb_tx_path #(.SPLIT(1)) u_dut (
        .clk_bit(clk_bit), .rst_n(rst_n), .ce60(1'b0), .clk60(clk60), .ld(ld),
        .speed(speed), .bypass_en(bypass_en), .eop_dis(eop_dis),
        .in_valid(in_valid), .in_ready(d_ready), .in_data(in_data), .in_last(in_last),
        .txd(d_txd), .tx_en(d_en), .tx_se0(d_se0), .tx_speed(d_spd),
        .busy(d_busy), .tx_done(d_done), .tx_underrun(d_under));

    integer errors = 0;
    task err(input [8*72-1:0] msg);
        begin
            errors = errors + 1;
            if (errors <= 20) $display("ERROR @%0t: %0s", $time, msg);
        end
    endtask

    //-------------------------------------------------------------------------
    // clk60 side: compare at every tick (values before the E0 edge)
    //-------------------------------------------------------------------------
    integer n_ticks = 0;
    always @(posedge clk_bit) if (rst_n && ce60) begin
        n_ticks = n_ticks + 1;
        if (d_ready !== r_ready) err("in_ready differs");
        if (d_busy  !== r_busy)  err("busy differs");
    end

    //-------------------------------------------------------------------------
    // line side: DUT cycle k == reference cycle k + 4
    //-------------------------------------------------------------------------
    localparam integer HL = 64;
    reg [6:0] dh [0:HL-1];
    integer   cyc = 0, n_line = 0, n_en = 0, n_done = 0, n_under = 0;
    reg [6:0] dv, rv;
    always @(posedge clk_bit) begin
        #0.1;
        dv = {d_txd, d_en, d_se0, d_spd, d_done, d_under};
        rv = {r_txd, r_en, r_se0, r_spd, r_done, r_under};
        dh[cyc % HL] = dv;
        if (rst_n && cyc >= 4) begin
            n_line = n_line + 1;
            if (dh[(cyc - 4) % HL] !== rv) begin
                err("line outputs differ (DUT 4 cycles earlier expected)");
                if (errors <= 20) $display("   ref %b  dut(-4) %b", rv, dh[(cyc - 4) % HL]);
            end
            if (r_en)    n_en    = n_en + 1;
            if (r_done)  n_done  = n_done + 1;
            if (r_under) n_under = n_under + 1;
        end
        cyc = cyc + 1;
    end

    //-------------------------------------------------------------------------
    // stimulus: clk60-domain byte source (changes on E0), follows u_ref
    //-------------------------------------------------------------------------
    integer seed = 32'h0060_0480;
    integer pk, nb, bi, gap_pct, len;
    reg     sent;
    initial begin
        repeat (4) @(posedge clk_bit);
        #0.3 rst_n = 1'b1;
        for (pk = 0; pk < NPKT; pk = pk + 1) begin
            // new configuration only while both are idle
            @(posedge clk_bit); while (!(ce60 && !r_busy)) @(posedge clk_bit);
            case ($unsigned($random(seed)) % 8)
                0, 1, 2, 3: speed <= 2'b00;
                4, 5:       speed <= 2'b01;
                6:          speed <= 2'b10;
                default:    speed <= 2'b11;
            endcase
            bypass_en <= (($unsigned($random(seed)) % 6) == 0);
            eop_dis   <= (($unsigned($random(seed)) % 6) == 0);
            gap_pct    = (($unsigned($random(seed)) % 3) == 0) ? 20 : 0;
            @(posedge clk_bit); while (!ce60) @(posedge clk_bit);
            len = (speed == 2'b00) ? 1 + $unsigned($random(seed)) % 40 :
                  (speed == 2'b10) ? 1 + $unsigned($random(seed)) % 3  :
                                     1 + $unsigned($random(seed)) % 8;
            for (bi = 0; bi < len; bi = bi + 1) begin
                // optional gap before the byte (HS: may cause an underrun)
                while (($unsigned($random(seed)) % 100) < gap_pct) begin
                    in_valid <= 1'b0;
                    @(posedge clk_bit); while (!ce60) @(posedge clk_bit);
                end
                in_valid <= 1'b1;
                in_data  <= $random(seed);
                in_last  <= (bi == len - 1);
                // hold until the reference takes it (sampled at a tick edge)
                sent = 1'b0;
                while (!sent) begin
                    @(posedge clk_bit); while (!ce60) @(posedge clk_bit);
                    sent = r_ready;
                end
            end
            in_valid <= 1'b0;
            in_last  <= 1'b0;
        end
        // drain
        @(posedge clk_bit); while (!(ce60 && !r_busy && !d_busy)) @(posedge clk_bit);
        repeat (40) @(posedge clk_bit);

        $display("%0d packets, %0d ticks, %0d line cycles compared (%0d with tx_en), %0d tx_done, %0d underruns",
                 NPKT, n_ticks, n_line, n_en, n_done, n_under);
        if (n_done < NPKT / 2) err("too few packets completed");
        if (n_under == 0)      err("no underrun exercised");
        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d errors", errors);
        $finish;
    end

endmodule
