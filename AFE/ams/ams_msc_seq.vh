//-----------------------------------------------------------------------------
// ams_msc_seq.vh - host enumeration of a full-speed USB mass-storage device
//                  (Bulk-Only Transport, SCSI) through the PHY's ULPI
//                  interface: Link model, sequence and checks
//
// Included inside the top module of
//   * AFE/ams/tb_ams_msc.vams   (Spectre AMS, Verilog-A AFE + Verilog-A device)
//   * tb_ams_msc_shadow.v       (Icarus, afe_*_bm.v + fs_msc_bm.v)
// Adapted from Tests/USB mass-storage device/tb_usb3300_fs_msc_enum.vams
// (same host tasks, enumeration and BOT steps); the Link is ulpi_link_bfm of
// Tests/USB ULPI Mouse/ulpi_tb_template.v, which the top includes at file
// level.  Differences from the template: this repository's PHY (Product ID
// 0007h, USB3320) in place of the USB3300 model; bus reset by the host PHY's
// 45 Ohm terminations (as in ams_mouse_seq.vh) instead of OpMode 10 + NOPID
// zero bytes; line levels checked through `AMS_VDP / `AMS_VDM; scaled
// times shorter; result line TEST PASSED / TEST FAILED.
//
// The top provides:
//   wire       ulpi_clk, ulpi_dir, ulpi_nxt, ulpi_stp;  wire [7:0] ulpi_data;
//   reg        por_n, resetb;          (both start at 0)
//   `AMS_VDP / `AMS_VDM               line voltages in volts (real)
//
// Sequence (the testbench plays the USB host / Link, the PHY is ams_ulpi_phy):
//   1. Power-on, RESETB; Vendor / Product ID (0424h / 0007h), scratch register.
//   2. Host mode: OTG Control 66h (DpPulldown, DmPulldown, DrvVbus,
//      DrvVbusExternal), Function Control 45h (FS host, TermSelect 1); the
//      Debug register's LineState goes 00 -> 01 (J) when the device connects
//      its D+ pull-up (full-speed); line: DP > 2.7 V, DM < 0.3 V.
//   3. Bus reset as the USB3320 does it: Function Control 50h (XcvrSelect 00,
//      TermSelect 0, OpMode 10) switches the 45 Ohm terminations on, which pull
//      the line to SE0 (checked on the line); then back to 45h.  The device
//      model reports "USB bus reset detected".
//   4. Enumeration: GET_DESCRIPTOR(device, 8) at address 0, SET_ADDRESS(7),
//      GET_DESCRIPTOR(device, 18), GET_DESCRIPTOR(configuration, 9 / 32),
//      SET_CONFIGURATION(1), GET_MAX_LUN: every SETUP ACKed, data-stage CRC16
//      and DATA toggles checked, descriptor fields checked against the model
//      (class 08h Mass Storage, subclass 06h SCSI, protocol 50h Bulk-Only,
//      EP1 OUT / EP2 IN bulk, 64 bytes).
//   5. Bulk-Only Transport: TEST UNIT READY, INQUIRY (36 B), READ CAPACITY(10)
//      (8 B), READ(10) of LBA 0 (512 B = 8 full-speed packets): CBW on EP1 OUT,
//      data on EP2 IN, CSW (signature, tag, status) on EP2 IN; bulk DATA
//      toggles and CRC16 of every IN packet checked, the data checked against
//      the model.
//   Every packet goes Link -> ULPI TXCMD -> PHY TX path -> AFE -> line ->
//   device, and back line -> AFE -> PHY RX path -> RXCMD / ULPI data -> Link.
//
// Times are scaled against USB 2.0 so the run stays short (the device model
// detects a reset after 2.5 us of SE0 and has no suspend, so SOFs are sent
// only once per transfer): debounce 10 us (100 ms), reset 10 us (10 ms),
// recovery 10 us (10 ms), SET_ADDRESS recovery 10 us (2 ms).  Simulated time
// about 1.5 ms.
//
// Result line: TEST PASSED / TEST FAILED: <n> error(s) / TEST FAILED: timeout.
//-----------------------------------------------------------------------------

    // ------------------------------------------------------------ parameters
    localparam [6:0] DEV_ADDR     = 7'd7;
    localparam integer RX_TO       = 60000;     // RX wait timeout [60 MHz clocks] (1 ms)
    localparam integer T_DEBOUNCE  = 10_000;    // ns, scaled (spec: 100 ms)
    localparam integer T_RESET     = 10_000;    // ns, scaled (spec: >= 10 ms SE0)
    localparam integer T_RECOVERY  = 10_000;    // ns, scaled (spec: 10 ms reset recovery)
    localparam integer T_SETADDR   = 10_000;    // ns, scaled (spec: 2 ms SET_ADDRESS recovery)
    localparam [7:0]   OTG_CTRL_VAL = 8'h66;    // DpPulldown | DmPulldown | DrvVbus | DrvVbusExternal

    localparam [7:0] FUNC_FS_HOST  = 8'h45;     // SuspendM=1, OpMode=00, TermSelect=1, XcvrSelect=01 (FS)
    localparam [7:0] FUNC_HS_RESET = 8'h50;     // SuspendM=1, OpMode=10, TermSelect=0, XcvrSelect=00:
                                                // 45 Ohm terminations on -> SE0 (USB3320 host reset)

    // ------------------------------------------------------------ Link-side ULPI BFM
    // A full-speed byte takes ~667 ns = 40 clocks.
    ulpi_link_bfm #(.NXT_TIMEOUT(4000)) u_link (
        .clk(ulpi_clk), .dir(ulpi_dir), .nxt(ulpi_nxt), .data(ulpi_data), .stp(ulpi_stp));

    // ============================================================ host-side state
    reg [7:0] ctl_buf  [0:255];    // control-read data
    reg [7:0] out_buf  [0:63];     // bulk OUT payload (filled by the caller)
    reg [7:0] bulk_buf [0:1023];   // bulk IN data (data stage at 0.., CSW at 600..)
    reg [7:0] cdb      [0:15];     // SCSI command block for host_msc_cmd
    integer   ctl_n, bulk_n;
    integer   errors, checks;
    reg [3:0] rx_pid;              // last received packet
    integer   rx_nbytes;           // bytes incl. PID and CRC
    reg       rx_ok;
    reg       bulk_out_tog, bulk_in_tog;
    integer   max_pkt0;
    reg [10:0] frame_num;

    localparam [3:0] PID_OUT   = `ULPI_PID_OUT;
    localparam [3:0] PID_IN    = `ULPI_PID_IN;
    localparam [3:0] PID_SOF   = `ULPI_PID_SOF;
    localparam [3:0] PID_SETUP = `ULPI_PID_SETUP;
    localparam [3:0] PID_DATA0 = `ULPI_PID_DATA0;
    localparam [3:0] PID_DATA1 = `ULPI_PID_DATA1;
    localparam [3:0] PID_ACK   = `ULPI_PID_ACK;
    localparam [3:0] PID_NAK   = `ULPI_PID_NAK;
    localparam [3:0] PID_STALL = `ULPI_PID_STALL;

    // ------------------------------------------------------------ check helper
    task check(input cond, input [8*64-1:0] msg);
        begin
            checks = checks + 1;
            if (!cond) begin
                errors = errors + 1;
                $display("[%0t] TB ERROR: %0s", $time, msg);
            end else
                $display("[%0t] TB OK   : %0s", $time, msg);
        end
    endtask

    // line levels (volts) at this moment
    task check_line(input real dp_lo, input real dp_hi, input real dm_lo, input real dm_hi,
                    input [8*64-1:0] msg);
        real vp, vm;
        begin
            vp = `AMS_VDP; vm = `AMS_VDM;
            $display("[%0t] line: DP = %0.3f V, DM = %0.3f V", $time, vp, vm);
            check(vp >= dp_lo && vp <= dp_hi && vm >= dm_lo && vm <= dm_hi, msg);
        end
    endtask

    // ------------------------------------------------------------ CRC helpers
    // CRC16 over u_link.tx_buf[0..len-1]
    task crc16_tx(input integer len, output [15:0] crc);
        integer i, j; reg [15:0] c; reg [7:0] b;
        begin
            c = 16'hFFFF;
            for (i = 0; i < len; i = i + 1) begin
                b = u_link.tx_buf[i];
                for (j = 0; j < 8; j = j + 1)
                    if (c[0] ^ b[j]) c = (c >> 1) ^ 16'hA001; else c = c >> 1;
            end
            crc = ~c;
        end
    endtask

    // CRC16 over u_link.rx_buf[first .. first+len-1]
    task crc16_rx(input integer first, input integer len, output [15:0] crc);
        integer i, j; reg [15:0] c; reg [7:0] b;
        begin
            c = 16'hFFFF;
            for (i = first; i < first + len; i = i + 1) begin
                b = u_link.rx_buf[i];
                for (j = 0; j < 8; j = j + 1)
                    if (c[0] ^ b[j]) c = (c >> 1) ^ 16'hA001; else c = c >> 1;
            end
            crc = ~c;
        end
    endtask

    // ------------------------------------------------------------ packet-level host tasks
    // Token packet: 7-bit address + 4-bit endpoint (for SOF the 11 bits are the frame number)
    task host_send_token(input [3:0] pid, input [6:0] addr, input [3:0] ep);
        reg [10:0] d; reg [4:0] c, cr; integer i;
        begin
            d = {ep, addr};
            c = 5'h1F;
            for (i = 0; i < 11; i = i + 1)
                if (c[4] ^ d[i]) c = {c[3:0], 1'b0} ^ 5'h05; else c = {c[3:0], 1'b0};
            c  = ~c;
            cr = {c[0], c[1], c[2], c[3], c[4]};          // transmitted MSB first
            u_link.tx_buf[0] = {ep[0], addr};
            u_link.tx_buf[1] = {cr, ep[3:1]};
            u_link.link_tx_packet(pid, 2);
        end
    endtask

    // Start-of-frame (full speed: one per 1 ms frame; sent once per transfer here)
    task host_sof;
        begin
            host_send_token(PID_SOF, frame_num[6:0], frame_num[10:7]);
            frame_num = frame_num + 11'd1;
        end
    endtask

    // DATA packet: payload already in u_link.tx_buf[0..len-1]; CRC16 appended here
    task host_send_data(input [3:0] pid, input integer len);
        reg [15:0] crc;
        begin
            crc16_tx(len, crc);
            u_link.tx_buf[len]     = crc[7:0];
            u_link.tx_buf[len + 1] = crc[15:8];
            u_link.link_tx_packet(pid, len + 2);
        end
    endtask

    task host_send_handshake(input [3:0] pid);
        begin u_link.link_tx_packet(pid, 0); end
    endtask

    // Wait for one packet from the device; fills rx_pid / rx_nbytes / rx_ok
    task host_wait_pkt(output ok);
        reg got; reg [7:0] b0;
        begin
            u_link.link_wait_rx_packet(RX_TO, got);
            rx_nbytes = u_link.rx_len;
            b0        = u_link.rx_buf[0];
            rx_pid    = b0[3:0];
            rx_ok     = got && (b0[7:4] == ~b0[3:0]) && !u_link.rx_err_seen;
            ok        = rx_ok;
        end
    endtask

    // ------------------------------------------------------------ control transfers
    // SETUP stage: SOF, token + DATA0(8 bytes) and ACK check
    task host_setup(input [6:0] addr, input [7:0] bm, input [7:0] br,
                    input [15:0] wv, input [15:0] wi, input [15:0] wl);
        reg ok;
        begin
            host_sof;
            host_send_token(PID_SETUP, addr, 4'd0);
            u_link.tx_buf[0] = bm;        u_link.tx_buf[1] = br;
            u_link.tx_buf[2] = wv[7:0];   u_link.tx_buf[3] = wv[15:8];
            u_link.tx_buf[4] = wi[7:0];   u_link.tx_buf[5] = wi[15:8];
            u_link.tx_buf[6] = wl[7:0];   u_link.tx_buf[7] = wl[15:8];
            host_send_data(PID_DATA0, 8);
            host_wait_pkt(ok);
            check(ok && rx_pid == PID_ACK, "SETUP stage ACKed");
        end
    endtask

    // Control read: SETUP + IN data stage (max_pkt0-byte packets) + OUT status stage
    task host_ctrl_read(input [6:0] addr, input [7:0] bm, input [7:0] br,
                        input [15:0] wv, input [15:0] wi, input [15:0] wl);
        reg ok, done, tog; reg [15:0] crc; integer tries, n, i;
        begin
            host_setup(addr, bm, br, wv, wi, wl);
            ctl_n = 0; tog = 1'b1; done = 1'b0; tries = 0;
            while (!done && tries < 100) begin
                host_send_token(PID_IN, addr, 4'd0);
                host_wait_pkt(ok);
                if (!ok) begin
                    check(1'b0, "data-stage packet received");
                    done = 1'b1;
                end else if (rx_pid == PID_NAK) begin
                    tries = tries + 1;
                end else if (rx_pid == PID_DATA0 || rx_pid == PID_DATA1) begin
                    n = rx_nbytes - 3;                               // minus PID and CRC16
                    crc16_rx(1, n, crc);
                    check({u_link.rx_buf[1 + n + 1], u_link.rx_buf[1 + n]} == crc, "data-stage CRC16");
                    check((rx_pid == PID_DATA1) == tog,                "data-stage DATA toggle");
                    for (i = 0; i < n; i = i + 1) ctl_buf[ctl_n + i] = u_link.rx_buf[1 + i];
                    ctl_n = ctl_n + n;
                    host_send_handshake(PID_ACK);
                    tog = ~tog;
                    if (n < max_pkt0 || ctl_n >= wl) done = 1'b1;
                end else begin
                    check(1'b0, "unexpected PID in data stage (STALL?)");
                    done = 1'b1;
                end
            end
            // status stage: zero-length DATA1 OUT
            host_send_token(PID_OUT, addr, 4'd0);
            host_send_data(PID_DATA1, 0);
            host_wait_pkt(ok);
            check(ok && rx_pid == PID_ACK, "status stage (OUT ZLP) ACKed");
        end
    endtask

    // Control transfer without data stage: SETUP + IN status (zero-length DATA1) + ACK
    task host_ctrl_nodata(input [6:0] addr, input [7:0] bm, input [7:0] br,
                          input [15:0] wv, input [15:0] wi);
        reg ok; integer tries, done;
        begin
            host_setup(addr, bm, br, wv, wi, 16'd0);
            done = 0; tries = 0;
            while (!done && tries < 100) begin
                host_send_token(PID_IN, addr, 4'd0);
                host_wait_pkt(ok);
                if (ok && rx_pid == PID_NAK) tries = tries + 1;
                else begin
                    check(ok && rx_pid == PID_DATA1 && rx_nbytes == 3, "status stage (IN ZLP) received");
                    if (ok) host_send_handshake(PID_ACK);
                    done = 1;
                end
            end
        end
    endtask

    // ------------------------------------------------------------ bulk transfers
    // Bulk OUT of len bytes from out_buf[0..len-1] (retries on NAK)
    task host_bulk_out(input [6:0] addr, input [3:0] ep, input integer len);
        reg ok, done; integer tries, i;
        begin
            done = 1'b0; tries = 0;
            while (!done && tries < 100) begin
                host_send_token(PID_OUT, addr, ep);
                for (i = 0; i < len; i = i + 1) u_link.tx_buf[i] = out_buf[i];   // after the token (tx_buf is shared)
                host_send_data(bulk_out_tog ? PID_DATA1 : PID_DATA0, len);
                host_wait_pkt(ok);
                if (ok && rx_pid == PID_ACK) begin
                    bulk_out_tog = ~bulk_out_tog; done = 1'b1;
                end else if (ok && rx_pid == PID_NAK) begin
                    tries = tries + 1;
                end else begin
                    check(1'b0, "bulk OUT ACKed");
                    done = 1'b1;
                end
            end
        end
    endtask

    // Bulk IN: up to maxlen bytes into bulk_buf[base ..]; ends on a short packet or maxlen bytes
    task host_bulk_in(input [6:0] addr, input [3:0] ep, input integer maxlen, input integer base);
        reg ok, done; reg [15:0] crc; integer tries, n, i;
        begin
            bulk_n = 0; done = 1'b0; tries = 0;
            while (!done && tries < 300) begin
                host_send_token(PID_IN, addr, ep);
                host_wait_pkt(ok);
                if (ok && rx_pid == PID_NAK) begin
                    tries = tries + 1;
                    #(2_000);
                end else if (ok && (rx_pid == PID_DATA0 || rx_pid == PID_DATA1)) begin
                    n = rx_nbytes - 3;
                    crc16_rx(1, n, crc);
                    check({u_link.rx_buf[1 + n + 1], u_link.rx_buf[1 + n]} == crc, "bulk IN CRC16");
                    check((rx_pid == PID_DATA1) == bulk_in_tog,                    "bulk IN DATA toggle");
                    for (i = 0; i < n; i = i + 1) bulk_buf[base + bulk_n + i] = u_link.rx_buf[1 + i];
                    bulk_n = bulk_n + n;
                    host_send_handshake(PID_ACK);
                    bulk_in_tog = ~bulk_in_tog;
                    if (n < 64 || bulk_n >= maxlen) done = 1'b1;
                end else begin
                    check(1'b0, "valid bulk IN packet or NAK");
                    done = 1'b1;
                end
            end
        end
    endtask

    // One Bulk-Only-Transport command: CBW (OUT) -> data stage (IN, if xlen>0) -> CSW (IN).
    // The SCSI CDB must be loaded in cdb[0..15] first.  Data lands in bulk_buf[0..], CSW in bulk_buf[600..].
    task host_msc_cmd(input [6:0] addr, input integer cblen, input integer xlen, input [31:0] tag);
        reg [31:0] x32; integer i;
        begin
            host_sof;
            x32 = xlen;
            out_buf[0] = 8'h55; out_buf[1] = 8'h53; out_buf[2] = 8'h42; out_buf[3] = 8'h43;   // "USBC"
            out_buf[4] = tag[7:0];  out_buf[5] = tag[15:8];  out_buf[6] = tag[23:16];  out_buf[7] = tag[31:24];
            out_buf[8] = x32[7:0];  out_buf[9] = x32[15:8];  out_buf[10] = x32[23:16]; out_buf[11] = x32[31:24];
            out_buf[12] = (xlen > 0) ? 8'h80 : 8'h00;       // direction: device-to-host
            out_buf[13] = 8'h00;                            // LUN 0
            out_buf[14] = cblen;
            for (i = 0; i < 16; i = i + 1) out_buf[15 + i] = cdb[i];
            host_bulk_out(addr, 4'd1, 31);                  // CBW

            if (xlen > 0) begin
                host_bulk_in(addr, 4'd2, xlen, 0);            // data stage
                check(bulk_n == xlen, "data stage length");
            end

            host_bulk_in(addr, 4'd2, 13, 600);              // CSW
            check(bulk_n == 13, "CSW length = 13");
            check({bulk_buf[603], bulk_buf[602], bulk_buf[601], bulk_buf[600]} == 32'h53425355, "CSW signature 'USBS'");
            check({bulk_buf[607], bulk_buf[606], bulk_buf[605], bulk_buf[604]} == tag,          "CSW tag matches CBW tag");
            check({bulk_buf[611], bulk_buf[610], bulk_buf[609], bulk_buf[608]} == 32'd0,        "CSW data residue = 0");
            check(bulk_buf[612] == 8'h00,                                                       "CSW status = passed");
        end
    endtask

    task cdb_clear;
        integer i;
        begin for (i = 0; i < 16; i = i + 1) cdb[i] = 8'h00; end
    endtask

    // ------------------------------------------------------------ port-level tasks
    // Wait for the device attach; returns 1 for low-speed (idle D- high), 2 for full-speed (idle D+ high)
    task host_wait_attach(output integer speed);
        reg [7:0] r; integer n;
        begin
            speed = 0; n = 0;
            while (speed == 0 && n < 2000) begin
                u_link.link_reg_read(`ULPI_REG_DEBUG, r);          // Debug register [1:0] = LineState
                if (r[1:0] == 2'b10)      speed = 1;
                else if (r[1:0] == 2'b01) speed = 2;
                else #(2_000);
                n = n + 1;
            end
        end
    endtask

    // Bus reset: the 45 Ohm HS terminations of the host PHY pull both wires to
    // SE0 (Function Control: XcvrSelect 00, TermSelect 0, OpMode 10), as the
    // USB3320 / ULPI host does it; then back to FS host.
    task host_bus_reset;
        reg [7:0] r;
        begin
            u_link.link_reg_write(`ULPI_REG_FUNC_CTRL, FUNC_HS_RESET);
            #(T_RESET / 2);
            check_line(-0.1, 0.3, -0.1, 0.3, "line SE0 during reset");
            #(T_RESET / 2);
            u_link.link_reg_write(`ULPI_REG_FUNC_CTRL, FUNC_FS_HOST);
            #(T_RECOVERY);
            u_link.link_reg_read(`ULPI_REG_DEBUG, r);
            check(r[1:0] == 2'b01, "LineState J (FS) after reset");
            check_line(2.7, 3.4, -0.1, 0.3, "line FS idle (J) after reset");
        end
    endtask

    // ============================================================ main sequence
    integer speed, wtotal, i;
    reg [7:0] rd;

    initial begin
        errors = 0; checks = 0; ctl_n = 0; bulk_n = 0; max_pkt0 = 8;
        bulk_out_tog = 1'b0; bulk_in_tog = 1'b0; frame_num = 11'd0;

        // ---- 1. power-up and PHY identification -----------------------------------
        #(100);    por_n  = 1'b1;
        #(1_000);  resetb = 1'b1;
        repeat (200) @(posedge ulpi_clk);
        $display("1. PHY identification");
        u_link.link_check_reg(`ULPI_REG_VENDOR_ID_LOW,  8'h24, 8'hFF);   // Microchip 0x0424
        u_link.link_check_reg(`ULPI_REG_VENDOR_ID_HIGH, 8'h04, 8'hFF);
        u_link.link_check_reg(`ULPI_REG_PRODUCT_ID_LOW, 8'h07, 8'hFF);   // USB3320 = 0x0007
        u_link.link_check_reg(`ULPI_REG_PRODUCT_ID_HIGH,8'h00, 8'hFF);
        u_link.link_reg_write(`ULPI_REG_SCRATCH, 8'hA5);
        u_link.link_check_reg(`ULPI_REG_SCRATCH, 8'hA5, 8'hFF);

        // ---- 2. host configuration, wait for attach --------------------------------
        $display("2. host mode, attach");
        u_link.link_reg_write(`ULPI_REG_OTG_CTRL,  OTG_CTRL_VAL);        // pull-downs on, drive VBUS
        u_link.link_reg_write(`ULPI_REG_FUNC_CTRL, FUNC_FS_HOST);        // full-speed host
        u_link.link_reg_read(`ULPI_REG_DEBUG, rd);
        check(rd[1:0] == 2'b00, "LineState SE0 before attach");
        host_wait_attach(speed);
        check(speed == 2, "full-speed device attached");
        #(T_DEBOUNCE);                                                   // attach debounce (scaled)
        u_link.link_reg_read(`ULPI_REG_DEBUG, rd);
        check(rd[1:0] == 2'b01, "attach stable after debounce (J state)");
        check_line(2.7, 3.4, -0.1, 0.3, "line: DP pulled up, DM low");

        // ---- 3. bus reset ----------------------------------------------------------------
        $display("3. bus reset");
        host_bus_reset;

        // ---- 4. first 8 bytes of the device descriptor at address 0 ---------------------
        $display("4. GET_DESCRIPTOR(device, 8) at address 0");
        host_ctrl_read(7'd0, 8'h80, 8'h06, 16'h0100, 16'h0000, 16'd8);
        check(ctl_n == 8,               "device descriptor: 8 bytes");
        check(ctl_buf[1] == 8'h01,      "descriptor type = DEVICE");
        max_pkt0 = ctl_buf[7];
        check(max_pkt0 == 64,           "bMaxPacketSize0 = 64 (full-speed)");

        // ---- 5. SET_ADDRESS ------------------------------------------------------------------
        $display("5. SET_ADDRESS(%0d)", DEV_ADDR);
        host_ctrl_nodata(7'd0, 8'h00, 8'h05, {9'd0, DEV_ADDR}, 16'h0000);
        #(T_SETADDR);

        // ---- 6. full device descriptor at the new address -------------------------------------
        $display("6. GET_DESCRIPTOR(device, 18)");
        host_ctrl_read(DEV_ADDR, 8'h80, 8'h06, 16'h0100, 16'h0000, 16'd18);
        check(ctl_n == 18,                              "device descriptor: 18 bytes");
        check({ctl_buf[3], ctl_buf[2]}   == 16'h0110,   "bcdUSB = 1.10");
        check({ctl_buf[9], ctl_buf[8]}   == 16'h1234,   "idVendor  = 0x1234");
        check({ctl_buf[11], ctl_buf[10]} == 16'h5680,   "idProduct = 0x5680");
        check(ctl_buf[17] == 8'h01,                     "bNumConfigurations = 1");

        // ---- 7. configuration descriptor (header, then full) ----------------------------------
        $display("7. GET_DESCRIPTOR(configuration, 9 / 32)");
        host_ctrl_read(DEV_ADDR, 8'h80, 8'h06, 16'h0200, 16'h0000, 16'd9);
        wtotal = {ctl_buf[3], ctl_buf[2]};
        check(wtotal == 32, "wTotalLength = 32");
        host_ctrl_read(DEV_ADDR, 8'h80, 8'h06, 16'h0200, 16'h0000, wtotal);
        check(ctl_n == 32,                "configuration descriptor: 32 bytes");
        check(ctl_buf[13] == 8'h02,       "interface: 2 endpoints");
        check(ctl_buf[14] == 8'h08,       "interface class = Mass Storage");
        check(ctl_buf[15] == 8'h06,       "interface subclass = SCSI transparent");
        check(ctl_buf[16] == 8'h50,       "interface protocol = Bulk-Only");
        check(ctl_buf[20] == 8'h01 && ctl_buf[21] == 8'h02, "endpoint 1 OUT, bulk");
        check(ctl_buf[27] == 8'h82 && ctl_buf[28] == 8'h02, "endpoint 2 IN, bulk");
        check(ctl_buf[22] == 8'd64 && ctl_buf[29] == 8'd64, "bulk max packet = 64");

        // ---- 8. SET_CONFIGURATION, GET_MAX_LUN ----------------------------------------------------
        $display("8. SET_CONFIGURATION, GET_MAX_LUN");
        host_ctrl_nodata(DEV_ADDR, 8'h00, 8'h09, {8'd0, ctl_buf[5]}, 16'h0000);
        bulk_out_tog = 1'b0; bulk_in_tog = 1'b0;                          // toggles reset by SET_CONFIGURATION
        host_ctrl_read(DEV_ADDR, 8'hA1, 8'hFE, 16'h0000, 16'h0000, 16'd1);
        check(ctl_n == 1 && ctl_buf[0] == 8'h00, "GET_MAX_LUN = 0");

        // ---- 9. Bulk-Only Transport / SCSI --------------------------------------------------------
        $display("9. BOT: TEST UNIT READY");
        cdb_clear; cdb[0] = 8'h00;
        host_msc_cmd(DEV_ADDR, 6, 0, 32'hA0000001);

        $display("9. BOT: INQUIRY");
        cdb_clear; cdb[0] = 8'h12; cdb[4] = 8'd36;
        host_msc_cmd(DEV_ADDR, 6, 36, 32'hA0000002);
        check(bulk_buf[0] == 8'h00,                                                    "INQUIRY: direct-access device");
        check(bulk_buf[1] == 8'h80,                                                    "INQUIRY: removable medium");
        check({bulk_buf[8], bulk_buf[9], bulk_buf[10], bulk_buf[11]} == 32'h41434D45,  "INQUIRY: vendor 'ACME'");
        check({bulk_buf[16], bulk_buf[17]} == 16'h5641,                                "INQUIRY: product 'VA'");
        check({bulk_buf[32], bulk_buf[33], bulk_buf[34], bulk_buf[35]} == 32'h312E3030, "INQUIRY: revision '1.00'");

        $display("9. BOT: READ CAPACITY(10)");
        cdb_clear; cdb[0] = 8'h25;
        host_msc_cmd(DEV_ADDR, 10, 8, 32'hA0000003);
        check({bulk_buf[0], bulk_buf[1], bulk_buf[2], bulk_buf[3]} == 32'h0000FFFF,    "READ CAPACITY: last LBA = 0xFFFF");
        check({bulk_buf[4], bulk_buf[5], bulk_buf[6], bulk_buf[7]} == 32'h00000200,    "READ CAPACITY: block size = 512");

        $display("9. BOT: READ(10) LBA 0, 1 block");
        cdb_clear; cdb[0] = 8'h28; cdb[8] = 8'd1;
        host_msc_cmd(DEV_ADDR, 10, 512, 32'hA0000004);
        begin : rd_pattern
            integer bad;
            bad = 0;
            for (i = 0; i < 510; i = i + 1) if (bulk_buf[i] !== i[7:0]) bad = bad + 1;
            check(bad == 0,                                     "READ(10): data pattern bytes 0..509");
        end
        check(bulk_buf[510] == 8'h55 && bulk_buf[511] == 8'hAA, "READ(10): boot signature 55 AA");

        // ---- 10. verdict ----------------------------------------------------------------------------
        errors = errors + u_link.err_cnt;
        $display("%0d checks, %0d Link BFM errors, %0d RXCMDs, %0d packets received, %0d TX CMDs retried",
                 checks, u_link.err_cnt, u_link.rxcmd_cnt, u_link.rx_pkt_cnt, u_link.cmd_retry_cnt);
        if (errors == 0) $display("TEST PASSED");
        else             $display("TEST FAILED: %0d error(s)", errors);
        $finish;
    end

    // watchdog
    initial begin
        #(20_000_000);                                  // 20 ms of simulated time
        $display("TEST FAILED: timeout");
        $finish;
    end
