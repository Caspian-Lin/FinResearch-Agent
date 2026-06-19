/**
 * Login page (FRA-17).
 *
 * Email + password form backed by antd `Form`. On submit, calls the auth
 * store's `login`, which stores the token and fetches the profile; on success
 * the user is navigated to `state.from` (the route ProtectedRoute intercepted)
 * or `/watchlist` by default.
 *
 * Error handling keys off the stable `ApiError.code` and maps it to a
 * translated message via `t('errors:<code>')` — the backend `detail` is NEVER
 * shown. A 401 (`unauthorized`) is surfaced as `errors:invalidCredentials`.
 *
 * An already-authenticated user visiting /login is redirected to /watchlist.
 */
import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Alert, Button, Card, Form, Input, Typography } from 'antd';

import { ApiError } from '@/api/client';
import { useAuthStore } from '@/store/auth';

const { Title } = Typography;

interface LoginFormValues {
  email: string;
  password: string;
}

export default function LoginPage() {
  const { t } = useTranslation(['auth', 'errors']);
  const navigate = useNavigate();
  const location = useLocation();
  const login = useAuthStore((s) => s.login);
  const status = useAuthStore((s) => s.status);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Already authenticated? Bounce to the app — no point showing the form.
  if (status === 'authenticated') {
    return <Navigate to="/watchlist" replace />;
  }

  // The route the user originally tried to reach (set by ProtectedRoute), so
  // we can return them there after a successful login. Falls back to /watchlist.
  const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname;

  async function handleFinish(values: LoginFormValues) {
    setFormError(null);
    setSubmitting(true);
    try {
      await login(values.email.trim(), values.password);
      navigate(from ?? '/watchlist', { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        // 401 → friendly "wrong credentials"; never echo the backend detail.
        if (err.code === 'unauthorized') {
          setFormError(t('errors:invalidCredentials'));
        } else {
          setFormError(t(`errors:${err.code}`));
        }
      } else {
        setFormError(t('errors:unknown'));
      }
    } finally {
      setSubmitting(false);
    }
  }

  // Show the session-expired banner when the user was bounced here by a 401
  // (i.e. ProtectedRoute redirected them with a `from`).
  const sessionExpired = Boolean(from);

  return (
    <div style={{ maxWidth: 400, margin: '0 auto' }}>
      <Card>
        <Title level={3} style={{ marginBottom: 24, textAlign: 'center' }}>
          {t('auth:signIn.title')}
        </Title>

        {sessionExpired && (
          <Alert
            type="warning"
            showIcon
            message={t('auth:session.expired')}
            style={{ marginBottom: 16 }}
          />
        )}

        {formError && (
          <Alert
            type="error"
            showIcon
            message={formError}
            style={{ marginBottom: 16 }}
            role="alert"
          />
        )}

        <Form<LoginFormValues>
          layout="vertical"
          onFinish={(v) => void handleFinish(v)}
          autoComplete="on"
          preserve={false}
        >
          <Form.Item
            name="email"
            label={t('auth:signIn.email.label')}
            rules={[
              { required: true, message: t('errors:validation') },
              { type: 'email', message: t('errors:validation') },
            ]}
          >
            <Input
              type="email"
              autoComplete="email"
              placeholder={t('auth:signIn.email.placeholder')}
            />
          </Form.Item>

          <Form.Item
            name="password"
            label={t('auth:signIn.password.label')}
            rules={[{ required: true, message: t('errors:validation') }]}
          >
            <Input.Password
              autoComplete="current-password"
              placeholder={t('auth:signIn.password.placeholder')}
            />
          </Form.Item>

          <Button type="primary" htmlType="submit" block loading={submitting}>
            {t('auth:signIn.submit')}
          </Button>
        </Form>

        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Link to="/register">{t('auth:register.link')}</Link>
        </div>
      </Card>
    </div>
  );
}
