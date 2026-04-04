/** @type {import('next').NextConfig} */
const nextConfig = {
  pageExtensions: ["ts", "tsx"],

  // Allow both localhost and 127.0.0.1 during local dev
  allowedDevOrigins: ["localhost", "127.0.0.1"],

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
