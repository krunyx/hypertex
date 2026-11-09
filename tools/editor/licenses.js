// 묶음에 들어간 npm 패키지의 저작권·사용 허가 문구를 htex/viewer/editor.LICENSE.txt 로 모은다.
const fs = require("fs"), path = require("path");
const meta = JSON.parse(fs.readFileSync("meta.json", "utf8"));
const pkgs = new Set();
for (const f of Object.keys(meta.inputs)) {
  const m = f.match(/node_modules\/((?:@[^/]+\/)?[^/]+)\//);
  if (m) pkgs.add(m[1]);
}
let out = "HyperTeX 원문 편집기(htex/viewer/editor.js)에 묶인 패키지와 사용 허가\n" +
          "Packages bundled into htex/viewer/editor.js and their licenses\n";
for (const p of [...pkgs].sort()) {
  const dir = path.join("node_modules", p);
  const pj = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
  const lic = fs.readdirSync(dir).find(n => /^licen[cs]e/i.test(n));
  out += `\n${"=".repeat(72)}\n${p} ${pj.version} (${pj.license})\n${"=".repeat(72)}\n`;
  out += lic ? fs.readFileSync(path.join(dir, lic), "utf8").trim() + "\n" : `License: ${pj.license}\n`;
}
fs.writeFileSync("../../htex/viewer/editor.LICENSE.txt", out);
fs.unlinkSync("meta.json");
console.log(`${pkgs.size} packages`);
