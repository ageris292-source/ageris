// Session-scoped JWT storage shared by every page. Storage access can throw
// (private mode, blocked site data); the token then lives in memory only.

export const TOKEN_KEY = "aegis.token";

export function readToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function writeToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}
