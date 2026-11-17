// End-to-end test of the proxy, fully local: a fake Anthropic server, a local D1 database and
// `wrangler dev`. Nothing here touches Cloudflare or Anthropic.   npm test
import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const UP_PORT = 8798, PORT = 8799;
const BASE = `http://127.0.0.1:${PORT}`;
const UPSTREAM_KEY = "test-upstream-key";
const GOOD = "CULL-TEST1-TEST1-TEST1-TEST1", SMALL = "CULL-SMALL-SMALL-SMALL-SMALL",
  REVOKED = "CULL-GONE1-GONE1-GONE1-GONE1";
const hash = (k) => createHash("sha256").update(k).digest("hex");
const npx = (args, opts = {}) => execFileSync("npx", args, { cwd: ROOT, shell: true, stdio: "pipe", ...opts });

// Fake Anthropic: records what it was sent. A message "boom" makes it fail like an overload.
const seen = [];
const upstream = createServer((req, res) => {
  let data = "";
  req.on("data", (c) => (data += c));
  req.on("end", () => {
    const body = JSON.parse(data);
    seen.push({ url: req.url, headers: req.headers, body });
    const boom = body.messages[0].content === "boom";
    res.writeHead(boom ? 529 : 200, { "content-type": "application/json", "request-id": "req_fake" });
    res.end(JSON.stringify(boom
      ? { type: "error", error: { type: "overloaded_error", message: "Overloaded" } }
      : { id: "msg_fake", type: "message", role: "assistant", model: body.model, stop_reason: "end_turn",
          content: [{ type: "text", text: "ok" }], usage: { input_tokens: 1, output_tokens: 1 } }));
  });
}).listen(UP_PORT, "127.0.0.1");

rmSync(join(ROOT, ".wrangler"), { recursive: true, force: true });
writeFileSync(join(ROOT, ".dev.vars"),
  `ANTHROPIC_API_KEY=${UPSTREAM_KEY}\nUPSTREAM_URL=http://127.0.0.1:${UP_PORT}\n`);
npx(["wrangler", "d1", "execute", "cull", "--local", "--file", "schema.sql"]);
npx(["wrangler", "d1", "execute", "cull", "--local", "--command",
  `"INSERT INTO licenses (key_hash, label, status, monthly_cap) VALUES ` +
  `('${hash(GOOD)}', 'test', 'active', NULL), ('${hash(SMALL)}', 'small cap', 'active', 2), ` +
  `('${hash(REVOKED)}', 'revoked', 'revoked', NULL)"`]);

const dev = spawn("npx", ["wrangler", "dev", "--port", String(PORT), "--ip", "127.0.0.1"],
  { cwd: ROOT, shell: true, stdio: "pipe" });
let log = "";
dev.stdout.on("data", (d) => (log += d));
dev.stderr.on("data", (d) => (log += d));

const body = (over = {}) => JSON.stringify({ model: "claude-opus-5-5", max_tokens: 100,
  messages: [{ role: "user", content: "hi" }], ...over });
const post = (key, payload = body(), query = "") => fetch(`${BASE}/v1/messages${query}`, {
  method: "POST", body: payload,
  headers: { "content-type": "application/json", "anthropic-beta": "some-beta", ...(key ? { "x-api-key": key } : {}) } });
const status = async (key) => (await fetch(`${BASE}/v1/license`, { headers: { "x-api-key": key } })).json();

async function ready() {
  for (let i = 0; i < 120; i++) {
    try { await fetch(BASE); return; } catch { await new Promise((r) => setTimeout(r, 500)); }
  }
  throw new Error("wrangler dev did not start:\n" + log);
}

let failed = false;
try {
  await ready();
  const checks = [];
  const check = (name, fn) => checks.push([name, fn]);

  check("no license key is refused", async () => {
    const r = await post(null);
    assert.equal(r.status, 401);
    assert.equal((await r.json()).error.type, "authentication_error");
    assert.equal(r.headers.get("x-should-retry"), "false");
  });
  check("unknown and revoked keys are refused, nothing reaches Anthropic", async () => {
    assert.equal((await post("CULL-NOPE")).status, 401);
    assert.equal((await post(REVOKED)).status, 401);
    assert.equal(seen.length, 0);
  });
  check("a valid license is forwarded with the real key, never the license", async () => {
    const r = await post(GOOD, body(), "?beta=true");
    assert.equal(r.status, 200);
    assert.equal((await r.json()).content[0].text, "ok");
    assert.equal(r.headers.get("x-cull-used"), "1");
    assert.equal(r.headers.get("x-cull-limit"), "1000");
    const sent = seen.at(-1);
    assert.equal(sent.headers["x-api-key"], UPSTREAM_KEY);
    assert.equal(sent.headers["anthropic-beta"], "some-beta");
    assert.equal(sent.url, "/v1/messages?beta=true");
    assert.ok(!JSON.stringify(sent).includes(GOOD));
  });
  check("requests Cull would not send are refused and not counted", async () => {
    const before = seen.length;
    for (const bad of [body({ model: "claude-haiku-5-5" }), body({ max_tokens: 100000 }),
      body({ tools: [] }), body({ stream: true }), body({ messages: [] }), "not json"]) {
      assert.equal((await post(GOOD, bad)).status, 400);
    }
    assert.equal(seen.length, before);
    assert.equal((await status(GOOD)).used, 1);
  });
  check("a call Anthropic fails is passed through and not counted", async () => {
    const r = await post(GOOD, body({ messages: [{ role: "user", content: "boom" }] }));
    assert.equal(r.status, 529);
    assert.equal((await status(GOOD)).used, 1);
  });
  check("the monthly cap stops further calls", async () => {
    assert.equal((await post(SMALL)).status, 200);
    assert.equal((await post(SMALL)).status, 200);
    const before = seen.length;
    const r = await post(SMALL);
    assert.equal(r.status, 429);
    assert.equal((await r.json()).error.type, "rate_limit_error");
    assert.equal(seen.length, before);
    assert.deepEqual(await status(SMALL), { valid: true, used: 2, limit: 2, month: new Date().toISOString().slice(0, 7) });
  });
  check("license status needs a valid key, other paths are 404", async () => {
    assert.equal((await fetch(`${BASE}/v1/license`, { headers: { "x-api-key": "nope" } })).status, 401);
    assert.equal((await fetch(`${BASE}/v1/models`)).status, 404);
  });

  for (const [name, fn] of checks) {
    try { await fn(); console.log("ok   " + name); } catch (e) { failed = true; console.log("FAIL " + name + "\n" + e.message); }
  }
} catch (e) {
  failed = true;
  console.log(String(e));
} finally {
  upstream.close();
  if (process.platform === "win32") {
    try { execFileSync("taskkill", ["/pid", String(dev.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* gone */ }
  } else dev.kill();
  rmSync(join(ROOT, ".dev.vars"), { force: true });
}
console.log(failed ? "FAILED" : "all proxy checks passed");
process.exit(failed ? 1 : 0);
