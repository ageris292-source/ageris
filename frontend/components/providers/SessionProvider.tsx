"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
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

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health());
    } catch {
      setHealth(null);
    }
  }, []);

  useEffect(() => {
    setToken(readToken());
    setReady(true);
    void refreshHealth();
    const id = setInterval(refreshHealth, 60_000);
    return () => clearInterval(id);
  }, [refreshHealth]);

  const signOut = useCallback(() => {
    writeToken(null);
    setToken(null);
    setMe(null);
  }, []);

  const signIn = useCallback((t: string) => {
    writeToken(t);
    setToken(t);
  }, []);

  const refreshMe = useCallback(async () => {
    if (!token) return;
    try {
      setMe(await api.me(token));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) signOut();
    }
  }, [token, signOut]);

  useEffect(() => {
    void refreshMe();
  }, [refreshMe]);

  /** Wraps an API call: a 401 signs the user out instead of surfacing an error. */
  const guard = useCallback<Guard>(
    async (fn) => {
      if (!token) return undefined;
      try {
        return await fn(token);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          signOut();
          return undefined;
        }
        throw err;
      }
    },
    [token, signOut],
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
