//-----------------------------------------------------------------------------
// usb_tx_piso.v - TX 8:1 PISO and idle clamp, the 480 MHz end of the TX path
//                 (Plan_60MHz.md 3.2 / 4.2, P6; spec DOC/afe_interface_spec.md
//                 3.1, 3.4, 4.1)
//
//   usb_afe_tx_if8 (clk60) --pin vectors--> [THIS BLOCK, clk_bit]
//        --> hs_tx_p / hs_tx_n / hs_tx_en (HS TX), fs_oe / fs_dat / fs_se0 / fs_ls
//
// Shift: one 8-bit shift register per pin, loaded with the clk60 vectors on
//   ld (the clk_bit edge E4, half a clk60 period after the clk60 edge that
//   launched them: usb_clk_gen boundary rule, SDC multicycle 4 / 3) and
//   shifted on the other 7 edges; bit 0 first.  hs_tx_n has its own shift
//   register, loaded with the complement, so P and N come from separate flops
//   and the P/N skew is only flop and routing mismatch (spec 3.1).  Every pin
//   is a flop with at most one gate in front of it (the clamp), so all pins
//   change on the same clk_bit edge.  Latency: vector bit i (output register of
//   usb_afe_tx_if8 after the clk60 edge E0) is on the pin after edge E5 + i.
//
// Idle clamp (drv_dis: OpMode 01 non-driving; iso_en: isolation), as the old
//   usb_afe_tx_if: drv_dis | iso_en is registered once (cq) and forces every
//   pin to its idle value on the following edge (the second edge after the
//   input).  The force term cq | kq has its own flop fq (same value), so each
//   pin flop has one gate in front of it (480 MHz at the slow corner).  The rest of the interrupted packet is dropped: the pins stay idle
//   (kq) until the packet's driver enables (hs_tx_en, fs_oe, before the clamp)
//   have fallen with the clamp off, so a packet never resumes in the middle.
//   The 60 MHz side does not see the clamp; it finishes the packet into the
//   dropped bits.  fs_ls goes to 0 and holds until the next FS/LS bit.  The
//   inputs are level controls (quasi-static OpMode, power sequencer), captured
//   by one flop as before.
//
// tx_active: a driver is on, or will be (act of usb_afe_tx_if8, sampled on ld,
//   covers everything up to the shift registers), for the receiver hold-off
//   and the HostDisconnect window.  Not cleared by the clamp.
//
// Pin values (spec 3.1 / 3.4)       reset / clamp   idle
//   hs_tx_p   1 = J (DP high)          1              1
//   hs_tx_n   complement               0              0
//   hs_tx_en, fs_oe, fs_se0            0              0
//   fs_dat    1 = J                    1              1
//   fs_ls     LS slew rate             0              holds the last packet's value
//
// Clocks: clk_bit; ld (usb_clk_gen, high while phase = 3); vector inputs and
//   act are clk60 signals.  Reset rst_n, asynchronous.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_tx_piso (
    input  wire       clk_bit,
    input  wire       rst_n,
    input  wire       ld,

    // from usb_afe_tx_if8 (clk60)
    input  wire [7:0] hs_p_v,
    input  wire [7:0] hs_en_v,
    input  wire [7:0] fs_oe_v,
    input  wire [7:0] fs_dat_v,
    input  wire [7:0] fs_se0_v,
    input  wire [7:0] any_v,
    input  wire       fs_ls_q,
    input  wire       act,

    // clamp
    input  wire       drv_dis,
    input  wire       iso_en,

    // AFE pins
    output reg        hs_tx_p,
    output reg        hs_tx_n,
    output reg        hs_tx_en,
    output reg        fs_oe,
    output reg        fs_dat,
    output reg        fs_se0,
    output reg        fs_ls,
    output wire       tx_active
);

    reg [7:0] s_p, s_n, s_en, s_oe, s_dat, s_se0, s_any;
    reg       ls_b, act_b, cq, kq, fq;     // fq = cq | kq, own flop (one gate per pin)

    always @(posedge clk_bit or negedge rst_n) begin
        if (!rst_n) begin
            s_p   <= 8'hFF; s_n   <= 8'h00; s_en <= 8'h00; s_oe <= 8'h00;
            s_dat <= 8'hFF; s_se0 <= 8'h00; s_any <= 8'h00;
            ls_b  <= 1'b0; act_b <= 1'b0; cq <= 1'b0; kq <= 1'b0; fq <= 1'b0;
            hs_tx_p <= 1'b1; hs_tx_n <= 1'b0; hs_tx_en <= 1'b0;
            fs_oe <= 1'b0; fs_dat <= 1'b1; fs_se0 <= 1'b0; fs_ls <= 1'b0;
        end else begin
            if (ld) begin
                s_p   <= hs_p_v;   s_n   <= ~hs_p_v;  s_en <= hs_en_v; s_oe <= fs_oe_v;
                s_dat <= fs_dat_v; s_se0 <= fs_se0_v; s_any <= any_v;
                ls_b  <= fs_ls_q;  act_b <= act;
            end else begin
                s_p   <= {1'b1, s_p[7:1]};   s_n   <= {1'b0, s_n[7:1]};
                s_en  <= {1'b0, s_en[7:1]};  s_oe  <= {1'b0, s_oe[7:1]};
                s_dat <= {1'b1, s_dat[7:1]}; s_se0 <= {1'b0, s_se0[7:1]};
                s_any <= {1'b0, s_any[7:1]};
            end

            cq <= drv_dis | iso_en;
            kq <= cq | (kq & s_any[0]);
            fq <= drv_dis | iso_en | cq | (kq & s_any[0]);   // = next cq | next kq

            hs_tx_p  <= s_p[0]   |  fq;
            hs_tx_n  <= s_n[0]   & ~fq;
            hs_tx_en <= s_en[0]  & ~fq;
            fs_oe    <= s_oe[0]  & ~fq;
            fs_dat   <= s_dat[0] |  fq;
            fs_se0   <= s_se0[0] & ~fq;
            fs_ls    <= ~fq & (s_oe[0] ? ls_b : fs_ls);
        end
    end

    assign tx_active = act_b | hs_tx_en | fs_oe;

endmodule
