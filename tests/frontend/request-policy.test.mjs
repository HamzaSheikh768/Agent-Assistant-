import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  DEFAULT_MAX_REQUEST_BYTES,
  contentLengthExceedsLimit,
  positiveInteger,
} from "../../src/lib/request-policy.ts";

test("request-size policy rejects oversized declared bodies", () => {
  assert.equal(DEFAULT_MAX_REQUEST_BYTES, 1_048_576);
  assert.equal(contentLengthExceedsLimit("1048577", DEFAULT_MAX_REQUEST_BYTES), true);
  assert.equal(contentLengthExceedsLimit("1048576", DEFAULT_MAX_REQUEST_BYTES), false);
  assert.equal(contentLengthExceedsLimit(null, DEFAULT_MAX_REQUEST_BYTES), false);
});

test("invalid numeric settings fall back safely", () => {
  assert.equal(positiveInteger("25", 10), 25);
  assert.equal(positiveInteger("0", 10), 10);
  assert.equal(positiveInteger("invalid", 10), 10);
});

test("Vercel deploy config connects Next.js and FastAPI services", () => {
  const config = JSON.parse(readFileSync(new URL("../../vercel.json", import.meta.url)));
  assert.equal(config.services.frontend.framework, "nextjs");
  assert.equal(config.services.frontend.bindings[0].env, "BACKEND_URL");
  assert.equal(config.services.frontend.bindings[0].service, "backend");
  assert.equal(config.services.backend.framework, "fastapi");
  assert.equal(config.services.backend.entrypoint, "server.app:app");
  assert.equal(config.rewrites[0].destination.service, "frontend");
});
