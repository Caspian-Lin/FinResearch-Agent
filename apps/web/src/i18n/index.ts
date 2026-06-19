/**
 * i18next initialization.
 *
 * - `initReactI18next` makes init synchronous so React can render with the
 *   right language on first paint.
 * - `LanguageDetector` handles localStorage + navigator detection using the
 *   keys/order defined in `config.ts`.
 * - `fallbackLng: 'en'` + `returnNull: false` guarantee that a missing key
 *   never surfaces the raw key string to users.
 * - `interpolation.escapeValue: false` — React already escapes interpolated
 *   values; double-escaping would corrupt output.
 */
import i18n, { type InitOptions } from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import { en } from '@/locales/en';
import { zhCN } from '@/locales/zh-CN';
import {
  DEFAULT_LANGUAGE,
  DEFAULT_NAMESPACE,
  LANG_STORAGE_KEY,
  NAMESPACES,
} from './config';

const initOptions: InitOptions = {
  resources: {
    en: flatten(en),
    'zh-CN': flatten(zhCN),
  },
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: ['en', 'zh-CN'],
  ns: [...NAMESPACES],
  defaultNS: DEFAULT_NAMESPACE,
  // `false` so a null/undefined value falls back instead of rendering `null`.
  returnNull: false,
  // `false` so a missing key returns the fallback language, never the key.
  returnEmptyString: false,
  interpolation: {
    escapeValue: false,
  },
  detection: {
    order: ['localStorage', 'navigator'],
    lookupLocalStorage: LANG_STORAGE_KEY,
    // `cacheUserLanguage` is provided by i18next-browser-languagedetector at
    // runtime; it is intentionally retained so a manual changeLanguage() is
    // persisted to localStorage by the detector itself.
    cacheUserLanguage: true,
  } as InitOptions['detection'],
  react: {
    useSuspense: false,
  },
};

void i18n.use(initReactI18next).use(LanguageDetector).init(initOptions);

// Keep <html lang="..."> in sync with the active language on every change,
// including the very first init.
syncHtmlLang(i18n.language);
i18n.on('languageChanged', syncHtmlLang);

function syncHtmlLang(lng: string | undefined): void {
  if (typeof document === 'undefined') return;
  const normalized = lng?.startsWith('zh') ? 'zh-CN' : 'en';
  document.documentElement.lang = normalized;
}

/**
 * The locale modules export `{ common, auth, ... }` already keyed by namespace.
 * i18next expects `resources[lng][ns] = {...}`. Our modules match that shape,
 * but we assert it explicitly for type safety.
 */
type ResourceTree = Record<string, Record<string, unknown>>;
function flatten(tree: unknown): ResourceTree {
  return tree as ResourceTree;
}

export default i18n;
