//-----------------------------------------------------------------------------
// rx_ctrl.v - UART register interface, threshold DAC and capture read-out of
//             the receiver-board FPGA (system clock domain, clk60)
//
// UART 8N1 (BAUD).  Binary protocol (as on the transmitter board, plus 'D'):
//   write:  57h ('W'), addr, data                    (no reply)
//   read:   52h ('R'), addr                          -> data
//   dump:   44h ('D'), off_l, off_h, n_l, n_h        -> n words, 4 bytes each,
//           little endian, words start_addr + off .. start_addr + off + n - 1
//           (start_addr = TRIG_ADDR - PRE, i.e. word 0 of the capture)
// Register map (doc/rx_board.md section 8)
//   00h ID          RO 52h ('R')
//   01h CTRL        [0] RX_EN  [1] HS_TERM_EN (board termination)  [2] LED  reset 01h
//   02h TRIG        [1:0] source (0 immediate, 1 SQUELCH_A fall, 2 DISC_A rise,
//                   3 RX_OUT edge); writing [7] = 1 arms a capture       reset 01h
//   03h PRE_L, 04h PRE_H   pre-trigger words                                reset 0040h
//   05h TAP_M [4:0], 06h TAP_S [4:0]  IDELAYE2 taps (78.1 ps)               reset 00h / 07h
//   07h DAC_SQ_L, 08h DAC_SQ_H     [11:0] V_SQ code   (1 mV / LSB)          reset 1320
//   09h DAC_DC_L, 0Ah DAC_DC_H     [11:0] V_DISC code (1 mV / LSB)          reset 1210
//   0Bh STATUS      RO [0] mmcm_locked [1] idelay_rdy [2] armed [3] done [4] VBUS_DET
//                      [5] SQUELCH_A [6] DISC_A [7] dac_busy
//   0Ch TRIG_ADDR_L, 0Dh TRIG_ADDR_H   RO
//   0Eh SQ_CNT_L, 0Fh SQ_CNT_H        RO SQUELCH_A falls (16 bit, wraps)
//   10h DC_CNT_L, 11h DC_CNT_H        RO DISC_A rises
//   12h AW          RO log2 of the capture depth (words)
// V_SQ = 0.1 x squelch trip, V_DISC = 2 x disconnect trip (board networks):
// codes 1320 / 1210 put the trips at ~125 mV / ~575 mV (simulation, doc 5.3);
// calibrate per board (doc section 10).
// MCP4822: 16-bit SPI words {A/B, 0, GA = 0 (2x, 1 mV / LSB), SHDN = 1, D[11:0]},
// mode 0, SCK = clk / 8, LDAC tied low.  Both channels are written after reset
// and after a write to their high byte.
// Reading 0Ch..11h: write the low byte's address first; the high byte is latched
// with the low byte (multi-byte values are consistent).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module rx_ctrl #(
    parameter CLK_HZ = 60000000,
    parameter BAUD   = 921600,
    parameter AW     = 13
) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          uart_rxd,
    output wire          uart_txd,

    output reg  [7:0]    ctrl,
    output reg  [1:0]    trig_src,
    output reg           arm_tgl,
    output reg  [AW-1:0] pre,
    output reg  [4:0]    tap_m,
    output reg  [4:0]    tap_s,
    input  wire [6:0]    status_in,     // [6:0] of STATUS
    input  wire [AW-1:0] trig_addr,
    input  wire [15:0]   sq_cnt,
    input  wire [15:0]   dc_cnt,

    output reg  [AW-1:0] raddr,
    input  wire [31:0]   rdata,

    input  wire          spi_gnt,       // SPI bus grant (1 = free-standing board; aio_spi_arb on the all-in-one board)
    output reg           dac_cs_n,
    output reg           dac_sck,
    output reg           dac_sdi
);

    localparam DIV = CLK_HZ / BAUD;

    // ---------------- UART RX ----------------
    reg [2:0]  rx_s;
    reg [15:0] rx_cnt;
    reg [3:0]  rx_bit;
    reg [7:0]  rx_sh;
    reg        rx_busy, rx_vld;
    reg [7:0]  rx_byte;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_s <= 3'b111; rx_cnt <= 0; rx_bit <= 0; rx_sh <= 0; rx_busy <= 0;
            rx_vld <= 0; rx_byte <= 0;
        end else begin
            rx_s   <= {rx_s[1:0], uart_rxd};
            rx_vld <= 1'b0;
            if (!rx_busy) begin
                if (rx_s[2:1] == 2'b10) begin
                    rx_busy <= 1'b1; rx_cnt <= DIV / 2; rx_bit <= 0;
                end
            end else if (rx_cnt != 0) begin
                rx_cnt <= rx_cnt - 1;
            end else begin
                rx_cnt <= DIV - 1;
                if (rx_bit == 0) begin
                    if (rx_s[2]) rx_busy <= 1'b0;
                    rx_bit <= 1;
                end else if (rx_bit <= 8) begin
                    rx_sh  <= {rx_s[2], rx_sh[7:1]};
                    rx_bit <= rx_bit + 1;
                end else begin
                    rx_busy <= 1'b0;
                    if (rx_s[2]) begin rx_vld <= 1'b1; rx_byte <= rx_sh; end
                end
            end
        end
    end

    // ---------------- UART TX ----------------
    reg [9:0]  tx_sh;
    reg [3:0]  tx_n;
    reg [15:0] tx_cnt;
    reg        tx_go;
    reg [7:0]  tx_byte;
    wire       tx_idle = (tx_n == 0) && !tx_go;
    assign uart_txd = tx_sh[0];
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx_sh <= 10'h3FF; tx_n <= 0; tx_cnt <= 0;
        end else if (tx_n == 0) begin
            if (tx_go) begin tx_sh <= {1'b1, tx_byte, 1'b0}; tx_n <= 10; tx_cnt <= DIV - 1; end
        end else if (tx_cnt != 0) begin
            tx_cnt <= tx_cnt - 1;
        end else begin
            tx_sh <= {1'b1, tx_sh[9:1]}; tx_n <= tx_n - 1; tx_cnt <= DIV - 1;
        end
    end

    // ---------------- Gray -> binary (counters from the clkdiv domain) ----------------
    function [15:0] g2b(input [15:0] g);
        integer k;
        begin
            g2b[15] = g[15];
            for (k = 14; k >= 0; k = k - 1) g2b[k] = g2b[k + 1] ^ g[k];
        end
    endfunction

    // ---------------- command decoder / registers ----------------
    reg [2:0]  cst;            // 0 cmd, 1 addr, 2 data, 3..6 dump args
    reg [1:0]  cmd;            // 0 W, 1 R, 2 D
    reg        rd_pend;
    reg [7:0]  addr;
    reg [11:0] dac_sq, dac_dc;
    reg [1:0]  dac_req;        // [0] channel A (V_SQ), [1] channel B (V_DISC)
    wire       dac_busy;
    reg [15:0] hold;           // high byte latch for multi-byte RO values
    reg [15:0] d_off, d_n;
    reg        d_start;
    reg        d_busy, d_tx_go;    // dump engine (below)
    reg [7:0]  d_tx_byte;
    reg        dac_ch, dac_go;     // DAC writer (below)

    wire [15:0] ta16 = trig_addr;
    reg [7:0] rdata_r;
    always @(*) begin
        case (addr)
            8'h00: rdata_r = 8'h52;
            8'h01: rdata_r = ctrl;
            8'h02: rdata_r = {6'd0, trig_src};
            8'h03: rdata_r = pre[7:0];
            8'h04: rdata_r = pre >> 8;
            8'h05: rdata_r = {3'd0, tap_m};
            8'h06: rdata_r = {3'd0, tap_s};
            8'h07: rdata_r = dac_sq[7:0];
            8'h08: rdata_r = {4'd0, dac_sq[11:8]};
            8'h09: rdata_r = dac_dc[7:0];
            8'h0A: rdata_r = {4'd0, dac_dc[11:8]};
            8'h0B: rdata_r = {dac_busy, status_in};
            8'h0C: rdata_r = ta16[7:0];
            8'h0E: rdata_r = g2b(sq_cnt) & 8'hFF;
            8'h10: rdata_r = g2b(dc_cnt) & 8'hFF;
            8'h0D, 8'h0F, 8'h11: rdata_r = hold[15:8];
            8'h12: rdata_r = AW;
            default: rdata_r = 8'h00;
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cst <= 0; cmd <= 0; addr <= 0; rd_pend <= 0; tx_go <= 0; tx_byte <= 0;
            ctrl <= 8'h01; trig_src <= 2'd1; arm_tgl <= 1'b0; pre <= 64;
            tap_m <= 5'd0; tap_s <= 5'd7; dac_sq <= 12'd1320; dac_dc <= 12'd1210;
            dac_req <= 2'b11; hold <= 0; d_off <= 0; d_n <= 0; d_start <= 0;
        end else begin
            tx_go   <= 1'b0;
            rd_pend <= 1'b0;
            d_start <= 1'b0;
            if (rd_pend) begin
                tx_byte <= rdata_r; tx_go <= 1'b1;
                case (addr)
                    8'h0C: hold <= ta16;
                    8'h0E: hold <= g2b(sq_cnt);
                    8'h10: hold <= g2b(dc_cnt);
                    default: ;
                endcase
            end
            if (dac_go) dac_req[dac_ch] <= 1'b0;          // request taken by the writer
            if (rx_vld && !d_busy) begin
                case (cst)
                    3'd0: if (rx_byte == 8'h57 || rx_byte == 8'h52 || rx_byte == 8'h44) begin
                              cmd <= (rx_byte == 8'h57) ? 2'd0 : (rx_byte == 8'h52) ? 2'd1 : 2'd2;
                              cst <= (rx_byte == 8'h44) ? 3'd3 : 3'd1;
                          end
                    3'd1: begin
                              addr <= rx_byte;
                              if (cmd == 2'd0) cst <= 3'd2;
                              else begin cst <= 3'd0; rd_pend <= 1'b1; end
                          end
                    3'd2: begin
                              cst <= 3'd0;
                              case (addr)
                                  8'h01: ctrl <= rx_byte;
                                  8'h02: begin trig_src <= rx_byte[1:0];
                                               if (rx_byte[7]) arm_tgl <= ~arm_tgl; end
                                  8'h03: pre[7:0] <= rx_byte;
                                  8'h04: pre[AW-1:8] <= rx_byte[AW-9:0];
                                  8'h05: tap_m <= rx_byte[4:0];
                                  8'h06: tap_s <= rx_byte[4:0];
                                  8'h07: dac_sq[7:0] <= rx_byte;
                                  8'h08: begin dac_sq[11:8] <= rx_byte[3:0]; dac_req[0] <= 1'b1; end
                                  8'h09: dac_dc[7:0] <= rx_byte;
                                  8'h0A: begin dac_dc[11:8] <= rx_byte[3:0]; dac_req[1] <= 1'b1; end
                                  default: ;
                              endcase
                          end
                    3'd3: begin d_off[7:0]  <= rx_byte; cst <= 3'd4; end
                    3'd4: begin d_off[15:8] <= rx_byte; cst <= 3'd5; end
                    3'd5: begin d_n[7:0]    <= rx_byte; cst <= 3'd6; end
                    default: begin d_n[15:8] <= rx_byte; cst <= 3'd0; d_start <= 1'b1; end
                endcase
            end
            if (d_tx_go) begin tx_byte <= d_tx_byte; tx_go <= 1'b1; end
        end
    end

    // ---------------- dump engine: n words from start_addr + off ----------------
    reg [15:0] d_left;
    reg [1:0]  d_b;            // byte index in the word
    reg [1:0]  d_st;           // 0 idle, 1 read wait, 2 send
    reg [31:0] d_word;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            d_busy <= 0; d_left <= 0; d_b <= 0; d_st <= 0; d_word <= 0; d_tx_go <= 0;
            d_tx_byte <= 0; raddr <= 0;
        end else begin
            d_tx_go <= 1'b0;
            case (d_st)
                2'd0: if (d_start) begin
                          raddr  <= trig_addr - pre + d_off[AW-1:0];
                          d_left <= d_n; d_busy <= (d_n != 0); d_st <= (d_n != 0) ? 2'd1 : 2'd0;
                      end
                2'd1: d_st <= 2'd2;                         // rdata valid next cycle
                default: begin
                    if (d_b == 0 && !d_tx_go && tx_idle) d_word <= rdata;
                    if (tx_idle && !d_tx_go) begin
                        d_tx_byte <= (d_b == 0) ? rdata[7:0] : d_word[8 * d_b +: 8];
                        d_tx_go   <= 1'b1;
                        d_b <= d_b + 2'd1;
                        if (d_b == 2'd3) begin
                            d_left <= d_left - 16'd1;
                            raddr  <= raddr + 1'b1;
                            if (d_left == 16'd1) begin d_busy <= 1'b0; d_st <= 2'd0; end
                            else d_st <= 2'd1;
                        end
                    end
                end
            endcase
        end
    end

    // ---------------- MCP4822 writer (one channel per frame) ----------------
    reg [4:0]  sbit;
    reg [2:0]  sdiv;
    reg [15:0] sword;
    reg        sact;
    assign dac_busy = sact;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sbit <= 0; sdiv <= 0; sword <= 0; sact <= 0; dac_ch <= 0; dac_go <= 0;
            dac_cs_n <= 1'b1; dac_sck <= 1'b0; dac_sdi <= 1'b0;
        end else if (!sact) begin
            dac_sck <= 1'b0;
            dac_go  <= 1'b0;
            if (|dac_req && !dac_go && spi_gnt) begin
                dac_ch <= dac_req[0] ? 1'b0 : 1'b1;
                sword  <= dac_req[0] ? {4'b0001, dac_sq} : {4'b1001, dac_dc};
                dac_go <= 1'b1;                          // request taken: cleared above
                sact <= 1'b1; sbit <= 5'd16; sdiv <= 3'd0; dac_cs_n <= 1'b0; dac_sdi <= 1'b0;
            end
        end else begin
            dac_go <= 1'b0;
            sdiv <= sdiv + 3'd1;
            case (sdiv)
                3'd0: if (sbit != 0) begin dac_sdi <= sword[15]; sword <= {sword[14:0], 1'b0}; end
                3'd2: if (sbit != 0) dac_sck <= 1'b1;
                3'd6: if (sbit != 0) begin dac_sck <= 1'b0; sbit <= sbit - 5'd1; end
                3'd7: if (sbit == 0) begin dac_cs_n <= 1'b1; sact <= 1'b0; end
                default: ;
            endcase
        end
    end

endmodule
