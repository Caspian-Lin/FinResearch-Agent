/**
 * Auth state machine (FRA-17).
 *
 * The store drives the whole auth lifecycle for the UI:
 *
 *  - On boot, `status` is initialized **synchronously** from the presence of a
 *    token in localStorage: token → `'loading'` (we don't yet know if it's
 *    valid), no token → `'unauthenticated'`. This lets `ProtectedRoute` paint
 *    a spinner instead of flashing the login page during refresh recovery.
 *  - `initialize()` runs once on app mount: if a token exists, it calls
 *    `fetchMe()` to validate it. On success the user is populated and
 *    `status` flips to `'authenticated'`; on failure (401 / network) the
 *    token is cleared and `status` becomes `'unauthenticated'`. Idempotent —
 *    safe to call more than once.
 *  - `login()` / `register()` wrap the API module; `login` stores the token
 *    and fetches the profile, `register` returns the created user without
 *    auto-logging-in (the UI decides the next step).
 *  - `logout()` clears the token and resets state.
 *
 * Errors from the API layer propagate as `ApiError` to the caller (the page),
 * which maps `error.code` to a translated message — never the raw `detail`.
 */
import { create } from 'zustand';

import { fetchMe, login as loginApi, register as registerApi } from '@/api/auth';
import { clearAccessToken, getAccessToken, setAccessToken } from '@/api/token';
import type { UserRead } from '@/types/api';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface AuthState {
  /** Current auth lifecycle phase. Drives ProtectedRoute rendering. */
  status: AuthStatus;
  /** The authenticated user, or null while loading/unauthenticated. */
  user: UserRead | null;
  /**
   * Validate the persisted token (if any) and resolve the session. Idempotent:
   * a no-op when already `authenticated`. Safe to call on every app mount.
   */
  initialize: () => Promise<void>;
  /** Authenticate, store the token, fetch the profile, become authenticated. */
  login: (email: string, password: string) => Promise<void>;
  /** Register a new account; returns the created user (does NOT auto-login). */
  register: (email: string, password: string) => Promise<UserRead>;
  /** Clear the token + user, become unauthenticated. */
  logout: () => void;
}

// Synchronous initial status: a present token means "verify it"; no token
// means the user is definitively anonymous.
const initialStatus: AuthStatus = getAccessToken() ? 'loading' : 'unauthenticated';

export const useAuthStore = create<AuthState>((set, get) => ({
  status: initialStatus,
  user: null,

  async initialize() {
    // Idempotent: never re-fetch once we've resolved the session.
    if (get().status === 'authenticated') return;
    if (!getAccessToken()) {
      set({ status: 'unauthenticated', user: null });
      return;
    }
    try {
      const user = await fetchMe();
      set({ status: 'authenticated', user });
    } catch {
      // Invalid/expired token (401) or network failure: treat as logged out.
      clearAccessToken();
      set({ status: 'unauthenticated', user: null });
    }
  },

  async login(email, password) {
    const token = await loginApi(email, password);
    setAccessToken(token.access_token);
    // Fetch the profile so the UI (Header, etc.) has the full UserRead.
    const user = await fetchMe();
    set({ status: 'authenticated', user });
  },

  async register(email, password) {
    return registerApi(email, password);
  },

  logout() {
    clearAccessToken();
    set({ status: 'unauthenticated', user: null });
  },
}));
