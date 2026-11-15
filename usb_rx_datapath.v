//-----------------------------------------------------------------------------
// usb_rx_datapath.v
//
// RX datapath of the USB 2.0 PHY (HS / FS / LS), from the AFE receiver outputs
// to the RX Data Handler of the ULPI Interface Controller (usb_ulpi_rx_path):
//
//   HS:    CDR rxd/clk_rx -> usb_rx_hs_sipo (clk_rx island: front end, 1:8 SIPO,
//                            word clock clk_rxw)
//                         -> usb_rx_elastic_buffer (word FIFO, clk_rxw -> clk60) --+
//   FS/LS: rxrcv/rxdp/rxdm -> usb_rx_fsls_sampler (clk_bit island, word on ld)     |
//                         -> usb_rx_fsls_dpll (clk60, <= 1 bit per tick) ----------+
//                                                                                   |
//          input register (HS word / FS bit / mode-change idle bit) <---------------+
//            -> usb_rx_decoder8 (one instance, hs = XcvrSelect 00)
//            -> event FIFO (8 entries, up to 4 writes per tick)
//            -> RX output stage (clk60)
//            -> rx_start / rx_valid + rx_data / rx_end / rx_error
//
// Clocking (Plan_60MHz.md P4 / P5): everything from the word FIFO / DPLL on runs
// on the core clock clk60.  Islands: the FS/LS sampler and a tx_en capture on
// clk_bit (read through registers that change on ld, usb_clk_gen boundary
// rule); the HS front end and SIPO on the CDR clock clk_rx, whose word clock
// clk_rxw writes the word FIFO.  clk_rxw and clk60 are asynchronous (Gray
// pointers in the FIFO).
//
// HS: the SIPO writes 8-bit words {act, lvl} only while the receiver is active
//   (plus one closing word), so the FIFO drains between packets; the clk60 side
//   pops a word whenever one is there and gives the decoder 8 bits, or none.
//   A slower far end gives ticks without bits, a faster one (<= 1000 ppm) makes
//   the FIFO hold up to about one more word per 1000; 8 words leave margin.
// FS/LS: at most one DPLL bit per tick.
// usb_rx_decoder8 is the bit chain of ref_rx_decoder (NRZI decoder -> SYNC
//   detect -> bit unstuffer -> deserializer 1:8 -> EOP / RxError check) for up
//   to 8 bits per tick.  It can write up to four events per tick (two with
//   HS_ZMIN >= 6), so an 8-entry FIFO (buf_afull = fewer than 4 entries left
//   after the writes in flight) sits in front of the output stage.

