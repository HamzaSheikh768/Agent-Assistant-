# Vercel deployment

This repository deploys the existing Next.js UI and the FastAPI agent as two
services in one Vercel project. The FastAPI service stays private; the public
`/api/chatkit` Next.js route reaches it through a Vercel service binding.

## Project settings

- Root Directory: `./`
- Framework Preset: `Services` (change the current `Next.js` selection)
- Build and Output settings: leave at their detected defaults

The `vercel.json` file defines both services and injects the private backend URL
into the frontend as `BACKEND_URL`. Do not manually create `BACKEND_URL`.

## Required Vercel environment variables

Configure these for Production (and Preview if preview deployments need chat):

- `NEXT_PUBLIC_CHATKIT_DOMAIN_KEY`
- `CHATKIT_INTERNAL_TOKEN` — a long random value shared automatically with both
  services through the project environment
- `GEMINI_API_KEY`

`CHATKIT_SERVER_URL` should remain unset when using Vercel Services. It is only
for a separately deployed Python backend or local development.

## Recommended production controls

- `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` make rate and usage
  counters shared across serverless instances. Without them, the safeguards use
  a best-effort per-instance memory fallback.
- `GEMINI_DAILY_TOKEN_BUDGET` sets a hard daily token ceiling. `0` or unset means
  usage is measured but the daily ceiling is disabled.
- `GEMINI_INPUT_USD_PER_MILLION` and `GEMINI_OUTPUT_USD_PER_MILLION` enable
  estimated cost values in structured logs. Set these to the current prices for
  the selected model.

Optional tuning variables:

- `CHATKIT_MAX_REQUEST_BYTES` (default `1048576`)
- `CHATKIT_RATE_LIMIT_PER_MINUTE` (default `20`)
- `CHATKIT_RATE_LIMIT_PER_DAY` (default `500`)
- `CHATKIT_UPSTREAM_TIMEOUT_MS` (default `30000`)
- `GEMINI_MODEL` (default `gemini-3.6-flash`)
- `GEMINI_CONTEXT_TOKEN_BUDGET` (default `24000`)
- `GEMINI_RESPONSE_TOKEN_RESERVE` (default `4096`)
- `GEMINI_RECENT_ITEMS` (default `12`)
- `GEMINI_MAX_RETRIES` (default `2`)
- `GEMINI_FIRST_TOKEN_TIMEOUT_SECONDS` (default `30`)
- `GEMINI_IDLE_TIMEOUT_SECONDS` (default `30`)
- `GEMINI_OVERALL_TIMEOUT_SECONDS` (default `120`)

## Verification after redeploy

1. Open `/api/health`; it must return HTTP `200` with both checks set to `ok`.
2. Send one ChatKit message and confirm the response streams normally.
3. In Vercel Runtime Logs, filter by the returned `x-request-id` to trace the
   frontend proxy, FastAPI request, Gemini latency, retries, and token usage.
4. Confirm the response includes CSP, HSTS, `X-Content-Type-Options`, and
   `Referrer-Policy` headers.

Local checks:

```powershell
node --test --experimental-strip-types tests/frontend/*.test.mjs
.\.venv\Scripts\python.exe -m unittest discover -s tests/backend -v
.\node_modules\.bin\tsc.cmd --noEmit --incremental false
.\node_modules\.bin\eslint.cmd .
```
