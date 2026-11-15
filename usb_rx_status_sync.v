//-----------------------------------------------------------------------------
// usb_rx_status_sync.v
//
// "Receiver status sync + glitch filter" of the AFE interface (WORK_PLAN 3.1 /
// 4.1, AFE_INTEGRATION_PLAN.md phase A5).  Synchronization point for the
// slow analog status outputs.  Position:
//
//   AFE: squelch / disconnect (SQUELCH_A, DISC_A), VBUS / ID comparators
//     --> [THIS BLOCK] --> usb_line_state (LineState, HostDisconnect)
//                      --> VbusState / IdGnd of usb_ulpi_phy_top
//
// The FS/LS receivers (RXDP_A, RXDM_A, RXRCV_A) are not synchronized here
// (Plan_60MHz.md P4): usb_rx_fsls_sampler in usb_rx_datapath takes them, and
// usb_line_state gets its D+ / D- / rxrcv samples from there.
//
// Clocking (Plan_60MHz.md P7): every output is a clk60 register.  Only the
// squelch / disconnect capture stays at bit rate, in a 7-flop clk_bit island
// (moved here from usb_line_state):
//
//   2. squelch, disc: 2-FF synchronizer on clk_bit, then one value per tick,
//      taken over on ld (E4, usb_clk_gen boundary rule):
//        squelch: the synchronized sample at E4;
//        disc:    the OR of the synchronized samples of the 8 clk_bit edges
//                 E5 .. E4, so a disconnect pulse of one clk_bit cycle counts
//                 (the HostDisconnect window of usb_line_state ORs per tick).
//      Glitch filter on clk60 (usb_rx_status_flt, en = 1): the output takes a
//      new value once the tick value has held it for flt + 1 consecutive ticks
//      (flt = sq_flt / disc_flt, in ticks; 0 = no filtering).  Latency from
//      the input: 2 clk_bit cycles + up to 8 to E4 + 4 to the next clk60 edge
//      + flt ticks, i.e. 6..14 clk_bit cycles + flt ticks.
//      Before P7 the filter counted clk_bit cycles (default 2 = 6.25 ns in
//      total).  The squelch detector already filters (spec 4.2: 4 ns release /
//      12 ns hold); this filter is the digital margin against comparator
//      chatter.  Recommended: sq_flt = 1 (the value must be the same at two
//      E4 samples 16.7 ns apart), disc_flt = 0 (a disconnect within an EOP can
//      be shorter than two ticks).  It delays the HS LineState only, not the
//      HS data path (usb_afe_rx_if has its own squelch synchronizer on clk_rx).
//   3. a_vbus_vld, sess_vld, sess_end, id_gnd: 2-FF synchronizer on clk60,
//      then a debounce: a new value is taken after it held for vb_flt + 1
//      consecutive ticks (VB_W bits: up to 2^16 ticks = 1.09 ms with the
//      default VB_W = 16, the ms-range debounce of WORK_PLAN 4.1).  As before
//      P7 apart from the synchronizer clock (was clk_bit, with the filter on
//      ce60): latency 2 ticks + vb_flt + 1 ticks (was 2 cycles + vb_flt + 1).
//
// Reset values are the isolated values of DOC/afe_interface_spec.md 3.4 /
// 3.5: squelch = 1, disc = 0, a_vbus_vld = sess_vld = 0, sess_end = 1,
// id_gnd = 0.  The filters start in that state, so a status that is already
// different at reset release shows up after the normal filter delay (and
// produces the RXCMD it should).
//
// Filter lengths are ports until the trim / config registers exist (WORK_PLAN
// 6.4); they are quasi-static.
//
// Clocks: clk60; clk_bit + ld for the squelch / disconnect island.  Reset
//   rst_n, active low, asynchronous (also the island's: every island flop holds
//   its reset value with an input that equals it until the inputs move).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_rx_status_sync #(
    parameter SQ_W = 4,               // squelch / disconnect filter counter width (ticks)
    parameter VB_W = 16               // VBUS / ID debounce counter width (ticks)
) (
    input  wire            clk_bit,   // 480 MHz: squelch / disconnect island only
    input  wire            rst_n,
    input  wire            clk60,     // core clock (usb_clk_gen)
    input  wire            ld,        // island strobe (usb_clk_gen)

    // asynchronous AFE outputs
    input  wire            squelch,
    input  wire            disc,
    input  wire            a_vbus_vld,
    input  wire            sess_vld,
    input  wire            sess_end,
    input  wire            id_gnd,

    // filter lengths (quasi-static), all in clk60 ticks
    input  wire [SQ_W-1:0] sq_flt,    // squelch: extra ticks
    input  wire [SQ_W-1:0] disc_flt,  // disconnect: extra ticks
    input  wire [VB_W-1:0] vb_flt,    // VBUS / ID: extra ticks

    // synchronized + filtered (clk60 domain)
    output wire            squelch_s,
    output wire            disc_s,
    output wire            a_vbus_vld_s,
    output wire            sess_vld_s,
    output wire            sess_end_s,
    output wire            id_gnd_s
);

    // ---------------- clk_bit island: squelch / disconnect ----------------
    reg sq1, sq2, dc1, dc2;           // 2-FF synchronizers
    reg dc_a;                         // disc seen since the last ld
    reg sq_t, dc_t;                   // tick values (change on ld = E4)
    always @(posedge clk_bit or negedge rst_n) begin
        if (!rst_n) begin
            sq1 <= 1'b1; sq2 <= 1'b1; dc1 <= 1'b0; dc2 <= 1'b0;
            dc_a <= 1'b0; sq_t <= 1'b1; dc_t <= 1'b0;
        end else begin
            sq1 <= squelch; sq2 <= sq1;
            dc1 <= disc;    dc2 <= dc1;
            if (ld) begin
                sq_t <= sq2;
                dc_t <= dc_a | dc2;
                dc_a <= 1'b0;
            end else
                dc_a <= dc_a | dc2;
        end
    end

    usb_rx_status_flt #(.W(SQ_W), .RST_V(1'b1)) u_sq (
        .clk(clk60), .rst_n(rst_n), .en(1'b1), .din(sq_t), .len(sq_flt),
        .dout(squelch_s));
    usb_rx_status_flt #(.W(SQ_W), .RST_V(1'b0)) u_disc (
        .clk(clk60), .rst_n(rst_n), .en(1'b1), .din(dc_t), .len(disc_flt),
        .dout(disc_s));

    // ---------------- VBUS / ID: 2-FF on clk60, debounce in ticks ----------------
    // reset value = isolated value of each input (bit order as din)
    localparam [3:0] RST_V = {1'b0, 1'b1, 1'b0, 1'b0};

    wire [3:0] din = {id_gnd, sess_end, sess_vld, a_vbus_vld};
    reg  [3:0] s1, s2;
    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            s1 <= RST_V;
            s2 <= RST_V;
        end else begin
            s1 <= din;
            s2 <= s1;
        end
    end

    usb_rx_status_flt #(.W(VB_W), .RST_V(1'b0)) u_avv (
        .clk(clk60), .rst_n(rst_n), .en(1'b1), .din(s2[0]), .len(vb_flt),
        .dout(a_vbus_vld_s));
    usb_rx_status_flt #(.W(VB_W), .RST_V(1'b0)) u_sv (
        .clk(clk60), .rst_n(rst_n), .en(1'b1), .din(s2[1]), .len(vb_flt),
        .dout(sess_vld_s));
    usb_rx_status_flt #(.W(VB_W), .RST_V(1'b1)) u_se (
        .clk(clk60), .rst_n(rst_n), .en(1'b1), .din(s2[2]), .len(vb_flt),
        .dout(sess_end_s));
    usb_rx_status_flt #(.W(VB_W), .RST_V(1'b0)) u_id (
        .clk(clk60), .rst_n(rst_n), .en(1'b1), .din(s2[3]), .len(vb_flt),
        .dout(id_gnd_s));

endmodule
