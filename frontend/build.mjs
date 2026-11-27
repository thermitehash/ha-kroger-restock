// Builds the card into the integration's served folder:
// custom_components/kroger_restock/frontend/
//   kroger-restock-card.js   (entry, loaded on every dashboard)
//   chunks/*.js              (barcode reader, loaded only when the camera opens)
//   zxing_reader.wasm        (copied from zxing-wasm; served locally, no CDN)
import { build } from "esbuild";
import { copyFileSync, mkdirSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "..", "custom_components", "kroger_restock", "frontend");
const require = createRequire(import.meta.url);

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

await build({
  entryPoints: { "kroger-restock-card": join(here, "src", "index.ts") },
  outdir: out,
  bundle: true,
  splitting: true,
  format: "esm",
  target: ["es2021", "safari15"],
  minify: true,
  legalComments: "eof",
  chunkNames: "chunks/[name]-[hash]",
  logLevel: "info",
});

const wasm = require.resolve("zxing-wasm/reader/zxing_reader.wasm");
copyFileSync(wasm, join(out, "zxing_reader.wasm"));
console.log("copied", wasm);
