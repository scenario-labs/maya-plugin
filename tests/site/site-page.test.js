"use strict";
// The page at the root of maya.scenario.com (site/index.html), which
// .github/workflows/pages.yml publishes beside the handbook under /handbook/.
// Static checks, no browser: every file it names is in site/, every anchor
// resolves, links into the handbook name a chapter of handbook.config.json,
// the clips follow the page's video rules, old handbook anchors are forwarded,
// and the wording follows the house
// rules the handbook build applies to the docs.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const SITE = path.join(ROOT, "site");
const PAGE = path.join(SITE, "index.html");
const html = fs.readFileSync(PAGE, "utf8");
// The visible text: no styles, scripts or tags.
const text = html
  .replace(/<style[\s\S]*?<\/style\s*>/gi, " ")
  .replace(/<script[\s\S]*?<\/script\s*>/gi, " ")
  .replace(/<[^>]+>/g, " ");

// The markup alone: the scripts build some links of their own (search results).
const markup = html.replace(/<script[\s\S]*?<\/script\s*>/gi, " ");

function attributes(name) {
  return [...markup.matchAll(new RegExp(`\\s${name}="([^"]*)"`, "g"))].map((m) => m[1]);
}

const ids = new Set(attributes("id"));
const config = JSON.parse(fs.readFileSync(path.join(ROOT, "handbook.config.json"), "utf8"));
const chapters = new Set(config.chapters.map((c) => c.id));
// Paths the site serves outside site/: the analytics script (Vercel) and the
// release package with its version file (the components action).
const SERVED = new Set(["/page.js", "/download/latest", "/download/latest.json"]);

test("every file the page names is in site/", () => {
  const missing = [];
  for (const ref of [...attributes("src"), ...attributes("poster"), ...attributes("href")]) {
    if (/^(https?:|mailto:|#)/.test(ref) || ref.startsWith("handbook/") || ref.startsWith("/")) continue;
    const file = path.join(SITE, decodeURI(ref.split("#")[0]));
    if (!file.startsWith(SITE + path.sep) || !fs.existsSync(file)) missing.push(ref);
  }
  assert.deepEqual(missing, []);
});

test("site-absolute links are only the ones the site serves", () => {
  const other = [...attributes("src"), ...attributes("href")].filter((r) => r.startsWith("/") && !SERVED.has(r));
  assert.deepEqual(other, []);
  assert.match(html, /<script defer src="\/page\.js"><\/script>/, "analytics script, as the handbook's config names it");
});

test("every anchor resolves on the page, and every handbook link names a chapter", () => {
  const broken = attributes("href").filter((r) => r.startsWith("#") && r.length > 1 && !ids.has(r.slice(1)));
  assert.deepEqual(broken, []);
  for (const ref of attributes("href").filter((r) => r.startsWith("handbook/"))) {
    const anchor = ref.split("#")[1];
    assert.ok(ref === "handbook/" || (anchor && chapters.has(anchor)), `${ref}: not a chapter of handbook.config.json`);
  }
  for (const id of ids) assert.equal(attributes("id").filter((x) => x === id).length, 1, `id ${id} is used twice`);
});

test("the guide reader has every page it turns to", () => {
  const n = Number((html.match(/var N = (\d+)/) || [])[1]);
  assert.ok(n > 0, "the reader's page count");
  for (let i = 1; i <= n; i++) {
    const page = path.join(SITE, "assets", "guide", "pages", `p${String(i).padStart(2, "0")}.webp`);
    assert.ok(fs.existsSync(page), `guide page ${i}`);
  }
  assert.ok(!fs.existsSync(path.join(SITE, "assets", "guide", "pages", `p${String(n + 1).padStart(2, "0")}.webp`)), "a page past the reader's count");
});

test("step clips are muted loops with a poster and controls, loaded on demand", () => {
  const videos = [...html.matchAll(/<figure class="fig shot clip">\s*<video([^>]*)>/g)].map((m) => m[1]);
  assert.ok(videos.length >= 1);
  for (const v of videos) {
    for (const flag of [" muted", " loop", " playsinline", " controls", ' preload="none"', " poster=", " aria-label="]) {
      assert.ok(v.includes(flag), `${flag.trim()} missing on ${v}`);
    }
    assert.ok(!/\sautoplay/.test(v), "clips start from the script, which waits under reduced motion");
  }
  assert.match(html, /prefers-reduced-motion: reduce/);
});

test("each 3D viewer has its model, and the viewer's code is in site/", () => {
  const boxes = [...markup.matchAll(/<div class="v3d"([^>]*)><\/div>/g)].map((m) => m[1]);
  assert.ok(boxes.length >= 1);
  for (const rest of boxes) {
    const src = (rest.match(/ data-src="([^"]+)"/) || [])[1];
    assert.ok(src && src.endsWith(".glb") && fs.existsSync(path.join(SITE, src)), `model ${src}`);
    assert.match(rest, / aria-label="[^"]+"/, `aria-label missing on ${src}`);
    const orbit = (rest.match(/ data-orbit="([^"]+)"/) || [])[1];
    if (orbit) assert.match(orbit, /^-?\d+(\.\d+)? \d+(\.\d+)? \d+(\.\d+)?$/, `data-orbit of ${src}: azimuth polar factor`);
  }
  // one bundle, built from tools/site_viewer, loaded on demand, its licence beside it
  const code = (html.match(/s\.src = "(assets\/vendor\/[^"]+)"/) || [])[1];
  assert.equal(code, "assets/vendor/viewer3d.min.js", "the viewer's code, loaded on demand");
  assert.ok(fs.existsSync(path.join(SITE, code)));
  assert.match(fs.readFileSync(path.join(SITE, "assets", "vendor", "viewer3d.LICENSE.txt"), "utf8"), /MIT License/);
  assert.ok(fs.existsSync(path.join(ROOT, "tools", "site_viewer", "viewer3d.js")), "the viewer's readable source");
  const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "tools", "site_viewer", "package.json"), "utf8"));
  assert.ok(pkg.scripts.build.includes("../../site/assets/vendor/viewer3d.min.js"), "npm run build writes the bundle the page loads");
  assert.ok(!/model-viewer/.test(markup), "the page no longer uses model-viewer");
  assert.ok(!/<script[^>]+src="https?:/.test(html), "no script from another site");
});

