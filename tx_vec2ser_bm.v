//-----------------------------------------------------------------------------
// tx_vec2ser_bm.v - TX line vectors -> serial line signals (testbench only)
//
// Behavioural helper for the testbenches that check the TX line bit by bit
// (Plan_60MHz.md P6).  It turns the clk60 vectors of usb_tx_serializer8 /
// usb_tx_path (txd_v / tx_en_v / tx_se0_v, bit 0 first) back into txd / tx_en /
// tx_se0 on clk_bit with exactly the timing of the old bit-serial serializer
// (ref_tx_serializer with ce60 on the clk60 edges): vector bit i of tick T
// (registered on the clk60 edge 8T) appears after clk_bit edge 8T + 2 + i.  So
// line checkers written for the single-clock design keep their cycle numbers.
// The hardware PISO (usb_tx_piso) puts the pins LAT = 9 cycles later; this
// model is not it and is never synthesized.
//
// tx_done / tx_underrun (one-tick clk60 pulses) become one-cycle pulses:
//   tx_done on the release bit (the first bit of the flagged vector with
//   tx_en = 0, as the old pulse), tx_underrun on bit 0 of the flagged vector.
//
// Phase: taken from ld (high in the clk_bit cycle before E4); the vectors are
//   latched on E2, two cycles after the clk60 edge that updated them.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tx_vec2ser_bm (
    input  wire       clk_bit,
    input  wire       ld,
    input  wire [7:0] txd_v,
    input  wire [7:0] tx_en_v,
    input  wire [7:0] tx_se0_v,
    input  wire       tx_done_t,
    input  wire       tx_underrun_t,
    output reg        txd,
    output reg        tx_en,
    output reg        tx_se0,
    output reg        tx_done,
    output reg        tx_underrun
);
    reg  [2:0] ph = 3'd0;               // phase after this edge (E4 -> 4)
    reg  [7:0] ld_d = 8'hFF, ld_e = 8'h00, ld_s = 8'h00;
    reg        ld_dn = 1'b0, ld_un = 1'b0;
    integer    rel = 8;
    reg  [2:0] k;

    initial begin txd = 1'b1; tx_en = 1'b0; tx_se0 = 1'b0; tx_done = 1'b0; tx_underrun = 1'b0; end

    always @(posedge clk_bit) begin
        ph <= ld ? 3'd4 : ph + 3'd1;
        // this edge is E(ph + 1); E2 starts a new vector
        k = ph - 3'd1;                  // bit index sent after this edge (E2 -> 0)
        if (ph == 3'd1) begin
            ld_d = txd_v; ld_e = tx_en_v; ld_s = tx_se0_v;
            ld_dn = tx_done_t; ld_un = tx_underrun_t;
            // rel = first bit with tx_en = 0 after the leading ones
            rel = 0;
            while (rel < 8 && tx_en_v[rel]) rel = rel + 1;
        end
        txd         <= ld_d[k];
        tx_en       <= ld_e[k];
        tx_se0      <= ld_s[k];
        tx_done     <= ld_dn && (k == rel[2:0]) && (rel < 8);
        tx_underrun <= ld_un && (k == 3'd0);
    end
endmodule
