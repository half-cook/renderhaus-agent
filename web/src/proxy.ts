import { clerkMiddleware } from "@clerk/nextjs/server";

// Next.js 16 renamed the middleware.ts convention to proxy.ts (same export
// shape) -- see web/node_modules/next/dist/docs/01-app/03-api-reference/
// 03-file-conventions/proxy.md. Auth gating happens at the component/action
// level (sign-in prompts on submit), not by redirecting whole routes, so no
// custom matcher/protection logic is needed here.
export default clerkMiddleware();
