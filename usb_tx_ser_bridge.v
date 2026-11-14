//-----------------------------------------------------------------------------
// usb_tx_ser_bridge.v - clk60 word interface for usb_tx_serializer (Plan_60MHz.md P2)
//
//   clk60 domain (NRZI encoder, tx_path)          clk_bit island (480 MHz)
//   in_valid / in_data / in_nbits / in_last ---> [THIS BLOCK: usb_tx_serializer]
//   in_ready, busy_t, tx_done_t, tx_underrun_t <---                      ---> txd / tx_en / tx_se0
//
// Interim block for P2..P5: the byte path runs on clk60 while the serializer
// stays a bit-serial clk_bit design until it is rewritten in P6.  All
// crossings follow the boundary rule of usb_clk_gen: the clk_bit side samples
// clk60 data and updates the registers that the clk60 side reads only on ld
// (high while phase = 3, so the registers change on E4, half a clk60 period
// away from the clk60 edges E0).  SDC: the 4 / 3 multicycles of
// constraints/usb_phy.sdc.
//
// Word handshake
//   * The serializer runs with ce60 = ld: it takes a word on E4 when in_valid
//     and its own ready are high (accept).  in_valid / in_data come from clk60
//     flops launched on E0, so they are stable there.
//   * in_ready (to the clk60 side) is acc_q = accept, registered on ld: it says
//     "the word you are presenting has been taken".  At the next clk60 edge
//     the sender sees in_valid && in_ready and moves on, exactly as with a
//     ready that is evaluated on that edge.  The sender must hold a word until
//     it sees in_ready (usb_nrzi_encoder does), and the serializer never sees
//     the same word twice: the next ld comes after the sender has moved on.
//   * An underrun blocks the accept until the ld that shows it as
//     tx_underrun_t (see "block" below).
//   * Compared with the single-clock design (accept on the E0 at the end of
//     the tick in which the word was presented) the serializer takes every
//     word 4 clk_bit cycles earlier, at the same point of the same tick.  Its
//     whole bit-level schedule is therefore the old one shifted by exactly
//     -4 clk_bit cycles, and every clk60-side handshake falls into the same
//     tick as before (tb_usb_tx_path_split compares both).  On the line, txd /
//     tx_en / tx_se0 / tx_done / tx_underrun come 4 clk_bit cycles earlier.
//
// Status for the clk60 side (registered on ld, stable at every clk60 edge)
//   busy_t        serializer busy or a word accepted at this ld.  busy rises
//                 only through an accept, so it cannot be missed between two
//                 ld edges; it falls at the first ld after the serializer is
//                 idle.
//   tx_done_t,    the serializer's 1-cycle pulses, collected between two ld
//   tx_underrun_t edges and shown for exactly one tick (one clk60 edge).
//   The raw pulses tx_done / tx_underrun stay available on the clk_bit side.
//
// Parameters and the remaining ports: as usb_tx_serializer (speed / eop_dis
// are static from TXCMD to tx_done and are sampled at packet start).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_tx_ser_bridge #(
    parameter FS_DIV = 40,
    parameter LS_DIV = 320,
    parameter DIV_W  = 9
) (
    input  wire        clk_bit,
    input  wire        rst_n,
    input  wire        ld,           // boundary strobe (usb_clk_gen), high while phase = 3

    input  wire [1:0]  speed,
    input  wire        eop_dis,

    // clk60 side
    input  wire        in_valid,
    output wire        in_ready,
    input  wire [7:0]  in_data,
    input  wire [3:0]  in_nbits,
    input  wire        in_last,
    output reg         busy_t,
    output reg         tx_done_t,
    output reg         tx_underrun_t,

    // clk_bit side
    output wire        txd,
    output wire        tx_en,
    output wire        tx_se0,
    output wire [1:0]  tx_speed,
    output wire        tx_done,
    output wire        tx_underrun
);

    wire ser_ready, ser_busy;
    reg  acc_q, done_f, under_f;

    usb_tx_serializer #(
        .FS_DIV (FS_DIV),
        .LS_DIV (LS_DIV),
        .DIV_W  (DIV_W)
    ) u_ser (
        .clk_bit     (clk_bit),
        .rst_n       (rst_n),
        .ce60        (ld),
        .speed       (speed),
        .eop_dis     (eop_dis),
        .in_valid    (in_valid & ~block),
        .in_ready    (ser_ready),
        .in_data     (in_data),
        .in_nbits    (in_nbits),
        .in_last     (in_last),
        .txd         (txd),
        .tx_en       (tx_en),
        .tx_se0      (tx_se0),
        .tx_speed    (tx_speed),
        .busy        (ser_busy),
        .tx_done     (tx_done),
        .tx_underrun (tx_underrun)
    );

    // An underrun that has not been shown to the clk60 side yet blocks the
    // accept: with eop_dis the serializer is ready again one cycle after the
    // underrun, and the next ld must not take a word of the aborted packet.
    // (The single-clock design gets the same from drop, set the cycle after
    // the pulse.)  From the ld on, tx_underrun_t / drop in usb_tx_path block.
    wire block  = under_f | tx_underrun;
    wire accept = in_valid & ~block & ser_ready;   // the serializer's accept on this ld

    assign in_ready = acc_q;

    always @(posedge clk_bit or negedge rst_n) begin
        if (!rst_n) begin
            acc_q         <= 1'b0;
            busy_t        <= 1'b0;
            done_f        <= 1'b0;
            under_f       <= 1'b0;
            tx_done_t     <= 1'b0;
            tx_underrun_t <= 1'b0;
        end else if (ld) begin
            acc_q         <= accept;
            busy_t        <= accept | ser_busy;
            tx_done_t     <= done_f  | tx_done;
            tx_underrun_t <= under_f | tx_underrun;
            done_f        <= 1'b0;
            under_f       <= 1'b0;
        end else begin
            done_f        <= done_f  | tx_done;
            under_f       <= under_f | tx_underrun;
        end
    end

endmodule
