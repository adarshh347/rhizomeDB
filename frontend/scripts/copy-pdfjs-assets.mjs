// Copy pdf.js's standard-font and cmap data from node_modules into public/ so
// Vite serves them locally (no CDN). Runs on `npm install` (postinstall), so a
// fresh checkout is ready to render base-14-font and non-Latin PDFs without the
// 2.5 MB of assets living in git. Idempotent; version-synced with pdfjs-dist.
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const src = resolve(root, "node_modules", "pdfjs-dist");
const dest = resolve(root, "public", "pdfjs");

if (!existsSync(src)) {
  console.warn("[pdfjs] pdfjs-dist not installed yet; skipping asset copy");
  process.exit(0);
}

mkdirSync(dest, { recursive: true });
for (const dir of ["standard_fonts", "cmaps"]) {
  const from = resolve(src, dir);
  if (existsSync(from)) cpSync(from, resolve(dest, dir), { recursive: true });
}
console.log("[pdfjs] copied standard_fonts + cmaps -> public/pdfjs/");
