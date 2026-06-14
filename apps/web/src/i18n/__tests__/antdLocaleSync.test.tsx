/**
 * Tests that Ant Design's built-in component copy follows the active language.
 *
 * Strategy: render `App` (which wraps content in `ConfigProvider` bound to the
 * i18n language) with an antd `Empty` passed as children. `Empty`'s default
 * description is locale-dependent: "No data" (en) vs "暂无数据" (zh-CN).
 * Switching language via the App's `LanguageSwitcher` updates antd locale
 * instantly (no reload).
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Empty } from 'antd';
import type { ReactNode } from 'react';

import App from '@/App';
import i18n from '../index';

beforeEach(async () => {
  window.localStorage.clear();
  await i18n.changeLanguage('en');
});

function renderApp(children?: ReactNode) {
  return render(<App>{children}</App>);
}

async function switchLanguageViaUI(user: ReturnType<typeof userEvent.setup>, label: string) {
  const selectors = document.querySelectorAll('.ant-select-selector');
  const appSelect = selectors[selectors.length - 1] as HTMLElement;
  await act(async () => {
    await user.click(appSelect);
  });
  const dropdown = document.querySelector('.ant-select-dropdown') as HTMLElement;
  await act(async () => {
    await user.click(await within(dropdown).findByText(label));
  });
}

describe('Ant Design locale sync', () => {
  it('App renders translated application strings in zh-CN', async () => {
    await i18n.changeLanguage('zh-CN');
    renderApp();
    expect(screen.getByText(/欢迎使用/)).toBeInTheDocument();
    // The English scaffold tag is translated, so the English label is gone.
    expect(screen.queryByText('Week 1 scaffold')).toBeNull();
  });

  it('antd Empty default description follows the i18n language (no reload)', async () => {
    const user = userEvent.setup();
    const { container, unmount } = renderApp(<Empty />);

    // English: antd Empty says "No data".
    expect(container.textContent).toContain('No data');

    // Switch language via the App's LanguageSwitcher.
    await switchLanguageViaUI(user, '简体中文');

    // antd Empty copy should now be Simplified Chinese.
    expect(container.textContent).toContain('暂无数据');
    expect(i18n.language).toBe('zh-CN');

    unmount();
  });

  it('switching back to English restores antd English copy', async () => {
    const user = userEvent.setup();
    const { container, unmount } = renderApp(<Empty />);

    await switchLanguageViaUI(user, '简体中文');
    expect(container.textContent).toContain('暂无数据');

    await switchLanguageViaUI(user, 'English');
    expect(container.textContent).toContain('No data');
    expect(i18n.language).toBe('en');

    unmount();
  });
});
