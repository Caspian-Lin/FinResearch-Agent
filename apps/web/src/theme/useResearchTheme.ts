import { useContext } from 'react';

import { ThemeContext } from './context';
import { fallbackTheme } from './tokens';
import type { ThemeContextValue } from './tokens';

export function useResearchTheme(): ThemeContextValue {
  return useContext(ThemeContext) ?? fallbackTheme;
}