test("carousel loops are muted, poster first, started by the script", () => {
  const loops = [...markup.matchAll(/<video data-loop([^>]*)>/g)].map((m) => m[1]);
  assert.ok(loops.length >= 1);
  for (const v of loops) {
    for (const flag of [" muted", " loop", " playsinline", ' preload="none"', " poster=", " aria-label="]) {
      assert.ok(v.includes(flag), `${flag.trim()} missing on ${v}`);
    }
    assert.ok(!/\sautoplay/.test(v), "loops play only in view, and not under reduced motion");
  }
  for (const car of markup.split('<div class="car"').slice(1)) {
    assert.match(car, /^ aria-roledescription="carousel" aria-label="[^"]+"/, "each carousel is labelled");
  }
});

test("old links to handbook chapters move to /handbook/", () => {
  const script = (html.match(/<script>\s*\/\/ Old links\.[\s\S]*?<\/script>/) || [])[0];
  assert.ok(script, "the forwarding script, in the head");
  assert.ok(html.indexOf(script) < html.indexOf("</head>"), "it runs before the page draws");
  const from = script.indexOf("var HANDBOOK = ");
  assert.ok(from >= 0, "the list of handbook chapters");
  const strings = script.slice(from, script.indexOf(";", from)).match(/"[^"]*"/g) || [];
  const list = new Set(strings.join(" ").replace(/"/g, "").split(/\s+/).filter(Boolean));
  for (const chapter of chapters) assert.ok(list.has(chapter), `chapter ${chapter} is forwarded`);
  for (const id of list) assert.ok(!ids.has(id), `${id} is on this page and must not be forwarded`);
  assert.match(script, /location\.replace\("handbook\/#" \+ encodeURIComponent\(id\)\)/);
});

test("no media file reaches GitHub's 50 MB warning", () => {
  const big = [];
  (function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (fs.statSync(full).size >= 50 * 1024 * 1024) big.push(path.relative(ROOT, full));
    }
  })(SITE);
  assert.deepEqual(big, []);
});

test("the wording follows the house rules", () => {
  assert.ok(!/[\u2013\u2014]/.test(html), "no en or em dash");
  const emails = new Set(html.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g) || []);
  assert.deepEqual([...emails], ["support@scenario.com"]);
  assert.deepEqual(text.match(/(?<!Scenario )\bMCP\b/g) || [], [], 'MCP is written "Scenario MCP"');
  assert.ok(!/\/(Users|home)\/[a-z]/i.test(html), "no machine path");
  assert.ok(!html.includes("{{"), "no unfilled placeholder: the page reads its version from download/latest.json");
});

test("the proxy sends /handbook to /handbook/", () => {
  const routing = JSON.parse(fs.readFileSync(path.join(ROOT, "tools", "site_proxy", "vercel.json"), "utf8"));
  assert.ok((routing.redirects || []).some((r) => r.source === "/handbook" && r.destination === "/handbook/"));
});
