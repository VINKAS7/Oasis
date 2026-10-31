import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { signIn, signUp } from "../lib/auth-client";
import { OasisLogo } from "../components/Brand";
import { ThemeToggle } from "../components/ThemeToggle";
import { Button, ErrorNote, Field, Input } from "../components/ui";

function AuthShell({ title, subtitle, children, footer }: { title: string; subtitle: string; children: ReactNode; footer: ReactNode }) {
  return (
    <div className="relative flex min-h-screen flex-col items-center px-6">
      <ThemeToggle className="absolute top-3 right-3" />
      <div className="flex w-full max-w-sm flex-1 flex-col justify-center py-16">
        <OasisLogo size="lg" className="mb-8" />
        <h1 className="text-[1.75rem] leading-tight font-bold tracking-tight text-stone-800">{title}</h1>
        <p className="mt-1.5 text-stone-500">{subtitle}</p>
        <div className="mt-8">{children}</div>
        <p className="mt-6 text-sm text-stone-500">{footer}</p>
      </div>
      <p className="pb-6 text-xs text-stone-400">Oasis makes any business or website usable by AI assistants.</p>
    </div>
  );
}

// When the auth service is down, the dev proxy answers 500 with an empty body, so better-auth
// has no message to show. Say what is wrong instead of a generic failure.
function authErrorText(error: { message?: string; status?: number }, fallback: string): string {
  if (error.message) return error.message;
  if (!error.status || error.status >= 500) {
    return "The sign-in service isn't answering. If you run Oasis yourself, start everything with npm run dev (the auth service runs on port 3001).";
  }
  return fallback;
}

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    const { error } = await signIn.email({ email, password });
    setLoading(false);
    if (error) setError(authErrorText(error, "Could not log in"));
  };

  return (
    <AuthShell
      title="Log in to Oasis"
      subtitle="Welcome back."
      footer={
        <>
          New here?{" "}
          <Link to="/signup" className="text-brand-700 hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email">
          <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@your-business.com" />
        </Field>
        <Field label="Password">
          <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" loading={loading} className="w-full py-2">
          Continue
        </Button>
      </form>
    </AuthShell>
  );
}

export function SignupPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) return setError("Use at least 8 characters for the password.");
    setLoading(true);
    const { error } = await signUp.email({ name, email, password });
    setLoading(false);
    if (error) setError(authErrorText(error, "Could not create the account"));
  };

  return (
    <AuthShell
      title="Create your account"
      subtitle="Show us your website once; AI assistants can then find you and act for your customers."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="text-brand-700 hover:underline">
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4">
        <Field label="Your name">
          <Input autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Email">
          <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" hint="At least 8 characters.">
          <Input type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" loading={loading} className="w-full py-2">
          Create account
        </Button>
      </form>
    </AuthShell>
  );
}
