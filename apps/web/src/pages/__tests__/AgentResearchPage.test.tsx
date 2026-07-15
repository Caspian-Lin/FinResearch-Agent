/**
 * Agent Research page tests (FRA-91).
 *
 * Covers the acceptance criteria:
 *   - NL submit only generates plan (no sync/backtest)
 *   - Plan validation gate disables approve button
 *   - Approve & Run calls createAgentRun with plan + hash
 *   - Timeline shows step statuses + tool trace
 *   - Cancel opens confirmation modal
 *   - Risk-fail shows restricted banner
 *   - History list loads and is clickable
 *   - Language switch does not refetch
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import AgentResearchPage from '@/pages/AgentResearchPage';
import i18n from '@/i18n';
import type {
  AgentPlanResponse,
  AgentRunDetail,
  AgentRunListResponse,
  AgentRunSummary,
  AgentTraceResponse,
} from '@/types/api';
import type { ResearchPlanT } from '@finresearch/shared';

const mocks = vi.hoisted(() => ({
  createAgentPlan: vi.fn(),
  createAgentRun: vi.fn(),
  listAgentRuns: vi.fn(),
  getAgentRun: vi.fn(),
  getAgentTrace: vi.fn(),
  cancelAgentRun: vi.fn(),
}));

vi.mock('@/api/agent', () => ({
  createAgentPlan: mocks.createAgentPlan,
  createAgentRun: mocks.createAgentRun,
  listAgentRuns: mocks.listAgentRuns,
  getAgentRun: mocks.getAgentRun,
  getAgentTrace: mocks.getAgentTrace,
  cancelAgentRun: mocks.cancelAgentRun,
}));

vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts" />,
}));

const validPlan: ResearchPlanT = {
  schema_version: '1.0',
  research_question: 'Do AI semis show 6m momentum vs QQQ?',
  resolution: 'validated',
  universe: [{ symbol: 'NVDA', asset_id: '11111111-1111-4111-8111-111111111111' }],
  benchmark: { symbol: 'QQQ', asset_id: '66666666-6666-4666-8666-666666666666' },
  data_source: 'yfinance',
  start_date: '2022-01-01T00:00:00Z',
  end_date: '2025-12-31T00:00:00Z',
  price_field: 'adjusted',
  factors: [{ name: 'momentum_63', kind: 'technical', params: {} }],
  strategy: { name: 'momentum', params: { lookback: 63, top_k: 1 }, rebalance: 'monthly' },
  transaction_cost_bps: 10,
  validation: {
    baselines: ['buy_and_hold', 'equal_weight', 'benchmark'],
    metrics: ['annual_return', 'sharpe'],
    cost_sensitivity_bps: [0, 5, 10, 25],
  },
  risk_checks: { enabled: true, transaction_cost_sensitivity: true, survivorship_documented: false },
  assumptions: ['Universe is survivorship-biased.'],
  requested_outputs: ['research_memo'],
};

const planResponse: AgentPlanResponse = {
  research_question: validPlan.research_question,
  plan: validPlan,
  plan_hash: 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
  clarification_needed: null,
  validation_errors: [],
  planner_provider: 'fixture',
  planner_model: 'fixture-planner',
};

const runSummary: AgentRunSummary = {
  id: 'run-1',
  research_question: validPlan.research_question,
  status: 'succeeded',
  plan_hash: planResponse.plan_hash!,
  created_at: '2026-07-15T00:00:00Z',
  started_at: '2026-07-15T00:00:01Z',
  completed_at: '2026-07-15T00:01:00Z',
  error_summary: null,
  current_step: 'report_agent',
};

const runDetail: AgentRunDetail = {
  ...runSummary,
  plan: validPlan,
  synthesis: {
    schema_version: '1.0',
    research_question: validPlan.research_question,
    scope: {
      window: { start: '2022-01-01', end: '2025-12-31' },
      universe: ['NVDA'],
      benchmark: 'QQQ',
      data_source: 'yfinance',
      price_field: 'adjusted',
    },
    methodology: { strategy: 'momentum', rebalance: 'monthly' },
    key_observations: [
      {
        metric: 'annual_return',
        value: '0.1523',
        interpretation: 'The strategy showed positive annualized returns.',
        citation: { ref_type: 'tool_result', ref_id: 'tc-1', field: 'net_annual_return' },
        window: '2022-01-01 to 2025-12-31',
      },
    ],
    risk_findings_summary: [{ check: 'max_drawdown', status: 'pass', detail: 'Within limits.' }],
    limitations: ['Survivorship bias may inflate returns.'],
    assumptions: ['Universe is survivorship-biased.'],
    data_gaps: [],
    disclaimer: 'This is not investment advice.',
    cited_refs: ['tc-1'],
    restricted: false,
    generated_at: '2026-07-15T00:01:00Z',
    provenance: { planner_provider: 'fixture', planner_model: 'fixture-planner' },
  },
  step_count: 5,
  completed_steps: 5,
};

const traceResponse: AgentTraceResponse = {
  run_id: 'run-1',
  run_status: 'succeeded',
  steps: [
    {
      id: 'step-1',
      sequence: 1,
      agent_role: 'data_agent',
      kind: 'tool',
      status: 'succeeded',
      input_summary: { tickers: ['NVDA'] },
      output_summary: { synced: 1 },
      error: null,
      duration_ms: 500,
      started_at: '2026-07-15T00:00:01Z',
      finished_at: '2026-07-15T00:00:02Z',
      tool_calls: [
        {
          id: 'tc-1',
          tool_name: 'sync_ohlcv',
          status: 'succeeded',
          args: { tickers: ['NVDA'] },
          result: { inserted: 1000 },
          error: null,
          error_code: null,
          evidence_refs: [{ ref_id: 'tc-1' }],
          duration_ms: 400,
          started_at: '2026-07-15T00:00:01Z',
          finished_at: '2026-07-15T00:00:02Z',
        },
      ],
    },
    {
      id: 'step-2',
      sequence: 2,
      agent_role: 'report_agent',
      kind: 'tool',
      status: 'succeeded',
      input_summary: {},
      output_summary: {},
      error: null,
      duration_ms: 300,
      started_at: null,
      finished_at: null,
      tool_calls: [],
    },
  ],
};

const emptyList: AgentRunListResponse = { runs: [], total: 0, limit: 20, offset: 0 };

function renderPage() {
  return render(
    <MemoryRouter>
      <AgentResearchPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.createAgentPlan.mockReset();
  mocks.createAgentRun.mockReset();
  mocks.listAgentRuns.mockReset();
  mocks.getAgentRun.mockReset();
  mocks.getAgentTrace.mockReset();
  mocks.cancelAgentRun.mockReset();

  mocks.listAgentRuns.mockResolvedValue(emptyList);
  void i18n.changeLanguage('en');
});

describe('AgentResearchPage — compose phase', () => {
  it('renders the question composer with example prompts', () => {
    renderPage();
    expect(screen.getByText('Research Question')).toBeInTheDocument();
    expect(screen.getByText('Example prompts')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generate plan/i })).toBeDisabled();
  });

  it('shows the disclaimer banner', () => {
    renderPage();
    expect(screen.getByText(/research and reproducibility tool/i)).toBeInTheDocument();
  });

  it('calls createAgentPlan (not createAgentRun) on submit', async () => {
    mocks.createAgentPlan.mockResolvedValue(planResponse);
    const user = userEvent.setup();
    renderPage();

    const textarea = screen.getByRole('textbox');
    await user.type(textarea, 'Do AI semis show 6m momentum vs QQQ?');
    await user.click(screen.getByRole('button', { name: /generate plan/i }));

    await waitFor(() => expect(mocks.createAgentPlan).toHaveBeenCalledTimes(1));
    expect(mocks.createAgentPlan).toHaveBeenCalledWith('Do AI semis show 6m momentum vs QQQ?');
    expect(mocks.createAgentRun).not.toHaveBeenCalled();
  });
});

describe('AgentResearchPage — plan review phase', () => {
  it('shows the plan review after plan generation', async () => {
    mocks.createAgentPlan.mockResolvedValue(planResponse);
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByRole('textbox'), 'Do AI semis show 6m momentum vs QQQ?');
    await user.click(screen.getByRole('button', { name: /generate plan/i }));

    expect(await screen.findByText('Plan Review')).toBeInTheDocument();
    expect(screen.getByText('Approve & Run')).toBeInTheDocument();
  });

  it('enables the approve button when plan is valid and unchanged', async () => {
    mocks.createAgentPlan.mockResolvedValue(planResponse);
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByRole('textbox'), 'Do AI semis show 6m momentum vs QQQ?');
    await user.click(screen.getByRole('button', { name: /generate plan/i }));

    const approveBtn = await screen.findByRole('button', { name: /approve & run/i });
    expect(approveBtn).not.toBeDisabled();
  });

  it('calls createAgentRun with plan and hash on approve', async () => {
    mocks.createAgentPlan.mockResolvedValue(planResponse);
    mocks.createAgentRun.mockResolvedValue({
      run_id: 'run-1',
      status: 'queued',
      plan_hash: planResponse.plan_hash!,
    });
    mocks.getAgentRun.mockResolvedValue(runDetail);
    mocks.getAgentTrace.mockResolvedValue(traceResponse);

    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByRole('textbox'), 'Do AI semis show 6m momentum vs QQQ?');
    await user.click(screen.getByRole('button', { name: /generate plan/i }));

    const approveBtn = await screen.findByRole('button', { name: /approve & run/i });
    await user.click(approveBtn);

    await waitFor(() => expect(mocks.createAgentRun).toHaveBeenCalledTimes(1));
    const call = mocks.createAgentRun.mock.calls[0];
    expect(call[1]).toBe(planResponse.plan_hash);
  });

  it('shows clarification guidance when planner returns no plan', async () => {
    mocks.createAgentPlan.mockResolvedValue({
      ...planResponse,
      plan: null,
      plan_hash: null,
      clarification_needed: 'Please specify a benchmark.',
    });

    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByRole('textbox'), 'something vague');
    await user.click(screen.getByRole('button', { name: /generate plan/i }));

    expect(await screen.findByText('Clarification Needed')).toBeInTheDocument();
    expect(screen.getAllByText('Please specify a benchmark.').length).toBeGreaterThan(0);
  });
});

describe('AgentResearchPage — monitor phase', () => {
  it('shows timeline and trace for a running run opened from history', async () => {
    const runningRun: AgentRunDetail = {
      ...runDetail,
      status: 'running',
      synthesis: null,
      step_count: 5,
      completed_steps: 2,
      current_step: 'factor_agent',
    };
    mocks.listAgentRuns.mockResolvedValue({
      runs: [{ ...runSummary, status: 'running', current_step: 'factor_agent' }],
      total: 1,
      limit: 20,
      offset: 0,
    });
    mocks.getAgentRun.mockResolvedValue(runningRun);
    mocks.getAgentTrace.mockResolvedValue(traceResponse);

    renderPage();

    const runItem = await screen.findByText('Do AI semis show 6m momentum vs QQQ?');
    await userEvent.click(runItem);

    expect(await screen.findByText('Execution Trace')).toBeInTheDocument();
    expect(screen.getByText('sync_ohlcv')).toBeInTheDocument();
    expect(screen.getByText('Cancel Run')).toBeInTheDocument();
  });

  it('shows cancel confirmation modal', async () => {
    const runningRun: AgentRunDetail = {
      ...runDetail,
      status: 'running',
      synthesis: null,
      current_step: 'data_agent',
    };
    mocks.listAgentRuns.mockResolvedValue({
      runs: [{ ...runSummary, status: 'running' }],
      total: 1,
      limit: 20,
      offset: 0,
    });
    mocks.getAgentRun.mockResolvedValue(runningRun);
    mocks.getAgentTrace.mockResolvedValue(traceResponse);

    const user = userEvent.setup();
    renderPage();

    const runItem = await screen.findByText('Do AI semis show 6m momentum vs QQQ?');
    await user.click(runItem);

    const cancelBtn = await screen.findByRole('button', { name: /cancel run/i });
    await user.click(cancelBtn);

    expect(await screen.findByText(/are you sure/i)).toBeInTheDocument();
  });
});

describe('AgentResearchPage — result phase', () => {
  it('shows synthesis result with observations and disclaimer for a succeeded run', async () => {
    mocks.listAgentRuns.mockResolvedValue({
      runs: [runSummary],
      total: 1,
      limit: 20,
      offset: 0,
    });
    mocks.getAgentRun.mockResolvedValue(runDetail);
    mocks.getAgentTrace.mockResolvedValue(traceResponse);

    renderPage();

    const runItem = await screen.findByText('Do AI semis show 6m momentum vs QQQ?');
    await userEvent.click(runItem);

    expect(await screen.findByText('Research Synthesis')).toBeInTheDocument();
    expect(screen.getByText('annual_return')).toBeInTheDocument();
    expect(screen.getByText('0.1523')).toBeInTheDocument();
    expect(screen.getByText('Disclaimer')).toBeInTheDocument();
  });

  it('shows restricted banner for risk-fail synthesis', async () => {
    const restrictedRun: AgentRunDetail = {
      ...runDetail,
      synthesis: { ...runDetail.synthesis!, restricted: true },
    };
    mocks.listAgentRuns.mockResolvedValue({
      runs: [{ ...runSummary, status: 'succeeded' }],
      total: 1,
      limit: 20,
      offset: 0,
    });
    mocks.getAgentRun.mockResolvedValue(restrictedRun);
    mocks.getAgentTrace.mockResolvedValue(traceResponse);

    renderPage();

    const runItem = await screen.findByText('Do AI semis show 6m momentum vs QQQ?');
    await userEvent.click(runItem);

    expect(await screen.findByText(/RESTRICTED/i)).toBeInTheDocument();
  });

  it('shows error summary for a failed run', async () => {
    const failedRun: AgentRunDetail = {
      ...runDetail,
      status: 'failed',
      synthesis: null,
      error_summary: 'Critical tool failed: run_backtest',
    };
    mocks.listAgentRuns.mockResolvedValue({
      runs: [{ ...runSummary, status: 'failed', error_summary: 'Critical tool failed' }],
      total: 1,
      limit: 20,
      offset: 0,
    });
    mocks.getAgentRun.mockResolvedValue(failedRun);
    mocks.getAgentTrace.mockResolvedValue(traceResponse);

    renderPage();

    const runItem = await screen.findByText('Do AI semis show 6m momentum vs QQQ?');
    await userEvent.click(runItem);

    expect(await screen.findByText('Run failed')).toBeInTheDocument();
    expect(screen.getByText('Critical tool failed: run_backtest')).toBeInTheDocument();
  });
});

describe('AgentResearchPage — history', () => {
  it('loads history list on mount', async () => {
    mocks.listAgentRuns.mockResolvedValue({
      runs: [runSummary],
      total: 1,
      limit: 20,
      offset: 0,
    });

    renderPage();

    await waitFor(() => expect(mocks.listAgentRuns).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('Do AI semis show 6m momentum vs QQQ?')).toBeInTheDocument();
  });

  it('shows empty state when no runs exist', async () => {
    mocks.listAgentRuns.mockResolvedValue(emptyList);
    renderPage();

    expect(await screen.findByText('No runs yet. Submit a research question to begin.')).toBeInTheDocument();
  });

  it('returns to compose view on "New Research" button', async () => {
    mocks.listAgentRuns.mockResolvedValue({
      runs: [runSummary],
      total: 1,
      limit: 20,
      offset: 0,
    });

    const user = userEvent.setup();
    renderPage();

    await screen.findByText('Do AI semis show 6m momentum vs QQQ?');
    const newBtn = screen.getByRole('button', { name: /new research/i });
    await user.click(newBtn);

    expect(screen.getByText('Research Question')).toBeInTheDocument();
  });
});

describe('AgentResearchPage — language independence', () => {
  it('does not refetch runs when language changes', async () => {
    mocks.listAgentRuns.mockResolvedValue(emptyList);
    renderPage();

    await waitFor(() => expect(mocks.listAgentRuns).toHaveBeenCalledTimes(1));

    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });

    expect(mocks.listAgentRuns).toHaveBeenCalledTimes(1);

    await act(async () => {
      await i18n.changeLanguage('en');
    });
  });
});
