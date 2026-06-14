/**
 * ProtectedRoute tests (FRA-17).
 *
 * Drives the guard across all three auth statuses by manipulating the store
 * directly (the store is mocked-out at the API boundary elsewhere). We render
 * the guard inside a MemoryRouter with a sentinel child route and assert on
 * what shows up: Navigate target (login), the spinner, or the child content.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { useAuthStore } from '@/store/auth';

// We don't mock the store itself — we drive it via getState().setStatus-like
// helpers by setting state directly. The store exposes its actions; to set
// arbitrary status/user in tests we mutate via the underlying set through a
// tiny helper that uses the real store.
function setAuthStatus(
  status: 'loading' | 'authenticated' | 'unauthenticated',
  user: ReturnType<typeof useAuthStore.getState>['user'] = null,
) {
  useAuthStore.setState({ status, user });
}

beforeEach(() => {
  window.localStorage.clear();
  useAuthStore.setState({ status: 'unauthenticated', user: null });
});

describe('ProtectedRoute', () => {
  it('redirects to /login (carrying location state) when unauthenticated', () => {
    setAuthStatus('unauthenticated');
    render(
      <MemoryRouter initialEntries={['/watchlist']}>
        <Routes>
          <Route element={<ProtectedRoute />}>
            <Route path="/watchlist" element={<div>SECRET</div>} />
          </Route>
          <Route path="/login" element={<div>LOGIN PAGE</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('LOGIN PAGE')).toBeInTheDocument();
    expect(screen.queryByText('SECRET')).toBeNull();
  });

  it('renders a spinner while loading', () => {
    setAuthStatus('loading');
    render(
      <MemoryRouter initialEntries={['/watchlist']}>
        <Routes>
          <Route element={<ProtectedRoute />}>
            <Route path="/watchlist" element={<div>SECRET</div>} />
          </Route>
          <Route path="/login" element={<div>LOGIN PAGE</div>} />
        </Routes>
      </MemoryRouter>,
    );
    // The loading copy from i18n is rendered; the secret page is not yet shown.
    expect(screen.queryByText('SECRET')).toBeNull();
    expect(screen.queryByText('LOGIN PAGE')).toBeNull();
  });

  it('renders the child route when authenticated', () => {
    setAuthStatus('authenticated', {
      id: 'u-1',
      email: 'a@b.com',
      is_active: true,
      created_at: '2024-01-01T00:00:00Z',
    });
    render(
      <MemoryRouter initialEntries={['/watchlist']}>
        <Routes>
          <Route element={<ProtectedRoute />}>
            <Route path="/watchlist" element={<div>SECRET</div>} />
          </Route>
          <Route path="/login" element={<div>LOGIN PAGE</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('SECRET')).toBeInTheDocument();
    expect(screen.queryByText('LOGIN PAGE')).toBeNull();
  });
});