// Mode (speed = XcvrSelect, quasi-static): 00 HS; 01 FS, 10 LS, 11 FS.  A mode
//   change feeds the decoder one inactive bit (in the old mode) instead of the
//   tick's bits, so a packet open at that moment ends with an error, and the
//   decoder never mixes the bits of two modes.  HS words that arrive while not
//   in HS mode are discarded.
//
// Local transmitter: while tx_en is high and for HOLDOFF clk_bit cycles after
//   it falls, both chains are disabled (receiver inactive), so the PHY never
//   reports its own packets (the HS receiver and the FS/LS receivers see the
//   local transmitter on the line).  HOLDOFF covers the AFE and CDR latency of
//   the echo.  rx_en = 0 disables reception as well (e.g. low-power mode).
//   tx_en is a clk_bit signal (TX serializer island): a 2-flop island ORs it over
//   each tick (taken over on ld), and the hold-off is counted on clk60 in ticks,
//   ceil(HOLDOFF / 8) after the last tick with tx_en.  The enables follow tx_en
//   with up to ~1.5 ticks of delay; HOLDOFF covers the end.
//
// FS/LS receiver samples for usb_line_state: ls_dp / ls_dm / ls_rcv = the newest
//   sample of the current sampler word (clk60-domain, changes on ld).
//
// Output (clk60 domain, combinational from registers - the decoder's event
//   registers, the event FIFO and the open flag - so every pulse is one tick
//   long, the format of usb_ulpi_rx_handler):
//   rx_start           a packet starts (SYNC received)
//   rx_valid, rx_data  a byte of the packet (PID first; SYNC and EOP stripped)
//   rx_end             the packet is over; rx_error = 1 in the same tick if the
//                      packet had an error (bit-stuff violation, not ending on a
//                      byte boundary, signal lost before the EOP, buffer
//                      overflow)
//   At most one event per tick.  The output stage shows the oldest event (FIFO
//   head, or the decoder's first event directly while the FIFO is empty); a
//   packet that was started is always ended, events outside a packet are
//   dropped.
//
// Latency (HS, line bit -> rx_*): front end 3 bits + up to 8 into a word + 4 to
//   clk_rxw + FIFO pointer synchronizer (1 - 2 ticks) + decoder (3 ticks, its
//   input is the FIFO head itself); the output shows the decoder's event in the
//   tick it is registered.  ULPI 1.1 Table 9 (RX End Delay, HS 3 - 8 clocks to
//   RxActive low) is measured in tb_usb_rx_datapath.
//
// Clocks / resets: clk60 (core) + clk_bit / ld (islands), clk_rx (HS recovered
//   clock) + clk_rxw.  rst_n is asynchronous; its release is synchronized to
//   clk_rx / clk_rxw in usb_rx_hs_sipo (it is assumed to be synchronous to
//   clk60 / clk_bit already).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_rx_datapath #(
    parameter FS_DIV  = 40,
    parameter LS_DIV  = 320,
    parameter DIV_W   = 9,
    parameter HS_ZMIN = 6,            // SYNC zeros needed, HS (4..8)
    parameter FS_ZMIN = 4,            // SYNC zeros needed, FS / LS
    parameter HS_AW   = 3,            // HS word FIFO: 8 words
    parameter HOLDOFF = 64            // clk_bit cycles after tx_en
) (
    input  wire        clk_bit,       // 480 MHz: FS/LS sampler and tx_en islands
    input  wire        rst_n,
    input  wire        clk60,         // core clock (usb_clk_gen)
    input  wire        ld,            // island strobe (usb_clk_gen)

    input  wire [1:0]  speed,         // XcvrSelect
    input  wire        rx_en,
    input  wire        tx_en,         // local transmitter active

    // HS receiver / CDR
    input  wire        clk_rx,
    input  wire        hs_rxd,
    input  wire        hs_squelch,
    input  wire        hs_cdr_lock,

    // FS / LS receivers (asynchronous AFE outputs)
    input  wire        rxrcv,
    input  wire        rxdp,
    input  wire        rxdm,
    // newest FS/LS receiver samples, for usb_line_state (clk60 domain)
    output wire        ls_dp,
    output wire        ls_dm,
    output wire        ls_rcv,

    // to usb_ulpi_rx_path
    output wire        rx_start,
    output wire        rx_valid,
    output wire [7:0]  rx_data,
    output wire        rx_end,
    output wire        rx_error,

    output wire        rx_busy        // a packet is open at the output
);

    localparam [1:0] EV_BYTE  = 2'b00;
    localparam [1:0] EV_START = 2'b01;
    localparam [1:0] EV_END   = 2'b10;

    // ---------------- mode, local transmitter hold-off ----------------
    localparam HT = (HOLDOFF + 7) / 8;                    // hold-off in ticks
    localparam HW = (HT < 2) ? 1 : $clog2(HT + 1);

    reg          txe_t, txe_a;        // clk_bit island: tx_en seen in the tick
    reg [HW-1:0] hold;
    reg          hs_en_q, fs_en_q, ls_q, hs_q, hs_d;
    wire         block = txe_t || (hold != {HW{1'b0}});

    always @(posedge clk_bit or negedge rst_n) begin
        if (!rst_n) begin
            txe_t <= 1'b0;
            txe_a <= 1'b0;
        end else if (ld) begin
            txe_t <= txe_a | tx_en;
            txe_a <= 1'b0;
        end else begin
            txe_a <= txe_a | tx_en;
        end
    end

    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            hold    <= {HW{1'b0}};
            hs_en_q <= 1'b0;
            fs_en_q <= 1'b0;
            ls_q    <= 1'b0;
            hs_q    <= 1'b0;
            hs_d    <= 1'b0;
        end else begin
            if (txe_t)                    hold <= HT;
            else if (hold != {HW{1'b0}})  hold <= hold - 1'b1;
            hs_en_q <= rx_en && !block && (speed == 2'b00);
            fs_en_q <= rx_en && !block && (speed != 2'b00);
            ls_q    <= (speed == 2'b10);
            hs_q    <= (speed == 2'b00);
            hs_d    <= hs_q;
        end
    end

    // ---------------- HS: clk_rx island + word FIFO ----------------
    wire        clk_rxw, hw_en, hw_full, hw_rst_n;
    wire [15:0] hw_data;
    wire        h_valid;
    wire [15:0] h_rdata;

    usb_rx_hs_sipo u_hs_sipo (
        .clk_rx   (clk_rx),
        .rst_n    (rst_n),
        .rxd      (hs_rxd),
        .squelch  (hs_squelch),
        .cdr_lock (hs_cdr_lock),
        .enable   (hs_en_q),
        .clk_rxw  (clk_rxw),
        .w_en     (hw_en),
        .w_data   (hw_data),
        .w_full   (hw_full),
        .w_rst_n  (hw_rst_n)
    );

    usb_rx_elastic_buffer #(.W(16), .AW(HS_AW), .ASYNC(1)) u_hs_wf (
        .wclk    (clk_rxw),
        .wrst_n  (hw_rst_n),
        .w_en    (hw_en),
        .w_data  (hw_data),
        .w_full  (hw_full),
        .w_afull (),
        .w_ovf   (),
        .rclk    (clk60),
        .rrst_n  (rst_n),
        .r_valid (h_valid),
        .r_data  (h_rdata),
        .r_pop   (1'b1)                // every word is taken (discarded outside HS)
    );

    // ---------------- FS / LS chain (sampler island + clk60) ----------------
    wire [7:0] rcv_v, dp_v, dm_v;
    wire       fb_en, fb_lvl, fb_se0, fb_act;

    usb_rx_fsls_sampler u_fs_smp (
        .clk_bit (clk_bit),
        .rst_n   (rst_n),
        .ld      (ld),
        .rxrcv   (rxrcv),
        .rxdp    (rxdp),
        .rxdm    (rxdm),
        .rcv_v   (rcv_v),
        .dp_v    (dp_v),
        .dm_v    (dm_v)
    );

    assign ls_dp  = dp_v[7];
    assign ls_dm  = dm_v[7];
    assign ls_rcv = rcv_v[7];

    usb_rx_fsls_dpll #(.FS_DIV(FS_DIV), .LS_DIV(LS_DIV), .DIV_W(DIV_W)) u_fs_dpll (
        .clk60  (clk60),
        .rst_n  (rst_n),
        .rcv_v  (rcv_v),
        .dp_v   (dp_v),
        .dm_v   (dm_v),
        .ls     (ls_q),
        .enable (fs_en_q),
        .b_en   (fb_en),
        .b_lvl  (fb_lvl),
        .b_se0  (fb_se0),
        .b_act  (fb_act)
    );

    // ---------------- decoder input (combinational, from registers) ----------------
    // HS: the word FIFO's head (Gray-synchronized r_valid, memory read);
    // FS / LS: the DPLL's registered bit; a mode change: one inactive bit.
    reg [7:0] in_en, in_lvl, in_se0, in_act;

    always @* begin
        if (hs_q != hs_d) begin
            in_en = 8'h01; in_lvl = 8'hFF; in_se0 = 8'd0; in_act = 8'd0;
        end else if (hs_d) begin
            in_en = {8{h_valid}}; in_lvl = h_rdata[7:0]; in_se0 = 8'd0; in_act = h_rdata[15:8];
        end else begin
            in_en  = {7'd0, fb_en};
            in_lvl = {7'h7F, fb_lvl};
            in_se0 = {7'd0, fb_se0};
            in_act = {7'd0, fb_act};
        end
    end

    // ---------------- decoder ----------------
    wire       d_w0, d_w1, d_w2, d_w3, d_busy;
    wire [1:0] d_ovf;
    wire [9:0] d_e0, d_e1, d_e2, d_e3;
    wire       f_afull, f_pop;

    usb_rx_decoder8 #(.ZMIN_HS(HS_ZMIN), .ZMIN_FS(FS_ZMIN)) u_dec (
        .clk60     (clk60),
        .rst_n     (rst_n),
        .hs        (hs_d),
        .s_en      (in_en),
        .s_lvl     (in_lvl),
        .s_se0     (in_se0),
        .s_act     (in_act),
        .buf_afull (f_afull),
        .ev0_wr    (d_w0),
        .ev0_data  (d_e0),
        .ev1_wr    (d_w1),
        .ev1_data  (d_e1),
        .ev2_wr    (d_w2),
        .ev2_data  (d_e2),
        .ev3_wr    (d_w3),
        .ev3_data  (d_e3),
        .busy      (d_busy),
        .ovf       (d_ovf)
    );

    // ---------------- event FIFO + output stage (clk60) ----------------
    // The output shows the oldest event: the FIFO head, or, while the FIFO is
    // empty, ev0 of the decoder directly (its registered output).  The events
    // of a tick that are not shown go into the FIFO (8 entries, up to four
    // writes, one pop per tick).  buf_afull counts the writes in flight.
    reg  [9:0] fq [0:7];
    reg  [2:0] f_rp, f_wp;
    reg  [3:0] f_cnt;
    reg        open;                  // a packet is open at the output

    wire [2:0] f_nw    = {2'd0, d_w0} + {2'd0, d_w1} + {2'd0, d_w2} + {2'd0, d_w3};
    wire       f_valid = (f_cnt != 4'd0);
    assign     f_afull = (f_cnt + {1'b0, f_nw}) > 4'd4;     // fewer than 4 entries left

    wire       e_val = f_valid | d_w0;
    wire [9:0] e_dat = f_valid ? fq[f_rp] : d_e0;
    wire [1:0] e_typ = e_dat[9:8];

    // every event is taken in its tick (the FIFO head does not wait); a START
    // while a packet is open closes it with an error and is dropped (cannot
    // happen: usb_rx_decoder8 ends a packet before the next SYNC, as
    // ref_rx_eop_check does)
    wire       dir   = !f_valid && d_w0;                     // ev0 shown directly
    assign     f_pop = f_valid;

    // events into the FIFO, in order (without ev0 when it was shown)
    wire [9:0] q0 = dir ? d_e1 : d_e0;
    wire [9:0] q1 = dir ? d_e2 : d_e1;
    wire [9:0] q2 = dir ? d_e3 : d_e2;
    wire [9:0] q3 = d_e3;
    wire       v0 = dir ? d_w1 : d_w0;
    wire       v1 = dir ? d_w2 : d_w1;
    wire       v2 = dir ? d_w3 : d_w2;
    wire       v3 = dir ? 1'b0 : d_w3;
    wire [3:0] f_in = {3'd0, v0} + {3'd0, v1} + {3'd0, v2} + {3'd0, v3};

    always @(posedge clk60) begin
        if (v0) fq[f_wp]        <= q0;
        if (v1) fq[f_wp + 3'd1] <= q1;
        if (v2) fq[f_wp + 3'd2] <= q2;
        if (v3) fq[f_wp + 3'd3] <= q3;
    end

    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            f_rp  <= 3'd0;
            f_wp  <= 3'd0;
            f_cnt <= 4'd0;
            open  <= 1'b0;
        end else begin
            if (f_pop) f_rp <= f_rp + 3'd1;
            f_wp  <= f_wp + f_in[2:0];
            f_cnt <= f_cnt + f_in - (f_pop ? 4'd1 : 4'd0);
            if (e_val) begin
                if (!open) open <= (e_typ == EV_START);        // else: orphan, dropped
                else       open <= (e_typ == EV_BYTE);         // END (or START: error)
            end
        end
    end

    // outputs: combinational from registers (decoder outputs, FIFO, open)
    assign rx_start = e_val && !open && (e_typ == EV_START);
    assign rx_valid = e_val &&  open && (e_typ == EV_BYTE);
    assign rx_data  = e_dat[7:0];
    assign rx_end   = e_val &&  open && (e_typ != EV_BYTE);
    assign rx_error = rx_end && ((e_typ == EV_START) || e_dat[0]);
    assign rx_busy  = open;

endmodule
