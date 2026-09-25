"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Health, type Me } from "@/lib/api";
import { readToken, writeToken } from "@/lib/auth";

export function useSession() {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    setToken(readToken());
    setReady(true);
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  const signOut = useCallback(() => {
    writeToken(null);
    setToken(null);
    setMe(null);
  }, []);

  const signIn = useCallback((t: string) => {
    writeToken(t);
    setToken(t);
  }, []);

  useEffect(() => {
    if (!token) return;
    api.me(token).then(setMe).catch((err) => {
      if (err instanceof ApiError && err.status === 401) signOut();
    });
  }, [token, signOut]);

  /** Wraps an API call: a 401 signs the user out instead of surfacing an error. */
  const guard = useCallback(
    async <T,>(fn: (t: string) => Promise<T>): Promise<T | undefined> => {
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

  return { token, ready, me, health, signIn, signOut, guard };
}
