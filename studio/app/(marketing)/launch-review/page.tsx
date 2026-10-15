import { notFound } from "next/navigation";
import { Suspense } from "react";
import { LaunchReview } from "@/components/rh/LaunchReview";

/** Dev-only gallery of the quiet-beta states (spec 4.12) for design review screenshots. 404 in production builds. */
export default function LaunchReviewPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Suspense fallback={null}><LaunchReview /></Suspense>;
}
