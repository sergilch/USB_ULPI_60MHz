//-----------------------------------------------------------------------------
// prims_sim.v - behavioural stand-ins for the 7-Series primitives of
//               rx_fpga_top (Icarus only, RX_SIM).  Only the features the
//               design uses are modelled:
//   MMCME2_BASE  CLKOUT0..2 from CLKIN1_PERIOD * DIVCLK_DIVIDE / CLKFBOUT_MULT_F,
//                phase-aligned, LOCKED 1 us after RST; fast_off stops CLKOUT0/1
//                (testbench speed-up during the slow UART read-out)
//   BUFR         BUFR_DIVIDE "4" only, first output edge on the first input edge
//   IDELAYE2     VAR_LOAD: transport delay CNTVALUE * 78.125 ps (200 MHz REFCLK)
//   ISERDESE2    NETWORKING, DDR, 8 bits: samples on both CLK edges, word on
//                CLKDIV rising; first received bit on Q8
//-----------------------------------------------------------------------------
`timescale 1ns/1ps
module IBUF   (input wire I, output wire O);              assign O = I;       endmodule
module IBUFDS (input wire I, input wire IB, output wire O); assign O = I;     endmodule
module IBUFDS_DIFF_OUT #(parameter DIFF_TERM = "FALSE", parameter IBUF_LOW_PWR = "TRUE",
                         parameter IOSTANDARD = "DEFAULT")
    (input wire I, input wire IB, output wire O, output wire OB);
    assign O = I; assign OB = ~I;
endmodule
module BUFG   (input wire I, output wire O);              assign O = I;       endmodule
module BUFIO  (input wire I, output wire O);              assign O = I;       endmodule

module BUFR #(parameter BUFR_DIVIDE = "4", parameter SIM_DEVICE = "7SERIES")
    (input wire I, input wire CE, input wire CLR, output reg O);
    reg [1:0] n = 2'd0;
    initial O = 1'b0;
    always @(posedge I or posedge CLR)
        if (CLR) begin n <= 2'd0; O <= 1'b0; end
        else begin
            n <= n + 2'd1;
            if (n == 2'd0) O <= 1'b1;
            if (n == 2'd2) O <= 1'b0;
        end
endmodule

module IDELAYCTRL (input wire REFCLK, input wire RST, output reg RDY);
    integer n;
    initial begin RDY = 1'b0; n = 0; end
    always @(posedge REFCLK or posedge RST)
        if (RST) begin n <= 0; RDY <= 1'b0; end
        else if (n < 20) n <= n + 1;
        else RDY <= 1'b1;
endmodule

module IDELAYE2 #(parameter IDELAY_TYPE = "FIXED", parameter DELAY_SRC = "IDATAIN",
                  parameter integer IDELAY_VALUE = 0, parameter HIGH_PERFORMANCE_MODE = "FALSE",
                  parameter real REFCLK_FREQUENCY = 200.0, parameter SIGNAL_PATTERN = "DATA",
                  parameter CINVCTRL_SEL = "FALSE", parameter PIPE_SEL = "FALSE")
    (input wire C, input wire CE, input wire INC, input wire LD, input wire LDPIPEEN,
     input wire REGRST, input wire CINVCTRL, input wire [4:0] CNTVALUEIN,
     output wire [4:0] CNTVALUEOUT, input wire IDATAIN, input wire DATAIN, output reg DATAOUT);
    reg [4:0] cnt = IDELAY_VALUE;
    real d;
    assign CNTVALUEOUT = cnt;
    always @(posedge C) if (LD) cnt <= CNTVALUEIN;
    initial DATAOUT = 1'b0;
    always @(IDATAIN) begin
        d = cnt * 1000.0 / (64.0 * REFCLK_FREQUENCY);
        DATAOUT <= #(d) IDATAIN;
    end
endmodule

module ISERDESE2 #(parameter DATA_RATE = "DDR", parameter integer DATA_WIDTH = 8,
                   parameter INTERFACE_TYPE = "NETWORKING", parameter IOBDELAY = "NONE",
                   parameter integer NUM_CE = 1, parameter OFB_USED = "FALSE",
                   parameter SERDES_MODE = "MASTER", parameter DYN_CLKDIV_INV_EN = "FALSE",
                   parameter DYN_CLK_INV_EN = "FALSE")
    (output reg Q1, output reg Q2, output reg Q3, output reg Q4, output reg Q5, output reg Q6,
     output reg Q7, output reg Q8, output wire O, output wire SHIFTOUT1, output wire SHIFTOUT2,
     input wire BITSLIP, input wire CE1, input wire CE2, input wire CLKDIVP, input wire CLK,
     input wire CLKB, input wire CLKDIV, input wire OCLK, input wire OCLKB,
     input wire DYNCLKDIVSEL, input wire DYNCLKSEL, input wire D, input wire DDLY,
     input wire OFB, input wire RST, input wire SHIFTIN1, input wire SHIFTIN2);
    wire din = (IOBDELAY == "IFD" || IOBDELAY == "BOTH") ? DDLY : D;
    reg [7:0] sr = 8'h00;                    // sr[0] newest
    assign O = D; assign SHIFTOUT1 = 1'b0; assign SHIFTOUT2 = 1'b0;
    always @(posedge CLK or negedge CLK) sr <= {sr[6:0], din};
    always @(posedge CLKDIV)
        if (RST) {Q8, Q7, Q6, Q5, Q4, Q3, Q2, Q1} <= 8'h00;
        else     {Q8, Q7, Q6, Q5, Q4, Q3, Q2, Q1} <= sr;   // Q8 = first received
endmodule

module MMCME2_BASE #(parameter real CLKIN1_PERIOD = 10.0, parameter real CLKFBOUT_MULT_F = 12.0,
                     parameter integer DIVCLK_DIVIDE = 1, parameter real CLKOUT0_DIVIDE_F = 2.5,
                     parameter integer CLKOUT1_DIVIDE = 6, parameter integer CLKOUT2_DIVIDE = 20)
    (input wire CLKIN1, input wire CLKFBIN, output wire CLKFBOUT, output wire CLKFBOUTB,
     output reg CLKOUT0, output wire CLKOUT0B, output reg CLKOUT1, output wire CLKOUT1B,
     output reg CLKOUT2, output wire CLKOUT2B, output wire CLKOUT3, output wire CLKOUT3B,
     output wire CLKOUT4, output wire CLKOUT5, output wire CLKOUT6,
     output reg LOCKED, input wire PWRDWN, input wire RST);
    real vco, h0, h1, h2;
    reg fast_off = 1'b0;                     // testbench: stop CLKOUT0/1
    assign CLKFBOUT = 1'b0; assign CLKFBOUTB = 1'b0;
    assign CLKOUT0B = ~CLKOUT0; assign CLKOUT1B = ~CLKOUT1; assign CLKOUT2B = ~CLKOUT2;
    assign CLKOUT3 = 1'b0; assign CLKOUT3B = 1'b1; assign CLKOUT4 = 1'b0;
    assign CLKOUT5 = 1'b0; assign CLKOUT6 = 1'b0;
    initial begin
        vco = CLKIN1_PERIOD * DIVCLK_DIVIDE / CLKFBOUT_MULT_F;
        h0 = vco * CLKOUT0_DIVIDE_F / 2.0; h1 = vco * CLKOUT1_DIVIDE / 2.0;
        h2 = vco * CLKOUT2_DIVIDE / 2.0;
        CLKOUT0 = 0; CLKOUT1 = 0; CLKOUT2 = 0; LOCKED = 0;
        fork
            begin #1000; LOCKED = 1; end
            forever begin #(h0); if (!fast_off) CLKOUT0 = ~CLKOUT0; end
            forever begin #(h1); if (!fast_off) CLKOUT1 = ~CLKOUT1; end
            forever begin #(h2); CLKOUT2 = ~CLKOUT2; end
        join
    end
    always @(posedge RST) LOCKED = 0;
endmodule
