//-----------------------------------------------------------------------------
// usb_tx_datapath.v   (revision 2: latency-aware Link interface)
//
// TX datapath of the USB 2.0 PHY as drawn in the block diagram
// (usb_phy_ulpi_digital), from the captured ULPI Link signals to the transmitter
// line signals:
//
//   usb_ulpi_input_capture -> usb_tx_holding  (TX Holding Reg / Ctrl, NXT pacing)
//                          -> usb_tx_sync_mux (SYNC + PID/Data Mux)
//                          -> usb_tx_path     (Bit Stuffer -> NRZI -> Serializer8 + EOP)
//                          -> txd_v / tx_en_v / tx_se0_v (8 bits per tick, to
//                             usb_afe_tx_if8 -> usb_tx_piso -> transmitter)
//
// Clocking (Plan_60MHz.md P2, P6): everything runs on the 60 MHz core clock
// clk60 (usb_clk_gen; the leaves keep their ce port, tied to 1).  The line
// leaves as vectors (usb_tx_serializer8); the only bit-rate stage is
// usb_tx_piso behind usb_afe_tx_if8, outside this block.  All inputs and
// outputs are clk60-domain signals; tx_done / tx_underrun are one-tick pulses.
//
// Link-side hookup (all from usb_ulpi_input_capture / usb_ulpi_bus_owner):
//   cmd_tx, cmd_pid, lnk_valid, lnk_data, lnk_stp : captured and decoded Link signals
//   nxt_seen : NXT of the tick of the captured byte;  nxt_pin : NXT on the pin now
//   stp_raw  : unregistered STP on the pin now
//   nxt_n    : NXT request for the next tick -> tx_nxt_n of usb_ulpi_bus_owner
//   hold_busy: TX holding block busy        -> tx_busy   of usb_ulpi_bus_owner
//
// Static configuration (stable from TXCMD to tx_done)
//   speed     : XcvrSelect, 00 HS, 01 FS, 10 LS
//   bypass_en : no bit stuffing and no NRZI (OpMode "disable bit stuffing and NRZI")
//   sync_dis  : do not insert SYNC
//   eop_dis   : no EOP at the end of the packet (OpMode 10 chirp / K signalling)
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_tx_datapath #(
    parameter FS_DIV = 40,
    parameter LS_DIV = 320,
    parameter DIV_W  = 9
) (
    input  wire        rst_n,
    input  wire        clk60,        // core clock (usb_clk_gen)

    input  wire [1:0]  speed,
    input  wire        bypass_en,
    input  wire        sync_dis,
    input  wire        eop_dis,

    // captured ULPI Link side
    input  wire        cmd_tx,
    input  wire [3:0]  cmd_pid,
    input  wire        lnk_valid,
    input  wire [7:0]  lnk_data,
    input  wire        lnk_stp,
    input  wire        nxt_seen,
    input  wire        nxt_pin,
    input  wire        stp_raw,
    output wire        nxt_n,
    output wire        hold_busy,

    // transmitter side (vectors, bit 0 first)
    output wire [7:0]  txd_v,
    output wire [7:0]  tx_en_v,
    output wire [7:0]  tx_se0_v,
    output wire [1:0]  tx_speed,

    output wire        busy,
    output wire        tx_done,
    output wire        tx_underrun
);

    // holding -> mux
    wire        hdr_valid, hdr_ready, hdr_nopid, hdr_empty;
    wire [3:0]  hdr_pid;
    wire        d_valid, d_ready, d_last;
    wire [7:0]  d_data;

    // mux -> TX path (stuffer)
    wire        m_valid, m_ready, m_last;
    wire [7:0]  m_data;
    wire        mux_busy, path_busy;

    usb_tx_holding u_hold (
        .clk       (clk60),
        .rst_n     (rst_n),
        .ce        (1'b1),
        .cmd_tx    (cmd_tx),
        .cmd_pid   (cmd_pid),
        .lnk_valid (lnk_valid),
        .lnk_data  (lnk_data),
        .lnk_stp   (lnk_stp),
        .nxt_seen  (nxt_seen),
        .nxt_pin   (nxt_pin),
        .stp_raw   (stp_raw),
        .nxt_n     (nxt_n),
        .hdr_valid (hdr_valid),
        .hdr_ready (hdr_ready),
        .hdr_pid   (hdr_pid),
        .hdr_nopid (hdr_nopid),
        .hdr_empty (hdr_empty),
        .d_valid   (d_valid),
        .d_ready   (d_ready),
        .d_data    (d_data),
        .d_last    (d_last),
        .busy      (hold_busy)
    );

    usb_tx_sync_mux u_mux (
        .clk       (clk60),
        .rst_n     (rst_n),
        .ce        (1'b1),
        .speed     (speed),
        .sync_dis  (sync_dis),
        .hdr_valid (hdr_valid),
        .hdr_ready (hdr_ready),
        .hdr_pid   (hdr_pid),
        .hdr_nopid (hdr_nopid),
        .hdr_empty (hdr_empty),
        .d_valid   (d_valid),
        .d_ready   (d_ready),
        .d_data    (d_data),
        .d_last    (d_last),
        .out_valid (m_valid),
        .out_ready (m_ready),
        .out_data  (m_data),
        .out_last  (m_last),
        .busy      (mux_busy)
    );

    usb_tx_path #(
        .FS_DIV (FS_DIV),
        .LS_DIV (LS_DIV),
        .DIV_W  (DIV_W)
    ) u_path (
        .clk         (clk60),
        .rst_n       (rst_n),
        .speed       (speed),
        .bypass_en   (bypass_en),
        .eop_dis     (eop_dis),
        .in_valid    (m_valid),
        .in_ready    (m_ready),
        .in_data     (m_data),
        .in_last     (m_last),
        .txd_v       (txd_v),
        .tx_en_v     (tx_en_v),
        .tx_se0_v    (tx_se0_v),
        .tx_speed    (tx_speed),
        .busy        (path_busy),
        .tx_done     (tx_done),
        .tx_underrun (tx_underrun)
    );

    assign busy = hold_busy | mux_busy | path_busy;

endmodule
