/**
 * In-memory sliding-window rate limiter for Next.js API routes.
 *
 * This is a first line of defense at the frontend proxy layer. The backend
 * has its own rate limiter — this prevents request volume from overwhelming
 * the Node.js process before requests even reach FastAPI.
 *
 * All state lives in-process. On Render Starter tier (always-on), this
 * persists across requests. On restart, state resets — acceptable since
 * the backend rate limiter provides the authoritative limits.
 */

import { NextResponse } from "next/server";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RateLimitResult {
  allowed: boolean;
  retryAfter: number; // seconds until the tightest violated window resets
}

interface Bucket {
  timestamps: number[];
  lastAccessed: number;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

// key → bucket of request timestamps
const buckets = new Map<string, Bucket>();

// Eviction config
const EVICTION_TTL_MS = 10 * 60 * 1000; // 10 minutes
const MAX_BUCKETS = 2000;
let lastEviction = 0;

// ---------------------------------------------------------------------------
// Core
// ---------------------------------------------------------------------------

/**
 * Check and record a request against rate limits.
 *
 * @param key   Unique identifier (e.g., "chat:192.168.1.1")
 * @param limits Array of [windowSeconds, maxRequests] tuples
 * @returns Whether the request is allowed and retry-after if not
 */
export function checkRateLimit(
  key: string,
  limits: [number, number][],
): RateLimitResult {
  const now = Date.now();
  maybeEvict(now);

  let bucket = buckets.get(key);
  if (!bucket) {
    bucket = { timestamps: [], lastAccessed: now };
    buckets.set(key, bucket);
  }
  bucket.lastAccessed = now;

  // Check all windows before recording the new request
  let tightest: RateLimitResult | null = null;
  for (const [windowSec, maxReqs] of limits) {
    const windowMs = windowSec * 1000;
    const cutoff = now - windowMs;
    const count = bucket.timestamps.filter((t) => t > cutoff).length;
    if (count >= maxReqs) {
      // Find the oldest timestamp in the window to compute retry-after
      const oldest = bucket.timestamps.find((t) => t > cutoff);
      const retryAfter = oldest
        ? Math.ceil((oldest - cutoff) / 1000) + 1
        : 1;
      if (!tightest || retryAfter < tightest.retryAfter) {
        tightest = { allowed: false, retryAfter };
      }
    }
  }

  // Always record the timestamp (even if denied — prevents window draining)
  bucket.timestamps.push(now);

  // Trim old timestamps to prevent unbounded growth.
  // Keep only timestamps within the largest window.
  const maxWindow = Math.max(...limits.map(([w]) => w)) * 1000;
  bucket.timestamps = bucket.timestamps.filter((t) => t > now - maxWindow);

  return tightest ?? { allowed: true, retryAfter: 0 };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function maybeEvict(now: number): void {
  if (now - lastEviction < 60_000 && buckets.size <= MAX_BUCKETS) return;
  lastEviction = now;
  const cutoff = now - EVICTION_TTL_MS;
  for (const [key, bucket] of buckets) {
    if (bucket.lastAccessed < cutoff) buckets.delete(key);
  }
}

/**
 * Extract the client IP from a Next.js request.
 * Render sets X-Forwarded-For; falls back to "unknown".
 */
export function getClientIp(headers: Headers): string {
  const forwarded = headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0].trim();
  return "unknown";
}

// ---------------------------------------------------------------------------
// 429 Response Builder
// ---------------------------------------------------------------------------

// Compassionate message with crisis resources — matches the backend's style.
const RATE_LIMIT_MESSAGE =
  "You\u2019re sending messages very quickly. Please wait a moment and try again.";

const CRISIS_RESOURCES =
  "If you need immediate help, call 311 for NYC services or 988 for the Suicide & Crisis Lifeline.";

/**
 * Build a 429 JSON response with Retry-After header.
 */
export function rateLimitResponse(retryAfter: number): NextResponse {
  return NextResponse.json(
    {
      detail: RATE_LIMIT_MESSAGE,
      crisis_resources: CRISIS_RESOURCES,
      retry_after: retryAfter,
    },
    {
      status: 429,
      headers: { "Retry-After": String(retryAfter) },
    },
  );
}
