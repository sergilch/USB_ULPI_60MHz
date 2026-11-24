// md2docx.js - converts tx_board.md into tx_board.docx (Microsoft Word)
//
//   node md2docx.js [in.md] [out.docx]        (needs the npm package "docx";
//   e.g. NODE_PATH=<dir>/node_modules node md2docx.js)
//
// Handles the Markdown subset used in tx_board.md: headings (# .. ####),
// paragraphs, bullet and numbered lists (one nested level), pipe tables,
// fenced code blocks, images (fig/*.svg is replaced by the PNG copy written by
// gen_figures.py), **bold**, *italic*, `code`.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, ImageRun, AlignmentType, LevelFormat, Footer,
  PageNumber, TableLayoutType,
} = require("docx");

const HERE = __dirname;
const IN = process.argv[2] || path.join(HERE, "tx_board.md");
const OUT = process.argv[3] || path.join(HERE, "tx_board.docx");
const PAGE_W = 11906, MARGIN = 1080, CONTENT_W = PAGE_W - 2 * MARGIN;   // A4, 0.75 in
const FONT = "Arial", MONO = "Consolas";

// ---------------------------------------------------------------- inline
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), font: FONT, ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, font: FONT, ...base }));
    else if (t.startsWith("`")) out.push(new TextRun({ text: t.slice(1, -1), font: MONO, ...base, size: (base.size || 21) - 2 }));
    else out.push(new TextRun({ text: t.slice(1, -1), italics: true, font: FONT, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), font: FONT, ...base }));
  return out;
}

// ---------------------------------------------------------------- blocks
function pngSize(file) {
  const b = fs.readFileSync(file);
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

function image(src) {
  const png = path.join(HERE, src.replace(/\.svg$/, ".png"));
  if (!fs.existsSync(png)) return new Paragraph({ children: runs("[missing figure " + src + "]") });
  const [w, h] = pngSize(png);
  const wpx = 640, hpx = Math.round(wpx * h / w);
  return new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true,
    children: [new ImageRun({ type: "png", data: fs.readFileSync(png), transformation: { width: wpx, height: hpx } })],
  });
}

const border = { style: BorderStyle.SINGLE, size: 4, color: "A0A0A0" };
const borders = { top: border, bottom: border, left: border, right: border };

function table(lines) {
  const rows = lines.filter((l, i) => i !== 1).map(l =>
    l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(c => c.trim()));
  const n = Math.max(...rows.map(r => r.length));
  const len = Array(n).fill(3);
  rows.forEach(r => r.forEach((c, i) => { len[i] = Math.max(len[i], Math.min(c.length, 60)); }));
  const tot = len.reduce((a, b) => a + b, 0);
  const widths = len.map(l => Math.max(500, Math.floor(CONTENT_W * l / tot)));
  const sum = widths.reduce((a, b) => a + b, 0);
  widths[widths.length - 1] += CONTENT_W - sum;
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths, layout: TableLayoutType.FIXED,
    rows: rows.map((r, ri) => new TableRow({
      tableHeader: ri === 0, cantSplit: true,
      children: widths.map((w, ci) => new TableCell({
        width: { size: w, type: WidthType.DXA }, borders,
        margins: { top: 40, bottom: 40, left: 80, right: 80 },
        shading: ri === 0 ? { fill: "DCE6F2", type: ShadingType.CLEAR, color: "auto" } : undefined,
        children: [new Paragraph({ children: runs(r[ci] || "", { size: 17, bold: ri === 0 ? true : undefined }) })],
      })),
    })),
  });
}

function code(lines) {
  return lines.map((l, i) => new Paragraph({
    spacing: { before: i === 0 ? 80 : 0, after: i === lines.length - 1 ? 120 : 0, line: 240 },
    shading: { fill: "F2F2F2", type: ShadingType.CLEAR, color: "auto" },
    children: [new TextRun({ text: l.length ? l : " ", font: MONO, size: 13 })],
  }));
}

// ---------------------------------------------------------------- parse
const src = fs.readFileSync(IN, "utf8").replace(/<!--[\s\S]*?-->/g, "").split("\n");
const body = [];
let i = 0, para = [], num = 0;
const flush = () => {
  if (para.length) body.push(new Paragraph({ spacing: { after: 120 }, children: runs(para.join(" ")) }));
  para = [];
};
while (i < src.length) {
  const l = src[i];
  if (/^```/.test(l)) {
    flush();
    const c = [];
    i++;
    while (i < src.length && !/^```/.test(src[i])) c.push(src[i++]);
    body.push(...code(c));
    i++;
    continue;
  }
  if (/^\|/.test(l)) {
    flush();
    const t = [];
    while (i < src.length && /^\|/.test(src[i])) t.push(src[i++]);
    body.push(table(t));
    body.push(new Paragraph({ spacing: { after: 60 }, children: [] }));
    continue;
  }
  let m;
  if ((m = /^(#{1,4}) (.*)/.exec(l))) {
    flush();
    const lv = m[1].length;
    if (lv === 1) body.push(new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun({ text: m[2], font: FONT })] }));
    else body.push(new Paragraph({
      heading: [HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3][lv - 2],
      children: [new TextRun({ text: m[2], font: FONT })],
    }));
  } else if ((m = /^!\[[^\]]*\]\(([^)]+)\)/.exec(l))) {
    flush();
    body.push(image(m[1]));
  } else if ((m = /^\*(Figure[^*]+)\*\s*$/.exec(l))) {
    flush();
    body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
      children: runs(m[1], { italics: true, size: 18 }) }));
  } else if ((m = /^(\s*)- (.*)/.exec(l))) {
    flush();
    body.push(new Paragraph({ numbering: { reference: "bul", level: m[1].length >= 2 ? 1 : 0 },
      spacing: { after: 60 }, children: runs(m[2]) }));
  } else if ((m = /^(\d+)\. (.*)/.exec(l))) {
    flush();
    // a numbered list restarts after any non-list block: one numbering instance per list
    if (!(i > 0 && /^(\d+\. |\s+- )/.test(src[i - 1]))) num++;
    body.push(new Paragraph({ numbering: { reference: "num", level: 0, instance: num },
      spacing: { after: 60 }, children: runs(m[2]) }));
  } else if (/^\s*$/.test(l)) {
    flush();
  } else {
    para.push(l.trim());
  }
  i++;
}
flush();

// ---------------------------------------------------------------- document
const H = (size, before, after) => ({ run: { font: FONT, size, bold: true, color: "1F3864" },
  paragraph: { spacing: { before, after }, keepNext: true } });
const doc = new Document({
  creator: "AFE/Discrete/Transmitter", title: "USB 2.0 discrete transmitter board",
  styles: {
    default: { document: { run: { font: FONT, size: 21 } },
      title: H(36, 0, 200), heading1: H(30, 360, 140), heading2: H(25, 260, 100), heading3: H(22, 200, 80) },
  },
  numbering: { config: [
    { reference: "bul", levels: [
      { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 540, hanging: 270 } } } },
      { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 1080, hanging: 270 } } } }] },
    { reference: "num", levels: [
      { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] },
  ] },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: 16838 },
      margin: { top: 1080, bottom: 1080, left: MARGIN, right: MARGIN } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "USB 2.0 discrete transmitter board – page ", font: FONT, size: 16 }),
                 new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16 })] })] }) },
    children: body,
  }],
});
Packer.toBuffer(doc).then(b => { fs.writeFileSync(OUT, b); console.log("wrote", OUT); });
