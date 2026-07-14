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
      // Mirror tsconfig `paths` so vitest resolves the workspace shared pkg to
      // its source directly — avoids depending on a built `dist` (CI does not
      // build @finresearch/shared before running web tests).
      '@finresearch/shared': path.resolve(__dirname, '../../packages/shared/src/index.ts'),
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
