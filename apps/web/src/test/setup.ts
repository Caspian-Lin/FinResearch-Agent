/**
 * Vitest global setup: register jest-dom DOM matchers and ensure a clean
 * localStorage / language state between tests.
 */
import '@testing-library/jest-dom/vitest';
import { afterEach, beforeEach, vi } from 'vitest';
import i18n from '@/i18n';

// Tell React this is an act() environment so @testing-library warnings about
// unwrapped state updates are silenced and act() works correctly.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(async () => {
  // Reset language + clear detector cache so tests don't leak into each other.
  window.localStorage.clear();
  await i18n.changeLanguage('en');
});

// jsdom does not implement `matchMedia` which antd touches on import.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});
