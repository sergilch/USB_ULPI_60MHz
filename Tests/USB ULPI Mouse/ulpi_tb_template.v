//=============================================================================
// ulpi_tb_template.v
//
// ULPI (UTMI+ Low Pin Interface, 8-bit SDR, 60 MHz) bus-access template for
// building testbenches.  Plain Verilog-2001, no SystemVerilog needed.
//
// Contents
//   1. Constants (`define): TXCMD codes, USB PIDs, register addresses
//   2. ulpi_link_bfm : testbench plays the LINK   -> use when the DUT is a PHY
//   3. ulpi_phy_bfm  : testbench plays the PHY    -> use when the DUT is a Link
//   4. ulpi_bfm_demo : back-to-back self-test (compile with +define+ULPI_BFM_DEMO)
//
// Signals (names per ULPI spec)
//   clk   : 60 MHz, driven by the PHY
//   data  : 8-bit bidirectional bus (Link drives when dir=0, PHY when dir=1)
//   dir   : PHY -> Link, bus direction
//   nxt   : PHY -> Link, "next" / handshake
//   stp   : Link -> PHY, "stop"
//
// Bus-level behaviour modelled (ULPI Rev 1.1, interface/register-access
// chapters -- please verify the corner cases against your copy of the spec):
//   TXCMD          : data[7:6]=01  transmit, [3:0]=PID   (0x40 = NOPID)
//                    data[7:6]=10  register write, [5:0]=address
//                    data[7:6]=11  register read,  [5:0]=address
//                    address 6'h2F -> extended register access (8-bit addr follows)
//   Register write : cmd (until nxt) -> data (until nxt) -> STP cycle w/ data=00
//   Register read  : cmd (until nxt) -> PHY dir=1 -> turnaround -> data -> dir=0
//   USB transmit   : TXCMD (until nxt) -> bytes (advance on nxt) -> STP cycle
//   TXCMD aborted  : the PHY asserts dir before nxt in the TXCMD cycle (RX CMD
//                    or USB receive): the Link BFM retries the TXCMD when the
//                    bus is idle again (link_cmd_phase, ULPI 3.8.2 / 3.8.3)
//   USB receive    : dir=1 -> turnaround -> RXCMD (RxActive=1) -> bytes with
//                    nxt=1 -> RXCMD (RxActive=0) -> dir=0
//                    (dir and nxt asserted together = implicit RxActive)
//   RXCMD          : dir=1, nxt=0: [1:0] LineState  [3:2] VbusState
//                    [5:4] RxEvent (00 idle, 01 RxActive, 11 RxActive+RxError,
//                    10 HostDisconnect)  [6] ID  [7] alt_int
//
// Timing convention
//   Every BFM output changes TCQ after a rising clk edge and every input is
//   sampled AT the rising edge (before the TCQ-delayed outputs change), so the
//   BFMs are free of races with a zero-delay DUT.  Each public task starts
//   with one aligning clock edge, so back-to-back calls have >=1 idle cycle.
//=============================================================================

