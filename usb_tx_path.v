//-----------------------------------------------------------------------------
// usb_tx_path.v
//
// Serial back end of the USB 2.0 PHY TX path (HS / FS / LS):
//
//   SYNC/PID mux -> [ usb_bit_stuffer -> usb_nrzi_encoder -> usb_tx_serializer8 ]
//                                                -> txd_v / tx_en_v / tx_se0_v (clk60)
//
// Input: the byte stream of one packet (SYNC, PID, payload, as built by
//   usb_tx_sync_mux), ready/valid, in_last on the last byte, bit 0 sent first.
//   Packets must have at least one byte (EOP-only packets are not supported by
//   the bit stuffer).
// Output: line signal vectors as described in usb_tx_serializer8 (txd J = 1 /
//   K = 0, tx_en, tx_se0 per bit, tx_speed), EOP appended by the serializer.
//
// Configuration (static during a packet)
//   speed     : XcvrSelect, 00 HS, 01 FS, 10 LS, 11 sent at the FS rate;
//               sampled by the serializer at packet start.
//   bypass_en : 1 = no bit stuffing and no NRZI (OpMode 10); the data bits are
//               sent as line levels.  SYNC / EOP are still sent (SYNC can be
//               disabled upstream with sync_dis).
//   eop_dis   : 1 = no EOP at the end of the packet (OpMode 10 chirp / K
//               signalling, see usb_tx_serializer8 and usb_mode_term_ctrl).
//
// Underrun (the serializer did not get a word in time; it ends the packet
//   with an EOP and pulses tx_underrun for one tick): the rest of the aborted
//   packet is still in the stuffer or upstream.  This block discards it (drop = 1: the stuffer
//   output is drained and not passed on) up to and including the stuffer's last
//   word of that packet, so it is not sent as a second, bogus packet.  The next
//   packet is sent normally.
//
// busy: 1 from the first byte accepted until the serializer has finished the
//   EOP of the last packet (also while discarding after an underrun).  The next
//   packet may already enter the stuffer while the serializer is still sending
//   the EOP of the previous one.
//
// Parameters: FS_DIV / LS_DIV stay in clk_bit cycles per bit (40 / 320, must
//   be multiples of 8); the serializer counts ticks (FS_DIV / 8, LS_DIV / 8).
//
// Clocking (Plan_60MHz.md P6): clk60 only (the leaves' ce tied to 1).  The
//   serializer is usb_tx_serializer8: the line comes out as 8-bit vectors per
//   tick (txd_v / tx_en_v / tx_se0_v, bit 0 first) for usb_afe_tx_if8 and
//   usb_tx_piso, the only 480 MHz stage.  tx_done / tx_underrun are one-tick
//   pulses.  The input side behaves tick for tick as the old bit-serial path
//   (usb_tx_serializer, kept as a reference model; tb_usb_tx_vec).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_tx_path #(
    parameter FS_DIV = 40,        // clk_bit cycles per FS bit (multiple of 8)
    parameter LS_DIV = 320,       // clk_bit cycles per LS bit (multiple of 8)
    parameter DIV_W  = 9          // >= clog2(LS_DIV); the serializer counts ticks (DIV_W - 3 bits)
) (
    input  wire        clk,          // clk60
    input  wire        rst_n,

    input  wire [1:0]  speed,
    input  wire        bypass_en,
    input  wire        eop_dis,

    input  wire        in_valid,
    output wire        in_ready,
    input  wire [7:0]  in_data,
    input  wire        in_last,

    output wire [7:0]  txd_v,
    output wire [7:0]  tx_en_v,
    output wire [7:0]  tx_se0_v,
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

    reg         drop;            // discarding the rest of an underrun packet
    reg         pkt_open;        // a packet is inside the stuffer (first byte in, last word not out)

    // the one-tick underrun is used at once (with drop), so the discard starts
    // on the tick after the missing word, as in the bit-serial design
    wire        drop_now = drop | tx_underrun;

    usb_bit_stuffer u_stuff (
        .clk       (clk),
        .rst_n     (rst_n),
        .ce        (1'b1),
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
        .clk       (clk),
        .rst_n     (rst_n),
        .ce        (1'b1),
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

    initial if ((FS_DIV % 8) != 0 || (LS_DIV % 8) != 0)
        $display("ERROR: usb_tx_path FS_DIV / LS_DIV must be multiples of 8");

    usb_tx_serializer8 #(
        .FS_TK (FS_DIV / 8),
        .LS_TK (LS_DIV / 8),
        .TK_W  (DIV_W - 3)
    ) u_ser (
        .clk         (clk),
        .rst_n       (rst_n),
        .speed       (speed),
        .eop_dis     (eop_dis),
        .in_valid    (n_valid && !drop_now),
        .in_ready    (ser_ready),
        .in_data     (n_data),
        .in_nbits    (n_nbits),
        .in_last     (n_last),
        .txd_v       (txd_v),
        .tx_en_v     (tx_en_v),
        .tx_se0_v    (tx_se0_v),
        .tx_speed    (tx_speed),
        .busy        (ser_busy),
        .tx_done     (tx_done),
        .tx_underrun (tx_underrun)
    );

    wire in_xfer   = in_valid && in_ready;
    wire last_word = n_valid && n_ready && n_last;   // stuffer released its last word

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            drop     <= 1'b0;
            pkt_open <= 1'b0;
        end else begin
            if (in_xfer)
                pkt_open <= 1'b1;
            else if (last_word)
                pkt_open <= 1'b0;

            // tx_underrun can only pulse while the packet's last word has not
            // reached the serializer, so the rest of the packet is still pending.
            // The release has priority: the one-tick underrun can come on the
            // tick on which the last word is discarded (drop_now), and then
            // nothing is left to discard.
            if (last_word)
                drop <= 1'b0;
            else if (tx_underrun)
                drop <= 1'b1;
        end
    end

    assign busy = pkt_open | drop | ser_busy;

endmodule
