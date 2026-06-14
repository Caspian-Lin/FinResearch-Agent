/**
 * Auth API client (FRA-6 backend contract).
 *
 * All requests ride the shared `apiClient`, which injects the bearer token on
 * the way out and normalizes any error into an `ApiError` on the way back —
 * so callers simply `await` and let `ApiError` propagate to the UI layer,
 * which maps `error.code` to a translated message (the raw `detail` is never
 * shown to users).
 *
 * Security: passwords are sent only over the request body to `/auth/login`
 * and `/auth/register`; they are never logged, persisted, or echoed back.
 */
import { apiClient } from './client';
import type { TokenResponse, UserRead } from '@/types/api';

/**
 * Register a new account.
 *
 * On success (201) returns the created user. A 409 from the backend surfaces
 * as an `ApiError` with `code: 'conflict'`; a 422 surfaces as `'validation'`.
 * Does NOT auto-login — the caller decides whether to redirect to /login.
 */
export async function register(email: string, password: string): Promise<UserRead> {
  const response = await apiClient.post<UserRead>('/auth/register', { email, password });
  return response.data;
}

/**
 * Authenticate and persist the returned access token via the token helpers.
 *
 * On success (200) returns the token response; the caller is responsible for
 * storing the token (via `setAccessToken`) and fetching the user profile.
 * A 401 surfaces as `code: 'unauthorized'`.
 */
export async function login(email: string, password: string): Promise<TokenResponse> {
  const response = await apiClient.post<TokenResponse>('/auth/login', { email, password });
  return response.data;
}

/**
 * Fetch the authenticated user's profile (requires a valid bearer token).
 *
 * Used by the auth store to restore the session on page reload (refresh
 * recovery). A 401 surfaces as `code: 'unauthorized'`.
 */
export async function fetchMe(): Promise<UserRead> {
  const response = await apiClient.get<UserRead>('/auth/me');
  return response.data;
}
