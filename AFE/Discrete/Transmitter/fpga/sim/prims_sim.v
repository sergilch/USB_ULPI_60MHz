//-----------------------------------------------------------------------------
// prims_sim.v - behavioural stand-ins for the 7-Series primitives that remain
//               in tx_fpga_top when TX_PISO_SIM is defined (Icarus only)
//-----------------------------------------------------------------------------
`timescale 1ns/1ps
module IBUF   (input wire I, output wire O);              assign O = I;       endmodule
module IBUFDS (input wire I, input wire IB, output wire O); assign O = I;     endmodule
module BUFG   (input wire I, output wire O);              assign O = I;       endmodule
module OBUFDS (input wire I, output wire O, output wire OB); assign O = I; assign OB = ~I; endmodule
