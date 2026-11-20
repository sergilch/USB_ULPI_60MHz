"""svgplot.py - minimal SVG line-plot helper for the PLL datasheet figures
(numpy only; matplotlib is not installed on the development machine).

Plot(w, h).panel(x, y, w, h, ...) creates axes; Axes.line / .points / .hline /
.vline / .text draw into them; Plot.save(path) writes the SVG.  Linear or log
axes, automatic 1-2-5 ticks, legends.
"""
import math
import numpy as np

FONT = "Arial, Helvetica, sans-serif"
COLORS = ["#1f4e9c", "#c0392b", "#2e8b57", "#d4860b", "#6c3483", "#555555"]


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def nice_ticks(lo, hi, n=6):
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=10 * mag)
    first = math.ceil(lo / step - 1e-9) * step
    out, v = [], first
    while v <= hi + step * 1e-9:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
    return out


def fmt(v):
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1e4 or a < 1e-3:
        e = int(math.floor(math.log10(a)))
        m = v / 10 ** e
        return (f"{m:g}·" if abs(m - 1) > 1e-9 else "") + f"10^{e}"
    s = f"{v:.6g}"
    return s


def log_label(v):
    pre = {1e-12: "1p", 1e-9: "1n", 1e-6: "1µ", 1e-3: "1m", 1: "1", 1e3: "1k", 1e6: "1M", 1e9: "1G", 1e12: "1T"}
    for k, s in pre.items():
        if abs(v / k - 1) < 1e-6:
            return s
    for k, s in pre.items():
        r = v / k
        if 1 < r < 1000 and abs(r - round(r)) < 1e-6:
            return f"{int(round(r))}{s[1:]}"
    return f"{v:g}"


