// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.CHAT_BACKEND_URL || "http://localhost:8000";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const clientIp = req.headers.get("x-forwarded-for") || req.ip || "";
    const res = await fetch(`${BACKEND_URL}/chat/feedback`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(clientIp && { "X-Forwarded-For": clientIp }),
      },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    // Feedback loss is acceptable — don't block the user
    return NextResponse.json({ ok: true });
  }
}
