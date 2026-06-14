/**
 * Pre-configured axios instance for the FinResearch API.
 *
 * - `baseURL` defaults to `/api` so requests ride the Vite dev proxy (same
 *   origin, no CORS). Override via `VITE_API_BASE_URL`.
 * - The request interceptor injects `Authorization: Bearer <token>` when a
 *   token is present (FRA-17 owns issuing tokens; FRA-16 only forwards them).
 * - The response interceptor normalizes any error into an `ApiError` with a
 *   stable `code` the UI can map to a translated message, and clears the
 *   token on 401 (FRA-17 will extend this to a /login redirect).
 *
 * Security: token material never leaves the Authorization header — it is not
 * logged, not stored on the error object, and not echoed back to the UI.
 */
import axios, { type AxiosError, type AxiosInstance } from 'axios';

import { clearAccessToken, getAccessToken } from './token';

/** Stable, locale-independent error codes the UI keys message off of. */
export type ApiErrorCode =
  | 'unauthorized'
  | 'forbidden'
  | 'notFound'
  | 'conflict'
  | 'validation'
  | 'rateLimited'
  | 'server'
  | 'network'
  | 'unknown';

/**
 * Normalized API error. `code` is the stable identifier the i18n layer maps
 * to a translated message; `status` is the raw HTTP status (0 for network
 * failures); `detail` is the backend's free-form message (kept for debugging
 * only, NOT shown to users — the UI uses `t('errors:<code>')`).
 */
export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly detail: string;

  constructor(code: ApiErrorCode, status: number, detail: string) {
    super(detail || code);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

/** Map an HTTP status (or its absence) to a stable error code. */
function errorCodeFromStatus(status: number | undefined): ApiErrorCode {
  if (status === undefined) return 'network';
  if (status === 401) return 'unauthorized';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'notFound';
  if (status === 409) return 'conflict';
  if (status === 422) return 'validation';
  if (status === 429) return 'rateLimited';
  if (status >= 500) return 'server';
  return 'unknown';
}

/** Extract the backend `{ detail }` message if present. */
function extractDetail(error: AxiosError<unknown>): string {
  const data = error.response?.data;
  if (data && typeof data === 'object' && 'detail' in data) {
    const detail = data.detail;
    if (typeof detail === 'string') return detail;
  }
  return error.message;
}

/** Shared axios instance. Import this from feature API modules. */
export const apiClient: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
  headers: { 'Content-Type': 'application/json' },
  timeout: 15_000,
});

apiClient.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<unknown>) => {
    const status = error.response?.status;
    // On 401 the token is invalid/expired: drop it so the next request is
    // treated as anonymous. FRA-17 will add the /login redirect here.
    if (status === 401) {
      clearAccessToken();
    }
    const code = errorCodeFromStatus(status);
    const detail = extractDetail(error);
    return Promise.reject(new ApiError(code, status ?? 0, detail));
  },
);
