//-----------------------------------------------------------------------------
// usb_afe_tx_if8.v - TX data boundary to the AFE, 60 MHz part
//                    (Plan_60MHz.md 4.2, P6; spec DOC/afe_interface_spec.md 3.1,
//                    3.4, 4.1)
//
//   usb_tx_serializer8 --txd_v / tx_en_v / tx_se0_v, tx_speed--> [THIS BLOCK]
//        --pin vectors (8 bits per tick)--> usb_tx_piso (clk_bit) --> HS TX, FS/LS
//
// The bit-serial usb_afe_tx_if (kept as the reference model of tb_usb_tx_vec)
// split in two: everything except the last flop stage runs here on clk60 and
// works on 8-bit vectors; usb_tx_piso shifts the vectors out at 480 MHz and
// holds the idle clamp.  Every output bit is the old pin value of the same
// bit time: output register after tick T+1's edge, bit i = the old
// usb_afe_tx_if pin after clk_bit edge 8T + 4 + i, for the serializer vector of
// tick T (old serializer edges 8T + 2 + i).  The PISO adds 9 clk_bit cycles
// (load on ld = E4, output flop), so the pins come LAT = 9 cycles after those of
// the single-clock chain (usb_tx_serializer + usb_afe_tx_if); tb_usb_tx_vec
// checks that cycle for cycle.
//
// Function (as usb_afe_tx_if, per bit; see its header)
//   * driver select from tx_speed: 00 HS current driver, 01 / 11 FS, 10 LS;
//   * TX_EN lead: the data of all speeds is delayed by tx_lead bit times, the
//     HS enable is not, so hs_tx_en rises tx_lead bits before the first SYNC
//     bit.  The delay is a 40-bit window (this vector + 4 previous) read at
//     offset tx_lead (a static 32:1 select per bit);
//   * TX_EN lag: hs_tx_en stays high tx_lag bits after the last HS bit (the
//     delayed HS enable dilated by tx_lag, with the previous vector);
//   * hs_tx_p during the lead: J, or with lead_first = 1 the level of the first
//     data bit; during the lag: the EOP level held.  An 8-step chain per tick
//     with the last bit of the previous tick as carry (the old per-bit
//     recurrence, unrolled);
//   * fs_oe / fs_dat / fs_se0 from the delayed FS/LS bits; fs_ls_q = LS
//     (applied by the PISO when an FS/LS bit is driven);
//   * tx_lead / tx_lag taken over after 16 ticks (128 bit times) without a
//     serializer bit, i.e. with the window empty.
//   The idle clamp (drv_dis, iso_en) is not here: usb_tx_piso forces the pins
//   at bit rate and drops the rest of the interrupted packet itself.
//
// act: a driver enable is pending anywhere in here (serializer vector, window,
//   lag, output register); usb_tx_piso samples it on ld for tx_active.
//
// Clock: clk60 (port named so the SDC times it); inputs / outputs clk60 domain.  Reset rst_n, asynchronous.
//-----------------------------------------------------------------------------
`timescale 1ns/1ps

module usb_afe_tx_if8 #(
    parameter LEAD_W = 5,                    // tx_lead width: 0 .. 31 (window: 4 previous vectors)
    parameter LAG_W  = 3                     // tx_lag width:  0 .. 7
) (
    input  wire              clk60,
    input  wire              rst_n,

    // from usb_tx_serializer8 (registers)
    input  wire [7:0]        txd_v,
    input  wire [7:0]        tx_en_v,
    input  wire [7:0]        tx_se0_v,
    input  wire [1:0]        tx_speed,

    // configuration
    input  wire [LEAD_W-1:0] tx_lead,
    input  wire [LAG_W-1:0]  tx_lag,
    input  wire              lead_first,

    // pin vectors for usb_tx_piso (bit 0 first)
    output reg  [7:0]        hs_p_v,         // TX_IN_P (TX_IN_N = complement, in the PISO)
    output reg  [7:0]        hs_en_v,        // TX_EN
    output reg  [7:0]        fs_oe_v,
    output reg  [7:0]        fs_dat_v,
    output reg  [7:0]        fs_se0_v,
    output reg  [7:0]        any_v,          // hs_en_v | fs_oe_v (PISO: end of a dropped packet)
    output reg               fs_ls_q,        // LS slew rate of the FS/LS bits
    output wire              act             // a driver enable is pending (for tx_active)
);

    // history: previous 4 serializer vectors (h1 = last tick)
    reg [7:0] h1_e, h2_e, h3_e, h4_e;
    reg [7:0] h1_d, h2_d, h3_d, h4_d;
    reg [7:0] h1_s, h2_s, h3_s, h4_s;
    // carries from the previous tick
    reg [7:0] oh_p;                          // delayed HS enable (lag dilation)
    reg       a_p, df_p, hen_p, hp_p;
    reg       sp_hs, sp_ls;                  // speed of the latest serializer bit
    // configuration
    // ~tx_lead as taken over, one copy per output bit for its 32:1 window select (fanout:
    // Yosys does not buffer).  Own process with (* keep *): Yosys copies process
    // attributes to the flops, so opt_merge leaves the 8 copies apart.
    reg [8*LEAD_W-1:0] nlead_b;
    reg [LAG_W-1:0]  lag_q;
    reg [4:0]        quiet;                  // idle ticks, saturating at 16

    // flat windows, bit 32 + k = stream offset k (-32 .. 7) of this tick
    wire [39:0] w_e = {tx_en_v,  h1_e, h2_e, h3_e, h4_e};
    wire [39:0] w_d = {txd_v,    h1_d, h2_d, h3_d, h4_d};
    wire [39:0] w_s = {tx_se0_v, h1_s, h2_s, h3_s, h4_s};

    wire       en_any = |tx_en_v;
    wire       sph    = en_any ? (tx_speed == 2'b00) : sp_hs;
    wire       spl    = en_any ? (tx_speed == 2'b10) : sp_ls;

    // undelayed HS enable / data at offset i-1 (lead start)
    wire [7:0] a  = w_e[38:31] & {8{tx_speed == 2'b00}};
    wire [7:0] ad = w_d[38:31];
    // delayed by the lead: offset i-1-lead
    // bit b = window bit 31 + b - lead = (w[b +: 32])[31 - lead] = (w[b +: 32])[~lead]
    wire [7:0] o, od, ose;
    genvar gb;
    generate for (gb = 0; gb < 8; gb = gb + 1) begin : g_sel
        wire [31:0] se = w_e[gb +: 32], sd = w_d[gb +: 32], ss = w_s[gb +: 32];
        wire [4:0]  nl = nlead_b[gb*LEAD_W +: LEAD_W];
        assign o[gb]   = se[nl];
        assign od[gb]  = sd[nl];
        assign ose[gb] = ss[nl];
    end endgenerate
    wire [7:0] oh  = o & {8{sph}};
    wire [7:0] of  = o & {8{~sph}};

    // lag: hen[i] = a[i] | OR_{j = 0 .. lag} oh(i - j)
    wire [15:0] ohx = {oh, oh_p};
    reg  [7:0]  hen;
    reg  [7:0]  df, hp;
    reg         dfc, hpc, enc, ac;
    integer     i, j;
    always @* begin
        for (i = 0; i < 8; i = i + 1) begin
            hen[i] = a[i];
            for (j = 0; j < 8; j = j + 1)
                if (j <= lag_q) hen[i] = hen[i] | ohx[8 + i - j];
        end
        // first-bit level (d_first) and hs_tx_p, per bit in order
        dfc = df_p; hpc = hp_p; enc = hen_p; ac = a_p;
        for (i = 0; i < 8; i = i + 1) begin
            dfc   = (a[i] & ~ac) ? ad[i] : dfc;
            df[i] = dfc;
            hpc   = oh[i] ? od[i] : hen[i] ? (enc ? hpc : (lead_first ? dfc : 1'b1)) : 1'b1;
            hp[i] = hpc;
            enc   = hen[i];
            ac    = a[i];
        end
    end

    assign act = en_any | (|h1_e) | (|h2_e) | (|h3_e) | (|h4_e) | (|oh_p) | (|hs_en_v) | (|fs_oe_v);

    wire take = quiet[4] & ~en_any;          // configuration takeover (window empty)
    (* keep *)
    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n)    nlead_b <= {8*LEAD_W{1'b1}};
        else if (take) nlead_b <= {8{~tx_lead}};
    end

    always @(posedge clk60 or negedge rst_n) begin
        if (!rst_n) begin
            h1_e <= 8'h00; h2_e <= 8'h00; h3_e <= 8'h00; h4_e <= 8'h00;
            h1_d <= 8'hFF; h2_d <= 8'hFF; h3_d <= 8'hFF; h4_d <= 8'hFF;
            h1_s <= 8'h00; h2_s <= 8'h00; h3_s <= 8'h00; h4_s <= 8'h00;
            oh_p <= 8'h00; a_p <= 1'b0; df_p <= 1'b1; hen_p <= 1'b0; hp_p <= 1'b1;
            sp_hs <= 1'b0; sp_ls <= 1'b0;
            lag_q <= {LAG_W{1'b0}}; quiet <= 5'd0;
            hs_p_v <= 8'hFF; hs_en_v <= 8'h00; fs_oe_v <= 8'h00; fs_dat_v <= 8'hFF;
            fs_se0_v <= 8'h00; any_v <= 8'h00; fs_ls_q <= 1'b0;
        end else begin
            h1_e <= tx_en_v;  h2_e <= h1_e; h3_e <= h2_e; h4_e <= h3_e;
            h1_d <= txd_v;    h2_d <= h1_d; h3_d <= h2_d; h4_d <= h3_d;
            h1_s <= tx_se0_v; h2_s <= h1_s; h3_s <= h2_s; h4_s <= h3_s;
            oh_p <= oh; a_p <= a[7]; df_p <= df[7]; hen_p <= hen[7]; hp_p <= hp[7];
            sp_hs <= sph; sp_ls <= spl;

            // configuration, only while the window is empty
            quiet <= en_any ? 5'd0 : (quiet[4] ? quiet : quiet + 5'd1);
            if (take) begin
                lag_q  <= tx_lag;
            end

            hs_p_v   <= hp;
            hs_en_v  <= hen;
            fs_oe_v  <= of;
            fs_dat_v <= ~of | od;
            fs_se0_v <= of & ose;
            any_v    <= hen | of;
            if (|of) fs_ls_q <= spl;
        end
    end

endmodule
