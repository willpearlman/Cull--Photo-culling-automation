# Cull proxy

A Cloudflare Worker that sits between the Cull app and the Anthropic API.

- The app sends its instruction call here with the user's **license key** where an API key
  would go. The app never holds an Anthropic key.
- The proxy checks the license, counts the call against the monthly cap, swaps in the real
  Anthropic key and forwards the request.
- Only what Cull sends is allowed through (one model, a `max_tokens` ceiling, no tools, no
  streaming), so a license is not a general Claude API key.

One typed instruction is **two calls**: one to build the plan, one to write the summary. The
default cap of 1,000 calls a month is about 500 instructions.

| Route | What it does |
| --- | --- |
| `POST /v1/messages` | The Anthropic Messages API, restricted as above |
| `GET /v1/license` | `{valid, used, limit, month}` for the license in `x-api-key` |

Errors use Anthropic's error shape: 401 for a missing, unknown or revoked key, 429 when the cap
is reached, 400 for a request Cull would not send. A call that Anthropic itself fails (429 or
5xx) is not counted.

## Test locally

Nothing here touches Cloudflare or Anthropic. It runs a fake Anthropic server, a local database
and `wrangler dev`.

```
cd C:\Users\willp\code\WiJoZa\proxy; npm install; npm test
```

## Deploy (once)

Run these in PowerShell from `C:\Users\willp\code\WiJoZa\proxy`. You need a free Cloudflare
account.

1. Sign in. A browser window opens.
   `npx wrangler login`
2. Create the database. Copy the `database_id` it prints into `wrangler.toml`.
   `npx wrangler d1 create cull`
3. Create the tables.
   `npx wrangler d1 execute cull --remote --file schema.sql`
4. Store the Anthropic key. Wrangler asks for it in a hidden prompt. Paste it there, never
   into a file or a chat.
   `npx wrangler secret put ANTHROPIC_API_KEY`
5. Deploy. It prints the proxy's address, like `https://cull-proxy.<you>.workers.dev`.
   `npx wrangler deploy`
6. Put that address in `PROXY_URL` in `cull/config.py`, then rebuild the installer.

## Licenses

Make a key and get the command that registers it:

```
node tools/new-license.mjs "beta: wedding tester"
```

The key is printed once. Only its SHA-256 goes into the database. Add a number at the end to
give that license its own monthly cap.

Revoke a license (find the row by its label):

```
npx wrangler d1 execute cull --remote --command "UPDATE licenses SET status = 'revoked' WHERE label = 'beta: wedding tester'"
```

See usage this month:

```
npx wrangler d1 execute cull --remote --command "SELECT l.label, u.month, u.calls FROM usage u JOIN licenses l USING (key_hash) ORDER BY u.month DESC, u.calls DESC"
```

## Settings

In `wrangler.toml`: `MONTHLY_CAP` (calls per license per UTC month), `ALLOWED_MODELS`
(comma-separated, must include the model in `cull/config.py`), `MAX_TOKENS`.
