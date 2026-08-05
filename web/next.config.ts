import type { NextConfig } from "next";

// Proxies API calls to the FastAPI backend (server/, run via `python -m
// server.app`, default port 8000) so the browser only ever talks to this
// origin — no CORS config needed on the backend. See MERGE_PLAN.md.
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_ORIGIN}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
