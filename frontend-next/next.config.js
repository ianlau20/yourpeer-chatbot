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
              // Covers both the Render backend and local dev
              `connect-src 'self' https://*.onrender.com ${
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
        ],
      },
    ];
  },
  async rewrites() {
    const backendUrl = process.env.CHAT_BACKEND_URL || "http://localhost:8000";
    return {
      beforeFiles: [
        {
          source: "/api/chat",
          destination: `${backendUrl}/chat/`,
        },
        {
          source: "/api/chat/feedback",
          destination: `${backendUrl}/chat/feedback`,
        },
        {
          source: "/api/admin/:path*",
          destination: `${backendUrl}/admin/api/:path*`,
        },
      ],
    };
  },
};
module.exports = nextConfig;