/**
 * i18n configuration: supported languages, default language, storage key,
 * and the pure initial-language detector.
 *
 * Priority for initial language:
 *   1. localStorage(saved choice)        — explicit user preference wins
 *   2. navigator.language prefix-match   — zh* → zh-CN
 *   3. English fallback
 *
 * The detector is exported as a pure function for unit-testing without
 * pulling in the full i18next runtime.
 */

/** Supported UI languages. Add a third language here only with full coverage. */
export const SUPPORTED_LANGUAGES = ['en', 'zh-CN'] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

/** Fallback when nothing else resolves. */
export const DEFAULT_LANGUAGE: SupportedLanguage = 'en';

/** localStorage key for the persisted language choice. */
export const LANG_STORAGE_KEY = 'fra.lang';

/** i18next resource namespaces (one per business domain). */
export const NAMESPACES = [
  'common',
  'auth',
  'watchlist',
  'dashboard',
  'errors',
] as const;
export type Namespace = (typeof NAMESPACES)[number];

/** Default namespace used by `useTranslation()` when none is given. */
export const DEFAULT_NAMESPACE: Namespace = 'common';

/**
 * Resolve a supported language from a raw locale string (e.g. navigator.language).
 * Any `zh*` variant (zh, zh-CN, zh-Hans, zh-TW, zh-HK, …) maps to `zh-CN`
 * since we only ship Simplified Chinese. Everything else falls back to `en`.
 */
export function normalizeLanguage(raw: string | undefined): SupportedLanguage {
  if (!raw) return DEFAULT_LANGUAGE;
  const lower = raw.toLowerCase();
  if (lower === 'en' || lower.startsWith('en-')) return 'en';
  if (lower === 'zh-cn' || lower.startsWith('zh')) return 'zh-CN';
  return DEFAULT_LANGUAGE;
}

/** Check whether a value is one of the supported languages. */
export function isSupportedLanguage(value: unknown): value is SupportedLanguage {
  return (
    typeof value === 'string' &&
    (SUPPORTED_LANGUAGES as readonly string[]).includes(value)
  );
}

/**
 * Read the language from a storage-like object (decoupled from `window`
 * so it is trivially testable). Returns `null` when no saved choice exists.
 */
export function readStoredLanguage(
  storage: { getItem(key: string): string | null } | undefined,
  key: string = LANG_STORAGE_KEY,
): SupportedLanguage | null {
  const raw = storage?.getItem(key);
  if (isSupportedLanguage(raw)) return raw;
  return null;
}

/**
 * Resolve the initial language by priority: saved → navigator → fallback.
 *
 * @param storage    localStorage-like (defaults to global `localStorage`)
 * @param navigator_ navigator-like (defaults to global `navigator`)
 */
export function detectInitialLanguage(
  storage: { getItem(key: string): string | null } | undefined = safeLocalStorage(),
  navigator_: { language?: string; languages?: readonly string[] } = safeNavigator(),
): SupportedLanguage {
  const saved = readStoredLanguage(storage);
  if (saved) return saved;

  // Prefer navigator.languages[0], fall back to navigator.language.
  const navLang = navigator_.languages?.[0] ?? navigator_.language;
  if (navLang) return normalizeLanguage(navLang);

  return DEFAULT_LANGUAGE;
}

/** SSR/guard-safe localStorage accessor. */
function safeLocalStorage(): { getItem(key: string): string | null } | undefined {
  if (typeof window === 'undefined') return undefined;
  return window.localStorage;
}

/** SSR/guard-safe navigator accessor. */
function safeNavigator(): { language?: string; languages?: readonly string[] } {
  if (typeof navigator === 'undefined') return {};
  return {
    language: navigator.language,
    languages: navigator.languages,
  };
}
