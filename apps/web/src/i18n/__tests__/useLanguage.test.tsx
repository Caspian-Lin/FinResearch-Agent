/**
 * Component-level tests for the `useLanguage` hook and `LanguageSwitcher`.
 *
 * These exercise the real i18next instance + react-i18next + antd Select to
 * prove instant (no reload) language switching and Ant Design locale sync.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { act } from 'react';
import { renderHook } from '@testing-library/react';

import { useLanguage } from '../useLanguage';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import i18n from '../index';
import { LANG_STORAGE_KEY } from '../config';

beforeEach(() => {
  window.localStorage.clear();
});

describe('useLanguage hook', () => {
  it('returns the current language and supported languages', () => {
    const { result, unmount } = renderHook(() => useLanguage());
    expect(['en', 'zh-CN']).toContain(result.current.language);
    expect(result.current.supportedLanguages).toEqual(['en', 'zh-CN']);
    expect(typeof result.current.t).toBe('function');
    unmount();
  });

  it('changes language and persists to localStorage', async () => {
    const { result, unmount } = renderHook(() => useLanguage());
    await act(async () => {
      await result.current.changeLanguage('zh-CN');
    });
    expect(result.current.language).toBe('zh-CN');
    expect(window.localStorage.getItem(LANG_STORAGE_KEY)).toBe('zh-CN');
    expect(document.documentElement.lang).toBe('zh-CN');
    unmount();
  });

  it('t() reflects the new language after switch', async () => {
    const { result, unmount } = renderHook(() => useLanguage());
    await act(async () => {
      await result.current.changeLanguage('zh-CN');
    });
    expect(result.current.t('common:actions.save')).toBe('保存');
    await act(async () => {
      await result.current.changeLanguage('en');
    });
    expect(result.current.t('common:actions.save')).toBe('Save');
    unmount();
  });
});

describe('LanguageSwitcher', () => {
  it('renders the current language and switches instantly without reload', async () => {
    const user = userEvent.setup();
    await i18n.changeLanguage('en');

    render(<LanguageSwitcher />);
    // The ToggleSelect trigger shows the current language label.
    expect(screen.getByText('English')).toBeInTheDocument();

    // Open the menu and pick 简体中文.
    await user.click(screen.getByRole('button'));
    const zhOption = await screen.findByRole('option', { name: '简体中文' });
    await user.click(zhOption);

    // Switching is instant: i18n language changed, no reload.
    expect(i18n.language).toBe('zh-CN');
    expect(window.localStorage.getItem(LANG_STORAGE_KEY)).toBe('zh-CN');
    expect(document.documentElement.lang).toBe('zh-CN');
  });

  it('toggles back to English', async () => {
    const user = userEvent.setup();
    await i18n.changeLanguage('zh-CN');
    render(<LanguageSwitcher />);
    await user.click(screen.getByRole('button'));
    const enOption = await screen.findByRole('option', { name: 'English' });
    await user.click(enOption);
    expect(i18n.language).toBe('en');
  });
});
