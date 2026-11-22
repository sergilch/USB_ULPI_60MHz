#!/usr/bin/env python3
"""md2html.py - ldo_description.md -> ldo_description.html

    python3 "AFE/LDO analog part/doc/md2html.py" [in.md out.html]

Converts the Markdown subset of the description (headings, paragraphs, bullet /
numbered lists, tables, fenced code, inline code / bold / italic / links, and
images on their own line) into one self-contained page.  Images that point to
an .svg are inlined (the schematic sheets follow the page's light / dark theme
through currentColor); other images are linked.  Style: the same tokens as
AFE/doc/pll_schematic.html.  Rerun after editing the Markdown or the sheets.
"""
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)

CSS = """
:root { --bg:#f4f7f7; --panel:#ffffff; --fg:#17221f; --muted:#56655f; --rule:#cdd8d5; --accent:#0f7c80;
  --sans:"IBM Plex Sans", system-ui, sans-serif; --mono:"IBM Plex Mono", ui-monospace, monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg:#0f1514; --panel:#151d1c; --fg:#e3ebe8; --muted:#9aaba5; --rule:#2a3734; --accent:#4cc2c2; color-scheme:dark; } }
:root[data-theme="dark"] { --bg:#0f1514; --panel:#151d1c; --fg:#e3ebe8; --muted:#9aaba5; --rule:#2a3734;
  --accent:#4cc2c2; color-scheme:dark; }
* { box-sizing: border-box; }
body { background:var(--bg); color:var(--fg); font:15px/1.6 var(--sans); margin:0;
  padding:32px max(16px, env(safe-area-inset-right, 0px)) 64px max(16px, env(safe-area-inset-left, 0px)); }
main { max-width:1120px; margin:0 auto; display:grid; gap:18px; }
h1 { font:600 clamp(24px,4vw,34px)/1.2 var(--mono); margin:0; text-wrap:balance; }
h2 { font:600 20px/1.3 var(--mono); margin:26px 0 0; padding-top:14px; border-top:1px solid var(--rule); }
h3 { font:600 16px/1.3 var(--mono); margin:12px 0 0; color:var(--accent); }
p, li { max-width:80ch; }
p { margin:0; }
.lede { color:var(--muted); font-size:14px; }
code { font-family:var(--mono); font-size:.88em; background:color-mix(in srgb, var(--rule) 40%, transparent);
  padding:1px 4px; border-radius:3px; }
pre { background:var(--panel); border:1px solid var(--rule); border-radius:6px; padding:12px 14px; overflow-x:auto;
  font:12.5px/1.45 var(--mono); margin:0; }
pre code { background:none; padding:0; }
.tw { overflow-x:auto; border:1px solid var(--rule); border-radius:6px; background:var(--panel); }
table { border-collapse:collapse; width:100%; font-size:13.5px; }
th, td { text-align:left; vertical-align:top; padding:7px 10px; border-bottom:1px solid var(--rule); }
th { font:600 12.5px/1.3 var(--mono); color:var(--muted); background:color-mix(in srgb, var(--rule) 25%, transparent); }
tr:last-child td { border-bottom:none; }
td:first-child { white-space:nowrap; }
figure { margin:0; background:var(--panel); border:1px solid var(--rule); border-radius:6px; padding:14px;
  display:grid; gap:8px; min-width:0; }
figure svg { width:100%; height:auto; color:var(--fg); background:transparent !important; }
figcaption { font-size:13px; color:var(--muted); }
a { color:var(--accent); }
ul, ol { margin:0; padding-left:22px; display:grid; gap:4px; }
"""


def inline(s):
    out, parts = [], re.split(r"(``.+?``|`[^`]+`)", s)
    for p in parts:
        if p.startswith("``"):
            out.append("<code>" + html.escape(p[2:-2].strip()) + "</code>")
        elif p.startswith("`"):
            out.append("<code>" + html.escape(p[1:-1]) + "</code>")
        else:
            t = html.escape(p, quote=False)
            t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', t)
            t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
            t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
            out.append(t)
    return "".join(out)


def svg_inline(path, caption):
    s = open(path).read()
    s = re.sub(r"<\?xml[^>]*>", "", s)
    s = s.replace('style="background:#fff;color:#17221f"', "")
    # unique marker ids per sheet
    tag = re.sub(r"\W", "", os.path.basename(path))
    s = s.replace('id="ah"', f'id="ah{tag}"').replace('url(#ah)', f'url(#ah{tag})')
    s = s.replace('id="ah2"', f'id="ah2{tag}"').replace('url(#ah2)', f'url(#ah2{tag})')
    return f"<figure>{s}<figcaption>{inline(caption)}</figcaption></figure>"


def convert(md, base):
    lines = md.split("\n")
    out, i, title = [], 0, "Document"
    para = []

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    first_italic = True
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            flush()
            j = i + 1
            while not lines[j].startswith("```"):
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(lines[i + 1:j])) + "</code></pre>")
            i = j + 1
            continue
        m = re.match(r"^(#{1,4}) (.*)", ln)
        if m:
            flush()
            n = len(m.group(1))
            if n == 1:
                title = re.sub(r"[`*]", "", m.group(2))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
            i += 1
            continue
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", ln)
        if m:
            flush()
            p = os.path.join(base, m.group(2))
            if p.endswith(".svg") and os.path.exists(p):
                out.append(svg_inline(p, m.group(1)))
            else:
                out.append(f'<figure><img src="{m.group(2)}" alt="{html.escape(m.group(1))}">'
                           f"<figcaption>{inline(m.group(1))}</figcaption></figure>")
            i += 1
            continue
        if ln.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            h = "<tr>" + "".join(f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr>"
            b = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[2:])
            out.append(f'<div class="tw"><table><thead>{h}</thead><tbody>{b}</tbody></table></div>')
            continue
        m = re.match(r"^(\s*)([-*]|\d+\.) (.*)", ln)
        if m:
            flush()
            tagn = "ol" if m.group(2)[0].isdigit() else "ul"
            items = []
            while i < len(lines):
                m = re.match(r"^\s*([-*]|\d+\.) (.*)", lines[i])
                if m:
                    items.append(m.group(2))
                elif lines[i].strip() and lines[i].startswith("  ") and items:
                    items[-1] += " " + lines[i].strip()
                else:
                    break
                i += 1
            out.append(f"<{tagn}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tagn}>")
            continue
        if not ln.strip():
            flush()
            i += 1
            continue
        if first_italic and ln.startswith("*") and ln.rstrip().endswith("*") and not ln.startswith("**"):
            flush()
            out.append(f'<p class="lede">{inline(ln.strip()[1:-1])}</p>')
            first_italic = False
            i += 1
            continue
        para.append(ln.strip())
        i += 1
    flush()
    return title, "\n".join(out)


def main():
    src = sys.argv[1] if len(sys.argv) > 2 else os.path.join(BASE, "ldo_description.md")
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE, "ldo_description.html")
    title, body = convert(open(src).read(), os.path.dirname(os.path.abspath(src)))
    body = body.replace('href="ldo_description.html"', 'href="ldo_description.md"')
    page = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LDO Regulator 1.8 V</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{CSS}</style>
<main>
{body}
</main>
</html>
"""
    open(dst, "w").write(page)
    print("wrote", dst)


if __name__ == "__main__":
    main()
