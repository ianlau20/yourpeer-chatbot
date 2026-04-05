// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.
import { NextRequest, NextResponse } from "next/server";
const BACKEND_URL = process.env.CHAT_BACKEND_URL || "http://localhost:8000";
/**
 * Catch-all proxy: /api/admin/stats → /admin/api/stats
 *                  /api/admin/eval/run → /admin/api/eval/run
 *                  etc.
 */
async function proxyToBackend(req: NextRequest, slug: string[]) {
  const path = slug.join("/");
  const url = new URL(`${BACKEND_URL}/admin/api/${path}`);
  // Forward query params
  req.nextUrl.searchParams.forEach((value, key) => {
    url.searchParams.set(key, value);
  });
  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    // Forward admin API key — prefer server-side env var (not exposed to browser)
    const adminKey = process.env.ADMIN_API_KEY;
    if (adminKey) {
      headers["Authorization"] = `Bearer ${adminKey}`;
    }
    const fetchOpts: RequestInit = {
      method: req.method,
      headers,
    };
    if (req.method === "POST" || req.method === "PUT" || req.method === "PATCH") {
      try {
        fetchOpts.body = JSON.stringify(await req.json());
      } catch {
        // No body — that's fine for some POSTs
      }
    }
    const res = await fetch(url.toString(), fetchOpts);
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(
      { detail: "Failed to reach admin backend" },
      { status: 502 },
    );
  }
}
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ slug: string[] }> },
) {
  const { slug } = await params;
  return proxyToBackend(req, slug);
}
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ slug: string[] }> },
) {
  const { slug } = await params;
  return proxyToBackend(req, slug);
}