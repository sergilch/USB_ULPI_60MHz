//-----------------------------------------------------------------------------
// ls_mouse_bm.v - event-driven (Icarus) port of the Verilog-A low-speed HID
//                 mouse usb_ls_mouse.v (same directory), testbench only
//
// Same behaviour as usb_ls_mouse.v, line by line: the same variables,
// descriptors, 8x oversampled receiver / transmitter / protocol engine (see
// the header of usb_ls_mouse.v), evaluated on the same timer (every
// tick = tbit / 8, first at t = 0) and printing the same "[mouse]" messages.
// Only the analog front end is mapped to the electrical convention of the
// afe_*_bm models (afe_line_bm.v: per wire a Norton pair *_g [S] / *_i [A] as
// $realtobits; the line voltages come back on dp_v / dm_v):
//   * driver on (drv_en): voltage source vdp / vdm behind rdrv; the source
//     ramps linearly to its target in trf (transition(), stepped in 25 steps)
//   * driver off: rin to ground
//   * after t_attach: rpu from DM to vcc (low-speed signature)
//   * cpin is not modelled (afe_line_bm has no capacitance)
// The line is sampled at each tick with the threshold vth, as V(dp) / V(dm)
// in the Verilog-A model.  Parameters keep the Verilog-A names and units
// (seconds, volts, ohms).
//
// Keep the two models in sync: a change of the protocol engine in
// usb_ls_mouse.v must be made here too (tb_ams_mouse_shadow.v runs this one,
// AFE/ams/tb_ams_mouse.vams the Verilog-A one).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module ls_mouse_bm #(
    parameter real    vcc         = 3.3,
    parameter real    rpu         = 1500.0,       // D- pull-up
    parameter real    rdrv        = 36.0,         // driver output resistance
    parameter real    rin         = 1.0e6,        // receiver input resistance
    parameter real    vth         = 1.65,         // logic threshold
    parameter real    tbit        = 666.667e-9,   // low-speed bit time
    parameter real    trf         = 100.0e-9,     // driver rise/fall time
    parameter real    t_attach    = 20.0e-6,      // plug-in time
    parameter real    rep_start   = 20.0e-6,      // first report this long after SET_CONFIGURATION
    parameter real    rep_period  = 100.0e-6,     // report availability period
    parameter integer rst_ticks   = 30            // SE0 ticks (tbit/8 each) = bus reset (~2.5 us)
) (
    input  wire [63:0] dp_v, dm_v,                // line voltages (afe_line_bm)
    output reg  [63:0] dp_g, dp_i,                // Norton contribution to DP
    output reg  [63:0] dm_g, dm_i                 // and to DM
);
  localparam real tick    = tbit / 8.0;
  localparam real tick_ns = tick * 1.0e9;

  // ---------------------------------------------------------------- descriptors
  integer dev_desc [0:17];
  integer cfg_desc [0:33];
  integer rep_desc [0:51];
  integer rep_data [0:11];

  // ---------------------------------------------------------------- engine state
  integer rxbuf [0:15];
  integer txd   [0:15];
  integer txs   [0:191];

  integer attached, drv_en;
  integer dpv, dmv, st, prev_st, samp_prev, cnt, rx_state, ones, bitpos, curbyte, nb, bv;
  integer se0_cnt, wcnt;
  integer tx_req, tx_pid, tx_nd, tx_on, tx_idx, tx_cnt, tx_tick;
  integer i, j, k, s, n, t, c, cur, bi, bb, crcl, crch, pid, chk, a, e;
  integer bm, br, wv, wi, wl;
  integer expect_k, dev_addr, pend_addr, addr_pend, configured;
  integer ctl_stage, in_src, in_len, in_off, in_tog, last_kind, last_len;
  integer tog1, rep_pending, rep_idx;

  real vdp_t, vdm_t, vdp, vdm, rep_next;

  // $abstime of the Verilog-A model, in seconds
  function real abstime(input dummy);
    abstime = $realtime * 1.0e-9;
  endfunction

  // CRC16 (x^16+x^15+x^2+1), reflected, one byte
  function integer crc16_byte(input integer crc, input integer b);
    integer ii, cc, x;
    begin
      cc = crc;
      for (ii = 0; ii < 8; ii = ii + 1) begin
        x  = (cc ^ (b >> ii)) & 1;
        cc = cc >> 1;
        if (x == 1) cc = cc ^ 40961;          // 0xA001
      end
      crc16_byte = cc;
    end
  endfunction

  // ------------------------------------------------------------ initialisation
  initial begin
    // Device descriptor
    dev_desc[0]=18;  dev_desc[1]=1;   dev_desc[2]=16;  dev_desc[3]=1;
    dev_desc[4]=0;   dev_desc[5]=0;   dev_desc[6]=0;   dev_desc[7]=8;
    dev_desc[8]=52;  dev_desc[9]=18;  dev_desc[10]=120; dev_desc[11]=86;  // VID 0x1234, PID 0x5678
    dev_desc[12]=0;  dev_desc[13]=1;  dev_desc[14]=0;  dev_desc[15]=0;
    dev_desc[16]=0;  dev_desc[17]=1;
    // Configuration (9) + Interface (9) + HID (9) + Endpoint (7) = 34
    cfg_desc[0]=9;   cfg_desc[1]=2;   cfg_desc[2]=34;  cfg_desc[3]=0;
    cfg_desc[4]=1;   cfg_desc[5]=1;   cfg_desc[6]=0;   cfg_desc[7]=160; cfg_desc[8]=50;
    cfg_desc[9]=9;   cfg_desc[10]=4;  cfg_desc[11]=0;  cfg_desc[12]=0;
    cfg_desc[13]=1;  cfg_desc[14]=3;  cfg_desc[15]=1;  cfg_desc[16]=2;  cfg_desc[17]=0;
    cfg_desc[18]=9;  cfg_desc[19]=33; cfg_desc[20]=16; cfg_desc[21]=1;
    cfg_desc[22]=0;  cfg_desc[23]=1;  cfg_desc[24]=34; cfg_desc[25]=52; cfg_desc[26]=0;
    cfg_desc[27]=7;  cfg_desc[28]=5;  cfg_desc[29]=129; cfg_desc[30]=3;
    cfg_desc[31]=4;  cfg_desc[32]=0;  cfg_desc[33]=10;
    // HID report descriptor (3 buttons + X, Y, wheel), 52 bytes
    rep_desc[0]=5;   rep_desc[1]=1;   rep_desc[2]=9;   rep_desc[3]=2;
    rep_desc[4]=161; rep_desc[5]=1;   rep_desc[6]=9;   rep_desc[7]=1;
    rep_desc[8]=161; rep_desc[9]=0;   rep_desc[10]=5;  rep_desc[11]=9;
    rep_desc[12]=25; rep_desc[13]=1;  rep_desc[14]=41; rep_desc[15]=3;
    rep_desc[16]=21; rep_desc[17]=0;  rep_desc[18]=37; rep_desc[19]=1;
    rep_desc[20]=149; rep_desc[21]=3; rep_desc[22]=117; rep_desc[23]=1;
    rep_desc[24]=129; rep_desc[25]=2; rep_desc[26]=149; rep_desc[27]=1;
    rep_desc[28]=117; rep_desc[29]=5; rep_desc[30]=129; rep_desc[31]=3;
    rep_desc[32]=5;  rep_desc[33]=1;  rep_desc[34]=9;  rep_desc[35]=48;
    rep_desc[36]=9;  rep_desc[37]=49; rep_desc[38]=9;  rep_desc[39]=56;
    rep_desc[40]=21; rep_desc[41]=129; rep_desc[42]=37; rep_desc[43]=127;
    rep_desc[44]=117; rep_desc[45]=8; rep_desc[46]=149; rep_desc[47]=3;
    rep_desc[48]=129; rep_desc[49]=6; rep_desc[50]=192; rep_desc[51]=192;
    // Mouse reports {buttons, dX, dY, wheel}
    rep_data[0]=1;   rep_data[1]=5;   rep_data[2]=253; rep_data[3]=0;    // left button, +5, -3
    rep_data[4]=0;   rep_data[5]=16;  rep_data[6]=0;   rep_data[7]=1;    // +16, wheel +1
    rep_data[8]=2;   rep_data[9]=240; rep_data[10]=8;  rep_data[11]=0;   // right button, -16, +8

    attached = 0; drv_en = 0; prev_st = 0; samp_prev = 1; cnt = 0; rx_state = 0;
    ones = 0; bitpos = 0; curbyte = 0; nb = 0; se0_cnt = 0; wcnt = 0;
    tx_req = 0; tx_on = 0; tx_idx = 0; tx_cnt = 0; tx_tick = 0; tx_pid = 0; tx_nd = 0;
    expect_k = 0; dev_addr = 0; pend_addr = 0; addr_pend = 0; configured = 0;
    ctl_stage = 0; in_src = 0; in_len = 0; in_off = 0; in_tog = 1; last_kind = 0; last_len = 0;
    tog1 = 0; rep_pending = 0; rep_idx = 0; rep_next = 1.0e9;
    vdp_t = 0.0; vdm_t = vcc;                       // J state when driven
    vdp = vdp_t; vdm = vdm_t;
  end

  // ------------------------------------------------------------ attach
  initial begin
    #(t_attach * 1.0e9);
    attached = 1;
    $display("[mouse] %e s: attached (D- pull-up connected)", abstime(0));
  end

  // ------------------------------------------------------------ 8x oversampled engine
  initial begin
    #0;
    forever begin
      engine_tick;
      #(tick_ns);
    end
  end

  task engine_tick;
    begin
      // line state: 0 = SE0, 1 = J, 2 = K, 3 = SE1
      dpv = ($bitstoreal(dp_v) > vth) ? 1 : 0;
      dmv = ($bitstoreal(dm_v) > vth) ? 1 : 0;
      if (dpv == 0 && dmv == 0)      st = 0;
      else if (dpv == 0 && dmv == 1) st = 1;
      else if (dpv == 1 && dmv == 0) st = 2;
      else                           st = 3;

      // a new report becomes available
      if (configured == 1 && rep_pending == 0 && abstime(0) >= rep_next) rep_pending = 1;

      // ---------------------------------------------------------- receiver
      if (attached == 1 && tx_on == 0) begin

        if (rx_state == 0) begin                                   // idle
          if (st == 0) begin
            se0_cnt = se0_cnt + 1;
            if (se0_cnt == rst_ticks) begin                        // bus reset
              dev_addr = 0; addr_pend = 0; configured = 0; ctl_stage = 0; expect_k = 0;
              in_tog = 1; tog1 = 0; rep_pending = 0; rep_idx = 0; rep_next = 1.0e9;
              $display("[mouse] %e s: USB bus reset detected", abstime(0));
            end
          end else begin
            se0_cnt = 0;
          end
          if (st == 2 && prev_st == 1) begin                       // J -> K : start of SYNC
            rx_state = 1; cnt = 0; samp_prev = 1;
            ones = 0; bitpos = 0; curbyte = 0; nb = 0;
          end

        end else if (rx_state == 1 || rx_state == 2) begin         // SYNC / packet body
          if (st != prev_st) cnt = 0; else cnt = cnt + 1;
          if (cnt >= 8) cnt = 0;

          if (cnt == 4) begin                                      // centre of a bit
            if (st == 0) begin
              if (rx_state == 2) begin                             // ------- EOP: process packet
                pid = rxbuf[0] & 15;
                chk = (rxbuf[0] >> 4) & 15;
                if (nb >= 1 && bitpos == 0 && chk == (15 - pid)) begin

                  if (pid == 13 || pid == 9 || pid == 1) begin     // SETUP / IN / OUT token
                    if (nb == 3) begin
                      a = rxbuf[1] & 127;
                      e = ((rxbuf[1] >> 7) & 1) | ((rxbuf[2] & 7) << 1);
                      expect_k = 0;
                      if (a == dev_addr) begin
                        if (pid == 13)     expect_k = 1;           // SETUP -> DATA0 follows
                        else if (pid == 1) expect_k = 2;           // OUT   -> DATA follows
                        else begin                                 // IN -> respond now
                          tx_nd = 0; last_kind = 0;
                          if (e == 0) begin
                            if (ctl_stage == 1) begin              // control read, data stage
                              n = in_len - in_off;
                              if (n > 8) n = 8;
                              for (i = 0; i < n; i = i + 1) begin
                                if (in_src == 1)      txd[i] = dev_desc[in_off + i];
                                else if (in_src == 2) txd[i] = cfg_desc[in_off + i];
                                else if (in_src == 3) txd[i] = rep_desc[in_off + i];
                                else                  txd[i] = cfg_desc[18 + in_off + i];
                              end
                              tx_pid = (in_tog == 1) ? 11 : 3;
                              tx_nd = n; last_len = n; last_kind = 1;
                            end else if (ctl_stage == 2) begin     // status stage of a no-data request
                              tx_pid = 11; last_kind = 2;          // zero-length DATA1
                            end else if (ctl_stage == 9) begin
                              tx_pid = 14;                         // STALL
                            end else begin
                              tx_pid = 10;                         // NAK
                            end
                          end else if (e == 1 && configured == 1) begin
                            if (rep_pending == 1) begin            // interrupt IN: mouse report
                              for (i = 0; i < 4; i = i + 1) txd[i] = rep_data[(rep_idx % 3) * 4 + i];
                              tx_pid = (tog1 == 1) ? 11 : 3;
                              tx_nd = 4; last_kind = 3;
                            end else begin
                              tx_pid = 10;                         // NAK: nothing to report
                            end
                          end else begin
                            tx_pid = 10;
                          end
                          tx_req = 1;
                        end
                      end
                    end

                  end else if (pid == 3 || pid == 11) begin        // DATA0 / DATA1 from host
                    if (expect_k == 1 && nb == 11) begin           // SETUP data: 8 bytes + CRC16
                      c = 65535;
                      for (i = 1; i <= 8; i = i + 1) c = crc16_byte(c, rxbuf[i]);
                      c = c ^ 65535;
                      if (c == (rxbuf[9] | (rxbuf[10] << 8))) begin
                        bm = rxbuf[1]; br = rxbuf[2];
                        wv = rxbuf[3] | (rxbuf[4] << 8);
                        wi = rxbuf[5] | (rxbuf[6] << 8);
                        wl = rxbuf[7] | (rxbuf[8] << 8);
                        $display("[mouse] %e s: SETUP bm=0x%h br=0x%h wValue=0x%h wIndex=0x%h wLength=%0d",
                                 abstime(0), bm[7:0], br[7:0], wv[15:0], wi[15:0], wl);
                        ctl_stage = 9; in_off = 0; in_tog = 1; in_len = 0; in_src = 0;
                        if (bm == 128 && br == 6) begin            // GET_DESCRIPTOR (device)
                          t = wv >> 8;
                          if (t == 1)      begin in_src = 1; in_len = 18; ctl_stage = 1; end
                          else if (t == 2) begin in_src = 2; in_len = 34; ctl_stage = 1; end
                        end else if (bm == 129 && br == 6) begin   // GET_DESCRIPTOR (interface: HID)
                          t = wv >> 8;
                          if (t == 34)      begin in_src = 3; in_len = 52; ctl_stage = 1; end
                          else if (t == 33) begin in_src = 4; in_len = 9;  ctl_stage = 1; end
                        end else if (bm == 0 && br == 5) begin     // SET_ADDRESS
                          pend_addr = wv & 127; addr_pend = 1; ctl_stage = 2;
                        end else if (bm == 0 && br == 9) begin     // SET_CONFIGURATION
                          configured = ((wv & 255) != 0) ? 1 : 0;
                          tog1 = 0; rep_idx = 0; rep_pending = 0;
                          rep_next = abstime(0) + rep_start;
                          ctl_stage = 2;
                        end else if (bm == 33 && (br == 10 || br == 11)) begin  // SET_IDLE / SET_PROTOCOL
                          ctl_stage = 2;
                        end
                        if (ctl_stage == 1 && in_len > wl) in_len = wl;
                        tx_pid = 2; tx_nd = 0; last_kind = 0; tx_req = 1;   // ACK the SETUP
                      end
                      expect_k = 0;
                    end else if (expect_k == 2) begin              // OUT data (e.g. status stage)
                      tx_nd = 0; last_kind = 0;
                      if (ctl_stage == 9) tx_pid = 14;             // STALL
                      else begin
                        tx_pid = 2;
                        if (ctl_stage == 3) ctl_stage = 0;         // control-read status stage done
                      end
                      tx_req = 1; expect_k = 0;
                    end

                  end else if (pid == 2) begin                     // ACK from host
                    if (last_kind == 1) begin
                      in_off = in_off + last_len;
                      in_tog = 1 - in_tog;
                      if (in_off >= in_len) ctl_stage = 3;         // wait for OUT status stage
                    end else if (last_kind == 2) begin
                      ctl_stage = 0;
                      if (addr_pend == 1) begin
                        dev_addr = pend_addr; addr_pend = 0;
                        $display("[mouse] %e s: address set to %0d", abstime(0), dev_addr);
                      end
                    end else if (last_kind == 3) begin
                      tog1 = 1 - tog1; rep_pending = 0; rep_idx = rep_idx + 1;
                      rep_next = abstime(0) + rep_period;
                    end
                    last_kind = 0;
                  end
                end
              end
              rx_state = 3; wcnt = 0;                              // wait for end of EOP
            end else if (st == 3) begin
              rx_state = 0;                                        // SE1: illegal, give up
            end else begin
              bv = (st == samp_prev) ? 1 : 0;                      // NRZI: no change = 1
              samp_prev = st;
              if (rx_state == 1) begin
                if (bv == 1) begin                                 // end of SYNC
                  rx_state = 2; ones = 1; bitpos = 0; curbyte = 0; nb = 0;
                end
              end else begin
                if (ones == 6) begin
                  ones = 0;                                        // stuffed bit: discard
                end else begin
                  if (bv == 1) ones = ones + 1; else ones = 0;
                  curbyte = curbyte | (bv << bitpos);
                  bitpos = bitpos + 1;
                  if (bitpos == 8) begin
                    if (nb < 16) rxbuf[nb] = curbyte;
                    nb = nb + 1; bitpos = 0; curbyte = 0;
                  end
                end
              end
            end
          end

        end else begin                                             // rx_state 3: EOP ends, J returns
          if (st == 1) begin
            wcnt = wcnt + 1;
            if (tx_req == 1) begin
              if (wcnt >= 16) begin                                // ~2 bit times turn-around
                // ---- build symbol stream: SYNC | PID | data | CRC16 | EOP ----
                txs[0] = 2; txs[1] = 1; txs[2] = 2; txs[3] = 1;
                txs[4] = 2; txs[5] = 1; txs[6] = 2; txs[7] = 2;    // KJKJKJKK
                k = 8; cur = 2; ones = 1;
                if (tx_pid == 3 || tx_pid == 11) begin
                  c = 65535;
                  for (i = 0; i < tx_nd; i = i + 1) c = crc16_byte(c, txd[i]);
                  c = c ^ 65535;
                  crcl = c & 255; crch = (c >> 8) & 255;
                  n = 1 + tx_nd + 2;
                end else begin
                  crcl = 0; crch = 0;
                  n = 1;
                end
                for (bi = 0; bi < n; bi = bi + 1) begin
                  if (bi == 0)              bb = tx_pid | ((15 - tx_pid) << 4);
                  else if (bi <= tx_nd)     bb = txd[bi - 1];
                  else if (bi == tx_nd + 1) bb = crcl;
                  else                      bb = crch;
                  for (j = 0; j < 8; j = j + 1) begin
                    if (((bb >> j) & 1) == 1) begin
                      txs[k] = cur; k = k + 1; ones = ones + 1;
                      if (ones == 6) begin                         // bit stuffing
                        cur = (cur == 1) ? 2 : 1; txs[k] = cur; k = k + 1; ones = 0;
                      end
                    end else begin
                      cur = (cur == 1) ? 2 : 1; txs[k] = cur; k = k + 1; ones = 0;
                    end
                  end
                end
                txs[k] = 0; txs[k + 1] = 0; txs[k + 2] = 1;        // EOP: SE0 SE0 J
                tx_cnt = k + 3;
                tx_on = 1; tx_idx = 0; tx_tick = 0; drv_en = 1; tx_req = 0;
                rx_state = 0;
              end
            end else begin
              rx_state = 0;
            end
          end else begin
            wcnt = 0;
          end
        end
      end

      // ---------------------------------------------------------- transmitter
      if (tx_on == 1) begin
        if (tx_tick == 0) begin
          if (tx_idx < tx_cnt) begin
            s = txs[tx_idx]; tx_idx = tx_idx + 1;
            if (s == 1)      begin vdp_t = 0.0; vdm_t = vcc; end   // J
            else if (s == 2) begin vdp_t = vcc; vdm_t = 0.0; end   // K
            else             begin vdp_t = 0.0; vdm_t = 0.0; end   // SE0
          end else begin
            drv_en = 0; tx_on = 0; vdp_t = 0.0; vdm_t = vcc;       // release the bus
            rx_state = 0; cnt = 0; samp_prev = 1; se0_cnt = 0;
          end
        end
        tx_tick = (tx_tick + 1) % 8;
      end

      prev_st = st;
    end
  endtask

  // ------------------------------------------------------------ analog front end
  // transition(v_t, 0, trf, trf): linear ramp of the source to its target in
  // trf, stepped in 25 steps (as afe_fsls_bm); a new target restarts the ramp
  // from the present value
  always begin
    if ((vdp != vdp_t) || (vdm != vdm_t)) begin
      #(trf * 1.0e9 / 25.0);
      vdp = ramp(vdp, vdp_t, vcc / 25.0);
      vdm = ramp(vdm, vdm_t, vcc / 25.0);
    end else
      @(vdp_t or vdm_t);
  end

  function real ramp(input real v, input real tgt, input real dv);
    begin
      if (v < tgt) ramp = (tgt - v <= dv) ? tgt : v + dv;
      else         ramp = (v - tgt <= dv) ? tgt : v - dv;
    end
  endfunction

  // I(dp) <+ (V(dp) - vdp) / rdrv  or  V(dp) / rin;  I(dm) likewise, plus the
  // pull-up (V(dm) - vcc) / rpu once attached.  Norton form for afe_line_bm:
  // g = 1 / R, i = Vsource / R.
  real gp, ip, gm, im;
  always @(drv_en or attached or vdp or vdm) begin
    if (drv_en == 1) begin
      gp = 1.0 / rdrv; ip = vdp / rdrv;
      gm = 1.0 / rdrv; im = vdm / rdrv;
    end else begin
      gp = 1.0 / rin;  ip = 0.0;
      gm = 1.0 / rin;  im = 0.0;
    end
    if (attached == 1) begin gm = gm + 1.0 / rpu; im = im + vcc / rpu; end
    dp_g = $realtobits(gp); dp_i = $realtobits(ip);
    dm_g = $realtobits(gm); dm_i = $realtobits(im);
  end
endmodule
