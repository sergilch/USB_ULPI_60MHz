//-----------------------------------------------------------------------------
// usb_rx_hs_frontend.v
//
// HS part of the "RX Data Capture / Clock Buffer" (AFE interface) of the USB
// 2.0 PHY.  Position:
//
//   AFE: HS receiver + CDR --rxd, clk_rx--> [THIS BLOCK] --> 1:8 SIPO (both in
//        usb_rx_hs_sipo) --> word FIFO --> usb_rx_decoder8 (HS, clk60)
//
// Assumption (work plan, decision D1): the CDR delivers a recovered bit clock
// clk_rx (480 MHz nominal, phase- and frequency-locked to the far transmitter,
// free-running at the local rate while there is no signal) and the retimed
// data rxd on it, J = 1 / K = 0.  Since Plan_60MHz.md P5 only this block and
// the SIPO behind it run on clk_rx; the bit chain runs on clk60.  Its
// outputs are exactly those of the single-clock design, so the squelch /
// lock / delay settings measured in A3 keep their meaning.
//
// What it does
//   * captures rxd on clk_rx;
//   * synchronizes the asynchronous qualifiers into clk_rx (2-FF):
//       squelch  : 1 = no valid HS signal on the line (AFE squelch detector),
//       cdr_lock : 1 = the CDR is locked (data valid),
//       enable   : 1 = HS reception allowed (from clk60: HS mode, RX enabled,
//                  not blocked by the local transmitter);
//   * delays the data by the synchronizer latency, so that b_act and b_lvl
//     refer to the same bit;
//   * b_en = 1 in every clk_rx cycle (one bit per cycle), b_se0 = 0 (there is
//     no SE0 in HS signalling), b_act = !squelch && cdr_lock && enable.
//
// Reset (Plan_60MHz.md P9): rst_n and rst_m_n, active low, asynchronous
//   assert, released on the same clk_rx edge (two copies of one synchronizer
//   output; tie both to the same reset when used alone).  rst_m_n only resets
//   flops whose D input equals their reset value at the first clk_rx edge
//   after the release, so its recovery is timed as a 2-cycle path (SDC): a
//   release that lands one edge late, or late and metastable, cannot change
//   their outputs.  rst_n resets the four flops that can change at that edge
//   (single cycle, fan-out 4).  The data flops d0 / d1 / b_lvl have no reset;
//   b_lvl is only meaningful with b_act = 1.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_rx_hs_frontend (
    input  wire clk_rx,
    input  wire rst_n,                // fast reset (low fan-out)
    input  wire rst_m_n,              // multicycle reset, same release edge

    input  wire rxd,
    input  wire squelch,
    input  wire cdr_lock,
    input  wire enable,

    output reg  b_en,
    output reg  b_lvl,
    output wire b_se0,
    output reg  b_act
);

    reg d0, d1;                       // data capture + alignment delay (no reset)
    reg sq1, sq2, lk1, lk2, en1, en2; // 2-FF synchronizers

    assign b_se0 = 1'b0;

    // data: no reset (b_lvl is only used with b_act = 1, which needs >= 3
    // clk_rx edges after the release; usb_rx_hs_sipo's level SIPO has none)
    always @(posedge clk_rx) begin
        d0    <= rxd;
        d1    <= d0;
        b_lvl <= d1;
    end

    // fast group (rst_n): D can differ from the reset value at the first edge
    always @(posedge clk_rx or negedge rst_n) begin
        if (!rst_n) begin
            sq1  <= 1'b1;
            lk1  <= 1'b0;
            en1  <= 1'b0;
            b_en <= 1'b0;
        end else begin
            sq1  <= squelch;
            lk1  <= cdr_lock;
            en1  <= enable;
            b_en <= 1'b1;
        end
    end

    // multicycle group (rst_m_n): D equals the reset value at the first edge
    // after the release (sq2 <- sq1 = 1, lk2 <- lk1 = 0, en2 <- en1 = 0,
    // b_act <- 0), so a release one edge late changes nothing
    always @(posedge clk_rx or negedge rst_m_n) begin
        if (!rst_m_n) begin
            sq2   <= 1'b1;
            lk2   <= 1'b0;
            en2   <= 1'b0;
            b_act <= 1'b0;
        end else begin
            sq2   <= sq1;
            lk2   <= lk1;
            en2   <= en1;
            b_act <= !sq2 && lk2 && en2;
        end
    end

endmodule
