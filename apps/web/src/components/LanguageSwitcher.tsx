/**
 * Global language switcher.
 *
 * Uses an Ant Design `Select` so it composes with the rest of the antd-based
 * header. Switching is instant (no page reload): `useLanguage().changeLanguage`
 * updates i18next, which re-renders every `useTranslation()` consumer.
 */
import { Select } from 'antd';
import { useLanguage } from '@/i18n/useLanguage';
import { isSupportedLanguage, type SupportedLanguage } from '@/i18n/config';
import { useTranslation } from 'react-i18next';

interface Option {
  value: SupportedLanguage;
  label: string;
}

const OPTIONS: Option[] = [
  { value: 'en', label: 'English' },
  { value: 'zh-CN', label: '简体中文' },
];

export function LanguageSwitcher() {
  const { language, changeLanguage } = useLanguage();
  const { t } = useTranslation();

  return (
    <Select
      size="small"
      value={language}
      onChange={(next) => {
        if (isSupportedLanguage(next)) void changeLanguage(next);
      }}
      aria-label={t('common:language.label')}
      options={OPTIONS}
      style={{ width: 140 }}
    />
  );
}

export default LanguageSwitcher;
