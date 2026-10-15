import { Suspense } from "react";
import { InviteSignup } from "@/components/beta/InviteSignup";

export default function SignInPage() {
  return <Suspense><InviteSignup mode="sign-in" /></Suspense>;
}
