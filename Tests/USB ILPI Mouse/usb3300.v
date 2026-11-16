// -----------------------------------------------------------------------------
// usb3300 - behavioral stub for the SMSC/Microchip USB3300 ULPI USB PHY
//
// Port directions (from the PHY's point of view):
//   DATA    inout  8-bit ULPI data bus        (held at Z)
//   DIR     output ULPI direction              (driven low = link may drive)
//   NXT     output ULPI next                   (driven low)
//   STP     input  ULPI stop (from link)
//   CLKOUT  output 60 MHz ULPI clock           (held low)
//   RESETB  input  active-low reset
//   XI      input  crystal / clock input
//   DP      inout  USB D+ (analog)             (held at Z)
//   DM      inout  USB D- (analog)             (held at Z)
// -----------------------------------------------------------------------------
`timescale 1ns / 1ps

module usb3300 (
    inout  wire [7:0] DATA,
    output wire       DIR,
    output wire       NXT,
    input  wire       STP,
    output wire       CLKOUT,
    input  wire       RESETB,
    input  wire       XI,
    inout  wire       DP,
    inout  wire       DM
);

    // Bidirectional / analog pins: high-impedance
    assign DATA = 8'bzzzz_zzzz;
    assign DP   = 1'bz;
    assign DM   = 1'bz;

    // Outputs: safe idle values
    assign DIR    = 1'b0;
    assign NXT    = 1'b0;
    assign CLKOUT = 1'b0;

endmodule