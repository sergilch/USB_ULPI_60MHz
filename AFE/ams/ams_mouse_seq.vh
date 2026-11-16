//-----------------------------------------------------------------------------
// ams_mouse_seq.vh - host enumeration of a low-speed HID mouse through the
//                    PHY's ULPI interface: Link model, sequence and checks
//
// Included inside the top module of
//   * AFE/ams/tb_ams_mouse.vams   (Spectre AMS, Verilog-A AFE + Verilog-A mouse)
//   * tb_ams_mouse_shadow.v       (Icarus, afe_*_bm.v + ls_mouse_bm.v)
// Adapted from Tests/USB ULPI Mouse/tb_usb3300_enum.vams (same host tasks and
// enumeration steps); the Link is ulpi_link_bfm of
// Tests/USB ULPI Mouse/ulpi_tb_template.v, which the top includes at file level.
//
// The top provides:
//   wire       ulpi_clk, ulpi_dir, ulpi_nxt, ulpi_stp;  wire [7:0] ulpi_data;
//   reg        por_n, resetb;          (both start at 0)
//   `AMS_VDP / `AMS_VDM               line voltages in volts (real)
//
// Sequence (the testbench plays the USB host / Link, the PHY is ams_ulpi_phy):
//   1. Power-on, RESETB; Vendor / Product ID (0424h / 0007h), scratch register.
//   2. Host mode: OTG Control 66h (DpPulldown, DmPulldown, DrvVbus,
//      DrvVbusExternal), Function Control 45h (FS, TermSelect 1) to sense the
//      attach; the Debug register's LineState goes 00 -> 10 when the mouse
//      connects its D- pull-up (low-speed); line: DM > 2.7 V, DP < 0.3 V.
//   3. Bus reset as the USB3320 does it: Function Control 50h (XcvrSelect 00,
//      TermSelect 0, OpMode 10) switches the 45 Ohm terminations on, which pull
//      the line to SE0 (checked on the line); then 46h (LS host, OpMode 00).
//      The mouse model reports "USB bus reset detected".
//   4. GET_DESCRIPTOR(device, 8) at address 0, SET_ADDRESS(5),
//      GET_DESCRIPTOR(device, 18), GET_DESCRIPTOR(configuration, 9 / 34),
//      SET_CONFIGURATION(1), SET_IDLE(0), GET_DESCRIPTOR(HID report, 52):
//      every SETUP ACKed, data-stage CRC16 and DATA toggles checked, the
//      descriptors' fields checked against the mouse model.
//   5. Three interrupt reports from EP1 (NAKs are retried), contents checked.
//   Every packet goes Link -> ULPI TXCMD -> PHY TX path -> AFE -> line ->
//   mouse, and back line -> AFE -> PHY RX path -> RXCMD / ULPI data -> Link.
//
// Times are scaled against USB 2.0 so the run stays short (the mouse model
// detects a reset after 2.5 us of SE0 and has no suspend, so no keep-alive is
// needed): debounce 10 us (100 ms), reset 10 us (10 ms), recovery 10 us
// (10 ms), SET_ADDRESS recovery 10 us (2 ms).  Simulated time about 3.5 ms.
//
// Result line: TEST PASSED / TEST FAILED: <n> error(s) / TEST FAILED: timeout.
//-----------------------------------------------------------------------------

    // ------------------------------------------------------------ parameters
    localparam [6:0] DEV_ADDR     = 7'd5;
    localparam integer RX_TO       = 60000;     // RX wait timeout [60 MHz clocks] (1 ms)
    localparam integer T_DEBOUNCE  = 10_000;    // ns, scaled (spec: 100 ms)
    localparam integer T_RESET     = 10_000;    // ns, scaled (spec: >= 10 ms SE0)
    localparam integer T_RECOVERY  = 10_000;    // ns, scaled (spec: 10 ms reset recovery)
    localparam integer T_SETADDR   = 10_000;    // ns, scaled (spec: 2 ms SET_ADDRESS recovery)
    localparam [7:0]   OTG_CTRL_VAL = 8'h66;    // DpPulldown | DmPulldown | DrvVbus | DrvVbusExternal

    localparam [7:0] FUNC_LS_HOST  = 8'h46;     // SuspendM=1, OpMode=00, TermSelect=1, XcvrSelect=10 (LS)
    localparam [7:0] FUNC_FS_HOST  = 8'h45;     // XcvrSelect=01 (FS), used to sense attach
    localparam [7:0] FUNC_HS_RESET = 8'h50;     // SuspendM=1, OpMode=10, TermSelect=0, XcvrSelect=00:
                                                // 45 Ohm terminations on -> SE0 (USB3320 host reset)

    // ------------------------------------------------------------ Link-side ULPI BFM
    // Low-speed bytes take ~5.3 us = 320 clocks, so nxt waits must be long.
    ulpi_link_bfm #(.NXT_TIMEOUT(4000)) u_link (
        .clk(ulpi_clk), .dir(ulpi_dir), .nxt(ulpi_nxt), .data(ulpi_data), .stp(ulpi_stp));

    // ============================================================ host-side state
    reg [7:0] ctl_buf [0:255];     // data received in control-read data stages
    integer   ctl_n;
    reg [7:0] rpt [0:3];           // last interrupt report
    integer   errors, checks;
    reg [3:0] rx_pid;              // last received packet
    integer   rx_nbytes;           // bytes incl. PID and CRC
    reg       rx_ok;
    reg       int_tog;             // expected DATA toggle for EP1
    integer   max_pkt0;

    localparam [3:0] PID_OUT   = `ULPI_PID_OUT;
    localparam [3:0] PID_IN    = `ULPI_PID_IN;
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
    // SETUP stage: token + DATA0(8 bytes) and ACK check
    task host_setup(input [6:0] addr, input [7:0] bm, input [7:0] br,
                    input [15:0] wv, input [15:0] wi, input [15:0] wl);
        reg ok;
        begin
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

    // Control read: SETUP + IN data stage (8-byte packets) + OUT status stage
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
                    if (n < 8 || ctl_n >= wl) done = 1'b1;
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

    // Poll interrupt endpoint 1 until a report arrives
    task host_poll_report(input [6:0] addr, output got_rpt);
        reg ok; reg [15:0] crc; integer tries, i;
        begin
            got_rpt = 1'b0; tries = 0;
            while (!got_rpt && tries < 300) begin
                host_send_token(PID_IN, addr, 4'd1);
                host_wait_pkt(ok);
                if (ok && rx_pid == PID_NAK) begin
                    tries = tries + 1;
                    #(5_000);
                end else if (ok && (rx_pid == PID_DATA0 || rx_pid == PID_DATA1) && rx_nbytes == 7) begin
                    crc16_rx(1, 4, crc);
                    check({u_link.rx_buf[6], u_link.rx_buf[5]} == crc, "report CRC16");
                    check((rx_pid == PID_DATA1) == int_tog,             "report DATA toggle");
                    for (i = 0; i < 4; i = i + 1) rpt[i] = u_link.rx_buf[1 + i];
                    host_send_handshake(PID_ACK);
                    int_tog = ~int_tog;
                    got_rpt = 1'b1;
                end else begin
                    check(1'b0, "valid interrupt report or NAK");
                    tries = 300;
                end
            end
        end
    endtask

    // ------------------------------------------------------------ port-level tasks
    // Wait for the device attach; returns 1 for low-speed (idle = K in FS terms), 2 for full-speed
    task host_wait_attach(output integer speed);
        reg [7:0] r; integer n;
        begin
            speed = 0; n = 0;
            while (speed == 0 && n < 2000) begin
                u_link.link_reg_read(`ULPI_REG_DEBUG, r);          // Debug register [1:0] = LineState
                if (r[1:0] == 2'b10)      speed = 1;               // D- high idle  -> low-speed device
                else if (r[1:0] == 2'b01) speed = 2;               // D+ high idle  -> full-speed device
                else #(2_000);
                n = n + 1;
            end
        end
    endtask

    // Bus reset: the 45 Ohm HS terminations of the host PHY pull both wires to
    // SE0 (Function Control: XcvrSelect 00, TermSelect 0, OpMode 10), as the
    // USB3320 / ULPI host does it; then back to LS host.
    task host_bus_reset;
        reg [7:0] r;
        begin
            u_link.link_reg_write(`ULPI_REG_FUNC_CTRL, FUNC_HS_RESET);
            #(T_RESET / 2);
            check_line(-0.1, 0.3, -0.1, 0.3, "line SE0 during reset");
            #(T_RESET / 2);
            u_link.link_reg_write(`ULPI_REG_FUNC_CTRL, FUNC_LS_HOST);
            #(T_RECOVERY);
            u_link.link_reg_read(`ULPI_REG_DEBUG, r);
            check(r[1:0] == 2'b10, "LineState J (LS) after reset");
            check_line(-0.1, 0.3, 2.7, 3.4, "line LS idle (J) after reset");
        end
    endtask

    // ============================================================ main sequence
    integer speed, wtotal;
    reg [7:0] rd;
    reg got;

    initial begin
        errors = 0; checks = 0; int_tog = 1'b0; ctl_n = 0; max_pkt0 = 8;

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
        u_link.link_reg_write(`ULPI_REG_FUNC_CTRL, FUNC_FS_HOST);        // sense attach in FS mode
        u_link.link_reg_read(`ULPI_REG_DEBUG, rd);
        check(rd[1:0] == 2'b00, "LineState SE0 before attach");
        host_wait_attach(speed);
        check(speed == 1, "low-speed device attached");
        #(T_DEBOUNCE);                                                   // attach debounce (scaled)
        u_link.link_reg_read(`ULPI_REG_DEBUG, rd);
        check(rd[1:0] == 2'b10, "attach stable after debounce");
        check_line(-0.1, 0.3, 2.7, 3.4, "line: DM pulled up, DP low");

        // ---- 3. bus reset, then low-speed host ---------------------------------------
        $display("3. bus reset");
        host_bus_reset;

        // ---- 4. first 8 bytes of device descriptor at address 0 ----------------------
        $display("4. GET_DESCRIPTOR(device, 8) at address 0");
        host_ctrl_read(7'd0, 8'h80, 8'h06, 16'h0100, 16'h0000, 16'd8);
        check(ctl_n == 8,               "device descriptor: 8 bytes");
        check(ctl_buf[1] == 8'h01,      "descriptor type = DEVICE");
        max_pkt0 = ctl_buf[7];
        check(max_pkt0 == 8,            "bMaxPacketSize0 = 8 (low-speed)");

        // ---- 5. SET_ADDRESS ------------------------------------------------------------
        $display("5. SET_ADDRESS(%0d)", DEV_ADDR);
        host_ctrl_nodata(7'd0, 8'h00, 8'h05, {9'd0, DEV_ADDR}, 16'h0000);
        #(T_SETADDR);

        // ---- 6. full device descriptor at the new address -------------------------------
        $display("6. GET_DESCRIPTOR(device, 18)");
        host_ctrl_read(DEV_ADDR, 8'h80, 8'h06, 16'h0100, 16'h0000, 16'd18);
        check(ctl_n == 18,                              "device descriptor: 18 bytes");
        check({ctl_buf[9], ctl_buf[8]}   == 16'h1234,   "idVendor  = 0x1234");
        check({ctl_buf[11], ctl_buf[10]} == 16'h5678,   "idProduct = 0x5678");
        check(ctl_buf[17] == 8'h01,                     "bNumConfigurations = 1");

        // ---- 7. configuration descriptor (header, then full) ---------------------------
        $display("7. GET_DESCRIPTOR(configuration, 9 / 34)");
        host_ctrl_read(DEV_ADDR, 8'h80, 8'h06, 16'h0200, 16'h0000, 16'd9);
        wtotal = {ctl_buf[3], ctl_buf[2]};
        check(wtotal == 34, "wTotalLength = 34");
        host_ctrl_read(DEV_ADDR, 8'h80, 8'h06, 16'h0200, 16'h0000, wtotal);
        check(ctl_n == 34,                "configuration descriptor: 34 bytes");
        check(ctl_buf[14] == 8'h03,       "interface class = HID");
        check(ctl_buf[15] == 8'h01,       "interface subclass = boot");
        check(ctl_buf[16] == 8'h02,       "interface protocol = mouse");
        check(ctl_buf[29] == 8'h81,       "endpoint 1 IN");
        check(ctl_buf[30] == 8'h03,       "endpoint type = interrupt");

        // ---- 8. SET_CONFIGURATION(1) and HID class requests -----------------------------
        $display("8. SET_CONFIGURATION, SET_IDLE, HID report descriptor");
        host_ctrl_nodata(DEV_ADDR, 8'h00, 8'h09, {8'd0, ctl_buf[5]}, 16'h0000);
        host_ctrl_nodata(DEV_ADDR, 8'h21, 8'h0A, 16'h0000, 16'h0000);        // SET_IDLE(0)
        host_ctrl_read  (DEV_ADDR, 8'h81, 8'h06, 16'h2200, 16'h0000, {ctl_buf[26], ctl_buf[25]}); // HID report descriptor
        check(ctl_n == 52,                "HID report descriptor: 52 bytes");
        check(ctl_buf[0] == 8'h05 && ctl_buf[1] == 8'h01 && ctl_buf[3] == 8'h02,
                                          "report descriptor: Generic Desktop / Mouse");

        // ---- 9. read three mouse reports from the interrupt endpoint -------------------
        $display("9. interrupt reports from EP1");
        host_poll_report(DEV_ADDR, got);
        check(got && rpt[0] == 8'h01 && rpt[1] == 8'h05 && rpt[2] == 8'hFD && rpt[3] == 8'h00,
              "report 1: left button, dX=+5, dY=-3");
        host_poll_report(DEV_ADDR, got);
        check(got && rpt[0] == 8'h00 && rpt[1] == 8'h10 && rpt[2] == 8'h00 && rpt[3] == 8'h01,
              "report 2: dX=+16, wheel=+1");
        host_poll_report(DEV_ADDR, got);
        check(got && rpt[0] == 8'h02 && rpt[1] == 8'hF0 && rpt[2] == 8'h08 && rpt[3] == 8'h00,
              "report 3: right button, dX=-16, dY=+8");

        // ---- 10. verdict -----------------------------------------------------------------
        errors = errors + u_link.err_cnt;
        $display("%0d checks, %0d Link BFM errors, %0d RXCMDs, %0d packets received",
                 checks, u_link.err_cnt, u_link.rxcmd_cnt, u_link.rx_pkt_cnt);
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
