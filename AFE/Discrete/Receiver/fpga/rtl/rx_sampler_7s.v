//-----------------------------------------------------------------------------
// rx_sampler_7s.v - 4x oversampling of RX_OUT and 2x sampling of SQUELCH_A /
//                   DISC_A with 7-Series ISERDESE2 (receiver-board FPGA)
//
// RX_OUT (LVDS from the board's SN65LVDS100) -> IBUFDS_DIFF_OUT:
//   O  -> IDELAYE2 (tap_m) -> ISERDESE2 "m"   NETWORKING, DDR, 1:8
//   OB -> IDELAYE2 (tap_s) -> ISERDESE2 "s"   (inverted data, re-inverted here)
// Each ISERDESE2 samples at both edges of clk480 (BUFIO), i.e. 960 Msample/s =
// 2 samples per HS bit (UI 2.083 ns).  The slave path is delayed by
// (tap_s - tap_m) * 78.1 ps; with the default 7 taps (547 ps, ~UI/4) the two
// streams interleave to 4 samples per bit:  s[i] is taken ~UI/4 before m[i]
// (a delayed data path samples older data).  rx_decode.py interleaves them.
// SQUELCH_A and DISC_A (LVCMOS) go straight into ISERDESE2 (no delay).
//
// Outputs per clkdiv (= clk480 / 4 = 120 MHz, BUFR) cycle, sample 0 = oldest:
//   m[7:0], s[7:0], sq[7:0], dc[7:0]
// ISERDESE2 delivers the first received bit on Q8 (UG471, NETWORKING mode); the
// generate below reverses the order (Q_FIRST_IS_Q8 = 0 swaps it back, for
// checking a board with a known pattern).
//
// tap_m / tap_s are quasi-static (written while no capture runs); a change is
// loaded (IDELAYE2 VAR_LOAD, LD) on the next clkdiv cycle.
// RX_SIM: the primitives come from fpga/sim/prims_sim.v.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module rx_sampler_7s #(
    parameter DIFF_TERM     = "TRUE",
    parameter Q_FIRST_IS_Q8 = 1
) (
    input  wire       clk480,       // BUFIO
    input  wire       clkdiv,       // BUFR /4, phase-aligned with clk480
    input  wire       rst,          // synchronous to clkdiv
    input  wire       rx_out_p,
    input  wire       rx_out_n,
    input  wire       squelch_a,
    input  wire       disc_a,
    input  wire [4:0] tap_m,
    input  wire [4:0] tap_s,
    output reg  [7:0] m,
    output reg  [7:0] s,
    output reg  [7:0] sq,
    output reg  [7:0] dc
);

    wire rx_o, rx_ob, d_m, d_s, sq_i, dc_i;
    IBUFDS_DIFF_OUT #(.DIFF_TERM(DIFF_TERM), .IBUF_LOW_PWR("FALSE")) u_ibuf (
        .I(rx_out_p), .IB(rx_out_n), .O(rx_o), .OB(rx_ob));
    IBUF u_ibsq (.I(squelch_a), .O(sq_i));
    IBUF u_ibdc (.I(disc_a),    .O(dc_i));

    // tap load: LD for one clkdiv cycle whenever a tap value changes
    reg [4:0] tm_q, ts_q;
    reg       ld;
    always @(posedge clkdiv) begin
        tm_q <= tap_m;
        ts_q <= tap_s;
        ld   <= rst || (tm_q != tap_m) || (ts_q != tap_s);
    end

    IDELAYE2 #(.IDELAY_TYPE("VAR_LOAD"), .DELAY_SRC("IDATAIN"), .IDELAY_VALUE(0),
               .HIGH_PERFORMANCE_MODE("TRUE"), .REFCLK_FREQUENCY(200.0),
               .SIGNAL_PATTERN("DATA"), .CINVCTRL_SEL("FALSE"), .PIPE_SEL("FALSE"))
        u_dly_m (.C(clkdiv), .CE(1'b0), .INC(1'b0), .LD(ld), .LDPIPEEN(1'b0), .REGRST(1'b0),
                 .CINVCTRL(1'b0), .CNTVALUEIN(tm_q), .CNTVALUEOUT(), .IDATAIN(rx_o),
                 .DATAIN(1'b0), .DATAOUT(d_m));
    IDELAYE2 #(.IDELAY_TYPE("VAR_LOAD"), .DELAY_SRC("IDATAIN"), .IDELAY_VALUE(0),
               .HIGH_PERFORMANCE_MODE("TRUE"), .REFCLK_FREQUENCY(200.0),
               .SIGNAL_PATTERN("DATA"), .CINVCTRL_SEL("FALSE"), .PIPE_SEL("FALSE"))
        u_dly_s (.C(clkdiv), .CE(1'b0), .INC(1'b0), .LD(ld), .LDPIPEEN(1'b0), .REGRST(1'b0),
                 .CINVCTRL(1'b0), .CNTVALUEIN(ts_q), .CNTVALUEOUT(), .IDATAIN(rx_ob),
                 .DATAIN(1'b0), .DATAOUT(d_s));

    wire [7:0] q_m, q_s, q_sq, q_dc;
    `define RX_ISERDES(NAME, DIN, DLY, IOBD, Q)                                           \
        ISERDESE2 #(.DATA_RATE("DDR"), .DATA_WIDTH(8), .INTERFACE_TYPE("NETWORKING"),     \
                    .IOBDELAY(IOBD), .NUM_CE(1), .OFB_USED("FALSE"), .SERDES_MODE("MASTER"), \
                    .DYN_CLKDIV_INV_EN("FALSE"), .DYN_CLK_INV_EN("FALSE"))                \
            NAME (.Q1(Q[0]), .Q2(Q[1]), .Q3(Q[2]), .Q4(Q[3]), .Q5(Q[4]), .Q6(Q[5]),        \
                  .Q7(Q[6]), .Q8(Q[7]), .O(), .SHIFTOUT1(), .SHIFTOUT2(),                  \
                  .BITSLIP(1'b0), .CE1(1'b1), .CE2(1'b1), .CLKDIVP(1'b0),                  \
                  .CLK(clk480), .CLKB(~clk480), .CLKDIV(clkdiv), .OCLK(1'b0), .OCLKB(1'b0), \
                  .DYNCLKDIVSEL(1'b0), .DYNCLKSEL(1'b0), .D(DIN), .DDLY(DLY), .OFB(1'b0),  \
                  .RST(rst), .SHIFTIN1(1'b0), .SHIFTIN2(1'b0));
    `RX_ISERDES(u_is_m,  1'b0, d_m,  "IFD",  q_m)
    `RX_ISERDES(u_is_s,  1'b0, d_s,  "IFD",  q_s)
    `RX_ISERDES(u_is_sq, sq_i, 1'b0, "NONE", q_sq)
    `RX_ISERDES(u_is_dc, dc_i, 1'b0, "NONE", q_dc)
    `undef RX_ISERDES

    // sample order: index 0 = oldest
    function [7:0] ord(input [7:0] q);
        integer k;
        begin
            for (k = 0; k < 8; k = k + 1)
                ord[k] = Q_FIRST_IS_Q8 ? q[7 - k] : q[k];
        end
    endfunction

    always @(posedge clkdiv) begin
        m  <= ord(q_m);
        s  <= ~ord(q_s);            // OB path carries the inverted data
        sq <= ord(q_sq);
        dc <= ord(q_dc);
    end

endmodule
