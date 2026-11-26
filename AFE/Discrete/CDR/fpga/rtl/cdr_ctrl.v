//-----------------------------------------------------------------------------
// cdr_ctrl.v - UART register interface, tuning DACs and CDR_CH_OUT ADC of the
//              CDR-board FPGA (system clock domain, 60 MHz)
//
// UART 8N1 (BAUD), the protocol of the transmitter / receiver / PLL boards:
//   write:  57h ('W'), addr, data        (no reply)
//   read:   52h ('R'), addr              -> data
// Register map (doc/cdr_board.md section 8)
//   00h ID        RO 43h ('C')
//   01h CTRL      [0] CDR_EN  [1] FF_SET (hold the phase detector set: no
//                 pump, HS_RXD = 1, also while CDR_EN = 0)  [2] DSRC (0 SMA
//                 J2/J3, 1 FPGA pattern)  [4:3] CSRC coarse source (0 open,
//                 1 SMA CDR_V_IN_2, 2 DAC B, 3 open)  [5] VCO_OFF  [6] LED
//                 [7] CLR (write 1: clear the RX / TX counters)   reset 04h
//   02h TXMODE    [1:0] 0 idle (J), 1 HS packets (usb_tx_path), 2 PRBS7,
//                 3 clock pattern (1010...)   reset 00h
//   03h TXLEN     packet payload bytes after the PID (1..255)  reset 32
//   04h TXGAP     idle between packets: 4 x (TXGAP + 1) ticks of 16.7 ns   reset 63
//   05h IDLY      [4:0] IDELAYE2 tap of HS_RXD (78 ps / tap)   reset IDLY_RST
//                 (22: near the eye centre for the XDC input delay, so the
//                 static timing of the tops checks the tap actually loaded)
//   06h/07h DACA  [11:0] V_A fine bias / frequency trim, 1 mV / LSB (MCP4822
//                 A, gain 2), written with the high byte   reset 2600
//   08h/09h DACB  [11:0] internal coarse voltage (MCP4822 B)   reset 3120
//   0Ah STATUS    RO [0] mmcm_locked [1] rx_alive (CLK_RX word clock runs)
//                    [2] idelay_rdy [3] prbs_sync [4] tx_busy [5] snap valid
//   0Bh/0Ch ADC   RO [11:0] CDR_CH_OUT (MCP3201, V = code x 5.02 / 4096)
//   0Dh-0Fh FCNT  RO [23:0] CLK_RX / 8 cycles in 2^FW system clock cycles
//                 (FW = 20: 1048576 at exactly 480 MHz; ppm = 1e6 x (FCNT / 2^20 - 1))
//   10h-12h TXPKT RO packets sent
//   13h-15h RXPKT RO SYNC detected (START events)
//   16h-18h RXOK  RO packets with PID + TXLEN payload bytes all correct, END without error
//   19h-1Bh LOSTS RO sum of the SYNC bits lost (31 - SYNC zeros received) over RXPKT
//   1Ch LOSTMAX   RO largest SYNC bits lost        1Dh LOSTMIN  RO smallest
//   1Eh-21h PBITS RO PRBS7 checker: received words (8 bits each)
//   22h-25h PERR  RO PRBS7 checker: bit errors (a single line error counts 3)
// Multi-byte RO values: read the low byte first; the higher bytes are latched
// with it.  The RX values are snapshots of the CLK_RX domain, refreshed about
// every 2 us (STATUS[5] = 0 while CLK_RX is stopped: the last values stay).
//
// DACs (MCP4822) and ADC (MCP3201) share SCK / SDI with separate CS#.  DAC word
// {A/B, 0, GA# = 0 (2x), SHDN# = 1, D[11:0]}, mode 0, SCK = clk / 8.  ADC: one
// conversion every ~20 us, SCK = clk / 40 (1.5 MHz, MCP3201 max 1.6 MHz at
// 5 V): 2 sample clocks, null bit, B11..B0 (DOUT changes on the falling edge,
// read on the rising edges 4..15).  A pending DAC write wins over the next
// conversion; DAC A before DAC B.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module cdr_ctrl #(
    parameter CLK_HZ = 60000000,
    parameter BAUD   = 921600,
    parameter [4:0] IDLY_RST = 5'd22
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         uart_rxd,
    output wire         uart_txd,

    output reg  [7:0]   ctrl,          // [7] is a pulse (clr)
    output reg  [1:0]   txmode,
    output reg  [7:0]   txlen,
    output reg  [7:0]   txgap,
    output reg  [4:0]   idly,
    output reg          idly_ld,       // one-cycle pulse after an IDLY write

    input  wire [7:0]   status,
    input  wire [23:0]  fcnt,
    input  wire [23:0]  txpkt,
    input  wire [23:0]  rxpkt,
    input  wire [23:0]  rxok,
    input  wire [23:0]  losts,
    input  wire [7:0]   lostmax,
    input  wire [7:0]   lostmin,
    input  wire [31:0]  pbits,
    input  wire [31:0]  perr,

    input  wire         spi_gnt,       // SPI bus grant (1 = free-standing board; aio_spi_arb on the all-in-one board)
    output reg          spi_sck,
    output reg          spi_sdi,
    output reg          dac_cs_n,
    output reg          adc_cs_n,
    input  wire         adc_sdo
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

    // ---------------- registers ----------------
    reg [1:0]  cst;               // 0 cmd, 1 addr, 2 data
    reg        cmd_w, rd_pend;
    reg [7:0]  addr;
    reg [11:0] daca, dacb;
    reg        daca_req, dacb_req;
    reg [11:0] adc_code;
    reg [31:0] hold;
    wire       daca_taken, dacb_taken;

    reg [7:0] rdata_r;
    always @(*) begin
        case (addr)
            8'h00: rdata_r = 8'h43;
            8'h01: rdata_r = {1'b0, ctrl[6:0]};
            8'h02: rdata_r = {6'd0, txmode};
            8'h03: rdata_r = txlen;
            8'h04: rdata_r = txgap;
            8'h05: rdata_r = {3'd0, idly};
            8'h06: rdata_r = daca[7:0];
            8'h07: rdata_r = {4'd0, daca[11:8]};
            8'h08: rdata_r = dacb[7:0];
            8'h09: rdata_r = {4'd0, dacb[11:8]};
            8'h0A: rdata_r = status;
            8'h0B: rdata_r = adc_code[7:0];
            8'h0D: rdata_r = fcnt[7:0];
            8'h10: rdata_r = txpkt[7:0];
            8'h13: rdata_r = rxpkt[7:0];
            8'h16: rdata_r = rxok[7:0];
            8'h19: rdata_r = losts[7:0];
            8'h1C: rdata_r = lostmax;
            8'h1D: rdata_r = lostmin;
            8'h1E: rdata_r = pbits[7:0];
            8'h22: rdata_r = perr[7:0];
            8'h0C, 8'h0E, 8'h11, 8'h14, 8'h17, 8'h1A, 8'h1F, 8'h23: rdata_r = hold[15:8];
            8'h0F, 8'h12, 8'h15, 8'h18, 8'h1B, 8'h20, 8'h24:        rdata_r = hold[23:16];
            8'h21, 8'h25:                                           rdata_r = hold[31:24];
            default: rdata_r = 8'h00;
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cst <= 0; cmd_w <= 0; addr <= 0; rd_pend <= 0; tx_go <= 0; tx_byte <= 0;
            ctrl <= 8'h04; txmode <= 2'd0; txlen <= 8'd32; txgap <= 8'd63; idly <= IDLY_RST;
            idly_ld <= 1'b1; daca <= 12'd2600; dacb <= 12'd3120;
            daca_req <= 1'b1; dacb_req <= 1'b1; hold <= 0;
        end else begin
            tx_go    <= 1'b0;
            rd_pend  <= 1'b0;
            idly_ld  <= 1'b0;
            ctrl[7]  <= 1'b0;
            if (rd_pend) begin
                tx_byte <= rdata_r; tx_go <= 1'b1;
                case (addr)
                    8'h0B: hold <= {20'd0, adc_code};
                    8'h0D: hold <= {8'd0, fcnt};
                    8'h10: hold <= {8'd0, txpkt};
                    8'h13: hold <= {8'd0, rxpkt};
                    8'h16: hold <= {8'd0, rxok};
                    8'h19: hold <= {8'd0, losts};
                    8'h1E: hold <= pbits;
                    8'h22: hold <= perr;
                    default: ;
                endcase
            end
            if (daca_taken) daca_req <= 1'b0;
            if (dacb_taken) dacb_req <= 1'b0;
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
                              case (addr)
                                  8'h01: ctrl <= rx_byte;
                                  8'h02: txmode <= rx_byte[1:0];
                                  8'h03: txlen <= (rx_byte == 8'd0) ? 8'd1 : rx_byte;
                                  8'h04: txgap <= rx_byte;
                                  8'h05: begin idly <= rx_byte[4:0]; idly_ld <= 1'b1; end
                                  8'h06: daca[7:0] <= rx_byte;
                                  8'h07: begin daca[11:8] <= rx_byte[3:0]; daca_req <= 1'b1; end
                                  8'h08: dacb[7:0] <= rx_byte;
                                  8'h09: begin dacb[11:8] <= rx_byte[3:0]; dacb_req <= 1'b1; end
                                  default: ;
                              endcase
                          end
                endcase
            end
        end
    end

    // ---------------- SPI: MCP4822 writes, MCP3201 conversions ----------------
    reg [1:0]  s_st;               // 0 idle, 1 DAC frame, 2 ADC frame
    reg [5:0]  s_div;
    reg [4:0]  s_n;
    reg [15:0] s_sh;
    reg [11:0] s_adc;
    reg [10:0] s_gap;              // idle time between conversions
    reg        s_ta, s_tb;
    assign daca_taken = s_ta;
    assign dacb_taken = s_tb;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s_st <= 0; s_div <= 0; s_n <= 0; s_sh <= 0; s_adc <= 0; s_gap <= 0; s_ta <= 0; s_tb <= 0;
            spi_sck <= 1'b0; spi_sdi <= 1'b0; dac_cs_n <= 1'b1; adc_cs_n <= 1'b1;
            adc_code <= 12'd0;
        end else begin
            s_ta <= 1'b0;
            s_tb <= 1'b0;
            case (s_st)
                2'd0: begin
                    spi_sck <= 1'b0;
                    if (s_gap != 0) s_gap <= s_gap - 11'd1;
                    if (!spi_gnt) begin                 // bus held by another block: wait
                    end else if (daca_req && !s_ta) begin
                        s_st <= 2'd1; s_sh <= {4'b0001, daca}; s_n <= 5'd16; s_div <= 0;
                        dac_cs_n <= 1'b0; s_ta <= 1'b1;
                    end else if (dacb_req && !s_tb) begin
                        s_st <= 2'd1; s_sh <= {4'b1001, dacb}; s_n <= 5'd16; s_div <= 0;
                        dac_cs_n <= 1'b0; s_tb <= 1'b1;
                    end else if (s_gap == 0) begin
                        s_st <= 2'd2; s_n <= 5'd15; s_div <= 0; adc_cs_n <= 1'b0;
                    end
                end
                2'd1: begin                                    // 16 bits, clk / 8
                    s_div <= (s_div == 6'd7) ? 6'd0 : s_div + 6'd1;
                    case (s_div)
                        6'd0: if (s_n != 0) begin spi_sdi <= s_sh[15]; s_sh <= {s_sh[14:0], 1'b0}; end
                        6'd2: if (s_n != 0) spi_sck <= 1'b1;
                        6'd6: if (s_n != 0) begin spi_sck <= 1'b0; s_n <= s_n - 5'd1; end
                        6'd7: if (s_n == 0) begin dac_cs_n <= 1'b1; s_st <= 2'd0; end
                        default: ;
                    endcase
                end
                default: begin                                 // 15 clocks, clk / 40
                    s_div <= (s_div == 6'd39) ? 6'd0 : s_div + 6'd1;
                    case (s_div)
                        6'd0:  if (s_n == 0) begin
                                   adc_cs_n <= 1'b1; s_st <= 2'd0; adc_code <= s_adc;
                                   s_gap <= 11'd1100;
                               end
                        6'd20: if (s_n != 0) begin
                                   spi_sck <= 1'b1;
                                   if (s_n <= 5'd12) s_adc <= {s_adc[10:0], adc_sdo};
                               end
                        6'd39: if (s_n != 0) begin spi_sck <= 1'b0; s_n <= s_n - 5'd1; end
                        default: ;
                    endcase
                end
            endcase
        end
    end

endmodule
