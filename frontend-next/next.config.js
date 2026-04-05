========== FILE 5: frontend-next/next.config.js ==========
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
              "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data:",
              "font-src 'self'",
              "connect-src 'self' https://*.onrender.com",
            ].join("; "),
          },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
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