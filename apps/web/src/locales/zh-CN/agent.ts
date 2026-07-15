/**
 * Simplified Chinese — `agent` namespace.
 *
 * 与 `en/agent.ts` 保持 key 和语义一致。金融缩写 (OHLCV, ETF, API)
 * 和股票代码 (NVDA, QQQ) 不翻译。
 */

const agent = {
  nav: {
    agentResearch: 'Agent 研究',
  },

  page: {
    title: 'Agent 研究',
    description: '提交自然语言投资假说,查看结构化研究计划,批准执行,并阅读基于证据的综合报告。',
  },

  disclaimer: {
    banner: '这是一个研究与可复现性工具。输出结果绑定到明确的数据窗口、资产范围和假设条件。本工具不提供投资建议。',
  },

  composer: {
    title: '研究问题',
    placeholder: '例如:"AI 半导体股票 (NVDA, AMD, AVGO) 在 2022-2025 相对 QQQ 是否表现出 6 个月动量?"',
    examples: '示例问题',
    submit: '生成计划',
    generating: '正在生成计划…',
    hint: '请包含股票代码、日期范围和基准以获得最佳效果。',
  },

  examples: [
    'AI 半导体 (NVDA, AMD, AVGO) 在 2022-2025 相对 QQQ 是否有 6 个月动量?',
    'RSI-14 均值回归策略在 SPY 上 2020-2025 相对买入持有是否盈利?',
    '低波动率 (20日) 在科技 ETF 中 2021-2025 是否跑赢高波动率?',
  ],

  plan: {
    title: '计划审核',
    description: '在执行前审核结构化研究计划。标记为可编辑的字段可以修改。',
    researchQuestion: '研究问题',
    universe: '资产范围',
    benchmark: '基准',
    window: '数据窗口',
    priceField: '价格字段',
    factors: '因子',
    strategy: '策略',
    transactionCost: '交易成本 (bps)',
    validation: '验证配置',
    baselines: '基准对比',
    metrics: '评估指标',
    costSensitivity: '成本敏感性 (bps)',
    riskChecks: '风险检查',
    assumptions: '假设条件',
    requestedOutputs: '请求输出',
    resolution: '计划状态',
    hash: '计划哈希',
    approveAndRun: '批准并运行',
    approved: '计划已批准 — 正在入队…',
    invalid: '计划存在验证错误。请在批准前修正高亮字段。',
    unresolved: '部分资产未解析 (无 UUID)。规划器将在执行前完成解析。',
    edit: '编辑',
    done: '完成',
    regenerate: '重新生成计划',
    clarification: '需要澄清',
    validationErrors: '验证错误',
    hashMismatch: '计划哈希不匹配。计划在生成后被修改。请重新生成或确认更改。',
  },

  run: {
    queued: '排队中',
    running: '运行中',
    succeeded: '已完成',
    failed: '失败',
    canceled: '已取消',
    cancel: '取消运行',
    cancelConfirm: '确定要取消此运行吗?此操作不可撤销。',
    cancelYes: '是,取消',
    cancelNo: '继续运行',
    canceling: '正在取消…',
    polling: '运行进行中…',
    currentStep: '当前步骤',
    progress: '{{done}} / {{total}} 步',
    errorSummary: '运行失败',
    timeout: '运行时间超出预期。您可以继续等待或取消。',
  },

  steps: {
    research_planner: '规划器',
    data_agent: '数据',
    factor_agent: '因子',
    backtest_agent: '回测',
    risk_agent: '风险',
    report_agent: '报告',
  },

  trace: {
    title: '执行轨迹',
    stepDuration: '{{ms}}ms',
    toolCalls: '工具调用',
    args: '参数',
    result: '结果',
    error: '错误',
    evidence: '证据引用',
    noTrace: '暂无执行轨迹。',
    expand: '展开',
    collapse: '收起',
  },

  result: {
    title: '研究综合报告',
    restricted: '受限 — 本研究未通过完整性检查。不展示任何肯定性结论。',
    scope: '范围',
    methodology: '方法论',
    keyObservations: '关键发现',
    riskFindings: '风险发现',
    limitations: '局限性',
    assumptions: '假设条件',
    dataGaps: '数据缺口',
    citations: '引用',
    disclaimer: '免责声明',
    provenance: '来源',
    window: '窗口',
    universeLabel: '资产范围',
    benchmarkLabel: '基准',
    dataSource: '数据源',
    strategyLabel: '策略',
    rebalance: '再平衡',
    noResult: '暂无综合报告。运行可能仍在进行中或已失败。',
    metric: '指标',
    value: '数值',
    interpretation: '解读',
    citation: '引用',
    windowLabel: '窗口',
    plannerModel: '规划器模型',
    reportModel: '报告模型',
  },

  history: {
    title: '运行历史',
    empty: '暂无运行记录。提交研究问题以开始。',
    newRun: '新建研究',
    openRun: '打开',
  },

  errors: {
    planFailed: '生成计划失败。请重新表述您的研究假说。',
    runFailed: '启动运行失败。请重试。',
    loadFailed: '加载数据失败。',
    cancelFailed: '取消运行失败。',
    riskFail: '风险检查未通过。结果标记为受限。',
    partialFail: '执行过程中部分工具失败。结果可能不完整。',
  },
} as const;

export default agent;
