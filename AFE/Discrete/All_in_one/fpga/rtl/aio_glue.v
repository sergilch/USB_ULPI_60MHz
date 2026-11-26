//-----------------------------------------------------------------------------
// aio_glue.v - shared-resource glue of the all-in-one FPGA design
//
// aio_uart_sel  one UART (PmodUSBUART on the ZedBoard JA header) for the four
//               block controllers.  SW1:SW0 select the block: 00 TX ('T'),
//               01 RX ('R'), 10 PLL ('P'), 11 CDR ('C'); register 00h of
//               every block returns its letter, so a host can check where it
//               is talking.  The selection follows the switches only after
//               they have been stable AND both UART lines have been idle for
//               2^SETTLE_W clk cycles (2^16 at 60 MHz = 1.1 ms, about 100 byte
//               times at 921600 baud): flipping a switch during a transfer or
//               an RX dump never cuts a byte.  The unselected controllers see
//               an idle line (1).
//
// aio_spi_arb   the merged board has one SPI_SCK / SPI_SDI pair for the TX DAC,
//               the RX DAC, the PLL DAC / ADC and the CDR DAC / ADC (separate
//               CS#, separate ADC DOUT).  Each block's SPI engine starts a
//               frame only while its spi_gnt is high (tx_ctrl, rx_ctrl,
//               pll_ctrl, cdr_ctrl input spi_gnt; tied to 1 on the single
//               boards).  A token goes round the four engines: the owner gets
//               gnt for one cycle (ph = 0); if it starts, its act (internal
//               or pin-level CS# low) holds the token until the frame ends,
//               otherwise the token moves on after a second cycle.  An engine
//               starting at the edge after its gnt cycle shows act one cycle
//               later, before the token can move, so two frames never
//               overlap.  The token comes round within 8 cycles of a free
//               bus; the longest frame (ADC, 15 x 40 cycles) delays another
//               engine by 10 us, far below the DAC / ADC update rates.
//               SCK = OR of the engines' SCK (all idle low); SDI = the SDI of
//               the engine whose CS# is low at its pins.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module aio_uart_sel #(
    parameter integer SETTLE_W = 16
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [1:0] sw,
    input  wire       uart_rxd,       // from the host
    output reg        uart_txd,       // to the host
    output reg  [1:0] sel,
    output wire [3:0] rxd_k,          // to the block controllers
    input  wire [3:0] txd_k           // from the block controllers
);
    reg [1:0]          sw_s1, sw_s2, sw_q;
    reg [1:0]          rx_s;
    reg [SETTLE_W-1:0] cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sw_s1 <= 2'd0; sw_s2 <= 2'd0; sw_q <= 2'd0; rx_s <= 2'b11; cnt <= 0; sel <= 2'd0;
            uart_txd <= 1'b1;
        end else begin
            sw_s1 <= sw; sw_s2 <= sw_s1;
            rx_s  <= {rx_s[0], uart_rxd};
            uart_txd <= txd_k[sel];
            if (sw_s2 != sw_q || !rx_s[1] || !txd_k[sel]) begin
                sw_q <= sw_s2; cnt <= 0;              // switch moved or a byte on a line
            end else if (&cnt) begin
                sel <= sw_q;
            end else begin
                cnt <= cnt + 1'b1;
            end
        end
    end
    assign rxd_k = {sel == 2'd3 ? uart_rxd : 1'b1, sel == 2'd2 ? uart_rxd : 1'b1,
                    sel == 2'd1 ? uart_rxd : 1'b1, sel == 2'd0 ? uart_rxd : 1'b1};
endmodule

module aio_spi_arb (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [3:0] act,            // engine k busy (internal or pin-level CS# low)
    input  wire [3:0] cs_pin,         // engine k has a CS# low at its pins
    input  wire [3:0] sck,
    input  wire [3:0] sdi,
    output wire [3:0] gnt,
    output wire       spi_sck,
    output wire       spi_sdi
);
    reg [1:0] own;
    reg       ph;
    wire      busy = act[own];
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            own <= 2'd0; ph <= 1'b0;
        end else if (busy) begin
            ph <= 1'b0;                               // frame running: keep the token
        end else if (!ph) begin
            ph <= 1'b1;                               // grant cycle over: wait for act
        end else begin
            own <= own + 2'd1; ph <= 1'b0;
        end
    end
    assign gnt     = (!ph && !busy) ? (4'b0001 << own) : 4'b0000;
    assign spi_sck = |sck;
    assign spi_sdi = |(sdi & cs_pin);
endmodule