class Axes:
    def __init__(self, plot, x, y, w, h, xlim, ylim, xlog=False, ylog=False,
                 xlabel="", ylabel="", title="", xticks=None, yticks=None,
                 xfmt=None, yfmt=None, legend="tr"):
        self.p, self.x0, self.y0, self.w, self.h = plot, x, y, w, h
        self.xlim, self.ylim, self.xlog, self.ylog = xlim, ylim, xlog, ylog
        self.items, self.leg, self.legpos = [], [], legend
        self.xfmt = xfmt or (log_label if xlog else fmt)
        self.yfmt = yfmt or (log_label if ylog else fmt)
        self._frame(xlabel, ylabel, title, xticks, yticks)

    def _tx(self, v):
        a, b = self.xlim
        if self.xlog:
            v, a, b = np.log10(v), math.log10(a), math.log10(b)
        return self.x0 + (v - a) / (b - a) * self.w

    def _ty(self, v):
        a, b = self.ylim
        if self.ylog:
            v, a, b = np.log10(v), math.log10(a), math.log10(b)
        return self.y0 + self.h - (v - a) / (b - a) * self.h

    def _ticks(self, lim, log, given):
        if given is not None:
            return given, []
        if log:
            a, b = math.floor(math.log10(lim[0]) + 1e-9), math.ceil(math.log10(lim[1]) - 1e-9)
            major = [10 ** e for e in range(a, b + 1) if lim[0] * 0.999 <= 10 ** e <= lim[1] * 1.001]
            minor = [m * 10 ** e for e in range(a - 1, b + 1) for m in range(2, 10)
                     if lim[0] < m * 10 ** e < lim[1]]
            return major, minor
        return nice_ticks(*lim), []

    def _frame(self, xlabel, ylabel, title, xticks, yticks):
        s = self.p.s
        x0, y0, w, h = self.x0, self.y0, self.w, self.h
        xt, xm = self._ticks(self.xlim, self.xlog, xticks)
        yt, ym = self._ticks(self.ylim, self.ylog, yticks)
        for v in xm:
            X = self._tx(v); s.append(f'<line x1="{X:.1f}" y1="{y0}" x2="{X:.1f}" y2="{y0 + h}" stroke="#eeeeee"/>')
        for v in ym:
            Y = self._ty(v); s.append(f'<line x1="{x0}" y1="{Y:.1f}" x2="{x0 + w}" y2="{Y:.1f}" stroke="#eeeeee"/>')
        for v in xt:
            X = self._tx(v)
            s.append(f'<line x1="{X:.1f}" y1="{y0}" x2="{X:.1f}" y2="{y0 + h}" stroke="#d8d8d8"/>')
            s.append(f'<text x="{X:.1f}" y="{y0 + h + 17}" font-size="12" text-anchor="middle">{_esc(self.xfmt(v))}</text>')
        for v in yt:
            Y = self._ty(v)
            s.append(f'<line x1="{x0}" y1="{Y:.1f}" x2="{x0 + w}" y2="{Y:.1f}" stroke="#d8d8d8"/>')
            s.append(f'<text x="{x0 - 6}" y="{Y + 4:.1f}" font-size="12" text-anchor="end">{_esc(self.yfmt(v))}</text>')
        s.append(f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="none" stroke="#333333"/>')
        if xlabel:
            s.append(f'<text x="{x0 + w / 2}" y="{y0 + h + 36}" font-size="13" text-anchor="middle">{_esc(xlabel)}</text>')
        if ylabel:
            s.append(f'<text transform="translate({x0 - 52},{y0 + h / 2}) rotate(-90)" font-size="13" '
                     f'text-anchor="middle">{_esc(ylabel)}</text>')
        if title:
            s.append(f'<text x="{x0}" y="{y0 - 8}" font-size="13" font-weight="bold">{_esc(title)}</text>')
        s.append(f'<clipPath id="c{id(self)}"><rect x="{x0}" y="{y0}" width="{w}" height="{h}"/></clipPath>')

    def line(self, x, y, color=None, width=2.0, dash=None, label=None):
        color = color or COLORS[len(self.leg) % len(COLORS)]
        x, y = np.asarray(x, float), np.asarray(y, float)
        ok = np.isfinite(x) & np.isfinite(y)
        if self.xlog: ok &= x > 0
        if self.ylog: ok &= y > 0
        pts = " ".join(f"{a:.2f},{b:.2f}" for a, b in zip(self._tx(x[ok]), self._ty(y[ok])))
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.p.s.append(f'<polyline clip-path="url(#c{id(self)})" points="{pts}" fill="none" stroke="{color}" '
                        f'stroke-width="{width}"{d} stroke-linejoin="round"/>')
        if label:
            self.leg.append((label, color, dash, "line"))
        return self

    def points(self, x, y, color=None, label=None, r=4.5, marker="o"):
        color = color or COLORS[len(self.leg) % len(COLORS)]
        for a, b in zip(x, y):
            if not (np.isfinite(a) and np.isfinite(b)):
                continue
            self.p.s.append(_mark(self._tx(a), self._ty(b), r, color, marker))
        if label:
            self.leg.append((label, color, None, marker))
        return self

    def hline(self, v, color="#888888", dash="5,4", label=None, text=None, anchor="end", below=False):
        Y = self._ty(v)
        self.p.s.append(f'<line x1="{self.x0}" y1="{Y:.1f}" x2="{self.x0 + self.w}" y2="{Y:.1f}" stroke="{color}" stroke-width="1.3" stroke-dasharray="{dash}"/>')
        if text:
            X = self.x0 + self.w - 4 if anchor == "end" else self.x0 + 4
            self.p.s.append(f'<text x="{X}" y="{Y + (14 if below else -4):.1f}" font-size="11" fill="{color}" text-anchor="{anchor}">{_esc(text)}</text>')
        if label:
            self.leg.append((label, color, dash, "line"))
        return self

    def vline(self, v, color="#888888", dash="5,4", text=None, top=True, left=False):
        X = self._tx(v)
        self.p.s.append(f'<line x1="{X:.1f}" y1="{self.y0}" x2="{X:.1f}" y2="{self.y0 + self.h}" stroke="{color}" stroke-width="1.3" stroke-dasharray="{dash}"/>')
        if text:
            Y = self.y0 + 14 if top else self.y0 + self.h - 6
            a = "end" if left else "start"
            self.p.s.append(f'<text x="{X + (-4 if left else 4):.1f}" y="{Y}" font-size="11" fill="{color}" text-anchor="{a}">{_esc(text)}</text>')
        return self

    def band(self, lo, hi, color="#2e8b57", opacity=0.10):
        Y1, Y2 = self._ty(hi), self._ty(lo)
        self.p.s.append(f'<rect x="{self.x0}" y="{Y1:.1f}" width="{self.w}" height="{Y2 - Y1:.1f}" fill="{color}" fill-opacity="{opacity}"/>')
        return self

    def text(self, x, y, s, color="#222222", size=11, anchor="start", data=True):
        X, Y = (self._tx(x), self._ty(y)) if data else (x, y)
        self.p.s.append(f'<text x="{X:.1f}" y="{Y:.1f}" font-size="{size}" fill="{color}" text-anchor="{anchor}">{_esc(s)}</text>')
        return self

    def marker(self, x, y, s=None, color="#222222", dx=6, dy=-6, anchor="start"):
        X, Y = self._tx(x), self._ty(y)
        self.p.s.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="3.5" fill="{color}"/>')
        if s:
            self.p.s.append(f'<text x="{X + dx:.1f}" y="{Y + dy:.1f}" font-size="11" fill="{color}" text-anchor="{anchor}">{_esc(s)}</text>')
        return self

    def legend(self, pos=None):
        pos = pos or self.legpos
        if not self.leg:
            return
        wbox = max(len(l[0]) for l in self.leg) * 6.4 + 42
        hbox = 18 * len(self.leg) + 8
        X = self.x0 + self.w - wbox - 8 if "r" in pos else self.x0 + 8
        Y = self.y0 + 8 if "t" in pos else self.y0 + self.h - hbox - 8
        s = self.p.s
        s.append(f'<rect x="{X}" y="{Y}" width="{wbox}" height="{hbox}" fill="white" fill-opacity="0.92" stroke="#bbbbbb"/>')
        for i, (lab, col, dash, kind) in enumerate(self.leg):
            yy = Y + 16 + 18 * i
            if kind == "line":
                d = f' stroke-dasharray="{dash}"' if dash else ""
                s.append(f'<line x1="{X + 8}" y1="{yy - 4}" x2="{X + 30}" y2="{yy - 4}" stroke="{col}" stroke-width="2"{d}/>')
            else:
                s.append(_mark(X + 19, yy - 4, 4, col, kind))
            s.append(f'<text x="{X + 36}" y="{yy}" font-size="11.5">{_esc(lab)}</text>')


def _mark(X, Y, r, color, marker):
    if marker == "s":
        return f'<rect x="{X - r:.1f}" y="{Y - r:.1f}" width="{2 * r}" height="{2 * r}" fill="white" stroke="{color}" stroke-width="1.8"/>'
    if marker == "^":
        return f'<polygon points="{X:.1f},{Y - r - 1:.1f} {X - r:.1f},{Y + r:.1f} {X + r:.1f},{Y + r:.1f}" fill="white" stroke="{color}" stroke-width="1.8"/>'
    return f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="{r}" fill="white" stroke="{color}" stroke-width="1.8"/>'


class Plot:
    def __init__(self, w=900, h=480):
        self.w, self.h, self.s = w, h, []
        self.axes = []

    def panel(self, *a, **k):
        ax = Axes(self, *a, **k)
        self.axes.append(ax)
        return ax

    def raw(self, svg):
        self.s.append(svg)

    def save(self, path):
        for ax in self.axes:
            ax.legend()
        body = "\n".join(self.s)
        open(path, "w").write(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" font-family="{FONT}">\n'
            f'<rect width="{self.w}" height="{self.h}" fill="white"/>\n{body}\n</svg>\n')