`timescale 1ns/1ps

//-----------------------------------------------------------------------------
// 1. Constants
//-----------------------------------------------------------------------------
`ifndef ULPI_DEFS_VH
`define ULPI_DEFS_VH

// TXCMD builders / codes
`define ULPI_TXCMD_NOOP        8'h00
`define ULPI_TXCMD_XMIT(pid)   {4'b0100, pid}   // pid is 4 bits; pid=0 -> NOPID
`define ULPI_TXCMD_REGW(addr)  {2'b10, addr}    // addr is 6 bits
`define ULPI_TXCMD_REGR(addr)  {2'b11, addr}
`define ULPI_TXCMD_EXT_REGW    8'hAF            // {2'b10, 6'h2F}
`define ULPI_TXCMD_EXT_REGR    8'hEF            // {2'b11, 6'h2F}

// USB PIDs (4-bit PID field, as carried in TXCMD[3:0])
`define ULPI_PID_OUT    4'h1
`define ULPI_PID_IN     4'h9
`define ULPI_PID_SOF    4'h5
`define ULPI_PID_SETUP  4'hD
`define ULPI_PID_DATA0  4'h3
`define ULPI_PID_DATA1  4'hB
`define ULPI_PID_DATA2  4'h7
`define ULPI_PID_MDATA  4'hF
`define ULPI_PID_ACK    4'h2
`define ULPI_PID_NAK    4'hA
`define ULPI_PID_STALL  4'hE
`define ULPI_PID_NYET   4'h6
`define ULPI_PID_PING   4'h4

// Immediate register addresses (read address; +1 = set, +2 = clear where noted)
`define ULPI_REG_VENDOR_ID_LOW   6'h00
`define ULPI_REG_VENDOR_ID_HIGH  6'h01
`define ULPI_REG_PRODUCT_ID_LOW  6'h02
`define ULPI_REG_PRODUCT_ID_HIGH 6'h03
`define ULPI_REG_FUNC_CTRL       6'h04   // 05 = set, 06 = clear
`define ULPI_REG_FUNC_CTRL_SET   6'h05
`define ULPI_REG_FUNC_CTRL_CLR   6'h06
`define ULPI_REG_IFACE_CTRL      6'h07   // 08 = set, 09 = clear
`define ULPI_REG_OTG_CTRL        6'h0A   // 0B = set, 0C = clear
`define ULPI_REG_INT_EN_RISING   6'h0D   // 0E = set, 0F = clear
`define ULPI_REG_INT_EN_FALLING  6'h10   // 11 = set, 12 = clear
`define ULPI_REG_INT_STATUS      6'h13
`define ULPI_REG_INT_LATCH       6'h14
`define ULPI_REG_DEBUG           6'h15
`define ULPI_REG_SCRATCH         6'h16   // 17 = set, 18 = clear
`define ULPI_REG_SCRATCH_SET     6'h17
`define ULPI_REG_SCRATCH_CLR     6'h18

// Function Control bits
`define ULPI_FUNC_RESET          8'h20
`define ULPI_FUNC_SUSPENDM       8'h40

`endif

//=============================================================================
// 2. LINK-side BFM  (testbench = Link, DUT = PHY)
//=============================================================================
module ulpi_link_bfm #(
  parameter real TCQ         = 1.0,   // clock-to-output delay [ns]
  parameter      NXT_TIMEOUT = 64,    // cycles to wait for nxt / dir before erroring
  parameter      TX_MAX      = 1024,  // size of tx_buf
  parameter      RX_MAX      = 1024,  // size of rx_buf
  parameter      CMD_RETRIES = 16     // TX CMD aborts by the PHY retried in a row
)(
  input        clk,
  input        dir,
  input        nxt,
  inout  [7:0] data,
  output reg   stp
);

  //---------------------------------------------------------------- bus drive
  reg [7:0] data_o;
  reg       data_oe;
  // Link releases the bus whenever the PHY owns it (dir=1)
  assign data = (data_oe && !dir) ? data_o : 8'bz;

  //----------------------------------------------------------- user-visible state
  reg [7:0] tx_buf [0:TX_MAX-1];   // fill before calling link_tx_packet
  reg [7:0] rx_buf [0:RX_MAX-1];   // filled by the receive monitor
  integer   rx_len;                // payload bytes in last/current received packet
  reg [7:0] last_rxcmd;            // most recent RXCMD
  integer   rxcmd_cnt;             // number of RXCMDs seen
  integer   rx_pkt_cnt;            // number of completed receive packets
  reg       rx_err_seen;           // RxError was flagged in the last packet
  integer   err_cnt;               // testbench error counter
  integer   cmd_retry_cnt;         // TX CMDs aborted by the PHY and retried (not errors)
  event     rx_packet_done;

  reg       reg_rd_busy;           // suppresses RXCMD/RX decode during register-read data

  initial begin
    $timeformat(-9, 3, " ns", 10);
    data_o = 8'h00; data_oe = 1'b1; stp = 1'b0;
    rx_len = 0; last_rxcmd = 8'h00; rxcmd_cnt = 0; rx_pkt_cnt = 0;
    rx_err_seen = 1'b0; err_cnt = 0; reg_rd_busy = 1'b0; cmd_retry_cnt = 0;
  end

  //------------------------------------------------------------ RXCMD decode
  function [1:0] rxcmd_linestate(input [7:0] b); rxcmd_linestate = b[1:0];          endfunction
  function [1:0] rxcmd_vbusstate(input [7:0] b); rxcmd_vbusstate = b[3:2];          endfunction
  function       rxcmd_rxactive (input [7:0] b); rxcmd_rxactive  = b[4];            endfunction
  function       rxcmd_rxerror  (input [7:0] b); rxcmd_rxerror   = b[5] & b[4];     endfunction
  function       rxcmd_hostdisc (input [7:0] b); rxcmd_hostdisc  = (b[5:4] == 2'b10); endfunction
  function       rxcmd_id       (input [7:0] b); rxcmd_id        = b[6];            endfunction
  function       rxcmd_alt_int  (input [7:0] b); rxcmd_alt_int   = b[7];            endfunction

  //------------------------------------------------- passive receive monitor
  // Decodes everything the PHY sends while dir=1 (RXCMDs and USB receive data).
  reg dir_q;
  reg rx_active;
  initial begin dir_q = 1'b0; rx_active = 1'b0; end

  always @(posedge clk) begin
    dir_q <= dir;
    if (dir && !dir_q) begin
      // Turnaround cycle.  nxt asserted together with dir => implicit RxActive.
      if (nxt && !reg_rd_busy) begin
        rx_active = 1'b1; rx_len = 0; rx_err_seen = 1'b0;
      end
    end else if (dir && dir_q && !reg_rd_busy) begin
      if (nxt) begin                         // USB receive data byte
        if (rx_len < RX_MAX) rx_buf[rx_len] = data;
        rx_len = rx_len + 1;
      end else begin                         // RXCMD
        last_rxcmd = data;
        rxcmd_cnt  = rxcmd_cnt + 1;
        if (rxcmd_rxerror(data)) rx_err_seen = 1'b1;
        if (data[4] && !rx_active) begin     // RxActive 0 -> 1
          rx_active = 1'b1; rx_len = 0; rx_err_seen = rxcmd_rxerror(data);
        end else if (!data[4] && rx_active) begin   // RxActive 1 -> 0
          rx_active  = 1'b0;
          rx_pkt_cnt = rx_pkt_cnt + 1;
          -> rx_packet_done;
        end
      end
    end
  end

  //------------------------------------------------------- low-level helpers
  // Align to a clock edge (+TCQ).  All public tasks call this first.
  task link_sync;
    begin @(posedge clk); #(TCQ); end
  endtask

  // Wait (if necessary) until the PHY has released the bus.
  task link_wait_idle;
    integer t;
    begin
      t = 0;
      if (dir) begin
        while (dir && t < 200000) begin @(posedge clk); t = t + 1; end
        #(TCQ);
      end
    end
  endtask

  // Drive one bus cycle; returns nxt/dir as sampled at the END of that cycle.
  // Must be entered at (edge + TCQ); returns at (next edge + TCQ).
  task link_cycle(input [7:0] d, input s, output nxt_s, output dir_s);
    begin
      data_o = d; stp = s; data_oe = 1'b1;
      @(posedge clk);
      nxt_s = nxt; dir_s = dir;
      #(TCQ);
    end
  endtask

  // Drive byte d until the PHY accepts it (nxt=1 sampled).  ok=0 on timeout or
  // if the PHY grabbed the bus (dir=1 -> transfer aborted).
  task link_phase(input [7:0] d, output ok);
    reg n, dr;
    integer t;
    begin
      ok = 1'b0; n = 1'b0; dr = 1'b0; t = 0;
      while (!n && !dr && t < NXT_TIMEOUT) begin
        link_cycle(d, 1'b0, n, dr);
        t = t + 1;
      end
      if (dr) begin
        err_cnt = err_cnt + 1;
        $display("[%0t] ULPI LINK: ERROR dir asserted during transfer (byte 0x%02h) - aborted", $time, d);
      end else if (!n) begin
        err_cnt = err_cnt + 1;
        $display("[%0t] ULPI LINK: ERROR timeout waiting for nxt (byte 0x%02h)", $time, d);
      end else
        ok = 1'b1;
    end
  endtask

  // TX CMD byte of any Link transfer.  The PHY may abort it by asserting dir
  // before it has accepted the byte (USB receive or an RX CMD; ULPI 1.1
  // 3.8.2.2, 3.8.3.1 / 3.8.3.2: "the Link must retry ... when the bus is idle"),
  // e.g. the LineState RX CMD that follows the RX CMD with RxActive = 0 at the
  // end of a received full-speed packet.  That is not an error: the Link waits
  // until the PHY releases the bus and sends the TX CMD again (counted in
  // cmd_retry_cnt).  A timeout, or more than CMD_RETRIES aborts in a row, is.
  task link_cmd_phase(input [7:0] d, output ok);
    reg n, dr;
    integer t, tries;
    begin
      ok = 1'b0; tries = 0;
      while (!ok && tries <= CMD_RETRIES) begin
        n = 1'b0; dr = 1'b0; t = 0;
        while (!n && !dr && t < NXT_TIMEOUT) begin
          link_cycle(d, 1'b0, n, dr);
          t = t + 1;
        end
        if (dr) begin
          tries = tries + 1;
          cmd_retry_cnt = cmd_retry_cnt + 1;
          $display("[%0t] ULPI LINK: TX CMD 0x%02h aborted by PHY (dir), retry when the bus is idle", $time, d);
          link_cleanup; link_sync; link_wait_idle;
        end else if (!n) begin
          err_cnt = err_cnt + 1;
          $display("[%0t] ULPI LINK: ERROR timeout waiting for nxt (TX CMD 0x%02h)", $time, d);
          tries = CMD_RETRIES + 1;
        end else
          ok = 1'b1;
      end
      if (!ok && tries == CMD_RETRIES + 1 && dr) begin
        err_cnt = err_cnt + 1;
        $display("[%0t] ULPI LINK: ERROR TX CMD 0x%02h aborted %0d times", $time, d, tries);
      end
    end
  endtask

  task link_cleanup;                 // return bus to idle after an abort
    begin data_o = 8'h00; stp = 1'b0; data_oe = 1'b1; end
  endtask

  task link_stp_cycle;               // one STP cycle (data=00) then one idle cycle
    reg n, d;
    begin
      link_cycle(8'h00, 1'b1, n, d);
      link_cycle(8'h00, 1'b0, n, d);
    end
  endtask

  // Receive the register-read data phase (after the read command was accepted).
  task link_read_data(output [7:0] rd);
    integer t;
    begin
      reg_rd_busy = 1'b1; rd = 8'hxx; t = 0;
      data_o = 8'h00; stp = 1'b0;                 // idle until PHY takes the bus
      @(posedge clk);
      while (!dir && t < NXT_TIMEOUT) begin @(posedge clk); t = t + 1; end
      if (!dir) begin
        err_cnt = err_cnt + 1;
        $display("[%0t] ULPI LINK: ERROR timeout waiting for dir (register read)", $time);
      end else begin
        @(posedge clk); rd = data;                // first dir cycle = turnaround
        @(posedge clk); t = 0;
        while (dir && t < NXT_TIMEOUT) begin @(posedge clk); t = t + 1; end
      end
      #(TCQ);
      reg_rd_busy = 1'b0;
    end
  endtask

  //---------------------------------------------------------- public tasks
  task link_noop;
    reg n, d;
    begin link_sync; link_cycle(`ULPI_TXCMD_NOOP, 1'b0, n, d); end
  endtask

  task link_idle(input integer cycles);
    reg n, d;
    integer i;
    begin
      link_sync;
      for (i = 0; i < cycles; i = i + 1) link_cycle(8'h00, 1'b0, n, d);
    end
  endtask

  // Immediate register write
  task link_reg_write(input [5:0] addr, input [7:0] wdata);
    reg ok;
    begin
      link_sync; link_wait_idle;
      link_cmd_phase(`ULPI_TXCMD_REGW(addr), ok);
      if (ok) link_phase(wdata, ok);
      if (ok) link_stp_cycle; else link_cleanup;
      $display("[%0t] ULPI LINK: REG WRITE [0x%02h] <= 0x%02h%s", $time, addr, wdata, ok ? "" : "  (FAILED)");
    end
  endtask

  // Immediate register read
  task link_reg_read(input [5:0] addr, output [7:0] rdata);
    reg ok;
    begin
      link_sync; link_wait_idle;
      rdata = 8'hxx;
      link_cmd_phase(`ULPI_TXCMD_REGR(addr), ok);
      if (ok) begin
        link_read_data(rdata);
        $display("[%0t] ULPI LINK: REG READ  [0x%02h] => 0x%02h", $time, addr, rdata);
      end else link_cleanup;
    end
  endtask

  // Extended register write (8-bit address)
  task link_ext_reg_write(input [7:0] addr, input [7:0] wdata);
    reg ok;
    begin
      link_sync; link_wait_idle;
      link_cmd_phase(`ULPI_TXCMD_EXT_REGW, ok);
      if (ok) link_phase(addr, ok);
      if (ok) link_phase(wdata, ok);
      if (ok) link_stp_cycle; else link_cleanup;
      $display("[%0t] ULPI LINK: EXT REG WRITE [0x%02h] <= 0x%02h%s", $time, addr, wdata, ok ? "" : "  (FAILED)");
    end
  endtask

  // Extended register read (8-bit address)
  task link_ext_reg_read(input [7:0] addr, output [7:0] rdata);
    reg ok;
    begin
      link_sync; link_wait_idle;
      rdata = 8'hxx;
      link_cmd_phase(`ULPI_TXCMD_EXT_REGR, ok);
      if (ok) link_phase(addr, ok);
      if (ok) begin
        link_read_data(rdata);
        $display("[%0t] ULPI LINK: EXT REG READ  [0x%02h] => 0x%02h", $time, addr, rdata);
      end else link_cleanup;
    end
  endtask

  // Read a register and compare (masked) against an expected value.
  task link_check_reg(input [5:0] addr, input [7:0] expected, input [7:0] mask);
    reg [7:0] rd;
    begin
      link_reg_read(addr, rd);
      if (((rd ^ expected) & mask) !== 8'h00) begin
        err_cnt = err_cnt + 1;
        $display("[%0t] ULPI LINK: FAIL reg 0x%02h = 0x%02h, expected 0x%02h (mask 0x%02h)",
                 $time, addr, rd, expected, mask);
      end else
        $display("[%0t] ULPI LINK: PASS reg 0x%02h = 0x%02h", $time, addr, rd);
    end
  endtask

  // Transmit a USB packet: TXCMD(pid) followed by len bytes from tx_buf[0..len-1].
  // The Link supplies PID-less payload (incl. CRC where applicable); the PHY adds
  // SYNC/PID check bits/bit-stuffing/EOP.  len=0 -> PID-only packet (ACK/NAK/...).
  task link_tx_packet(input [3:0] pid, input integer len);
    reg ok;
    integer i;
    begin
      link_sync; link_wait_idle;
      link_cmd_phase(`ULPI_TXCMD_XMIT(pid), ok);
      i = 0;
      while (ok && i < len) begin
        link_phase(tx_buf[i], ok);
        i = i + 1;
      end
      if (ok) link_stp_cycle; else link_cleanup;
      $display("[%0t] ULPI LINK: TX PACKET pid=0x%01h len=%0d%s", $time, pid, len, ok ? "" : "  (FAILED)");
    end
  endtask

  // Wait for the next completed receive packet (rx_buf/rx_len valid when got=1).
  task link_wait_rx_packet(input integer timeout_cycles, output got);
    integer start, t;
    begin
      start = rx_pkt_cnt; t = 0;
      while (rx_pkt_cnt == start && t < timeout_cycles) begin @(posedge clk); t = t + 1; end
      got = (rx_pkt_cnt != start);
      if (!got) begin
        err_cnt = err_cnt + 1;
        $display("[%0t] ULPI LINK: ERROR timeout waiting for RX packet", $time);
      end
    end
  endtask

  // Wait for the next RXCMD (last_rxcmd updated when got=1).
  task link_wait_rxcmd(input integer timeout_cycles, output got);
    integer start, t;
    begin
      start = rxcmd_cnt; t = 0;
      while (rxcmd_cnt == start && t < timeout_cycles) begin @(posedge clk); t = t + 1; end
      got = (rxcmd_cnt != start);
    end
  endtask

  task link_report;
    begin
      if (err_cnt == 0) $display("[%0t] ULPI LINK: *** PASS (0 errors) ***", $time);
      else              $display("[%0t] ULPI LINK: *** FAIL (%0d errors) ***", $time, err_cnt);
    end
  endtask

endmodule


//=============================================================================
// 3. PHY-side BFM  (testbench = PHY, DUT = Link)
//
//   * generates the 60 MHz clock
//   * contains a reactive responder: it decodes TXCMDs issued by the DUT Link,
//     keeps a register file (immediate + extended), captures transmitted USB
//     packets and handles the register-read turnaround
//   * provides tasks to inject RXCMDs and USB receive packets
//=============================================================================
module ulpi_phy_bfm #(
  parameter real TCQ       = 1.0,
  parameter real CLK_HALF  = 8.333,  // 60 MHz
  parameter      TX_MAX    = 1024,
  parameter      RX_MAX    = 1024
)(
  output reg   clk,
  output reg   dir,
  output reg   nxt,
  inout  [7:0] data,
  input        stp
);

  //---------------------------------------------------------------- clock
  reg clk_en;
  initial begin clk = 1'b0; clk_en = 1'b1; end
  always #(CLK_HALF) if (clk_en) clk = ~clk;   // clk_en=0 emulates a stopped clock

  //---------------------------------------------------------------- bus drive
  reg [7:0] phy_data;
  reg       phy_oe;
  assign data = phy_oe ? phy_data : 8'bz;

  //----------------------------------------------------- user-visible state
  reg [7:0] regfile     [0:63];     // immediate register space
  reg [7:0] ext_regfile [0:255];    // extended register space
  reg [7:0] txcap_buf   [0:TX_MAX-1];   // bytes captured from the last Link transmit
  integer   txcap_len;
  reg [3:0] txcap_pid;
  integer   txcap_cnt;              // completed Link transmits
  integer   reg_wr_cnt, reg_rd_cnt;
  reg [5:0] last_wr_addr;
  reg [7:0] last_wr_data;
  integer   err_cnt;
  event     tx_packet_done;

  reg [7:0] rx_src [0:RX_MAX-1];    // fill before calling phy_send_rx_packet

  // Knobs
  integer   nxt_wait_cycles;        // wait states before accepting a TXCMD
  integer   tx_throttle;            // 0: nxt always 1 during Link data; N: nxt low every Nth cycle
  reg [1:0] phy_linestate;          // reported in RXCMDs
  reg [1:0] phy_vbusstate;
  reg       phy_id;
  reg       phy_alt_int;

  reg       bus_busy;               // PHY owns/is servicing the bus

  integer i_init;
  initial begin
    dir = 1'b0; nxt = 1'b0; phy_data = 8'h00; phy_oe = 1'b0;
    txcap_len = 0; txcap_pid = 4'h0; txcap_cnt = 0; reg_wr_cnt = 0; reg_rd_cnt = 0;
    last_wr_addr = 6'h00; last_wr_data = 8'h00; err_cnt = 0;
    nxt_wait_cycles = 0; tx_throttle = 0;
    phy_linestate = 2'b01; phy_vbusstate = 2'b11; phy_id = 1'b0; phy_alt_int = 1'b0;
    bus_busy = 1'b0;
    for (i_init = 0; i_init < 64;  i_init = i_init + 1) regfile[i_init]     = 8'h00;
    for (i_init = 0; i_init < 256; i_init = i_init + 1) ext_regfile[i_init] = 8'h00;
    // Example power-up values -- adapt to the PHY you are modelling
    regfile[6'h00] = 8'h24;  regfile[6'h01] = 8'h04;   // Vendor ID  (example)
    regfile[6'h02] = 8'h04;  regfile[6'h03] = 8'h00;   // Product ID (example)
    regfile[6'h04] = 8'h41;                            // FuncCtrl reset value
    regfile[6'h0A] = 8'h06;                            // OTGCtrl  reset value
  end

  //------------------------------------------------------------ functions
  // Build an RXCMD byte
  function [7:0] rxcmd_build(input [1:0] ls, input [1:0] vbus, input [1:0] rxev,
                             input id, input alt);
    rxcmd_build = {alt, id, rxev, vbus, ls};
  endfunction

  // Map set/clear register aliases to the base register
  function [5:0] reg_base(input [5:0] a);
    case (a)
      6'h05, 6'h06: reg_base = 6'h04;
      6'h08, 6'h09: reg_base = 6'h07;
      6'h0B, 6'h0C: reg_base = 6'h0A;
      6'h0E, 6'h0F: reg_base = 6'h0D;
      6'h11, 6'h12: reg_base = 6'h10;
      6'h17, 6'h18: reg_base = 6'h16;
      default:      reg_base = a;
    endcase
  endfunction

  function reg_is_set(input [5:0] a);
    reg_is_set = (a == 6'h05) || (a == 6'h08) || (a == 6'h0B) ||
                 (a == 6'h0E) || (a == 6'h11) || (a == 6'h17);
  endfunction

  function reg_is_clr(input [5:0] a);
    reg_is_clr = (a == 6'h06) || (a == 6'h09) || (a == 6'h0C) ||
                 (a == 6'h0F) || (a == 6'h12) || (a == 6'h18);
  endfunction

  //------------------------------------------------------ helper tasks
  task phy_reg_apply(input [5:0] a, input [7:0] v);
    reg [5:0] b;
    begin
      b = reg_base(a);
      if      (reg_is_set(a)) regfile[b] = regfile[b] | v;
      else if (reg_is_clr(a)) regfile[b] = regfile[b] & ~v;
      else                    regfile[b] = v;      // TODO: honour read-only registers
      last_wr_addr = a; last_wr_data = v; reg_wr_cnt = reg_wr_cnt + 1;
      $display("[%0t] ULPI PHY : REG WRITE [0x%02h] <= 0x%02h (now 0x%02h)", $time, a, v, regfile[b]);
    end
  endtask

  // Common tail of a register/extended read: dir=1, turnaround, data, dir=0.
  // Entered at (edge + TCQ) right after the last command byte was accepted.
  task phy_read_return(input [7:0] rd);
    begin
      nxt = 1'b0; dir = 1'b1;           // dir rises: turnaround cycle
      @(posedge clk); #(TCQ);
      phy_data = rd; phy_oe = 1'b1;     // register data (nxt=0)
      @(posedge clk); #(TCQ);
      dir = 1'b0; phy_oe = 1'b0;        // release bus, turnaround back
    end
  endtask

  // Check that the Link terminated a write with STP
  task phy_expect_stp(input [127:0] what);
    begin
      if (stp !== 1'b1) begin
        err_cnt = err_cnt + 1;
        $display("[%0t] ULPI PHY : ERROR expected STP after %0s", $time, what);
      end
    end
  endtask

  // Capture Link data until STP (USB transmit). nxt is already high.
  task phy_capture_tx(input [3:0] pid);
    integer n, cyc;
    reg done, nxt_cur;
    begin
      txcap_pid = pid; n = 0; cyc = 0; done = 1'b0; nxt_cur = 1'b1;
      while (!done) begin
        @(posedge clk);
        if (stp) done = 1'b1;
        else if (nxt_cur) begin
          if (n < TX_MAX) txcap_buf[n] = data;
          n = n + 1;
        end
        cyc = cyc + 1;
        #(TCQ);
        if (done)                nxt_cur = 1'b0;
        else if (tx_throttle==0) nxt_cur = 1'b1;
        else                     nxt_cur = ((cyc % tx_throttle) != 0);
        nxt = nxt_cur;
      end
      txcap_len = n; txcap_cnt = txcap_cnt + 1;
      $display("[%0t] ULPI PHY : TX PACKET captured pid=0x%01h len=%0d", $time, pid, n);
      -> tx_packet_done;
    end
  endtask

  // Service one TXCMD seen on the bus. Entered at the edge the command was first sampled.
  task phy_handle_txcmd;
    reg [7:0] cmd, wd, ea, rd;
    reg [5:0] a;
    begin
      bus_busy = 1'b1;
      cmd = data;
      repeat (nxt_wait_cycles) @(posedge clk);
      #(TCQ) nxt = 1'b1;
      @(posedge clk);                          // command accepted here (nxt=1, data=cmd)
      if (data !== cmd)
        $display("[%0t] ULPI PHY : WARNING TXCMD changed before acceptance (0x%02h -> 0x%02h)", $time, cmd, data);
      a = cmd[5:0];
      case (cmd[7:6])
        2'b01: begin                           // USB transmit
          phy_capture_tx(cmd[3:0]);
        end
        2'b10: begin
          if (a == 6'h2F) begin                // extended register write
            @(posedge clk); ea = data;
            @(posedge clk); wd = data;
            #(TCQ) nxt = 1'b0;
            @(posedge clk); phy_expect_stp("extended register write");
            ext_regfile[ea] = wd; reg_wr_cnt = reg_wr_cnt + 1;
            $display("[%0t] ULPI PHY : EXT REG WRITE [0x%02h] <= 0x%02h", $time, ea, wd);
          end else begin                       // immediate register write
            @(posedge clk); wd = data;         // nxt still high: data byte accepted
            #(TCQ) nxt = 1'b0;
            @(posedge clk); phy_expect_stp("register write");
            phy_reg_apply(a, wd);
          end
        end
        2'b11: begin
          if (a == 6'h2F) begin                // extended register read
            @(posedge clk); ea = data;         // extended address accepted
            rd = ext_regfile[ea]; reg_rd_cnt = reg_rd_cnt + 1;
            #(TCQ);
            phy_read_return(rd);
            $display("[%0t] ULPI PHY : EXT REG READ  [0x%02h] => 0x%02h", $time, ea, rd);
          end else begin                       // immediate register read
            rd = regfile[reg_base(a)]; reg_rd_cnt = reg_rd_cnt + 1;
            #(TCQ);
            phy_read_return(rd);
            $display("[%0t] ULPI PHY : REG READ  [0x%02h] => 0x%02h", $time, a, rd);
          end
        end
        default: ;
      endcase
      nxt = 1'b0;
      bus_busy = 1'b0;
    end
  endtask

  //----------------------------------------------- reactive command monitor
  always @(posedge clk) begin
    if (!dir && !bus_busy && !stp && ((^data) !== 1'bx) && (data[7:6] != 2'b00))
      phy_handle_txcmd;
  end

  //------------------------------------------------------- public tasks
  // Claim the bus for PHY-initiated traffic (RXCMD / USB receive).
  // NOTE: don't start PHY traffic in the same cycle the Link starts a command.
  task phy_acquire;
    begin
      @(posedge clk);
      while (bus_busy) @(posedge clk);
      bus_busy = 1'b1;
      #(TCQ);
    end
  endtask

  task phy_release;
    begin bus_busy = 1'b0; end
  endtask

  // Send one RXCMD (dir=1, turnaround, RXCMD with nxt=0, dir=0)
  task phy_send_rxcmd(input [7:0] rxcmd);
    begin
      phy_acquire;
      dir = 1'b1; nxt = 1'b0;
      @(posedge clk); #(TCQ);
      phy_data = rxcmd; phy_oe = 1'b1;
      @(posedge clk); #(TCQ);
      dir = 1'b0; phy_oe = 1'b0;
      phy_release;
      $display("[%0t] ULPI PHY : RXCMD 0x%02h", $time, rxcmd);
    end
  endtask

  // Update LineState/VbusState/ID/alt_int and report via RXCMD (RxEvent=idle)
  task phy_update_status(input [1:0] ls, input [1:0] vbus, input id, input alt);
    begin
      phy_linestate = ls; phy_vbusstate = vbus; phy_id = id; phy_alt_int = alt;
      phy_send_rxcmd(rxcmd_build(ls, vbus, 2'b00, id, alt));
    end
  endtask

  // Send a USB receive packet from rx_src[0..len-1].
  //   implicit=1 : dir and nxt asserted together (RxActive implied)
  //   implicit=0 : explicit RXCMD with RxActive=1 before the data
  //   err=1      : insert an RXCMD with RxError before the end of packet
  task phy_send_rx_packet(input integer len, input implicit, input err);
    integer i;
    begin
      phy_acquire;
      dir = 1'b1; nxt = implicit;                 // turnaround cycle
      @(posedge clk); #(TCQ);
      if (!implicit) begin
        phy_data = rxcmd_build(phy_linestate, phy_vbusstate, 2'b01, phy_id, phy_alt_int);
        phy_oe = 1'b1; nxt = 1'b0;
        @(posedge clk); #(TCQ);
      end
      for (i = 0; i < len; i = i + 1) begin
        phy_data = rx_src[i]; phy_oe = 1'b1; nxt = 1'b1;
        @(posedge clk); #(TCQ);
      end
      if (err) begin
        phy_data = rxcmd_build(phy_linestate, phy_vbusstate, 2'b11, phy_id, phy_alt_int);
        nxt = 1'b0;
        @(posedge clk); #(TCQ);
      end
      phy_data = rxcmd_build(phy_linestate, phy_vbusstate, 2'b00, phy_id, phy_alt_int);
      nxt = 1'b0;                                  // RxActive=0 RXCMD
      @(posedge clk); #(TCQ);
      dir = 1'b0; phy_oe = 1'b0;
      phy_release;
      $display("[%0t] ULPI PHY : RX PACKET sent len=%0d%s%s", $time, len,
               implicit ? " (implicit)" : "", err ? " (RxError)" : "");
    end
  endtask

  // Stop / restart the 60 MHz clock (low-power / suspend tests)
  task phy_clock_stop;  begin @(negedge clk); clk_en = 1'b0; end endtask
  task phy_clock_start; begin clk_en = 1'b1; end endtask

endmodule


//=============================================================================
// 4. Demo: Link BFM <-> PHY BFM back to back (self-test of this file).
//    Compile with  +define+ULPI_BFM_DEMO  (e.g. iverilog -DULPI_BFM_DEMO ...).
//    For your own testbench: delete this and instantiate ONE BFM against your DUT.
//=============================================================================
`ifdef ULPI_BFM_DEMO
module ulpi_bfm_demo;
  wire       clk, dir, nxt, stp;
  wire [7:0] data;

  ulpi_phy_bfm  u_phy  (.clk(clk), .dir(dir), .nxt(nxt), .data(data), .stp(stp));
  ulpi_link_bfm u_link (.clk(clk), .dir(dir), .nxt(nxt), .data(data), .stp(stp));

  reg [7:0] rd;
  reg       got;
  integer   i;

  initial begin
    #200;

    // --- register access -------------------------------------------------
    u_link.link_check_reg(`ULPI_REG_VENDOR_ID_LOW, 8'h24, 8'hFF);
    u_link.link_reg_write(`ULPI_REG_SCRATCH, 8'hA5);
    u_link.link_check_reg(`ULPI_REG_SCRATCH, 8'hA5, 8'hFF);
    u_link.link_reg_write(`ULPI_REG_SCRATCH_SET, 8'h0F);
    u_link.link_reg_write(`ULPI_REG_SCRATCH_CLR, 8'hA0);
    u_link.link_check_reg(`ULPI_REG_SCRATCH, 8'h0F, 8'hFF);
    u_link.link_ext_reg_write(8'h80, 8'h3C);
    u_link.link_ext_reg_read (8'h80, rd);
    if (rd !== 8'h3C) begin u_link.err_cnt = u_link.err_cnt + 1; $display("FAIL ext reg"); end

    // --- Link -> PHY USB transmit (OUT token: addr/endp/crc5 bytes) -------
    u_link.tx_buf[0] = 8'h01;
    u_link.tx_buf[1] = 8'h08;
    u_link.link_tx_packet(`ULPI_PID_OUT, 2);
    if (u_phy.txcap_len !== 2 || u_phy.txcap_pid !== `ULPI_PID_OUT ||
        u_phy.txcap_buf[0] !== 8'h01 || u_phy.txcap_buf[1] !== 8'h08) begin
      u_link.err_cnt = u_link.err_cnt + 1; $display("FAIL tx packet");
    end
    // PID-only packet (ACK) with PHY inserting nxt wait states
    u_phy.tx_throttle = 3;
    u_link.link_tx_packet(`ULPI_PID_ACK, 0);
    u_phy.tx_throttle = 0;

    // --- PHY -> Link USB receive (ACK handshake byte 0xD2) ----------------
    u_phy.rx_src[0] = 8'hD2;
    fork
      u_phy.phy_send_rx_packet(1, 1'b0, 1'b0);
      u_link.link_wait_rx_packet(100, got);
    join
    if (!got || u_link.rx_len !== 1 || u_link.rx_buf[0] !== 8'hD2) begin
      u_link.err_cnt = u_link.err_cnt + 1; $display("FAIL rx packet");
    end

    // implicit-RxActive packet with 4 bytes
    for (i = 0; i < 4; i = i + 1) u_phy.rx_src[i] = 8'h10 + i;
    fork
      u_phy.phy_send_rx_packet(4, 1'b1, 1'b0);
      u_link.link_wait_rx_packet(100, got);
    join
    if (!got || u_link.rx_len !== 4 || u_link.rx_buf[3] !== 8'h13) begin
      u_link.err_cnt = u_link.err_cnt + 1; $display("FAIL implicit rx packet");
    end

    // --- PHY status change via RXCMD ---------------------------------------
    fork
      u_phy.phy_update_status(2'b10, 2'b11, 1'b0, 1'b0);   // LineState = 10
      u_link.link_wait_rxcmd(100, got);
    join
    if (!got || u_link.rxcmd_linestate(u_link.last_rxcmd) !== 2'b10) begin
      u_link.err_cnt = u_link.err_cnt + 1; $display("FAIL rxcmd");
    end

    u_link.link_idle(10);
    u_link.link_report;
    $finish;
  end

  initial begin #200000; $display("TIMEOUT"); $finish; end
endmodule
`endif
