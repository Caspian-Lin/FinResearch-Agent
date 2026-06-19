import { Segmented } from 'antd';
import { useTranslation } from 'react-i18next';

import { useResearchTheme, type ThemeMode } from '@/theme';

export function ThemeModeSwitch() {
  const { t } = useTranslation();
  const { mode, setMode } = useResearchTheme();

  return (
    <Segmented<ThemeMode>
      aria-label={t('common:theme.label')}
      size="small"
      value={mode}
      onChange={setMode}
      options={[
        { value: 'light', label: t('common:theme.light') },
        { value: 'dark', label: t('common:theme.dark') },
      ]}
    />
  );
}

export default ThemeModeSwitch;
