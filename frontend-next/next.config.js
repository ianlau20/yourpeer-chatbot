/** @type {import('next').NextConfig} */
const nextConfig = {
  pageExtensions: ["ts", "tsx"],
  // Allow both localhost and 127.0.0.1 during local dev
  allowedDevOrigins: ["localhost", "127.0.0.1"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              // Remove 'unsafe-eval' — it was here but is not needed by Next.js
              // in production and significantly widens the attack surface.
              // Keep 'unsafe-inline' for Next.js hydration scripts.
              "script-src 'self' 'unsafe-inline'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data:",
              "font-src 'self'",
              // All API calls go through Next.js route handlers (relative paths),
              // so 'self' is sufficient in production. Local dev needs the
              // backend directly for hot-reload proxying.
              `connect-src 'self' ${
                process.env.NODE_ENV === "development"
                  ? "http://localhost:8000 http://127.0.0.1:8000"
                  : ""
              }`.trim(),
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
              "object-src 'none'",
            ].join("; "),
          },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // Prevents third-party iframes from silently accessing geolocation,
          // which matters since the chat collects lat/long from users.
          { key: "Permissions-Policy", value: "geolocation=(self), camera=(), microphone=()" },
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
    ];
  },
  async rewrites() {
    // Chat and feedback routes are handled by the route handlers at
    // app/api/chat/route.ts and app/api/chat/feedback/route.ts, which
    // add IP-based rate limiting before proxying to the backend.
    //
    // Admin routes are handled by app/api/admin/[...slug]/route.ts,
    // which adds the Authorization header before proxying.
    //
    // No rewrites needed — all API proxying is done in route handlers.
    return { beforeFiles: [] };
  },
};

module.exports = nextConfig;
