"use strict";
// The Vercel middleware behind maya.scenario.com (ported from photoshop-plugin)
// (tools/site_proxy/middleware.ts): download counts sent to PostHog, and the
// /download/latest redirect. A local server stands in for GitHub Pages
// (download/latest.json) and for PostHog. The middleware is TypeScript, run
// here through Node's type stripping, so these tests skip on Node 20; Vercel
// runs it on Node 24.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const ROOT = path.resolve(__dirname, "..", "..");
const FILE = path.join(ROOT, "tools", "site_proxy", "middleware.ts");
const skip = process.features.typescript ? false : "needs Node's TypeScript type stripping (Node 22.18 or later)";
const BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Firefox/140.0";

let proxy;
let server;
let base;
let received = [];
let posthogStatus = 200;
// download/latest.json per stand-in origin: { status, version }.
const latest = new Map();
const latestReads = new Map();
let origins = 0;

test.before(async () => {
  if (skip) return;
  proxy = await import(pathToFileURL(FILE).href);
  server = http.createServer((request, response) => {
    const url = request.url || "";
    const prefix = url.replace(/\/download\/latest\.json$/, "");
    if (request.method === "GET" && latest.has(prefix)) {
      latestReads.set(prefix, (latestReads.get(prefix) || 0) + 1);
      const file = latest.get(prefix);
      response.writeHead(file.status, { "content-type": "application/json" }).end(JSON.stringify({ version: file.version }));
      return;
    }
    let text = "";
    request.on("data", (chunk) => (text += chunk));
    request.on("end", () => {
      received.push({ path: url, body: JSON.parse(text) });
      response.writeHead(posthogStatus).end();
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  process.env.POSTHOG_HOST = base;
  process.env.POSTHOG_PROJECT_TOKEN = "phc_test";
});

test.after(() => {
  if (!server) return;
  server.closeAllConnections();
  server.close();
});

test.beforeEach(() => {
  received = [];
  posthogStatus = 200;
});

// A new stand-in origin, so the middleware's cached version starts empty.
function publish(version, status = 200) {
  const prefix = `/pages-${++origins}`;
  latest.set(prefix, { status, version });
  process.env.SITE_ORIGIN = `${base}${prefix}`;
  return prefix;
}

// One request through the middleware; resolves once its count is sent.
async function visit(pathname, headers = {}, method = "GET") {
  const pending = [];
  const result = proxy.default(new Request(`https://maya.scenario.com${pathname}`, { method, headers }), { waitUntil: (p) => pending.push(p) });
  const response = result ? await result : undefined;
  await Promise.all(pending);
  return { response, counted: pending.length };
}

test("runs only for the download folder, and forwards to the Pages address vercel.json uses", { skip }, () => {
  assert.deepEqual(proxy.config, { matcher: "/download/:path*", runtime: "nodejs" });
  const routing = JSON.parse(fs.readFileSync(path.join(ROOT, "tools", "site_proxy", "vercel.json"), "utf8"));
  assert.equal(routing.rewrites.at(-1).destination, `${proxy.ORIGIN}/$1`);
});

test("records a download with the plugin, version, client and country only", { skip }, async () => {
  publish("0.8.0");
  const { response } = await visit("/download/scenario-maya-0.8.0.zip", { "user-agent": BROWSER, "x-vercel-ip-country": "FR" });
  assert.equal(response, undefined, "the request goes on to Pages unchanged");
  assert.equal(received.length, 1);
  assert.equal(received[0].path, "/i/v0/e/");
  const { api_key, event, distinct_id, properties } = received[0].body;
  assert.equal(api_key, "phc_test");
  assert.equal(event, "extension_downloaded");
  assert.match(distinct_id, /^[0-9a-f-]{36}$/);
  assert.deepEqual(properties, {
    plugin: "maya",
    client: "browser",
    country: "FR",
    $process_person_profile: false,
    $geoip_disable: true,
    extension_version: "0.8.0"
  });
});

test("uses a new anonymous identifier for every request", { skip }, async () => {
  publish("0.8.0");
  await visit("/download/scenario-maya-0.8.0.zip", { "user-agent": BROWSER });
  await visit("/download/scenario-maya-0.8.0.zip", { "user-agent": BROWSER });
  assert.notEqual(received[0].body.distinct_id, received[1].body.distinct_id);
});

test("records a version that is not the published one, or an unreadable latest.json, as unknown", { skip }, async () => {
  publish("0.8.0");
  await visit("/download/scenario-maya-9.9.9.zip");
  publish("0.8.0", 500);
  await visit("/download/scenario-maya-0.8.0.zip");
  assert.deepEqual(received.map((r) => r.body.properties.extension_version), ["unknown", "unknown"]);
});

test("reads latest.json once for several downloads, and again for an unseen version after a minute", { skip }, async (t) => {
  const prefix = publish("0.8.0");
  await visit("/download/scenario-maya-0.8.0.zip");
  await visit("/download/scenario-maya-0.8.0.zip");
  assert.equal(latestReads.get(prefix), 1);
  latest.set(prefix, { status: 200, version: "0.9.0" });
  await visit("/download/scenario-maya-0.9.0.zip");
  assert.equal(latestReads.get(prefix), 1, "not within the minute");
  const now = Date.now();
  t.mock.method(Date, "now", () => now + 61_000);
  await visit("/download/scenario-maya-0.9.0.zip");
  assert.equal(latestReads.get(prefix), 2);
  assert.deepEqual(received.map((r) => r.body.properties.extension_version), ["0.8.0", "0.8.0", "unknown", "0.9.0"]);
});

test("sorts clients into crawlers, scripts, browsers and the rest, and keeps only two-letter countries", { skip }, async () => {
  publish("0.8.0");
  const agents = [
    ["Mozilla/5.0 (compatible; Googlebot/2.1)", "bot"],
    ["lychee/0.18", "bot"],
    ["curl/8.7.1", "tool"],
    ["", "tool"],
    [BROWSER, "browser"],
    ["Autodesk Maya/2027", "other"]
  ];
  for (const [agent] of agents) await visit("/download/scenario-maya-0.8.0.zip", { "user-agent": agent, "x-vercel-ip-country": "not a code" });
  assert.deepEqual(received.map((r) => r.body.properties.client), agents.map(([, client]) => client));
  assert.ok(received.every((r) => !("country" in r.body.properties)));
});

test("ignores other files, HEAD requests and resumed downloads", { skip }, async () => {
  publish("0.8.0");
  for (const p of ["/download/", "/download/latest.json", "/download/SHA256SUMS", "/download/scenario-maya-0.8.0.tar.gz", "/", "/page.js"]) {
    assert.equal((await visit(p)).counted, 0, p);
  }
  assert.equal((await visit("/download/scenario-maya-0.8.0.zip", {}, "HEAD")).counted, 0);
  assert.equal((await visit("/download/scenario-maya-0.8.0.zip", { range: "bytes=1000-" })).counted, 0);
  assert.equal((await visit("/download/scenario-maya-0.8.0.zip", { range: "bytes=0-" })).counted, 1);
  assert.equal(received.length, 1);
});

test("counts nothing without a PostHog token", { skip }, async () => {
  publish("0.8.0");
  delete process.env.POSTHOG_PROJECT_TOKEN;
  try {
    assert.deepEqual(await visit("/download/scenario-maya-0.8.0.zip"), { response: undefined, counted: 0 });
  } finally {
    process.env.POSTHOG_PROJECT_TOKEN = "phc_test";
  }
  assert.equal(received.length, 0);
});

test("a failed send is logged and changes nothing", { skip }, async (t) => {
  publish("0.8.0");
  const warn = t.mock.method(console, "warn", () => {});
  posthogStatus = 500;
  const { response } = await visit("/download/scenario-maya-0.8.0.zip");
  assert.equal(response, undefined);
  assert.deepEqual(warn.mock.calls.map((c) => c.arguments[0]), ["Download count not recorded: HTTP 500"]);
});

test("/download/latest redirects to the latest package without counting it", { skip }, async () => {
  publish("0.8.0");
  for (const method of ["GET", "HEAD"]) {
    const { response, counted } = await visit("/download/latest", {}, method);
    assert.equal(response.status, 302);
    assert.equal(response.headers.get("location"), "/download/scenario-maya-0.8.0.zip");
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(counted, 0);
  }
  // Before the first release, or while latest.json cannot be read: the releases page.
  publish("", 404);
  const { response } = await visit("/download/latest");
  assert.equal(response.headers.get("location"), "https://github.com/scenario-labs/maya-plugin/releases");
  assert.equal(received.length, 0);
});

test("/download/latest reads latest.json on every request, and sends to the releases page when a read fails", { skip }, async () => {
  const prefix = publish("0.8.0");
  await visit("/download/scenario-maya-0.8.0.zip");
  // A release lands within the five minutes the download count remembers 0.8.0.
  latest.set(prefix, { status: 200, version: "0.9.0" });
  assert.equal((await visit("/download/latest")).response.headers.get("location"), "/download/scenario-maya-0.9.0.zip");
  // A failed read must not send to a package remembered from an earlier
  // read: Pages serves the latest package only, so it may be gone.
  latest.set(prefix, { status: 500, version: "" });
  assert.equal((await visit("/download/latest")).response.headers.get("location"), "https://github.com/scenario-labs/maya-plugin/releases");
  assert.equal(latestReads.get(prefix), 3);
  // The download count still keeps the last version read.
  await visit("/download/scenario-maya-0.9.0.zip");
  assert.equal(received.at(-1).body.properties.extension_version, "0.9.0");
});
