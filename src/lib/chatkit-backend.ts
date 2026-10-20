const LOCAL_BACKEND = "http://127.0.0.1:8000";

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function configuredBackendBase(): string | null {
  const serviceURL = process.env.BACKEND_URL?.trim();
  if (serviceURL) {
    return trimTrailingSlash(serviceURL);
  }

  const chatkitURL = process.env.CHATKIT_SERVER_URL?.trim();
  if (chatkitURL) {
    return trimTrailingSlash(chatkitURL).replace(/\/chatkit$/, "");
  }

  if (!process.env.VERCEL) {
    return LOCAL_BACKEND;
  }

  return null;
}

export function getChatkitEndpoint(): string {
  const explicitURL = process.env.CHATKIT_SERVER_URL?.trim();
  if (explicitURL) {
    return explicitURL;
  }

  const baseURL = configuredBackendBase();
  if (!baseURL) {
    throw new Error(
      "Python backend is not connected. Enable Vercel Services or set CHATKIT_SERVER_URL.",
    );
  }
  return `${baseURL}/chatkit`;
}

export function getBackendReadinessEndpoint(): string {
  const baseURL = configuredBackendBase();
  if (!baseURL) {
    throw new Error(
      "Python backend is not connected. Enable Vercel Services or set CHATKIT_SERVER_URL.",
    );
  }
  return `${baseURL}/health/ready`;
}

export async function isChatBackendReady(timeoutMs = 3_000): Promise<boolean> {
  const internalToken = process.env.CHATKIT_INTERNAL_TOKEN;
  if (!internalToken) {
    return false;
  }

  try {
    const response = await fetch(getBackendReadinessEndpoint(), {
      headers: { authorization: `Bearer ${internalToken}` },
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    return response.ok;
  } catch {
    return false;
  }
}
