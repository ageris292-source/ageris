"use client";

import { Eye, EyeOff, KeyRound, LineChart, ShieldCheck, Wallet } from "lucide-react";
import { useState } from "react";
import { BrandMark } from "@/components/shell/Brand";
import { useSession } from "@/components/providers/SessionProvider";
import { Button, Callout, Field, Input } from "@/components/ui/core";
import { api, ApiError } from "@/lib/api";

function PasswordInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input {...props} type={show ? "text" : "password"} className="pr-10" />
      <button
        type="button"
        onClick={() => setShow((v) => !v)}
        className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-subtle hover:text-ink"
        aria-label={show ? "Hide password" : "Show password"}
      >
        {show ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  );
}

const FEATURES = [
  { icon: LineChart, title: "Multi-agent research", body: "Technical, fundamental, news, valuation, macro and risk agents — every one point-in-time." },
  { icon: ShieldCheck, title: "24-gate risk engine", body: "Only a deterministic engine can approve a trade. Unknown never passes." },
  { icon: Wallet, title: "Paper trading first", body: "Simulated fills with human approval on every order. Live trading stays off." },
];

export function LoginScreen() {
  const { signIn, health } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { access_token } = await api.login(email, password);
      signIn(access_token);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 401
            ? "That email and password don't match an active account."
            : err.message
          : "Can't reach the Aegis server. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-[#0b1220] p-12 text-white lg:flex lg:flex-col">
        <div
          className="absolute inset-0 opacity-60"
          style={{
            background:
              "radial-gradient(900px 500px at 10% 0%, rgba(57,135,229,0.35), transparent 60%), radial-gradient(700px 400px at 90% 100%, rgba(25,158,112,0.22), transparent 60%)",
          }}
          aria-hidden
        />
        <div className="relative flex items-center gap-3">
          <BrandMark size={34} />
          <span className="text-xl font-semibold tracking-tight">Aegis</span>
        </div>
        <div className="relative mt-auto max-w-md">
          <h1 className="text-3xl font-semibold leading-tight tracking-tight">
            Research Indian equities with discipline, not hunches.
          </h1>
          <p className="mt-3 text-sm text-white/70">
            NSE & BSE research, backtesting and paper trading — capital preservation first, and “no trade” by default.
          </p>
          <ul className="mt-10 space-y-5">
            {FEATURES.map((f) => (
              <li key={f.title} className="flex gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/10">
                  <f.icon size={18} aria-hidden />
                </span>
                <div>
                  <p className="text-sm font-medium">{f.title}</p>
                  <p className="text-xs text-white/65">{f.body}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative mt-12 text-xs text-white/45">Not investment advice. Past results do not predict future results.</p>
      </aside>

      <section className="flex items-center justify-center px-5 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <BrandMark size={32} />
            <span className="text-xl font-semibold">Aegis</span>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight">Welcome back</h2>
          <p className="mt-1 text-sm text-muted">Sign in to your research console.</p>
          <form onSubmit={submit} className="mt-8 space-y-4">
            <Field label="Email">
              {(id) => (
                <Input
                  id={id}
                  type="email"
                  autoComplete="username"
                  required
                  autoFocus
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="h-10"
                />
              )}
            </Field>
            <Field label="Password">
              {(id) => (
                <PasswordInput
                  id={id}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="h-10"
                />
              )}
            </Field>
            {error && (
              <p role="alert" className="rounded-md bg-fail-soft px-3 py-2 text-sm text-fail">
                {error}
              </p>
            )}
            <Button type="submit" variant="primary" size="lg" loading={busy} className="w-full">
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>
          <p className="mt-6 text-xs text-subtle">
            No account? Aegis is invite-only — ask your admin to invite you.
            {health === null && <span className="mt-2 block text-warn">The server isn&apos;t responding right now.</span>}
          </p>
        </div>
      </section>
    </main>
  );
}

export function ChangePasswordForm({ forced, onDone }: { forced?: boolean; onDone?: () => void }) {
  const { guard, signIn, refreshMe } = useSession();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const tooShort = next.length > 0 && next.length < 12;
  const mismatch = confirm.length > 0 && confirm !== next;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next.length < 12 || next !== confirm) return;
    setBusy(true);
    setError(null);
    try {
      const r = await guard((t) => api.changePassword(t, current, next));
      if (r) {
        signIn(r.access_token);
        await refreshMe();
        setCurrent("");
        setNext("");
        setConfirm("");
        onDone?.();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change the password");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label={forced ? "Temporary password" : "Current password"}>
        {(id) => <PasswordInput id={id} autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />}
      </Field>
      <Field label="New password" hint="At least 12 characters. A passphrase of a few words works well." error={tooShort ? "Use at least 12 characters." : undefined}>
        {(id) => <PasswordInput id={id} autoComplete="new-password" required value={next} onChange={(e) => setNext(e.target.value)} />}
      </Field>
      <Field label="Confirm new password" error={mismatch ? "Passwords don't match." : undefined}>
        {(id) => <PasswordInput id={id} autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />}
      </Field>
      {error && (
        <p role="alert" className="rounded-md bg-fail-soft px-3 py-2 text-sm text-fail">
          {error}
        </p>
      )}
      <Button type="submit" variant="primary" loading={busy} disabled={next.length < 12 || next !== confirm || !current} className={forced ? "w-full" : ""}>
        {forced ? "Set password and continue" : "Update password"}
      </Button>
      {!forced && <p className="text-xs text-subtle">Other signed-in sessions are signed out when you change your password.</p>}
    </form>
  );
}

export function ForcedPasswordScreen() {
  const { me, signOut } = useSession();
  return (
    <main className="flex min-h-screen items-center justify-center px-5 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex h-11 w-11 items-center justify-center rounded-xl bg-accent-soft text-accent">
          <KeyRound size={20} aria-hidden />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">Set your password</h1>
        <p className="mt-1 text-sm text-muted">
          You signed in as <span className="font-medium text-ink">{me?.email}</span> with a temporary password. Choose your own to continue.
        </p>
        <Callout tone="info" className="mb-6 mt-6">
          Aegis never shows your password to anyone, including admins.
        </Callout>
        <ChangePasswordForm forced />
        <button onClick={signOut} className="mt-6 text-xs text-muted underline-offset-2 hover:underline">
          Sign out instead
        </button>
      </div>
    </main>
  );
}
