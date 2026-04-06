// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

import { NextRequest, NextResponse } from "next/server";
import { createHmac, timingSafeEqual } from "crypto";
import { checkRateLimit, getClientIp } from "@/lib/rate-limit";

const ADMIN_API_KEY = process.env.ADMIN_API_KEY || "";
const COOKIE_NAME = "admin_session";
const COOKIE_MAX_AGE = 8 * 60 * 60; // 8 hours

/**
 * Compute a signed token from the admin key.  The cookie value is an
 * HMAC of a fixed payload — anyone with the correct ADMIN_API_KEY can
 * reproduce it, but you cannot forge the cookie without the key.
 */
function signedToken(): string {
  return createHmac("sha256", ADMIN_API_KEY)
    .update("admin-authenticated")
    .digest("hex");
}

function isValidCookie(value: string): boolean {
  try {
    const expected = signedToken();
    const a = Buffer.from(value, "utf8");
    const b = Buffer.from(expected, "utf8");
    return a.length === b.length && timingSafeEqual(a, b);
  } catch {
    return false;
  }
}

function cookieOptions() {
  const isProd = process.env.NODE_ENV === "production";
  return {
    httpOnly: true,
    secure: isProd,
    sameSite: "strict" as const,
    path: "/",
    maxAge: COOKIE_MAX_AGE,
  };
}

// ---------------------------------------------------------------------------
// GET — check auth status
// ---------------------------------------------------------------------------

export async function GET(req: NextRequest) {
  // No key configured → auth is disabled (dev mode)
  if (!ADMIN_API_KEY) {
    return NextResponse.json({ authenticated: true, authDisabled: true });
  }

  const cookie = req.cookies.get(COOKIE_NAME);
  const authenticated = cookie ? isValidCookie(cookie.value) : false;
  return NextResponse.json({ authenticated });
}

// ---------------------------------------------------------------------------
// Login attempt rate limits — 5 failed attempts per IP per 15 minutes.
// Only failed attempts are counted (successful logins don't consume quota).
// ---------------------------------------------------------------------------

const LOGIN_LIMITS: [number, number][] = [
  [900, 5], // 5 attempts per 15 minutes per IP
];

// ---------------------------------------------------------------------------
// POST — login
// ---------------------------------------------------------------------------

export async function POST(req: NextRequest) {
  // No key configured → always succeed
  if (!ADMIN_API_KEY) {
    return NextResponse.json({ authenticated: true, authDisabled: true });
  }

  let password = "";
  try {
    const body = await req.json();
    password = body.password || "";
  } catch {
    return NextResponse.json(
      { authenticated: false, error: "Invalid request" },
      { status: 400 },
    );
  }

  // Constant-time comparison
  const a = Buffer.from(password, "utf8");
  const b = Buffer.from(ADMIN_API_KEY, "utf8");
  const valid = a.length === b.length && timingSafeEqual(a, b);

  if (!valid) {
    // Check rate limit ONLY on failed attempts — successful logins don't
    // consume quota, so a legitimate admin can always log in even if an
    // attacker has been brute-forcing from the same IP.
    const clientIp = getClientIp(req.headers);
    const limit = checkRateLimit(`admin-login:${clientIp}`, LOGIN_LIMITS);
    if (!limit.allowed) {
      return NextResponse.json(
        { authenticated: false, error: "Too many login attempts. Try again later." },
        { status: 429, headers: { "Retry-After": String(limit.retryAfter) } },
      );
    }

    return NextResponse.json(
      { authenticated: false, error: "Invalid password" },
      { status: 401 },
    );
  }

  const response = NextResponse.json({ authenticated: true });
  response.cookies.set(COOKIE_NAME, signedToken(), cookieOptions());
  return response;
}

// ---------------------------------------------------------------------------
// DELETE — logout
// ---------------------------------------------------------------------------

export async function DELETE() {
  const response = NextResponse.json({ authenticated: false });
  response.cookies.set(COOKIE_NAME, "", { ...cookieOptions(), maxAge: 0 });
  return response;
}
