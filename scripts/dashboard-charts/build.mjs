import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const output = resolve(here, "../../web/dashboard/vendor");
const modules = join(here, "node_modules");
const echarts = join(modules, "echarts");
const licenseFiles = new Map([
  ["ECHARTS-LICENSE.txt", join(echarts, "LICENSE")],
  ["ECHARTS-NOTICE.txt", join(echarts, "NOTICE")],
  ["ZRENDER-LICENSE.txt", join(modules, "zrender", "LICENSE")],
  ["TSLIB-LICENSE.txt", join(modules, "tslib", "LICENSE.txt")],
]);

await mkdir(output, { recursive: true });
const name = "echarts.min.js";
await build({
  entryPoints: [join(here, "entry.js")],
  outfile: join(output, name),
  platform: "browser",
  format: "iife",
  target: "es2020",
  bundle: true,
  minify: true,
  legalComments: "linked",
  define: { "process.env.NODE_ENV": '"production"' },
  banner: { js: "/* Apache ECharts 6.1.0 subset. See bundled license and notice files. */" },
});
for (const [target, source] of licenseFiles) await copyFile(source, join(output, target));
const names = [name, `${name}.LEGAL.txt`, ...licenseFiles.keys()];
const checksums = await Promise.all(names.sort().map(async (file) => {
  const data = await readFile(join(output, file));
  return `${createHash("sha256").update(data).digest("hex")}  ${file}\n`;
}));
await writeFile(join(output, "SHA256SUMS"), checksums.join(""), "utf8");
console.log(`ECharts browser bundle: ${(await readFile(join(output, name))).length} bytes`);
