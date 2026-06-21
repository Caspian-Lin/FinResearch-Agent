import type { ThemeConfig } from 'antd';
import { theme as antdTheme } from 'antd';

export type ThemeMode = 'light' | 'dark';

export interface ChartTheme {
  text: string;
  mutedText: string;
  gridLine: string;
  axisLine: string;
  surface: string;
  tooltipBg: string;
  tooltipBorder: string;
  primary: string;
  primarySoft: string;
  quality: string;
  warning: string;
  danger: string;
  ma5: string;
  ma20: string;
  volume: string;
}

export interface ThemePalette {
  bg: string;
  shell: string;
  surface: string;
  surfaceStrong: string;
  border: string;
  borderStrong: string;
  ink: string;
  muted: string;
  subtle: string;
  primary: string;
  primaryHover: string;
  primaryActive: string;
  primarySoft: string;
  quality: string;
  qualitySoft: string;
  warning: string;
  warningSoft: string;
  danger: string;
  dangerSoft: string;
  shadow: string;
  chart: ChartTheme;
}

export interface ThemeContextValue {
  mode: ThemeMode;
  palette: ThemePalette;
  antdTheme: ThemeConfig;
  setMode: (mode: ThemeMode) => void;
  toggleMode: () => void;
}

export const THEME_STORAGE_KEY = 'fra.theme';

export const palettes: Record<ThemeMode, ThemePalette> = {
  light: {
    bg: 'oklch(1 0 0)',
    shell: 'oklch(0.985 0.003 250)',
    surface: 'oklch(0.975 0.004 250)',
    surfaceStrong: 'oklch(0.94 0.007 250)',
    border: 'oklch(0.9 0.009 250)',
    borderStrong: 'oklch(0.78 0.014 250)',
    ink: 'oklch(0.18 0.018 250)',
    muted: 'oklch(0.42 0.014 250)',
    subtle: 'oklch(0.56 0.012 250)',
    primary: 'oklch(0.58 0.16 31)',
    primaryHover: 'oklch(0.5 0.15 31)',
    primaryActive: 'oklch(0.42 0.13 31)',
    primarySoft: 'oklch(0.96 0.025 31)',
    quality: 'oklch(0.48 0.12 185)',
    qualitySoft: 'oklch(0.95 0.035 185)',
    warning: 'oklch(0.72 0.14 78)',
    warningSoft: 'oklch(0.96 0.045 78)',
    danger: 'oklch(0.58 0.17 28)',
    dangerSoft: 'oklch(0.96 0.035 28)',
    shadow: '0 6px 16px rgba(15, 23, 42, 0.12)',
    chart: {
      text: '#252833',
      mutedText: '#667085',
      gridLine: '#e7e9ef',
      axisLine: '#c9ced8',
      surface: '#ffffff',
      tooltipBg: 'rgba(255, 255, 255, 0.98)',
      tooltipBorder: '#d9dee8',
      primary: '#b85033',
      primarySoft: 'rgba(184, 80, 51, 0.16)',
      quality: '#16877d',
      warning: '#b27a00',
      danger: '#c94135',
      ma5: '#b98500',
      ma20: '#7357b8',
      volume: 'rgba(22, 135, 125, 0.34)',
    },
  },
  dark: {
    bg: 'oklch(0.12 0.012 250)',
    shell: 'oklch(0.16 0.014 250)',
    surface: 'oklch(0.2 0.016 250)',
    surfaceStrong: 'oklch(0.27 0.018 250)',
    border: 'oklch(0.33 0.018 250)',
    borderStrong: 'oklch(0.45 0.018 250)',
    ink: 'oklch(0.94 0.005 250)',
    muted: 'oklch(0.74 0.012 250)',
    subtle: 'oklch(0.62 0.012 250)',
    primary: 'oklch(0.68 0.15 31)',
    primaryHover: 'oklch(0.74 0.13 31)',
    primaryActive: 'oklch(0.58 0.16 31)',
    primarySoft: 'oklch(0.25 0.055 31)',
    quality: 'oklch(0.68 0.11 185)',
    qualitySoft: 'oklch(0.24 0.045 185)',
    warning: 'oklch(0.78 0.13 78)',
    warningSoft: 'oklch(0.25 0.05 78)',
    danger: 'oklch(0.68 0.15 28)',
    dangerSoft: 'oklch(0.25 0.055 28)',
    shadow: '0 6px 16px rgba(0, 0, 0, 0.36)',
    chart: {
      text: '#edf0f7',
      mutedText: '#aab3c2',
      gridLine: '#343b49',
      axisLine: '#566071',
      surface: '#202532',
      tooltipBg: 'rgba(32, 37, 50, 0.98)',
      tooltipBorder: '#4a5364',
      primary: '#dc7a5d',
      primarySoft: 'rgba(220, 122, 93, 0.2)',
      quality: '#65c9bd',
      warning: '#e2b84e',
      danger: '#e67868',
      ma5: '#e0b74b',
      ma20: '#b8a4ff',
      volume: 'rgba(101, 201, 189, 0.32)',
    },
  },
};

