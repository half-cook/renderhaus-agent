import type { NextConfig } from "next";

const studioApiOrigin = (process.env.STUDIO_API_ORIGIN || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${studioApiOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
