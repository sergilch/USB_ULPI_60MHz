//-----------------------------------------------------------------------------
// usb_rx_fsls_sampler.v - FS/LS receiver sampler, 480 MHz island (Plan_60MHz.md 3.2, P4)
//
//   AFE: rxrcv, rxdp, rxdm (asynchronous) --> [THIS BLOCK, clk_bit]
//        --> rcv_v / dp_v / dm_v [7:0] per clk60 tick --> usb_rx_fsls_dpll (DPLL)
//                                                    --> usb_line_state (newest sample)
//
// The only part of the FS/LS receive path that runs at 480 MHz: each receiver
// output goes through a 2-FF synchronizer and a 1:8 shift register; a word
// register takes the 8 samples on the island strobe ld (edge E4, usb_clk_gen
// boundary rule), so the clk60 side reads a stable word.  Every sample is in
// exactly one word; bit 0 is the oldest sample of a word, bit 7 the newest.
// 40 samples per FS bit, 320 per LS bit, as in the single-clock design.
//
// Latency: a level at the pin is in the synchronizer output after 2 clk_bit
// edges, in a word after up to 8 more, and seen by clk60 logic 4 edges after
// that (E4 -> E0).
//
// Reset values: the isolated receiver outputs (DOC/afe_interface_spec.md 3.2):
// rxdp = rxdm = 0 (SE0), rxrcv = 1.
//
// Every path is flop -> (at most one 2:1 mux) -> flop.  54 flops.
//
// Clocking: clk_bit, ld from usb_clk_gen; active-low asynchronous reset rst_n.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_rx_fsls_sampler (
    input  wire       clk_bit,
    input  wire       rst_n,
    input  wire       ld,

    input  wire       rxrcv,
    input  wire       rxdp,
    input  wire       rxdm,

    output reg  [7:0] rcv_v,
    output reg  [7:0] dp_v,
    output reg  [7:0] dm_v
);

    reg rc1, rc2, dp1, dp2, dm1, dm2;
    reg [7:0] rc_sh, dp_sh, dm_sh;

    always @(posedge clk_bit or negedge rst_n) begin
        if (!rst_n) begin
            rc1   <= 1'b1;  rc2 <= 1'b1;
            dp1   <= 1'b0;  dp2 <= 1'b0;
            dm1   <= 1'b0;  dm2 <= 1'b0;
            rc_sh <= 8'hFF; dp_sh <= 8'h00; dm_sh <= 8'h00;
            rcv_v <= 8'hFF; dp_v  <= 8'h00; dm_v  <= 8'h00;
        end else begin
            rc1 <= rxrcv;  rc2 <= rc1;
            dp1 <= rxdp;   dp2 <= dp1;
            dm1 <= rxdm;   dm2 <= dm1;
            rc_sh <= {rc2, rc_sh[7:1]};
            dp_sh <= {dp2, dp_sh[7:1]};
            dm_sh <= {dm2, dm_sh[7:1]};
            if (ld) begin
                rcv_v <= rc_sh;
                dp_v  <= dp_sh;
                dm_v  <= dm_sh;
            end
        end
    end

endmodule
