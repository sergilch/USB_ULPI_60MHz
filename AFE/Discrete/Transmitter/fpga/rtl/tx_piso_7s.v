//-----------------------------------------------------------------------------
// tx_piso_7s.v - TX 8:1 PISO and idle clamp for an AMD 7-Series FPGA
//                (stand-in for usb_tx_piso on the discrete transmitter board)
//
//   usb_afe_tx_if8 (clk60) --pin vectors--> [THIS BLOCK] --> OSERDESE2 x 7
//        --> TX_IN_P / TX_IN_N (LVDS), TX_EN, FS_OE, FS_DAT, FS_SE0, FS_LS (LVCMOS)
//
// Same pin vectors, pin polarities and idle values as usb_tx_piso (repo root;
// spec DOC/afe_interface_spec.md 3.1, 3.4, 4.1).  The ASIC shifts with 480 MHz
// flops; here each pin is one OSERDESE2 in DDR 8:1 mode (CLK = 240 MHz,
// CLKDIV = clk60, from the same MMCM), D1 = vector bit 0 = first bit on the
// pin.  TX_IN_N has its own OSERDESE2 loaded with the complement of hs_p_v, so
// P and N come from separate serializers as in the ASIC (spec 3.1).
//
// Differences to usb_tx_piso (documented in doc/tx_board.md, section 7):
//   * the idle clamp (drv_dis | iso_en) acts on whole 8-bit vectors: the pins
//     go idle from the first vector after the clamp was registered on clk60
//     (up to 8 + 2 bit times later instead of 2), and the rest of an
//     interrupted packet is dropped until a vector without any driver enable
//     (any_v = 0) has passed with the clamp off - the same rule per tick;
//   * fs_ls is a pin vector here (constant within a tick: fs_ls_q, or the held
//     value while no FS/LS bit is driven);
//   * OSERDESE2 latency (CLKDIV-to-OQ, a few CLK cycles) replaces the
//     LAT = 9 clk_bit cycles of the ASIC PISO.  It is constant and the same for
//     all seven pins, so the relative timing (TX_LEAD / TX_LAG) is exact.
//
// tx_active: as usb_tx_piso (act, or any driver enable in the output register).
//
// Simulation: define TX_PISO_SIM to replace OSERDESE2 by a behavioural DDR
// serializer (tb_tx_fpga_top, Icarus); synthesis uses the primitive.
// Clocks: clk60 (CLKDIV), clk240 (CLK), phase-aligned outputs of one MMCM.
// Reset rst_n asynchronous assert; the OSERDESE2 RST is released synchronously
// to clk60 by the top level.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module tx_piso_7s (
    input  wire       clk60,
    input  wire       clk240,
    input  wire       rst_n,

    // from usb_afe_tx_if8 (clk60)
    input  wire [7:0] hs_p_v,
    input  wire [7:0] hs_en_v,
    input  wire [7:0] fs_oe_v,
    input  wire [7:0] fs_dat_v,
    input  wire [7:0] fs_se0_v,
    input  wire [7:0] any_v,
    input  wire       fs_ls_q,
    input  wire       act,

    // clamp (quasi-static levels)
    input  wire       drv_dis,
    input  wire       iso_en,

    // serial pins (to OBUFDS / OBUF in the top level)
    output wire       hs_tx_p,
    output wire       hs_tx_n,
    output wire       hs_tx_en,
    output wire       fs_oe,
    output wire       fs_dat,
    output wire       fs_se0,
    output wire       fs_ls,
    output wire       tx_active
);

    reg [7:0] w_p, w_n, w_en, w_oe, w_dat, w_se0, w_ls;
    reg       cq, kq, ls_hold, act_q;

    wire force_idle = cq | kq;

    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            cq <= 1'b0; kq <= 1'b0; ls_hold <= 1'b0; act_q <= 1'b0;
            w_p <= 8'hFF; w_n <= 8'h00; w_en <= 8'h00; w_oe <= 8'h00;
            w_dat <= 8'hFF; w_se0 <= 8'h00; w_ls <= 8'h00;
        end else begin
            cq    <= drv_dis | iso_en;
            // drop the rest of an interrupted packet: stay forced while the
            // vectors still carry driver enables of that packet
            kq    <= cq | (kq & (|any_v));
            act_q <= act;
            if (force_idle) begin
                w_p <= 8'hFF; w_n <= 8'h00; w_en <= 8'h00; w_oe <= 8'h00;
                w_dat <= 8'hFF; w_se0 <= 8'h00; w_ls <= 8'h00;
                ls_hold <= 1'b0;
            end else begin
                w_p   <= hs_p_v;
                w_n   <= ~hs_p_v;
                w_en  <= hs_en_v;
                w_oe  <= fs_oe_v;
                w_dat <= fs_dat_v;
                w_se0 <= fs_se0_v;
                w_ls  <= {8{(|fs_oe_v) ? fs_ls_q : ls_hold}};
                if (|fs_oe_v) ls_hold <= fs_ls_q;
            end
        end
    end

    assign tx_active = act_q | (|w_en) | (|w_oe);

    oserdes8 u_p   (.clk60(clk60), .clk240(clk240), .rst_n(rst_n), .d(w_p),   .oq(hs_tx_p));
    oserdes8 u_n   (.clk60(clk60), .clk240(clk240), .rst_n(rst_n), .d(w_n),   .oq(hs_tx_n));
    oserdes8 u_en  (.clk60(clk60), .clk240(clk240), .rst_n(rst_n), .d(w_en),  .oq(hs_tx_en));
    oserdes8 u_oe  (.clk60(clk60), .clk240(clk240), .rst_n(rst_n), .d(w_oe),  .oq(fs_oe));
    oserdes8 u_dat (.clk60(clk60), .clk240(clk240), .rst_n(rst_n), .d(w_dat), .oq(fs_dat));
    oserdes8 u_se0 (.clk60(clk60), .clk240(clk240), .rst_n(rst_n), .d(w_se0), .oq(fs_se0));
    oserdes8 u_ls  (.clk60(clk60), .clk240(clk240), .rst_n(rst_n), .d(w_ls),  .oq(fs_ls));

