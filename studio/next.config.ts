import type { NextConfig } from "next";

const studioApiUrl = process.env.STUDIO_API_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  experimental: {
    // Agent media jobs commonly outlive Next's 30-second development proxy default.
    proxyTimeout: 25 * 60 * 1000,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${studioApiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
