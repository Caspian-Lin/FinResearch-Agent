/**
 * Tests that Ant Design's built-in component copy follows the active language.
 *
 * App is now a React Router layout route (it renders `<Outlet/>`), so we mount
 * it inside a `MemoryRouter` + `<Routes>` and feed an antd `Empty` through the
 * child route's element. `Empty`'s default description is locale-dependent:
 * "No data" (en) vs "暂无数据" (zh-CN). Switching language via the App's
 * `LanguageSwitcher` updates antd locale instantly (no reload).
 *
 * Language assertions use locale-distinct copy that only exists in one
 * language at a time: the disclaimer title (`Important Disclaimer` vs
 * `重要免责声明`) and antd's `Empty` description.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Empty } from 'antd';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import App from '@/App';
import i18n from '../index';

beforeEach(async () => {
  window.localStorage.clear();
  await i18n.changeLanguage('en');
});

/** Render App as a layout route whose child route renders `node`. */
function renderAppWith(node: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<App />}>
          <Route path="/" element={node} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

async function switchLanguageViaUI(user: ReturnType<typeof userEvent.setup>, label: string) {
  const selectors = document.querySelectorAll('.ant-select-selector');
  // The language switcher is the last Select in the header.
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
  it('App renders the zh-CN disclaimer title under zh-CN', async () => {
    await i18n.changeLanguage('zh-CN');
    renderAppWith(null);
    // Disclaimer title is locale-distinct (en: "Important Disclaimer").
    expect(screen.getByText('重要免责声明')).toBeInTheDocument();
    expect(screen.queryByText('Important Disclaimer')).toBeNull();
  });

  it('antd Empty default description follows the i18n language (no reload)', async () => {
    const user = userEvent.setup();
    const { container, unmount } = renderAppWith(<Empty />);

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
    const { container, unmount } = renderAppWith(<Empty />);

    await switchLanguageViaUI(user, '简体中文');
    expect(container.textContent).toContain('暂无数据');

    await switchLanguageViaUI(user, 'English');
    expect(container.textContent).toContain('No data');
    expect(i18n.language).toBe('en');

    unmount();
  });
});
