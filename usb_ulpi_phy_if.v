//-----------------------------------------------------------------------------
// usb_ulpi_phy_if.v
//
// Complete digital ULPI interface of the USB 2.0 PHY: ULPI pins on one side; the
// transmitter line signals, the RX datapath, the line / VBUS / ID status and the ULPI
// Register File on the other side.
//
//                       +-----------------------------------------------+
//   ULPI pins <-------> |  usb_ulpi_core                                | --> txd/tx_en/tx_se0
//                       |   (capture, TX datapath, register access,     | <-> Register File
//                       |    burst mux, bus owner)                      |
//                       +----------------^------------------------------+
//                                        | arb_* burst, stp_abort
//   RX datapath ----> usb_ulpi_rx_path (RX Data Handler, RXCMD Generator, Output Arbiter)
//   status / IE masks ---^
//
// Clocking (Plan_60MHz.md P2): everything runs on the 60 MHz core clock clk60
// (usb_clk_gen; the leaves keep their ce port, tied to 1).  Only the TX
// serializer stays on clk_bit (480 MHz), behind usb_tx_ser_bridge: words and
// status cross on the island strobe ld (usb_clk_gen boundary rule), and the
// line outputs txd / tx_en / tx_se0 / tx_speed / tx_done / tx_underrun are
// clk_bit signals.  On the line, a packet leaves 4 clk_bit cycles earlier
// than in the single-clock design; every ULPI-side event is in the same tick.
// All other inputs and outputs are clk60-domain signals.
//
// Open ends of the PHY: the Register File itself (reg_*), the RX datapath
// (rx_*), the line state / VBUS / ID detectors (status inputs) and the low-power
// controller (dir_hold).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_ulpi_phy_if #(
    parameter FS_DIV   = 40,
    parameter LS_DIV   = 320,
    parameter DIV_W    = 9,
    parameter RX_DEPTH = 8
) (
    input  wire        clk_bit,      // 480 MHz: TX serializer island only
    input  wire        rst_n,
    input  wire        clk60,        // core clock (usb_clk_gen), everything except the serializer
    input  wire        ld,           // island strobe (usb_clk_gen): serializer bridge

    // ULPI pins
    input  wire [7:0]  ulpi_data_in,
    input  wire        ulpi_stp,
    output wire        ulpi_dir,
    output wire        ulpi_nxt,
    output wire [7:0]  ulpi_data_out,
    output wire        ulpi_data_oe,

    // static configuration
    input  wire [1:0]  speed,
    input  wire        bypass_en,
    input  wire        sync_dis,
    input  wire        eop_dis,
    input  wire        dir_hold,

    // RX datapath
    input  wire        rx_start,
    input  wire        rx_valid,
    input  wire [7:0]  rx_data,
    input  wire        rx_end,
    input  wire        rx_error,

    // status for the RXCMD byte
    input  wire [1:0]  linestate,
    input  wire [1:0]  vbusstate,
    input  wire        host_disc,
    input  wire        id_gnd,
    input  wire        alt_int,
    input  wire [4:0]  ie_rise,
    input  wire [4:0]  ie_fall,

    // ULPI Register File
    output wire        reg_wr,
    output wire        reg_rd,
    output wire        reg_ext,
    output wire [7:0]  reg_addr,
    output wire [7:0]  reg_wdata,
    input  wire [7:0]  reg_rdata,
    input  wire        rd_valid,

    // transmitter side
    output wire        txd,
    output wire        tx_en,
    output wire        tx_se0,
    output wire [1:0]  tx_speed,

    output wire        busy,
    output wire        tx_done,
    output wire        tx_underrun,
    output wire        rx_active,
    output wire        rx_err,
    output wire        rx_overrun
);

    wire       arb_valid, arb_is_data, arb_ready;
    wire [7:0] arb_data;
    wire       stp_abort;

    usb_ulpi_core #(
        .FS_DIV (FS_DIV),
        .LS_DIV (LS_DIV),
        .DIV_W  (DIV_W)
    ) u_core (
        .clk_bit       (clk_bit),
        .rst_n         (rst_n),
        .clk60          (clk60),
        .ld             (ld),
        .ulpi_data_in  (ulpi_data_in),
        .ulpi_stp      (ulpi_stp),
        .ulpi_dir      (ulpi_dir),
        .ulpi_nxt      (ulpi_nxt),
        .ulpi_data_out (ulpi_data_out),
        .ulpi_data_oe  (ulpi_data_oe),
        .speed         (speed),
        .bypass_en     (bypass_en),
        .sync_dis      (sync_dis),
        .eop_dis       (eop_dis),
        .arb_valid     (arb_valid),
        .arb_data      (arb_data),
        .arb_is_data   (arb_is_data),
        .arb_ready     (arb_ready),
        .dir_hold      (dir_hold),
        .reg_wr        (reg_wr),
        .reg_rd        (reg_rd),
        .reg_ext       (reg_ext),
        .reg_addr      (reg_addr),
        .reg_wdata     (reg_wdata),
        .reg_rdata     (reg_rdata),
        .rd_valid      (rd_valid),
        .stp_abort     (stp_abort),
        .txd           (txd),
        .tx_en         (tx_en),
        .tx_se0        (tx_se0),
        .tx_speed      (tx_speed),
        .busy          (busy),
        .tx_done       (tx_done),
        .tx_underrun   (tx_underrun)
    );

    usb_ulpi_rx_path #(.DEPTH(RX_DEPTH)) u_rx (
        .clk         (clk60),
        .rst_n       (rst_n),
        .ce          (1'b1),
        .rx_start    (rx_start),
        .rx_valid    (rx_valid),
        .rx_data     (rx_data),
        .rx_end      (rx_end),
        .rx_error    (rx_error),
        .rx_abort    (stp_abort),
        .linestate   (linestate),
        .vbusstate   (vbusstate),
        .host_disc   (host_disc),
        .id_gnd      (id_gnd),
        .alt_int     (alt_int),
        .ie_rise     (ie_rise),
        .ie_fall     (ie_fall),
        .ext_valid   (arb_valid),
        .ext_data    (arb_data),
        .ext_is_data (arb_is_data),
        .ext_ready   (arb_ready),
        .rx_active   (rx_active),
        .rx_err      (rx_err),
        .overrun     (rx_overrun)
    );

endmodule
