/**
 * Tests for the pure language-detection helpers in `i18n/config.ts`.
 * These do NOT depend on the i18next runtime — they validate priority
 * resolution: saved choice → navigator → fallback.
 */
import { describe, it, expect } from 'vitest';
import {
  DEFAULT_LANGUAGE,
  LANG_STORAGE_KEY,
  SUPPORTED_LANGUAGES,
  detectInitialLanguage,
  isSupportedLanguage,
  normalizeLanguage,
  readStoredLanguage,
} from '../config';

function makeStorage(map: Record<string, string> = {}) {
  return {
    getItem: (key: string) => (key in map ? map[key] ?? null : null),
  };
}

describe('SUPPORTED_LANGUAGES / DEFAULT_LANGUAGE', () => {
  it('supports exactly en and zh-CN', () => {
    expect([...SUPPORTED_LANGUAGES]).toEqual(['en', 'zh-CN']);
  });

  it('defaults to English', () => {
    expect(DEFAULT_LANGUAGE).toBe('en');
  });
});

describe('normalizeLanguage', () => {
  it('maps en variants to en', () => {
    expect(normalizeLanguage('en')).toBe('en');
    expect(normalizeLanguage('en-US')).toBe('en');
    expect(normalizeLanguage('EN-GB')).toBe('en');
  });

  it('maps all zh variants to zh-CN (only Simplified is shipped)', () => {
    expect(normalizeLanguage('zh')).toBe('zh-CN');
    expect(normalizeLanguage('zh-CN')).toBe('zh-CN');
    expect(normalizeLanguage('zh-Hans')).toBe('zh-CN');
    expect(normalizeLanguage('zh-TW')).toBe('zh-CN');
    expect(normalizeLanguage('zh-HK')).toBe('zh-CN');
  });

  it('falls back to en for unsupported locales', () => {
    expect(normalizeLanguage('fr')).toBe('en');
    expect(normalizeLanguage('ja-JP')).toBe('en');
    expect(normalizeLanguage(undefined)).toBe('en');
    expect(normalizeLanguage('')).toBe('en');
  });
});

describe('isSupportedLanguage', () => {
  it('accepts the two supported codes', () => {
    expect(isSupportedLanguage('en')).toBe(true);
    expect(isSupportedLanguage('zh-CN')).toBe(true);
  });

  it('rejects unsupported or malformed values', () => {
    expect(isSupportedLanguage('zh')).toBe(false);
    expect(isSupportedLanguage('zh-TW')).toBe(false);
    expect(isSupportedLanguage('fr')).toBe(false);
    expect(isSupportedLanguage(null)).toBe(false);
    expect(isSupportedLanguage(123)).toBe(false);
  });
});

describe('readStoredLanguage', () => {
  it('returns the saved value when valid', () => {
    const storage = makeStorage({ [LANG_STORAGE_KEY]: 'zh-CN' });
    expect(readStoredLanguage(storage)).toBe('zh-CN');
  });

  it('returns null when the saved value is invalid', () => {
    const storage = makeStorage({ [LANG_STORAGE_KEY]: 'zh-TW' });
    expect(readStoredLanguage(storage)).toBeNull();
  });

  it('returns null when nothing is stored', () => {
    expect(readStoredLanguage(makeStorage())).toBeNull();
    expect(readStoredLanguage(undefined)).toBeNull();
  });
});

describe('detectInitialLanguage priority', () => {
  it('prefers a saved choice over navigator language', () => {
    const storage = makeStorage({ [LANG_STORAGE_KEY]: 'zh-CN' });
    expect(detectInitialLanguage(storage, { language: 'en-US' })).toBe('zh-CN');
  });

  it('uses navigator language when nothing is saved (zh variant)', () => {
    expect(detectInitialLanguage(makeStorage(), { language: 'zh-CN' })).toBe('zh-CN');
    expect(detectInitialLanguage(makeStorage(), { language: 'zh' })).toBe('zh-CN');
  });

  it('uses navigator language when nothing is saved (en variant)', () => {
    expect(detectInitialLanguage(makeStorage(), { language: 'en-GB' })).toBe('en');
  });

  it('prefers navigator.languages[0] over navigator.language', () => {
    expect(
      detectInitialLanguage(makeStorage(), {
        language: 'en',
        languages: ['zh-CN', 'en'],
      }),
    ).toBe('zh-CN');
  });

  it('falls back to English when nothing resolves', () => {
    expect(detectInitialLanguage(makeStorage(), {})).toBe('en');
  });

  it('falls back to English when navigator locale is unsupported', () => {
    expect(detectInitialLanguage(makeStorage(), { language: 'fr-FR' })).toBe('en');
  });
});
