import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <div className="canvas-texture-bg flex min-h-screen items-center justify-center">
      <SignIn fallbackRedirectUrl="/home" />
    </div>
  );
}
