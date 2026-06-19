/**
 * Global language switcher.
 *
 * Uses the custom `ToggleSelect` (FRA-45) so it shares one look with every other
 * toggle in the app, instead of an antd `Select` with a wall of token overrides
 * (the old `.language-switcher` rules). Switching is instant (no page reload):
 * `useLanguage().changeLanguage` updates i18next, which re-renders every
 * `useTranslation()` consumer.
 */
import { useTranslation } from 'react-i18next';

import { ToggleSelect } from '@/components/ui/ToggleSelect';
import { useLanguage } from '@/i18n/useLanguage';
import { isSupportedLanguage } from '@/i18n/config';

const OPTIONS = [
  { value: 'en', label: 'English' },
  { value: 'zh-CN', label: '简体中文' },
];

export function LanguageSwitcher() {
  const { language, changeLanguage } = useLanguage();
  const { t } = useTranslation();

  return (
    <ToggleSelect
      options={OPTIONS}
      value={language}
      onChange={(next) => {
        if (isSupportedLanguage(next)) void changeLanguage(next);
      }}
      ariaLabel={t('common:language.label')}
      size="small"
      width={140}
    />
  );
}

export default LanguageSwitcher;
