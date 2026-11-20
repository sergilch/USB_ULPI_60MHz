// md2docx.js - converts DOC/Description/USB_ULPI_PHY_Verilog_Modules.md to .docx
//
// Usage (needs Node.js and the npm package "docx", tested with 9.15.4):
//   npm install docx            # in any directory, e.g. a scratch dir
//   NODE_PATH=<that dir>/node_modules node DOC/Description/md2docx.js \
//       DOC/Description/USB_ULPI_PHY_Verilog_Modules.md \
//       DOC/Description/USB_ULPI_PHY_Verilog_Modules.docx
//
// Supports only the Markdown subset used by the description: headings (# title,
// ## chapter, ### section, #### module), paragraphs, bullet / numbered lists,
// tables, fenced code blocks, --- rules, inline `code` / ``code with ` `` /
// **bold** / *italic*, [links](url) (rendered as their text), and images on a
// line of their own: ![caption](fig/x.svg) embeds fig/x.png (the PNG next to the
// referenced file, path relative to the Markdown file) at full text width,
// with the caption centred below it.
// Optional third argument: footer text (default: the description's footer), e.g.
//   node DOC/Description/md2docx.js in.md out.docx "Mass-storage test"
// Output: A4, table of contents before chapter 1 (Word fills it on opening).
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, LevelFormat, AlignmentType, Footer, PageNumber,
  TableOfContents, ImageRun,
} = require('docx');
const path = require('path');

const [, , inPath, outPath, footerText = 'USB 2.0 ULPI PHY — Verilog modules'] = process.argv;
const lines = fs.readFileSync(inPath, 'utf8').split('\n');

const FONT = 'Calibri', MONO = 'Consolas';
const PAGE_W = 11906, MARGIN = 1134, CONTENT_W = PAGE_W - 2 * MARGIN; // A4, 2 cm margins

function inline(text, base = {}) {
  const runs = [];
  const re = /(\[[^\]]+\]\([^)]+\)|``.+?``|`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) runs.push(new TextRun({ text: text.slice(last, m.index), font: FONT, ...base }));
    const t = m[0];
    if (t.startsWith('[')) runs.push(...inline(t.slice(1, t.indexOf('](')), base));
    else if (t.startsWith('``')) runs.push(new TextRun({ text: t.slice(2, -2).trim(), font: MONO, size: (base.size || 21) - 2, color: '8B1A1A', bold: base.bold, italics: base.italics }));
    else if (t.startsWith('`')) runs.push(new TextRun({ text: t.slice(1, -1), font: MONO, size: (base.size || 21) - 2, color: '8B1A1A', bold: base.bold, italics: base.italics }));
    else if (t.startsWith('**')) runs.push(...inline(t.slice(2, -2), { ...base, bold: true }));
    else runs.push(...inline(t.slice(1, -1), { ...base, italics: true }));
    last = m.index + t.length;
  }
  if (last < text.length) runs.push(new TextRun({ text: text.slice(last), font: FONT, ...base }));
  return runs;
}

const border = { style: BorderStyle.SINGLE, size: 4, color: 'A6A6A6' };
const borders = { top: border, bottom: border, left: border, right: border };

function splitRow(l) {
  return l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
}

