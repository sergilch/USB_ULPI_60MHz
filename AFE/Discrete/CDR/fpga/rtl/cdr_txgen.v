//-----------------------------------------------------------------------------
// cdr_txgen.v - test pattern for the CDR board's data input (FPGA pattern,
//               EP57 D1): 8 line bits per 60 MHz tick to the 8:1 OSERDESE2
//               (480 Mb/s), bit 0 first, J = 1 / K = 0
//
// Modes (TXMODE)
//   0  idle: constant J (no transitions: the CDR free-runs, for the
//      frequency calibration of the host)
//   1  HS packets through the PHY's own TX back end (repo usb_tx_path:
//      bit stuffer -> NRZI -> usb_tx_serializer8, HS, EOP appended):
//      SYNC 00 00 00 80h (31 zeros, 1), PID C3h (DATA0), TXLEN payload bytes
//      = PRBS7 bits (x^7 + x^6 + 1, seed 5Ah at every packet, bit 0 of a byte
//      first; cdr_rxchk regenerates them), then 4 x (TXGAP + 1) ticks of idle J
//      after the serializer has finished.  Between packets the line is J
//      (tx_en = 0), not the HS bus SE0: the CDR board has no squelch.
//   2  PRBS7 line bits (no NRZI, no stuffing), for BER / eye scans
//   3  clock pattern 1010... (a transition every bit)
//   txpkt counts the packets started (cleared by clr).
//
// Clocking: clk = the 60 MHz system clock (OSERDESE2 CLKDIV), rst_n async.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module cdr_txgen (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [1:0]  mode,
    input  wire [7:0]  txlen,
    input  wire [7:0]  txgap,
    input  wire        clr,
    output reg  [7:0]  lw,           // line word, bit 0 first
    output reg  [23:0] txpkt,
    output wire        busy
);
    // ---------------- PRBS7, 8 bits per call ----------------
    // x[n] = x[n-7] ^ x[n-6]; s = the last 7 bits, s[6] the newest
    function [14:0] prbs8(input [6:0] s);     // {next state, 8 bits (bit 0 first)}
        integer i;
        reg [6:0] t;
        reg [7:0] b;
        begin
            t = s;
            for (i = 0; i < 8; i = i + 1) begin
                b[i] = t[0] ^ t[1];
                t    = {b[i], t[6:1]};
            end
            prbs8 = {t, b};
        end
    endfunction

    // ---------------- packets: usb_tx_path ----------------
    reg        in_valid;
    wire       in_ready;
    reg  [7:0] in_data;
    reg        in_last;
    wire [7:0] txd_v, tx_en_v, tx_se0_v;
    wire       tp_busy, tx_done, tx_underrun;
    usb_tx_path u_tx (
        .clk(clk), .rst_n(rst_n), .speed(2'b00), .bypass_en(1'b0), .eop_dis(1'b0),
        .in_valid(in_valid), .in_ready(in_ready), .in_data(in_data), .in_last(in_last),
        .txd_v(txd_v), .tx_en_v(tx_en_v), .tx_se0_v(tx_se0_v), .tx_speed(),
        .busy(tp_busy), .tx_done(tx_done), .tx_underrun(tx_underrun));

    reg [1:0]  p_st;             // 0 gap, 1 bytes, 2 wait for the serializer
    reg [8:0]  p_idx;            // byte index: 0..3 SYNC, 4 PID, 5.. payload
    reg [6:0]  p_prbs;
    reg [9:0]  p_gap;
    wire [14:0] pn = prbs8(p_prbs);
    wire [8:0]  last_idx = 9'd4 + {1'b0, txlen};
    assign busy = (p_st != 2'd0) || tp_busy;

    always @(*) begin
        case (p_idx)
            9'd0, 9'd1, 9'd2: in_data = 8'h00;
            9'd3:             in_data = 8'h80;
            9'd4:             in_data = 8'hC3;
            default:          in_data = pn[7:0];
        endcase
        in_last = (p_idx == last_idx);
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            p_st <= 2'd0; p_idx <= 9'd0; p_prbs <= 7'h5A; p_gap <= 10'd0; in_valid <= 1'b0;
            txpkt <= 24'd0;
        end else begin
            if (clr) txpkt <= 24'd0;
            case (p_st)
                2'd0: begin
                    in_valid <= 1'b0;
                    if (p_gap != 10'd0) p_gap <= p_gap - 10'd1;
                    else if (mode == 2'd1 && !tp_busy) begin
                        p_st <= 2'd1; p_idx <= 9'd0; p_prbs <= 7'h5A; in_valid <= 1'b1;
                        if (!clr) txpkt <= txpkt + 24'd1;
                    end
                end
                2'd1: if (in_ready) begin
                    if (p_idx >= 9'd5) p_prbs <= pn[14:8];
                    if (in_last) begin
                        in_valid <= 1'b0; p_st <= 2'd2;
                    end else
                        p_idx <= p_idx + 9'd1;
                end
                default: if (!tp_busy) begin
                    p_st <= 2'd0; p_gap <= {txgap, 2'b11};
                end
            endcase
        end
    end

    // ---------------- line word ----------------
    reg [6:0]  l_prbs;
    wire [14:0] ln = prbs8(l_prbs);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lw <= 8'hFF; l_prbs <= 7'h7F;
        end else begin
            case (mode)
                2'd1:    lw <= txd_v | ~tx_en_v;          // idle (tx_en = 0) = J
                2'd2:    begin lw <= ln[7:0]; l_prbs <= ln[14:8]; end
                2'd3:    lw <= 8'h55;
                default: lw <= 8'hFF;
            endcase
        end
    end

endmodule
