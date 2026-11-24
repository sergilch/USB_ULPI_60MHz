//-----------------------------------------------------------------------------
// rx_capture.v - triggered capture buffer and event counters of the
//                receiver-board FPGA (clkdiv = 120 MHz domain)
//
// Every clkdiv cycle one 32-bit word {dc, sq, s, m} (rx_sampler_7s, sample 0 =
// oldest) is written into a ring buffer of 2^AW words (AW = 13: 8192 words =
// 68 us, 8 BRAM36).  The read port runs on the system clock (rclk).
//
// Capture: an arm (toggle arm_tgl in the rclk domain) clears done, sets armed
// and starts writing.  Once at least `pre` words are written, the first word
// containing the trigger event fixes trig_addr (the address of that word);
// writing continues for DEPTH - pre - 1 more words, then armed falls and done
// rises.  The capture is the DEPTH words starting at start_addr = trig_addr - pre.
// Trigger sources (src): 0 immediate (first word after pre), 1 SQUELCH_A falling
// (line activity starts), 2 DISC_A rising, 3 any RX_OUT transition (m stream).
// src and pre must be stable while armed (rclk-domain registers, written only
// between captures).
//
// Counters (free running, 16 bit, Gray-coded for the rclk-domain reader):
//   sq_cnt  SQUELCH_A falling edges (line-activity bursts = packets)
//   dc_cnt  DISC_A rising edges
// done / armed / trig_addr are read through 2-FF synchronizers (trig_addr is
// stable when done is seen).
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module rx_capture #(
    parameter AW = 13
) (
    input  wire          clk,          // clkdiv
    input  wire          rst,          // synchronous to clk
    input  wire [31:0]   din,          // {dc, sq, s, m}
    input  wire          arm_tgl,      // rclk domain toggle
    input  wire [1:0]    src,
    input  wire [AW-1:0] pre,
    output reg           armed,
    output reg           done,
    output reg  [AW-1:0] trig_addr,
    output reg  [15:0]   sq_cnt_g,
    output reg  [15:0]   dc_cnt_g,
    // read port
    input  wire          rclk,
    input  wire [AW-1:0] raddr,
    output reg  [31:0]   rdata
);

    localparam [AW-1:0] DEPTH_M1 = {AW{1'b1}};

    (* ram_style = "block" *) reg [31:0] mem [0:(1 << AW) - 1];

    // ---------------- events in the current word ----------------
    wire [7:0] m  = din[7:0];
    wire [7:0] sq = din[23:16];
    wire [7:0] dc = din[31:24];
    reg        m_l, sq_l, dc_l;                      // last sample of the previous word
    wire [8:0] m9  = {m,  m_l};
    wire [8:0] sq9 = {sq, sq_l};
    wire [8:0] dc9 = {dc, dc_l};
    wire [7:0] sq_fall = sq9[7:0] & ~sq9[8:1];       // sample k-1 = 1, sample k = 0
    wire [7:0] dc_rise = ~dc9[7:0] & dc9[8:1];
    wire       m_edge  = |(m9[7:0] ^ m9[8:1]);
    reg [1:0]  warm;                                  // events valid 3 words after reset
    wire       ev_ok = &warm;                        // (ISERDESE2 outputs 0 until filled)
    reg        hit;
    always @(*) begin
        case (src)
            2'd0: hit = 1'b1;
            2'd1: hit = |sq_fall;
            2'd2: hit = |dc_rise;
            default: hit = m_edge;
        endcase
    end

    // ---------------- arm synchronizer ----------------
    reg [2:0] arm_s;
    wire      arm = arm_s[2] ^ arm_s[1];

    // ---------------- capture FSM ----------------
    reg [AW-1:0] waddr, post;
    reg [AW:0]   cnt;                                // words written since arm (saturating)
    reg          trig;
    reg [15:0]   sq_cnt, dc_cnt;

    always @(posedge clk) begin
        if (rst) begin
            arm_s <= 3'b000; armed <= 1'b0; done <= 1'b0; trig <= 1'b0;
            waddr <= 0; post <= 0; cnt <= 0; trig_addr <= 0;
            m_l <= 1'b0; sq_l <= 1'b1; dc_l <= 1'b0; warm <= 2'd0;
            sq_cnt <= 0; dc_cnt <= 0; sq_cnt_g <= 0; dc_cnt_g <= 0;
        end else begin
            arm_s <= {arm_s[1:0], arm_tgl};
            m_l <= m[7]; sq_l <= sq[7]; dc_l <= dc[7];
            if (!ev_ok) warm <= warm + 2'd1;
            if (ev_ok && |sq_fall) sq_cnt <= sq_cnt + 16'd1;
            if (ev_ok && |dc_rise) dc_cnt <= dc_cnt + 16'd1;
            sq_cnt_g <= sq_cnt ^ (sq_cnt >> 1);
            dc_cnt_g <= dc_cnt ^ (dc_cnt >> 1);
            if (arm) begin
                armed <= 1'b1; done <= 1'b0; trig <= 1'b0; cnt <= 0;
            end else if (armed) begin
                waddr <= waddr + 1'b1;
                if (!cnt[AW]) cnt <= cnt + 1'b1;
                if (!trig) begin
                    if ((cnt >= {1'b0, pre}) && hit && ev_ok) begin
                        trig <= 1'b1; trig_addr <= waddr; post <= DEPTH_M1 - pre - 1'b1;
                    end
                end else if (post != 0) begin
                    post <= post - 1'b1;
                end else begin
                    armed <= 1'b0; done <= 1'b1;
                end
            end
        end
    end

    always @(posedge clk)
        if (armed && !arm) mem[waddr] <= din;

    always @(posedge rclk)
        rdata <= mem[raddr];

endmodule
