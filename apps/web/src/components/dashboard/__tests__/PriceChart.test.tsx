/**
 * PriceChart component tests (FRA-11).
 *
 * `echarts-for-react` is mocked to a stub div so we never touch canvas/jsdom
 * chart rendering; we assert on the forwarded `option` and the surrounding
 * loading / error / empty / language states.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';

import { PriceChart } from '@/components/dashboard/PriceChart';
import i18n from '@/i18n';
import type { OhlcvRead } from '@/types/api';

// Stub echarts-for-react: surface the option for assertions, render a marker.
vi.mock('echarts-for-react', () => ({
  default: (props: { option: unknown }) => (
    <div data-testid="echarts" data-option={JSON.stringify(props.option)} />
  ),
}));

beforeEach(async () => {
  await i18n.changeLanguage('en');
});

function makeBar(overrides: Partial<OhlcvRead> = {}): OhlcvRead {
  return {
    asset_id: 'a-1',
    time: '2024-01-02T00:00:00Z',
    source: 'yfinance',
    open: 10,
    high: 11,
    low: 9,
    close: 10,
    adjusted_close: 10,
    volume: 1000,
    ...overrides,
  };
}

describe('PriceChart', () => {
  it('shows a Spin while loading and renders no chart', () => {
    render(<PriceChart bars={[]} loading errorCode={null} />);
    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByTestId('echarts')).toBeNull();
  });

  it('shows the translated error code and never the backend detail', () => {
    // errorCode drives the message; no raw detail is ever passed in.
    render(<PriceChart bars={[makeBar()]} loading={false} errorCode="notFound" />);
    expect(screen.getByText('The requested resource was not found.')).toBeInTheDocument();
    // No chart while errored.
    expect(screen.queryByTestId('echarts')).toBeNull();
  });

  it('shows the empty state when bars is empty (no error, not loading)', () => {
    render(<PriceChart bars={[]} loading={false} errorCode={null} />);
    expect(screen.getByText('No price data for the selected window.')).toBeInTheDocument();
    expect(screen.queryByTestId('echarts')).toBeNull();
  });

  it('renders the chart + fallback note when bars are present', () => {
    render(<PriceChart bars={[makeBar()]} loading={false} errorCode={null} />);
    expect(screen.getByTestId('echarts')).toBeInTheDocument();
    expect(
      screen.getByText('Adjusted close, falling back to close when missing.'),
    ).toBeInTheDocument();
  });

  it('forwards the built option to echarts-for-react', () => {
    render(<PriceChart bars={[makeBar()]} loading={false} errorCode={null} />);
    const el = screen.getByTestId('echarts');
    const option = JSON.parse(el.getAttribute('data-option') ?? '{}') as {
      legend: { data: string[] };
    };
    expect(option.legend.data).toEqual(['Adjusted close']);
  });

  it('switches language: fallback note + legend become zh-CN after changeLanguage', async () => {
    render(<PriceChart bars={[makeBar()]} loading={false} errorCode={null} />);
    expect(
      screen.getByText('Adjusted close, falling back to close when missing.'),
    ).toBeInTheDocument();

    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });

    expect(
      screen.getByText('使用复权收盘价,缺失时回退到收盘价。'),
    ).toBeInTheDocument();
    // The remounted chart's option now uses the translated legend name.
    const el = screen.getByTestId('echarts');
    const option = JSON.parse(el.getAttribute('data-option') ?? '{}') as {
      legend: { data: string[] };
    };
    expect(option.legend.data).toEqual(['复权收盘价']);
  });
});
