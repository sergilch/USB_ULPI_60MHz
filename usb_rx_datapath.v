//-----------------------------------------------------------------------------
// usb_rx_datapath.v
//
// RX datapath of the USB 2.0 PHY (HS / FS / LS), from the AFE receiver outputs
// to the RX Data Handler of the ULPI Interface Controller (usb_ulpi_rx_path):
//
//   HS:    CDR rxd/clk_rx -> usb_rx_hs_frontend -> usb_rx_decoder (HS, clk_rx)
//                         -> usb_rx_elastic_buffer (async, clk_rx -> clk60) ----+
//   FS/LS: rxrcv/rxdp/rxdm -> usb_rx_fsls_sampler (clk_bit island, word on ld)   |
//                         -> usb_rx_fsls_dpll -> usb_rx_decoder8 (FS/LS)         |
//                         -> event FIFO (4 entries, clk60) ----------------------+
//                                                                                 |
//          RX output stage (clk60) <---------------------------------------------+
//            -> rx_start / rx_valid + rx_data / rx_end / rx_error
//
// Clocking (Plan_60MHz.md P4): the FS/LS half and the output stage run on the
// core clock clk60; only the FS/LS sampler (2-FF synchronizers, 1:8 SIPO) and
// the transmit hold-off counter are clk_bit islands, read by clk60 through
// registers that change on ld (usb_clk_gen boundary rule).  The HS half is
// unchanged on clk_rx (moves in P5); its elastic buffer now delivers to clk60.
//
// usb_rx_decoder is: NRZI decoder -> SYNC detect -> bit unstuffer ->
// deserializer 1:8 -> EOP / RxError check.  usb_rx_decoder8 is the same chain for
// up to 8 bits per clk60 tick; the FS/LS DPLL gives it at most one bit per tick.
// It can write two events per tick, so a 4-entry FIFO (buf_afull = fewer than 3
// free entries) sits in front of the output stage.
//
// Mode (speed = XcvrSelect, quasi-static): 00 HS chain; 01 FS, 10 LS, 11 FS
//   (FS/LS chain).  Changing the mode during a packet ends it with an error.
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
// Output (clk60 domain, registered, so every pulse is one tick long - the
//   format of usb_ulpi_rx_handler):
//   rx_start           a packet starts (SYNC received)
//   rx_valid, rx_data  a byte of the packet (PID first; SYNC and EOP stripped)
//   rx_end             the packet is over; rx_error = 1 in the same tick if the
//                      packet had an error (bit-stuff violation, not ending on a
//                      byte boundary, signal lost before the EOP, buffer
//                      overflow)
//   At most one event per tick.  The output stage pops one event per tick from
//   the buffer of the active chain; a packet that was started is always ended,
//   events outside a packet are dropped.
//
// Clocks / resets: clk60 (core) + clk_bit / ld (islands), clk_rx (HS recovered
//   clock).  rst_n is asynchronous; its release is synchronized to clk_rx here
//   (it is assumed to be synchronous to clk60 / clk_bit already).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_rx_datapath #(
    parameter FS_DIV  = 40,
    parameter LS_DIV  = 320,
    parameter DIV_W   = 9,
    parameter HS_ZMIN = 6,            // SYNC zeros needed, HS
    parameter FS_ZMIN = 4,            // SYNC zeros needed, FS / LS
    parameter HS_AW   = 4,            // HS elastic buffer: 16 events
    parameter HOLDOFF = 64            // clk_bit cycles after tx_en
) (
    input  wire        clk_bit,       // 480 MHz: FS/LS sampler and hold-off islands
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
    output reg         rx_start,
    output reg         rx_valid,
    output reg  [7:0]  rx_data,
    output reg         rx_end,
    output reg         rx_error,

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
    reg          hs_en_q, fs_en_q, ls_q;
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
        end else begin
            if (txe_t)                    hold <= HT;
            else if (hold != {HW{1'b0}})  hold <= hold - 1'b1;
            hs_en_q <= rx_en && !block && (speed == 2'b00);
            fs_en_q <= rx_en && !block && (speed != 2'b00);
            ls_q    <= (speed == 2'b10);
        end
    end

    // ---------------- clk_rx reset synchronizer ----------------
    reg rr1, rst_rx_n;
    always @(posedge clk_rx or negedge rst_n) begin
        if (!rst_n) begin
            rr1      <= 1'b0;
            rst_rx_n <= 1'b0;
        end else begin
            rr1      <= 1'b1;
            rst_rx_n <= rr1;
        end
    end

    // ---------------- HS chain (clk_rx) ----------------
    wire       hb_en, hb_lvl, hb_se0, hb_act;
    wire       h_ev_wr, h_afull, h_full, h_wovf, h_busy, h_ovf;
    wire [9:0] h_ev;
    wire       h_valid;
    wire [9:0] h_rdata;
    wire       h_pop;

    usb_rx_hs_frontend u_hs_fe (
        .clk_rx   (clk_rx),
        .rst_n    (rst_rx_n),
        .rxd      (hs_rxd),
        .squelch  (hs_squelch),
        .cdr_lock (hs_cdr_lock),
        .enable   (hs_en_q),
        .b_en     (hb_en),
        .b_lvl    (hb_lvl),
        .b_se0    (hb_se0),
        .b_act    (hb_act)
    );

    usb_rx_decoder #(.HS(1), .ZMIN(HS_ZMIN)) u_hs_dec (
        .clk       (clk_rx),
        .rst_n     (rst_rx_n),
        .b_en      (hb_en),
        .b_lvl     (hb_lvl),
        .b_se0     (hb_se0),
        .b_act     (hb_act),
        .buf_afull (h_afull),
        .ev_wr     (h_ev_wr),
        .ev_data   (h_ev),
        .busy      (h_busy),
        .ovf       (h_ovf)
    );

    usb_rx_elastic_buffer #(.W(10), .AW(HS_AW), .ASYNC(1)) u_hs_eb (
        .wclk    (clk_rx),
        .wrst_n  (rst_rx_n),
        .w_en    (h_ev_wr),
        .w_data  (h_ev),
        .w_full  (h_full),
        .w_afull (h_afull),
        .w_ovf   (h_wovf),
        .rclk    (clk60),
        .rrst_n  (rst_n),
        .r_valid (h_valid),
        .r_data  (h_rdata),
        .r_pop   (h_pop)
    );

    // ---------------- FS / LS chain (sampler island + clk60) ----------------
    wire [7:0] rcv_v, dp_v, dm_v;
    wire       fb_en, fb_lvl, fb_se0, fb_act;
    wire       f_w0, f_w1, f_busy, f_ovf;
    wire [9:0] f_e0, f_e1;
    wire       f_valid, f_afull;
    wire [9:0] f_rdata;
    wire       f_pop;

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

    usb_rx_decoder8 #(.ZMIN_HS(6), .ZMIN_FS(FS_ZMIN)) u_fs_dec (
        .clk60     (clk60),
        .rst_n     (rst_n),
        .hs        (1'b0),
        .s_en      ({7'd0, fb_en}),
        .s_lvl     ({7'h7F, fb_lvl}),
        .s_se0     ({7'd0, fb_se0}),
        .s_act     ({7'd0, fb_act}),
        .buf_afull (f_afull),
        .ev0_wr    (f_w0),
        .ev0_data  (f_e0),
        .ev1_wr    (f_w1),
        .ev1_data  (f_e1),
        .busy      (f_busy),
        .ovf       (f_ovf)
    );

    // event FIFO: 4 entries, up to two writes (ev0 then ev1) and one pop per tick
    reg [9:0] fq [0:3];
    reg [1:0] f_rp;
    reg [2:0] f_cnt;
    wire [1:0] f_wp = f_rp + f_cnt[1:0];

    assign f_valid = (f_cnt != 3'd0);
    assign f_rdata = fq[f_rp];
    assign f_afull = (f_cnt >= 3'd2);            // fewer than 3 free entries

    always @(posedge clk60) begin
        if (f_w0) fq[f_wp]        <= f_e0;
        if (f_w1) fq[f_wp + 2'd1] <= f_e1;
    end

    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            f_rp  <= 2'd0;
            f_cnt <= 3'd0;
        end else begin
            if (f_pop) f_rp <= f_rp + 2'd1;
            f_cnt <= f_cnt + f_w0 + f_w1 - (f_pop ? 3'd1 : 3'd0);
        end
    end

    // ---------------- output stage (clk60, one event per tick) ----------------
    reg        open;                  // a packet is open at the output
    reg        src;                   // 0 = HS chain, 1 = FS/LS chain (while open)

    wire       sel   = open ? src : !h_valid;          // idle: HS first
    wire       e_val = sel ? f_valid : h_valid;
    wire [9:0] e_dat = sel ? f_rdata : h_rdata;
    wire [1:0] e_typ = e_dat[9:8];

    // a START while a packet is open is not popped: the open packet is closed
    // with an error first (cannot happen with usb_rx_eop_check, which always
    // pairs START / END)
    wire       e_pop = e_val && !(open && (e_typ == EV_START));
    assign h_pop = e_pop && !sel;
    assign f_pop = e_pop &&  sel;

    assign rx_busy = open;

    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            open     <= 1'b0;
            src      <= 1'b0;
            rx_start <= 1'b0;
            rx_valid <= 1'b0;
            rx_data  <= 8'd0;
            rx_end   <= 1'b0;
            rx_error <= 1'b0;
        end else begin
            rx_start <= 1'b0;
            rx_valid <= 1'b0;
            rx_end   <= 1'b0;
            rx_error <= 1'b0;
            if (e_val) begin
                if (!open) begin
                    if (e_typ == EV_START) begin
                        rx_start <= 1'b1;
                        open     <= 1'b1;
                        src      <= sel;
                    end                                     // else: orphan, dropped
                end else begin
                    case (e_typ)
                        EV_BYTE: begin
                            rx_valid <= 1'b1;
                            rx_data  <= e_dat[7:0];
                        end
                        EV_END: begin
                            rx_end   <= 1'b1;
                            rx_error <= e_dat[0];
                            open     <= 1'b0;
                        end
                        default: begin                      // START while open
                            rx_end   <= 1'b1;
                            rx_error <= 1'b1;
                            open     <= 1'b0;
                        end
                    endcase
                end
            end
        end
    end

endmodule
