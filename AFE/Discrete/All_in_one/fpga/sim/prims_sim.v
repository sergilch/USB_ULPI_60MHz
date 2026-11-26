//-----------------------------------------------------------------------------
// prims_sim.v - behavioural stand-ins for the 7-Series primitives of
//               aio_fpga_top (Icarus only, AIO_SIM).  The union of the block
//               boards' models (Receiver / CDR fpga/sim/prims_sim.v); only the
//               features the design uses are modelled:
//   MMCME2_BASE  CLKOUT0..3 from one edge train of CLKOUT0 (CLKOUT1 / 3 divide
//                it by CLKOUTn_DIVIDE / CLKOUT0_DIVIDE_F, which must be an
//                integer: 480 -> 240 / 60 MHz, rising together), CLKOUT2 on
//                its own; LOCKED 1 us after start / RST
//   BUFR         BUFR_DIVIDE 2 / 4 / 8, output 10 ps after the input edge
//                (after BUFIO), CLR
//   OSERDESE2    DDR 8:1: the word taken on a CLKDIV rising edge goes out D1
//                first, one CLKDIV period later, bit time = CLKDIV period / 8
//   ISERDESE2    SDR (CLK rising) or DDR (both edges) 1:8; Q8 = the oldest bit
//                of the word presented on the CLKDIV rising edge
//   IDELAYE2     VAR_LOAD: transport delay CNTVALUEIN / (64 F_REF), loaded on C with LD
//   IDELAYCTRL   RDY 20 REFCLK cycles after RST
// The timescale's 1 fs precision keeps the 480 MHz period exact enough.
//-----------------------------------------------------------------------------
`timescale 1ns/1fs
module IBUF   (input wire I, output wire O);                assign O = I;   endmodule
module IBUFDS #(parameter DIFF_TERM = "FALSE") (input wire I, input wire IB, output wire O);
    assign O = I;
endmodule
module IBUFDS_DIFF_OUT #(parameter DIFF_TERM = "FALSE", parameter IBUF_LOW_PWR = "TRUE",
                         parameter IOSTANDARD = "DEFAULT")
    (input wire I, input wire IB, output wire O, output wire OB);
    assign O = I; assign OB = ~I;
endmodule
module OBUFDS (input wire I, output wire O, output wire OB); assign O = I; assign OB = ~I; endmodule
module BUFG   (input wire I, output wire O);                assign O = I;   endmodule
module BUFIO  (input wire I, output wire O);                assign O = I;   endmodule

module BUFR #(parameter BUFR_DIVIDE = "8", parameter SIM_DEVICE = "7SERIES")
    (input wire I, input wire CE, input wire CLR, output reg O);
    localparam integer DIV = (BUFR_DIVIDE == "2") ? 2 : (BUFR_DIVIDE == "4") ? 4 : 8;
    integer n = 0;
    initial O = 1'b0;
    always @(posedge I or posedge CLR)
        if (CLR) begin n = 0; O <= #0.01 1'b0; end
        else begin
            if (n == 0)       O <= #0.01 1'b1;
            if (n == DIV / 2) O <= #0.01 1'b0;
            n = (n + 1) % DIV;
        end
endmodule

module MMCME2_BASE #(parameter real CLKIN1_PERIOD = 10.0, parameter real CLKFBOUT_MULT_F = 12.0,
                     parameter integer DIVCLK_DIVIDE = 1, parameter real CLKOUT0_DIVIDE_F = 2.5,
                     parameter integer CLKOUT1_DIVIDE = 5, parameter integer CLKOUT2_DIVIDE = 6,
                     parameter integer CLKOUT3_DIVIDE = 20)
    (input wire CLKIN1, input wire CLKFBIN, output wire CLKFBOUT, output wire CLKFBOUTB,
     output reg CLKOUT0, output wire CLKOUT0B, output reg CLKOUT1, output wire CLKOUT1B,
     output reg CLKOUT2, output wire CLKOUT2B, output reg CLKOUT3, output wire CLKOUT3B,
     output wire CLKOUT4, output wire CLKOUT5, output wire CLKOUT6,
     output reg LOCKED, input wire PWRDWN, input wire RST);
    real    tv, h0, h2;
    integer r1, r3, n;
    initial begin
        tv = CLKIN1_PERIOD * DIVCLK_DIVIDE / CLKFBOUT_MULT_F;
        h0 = tv * CLKOUT0_DIVIDE_F / 2.0;
        h2 = tv * CLKOUT2_DIVIDE / 2.0;
        r1 = CLKOUT1_DIVIDE / CLKOUT0_DIVIDE_F;
        r3 = CLKOUT3_DIVIDE / CLKOUT0_DIVIDE_F;
        if (r1 * CLKOUT0_DIVIDE_F != CLKOUT1_DIVIDE || r3 * CLKOUT0_DIVIDE_F != CLKOUT3_DIVIDE)
            $display("prims_sim MMCME2_BASE: CLKOUT1 / 3 not integer multiples of CLKOUT0");
        CLKOUT0 = 1'b0; CLKOUT1 = 1'b0; CLKOUT2 = 1'b0; CLKOUT3 = 1'b0; LOCKED = 1'b0; n = 0;
        fork
            forever begin                                  // n counts CLKOUT0 half periods
                #(h0);
                CLKOUT0 = ~CLKOUT0;
                if (n % r1 == 0) CLKOUT1 = ~CLKOUT1;
                if (n % r3 == 0) CLKOUT3 = ~CLKOUT3;
                n = n + 1;
            end
            forever #(h2) CLKOUT2 = ~CLKOUT2;
        join
    end
    always @(posedge RST) LOCKED = 1'b0;
    initial #1000 LOCKED = 1'b1;
    always @(negedge RST) #1000 LOCKED = 1'b1;
    assign CLKFBOUT = 1'b0; assign CLKFBOUTB = 1'b0; assign CLKOUT0B = ~CLKOUT0;
    assign CLKOUT1B = ~CLKOUT1; assign CLKOUT2B = ~CLKOUT2; assign CLKOUT3B = ~CLKOUT3;
    assign CLKOUT4 = 1'b0; assign CLKOUT5 = 1'b0; assign CLKOUT6 = 1'b0;
endmodule

module OSERDESE2 #(parameter DATA_RATE_OQ = "DDR", parameter DATA_RATE_TQ = "SDR",
                   parameter integer DATA_WIDTH = 8, parameter integer TRISTATE_WIDTH = 1,
                   parameter SERDES_MODE = "MASTER", parameter [0:0] INIT_OQ = 1'b1,
                   parameter [0:0] SRVAL_OQ = 1'b1)
    (input wire CLK, input wire CLKDIV, input wire RST, input wire OCE, input wire TCE,
     input wire D1, input wire D2, input wire D3, input wire D4, input wire D5, input wire D6,
     input wire D7, input wire D8, input wire T1, input wire T2, input wire T3, input wire T4,
     input wire TBYTEIN, input wire SHIFTIN1, input wire SHIFTIN2,
     output reg OQ, output wire TQ, output wire OFB, output wire TFB, output wire TBYTEOUT,
     output wire SHIFTOUT1, output wire SHIFTOUT2);
    real tl = -1.0, tp = 0.0;
    reg [7:0] wd;
    integer i;
    initial OQ = INIT_OQ;
    always @(posedge CLKDIV) begin
        if (tl >= 0.0) tp = $realtime - tl;
        tl = $realtime;
        wd = RST ? {8{SRVAL_OQ}} : {D8, D7, D6, D5, D4, D3, D2, D1};
        if (tp > 0.0)
            for (i = 0; i < 8; i = i + 1) OQ <= #(tp + i * tp / 8.0) wd[i];
    end
    assign TQ = 1'b0; assign OFB = OQ; assign TFB = 1'b0; assign TBYTEOUT = 1'b0;
    assign SHIFTOUT1 = 1'b0; assign SHIFTOUT2 = 1'b0;
endmodule

module ISERDESE2 #(parameter INTERFACE_TYPE = "NETWORKING", parameter DATA_RATE = "SDR",
                   parameter integer DATA_WIDTH = 8, parameter integer NUM_CE = 1,
                   parameter IOBDELAY = "IFD", parameter SERDES_MODE = "MASTER",
                   parameter OFB_USED = "FALSE", parameter DYN_CLKDIV_INV_EN = "FALSE",
                   parameter DYN_CLK_INV_EN = "FALSE")
    (input wire CLK, input wire CLKB, input wire CLKDIV, input wire CLKDIVP, input wire OCLK,
     input wire OCLKB, input wire RST, input wire CE1, input wire CE2, input wire BITSLIP,
     input wire D, input wire DDLY, input wire OFB, input wire DYNCLKDIVSEL, input wire DYNCLKSEL,
     input wire SHIFTIN1, input wire SHIFTIN2,
     output reg Q1, output reg Q2, output reg Q3, output reg Q4, output reg Q5, output reg Q6,
     output reg Q7, output reg Q8, output wire O, output wire SHIFTOUT1, output wire SHIFTOUT2);
    localparam DDR = (DATA_RATE == "DDR");
    wire din = (IOBDELAY == "IFD" || IOBDELAY == "BOTH") ? DDLY : D;
    reg [7:0] sh = DDR ? 8'h00 : 8'hFF;                   // sh[0] newest
    always @(posedge CLK) sh <= {sh[6:0], din};
    always @(negedge CLK) if (DDR) sh <= {sh[6:0], din};
    always @(posedge CLKDIV)
        if (RST) {Q8, Q7, Q6, Q5, Q4, Q3, Q2, Q1} <= 8'h00;
        else     {Q8, Q7, Q6, Q5, Q4, Q3, Q2, Q1} <= sh;
    assign O = D; assign SHIFTOUT1 = 1'b0; assign SHIFTOUT2 = 1'b0;
endmodule

module IDELAYE2 #(parameter IDELAY_TYPE = "VAR_LOAD", parameter DELAY_SRC = "IDATAIN",
                  parameter HIGH_PERFORMANCE_MODE = "TRUE", parameter real REFCLK_FREQUENCY = 200.0,
                  parameter integer IDELAY_VALUE = 0, parameter SIGNAL_PATTERN = "DATA",
                  parameter PIPE_SEL = "FALSE", parameter CINVCTRL_SEL = "FALSE")
    (input wire C, input wire LD, input wire [4:0] CNTVALUEIN, input wire CE, input wire INC,
     input wire LDPIPEEN, input wire REGRST, input wire CINVCTRL, input wire DATAIN,
     input wire IDATAIN, output reg DATAOUT, output wire [4:0] CNTVALUEOUT);
    reg [4:0] tap = IDELAY_VALUE;
    real d;
    always @(posedge C) if (LD) tap <= CNTVALUEIN;
    initial DATAOUT = 1'b1;
    always @(IDATAIN) begin
        d = tap * 1000.0 / (64.0 * REFCLK_FREQUENCY);
        if (tap == 0) DATAOUT <= IDATAIN;
        else          DATAOUT <= #(d) IDATAIN;
    end
    assign CNTVALUEOUT = tap;
endmodule

module IDELAYCTRL (input wire REFCLK, input wire RST, output reg RDY);
    integer n;
    initial begin RDY = 1'b0; n = 0; end
    always @(posedge REFCLK or posedge RST)
        if (RST) begin n <= 0; RDY <= 1'b0; end
        else if (n < 20) n <= n + 1;
        else RDY <= 1'b1;
endmodule
