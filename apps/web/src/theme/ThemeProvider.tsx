import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import { ThemeContext } from './context';
import {
  THEME_STORAGE_KEY,
  buildAntdTheme,
  palettes,
  type ThemeContextValue,
  type ThemeMode,
} from './tokens';

export function ResearchThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => readInitialTheme());
  const palette = palettes[mode];

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = mode;
    root.style.colorScheme = mode;
    window.localStorage.setItem(THEME_STORAGE_KEY, mode);
  }, [mode]);

  const config = useMemo(() => buildAntdTheme(mode, palette), [mode, palette]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      mode,
      palette,
      antdTheme: config,
      setMode: setModeState,
      toggleMode: () => setModeState((prev) => (prev === 'light' ? 'dark' : 'light')),
    }),
    [config, mode, palette],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

function readInitialTheme(): ThemeMode {
  if (typeof window === 'undefined') return 'light';
  const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (saved === 'light' || saved === 'dark') return saved;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
