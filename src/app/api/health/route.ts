import { randomUUID } from "node:crypto";

import { isChatBackendReady } from "@/lib/chatkit-backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const id = randomUUID();
  const domainKeyConfigured = Boolean(
    process.env.NEXT_PUBLIC_CHATKIT_DOMAIN_KEY,
  );
  const backendReady = await isChatBackendReady();
  const ready = domainKeyConfigured && backendReady;

  return Response.json(
    {
      status: ready ? "ready" : "unavailable",
      checks: {
        chatkitDomain: domainKeyConfigured ? "ok" : "missing",
        agentBackend: backendReady ? "ok" : "unavailable",
      },
      requestId: id,
    },
    {
      status: ready ? 200 : 503,
      headers: {
        "cache-control": "no-store",
        "x-request-id": id,
      },
    },
  );
}
