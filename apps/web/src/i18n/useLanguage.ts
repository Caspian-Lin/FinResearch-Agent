/**
 * `useLanguage` — single hook for reading + changing the active language.
 *
 * - `language` is reactive: re-renders when i18next fires `languageChanged`.
 * - `changeLanguage(l)` writes to localStorage (via i18next detector cache),
 *   updates `<html lang>`, and triggers `i18n.changeLanguage`.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import i18n from './index';
import {
  LANG_STORAGE_KEY,
  SUPPORTED_LANGUAGES,
  isSupportedLanguage,
  type SupportedLanguage,
} from './config';

export interface UseLanguageResult {
  language: SupportedLanguage;
  /** All supported languages, for switchers. */
  supportedLanguages: readonly SupportedLanguage[];
  /** Change the active language (persisted + reactive). Resolves on i18next. */
  changeLanguage: (next: SupportedLanguage) => Promise<void>;
  /** Bound `t` from react-i18next for convenience. */
  t: TFunction;
}

export function useLanguage(): UseLanguageResult {
  const { t } = useTranslation();
  const [language, setLanguage] = useState<SupportedLanguage>(() =>
    coerce(i18n.language),
  );

  useEffect(() => {
    const handler = (lng: string) => setLanguage(coerce(lng));
    i18n.on('languageChanged', handler);
    return () => {
      i18n.off('languageChanged', handler);
    };
  }, []);

  const changeLanguage = useCallback(async (next: SupportedLanguage) => {
    if (!isSupportedLanguage(next)) return;
    // Persist explicitly (LanguageDetector caches, but be defensive for SSR/tests).
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(LANG_STORAGE_KEY, next);
    }
    // `document.documentElement.lang` is also kept in sync via the i18n init
    // listener; setting here too keeps it correct in test environments that
    // import the hook but not the full i18n init side-effect chain.
    if (typeof document !== 'undefined') {
      document.documentElement.lang = next;
    }
    await i18n.changeLanguage(next);
  }, []);

  return {
    language,
    supportedLanguages: SUPPORTED_LANGUAGES,
    changeLanguage,
    t,
  };
}

function coerce(lng: string | undefined): SupportedLanguage {
  if (isSupportedLanguage(lng)) return lng;
  return 'en';
}
