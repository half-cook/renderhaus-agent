// node compare.mjs [theme=dark]  ->  out/diff/<theme>/<project>/<id>.png + out/report-<theme>.html
// Pairs out/before/<theme>/** with out/after/<theme>/**; screens that only exist in "after" are listed as NEW.
import { readdirSync, readFileSync, writeFileSync, mkdirSync, existsSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PNG } from "pngjs";
import pixelmatch from "pixelmatch";

const theme = process.argv[2] ?? "dark";
const OUT = path.resolve(process.env.SHOT_OUT_DIR || path.join(path.dirname(fileURLToPath(import.meta.url)), "out"));
const A = path.join(OUT, "after", theme);
const B = path.join(OUT, "before", theme);
const inventory = (directory, accept) => existsSync(directory) ? readdirSync(directory).filter((name) => accept(name, path.join(directory, name))) : [];
const projects = (directory) => inventory(directory, (_, file) => statSync(file).isDirectory());
const screenshots = (directory) => inventory(directory, (name, file) => name.endsWith(".png") && statSync(file).isFile());
if (!existsSync(A) && !existsSync(B)) { console.error("No captures to compare"); process.exit(2); }
const rows = [];
for (const project of [...new Set([...projects(B), ...projects(A)])].sort()) {
  for (const f of [...new Set([...screenshots(path.join(B, project)), ...screenshots(path.join(A, project))])].sort()) {
    const after = path.join(A, project, f);
    const before = path.join(OUT, "before", theme, project, f);
    const rel = (p) => path.relative(OUT, p);
    if (!existsSync(after)) { rows.push({ project, f, status: "MISSING AFTER", before: rel(before) }); continue; }
    if (!existsSync(before)) { rows.push({ project, f, status: "NEW", after: rel(after) }); continue; }
    const a = PNG.sync.read(readFileSync(after)), b = PNG.sync.read(readFileSync(before));
    if (a.width !== b.width || a.height !== b.height) {
      rows.push({ project, f, status: `SIZE ${b.width}x${b.height} -> ${a.width}x${a.height}`, before: rel(before), after: rel(after) });
      continue;
    }
    const diff = new PNG({ width: a.width, height: a.height });
    const n = pixelmatch(b.data, a.data, diff.data, a.width, a.height, { threshold: 0.05 });
    const dir = path.join(OUT, "diff", theme, project); mkdirSync(dir, { recursive: true });
    const dp = path.join(dir, f); writeFileSync(dp, PNG.sync.write(diff));
    const diffPercent = (n / (a.width * a.height)) * 100;
    rows.push({ project, f, status: `${diffPercent.toFixed(2)}% changed`, diffPixels: n, diffPercent, before: rel(before), after: rel(after), diff: rel(dp) });
  }
}
const img = (s) => (s ? `<a href="${s}"><img loading="lazy" src="${s}"></a>` : "<em>-</em>");
const html = `<!doctype html><meta charset=utf-8><title>Renderhaus UI revamp: before/after (${theme})</title>
<style>body{background:#0a0a0a;color:#e5e5e5;font:14px system-ui;margin:24px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #262626;padding:8px;vertical-align:top}img{max-width:100%;display:block}h2{margin-top:32px}</style>
<h1>Before (staging) vs After (feat/ui-revamp) &middot; ${theme}</h1>
${[...new Set(rows.map((r) => r.project))].map((p) => `<h2>${p}</h2><table><tr><th>Screen</th><th>Before</th><th>After</th><th>Diff</th></tr>${rows.filter((r) => r.project === p).map((r) => `<tr><td>${r.f}<br><b>${r.status}</b></td><td>${img(r.before)}</td><td>${img(r.after)}</td><td>${img(r.diff)}</td></tr>`).join("")}</table>`).join("")}`;
writeFileSync(path.join(OUT, `report-${theme}.html`), html);
writeFileSync(path.join(OUT, `report-${theme}.json`), JSON.stringify(rows, null, 2));
console.table(rows.map(({ project, f, status }) => ({ project, screen: f, status })));
if (rows.some((row) => row.status === "MISSING AFTER" || row.status.startsWith("SIZE "))) process.exitCode = 1;
