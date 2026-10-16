import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const chatKitServerURL =
  process.env.CHATKIT_SERVER_URL ?? "http://127.0.0.1:8000/chatkit";

export async function POST(request: NextRequest) {
  const internalToken = process.env.CHATKIT_INTERNAL_TOKEN;

  if (!internalToken) {
    return Response.json(
      {
        error:
          "CHATKIT_INTERNAL_TOKEN is not configured on the Next.js server.",
      },
      { status: 503 },
    );
  }

  try {
    const upstream = await fetch(chatKitServerURL, {
      method: "POST",
      headers: {
        authorization: `Bearer ${internalToken}`,
        "content-type": request.headers.get("content-type") ?? "application/json",
      },
      body: await request.arrayBuffer(),
      cache: "no-store",
      signal: request.signal,
    });

    const headers = new Headers();
    headers.set(
      "content-type",
      upstream.headers.get("content-type") ?? "application/json",
    );
    headers.set("cache-control", "no-cache, no-transform");
    headers.set("x-accel-buffering", "no");

    return new Response(upstream.body, {
      status: upstream.status,
      headers,
    });
  } catch (error) {
    console.error("ChatKit upstream request failed", error);
    return Response.json(
      {
        error:
          "The ChatKit agent service is unavailable. Start the Python server and try again.",
      },
      { status: 503 },
    );
  }
}
