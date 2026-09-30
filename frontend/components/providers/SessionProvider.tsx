"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type Health, type Me } from "@/lib/api";
import { readToken, writeToken } from "@/lib/auth";

type Guard = <T>(fn: (t: string) => Promise<T>) => Promise<T | undefined>;

export interface Session {
  token: string | null;
  ready: boolean;
  me: Me | null;
  health: Health | null;
  isAdmin: boolean;
  signIn: (t: string) => void;
  signOut: () => void;
  guard: Guard;
  refreshMe: () => Promise<void>;
  refreshHealth: () => Promise<void>;
}

const Ctx = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  // The token currently in force. A 401 from a request made with an older
  // token (e.g. one revoked by a password change) must not end the new session.
  const current = useRef<string | null>(null);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health());
    } catch {
      setHealth(null);
    }
  }, []);

  useEffect(() => {
    const t = readToken();
    current.current = t;
    setToken(t);
    setReady(true);
    void refreshHealth();
    const id = setInterval(refreshHealth, 60_000);
    return () => clearInterval(id);
  }, [refreshHealth]);

  const signOut = useCallback(() => {
    current.current = null;
    writeToken(null);
    setToken(null);
    setMe(null);
  }, []);

  const signIn = useCallback((t: string) => {
    current.current = t;
    writeToken(t);
    setToken(t);
  }, []);

  /** Sign out only if the rejected token is still the one in force. */
  const expire = useCallback(
    (used: string) => {
      if (current.current === used) signOut();
    },
    [signOut],
  );

  const refreshMe = useCallback(async () => {
    const t = current.current;
    if (!t) return;
    try {
      const m = await api.me(t);
      if (current.current === t) setMe(m);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) expire(t);
    }
  }, [expire]);

  useEffect(() => {
    if (token) void refreshMe();
  }, [token, refreshMe]);

  /** Wraps an API call: a 401 signs the user out instead of surfacing an error. */
  const guard = useCallback<Guard>(
    async (fn) => {
      const t = token;
      if (!t) return undefined;
      try {
        return await fn(t);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          expire(t);
          return undefined;
        }
        throw err;
      }
    },
    [token, expire],
  );

  const value = useMemo<Session>(
    () => ({
      token,
      ready,
      me,
      health,
      isAdmin: me?.role === "admin",
      signIn,
      signOut,
      guard,
      refreshMe,
      refreshHealth,
    }),
    [token, ready, me, health, signIn, signOut, guard, refreshMe, refreshHealth],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession must be used inside <SessionProvider>");
  return s;
}
