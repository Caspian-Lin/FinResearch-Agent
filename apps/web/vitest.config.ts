/// <reference types="vitest" />
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// Separate vitest config so the production `vite build` is untouched.
// - jsdom env gives us `document`, `window.localStorage`, `navigator`.
// - globals so test files can use `describe/it/expect` without imports.
// - `setupFiles` registers jest-dom matchers (`toBeInTheDocument`, …).
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
    },
  },
});