endmodule

//-----------------------------------------------------------------------------
// oserdes8: one pin, 8:1 DDR serializer, d[0] first
//-----------------------------------------------------------------------------
module oserdes8 (
    input  wire       clk60,
    input  wire       clk240,
    input  wire       rst_n,
    input  wire [7:0] d,
    output wire       oq
);
`ifdef TX_PISO_SIM
    // behavioural: word taken on clk60, bit k after the k-th clk240 edge
    // (both edges) that follows; clk240 rises with clk60 (same MMCM)
    reg [7:0] sh;
    reg [2:0] k;
    reg [7:0] word;
    reg       q;
    always @(posedge clk60 or negedge rst_n)
        if (!rst_n) word <= 8'h00; else word <= d;
    always @(posedge clk240 or negedge clk240 or negedge rst_n) begin
        if (!rst_n) begin
            k <= 3'd0; q <= 1'b0; sh <= 8'h00;
        end else begin
            if (k == 3'd0) begin q <= word[0]; sh <= {1'b0, word[7:1]}; end
            else begin q <= sh[0]; sh <= {1'b0, sh[7:1]}; end
            k <= k + 3'd1;
        end
    end
    assign oq = q;
`else
    reg rst_s1, rst_s2;                      // RST released synchronously to CLKDIV
    always @(posedge clk60 or negedge rst_n)
        if (!rst_n) {rst_s1, rst_s2} <= 2'b11; else {rst_s1, rst_s2} <= {1'b0, rst_s1};

    OSERDESE2 #(
        .DATA_RATE_OQ   ("DDR"),
        .DATA_RATE_TQ   ("SDR"),
        .DATA_WIDTH     (8),
        .SERDES_MODE    ("MASTER"),
        .TRISTATE_WIDTH (1),
        .INIT_OQ        (1'b0),
        .SRVAL_OQ       (1'b0)
    ) u_oserdes (
        .OQ       (oq),
        .OFB      (),
        .TQ       (),
        .TFB      (),
        .SHIFTOUT1(),
        .SHIFTOUT2(),
        .TBYTEOUT (),
        .CLK      (clk240),
        .CLKDIV   (clk60),
        .D1(d[0]), .D2(d[1]), .D3(d[2]), .D4(d[3]),
        .D5(d[4]), .D6(d[5]), .D7(d[6]), .D8(d[7]),
        .OCE      (1'b1),
        .RST      (rst_s2),
        .SHIFTIN1 (1'b0),
        .SHIFTIN2 (1'b0),
        .T1(1'b0), .T2(1'b0), .T3(1'b0), .T4(1'b0),
        .TBYTEIN  (1'b0),
        .TCE      (1'b0)
    );
`endif
endmodule
