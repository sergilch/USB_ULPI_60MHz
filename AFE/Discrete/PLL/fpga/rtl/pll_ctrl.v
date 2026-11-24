//-----------------------------------------------------------------------------
// pll_ctrl.v - UART register interface, ADF4002 programmer, tuning DAC and
//              VTUNE ADC of the PLL-board FPGA (system clock domain, 60 MHz)
//
// UART 8N1 (BAUD), the protocol of the transmitter / receiver boards:
//   write:  57h ('W'), addr, data        (no reply)
//   read:   52h ('R'), addr              -> data
// Register map (doc/pll_board.md section 8)
//   00h ID        RO 50h ('P')
//   01h CTRL      [0] PLL_EN  [1] OPEN_LOOP  [3:2] REFSRC (0 = 24 MHz osc,
//                 1 = 19.2 MHz osc, 2/3 = SMA J2)  [4] LED  [5] LOL_CLR (write 1)
//                 reset 01h
//   02h REFSEL    [1:0] REFSEL1/0 (afe_pll.va code, also to usb_pll_lock_det)
//                 [7] REAL26: REFSEL 10 with R = 13 / N = 120 (480 MHz from
//                 26 MHz) instead of the model's /20.  A write loads R_DIV /
//                 N_DIV / CPI from the table below and programs the ADF4002.
//                 reset 01h
//   03h MUXSEL    [2:0] ADF4002 MUXOUT (M3..M1): 1 digital lock detect (reset),
//                 2 N divider output, 4 R divider output
//   04h/05h R_DIV [13:0]   06h/07h N_DIV [12:0]   08h CPI [2:0] (ICP = 0.625 mA
//                 x (CPI + 1), RSET 5.1 kOhm)
//   09h PROG      write: program the ADF4002 (init, R and N latches) with
//                 R_DIV / N_DIV / CPI / MUXSEL / OPEN_LOOP
//   0Ah/0Bh DAC   [11:0] open-loop tuning voltage, 1 mV / LSB (MCP4821, 2x),
//                 written to the DAC with the high byte
//   0Ch STATUS    RO [0] mmcm_locked [1] pll_lock [2] lol [3] refsel_err
//                    [4] MUXOUT [5] adf_busy [6] phase valid [7] clk_bit alive
//   0Dh/0Eh ADC   RO [11:0] VTUNE (MCP3201, +5V_A = 5.02 V reference: V = code x 5.02 / 4096)
//   0Fh/10h/11h FCNT RO [23:0] CLK60_A cycles in 2^14 REF_DIG cycles
//                 (24 MHz: 40960 at 480 MHz; f_bit = 8 x FCNT x f_ref / 16384)
//   12h/13h T_LOCK RO: us from PLL_EN rising to pll_lock rising (65535: none)
//   14h/15h T_DLD  RO: us from PLL_EN rising to MUXOUT rising
//   16h PHASE     RO [2:0] CLK60_A rising edge position against usb_clk_gen
//                 (clk_bit cycles after E0), [7] valid
//   17h PH_ERR    RO 8-sample words that were not a rotation of 11110000 (sat.)
//   18h FB_DIV    RO usb_pll_lock_det fb_div
// Multi-byte RO values: read the low byte first; the higher bytes are latched
// with it.
//
// REFSEL table (afe_pll.va prog_div = 1; the ADF4002 counts the CDCM1804 Y1
// output, VCO / 2, so N_eff = f_vco / f_pfd = 2 x N_DIV x R_DIV / R_DIV):
//   REFSEL  f_ref     R   N    PFD       N_eff  CPI (ICP)     loop gain
//     00    19.2 MHz  2   25   9.6 MHz    50    4 (3.125 mA)  = 24 MHz case
//     01    24 MHz    1   10   24 MHz     20    1 (1.25 mA)
//     10    26 MHz    1   10   26 MHz     20    1             520 MHz: no lock
//     10 + REAL26     13  120  2 MHz     240    7 (5.0 mA)    narrow loop
//     11    reserved  1   10   24 MHz     20    1             (div_11 = 20)
//
// ADF4002 words (24 bit, MSB first, LE pulse after each): init latch (C = 11)
// with the function bits, then R latch (C = 00: ABP = 00 2.9 ns, LDP = 1) and
// N latch (C = 01, G1 = 0).  Function: PD1 = PD2 = 0, F1 = 0, F2 = 1 (positive
// polarity: VTUNE up = frequency up), F3 = OPEN_LOOP (CP three-state), F4 = 0,
// CPI6..4 = CPI3..1 = CPI.  SPI clock = clk / 8 (7.5 MHz; t3 / t4 >= 25 ns).
// Programmed after reset and on writes to REFSEL, PROG and CTRL.OPEN_LOOP.
// CE follows PLL_EN (the latches keep their contents in power-down), so the
// lock time is not delayed by programming.
//
// DAC (MCP4821) and ADC (MCP3201) share SCK / SDI with separate CS#.  DAC word
// {0, 0, GA = 0 (2x), SHDN# = 1, D[11:0]}, mode 0, SCK = clk / 8.  ADC: one
// conversion every ~20 us, SCK = clk / 40 (1.5 MHz, MCP3201 max 1.6 MHz at
// 5 V): 2 sample clocks, null bit, B11..B0 (DOUT changes on the falling edge,
// read on the rising edges 4..15).  A pending DAC write wins over the next
// conversion.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module pll_ctrl #(
    parameter CLK_HZ = 60000000,
    parameter BAUD   = 921600
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        uart_rxd,
    output wire        uart_txd,

    output reg  [7:0]  ctrl,
    output reg  [1:0]  refsel,
    output wire        lol_clr_tgl,
    input  wire [4:0]  status_in,      // [7:6] / [4:0] of STATUS: {alive, ph_valid} below
    input  wire        ph_valid,
    input  wire        clk_alive,
    input  wire [23:0] fcnt,
    input  wire [15:0] t_lock,
    input  wire [15:0] t_dld,
    input  wire [2:0]  phase,
    input  wire [7:0]  ph_err,
    input  wire [4:0]  fb_div,

    output reg         adf_clk,
    output reg         adf_data,
    output reg         adf_le,

    output reg         spi_sck,
    output reg         spi_sdi,
    output reg         dac_cs_n,
    output reg         adc_cs_n,
    input  wire        adc_sdo
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
    reg        real26;
    reg [2:0]  muxsel, cpi;
    reg [13:0] r_div;
    reg [12:0] n_div;
    reg [11:0] dac;
    reg        dac_req, prog_req, lol_t;
    reg [11:0] adc_code;
    reg [23:0] hold;
    wire       adf_busy, dac_taken;
    assign lol_clr_tgl = lol_t;

    wire [7:0] status = {clk_alive, ph_valid, adf_busy, status_in};

    reg [7:0] rdata_r;
    always @(*) begin
        case (addr)
            8'h00: rdata_r = 8'h50;
            8'h01: rdata_r = ctrl;
            8'h02: rdata_r = {real26, 5'd0, refsel};
            8'h03: rdata_r = {5'd0, muxsel};
            8'h04: rdata_r = r_div[7:0];
            8'h05: rdata_r = {2'd0, r_div[13:8]};
            8'h06: rdata_r = n_div[7:0];
            8'h07: rdata_r = {3'd0, n_div[12:8]};
            8'h08: rdata_r = {5'd0, cpi};
            8'h0A: rdata_r = dac[7:0];
            8'h0B: rdata_r = {4'd0, dac[11:8]};
            8'h0C: rdata_r = status;
            8'h0D: rdata_r = adc_code[7:0];
            8'h0F: rdata_r = fcnt[7:0];
            8'h12: rdata_r = t_lock[7:0];
            8'h14: rdata_r = t_dld[7:0];
            8'h0E, 8'h10, 8'h13, 8'h15: rdata_r = hold[15:8];
            8'h11: rdata_r = hold[23:16];
            8'h16: rdata_r = {ph_valid, 4'd0, phase};
            8'h17: rdata_r = ph_err;
            8'h18: rdata_r = {3'd0, fb_div};
            default: rdata_r = 8'h00;
        endcase
    end

    // REFSEL table
    task load_table(input [1:0] rs, input r26);
        begin
            case (rs)
                2'b00:   begin r_div <= 14'd2;  n_div <= 13'd25;  cpi <= 3'd4; end
                2'b10:   if (r26) begin r_div <= 14'd13; n_div <= 13'd120; cpi <= 3'd7; end
                         else     begin r_div <= 14'd1;  n_div <= 13'd10;  cpi <= 3'd1; end
                default: begin r_div <= 14'd1;  n_div <= 13'd10;  cpi <= 3'd1; end
            endcase
        end
    endtask

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cst <= 0; cmd_w <= 0; addr <= 0; rd_pend <= 0; tx_go <= 0; tx_byte <= 0;
            ctrl <= 8'h01; refsel <= 2'b01; real26 <= 1'b0; muxsel <= 3'd1;
            r_div <= 14'd1; n_div <= 13'd10; cpi <= 3'd1; dac <= 12'd3150;
            dac_req <= 1'b1; prog_req <= 1'b1; lol_t <= 1'b0; hold <= 0;
        end else begin
            tx_go   <= 1'b0;
            rd_pend <= 1'b0;
            if (rd_pend) begin
                tx_byte <= rdata_r; tx_go <= 1'b1;
                case (addr)
                    8'h0D: hold <= {12'd0, adc_code};
                    8'h0F: hold <= fcnt;
                    8'h12: hold <= {8'd0, t_lock};
                    8'h14: hold <= {8'd0, t_dld};
                    default: ;
                endcase
            end
            if (dac_taken)        dac_req  <= 1'b0;
            if (adf_busy)         prog_req <= 1'b0;
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
                                  8'h01: begin
                                             ctrl <= {2'b00, rx_byte[5], rx_byte[4:0]} & 8'h1F;
                                             if (rx_byte[5]) lol_t <= ~lol_t;
                                             if (rx_byte[1] != ctrl[1]) prog_req <= 1'b1;
                                         end
                                  8'h02: begin
                                             refsel <= rx_byte[1:0]; real26 <= rx_byte[7];
                                             load_table(rx_byte[1:0], rx_byte[7]);
                                             prog_req <= 1'b1;
                                         end
                                  8'h03: muxsel <= rx_byte[2:0];
                                  8'h04: r_div[7:0]  <= rx_byte;
                                  8'h05: r_div[13:8] <= rx_byte[5:0];
                                  8'h06: n_div[7:0]  <= rx_byte;
                                  8'h07: n_div[12:8] <= rx_byte[4:0];
                                  8'h08: cpi <= rx_byte[2:0];
                                  8'h09: prog_req <= 1'b1;
                                  8'h0A: dac[7:0] <= rx_byte;
                                  8'h0B: begin dac[11:8] <= rx_byte[3:0]; dac_req <= 1'b1; end
                                  default: ;
                              endcase
                          end
                endcase
            end
        end
    end

    // ---------------- ADF4002 programmer: init, R, N latches ----------------
    wire [23:0] w_func = {2'b00, 1'b0, cpi, cpi, 4'b0000, 1'b0, 1'b0, ctrl[1], 1'b1,
                          muxsel, 1'b0, 1'b0, 2'b11};                    // init latch (C = 11)
    wire [23:0] w_r    = {1'b0, 2'b00, 1'b1, 2'b00, 2'b00, r_div, 2'b00};
    wire [23:0] w_n    = {2'b00, 1'b0, n_div, 6'd0, 2'b01};
    reg  [1:0]  a_w;               // word index 0..2
    reg  [4:0]  a_bit;
    reg  [2:0]  a_div;
    reg  [23:0] a_sh;
    reg         a_act, a_le_ph;
    assign adf_busy = a_act;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_w <= 0; a_bit <= 0; a_div <= 0; a_sh <= 0; a_act <= 0; a_le_ph <= 0;
            adf_clk <= 1'b0; adf_data <= 1'b0; adf_le <= 1'b0;
        end else if (!a_act) begin
            adf_clk <= 1'b0; adf_le <= 1'b0;
            if (prog_req) begin
                a_act <= 1'b1; a_w <= 0; a_sh <= w_func; a_bit <= 5'd24; a_div <= 0; a_le_ph <= 0;
            end
        end else begin
            a_div <= a_div + 3'd1;
            if (!a_le_ph) begin
                case (a_div)
                    3'd0: begin adf_data <= a_sh[23]; a_sh <= {a_sh[22:0], 1'b0}; end
                    3'd3: adf_clk <= 1'b1;
                    3'd7: begin
                              adf_clk <= 1'b0;
                              a_bit <= a_bit - 5'd1;
                              if (a_bit == 5'd1) a_le_ph <= 1'b1;
                          end
                    default: ;
                endcase
            end else begin
                case (a_div)
                    3'd1: adf_le <= 1'b1;
                    3'd5: adf_le <= 1'b0;
                    3'd7: begin
                              a_le_ph <= 1'b0; a_bit <= 5'd24;
                              if (a_w == 2'd2) a_act <= 1'b0;
                              else begin
                                  a_w  <= a_w + 2'd1;
                                  a_sh <= (a_w == 2'd0) ? w_r : w_n;
                              end
                          end
                    default: ;
                endcase
            end
        end
    end

    // ---------------- SPI: MCP4821 writes, MCP3201 conversions ----------------
    reg [1:0]  s_st;               // 0 idle, 1 DAC frame, 2 ADC frame
    reg [5:0]  s_div;
    reg [4:0]  s_n;
    reg [15:0] s_sh;
    reg [11:0] s_adc;
    reg [10:0] s_gap;              // idle time between conversions
    reg        s_take;
    assign dac_taken = s_take;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s_st <= 0; s_div <= 0; s_n <= 0; s_sh <= 0; s_adc <= 0; s_gap <= 0; s_take <= 0;
            spi_sck <= 1'b0; spi_sdi <= 1'b0; dac_cs_n <= 1'b1; adc_cs_n <= 1'b1;
            adc_code <= 12'd0;
        end else begin
            s_take <= 1'b0;
            case (s_st)
                2'd0: begin
                    spi_sck <= 1'b0;
                    if (s_gap != 0) s_gap <= s_gap - 11'd1;
                    if (dac_req && !s_take) begin
                        s_st <= 2'd1; s_sh <= {4'b0001, dac}; s_n <= 5'd16; s_div <= 0;
                        dac_cs_n <= 1'b0; s_take <= 1'b1;
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
