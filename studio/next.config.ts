import type { NextConfig } from "next";
import { proxyUploadLimitBytes } from "./lib/upload-limits";

const studioApiOrigin = (process.env.STUDIO_API_ORIGIN || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

const nextConfig: NextConfig = {
  experimental: {
    middlewareClientMaxBodySize: proxyUploadLimitBytes(process.env),
  },
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
