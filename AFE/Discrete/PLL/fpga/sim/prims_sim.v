//-----------------------------------------------------------------------------
// prims_sim.v - behavioural stand-ins for the 7-Series primitives of
//               pll_fpga_top (Icarus only, PLL_SIM).  Only the features the
//               design uses are modelled:
//   MMCME2_BASE  CLKOUT0 = CLKIN1_PERIOD * DIVCLK_DIVIDE / CLKFBOUT_MULT_F *
//                CLKOUT0_DIVIDE_F, LOCKED 1 us after RST
//-----------------------------------------------------------------------------
`timescale 1ns/1ps
module IBUF   (input wire I, output wire O);              assign O = I;       endmodule
module IBUFDS (input wire I, input wire IB, output wire O); assign O = I;     endmodule
module BUFG   (input wire I, output wire O);              assign O = I;       endmodule

module MMCME2_BASE #(parameter real CLKIN1_PERIOD = 10.0, parameter real CLKFBOUT_MULT_F = 12.0,
                     parameter integer DIVCLK_DIVIDE = 1, parameter real CLKOUT0_DIVIDE_F = 20.0)
    (input wire CLKIN1, input wire CLKFBIN, output wire CLKFBOUT, output wire CLKFBOUTB,
     output reg CLKOUT0, output wire CLKOUT0B, output wire CLKOUT1, output wire CLKOUT1B,
     output wire CLKOUT2, output wire CLKOUT2B, output wire CLKOUT3, output wire CLKOUT3B,
     output wire CLKOUT4, output wire CLKOUT5, output wire CLKOUT6,
     output reg LOCKED, input wire PWRDWN, input wire RST);
    real h0;
    initial begin
        h0 = CLKIN1_PERIOD * DIVCLK_DIVIDE / CLKFBOUT_MULT_F * CLKOUT0_DIVIDE_F / 2.0;
        CLKOUT0 = 1'b0; LOCKED = 1'b0;
        forever #(h0) CLKOUT0 = ~CLKOUT0;
    end
    always @(posedge RST or negedge RST)
        if (RST) LOCKED = 1'b0;
    initial #1000 LOCKED = 1'b1;
    always @(negedge RST) #1000 LOCKED = 1'b1;
    assign CLKFBOUT = 1'b0; assign CLKFBOUTB = 1'b0; assign CLKOUT0B = ~CLKOUT0;
    assign CLKOUT1 = 1'b0; assign CLKOUT1B = 1'b0; assign CLKOUT2 = 1'b0; assign CLKOUT2B = 1'b0;
    assign CLKOUT3 = 1'b0; assign CLKOUT3B = 1'b0; assign CLKOUT4 = 1'b0; assign CLKOUT5 = 1'b0;
    assign CLKOUT6 = 1'b0;
endmodule
