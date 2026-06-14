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
    username: 'Username',
    password: 'Password',
    submit: 'Sign in',
    rememberMe: 'Remember me',
  },
  signOut: 'Sign out',
  session: {
    expired: 'Your session has expired. Please sign in again.',
  },
} as const;

export default auth;
