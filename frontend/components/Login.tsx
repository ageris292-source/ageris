"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";

export function Login({ onToken }: { onToken: (t: string) => void }) {
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
      onToken(access_token);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Cannot reach the Aegis API");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto mt-24 max-w-sm px-4">
      <h1 className="mb-1 text-2xl font-semibold">Aegis</h1>
      <p className="mb-8 text-sm text-muted">Sign in to the research console.</p>
      <form onSubmit={submit} className="space-y-3">
        <input
          className="w-full rounded border border-line bg-panel px-3 py-2"
          type="email" placeholder="Email" autoComplete="username" required
          value={email} onChange={(e) => setEmail(e.target.value)}
        />
        <input
          className="w-full rounded border border-line bg-panel px-3 py-2"
          type="password" placeholder="Password" autoComplete="current-password" required
          value={password} onChange={(e) => setPassword(e.target.value)}
        />
        {error && <p className="text-sm text-fail">{error}</p>}
        <button
          className="w-full rounded bg-ink px-3 py-2 font-medium text-surface disabled:opacity-50"
          disabled={busy}
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
