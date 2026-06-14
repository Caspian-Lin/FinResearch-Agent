/**
 * Access-token storage helpers.
 *
 * Pure functions over `window.localStorage` — no framework coupling — so the
 * same helpers can be reused by axios interceptors, route guards (FRA-17) and
 * tests. Every access is wrapped in try/catch so SSR or environments with a
 * disabled/quota-exceeded localStorage degrade to "no token" instead of
 * throwing.
 */

const TOKEN_KEY = 'fra.access_token';

/** Read the persisted access token, or `null` when none/unavailable. */
export function getAccessToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/** Persist the access token. */
export function setAccessToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Ignore storage failures (private mode, quota, SSR) — callers must
    // rely on the 401 path to re-authenticate.
  }
}

/** Remove the persisted access token. */
export function clearAccessToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Same rationale as above.
  }
}

/** localStorage key used to store the token (exported for tests). */
export const ACCESS_TOKEN_KEY = TOKEN_KEY;
