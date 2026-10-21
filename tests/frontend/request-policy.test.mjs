import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  DEFAULT_MAX_REQUEST_BYTES,
  contentLengthExceedsLimit,
  positiveInteger,
} from "../../src/lib/request-policy.ts";
import {
  getChatkitEndpoint,
  getChatkitPublicFallbackEndpoint,
} from "../../src/lib/chatkit-backend.ts";

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
  assert.equal(config.services.backend.rewrites[0].source, "/_agent/chatkit");
  assert.equal(config.services.backend.rewrites[0].destination, "/chatkit");
  assert.equal(config.rewrites[0].source, "/_agent/chatkit");
  assert.equal(config.rewrites[0].destination.service, "backend");
  assert.equal(config.rewrites[1].destination.service, "frontend");
});

test("public fallback only targets a trusted Vercel deployment origin", () => {
  const previous = {
    backendURL: process.env.BACKEND_URL,
    chatkitURL: process.env.CHATKIT_SERVER_URL,
    vercelURL: process.env.VERCEL_URL,
  };

  delete process.env.BACKEND_URL;
  delete process.env.CHATKIT_SERVER_URL;
  delete process.env.VERCEL_URL;

  try {
    assert.equal(
      getChatkitPublicFallbackEndpoint("https://assistant-bots.vercel.app"),
      "https://assistant-bots.vercel.app/_agent/chatkit",
    );
    assert.equal(
      getChatkitPublicFallbackEndpoint("https://example.com"),
      null,
    );
  } finally {
    for (const [name, value] of Object.entries({
      BACKEND_URL: previous.backendURL,
      CHATKIT_SERVER_URL: previous.chatkitURL,
      VERCEL_URL: previous.vercelURL,
    })) {
      if (value === undefined) {
        delete process.env[name];
      } else {
        process.env[name] = value;
      }
    }
  }
});

test("Vercel service binding takes priority over a manual backend URL", () => {
  const previous = {
    backendURL: process.env.BACKEND_URL,
    chatkitURL: process.env.CHATKIT_SERVER_URL,
  };

  process.env.BACKEND_URL = "http://backend.internal";
  process.env.CHATKIT_SERVER_URL = "https://stale.example.com/chatkit";

  try {
    assert.equal(getChatkitEndpoint(), "http://backend.internal/chatkit");
    assert.equal(
      getChatkitPublicFallbackEndpoint("https://assistant-bots.vercel.app"),
      "https://assistant-bots.vercel.app/_agent/chatkit",
    );
  } finally {
    for (const [name, value] of Object.entries({
      BACKEND_URL: previous.backendURL,
      CHATKIT_SERVER_URL: previous.chatkitURL,
    })) {
      if (value === undefined) {
        delete process.env[name];
      } else {
        process.env[name] = value;
      }
    }
  }
});
