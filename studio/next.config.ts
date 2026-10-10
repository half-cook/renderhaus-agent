import type { NextConfig } from "next";
import { proxyUploadLimitBytes } from "./lib/upload-limits";

const studioApiOrigin = (process.env.STUDIO_API_ORIGIN || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

const nextConfig: NextConfig = {
  distDir: process.env.RH_SHOT_BUILD_DIR || ".next",
  // The framework's floating dev badge never belongs in design review captures.
  devIndicators: false,
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
