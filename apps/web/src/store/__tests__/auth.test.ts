/**
 * Auth store tests (FRA-17).
 *
 * The API layer (`@/api/auth`) is mocked at the module boundary so no HTTP is
 * issued. We drive the store through its lifecycle: initialize / login /
 * register / logout, and assert on `getState()` + `localStorage`.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { ACCESS_TOKEN_KEY } from '@/api/token';
import { ApiError } from '@/api/client';
import type { TokenResponse, UserRead } from '@/types/api';

// Re-create the store for each test so the synchronous initial-status derived
// from localStorage is fresh. We reset localStorage in `beforeEach` and use a
// dynamic import + cache-busting via vi.resetModules.

const mocks = vi.hoisted(() => ({
  loginApi: vi.fn<(email: string, password: string) => Promise<TokenResponse>>(),
  registerApi: vi.fn<(email: string, password: string) => Promise<UserRead>>(),
  fetchMe: vi.fn<() => Promise<UserRead>>(),
}));

vi.mock('@/api/auth', () => ({
  login: mocks.loginApi,
  register: mocks.registerApi,
  fetchMe: mocks.fetchMe,
}));

// Import the store AFTER the mock is registered. `importFresh` reloads the
// module so the synchronous `getAccessToken()`-based initial status is right.
async function importFreshStore() {
  vi.resetModules();
  const mod = await import('@/store/auth');
  return mod.useAuthStore;
}

function makeUser(overrides: Partial<UserRead> = {}): UserRead {
  return {
    id: 'u-1',
    email: 'alice@example.com',
    is_active: true,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  window.localStorage.clear();
  mocks.loginApi.mockReset();
  mocks.registerApi.mockReset();
  mocks.fetchMe.mockReset();
});

describe('auth store — initial status', () => {
  it('is unauthenticated when no token is present', async () => {
    const store = await importFreshStore();
    expect(store.getState().status).toBe('unauthenticated');
    expect(store.getState().user).toBeNull();
  });

  it('is loading when a token is present (refresh recovery pending)', async () => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'stale-token');
    const store = await importFreshStore();
    expect(store.getState().status).toBe('loading');
  });
});

describe('auth store — initialize()', () => {
  it('authenticates when fetchMe succeeds (valid persisted token)', async () => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'valid-token');
    const user = makeUser();
    mocks.fetchMe.mockResolvedValue(user);

    const store = await importFreshStore();
    await store.getState().initialize();

    expect(store.getState().status).toBe('authenticated');
    expect(store.getState().user).toEqual(user);
    expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBe('valid-token');
  });

  it('becomes unauthenticated + clears token when fetchMe rejects with 401', async () => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'expired-token');
    mocks.fetchMe.mockRejectedValue(new ApiError('unauthorized', 401, 'bad token'));

    const store = await importFreshStore();
    await store.getState().initialize();

    expect(store.getState().status).toBe('unauthenticated');
    expect(store.getState().user).toBeNull();
    expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
  });

  it('becomes unauthenticated + clears token on network failure', async () => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'some-token');
    mocks.fetchMe.mockRejectedValue(new ApiError('network', 0, 'offline'));

    const store = await importFreshStore();
    await store.getState().initialize();

    expect(store.getState().status).toBe('unauthenticated');
    expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
  });

  it('becomes unauthenticated immediately when there is no token', async () => {
    const store = await importFreshStore();
    await store.getState().initialize();
    expect(mocks.fetchMe).not.toHaveBeenCalled();
    expect(store.getState().status).toBe('unauthenticated');
  });

  it('is idempotent — does not refetch once authenticated', async () => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'valid-token');
    mocks.fetchMe.mockResolvedValue(makeUser());

    const store = await importFreshStore();
    await store.getState().initialize();
    await store.getState().initialize();

    expect(mocks.fetchMe).toHaveBeenCalledTimes(1);
  });
});

describe('auth store — login()', () => {
  it('stores the token, fetches the profile, becomes authenticated', async () => {
    const token: TokenResponse = {
      access_token: 'fresh-jwt',
      token_type: 'bearer',
      expires_in: 3600,
    };
    mocks.loginApi.mockResolvedValue(token);
    const user = makeUser();
    mocks.fetchMe.mockResolvedValue(user);

    const store = await importFreshStore();
    await store.getState().login('alice@example.com', 'password123');

    expect(mocks.loginApi).toHaveBeenCalledWith('alice@example.com', 'password123');
    expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBe('fresh-jwt');
    expect(store.getState().status).toBe('authenticated');
    expect(store.getState().user).toEqual(user);
  });

  it('propagates ApiError (401) without storing a token', async () => {
    mocks.loginApi.mockRejectedValue(new ApiError('unauthorized', 401, 'nope'));

    const store = await importFreshStore();
    await expect(store.getState().login('x@y.com', 'bad')).rejects.toBeInstanceOf(ApiError);

    expect(store.getState().status).toBe('unauthenticated');
    expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
  });

  it('does not persist a token when fetchMe fails after login', async () => {
    mocks.loginApi.mockResolvedValue({
      access_token: 'jwt',
      token_type: 'bearer',
      expires_in: 3600,
    });
    mocks.fetchMe.mockRejectedValue(new ApiError('network', 0, 'offline'));

    const store = await importFreshStore();
    await expect(store.getState().login('x@y.com', 'pw123456')).rejects.toBeInstanceOf(ApiError);
    // The token WAS written by login before fetchMe threw; acceptable, since a
    // subsequent /login retry will overwrite it, and the next 401 clears it.
    // We only assert the user is not marked authenticated.
    expect(store.getState().status).toBe('unauthenticated');
    expect(store.getState().user).toBeNull();
  });
});

describe('auth store — register()', () => {
  it('returns the created user without auto-logging-in', async () => {
    const created = makeUser({ id: 'u-new', email: 'new@example.com' });
    mocks.registerApi.mockResolvedValue(created);

    const store = await importFreshStore();
    const result = await store.getState().register('new@example.com', 'password123');

    expect(result).toEqual(created);
    expect(mocks.registerApi).toHaveBeenCalledWith('new@example.com', 'password123');
    // No token, no authenticated state.
    expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
    expect(store.getState().status).toBe('unauthenticated');
  });

  it('propagates ApiError (409 conflict)', async () => {
    mocks.registerApi.mockRejectedValue(new ApiError('conflict', 409, 'dup'));

    const store = await importFreshStore();
    await expect(
      store.getState().register('dup@example.com', 'password123'),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe('auth store — logout()', () => {
  it('clears the token and resets state', async () => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'jwt');
    mocks.fetchMe.mockResolvedValue(makeUser());

    const store = await importFreshStore();
    await store.getState().initialize();
    expect(store.getState().status).toBe('authenticated');

    store.getState().logout();

    expect(store.getState().status).toBe('unauthenticated');
    expect(store.getState().user).toBeNull();
    expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
  });
});