export function buildAntdTheme(mode: ThemeMode, palette: ThemePalette): ThemeConfig {
  return {
    algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: palette.primary,
      colorSuccess: palette.quality,
      colorWarning: palette.warning,
      colorError: palette.danger,
      colorInfo: palette.quality,
      colorText: palette.ink,
      colorTextSecondary: palette.muted,
      colorTextTertiary: palette.subtle,
      colorBgBase: palette.bg,
      colorBgLayout: palette.shell,
      colorBgContainer: palette.bg,
      colorBgElevated: palette.bg,
      colorBorder: palette.border,
      colorBorderSecondary: palette.surfaceStrong,
      borderRadius: 6,
      borderRadiusLG: 10,
      boxShadow: palette.shadow,
      fontFamily:
        "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
      fontSize: 14,
    },
    components: {
      Layout: {
        bodyBg: palette.shell,
        headerBg: palette.bg,
        footerBg: palette.shell,
      },
      // Pin the primary button to our palette so darkAlgorithm's derivation
      // can't desaturate it into an unreadable dark-on-dark slab (the login
      // submit was rendering near-black in dark mode without this override).
      Button: {
        colorPrimary: palette.primary,
        colorPrimaryHover: palette.primaryHover,
        colorPrimaryActive: palette.primaryActive,
        primaryShadow: 'none',
        defaultShadow: 'none',
        fontWeight: 500,
      },
      Menu: {
        itemSelectedColor: palette.primary,
        itemSelectedBg: palette.primarySoft,
        itemHoverColor: palette.primary,
        darkItemSelectedBg: palette.primarySoft,
      },
      Card: {
        colorBgContainer: palette.bg,
        colorBorderSecondary: palette.border,
      },
      Table: {
        headerBg: palette.surface,
        headerSortActiveBg: palette.surface,
        headerSortHoverBg: palette.surface,
        // Body cells of the active-sort column. Without this the algorithm
        // derives it from colorBgBase (oklch) into a near-black fill, so the
        // sorted date column rendered black-on-black in light mode.
        bodySortBg: palette.surface,
        rowHoverBg: palette.surface,
        borderColor: palette.border,
      },
      Segmented: {
        itemSelectedBg: palette.bg,
        itemSelectedColor: palette.primary,
      },
      Alert: {
        colorInfo: palette.quality,
        colorInfoBg: palette.qualitySoft,
        // success was unset → the algorithm derived a dark bg from colorSuccess
        // (oklch), so the "data synced" success Alert rendered dark grey in
        // light mode. Mirror the info/warning/error pattern explicitly.
        colorSuccess: palette.quality,
        colorSuccessBg: palette.qualitySoft,
        colorWarning: palette.warning,
        colorWarningBg: palette.warningSoft,
        colorError: palette.danger,
        colorErrorBg: palette.dangerSoft,
      },
      Select: {
        // Without these the algorithm derives option Active/Selected fills from
        // colorPrimary (oklch) into dark greys; the benchmark dropdown's option
        // panel then rendered dark grey in light mode.
        optionSelectedBg: palette.primarySoft,
        optionSelectedColor: palette.primary,
        optionSelectedFontWeight: 600,
        optionActiveBg: palette.surface,
      },
    },
  };
}

export const fallbackTheme: ThemeContextValue = {
  mode: 'light',
  palette: palettes.light,
  antdTheme: buildAntdTheme('light', palettes.light),
  setMode: () => undefined,
  toggleMode: () => undefined,
};
