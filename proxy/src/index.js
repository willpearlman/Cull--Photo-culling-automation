// Cull proxy (Cloudflare Worker).
//
// The app sends its instruction call here with the user's license key where the Anthropic key
// would go (x-api-key). The proxy checks the license, counts the call against the monthly cap,
// swaps in the real Anthropic key and forwards the request. The real key never leaves here.
//
//   POST /v1/messages   the Anthropic Messages API, restricted to what Cull sends
//   GET  /v1/license    {valid, used, limit, month} for the license in x-api-key
//
// Errors use Anthropic's error shape, so the Anthropic SDK in the app raises its usual
// exceptions (401 AuthenticationError, 429 RateLimitError, 400 BadRequestError).

const UPSTREAM = "https://api.anthropic.com";
const MAX_BODY_BYTES = 200_000;
// Top-level request fields Cull uses. Anything else (tools, stream, ...) is refused, so a
// license cannot be used as a general Claude API key.
const ALLOWED_FIELDS = new Set(["model", "max_tokens", "messages", "system", "output_config",
  "fallbacks", "metadata"]);

function error(status, type, message, headers = {}) {
  return Response.json({ type: "error", error: { type, message } },
    { status, headers: { "x-should-retry": "false", ...headers } });
}

async function sha256(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function month() {
  return new Date().toISOString().slice(0, 7); // YYYY-MM, UTC
}

// The license row for the request's key, or an error Response.
async function license(request, env) {
  const key = (request.headers.get("x-api-key") || "").trim();
  if (!key) return error(401, "authentication_error", "No license key was sent.");
  const hash = await sha256(key);
  const row = await env.DB.prepare(
    "SELECT status, monthly_cap FROM licenses WHERE key_hash = ?1").bind(hash).first();
  if (!row) return error(401, "authentication_error", "This license key is not recognized.");
  if (row.status !== "active") {
    return error(401, "authentication_error", "This license key is no longer active.");
  }
  return { hash, limit: row.monthly_cap ?? Number(env.MONTHLY_CAP) };
}

async function used(env, hash) {
  const row = await env.DB.prepare(
    "SELECT calls FROM usage WHERE key_hash = ?1 AND month = ?2").bind(hash, month()).first();
  return row ? row.calls : 0;
}

// Count one call. Returns the new count, or null when the license is at its cap. One statement,
// so two calls at once cannot both take the last slot.
async function take(env, lic) {
  const row = await env.DB.prepare(
    `INSERT INTO usage (key_hash, month, calls) VALUES (?1, ?2, 1)
     ON CONFLICT (key_hash, month) DO UPDATE SET calls = calls + 1 WHERE calls < ?3
     RETURNING calls`).bind(lic.hash, month(), lic.limit).first();
  return row ? row.calls : null;
}

async function giveBack(env, lic) {
  await env.DB.prepare(
    "UPDATE usage SET calls = calls - 1 WHERE key_hash = ?1 AND month = ?2 AND calls > 0")
    .bind(lic.hash, month()).run();
}

// The parsed request body if it is something Cull would send, or an error Response.
async function checkedBody(request, env) {
  const text = await request.text();
  if (text.length > MAX_BODY_BYTES) return error(413, "request_too_large", "Request is too large.");
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    return error(400, "invalid_request_error", "Request body is not JSON.");
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return error(400, "invalid_request_error", "Request body must be an object.");
  }
  const extra = Object.keys(body).filter((k) => !ALLOWED_FIELDS.has(k));
  if (extra.length) {
    return error(400, "invalid_request_error", `Not allowed through Cull: ${extra.join(", ")}`);
  }
  const models = env.ALLOWED_MODELS.split(",").map((m) => m.trim());
  if (!models.includes(body.model)) {
    return error(400, "invalid_request_error", `Model not allowed through Cull: ${body.model}`);
  }
  const maxTokens = Number(env.MAX_TOKENS);
  if (!Number.isInteger(body.max_tokens) || body.max_tokens < 1 || body.max_tokens > maxTokens) {
    return error(400, "invalid_request_error", `max_tokens must be 1 to ${maxTokens}.`);
  }
  if (!Array.isArray(body.messages) || body.messages.length === 0) {
    return error(400, "invalid_request_error", "messages is required.");
  }
  return { text };
}

async function messages(request, env) {
  if (!env.ANTHROPIC_API_KEY) return error(500, "api_error", "The proxy has no API key set.");
  const lic = await license(request, env);
  if (lic instanceof Response) return lic;
  const body = await checkedBody(request, env);
  if (body instanceof Response) return body;

  const count = await take(env, lic);
  if (count === null) {
    return error(429, "rate_limit_error",
      `This license has used all ${lic.limit} instruction calls for ${month()}.`,
      { "x-cull-used": String(lic.limit), "x-cull-limit": String(lic.limit) });
  }

  const headers = {
    "content-type": "application/json",
    "x-api-key": env.ANTHROPIC_API_KEY,
    "anthropic-version": request.headers.get("anthropic-version") || "2023-06-01",
  };
  const beta = request.headers.get("anthropic-beta");
  if (beta) headers["anthropic-beta"] = beta;

  let upstream;
  try {
    upstream = await fetch((env.UPSTREAM_URL || UPSTREAM) + "/v1/messages" + new URL(request.url).search,
      { method: "POST", headers, body: body.text });
  } catch {
    await giveBack(env, lic);
    return error(502, "api_error", "Could not reach the AI service.");
  }
  // A call the AI service did not answer (overloaded, its own rate limit, server error) is
  // not the user's to pay for.
  let usedNow = count;
  if (upstream.status === 429 || upstream.status >= 500) {
    await giveBack(env, lic);
    usedNow = count - 1;
  }
  const out = new Headers({ "content-type": upstream.headers.get("content-type") || "application/json",
    "x-cull-used": String(usedNow), "x-cull-limit": String(lic.limit) });
  for (const name of ["request-id", "retry-after"]) {
    if (upstream.headers.get(name)) out.set(name, upstream.headers.get(name));
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

async function licenseStatus(request, env) {
  const lic = await license(request, env);
  if (lic instanceof Response) return lic;
  return Response.json({ valid: true, used: await used(env, lic.hash), limit: lic.limit, month: month() });
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    try {
      if (pathname === "/v1/messages" && request.method === "POST") return await messages(request, env);
      if (pathname === "/v1/license" && request.method === "GET") return await licenseStatus(request, env);
    } catch (err) {
      console.error(err);
      return error(500, "api_error", "The Cull proxy hit an internal error.");
    }
    return error(404, "not_found_error", "Not found.");
  },
};
