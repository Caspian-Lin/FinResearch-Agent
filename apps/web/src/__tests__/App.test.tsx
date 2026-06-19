/**
 * App layout tests — Header user area + global 401 handler (FRA-17).
 *
 * App is rendered inside a MemoryRouter with a sentinel child route so the
 * `<Outlet/>` has something to show. The auth store is the real store driven
 * via setState; `initialize()` is stubbed where we want to assert on the
 * synchronous render of a given status (loading spin, etc.) without the
 * mount effect racing in.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import axios, {
  type AxiosAdapter,
  type InternalAxiosRequestConfig,
  type AxiosResponse,
} from 'axios';

import App from '@/App';
import { useAuthStore } from '@/store/auth';
import { setUnauthorizedHandler, apiClient } from '@/api/client';
import { ACCESS_TOKEN_KEY } from '@/api/token';
import type { UserRead } from '@/types/api';

function makeUser(overrides: Partial<UserRead> = {}): UserRead {
  return {
    id: 'u-1',
    email: 'alice@example.com',
    is_active: true,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  };
}

function renderApp(initialPath = '/watchlist') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<App />}>
          <Route path="/watchlist" element={<div>WATCHLIST CONTENT</div>} />
          <Route path="/login" element={<div>LOGIN CONTENT</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  useAuthStore.setState({ status: 'unauthenticated', user: null });
  setUnauthorizedHandler(null);
  // Default: initialize() resolves immediately as a no-op so the mount effect
  // doesn't race the assertions. Individual tests override where needed.
  vi.spyOn(useAuthStore.getState(), 'initialize').mockResolvedValue(undefined);
});

describe('App — Header user area', () => {
  it('shows a "Sign in" button when unauthenticated', () => {
    renderApp();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('shows the email + sign-out menu when authenticated', async () => {
    useAuthStore.setState({ status: 'authenticated', user: makeUser() });
    renderApp();
    expect(screen.getByText('alice@example.com')).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByText('alice@example.com'));
    // Dropdown menu item (English copy from auth:userMenu.signOut).
    expect(await screen.findByText('Sign out')).toBeInTheDocument();
  });

  it('logs out and navigates to /login on sign-out click', async () => {
    useAuthStore.setState({ status: 'authenticated', user: makeUser() });
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'jwt');
    renderApp();
    expect(screen.getByText('alice@example.com')).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByText('alice@example.com'));
    const signOutItem = await screen.findByText('Sign out');
    await user.click(signOutItem);

    await waitFor(() => expect(screen.getByText('LOGIN CONTENT')).toBeInTheDocument());
    expect(useAuthStore.getState().status).toBe('unauthenticated');
    expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
  });

  it('renders a small spinner in the header while loading', () => {
    useAuthStore.setState({ status: 'loading', user: null });
    const { container } = renderApp();
    // antd Spin renders an element with class ant-spin.
    expect(container.querySelector('.ant-spin')).not.toBeNull();
  });
});

describe('App — global 401 handler', () => {
  it('a 401 response triggers logout + navigate to /login', async () => {
    useAuthStore.setState({ status: 'authenticated', user: makeUser() });
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'jwt');

    renderApp();
    expect(await screen.findByText('WATCHLIST CONTENT')).toBeInTheDocument();

    // Stub the lowest axios layer (adapter) so any request through apiClient
    // resolves to a 401, exercising the response interceptor end-to-end. The
    // adapter returns a rejected promise carrying a real AxiosError whose
    // `response.status` is 401.
    const adapter: AxiosAdapter = (config: InternalAxiosRequestConfig) => {
      const response: Partial<AxiosResponse> = {
        status: 401,
        data: { detail: 'token expired' },
        statusText: 'Unauthorized',
        headers: {},
        config,
      };
      return Promise.reject(
        new axios.AxiosError(
          'Request failed with status code 401',
          axios.AxiosError.ERR_BAD_REQUEST,
          config,
          undefined,
          response as AxiosResponse,
        ),
      );
    };
    apiClient.defaults.adapter = adapter;

    // Fire a request; it rejects with an ApiError (interceptor normalized it).
    await expect(apiClient.get('/anything')).rejects.toMatchObject({ code: 'unauthorized' });

    // The interceptor cleared the token + invoked App's handler, which logged
    // out and navigated to /login.
    await waitFor(() => {
      expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
    });
    expect(useAuthStore.getState().status).toBe('unauthenticated');
    await waitFor(() => expect(screen.getByText('LOGIN CONTENT')).toBeInTheDocument());

    // And critically, the backend detail never appears in the DOM.
    expect(screen.queryByText('token expired')).toBeNull();
  });
});

describe('App — layout (FRA-24)', () => {
  it('pins the risk disclaimer inside the Footer, not floating in Content', () => {
    const { container } = renderApp();
    const footer = container.querySelector('footer');
    const content = container.querySelector('.ant-layout-content');
    // The disclaimer is a warning Alert; it must live in the footer...
    expect(footer?.querySelector('.ant-alert-warning')).not.toBeNull();
    // ...and NOT float inside the page content area.
    expect(content?.querySelector('.ant-alert-warning')).toBeNull();
  });

  it('makes the Header sticky so it stays visible while scrolling', () => {
    const { container } = renderApp();
    const header = container.querySelector('header');
    expect(header).not.toBeNull();
    expect(header).toHaveClass('app-header');
  });

  it('persists the selected theme mode and updates the document theme', async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(screen.getByText('Dark'));

    expect(window.localStorage.getItem('fra.theme')).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });
});
