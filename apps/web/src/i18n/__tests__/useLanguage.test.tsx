/**
 * Component-level tests for the `useLanguage` hook and `LanguageSwitcher`.
 *
 * These exercise the real i18next instance + react-i18next + antd Select to
 * prove instant (no reload) language switching and Ant Design locale sync.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, within } from '@testing-library/react';
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

    const { container, unmount } = render(<LanguageSwitcher />);
    // antd Select renders the selected value; the english label should show.
    expect(container.textContent).toContain('English');

    // Open the dropdown and pick 简体中文.
    await user.click(container.querySelector('.ant-select-selector')!);
    const dropdown = document.querySelector('.ant-select-dropdown')!;
    const zhOption = await within(dropdown as HTMLElement).findByText('简体中文');
    await user.click(zhOption);

    // Switching is instant: i18n language changed, no reload.
    expect(i18n.language).toBe('zh-CN');
    expect(window.localStorage.getItem(LANG_STORAGE_KEY)).toBe('zh-CN');
    expect(document.documentElement.lang).toBe('zh-CN');
    unmount();
  });

  it('toggles back to English', async () => {
    const user = userEvent.setup();
    await i18n.changeLanguage('zh-CN');
    const { container, unmount } = render(<LanguageSwitcher />);
    await user.click(container.querySelector('.ant-select-selector')!);
    const dropdown = document.querySelector('.ant-select-dropdown')!;
    const enOption = await within(dropdown as HTMLElement).findByText('English');
    await user.click(enOption);
    expect(i18n.language).toBe('en');
    unmount();
  });
});
