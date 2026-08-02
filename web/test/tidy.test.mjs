// Exercises the tidy view's real functions from index.html: the number guard,
// the markdown renderer, and one live reformat of a genuinely mangled table.
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const app = html.match(/<script>\s*\n([\s\S]*?)<\/script>\s*<\/body>/)[1];
const block = app.slice(app.indexOf('var TIDY_PROMPT'), app.indexOf('/* ---------------- segregation'));

const realFetch = globalThis.fetch;
globalThis.fetch = (u, o = {}) =>
  realFetch(u, { ...o, headers: { ...(o.headers || {}), 'User-Agent': 'curl/8.7.1' } });

const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const mod = new Function('LLM', 'esc',
  block + '\nreturn {tidyText, mdToHtml};')(
  { url: 'https://api.jaypokale.me/v1', key: process.env.GST_API_KEY, model: 'Qwen/Qwen3.6-27B-FP8' },
  esc);


const t = mod.mdToHtml('Heading line\n\n| A | B |\n|---|---|\n| 1 | 2 |');
console.assert(t.includes('<table class="tidytab">') && t.includes('>A</th>') && t.includes('>2</td>'),
  'markdown table renders');
console.assert(!t.includes('|---|'), 'separator row dropped');
console.assert(mod.mdToHtml('just prose').includes('<p>just prose</p>'), 'prose renders');
console.assert(mod.mdToHtml('<img src=x onerror=1>').includes('&lt;img'), 'html is escaped');
// short figure columns get "num nums" (serial numbers), long ones just "num"
console.assert(/class="num/.test(mod.mdToHtml('| a | 1 |\n| b | 2 |')), 'numeric column detected');
console.assert(/class="num nums"/.test(mod.mdToHtml('| a | n |\n| b | 2 |')), 'short figure column marked narrow');
console.assert(!/nums/.test(mod.mdToHtml('| a | n |\n| b | 176634971 |')), 'money column not marked narrow');
console.assert(/<col style="width:\d+px">/.test(mod.mdToHtml('| a | n |\n| b | 176634971 |')), 'figure column width emitted');
console.log('markdown renderer OK');

// --- live: the actual mangled ITC-imports table from the Fujitec order ---
const mangled = `• Scrutiny of ITC availed under Imports:
 S.No       Description            IGST                  CESS              Total
  1                 2                3                    4                  5
        ITC availed on
        import of goods
  1     (including supplies         176634971                    0            176634971
        from SEZs) in table
        6E of GSTR-9
        Import of goods from
        overseas on bill of
        entry and Inward
        supplies of goods
  2     received from SEZ           162875367                    0            162875367
        units / developers
        on bill of entry as
        per Table 10 and 11
        of GSTR 2A
        Excess ITC Claimed
  3                                  13759604                    0               13759604
        on imports (1-2)`;

const md = await mod.tidyText(mangled);
console.log('\n--- model output ---\n' + md);
