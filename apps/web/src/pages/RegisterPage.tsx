/**
 * Register page (FRA-17).
 *
 * Email + password + password-confirm form. On submit, calls the auth store's
 * `register`, which returns the created `UserRead`. We do NOT auto-login — the
 * user is shown a success toast and redirected to /login to sign in
 * explicitly (matches the FRA-6 contract: registration and login are separate
 * endpoints; no token is issued on register).
 *
 * Error handling keys off the stable `ApiError.code`:
 *  - `conflict` (409, email taken)   → `errors:emailExists`, shown as an inline
 *    field error on the email input so the user can fix and retry.
 *  - `validation` (422, malformed)   → `errors:validation` as a form-level alert.
 *  - anything else                   → `t('errors:<code>')`.
 * The backend `detail` is NEVER shown.
 *
 * An already-authenticated user visiting /register is redirected to /watchlist.
 */
import { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Alert, Button, Card, Form, Input, Typography, message } from 'antd';

import { ApiError } from '@/api/client';
import { useAuthStore } from '@/store/auth';

const { Title } = Typography;

interface RegisterFormValues {
  email: string;
  password: string;
  confirm: string;
}

export default function RegisterPage() {
  const { t } = useTranslation(['auth', 'errors']);
  const navigate = useNavigate();
  const register = useAuthStore((s) => s.register);
  const status = useAuthStore((s) => s.status);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [messageApi, messageContext] = message.useMessage();

  const [form] = Form.useForm<RegisterFormValues>();

  // Already authenticated? Bounce to the app.
  if (status === 'authenticated') {
    return <Navigate to="/watchlist" replace />;
  }

  async function handleFinish(values: RegisterFormValues) {
    setFormError(null);
    setSubmitting(true);
    try {
      await register(values.email.trim(), values.password);
      messageApi.success(t('auth:register.success'));
      navigate('/login', { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        // 409 → email already registered: surface as a field error so the user
        // can edit and retry without losing the rest of the form.
        if (err.code === 'conflict') {
          form.setFields([{ name: 'email', errors: [t('errors:emailExists')] }]);
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

  return (
    <div className="auth-shell">
      {messageContext}
      <Card className="auth-card">
        <Title level={3} style={{ marginBottom: 24, textAlign: 'center' }}>
          {t('auth:register.title')}
        </Title>

        {formError && (
          <Alert
            type="error"
            showIcon
            message={formError}
            style={{ marginBottom: 16 }}
            role="alert"
          />
        )}

        <Form
          form={form}
          layout="vertical"
          onFinish={(v) => void handleFinish(v)}
          autoComplete="on"
          preserve={false}
        >
          <Form.Item
            name="email"
            label={t('auth:register.email.label')}
            rules={[
              { required: true, message: t('errors:validation') },
              { type: 'email', message: t('errors:validation') },
            ]}
          >
            <Input
              type="email"
              autoComplete="email"
              placeholder={t('auth:register.email.placeholder')}
            />
          </Form.Item>

          <Form.Item
            name="password"
            label={t('auth:register.password.label')}
            rules={[
              { required: true, message: t('errors:validation') },
              { min: 8, message: t('errors:validation') },
            ]}
          >
            <Input.Password
              autoComplete="new-password"
              placeholder={t('auth:register.password.placeholder')}
            />
          </Form.Item>

          <Form.Item
            name="confirm"
            label={t('auth:register.passwordConfirm.label')}
            dependencies={['password']}
            rules={[
              { required: true, message: t('errors:validation') },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error(t('errors:validation')));
                },
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>

          <Button type="primary" htmlType="submit" block loading={submitting}>
            {t('auth:register.submit')}
          </Button>
        </Form>

        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Link to="/login">{t('auth:signIn.link')}</Link>
        </div>
      </Card>
    </div>
  );
}
