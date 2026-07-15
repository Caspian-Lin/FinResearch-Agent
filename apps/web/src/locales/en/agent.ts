/**
 * English — `agent` namespace.
 *
 * Copy for the Agent Research UI: question composer, plan review, run
 * timeline, result view, and history sidebar. Every result section
 * emphasizes "historical research / not investment advice" per the
 * project's domain safety rules.
 *
 * Keep keys and intent in sync with `zh-CN/agent.ts`.
 */

const agent = {
  nav: {
    agentResearch: 'Agent Research',
  },

  page: {
    title: 'Agent Research',
    description:
      'Submit a natural-language investment hypothesis, review the structured plan, approve execution, and read the evidence-bound synthesis.',
  },

  disclaimer: {
    banner:
      'This is a research and reproducibility tool. Outputs are bound to a stated data window, universe, and assumptions. This is NOT investment advice.',
  },

  composer: {
    title: 'Research Question',
    placeholder:
      'e.g. "Do AI semiconductor stocks (NVDA, AMD, AVGO) show 6-month momentum vs QQQ over 2022-2025?"',
    examples: 'Example prompts',
    submit: 'Generate Plan',
    generating: 'Generating plan…',
    hint: 'Include tickers, a date range, and a benchmark for best results.',
  },

  examples: [
    'Do AI semis (NVDA, AMD, AVGO) show 6m momentum vs QQQ over 2022-2025?',
    'Is RSI-14 mean reversion profitable on SPY vs buy-and-hold 2020-2025?',
    'Does low volatility (20d) outperform high volatility in tech ETFs 2021-2025?',
  ],

  plan: {
    title: 'Plan Review',
    description: 'Review the structured research plan before execution. Edit fields marked as editable.',
    researchQuestion: 'Research Question',
    universe: 'Asset Universe',
    benchmark: 'Benchmark',
    window: 'Data Window',
    priceField: 'Price Field',
    factors: 'Factors',
    strategy: 'Strategy',
    transactionCost: 'Transaction Cost (bps)',
    validation: 'Validation',
    baselines: 'Baselines',
    metrics: 'Metrics',
    costSensitivity: 'Cost Sensitivity (bps)',
    riskChecks: 'Risk Checks',
    assumptions: 'Assumptions',
    requestedOutputs: 'Requested Outputs',
    resolution: 'Resolution',
    hash: 'Plan Hash',
    approveAndRun: 'Approve & Run',
    approved: 'Plan approved — enqueueing…',
    invalid: 'Plan has validation errors. Fix the highlighted fields before approving.',
    unresolved: 'Some assets are unresolved (no UUID). The planner will resolve them before execution.',
    edit: 'Edit',
    done: 'Done',
    regenerate: 'Regenerate Plan',
    clarification: 'Clarification Needed',
    validationErrors: 'Validation Errors',
    hashMismatch: 'Plan hash mismatch. The plan was modified after generation. Please regenerate or confirm the changes.',
  },

  run: {
    queued: 'Queued',
    running: 'Running',
    succeeded: 'Completed',
    failed: 'Failed',
    canceled: 'Canceled',
    cancel: 'Cancel Run',
    cancelConfirm: 'Are you sure you want to cancel this run? This action is irreversible.',
    cancelYes: 'Yes, cancel',
    cancelNo: 'Keep running',
    canceling: 'Canceling…',
    polling: 'Run in progress…',
    currentStep: 'Current step',
    progress: '{{done}} / {{total}} steps',
    errorSummary: 'Run failed',
    timeout: 'Run is taking longer than expected. You can keep waiting or cancel.',
  },

  steps: {
    research_planner: 'Planner',
    data_agent: 'Data',
    factor_agent: 'Factor',
    backtest_agent: 'Backtest',
    risk_agent: 'Risk',
    report_agent: 'Report',
  },

  trace: {
    title: 'Execution Trace',
    stepDuration: '{{ms}}ms',
    toolCalls: 'Tool calls',
    args: 'Arguments',
    result: 'Result',
    error: 'Error',
    evidence: 'Evidence refs',
    noTrace: 'No trace available yet.',
    expand: 'Expand',
    collapse: 'Collapse',
  },

  result: {
    title: 'Research Synthesis',
    restricted: 'RESTRICTED — This research did not pass integrity checks. No affirmative conclusions are presented.',
    scope: 'Scope',
    methodology: 'Methodology',
    keyObservations: 'Key Observations',
    riskFindings: 'Risk Findings',
    limitations: 'Limitations',
    assumptions: 'Assumptions',
    dataGaps: 'Data Gaps',
    citations: 'Citations',
    disclaimer: 'Disclaimer',
    provenance: 'Provenance',
    window: 'Window',
    universeLabel: 'Universe',
    benchmarkLabel: 'Benchmark',
    dataSource: 'Data Source',
    strategyLabel: 'Strategy',
    rebalance: 'Rebalance',
    noResult: 'No synthesis available. The run may still be in progress or has failed.',
    metric: 'Metric',
    value: 'Value',
    interpretation: 'Interpretation',
    citation: 'Citation',
    windowLabel: 'Window',
    plannerModel: 'Planner Model',
    reportModel: 'Report Model',
  },

  history: {
    title: 'Run History',
    empty: 'No runs yet. Submit a research question to begin.',
    newRun: 'New Research',
    openRun: 'Open',
  },

  errors: {
    planFailed: 'Failed to generate plan. Please rephrase your hypothesis.',
    runFailed: 'Failed to start the run. Please try again.',
    loadFailed: 'Failed to load data.',
    cancelFailed: 'Failed to cancel the run.',
    riskFail: 'Risk checks did not pass. Results are marked as restricted.',
    partialFail: 'Some tools failed during execution. Results may be incomplete.',
  },
} as const;

export default agent;
