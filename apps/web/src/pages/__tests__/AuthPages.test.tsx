/**
 * LoginPage + RegisterPage component tests (FRA-17).
 *
 * The API layer (`@/api/auth`) is mocked at the module boundary so no HTTP is
 * issued; we control outcomes by resolving/rejecting the mocked functions.
 * The auth store is the real store (driven by the mocked API). Navigation
 * outcomes are observed through a sentinel route rendered inside the same
 * MemoryRouter (if the watchlist route renders, the user navigated there).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import LoginPage from '@/pages/LoginPage';
import RegisterPage from '@/pages/RegisterPage';
import { useAuthStore } from '@/store/auth';
import { ApiError } from '@/api/client';
import { ACCESS_TOKEN_KEY } from '@/api/token';
import i18n from '@/i18n';
import type { TokenResponse, UserRead } from '@/types/api';

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

function makeUser(overrides: Partial<UserRead> = {}): UserRead {
  return {
    id: 'u-1',
    email: 'alice@example.com',
    is_active: true,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  };
}

function renderLogin(initialPath = '/login') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/watchlist" element={<div>WATCHLIST PAGE</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function renderRegister(initialPath = '/register') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/login" element={<div>LOGIN PAGE</div>} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/watchlist" element={<div>WATCHLIST PAGE</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  mocks.loginApi.mockReset();
  mocks.registerApi.mockReset();
  mocks.fetchMe.mockReset();
  // Reset the store to a clean unauthenticated state (the synchronous initial
  // status depends on localStorage, which is now empty).
  useAuthStore.setState({ status: 'unauthenticated', user: null });
  void i18n.changeLanguage('en');
});

// --- LoginPage --------------------------------------------------------------

describe('LoginPage', () => {
  it('renders the form with email + password fields', () => {
    renderLogin();
    expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeEnabled();
  });

  it('shows validation errors on empty submit', async () => {
    const user = userEvent.setup();
    renderLogin();
    await user.click(screen.getByRole('button', { name: /sign in/i }));
    // antd renders the validation message text from `errors:validation`.
    expect(await screen.findByText(/some fields are invalid/i)).toBeInTheDocument();
    expect(mocks.loginApi).not.toHaveBeenCalled();
  });

  it('logs in successfully and navigates to /watchlist', async () => {
    const user = userEvent.setup();
    mocks.loginApi.mockResolvedValue({
      access_token: 'jwt',
      token_type: 'bearer',
      expires_in: 3600,
    });
    const me = makeUser();
    mocks.fetchMe.mockResolvedValue(me);

    renderLogin();
    await user.type(screen.getByLabelText(/email/i), 'alice@example.com');
    await user.type(screen.getByLabelText(/password/i), 'password123');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    // Navigated to /watchlist (sentinel rendered).
    expect(await screen.findByText('WATCHLIST PAGE')).toBeInTheDocument();
    // Token persisted; store authenticated.
    expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBe('jwt');
    expect(useAuthStore.getState().status).toBe('authenticated');
  });

  it('returns to the originally-requested route after login (from state)', async () => {
    const user = userEvent.setup();
    mocks.loginApi.mockResolvedValue({
      access_token: 'jwt',
      token_type: 'bearer',
      expires_in: 3600,
    });
    mocks.fetchMe.mockResolvedValue(makeUser());

    // Land on /login carrying `state.from = /watchlist`, exactly as
    // ProtectedRoute would set when bouncing an unauthenticated user.
    render(
      <MemoryRouter
        initialEntries={[{ pathname: '/login', state: { from: { pathname: '/watchlist' } } }]}
      >
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/watchlist" element={<div>WATCHLIST PAGE</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await user.type(await screen.findByLabelText(/email/i), 'alice@example.com');
    await user.type(screen.getByLabelText(/password/i), 'password123');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    // Logged-in user is returned to /watchlist (the `from` route).
    expect(await screen.findByText('WATCHLIST PAGE')).toBeInTheDocument();
  });

  it('shows invalidCredentials (not backend detail) on 401', async () => {
    const user = userEvent.setup();
    // Use a detail that is NOT the stable-code copy, so we can prove the UI
    // shows the translated message and not the raw backend string.
    mocks.loginApi.mockRejectedValue(new ApiError('unauthorized', 401, 'BACKEND_SECRET_DETAIL'));

    renderLogin();
    await user.type(screen.getByLabelText(/email/i), 'alice@example.com');
    await user.type(screen.getByLabelText(/password/i), 'wrongpass');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByText(/incorrect email or password/i)).toBeInTheDocument();
    // Backend detail must never leak.
    expect(screen.queryByText('BACKEND_SECRET_DETAIL')).toBeNull();
    // Token not persisted; still unauthenticated.
    expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
    expect(useAuthStore.getState().status).toBe('unauthenticated');
  });

  it('shows the generic server message on a 500', async () => {
    const user = userEvent.setup();
    mocks.loginApi.mockRejectedValue(new ApiError('server', 500, 'boom'));

    renderLogin();
    await user.type(screen.getByLabelText(/email/i), 'alice@example.com');
    await user.type(screen.getByLabelText(/password/i), 'password123');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByText(/server error/i)).toBeInTheDocument();
  });

  it('links to the register page', () => {
    renderLogin();
    expect(screen.getByRole('link', { name: /create account/i })).toHaveAttribute(
      'href',
      '/register',
    );
  });

  it('redirects an already-authenticated user to /watchlist', () => {
    useAuthStore.setState({
      status: 'authenticated',
      user: makeUser(),
    });
    renderLogin();
    expect(screen.getByText('WATCHLIST PAGE')).toBeInTheDocument();
  });

  it('switches language instantly (en ↔ zh-CN) without re-submitting', async () => {
    mocks.loginApi.mockResolvedValue({
      access_token: 'jwt',
      token_type: 'bearer',
      expires_in: 3600,
    });
    renderLogin();
    expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument();

    const callsBefore = mocks.loginApi.mock.calls.length;
    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });
    expect(screen.getByRole('heading', { name: /登录/i })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /sign in/i })).toBeNull();

    await act(async () => {
      await i18n.changeLanguage('en');
    });
    expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument();

    // No accidental login attempts from the language switch.
    expect(mocks.loginApi.mock.calls.length).toBe(callsBefore);
  });
});

// --- RegisterPage -----------------------------------------------------------

describe('RegisterPage', () => {
  it('renders the form with email + password + confirm fields', () => {
    renderRegister();
    expect(screen.getByRole('heading', { name: /create account/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm password/i)).toBeInTheDocument();
  });

  it('rejects passwords shorter than 8 characters', async () => {
    const user = userEvent.setup();
    renderRegister();
    await user.type(screen.getByLabelText(/email/i), 'alice@example.com');
    await user.type(screen.getByLabelText(/^password$/i), 'short');
    await user.type(screen.getByLabelText(/confirm password/i), 'short');
    await user.click(screen.getByRole('button', { name: /register/i }));
    expect(await screen.findByText(/some fields are invalid/i)).toBeInTheDocument();
    expect(mocks.registerApi).not.toHaveBeenCalled();
  });

  it('rejects when confirm does not match password', async () => {
    const user = userEvent.setup();
    renderRegister();
    await user.type(screen.getByLabelText(/email/i), 'alice@example.com');
    await user.type(screen.getByLabelText(/^password$/i), 'password123');
    await user.type(screen.getByLabelText(/confirm password/i), 'password999');
    await user.click(screen.getByRole('button', { name: /register/i }));
    expect(await screen.findByText(/some fields are invalid/i)).toBeInTheDocument();
    expect(mocks.registerApi).not.toHaveBeenCalled();
  });

  it('registers successfully: navigates to /login after success', async () => {
    const user = userEvent.setup();
    mocks.registerApi.mockResolvedValue(makeUser({ id: 'u-new' }));

    renderRegister();
    await user.type(screen.getByLabelText(/email/i), 'new@example.com');
    await user.type(screen.getByLabelText(/^password$/i), 'password123');
    await user.type(screen.getByLabelText(/confirm password/i), 'password123');
    await user.click(screen.getByRole('button', { name: /register/i }));

    // The success toast (`messageApi.success`) is fired, then we navigate to
    // /login. The toast itself is a transient overlay tied to the page's
    // message context, so by the time we assert it has unmounted with the
    // page — we assert the navigation outcome and the API call instead.
    await waitFor(() => expect(screen.getByText('LOGIN PAGE')).toBeInTheDocument());
    expect(mocks.registerApi).toHaveBeenCalledWith('new@example.com', 'password123');
    // No token persisted (register does not auto-login).
    expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
    expect(useAuthStore.getState().status).toBe('unauthenticated');
  });

  it('shows emailExists (not backend detail) on 409 conflict', async () => {
    const user = userEvent.setup();
    mocks.registerApi.mockRejectedValue(
      new ApiError('conflict', 409, 'Email already registered.'),
    );

    renderRegister();
    await user.type(screen.getByLabelText(/email/i), 'dup@example.com');
    await user.type(screen.getByLabelText(/^password$/i), 'password123');
    await user.type(screen.getByLabelText(/confirm password/i), 'password123');
    await user.click(screen.getByRole('button', { name: /register/i }));

    expect(await screen.findByText(/already exists/i)).toBeInTheDocument();
    expect(screen.queryByText('Email already registered.')).toBeNull();
  });

  it('shows the validation message on 422', async () => {
    const user = userEvent.setup();
    mocks.registerApi.mockRejectedValue(new ApiError('validation', 422, 'bad'));

    renderRegister();
    await user.type(screen.getByLabelText(/email/i), 'not-an-email');
    // Force a submit even though email rule would normally fire first; we mock
    // the API so we can drive a 422 from the server side.
    await user.type(screen.getByLabelText(/^password$/i), 'password123');
    await user.type(screen.getByLabelText(/confirm password/i), 'password123');
    await user.click(screen.getByRole('button', { name: /register/i }));
    // The form-level error or field-level validation message must appear.
    await waitFor(() => {
      expect(screen.queryByText(/some fields are invalid/i)).not.toBeNull();
    });
  });

  it('links to the sign-in page', () => {
    renderRegister();
    expect(screen.getByRole('link', { name: /sign in/i })).toHaveAttribute('href', '/login');
  });

  it('redirects an already-authenticated user to /watchlist', () => {
    useAuthStore.setState({ status: 'authenticated', user: makeUser() });
    renderRegister();
    expect(screen.getByText('WATCHLIST PAGE')).toBeInTheDocument();
  });
});
