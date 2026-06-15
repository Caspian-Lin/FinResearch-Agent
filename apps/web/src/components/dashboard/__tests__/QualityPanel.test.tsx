/**
 * QualityPanel component tests (FRA-11).
 *
 * Renders the real component (antd) against fixtures; assertions cover loading,
 * error, coverage formatting, the missing-sessions truncation (+N more), the
 * anomaly list (rule translation + verbatim detail), the empty anomalies copy,
 * and language switching of rule names.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';

import { QualityPanel } from '@/components/dashboard/QualityPanel';
import i18n from '@/i18n';
import type { AnomalyPoint, QualityReport } from '@/types/api';

beforeEach(async () => {
  await i18n.changeLanguage('en');
});

function makeReport(overrides: Partial<QualityReport> = {}): QualityReport {
  return {
    asset_id: 'a-1',
    source: 'yfinance',
    start: '2024-01-01',
    end: '2024-01-31',
    expected_sessions: 22,
    observed_sessions: 20,
    missing_sessions_count: 2,
    coverage: 0.9090909,
    missing_sessions: ['2024-01-15', '2024-01-16'],
    anomalies: [],
    ...overrides,
  };
}

describe('QualityPanel', () => {
  it('shows a Spin while loading', () => {
    render(<QualityPanel report={null} loading errorCode={null} />);
    expect(screen.getByText('Loading…')).toBeInTheDocument();
  });

  it('shows the translated error code on errorCode', () => {
    render(<QualityPanel report={null} loading={false} errorCode="server" />);
    expect(
      screen.getByText('Server error. We have been notified. Please retry later.'),
    ).toBeInTheDocument();
  });

  it('formats coverage as a percentage with expected/observed counts', () => {
    const report = makeReport({ coverage: 0.875, expected_sessions: 80, observed_sessions: 70 });
    render(<QualityPanel report={report} loading={false} errorCode={null} />);
    expect(screen.getByText('87.5%')).toBeInTheDocument();
    expect(screen.getByText('80')).toBeInTheDocument();
    expect(screen.getByText('70')).toBeInTheDocument();
  });

  it('truncates missing sessions past 20 and shows "+N more"', () => {
    const missing = Array.from({ length: 25 }, (_, i) => `2024-01-${String(i + 1).padStart(2, '0')}`);
    const report = makeReport({ missing_sessions: missing, missing_sessions_count: 25 });
    render(<QualityPanel report={report} loading={false} errorCode={null} />);
    // The truncation helper collapses the tail beyond 20 → 5 more.
    expect(screen.getByText('+5 more')).toBeInTheDocument();
  });

  it('renders each anomaly rule translated with verbatim detail', () => {
    const anomalies: AnomalyPoint[] = [
      { time: '2024-01-10', rule: 'non_positive_price', detail: 'price was 0' },
      { time: '2024-01-11', rule: 'high_lt_low', detail: null },
    ];
    const report = makeReport({ anomalies });
    render(<QualityPanel report={report} loading={false} errorCode={null} />);
    expect(screen.getByText('Non-positive price')).toBeInTheDocument();
    expect(screen.getByText('price was 0')).toBeInTheDocument();
    expect(screen.getByText('High below low')).toBeInTheDocument();
  });

  it('shows the empty anomalies copy when there are none', () => {
    const report = makeReport({ anomalies: [] });
    render(<QualityPanel report={report} loading={false} errorCode={null} />);
    expect(screen.getByText('No anomalies detected.')).toBeInTheDocument();
  });

  it('switches language: rule names become zh-CN', async () => {
    const anomalies: AnomalyPoint[] = [
      { time: '2024-01-10', rule: 'negative_volume', detail: null },
    ];
    render(<QualityPanel report={makeReport({ anomalies })} loading={false} errorCode={null} />);
    expect(screen.getByText('Negative volume')).toBeInTheDocument();

    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });
    expect(screen.getByText('负成交量')).toBeInTheDocument();
    expect(screen.queryByText('Negative volume')).toBeNull();
  });
});
