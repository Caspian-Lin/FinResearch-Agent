/**
 * English — `auth` namespace.
 *
 * Authentication / session UI strings. Backed by stable form labels only —
 * backend error *messages* are NOT used as keys; see the `errors` namespace
 * for error-code-based translation.
 */

const auth = {
  signIn: {
    title: 'Sign in',
    email: {
      label: 'Email',
      placeholder: 'you@example.com',
    },
    password: {
      label: 'Password',
      placeholder: 'Enter your password',
    },
    submit: 'Sign in',
    /** Link from the register page back to the sign-in page. */
    link: 'Sign in',
  },
  register: {
    title: 'Create account',
    email: {
      label: 'Email',
      placeholder: 'you@example.com',
    },
    password: {
      label: 'Password',
      placeholder: 'At least 8 characters',
    },
    passwordConfirm: {
      label: 'Confirm password',
    },
    submit: 'Register',
    /** Link from the sign-in page to the register page. */
    link: 'Create account',
    /** Toast shown after a successful registration, before redirecting to /login. */
    success: 'Account created. Please sign in.',
  },
  /** Full-screen loading copy shown during session refresh recovery. */
  loading: 'Restoring your session…',
  signOut: 'Sign out',
  userMenu: {
    /** Dropdown menu item label. */
    signOut: 'Sign out',
  },
  session: {
    expired: 'Your session has expired. Please sign in again.',
  },
} as const;

export default auth;
