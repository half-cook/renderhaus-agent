import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <div className="canvas-texture-bg flex min-h-screen items-center justify-center">
      <SignUp fallbackRedirectUrl="/home" />
    </div>
  );
}
