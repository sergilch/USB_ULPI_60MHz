//-----------------------------------------------------------------------------
// tx_ctrl.v - UART register interface and HS-amplitude DAC of the transmitter-
//             board FPGA
//
// UART 8N1 (BAUD, default 115200).  Protocol, binary:
//   write:  57h ('W'), addr, data          (no reply)
//   read:   52h ('R'), addr                -> data
// Register map (8-bit; doc/tx_board.md section 8)
//   00h ID        RO  54h ('T')
//   01h CTRL      [0] go  [1] rpt  [3:2] speed (00 HS, 01 FS, 10 LS, 11 FS rate)
//                 [4] sync_dis  [5] drv_dis (idle clamp)  [6] iso_en          reset 00h
//   02h PATTERN   [2:0] (tx_seq: 0 Test_Packet, 1 user, 2 Test_J, 3 Test_K,
//                 4 chirp K, 5 PRBS7)                                         reset 00h
//   03h LEN_L, 04h LEN_H   len (tx_seq)                                       reset 0040h
//   05h GAP_L, 06h GAP_H   gap in clk60 ticks                                  reset 0100h
//   07h BUF_ADDR  user-buffer write address (auto-increment on BUF_DATA)
//   08h BUF_DATA  WO  user-buffer data
//   09h TRIM_LEAD [4:0] TX_LEAD  [7:5] TX_LAG  (as spec register 31h)         reset 0Ah
//   0Ah TRIM_TX   [3:0] TX_AMP (as spec register 30h; 8 = nominal)            reset 08h
//   0Bh DAC_L, 0Ch DAC_H   [11:0] DAC code override, [15] override enable     reset 0000h
//   0Dh TERM      [0] DP_PULLUP_EN  [1] HS_TERM_EN  [2] PD_EN0  [3] PD_EN1
//                 [4] FS_SUSPND  [5] FS_RX_EN (FPGA-side isolation emulation) reset 20h
//   0Eh STATUS    RO [0] seq_busy [1] tx_active [2] mmcm_locked [3] RXRCV [4] RXDP
//                    [5] RXDM [6] VBUS_DET [7] dac_busy
//   0Fh PKT_CNT   RO packets finished (wraps)
// TX_AMP -> DAC (MCP4821, 2.048 V internal reference, gain 1, 0.5 mV / LSB):
//   code = DAC_NOM + (TX_AMP - 8) * DAC_STEP = 1200 + (TX_AMP - 8) * 30
//   i.e. V_CTL = 0.600 V nominal, 2.5 % per step (-20 % .. +17.5 %).
//   Written whenever TRIM_TX or DAC_L/H changes (and once after reset).
//   SPI: mode 0, MSB first, 16 bits {0, x, GA = 1, SHDN = 1, D[11:0]}, SCK = clk60 / 8,
//   LDAC tied low on the board (the DAC updates on the rising CS).
// Clock clk60, reset rst_n asynchronous.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tx_ctrl #(
    parameter CLK_HZ   = 60000000,
    parameter BAUD     = 115200,
    parameter DAC_NOM  = 1200,
    parameter DAC_STEP = 30
) (
    input  wire        clk60,
    input  wire        rst_n,
    input  wire        uart_rxd,
    output wire        uart_txd,

    // registers
    output reg  [7:0]  ctrl,
    output reg  [2:0]  pattern,
    output reg  [15:0] len,
    output reg  [15:0] gap,
    output reg         buf_we,
    output reg  [5:0]  buf_waddr,
    output reg  [7:0]  buf_wdata,
    output reg  [4:0]  tx_lead,
    output reg  [2:0]  tx_lag,
    output reg  [7:0]  term,
    input  wire [7:0]  status_in,      // [6:0]; bit 7 is dac_busy (internal)
    input  wire [7:0]  pkt_cnt,

    // MCP4821
    output reg         dac_cs_n,
    output reg         dac_sck,
    output reg         dac_sdi
);

    localparam DIV = CLK_HZ / BAUD;

    // ---------------- UART RX ----------------
    reg [2:0]  rx_s;
    reg [15:0] rx_cnt;
    reg [3:0]  rx_bit;
    reg [7:0]  rx_sh;
    reg        rx_busy, rx_vld;
    reg [7:0]  rx_byte;
    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            rx_s <= 3'b111; rx_cnt <= 0; rx_bit <= 0; rx_sh <= 0; rx_busy <= 0;
            rx_vld <= 0; rx_byte <= 0;
        end else begin
            rx_s   <= {rx_s[1:0], uart_rxd};
            rx_vld <= 1'b0;
            if (!rx_busy) begin
                if (rx_s[2:1] == 2'b10) begin          // start bit edge
                    rx_busy <= 1'b1; rx_cnt <= DIV / 2; rx_bit <= 0;
                end
            end else if (rx_cnt != 0) begin
                rx_cnt <= rx_cnt - 1;
            end else begin
                rx_cnt <= DIV - 1;
                if (rx_bit == 0) begin
                    if (rx_s[2]) rx_busy <= 1'b0;       // false start
                    rx_bit <= 1;
                end else if (rx_bit <= 8) begin
                    rx_sh  <= {rx_s[2], rx_sh[7:1]};
                    rx_bit <= rx_bit + 1;
                end else begin                          // stop bit
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
    assign uart_txd = tx_sh[0];
    always @(posedge clk60 or negedge rst_n) begin
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

    // ---------------- command decoder / registers ----------------
    reg [1:0]  cst;          // 0 cmd, 1 addr, 2 data
    reg        rd_pend;      // reply one clock after the address (addr is then valid)
    reg        cmd_w;
    reg [7:0]  addr;
    reg [7:0]  tx_amp_r;
    reg [15:0] dac_ovr;
    reg        dac_req;
    wire       dac_busy;

    reg [7:0] rdata;
    always @(*) begin
        case (addr[3:0])
            4'h0: rdata = 8'h54;
            4'h1: rdata = ctrl;
            4'h2: rdata = {5'd0, pattern};
            4'h3: rdata = len[7:0];
            4'h4: rdata = len[15:8];
            4'h5: rdata = gap[7:0];
            4'h6: rdata = gap[15:8];
            4'h7: rdata = {2'd0, buf_waddr};
            4'h9: rdata = {tx_lag, tx_lead};
            4'hA: rdata = tx_amp_r;
            4'hB: rdata = dac_ovr[7:0];
            4'hC: rdata = dac_ovr[15:8];
            4'hD: rdata = term;
            4'hE: rdata = {dac_busy, status_in[6:0]};
            4'hF: rdata = pkt_cnt;
            default: rdata = 8'h00;
        endcase
    end

    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            cst <= 0; cmd_w <= 0; addr <= 0; tx_go <= 0; tx_byte <= 0; rd_pend <= 0;
            ctrl <= 8'h00; pattern <= 3'd0; len <= 16'h0040; gap <= 16'h0100;
            buf_we <= 0; buf_waddr <= 0; buf_wdata <= 0;
            tx_lead <= 5'd10; tx_lag <= 3'd0; tx_amp_r <= 8'h08; dac_ovr <= 16'h0000;
            term <= 8'h20; dac_req <= 1'b1;                       // write the DAC once after reset
        end else begin
            tx_go  <= 1'b0;
            buf_we <= 1'b0;
            rd_pend <= 1'b0;
            if (rd_pend) begin tx_byte <= rdata; tx_go <= 1'b1; end
            if (buf_we) buf_waddr <= buf_waddr + 6'd1;
            if (dac_req && !dac_busy) dac_req <= 1'b0;
            if (rx_vld) begin
                case (cst)
                    2'd0: if (rx_byte == 8'h57 || rx_byte == 8'h52) begin
                              cmd_w <= (rx_byte == 8'h57); cst <= 2'd1;
                          end
                    2'd1: begin
                              addr <= rx_byte;
                              if (cmd_w) cst <= 2'd2;
                              else begin cst <= 2'd0; rd_pend <= 1'b1; end
                          end
                    default: begin
                              cst <= 2'd0;
                              case (addr[3:0])
                                  4'h1: ctrl <= rx_byte;
                                  4'h2: pattern <= rx_byte[2:0];
                                  4'h3: len[7:0] <= rx_byte;
                                  4'h4: len[15:8] <= rx_byte;
                                  4'h5: gap[7:0] <= rx_byte;
                                  4'h6: gap[15:8] <= rx_byte;
                                  4'h7: buf_waddr <= rx_byte[5:0];
                                  4'h8: begin buf_we <= 1'b1; buf_wdata <= rx_byte; end
                                  4'h9: {tx_lag, tx_lead} <= rx_byte;
                                  4'hA: begin tx_amp_r <= {4'd0, rx_byte[3:0]}; dac_req <= 1'b1; end
                                  4'hB: begin dac_ovr[7:0] <= rx_byte; dac_req <= 1'b1; end
                                  4'hC: begin dac_ovr[15:8] <= rx_byte; dac_req <= 1'b1; end
                                  4'hD: term <= rx_byte;
                                  default: ;
                              endcase
                          end
                endcase
            end
        end
    end

    // ---------------- MCP4821 writer ----------------
    wire signed [12:0] amp_off = $signed({1'b0, tx_amp_r[3:0]}) - 13'sd8;
    wire signed [16:0] code_s  = DAC_NOM + amp_off * DAC_STEP;
    wire [11:0] code = dac_ovr[15] ? dac_ovr[11:0] :
                       (code_s < 0) ? 12'd0 : (code_s > 4095) ? 12'd4095 : code_s[11:0];

    reg [4:0]  sbit;
    reg [2:0]  sdiv;
    reg [15:0] sword;
    reg        sact;
    assign dac_busy = sact;
    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            sbit <= 0; sdiv <= 0; sword <= 0; sact <= 0;
            dac_cs_n <= 1'b1; dac_sck <= 1'b0; dac_sdi <= 1'b0;
        end else if (!sact) begin
            dac_sck <= 1'b0;
            if (dac_req) begin
                sword <= {1'b0, 1'b0, 1'b1, 1'b1, code};
                sact <= 1'b1; sbit <= 5'd16; sdiv <= 3'd0; dac_cs_n <= 1'b0;
                dac_sdi <= 1'b0;
            end
        end else begin
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