function makeTable(rows) {
  const header = rows[0], body = rows.slice(2);
  const n = header.length;
  // column widths: each column at least as wide as its longest word (no
  // words broken across lines), the rest shared in proportion to the
  // column's longest cell text (bounded)
  const all = [header, ...body];
  const plain = s => (s || '').replace(/[`*]/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  const CH = 115, PAD = 230;  // approx. DXA per character at 10 pt, cell padding
  const want = Array.from({ length: n }, (_, i) =>
    Math.min(60, Math.max(6, ...all.map(r => plain(r[i]).length))) * CH + PAD);
  const minW = Array.from({ length: n }, (_, i) =>
    Math.min(28, Math.max(3, ...all.map(r => Math.max(0, ...plain(r[i]).split(/\s+/).map(w => w.length))))) * CH + PAD);
  const minSum = minW.reduce((a, b) => a + b, 0);
  let widths;
  if (minSum >= CONTENT_W) {
    widths = minW.map(w => Math.floor(CONTENT_W * w / minSum));
  } else {
    const extra = want.map((w, i) => Math.max(0, w - minW[i]));
    const exSum = extra.reduce((a, b) => a + b, 0);
    widths = minW.map((w, i) => Math.floor(w + (CONTENT_W - minSum) * (exSum ? extra[i] / exSum : 1 / n)));
  }
  widths[n - 1] += CONTENT_W - widths.reduce((a, b) => a + b, 0);
  const cell = (txt, i, isHead) => new TableCell({
    borders, width: { size: widths[i], type: WidthType.DXA },
    shading: isHead ? { fill: 'D9E2F3', type: ShadingType.CLEAR, color: 'auto' } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ spacing: { before: 0, after: 0 }, children: inline(txt || '', { size: 19, bold: isHead }) })],
  });
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    rows: [
      new TableRow({ tableHeader: true, children: header.map((c, i) => cell(c, i, true)) }),
      ...body.map(r => new TableRow({ children: Array.from({ length: n }, (_, i) => cell(r[i], i, false)) })),
    ],
  });
}

const children = [];
let i = 0, title = null, numId = 0;
while (i < lines.length) {
  const l = lines[i];
  if (/^```/.test(l)) {
    i++;
    const code = [];
    while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
    i++;
    code.forEach((c, k) => children.push(new Paragraph({
      shading: { fill: 'F2F2F2', type: ShadingType.CLEAR, color: 'auto' },
      spacing: { before: k === 0 ? 120 : 0, after: k === code.length - 1 ? 120 : 0, line: 240 },
      indent: { left: 113 },
      children: [new TextRun({ text: c.length ? c : ' ', font: MONO, size: 16 })],
    })));
    continue;
  }
  if (/^\|/.test(l)) {
    const rows = [];
    while (i < lines.length && /^\|/.test(lines[i])) rows.push(splitRow(lines[i++]));
    children.push(makeTable(rows));
    children.push(new Paragraph({ spacing: { before: 0, after: 60 }, children: [] }));
    continue;
  }
  let m;
  if ((m = /^(#{1,4}) (.*)$/.exec(l))) {
    const lvl = m[1].length;
    if (lvl === 1 && !title) {
      title = m[2];
      children.push(new Paragraph({ heading: HeadingLevel.TITLE, children: inline(m[2], { size: 40, bold: true, color: '1F3864' }) }));
    } else {
      const H = [null, HeadingLevel.HEADING_1, HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3][lvl];
      if (lvl === 2 && /^1\. /.test(m[2])) {
        // insert a table of contents before the first chapter
        children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: 'Contents', font: FONT })] }));
        children.push(new TableOfContents('Contents', { hyperlink: true, headingStyleRange: '1-3' }));
      }
      children.push(new Paragraph({ heading: H, children: inline(m[2]) }));
    }
    i++; continue;
  }
  if ((m = /^!\[([^\]]*)\]\(([^)]+)\)\s*$/.exec(l))) {
    const png = path.resolve(path.dirname(inPath), m[2].replace(/\.svg$/i, '.png'));
    const data = fs.readFileSync(png);
    const w0 = data.readUInt32BE(16), h0 = data.readUInt32BE(20);   // PNG IHDR
    const w = Math.round(CONTENT_W / 15), h = Math.round(w * h0 / w0); // twips -> px at 96 dpi
    children.push(new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 120, after: 40 },
      children: [new ImageRun({ type: 'png', data, transformation: { width: w, height: h } })] }));
    if (m[1]) children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
      children: inline(m[1], { size: 18, italics: true, color: '404040' }) }));
    i++; continue;
  }
  if (/^---\s*$/.test(l)) {
    children.push(new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: '8EAADB', space: 1 } }, children: [] }));
    i++; continue;
  }
  if ((m = /^(\s*)- (.*)$/.exec(l))) {
    children.push(new Paragraph({ numbering: { reference: 'bullets', level: Math.min(1, Math.floor(m[1].length / 2)) }, spacing: { after: 40 }, children: inline(m[2]) }));
    i++; continue;
  }
  if ((m = /^(\d+)\. (.*)$/.exec(l))) {
    // restart numbering for each separate list
    if (!/^\d+\. /.test(lines[i - 1] || '')) numId++;
    children.push(new Paragraph({ numbering: { reference: 'num' + numId, level: 0 }, spacing: { after: 40 }, children: inline(m[2]) }));
    i++; continue;
  }
  if (l.trim() === '') { i++; continue; }
  // paragraph: join following plain lines
  const para = [l];
  i++;
  while (i < lines.length && lines[i].trim() !== '' && !/^(#|\||```|\s*- |\d+\. |---|!\[)/.test(lines[i])) para.push(lines[i++]);
  children.push(new Paragraph({ spacing: { after: 120 }, children: inline(para.join(' ')) }));
}


function heading(size, color, before, after) {
  return { run: { font: FONT, size, bold: true, color }, paragraph: { spacing: { before, after }, keepNext: true, keepLines: true } };
}
const numConfigs = [{ reference: 'bullets', levels: [
  { level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 567, hanging: 283 } } } },
  { level: 1, format: LevelFormat.BULLET, text: '–', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1134, hanging: 283 } } } },
] }];
for (let k = 1; k <= 40; k++) numConfigs.push({ reference: 'num' + k, levels: [
  { level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 567, hanging: 340 } } } }] });

const doc = new Document({
  creator: 'USB_60 project', title: title || 'Description',
  features: { updateFields: true },
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: 'Title', name: 'Title', basedOn: 'Normal', run: { font: FONT, size: 40, bold: true, color: '1F3864' }, paragraph: { spacing: { before: 0, after: 200 }, keepNext: true } },
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, ...heading(32, '1F3864', 360, 160), paragraph: { spacing: { before: 360, after: 160 }, keepNext: true, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, ...heading(28, '2F5496', 300, 120), paragraph: { spacing: { before: 300, after: 120 }, keepNext: true, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true, ...heading(24, '2F5496', 240, 100), paragraph: { spacing: { before: 240, after: 100 }, keepNext: true, outlineLevel: 2 } },
      { id: 'Heading4', name: 'Heading 4', basedOn: 'Normal', next: 'Normal', quickFormat: true, ...heading(22, '404040', 200, 80), paragraph: { spacing: { before: 200, after: 80 }, keepNext: true, outlineLevel: 3 } },
    ],
  },
  numbering: { config: numConfigs },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: 16838 }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
      new TextRun({ text: footerText + '    Page ', font: FONT, size: 16, color: '808080' }),
      new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: '808080' })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then(b => { fs.writeFileSync(outPath, b); console.log('written', outPath); });
