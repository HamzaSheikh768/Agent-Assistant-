export const DEFAULT_MAX_REQUEST_BYTES = 1_048_576;

export function positiveInteger(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function maxRequestBytes(): number {
  return positiveInteger(
    process.env.CHATKIT_MAX_REQUEST_BYTES,
    DEFAULT_MAX_REQUEST_BYTES,
  );
}

export function contentLengthExceedsLimit(
  contentLength: string | null,
  limit: number,
): boolean {
  if (!contentLength) {
    return false;
  }
  const parsed = Number.parseInt(contentLength, 10);
  return Number.isFinite(parsed) && parsed > limit;
}
