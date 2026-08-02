// Runs the REAL segregate()/readStream()/extractJson()/sliceRanges() lifted out of
// index.html against the live model server, so the shipped code path is tested.
// Not covered here: pdf.js text extraction and DOM rendering (browser-only).
import { readFileSync, readdirSync, mkdtempSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const app = html.match(/<script>\s*\n([\s\S]*?)<\/script>\s*<\/body>/)[1];

const cut = (a, b) => {
  const i = app.indexOf(a), j = app.indexOf(b);
  if (i < 0 || j < 0) throw new Error(`could not locate ${a} .. ${b} in index.html`);
  return app.slice(i, j);
};
// OCR helpers first: ocrDocument/pageToDataURL only touch the DOM when called,
// so they define cleanly here and ocrPage can be exercised on its own.
const block = cut('var SCAN_SCALE', 'var PROMPT =') + cut('var PROMPT =', '/* ---------------- rendering');

// Cloudflare 403s non-browser user agents; a real browser sends its own.
const realFetch = globalThis.fetch;
globalThis.fetch = (u, o = {}) =>
  realFetch(u, { ...o, headers: { ...(o.headers || {}), 'User-Agent': 'curl/8.7.1' } });

const mod = new Function('LLM', block + '\nreturn {segregate, extractJson, sliceRanges, statusOf, ocrPage};')({
  url: 'https://api.jaypokale.me/v1',
  key: process.env.GST_API_KEY,
  model: 'Qwen/Qwen3.6-27B-FP8'
});

// --- pure-function checks ---
const L = ['aaa', 'bbb', 'ccc', 'ddd', 'eee'];
console.assert(mod.sliceRanges(L, [[2, 3]]) === 'bbb\nccc', 'sliceRanges basic');
console.assert(mod.sliceRanges(L, [[1, 1], [5, 5]]) === 'aaa\n\neee', 'sliceRanges multi');
console.assert(mod.sliceRanges(L, [[0, 99]]) === 'aaa\nbbb\nccc\nddd\neee', 'sliceRanges clamps');
console.assert(mod.sliceRanges(L, []) === '', 'sliceRanges empty');
console.assert(mod.extractJson('```json\n{"a":1}\n```').a === 1, 'extractJson fences');
console.assert(mod.extractJson('sure! {"a":[[1,2]]} done').a[0][1] === 2, 'extractJson prose');
console.assert(mod.statusOf('partly_confirmed').label === 'Partly Confirmed', 'statusOf');
console.assert(mod.statusOf('garbage').label === 'For Review', 'statusOf fallback');
console.log('pure functions OK');

// --- live end-to-end on a real order ---
const pdf = process.argv[2];
let text = execFileSync('pdftotext', ['-layout', pdf, '-'], { encoding: 'utf8', maxBuffer: 1 << 28 });

// A scan has no text layer; the app OCRs it instead. pdftoppm stands in for the
// browser's canvas render, so the same ocrPage() runs on the same pixels.
if (text.replace(/\s+/g, '').length < 200) {
  const dir = mkdtempSync(join(tmpdir(), 'ocr-'));
  execFileSync('pdftoppm', ['-png', '-r', '104', pdf, join(dir, 'p')]);
  const pages = readdirSync(dir).filter(f => f.endsWith('.png')).sort();
  console.log(`no text layer — OCRing ${pages.length} page(s)`);
  const t = Date.now();
  const out = await Promise.all(pages.map(f =>
    mod.ocrPage('data:image/png;base64,' + readFileSync(join(dir, f)).toString('base64'))));
  text = out.join('\n');
  rmSync(dir, { recursive: true, force: true });
  console.log(`OCR done in ${((Date.now() - t) / 1000).toFixed(1)}s, ${text.length} chars`);
  if (text.replace(/\s+/g, '').length < 200) throw new Error('OCR returned nothing usable');
}
const lines = text.split('\n');

let ticks = 0;
const t0 = Date.now();
const parsed = await mod.segregate(lines, () => ticks++);
const secs = ((Date.now() - t0) / 1000).toFixed(1);

console.log(`\nstreamed in ${secs}s over ${ticks} chunks`);
console.log('case:', JSON.stringify(parsed.case));
if (!ticks) throw new Error('stream produced no chunks — SSE parsing is broken');

for (const i of parsed.issues) {
  console.log('-'.repeat(64));
  console.log(`${i.title}  [${mod.statusOf(i.status).label}]`);
  for (const p of ['notice', 'reply', 'finding']) {
    const t = i[p + '_text'];
    // every column must be a verbatim substring of the source document
    const verbatim = t === '' || t.split('\n\n').every(c => text.includes(c.split('\n')[0]));
    console.log(`  ${p.padEnd(8)} ${String(t.length).padStart(6)} chars  verbatim=${verbatim}`);
    if (!verbatim) throw new Error(`${i.title}/${p} is not verbatim from the PDF`);
  }
}
// the two demand tables must be distinct and both quoted from the PDF
for (const k of ['proposed', 'confirmed']) {
  const t = parsed.demand[k];
  const verbatim = !t || t.split('\n\n').every(c => text.includes(c.split('\n')[0]));
  console.log(`demand.${k.padEnd(9)} ${t ? String(t.length).padStart(5) + ' chars' : '  (none)'}  verbatim=${verbatim}`);
  if (!verbatim) throw new Error(`demand.${k} is not verbatim from the PDF`);
}
if (parsed.demand.confirmed && parsed.demand.confirmed === parsed.demand.proposed)
  throw new Error('confirmed demand is just the proposed one - the whole point is that they differ');

console.log('\nALL CHECKS PASSED');
