//-----------------------------------------------------------------------------
// usb_rx_fsls_dpll.v - FS/LS clock / data recovery on clk60 (Plan_60MHz.md 4.3, P4)
//
//   usb_rx_fsls_sampler --rcv_v, dp_v, dm_v [7:0]--> [THIS BLOCK, clk60]
//        --> b_en / b_lvl / b_se0 / b_act (at most one bit per tick)
//        --> usb_rx_decoder8 (hs = 0, slot 0)
//
// The DPLL of ref_rx_fsls_frontend, for the 8 samples of a tick at once.  Per
// sample (bit 0 = oldest):
//   symbol = SE0 (both single-ended receivers low), or J / K from rxrcv
//     (FS: J = rxrcv 1, LS: J = rxrcv 0; rxrcv is ignored during SE0);
//   change = SE0 starts / ends, or the J/K level differs from the previous
//     sample's (ref_rx_fsls_frontend compares with the last J/K level, held
//     through SE0; that only matters for a sample right after SE0, which is a
//     change anyway, so both rules are the same);
//   a bit-time counter (in samples) restarts at 1 on a change, wraps from
//   DIV - 1 to 0, and the bit is strobed on a sample without a change where
//   the counter is DIV / 2 (middle of the bit).
// Same rule, same sample: the strobed bits are those of ref_rx_fsls_frontend on
// the same sample stream (tb_usb_rx_fsls_frontend compares both).
//
// Closed form.  DIV / 2 >= 8 (FS_DIV >= 16), so a strobe can only come from the
//   count carried into the tick: strobe at sample i <=> no change in samples
//   0..i and cnt + i == DIV / 2.  Hence at most one strobe per tick.  The
//   carried count is 8 - j after a last change at sample j, otherwise cnt + 8
//   with at most one wrap (DIV > 8).
//
// The sampler word is registered on clk60 first (it comes from the clk_bit
// island, changes on ld and so has only half a tick, E4 -> E0, to its first
// clk60 flop; Plan_60MHz.md K10).
//
// Output (registered, two ticks after the word): b_en = a bit in this tick,
//   b_lvl / b_se0 = its symbol, b_act = enable.  ls / enable are quasi-static
//   clk60 signals.
//
// Clocking: clk60, active-low asynchronous reset rst_n.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_rx_fsls_dpll #(
    parameter FS_DIV = 40,            // samples per FS bit (>= 16)
    parameter LS_DIV = 320,           // samples per LS bit
    parameter DIV_W  = 9
) (
    input  wire       clk60,
    input  wire       rst_n,

    input  wire [7:0] rcv_v,
    input  wire [7:0] dp_v,
    input  wire [7:0] dm_v,
    input  wire       ls,             // 1 = LS (polarity, bit rate), 0 = FS
    input  wire       enable,

    output reg        b_en,
    output reg        b_lvl,
    output reg        b_se0,
    output reg        b_act
);

    // synthesis translate_off
    initial if (FS_DIV < 16 || LS_DIV < 16) begin
        $display("usb_rx_fsls_dpll: FS_DIV / LS_DIV must be >= 16");
        $finish;
    end
    // synthesis translate_on

    reg [7:0]       rcv_q, dp_q, dm_q;   // sampler word, registered on clk60
    reg             se0_q, lvl_q;     // symbol of the previous sample
    reg [DIV_W-1:0] cnt;

    wire [DIV_W-1:0] div_m1 = ls ? (LS_DIV - 1) : (FS_DIV - 1);
    wire [DIV_W-1:0] half   = ls ? (LS_DIV / 2) : (FS_DIV / 2);

    integer i;
    reg [7:0] se0, lvl, chg, stb;
    reg       sp, lp, nc, any;
    reg       s_lvl, s_se0;
    reg [DIV_W-1:0] cnt_n;
    reg [3:0] lastj;

    always @* begin
        for (i = 0; i < 8; i = i + 1) begin
            se0[i] = !dp_q[i] && !dm_q[i];
            lvl[i] = ls ? !rcv_q[i] : rcv_q[i];
        end
        for (i = 0; i < 8; i = i + 1) begin
            sp     = (i == 0) ? se0_q : se0[i-1];
            lp     = (i == 0) ? lvl_q : lvl[i-1];
            chg[i] = (se0[i] != sp) || (!se0[i] && (lvl[i] != lp));
        end
        nc = 1'b1;
        s_lvl = 1'b0; s_se0 = 1'b0;
        for (i = 0; i < 8; i = i + 1) begin
            nc     = nc & !chg[i];
            stb[i] = nc && (cnt == half - i);
            s_lvl  = s_lvl | (stb[i] & lvl[i]);
            s_se0  = s_se0 | (stb[i] & se0[i]);
        end
        // carried count
        any = |chg;
        lastj = 4'd0;
        for (i = 0; i < 8; i = i + 1) if (chg[i]) lastj = i;
        if (any)                    cnt_n = 4'd8 - lastj;
        else if (cnt + 8 <= div_m1) cnt_n = cnt + 4'd8;
        else if (cnt >= div_m1)     cnt_n = 4'd7;
        else                        cnt_n = cnt + 4'd7 - div_m1;
    end

    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            rcv_q <= 8'hFF;
            dp_q  <= 8'h00;
            dm_q  <= 8'h00;
            se0_q <= 1'b1;
            lvl_q <= 1'b1;
            cnt   <= {DIV_W{1'b0}};
            b_en  <= 1'b0;
            b_lvl <= 1'b1;
            b_se0 <= 1'b0;
            b_act <= 1'b0;
        end else begin
            rcv_q <= rcv_v;
            dp_q  <= dp_v;
            dm_q  <= dm_v;
            se0_q <= se0[7];
            lvl_q <= lvl[7];
            cnt   <= cnt_n;
            b_en  <= |stb;
            if (|stb) begin
                b_lvl <= s_lvl;
                b_se0 <= s_se0;
                b_act <= enable;
            end
        end
    end

endmodule
