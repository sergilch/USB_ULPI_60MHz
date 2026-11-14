//-----------------------------------------------------------------------------
// usb_tx_path.v
//
// Serial back end of the USB 2.0 PHY TX path (HS / FS / LS):
//
//   SYNC/PID mux -> [ usb_bit_stuffer -> usb_nrzi_encoder -> usb_tx_serializer ]
//                                                              -> txd / tx_en / tx_se0
//
// Input: the byte stream of one packet (SYNC, PID, payload, as built by
//   usb_tx_sync_mux), ready/valid, in_last on the last byte, bit 0 sent first.
//   Packets must have at least one byte (EOP-only packets are not supported by
//   the bit stuffer).
// Output: line signals as described in usb_tx_serializer (txd J = 1 / K = 0,
//   tx_en, tx_se0, tx_speed), EOP appended by the serializer.
//
// Configuration (static during a packet)
//   speed     : XcvrSelect, 00 HS, 01 FS, 10 LS, 11 sent at the FS rate;
//               sampled by the serializer at packet start.
//   bypass_en : 1 = no bit stuffing and no NRZI (OpMode 10); the data bits are
//               sent as line levels.  SYNC / EOP are still sent (SYNC can be
//               disabled upstream with sync_dis).
//   eop_dis   : 1 = no EOP at the end of the packet (OpMode 10 chirp / K
//               signalling, see usb_tx_serializer and usb_mode_term_ctrl).
//
// Underrun (HS: the serializer did not get a word in time; it ends the packet
//   with an EOP and pulses tx_underrun): the rest of the aborted packet is still
//   in the stuffer or upstream.  This block discards it (drop = 1: the stuffer
//   output is drained and not passed on) up to and including the stuffer's last
//   word of that packet, so it is not sent as a second, bogus packet.  The next
//   packet is sent normally.
//
// busy: 1 from the first byte accepted until the serializer has finished the
//   EOP of the last packet (also while discarding after an underrun).  The next
//   packet may already enter the stuffer while the serializer is still sending
//   the EOP of the previous one.
//
// Clocking (parameter SPLIT)
//   SPLIT = 0: everything on clk_bit; the byte / word interfaces use the tick
//     enable ce60 (one clk_bit cycle in eight, aligned with clk60).  clk60 and
//     ld are not used.  This is the single-clock design, used by the AFE-level
//     testbenches until P6 of Plan_60MHz.md.
//   SPLIT = 1 (Plan_60MHz.md P2): the stuffer, the NRZI encoder and the discard
//     logic run on clk60 (ce = 1); the serializer stays on clk_bit behind
//     usb_tx_ser_bridge (crossings on ld only).  ce60 is not used.  The input
//     side behaves tick for tick as with SPLIT = 0; the line outputs and the
//     raw tx_done / tx_underrun pulses come 4 clk_bit cycles earlier
//     (usb_tx_ser_bridge header, tb_usb_tx_path_split).  busy is a clk60-side
//     signal; the discard logic uses the bridge's one-tick tx_underrun_t.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_tx_path #(
    parameter FS_DIV = 40,
    parameter LS_DIV = 320,
    parameter DIV_W  = 9,
    parameter SPLIT  = 0          // 1 = byte side on clk60, serializer bridged
) (
    input  wire        clk_bit,
    input  wire        rst_n,
    input  wire        ce60,         // SPLIT = 0 only
    input  wire        clk60,        // SPLIT = 1 only
    input  wire        ld,           // SPLIT = 1 only (usb_clk_gen)

    input  wire [1:0]  speed,
    input  wire        bypass_en,
    input  wire        eop_dis,

    input  wire        in_valid,
    output wire        in_ready,
    input  wire [7:0]  in_data,
    input  wire        in_last,

    output wire        txd,
    output wire        tx_en,
    output wire        tx_se0,
    output wire [1:0]  tx_speed,

    output wire        busy,
    output wire        tx_done,
    output wire        tx_underrun
);

    // stuffer -> NRZI
    wire        s_valid, s_ready, s_last;
    wire [7:0]  s_data;
    wire [3:0]  s_nbits;

    // NRZI -> serializer (before the discard gate)
    wire        n_valid, n_ready, n_last;
    wire [7:0]  n_data;
    wire [3:0]  n_nbits;

    wire        ser_ready, ser_busy;
    wire        ser_underrun;    // underrun as seen by the discard logic

    reg         drop;        // discarding the rest of an underrun packet
    reg         pkt_open;        // a packet is inside the stuffer (first byte in, last word not out)

    // clock / enable of the byte side (constant select)
    wire        clk_w = SPLIT ? clk60 : clk_bit;
    wire        ce_w  = SPLIT ? 1'b1  : ce60;
    // SPLIT = 1: the bridge's one-tick underrun is used at once (with drop),
    // so the discard starts on the same tick as with SPLIT = 0
    wire        drop_now = drop | (SPLIT ? ser_underrun : 1'b0);

    usb_bit_stuffer u_stuff (
        .clk       (clk_w),
        .rst_n     (rst_n),
        .ce        (ce_w),
        .stuff_dis (bypass_en),
        .in_valid  (in_valid),
        .in_ready  (in_ready),
        .in_data   (in_data),
        .in_last   (in_last),
        .out_valid (s_valid),
        .out_ready (s_ready),
        .out_data  (s_data),
        .out_nbits (s_nbits),
        .out_last  (s_last)
    );

    usb_nrzi_encoder u_nrzi (
        .clk       (clk_w),
        .rst_n     (rst_n),
        .ce        (ce_w),
        .bypass_en (bypass_en),
        .in_valid  (s_valid),
        .in_ready  (s_ready),
        .in_data   (s_data),
        .in_nbits  (s_nbits),
        .in_last   (s_last),
        .out_valid (n_valid),
        .out_ready (n_ready),
        .out_data  (n_data),
        .out_nbits (n_nbits),
        .out_last  (n_last)
    );

    // discard gate: while drop = 1 the words are consumed here, not by the serializer
    assign n_ready = drop_now ? 1'b1 : ser_ready;

    generate
        if (SPLIT) begin : g_split
            usb_tx_ser_bridge #(
                .FS_DIV (FS_DIV),
                .LS_DIV (LS_DIV),
                .DIV_W  (DIV_W)
            ) u_ser (
                .clk_bit       (clk_bit),
                .rst_n         (rst_n),
                .ld            (ld),
                .speed         (speed),
                .eop_dis       (eop_dis),
                .in_valid      (n_valid && !drop_now),
                .in_ready      (ser_ready),
                .in_data       (n_data),
                .in_nbits      (n_nbits),
                .in_last       (n_last),
                .busy_t        (ser_busy),
                .tx_done_t     (),
                .tx_underrun_t (ser_underrun),
                .txd           (txd),
                .tx_en         (tx_en),
                .tx_se0        (tx_se0),
                .tx_speed      (tx_speed),
                .tx_done       (tx_done),
                .tx_underrun   (tx_underrun)
            );
        end else begin : g_single
            usb_tx_serializer #(
                .FS_DIV (FS_DIV),
                .LS_DIV (LS_DIV),
                .DIV_W  (DIV_W)
            ) u_ser (
                .clk_bit     (clk_bit),
                .rst_n       (rst_n),
                .ce60        (ce60),
                .speed       (speed),
                .eop_dis     (eop_dis),
                .in_valid    (n_valid && !drop),
                .in_ready    (ser_ready),
                .in_data     (n_data),
                .in_nbits    (n_nbits),
                .in_last     (n_last),
                .txd         (txd),
                .tx_en       (tx_en),
                .tx_se0      (tx_se0),
                .tx_speed    (tx_speed),
                .busy        (ser_busy),
                .tx_done     (tx_done),
                .tx_underrun (tx_underrun)
            );
            assign ser_underrun = tx_underrun;
        end
    endgenerate

    wire in_xfer   = ce_w && in_valid && in_ready;
    wire last_word = ce_w && n_valid && n_ready && n_last;   // stuffer released its last word

    always @(posedge clk_w or negedge rst_n) begin
        if (!rst_n) begin
            drop <= 1'b0;
            pkt_open <= 1'b0;
        end else begin
            if (in_xfer)
                pkt_open <= 1'b1;
            else if (last_word)
                pkt_open <= 1'b0;

            // tx_underrun can only pulse while the packet's last word has not
            // reached the serializer, so the rest of the packet is still pending.
            // The release has priority: with SPLIT = 1 the one-tick underrun
            // can come on the tick on which the last word is discarded
            // (drop_now), and then nothing is left to discard.  (SPLIT = 0:
            // the pulse is never on an E0, so both never coincide.)
            if (last_word)
                drop <= 1'b0;
            else if (ser_underrun)
                drop <= 1'b1;
        end
    end

    assign busy = pkt_open | drop | ser_busy;

endmodule
