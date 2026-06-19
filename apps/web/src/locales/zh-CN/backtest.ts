/**
 * 简体中文 — `backtest` 命名空间(FRA-38)。
 *
 * 回测页面文案:配置表单、结果可视化(权益/回撤曲线、指标、交易明细)、轮询状态、
 * 最近回测列表。金融缩写(MA、bps)与标的/货币代码(QQQ、SPY、USD)保留原文不译。
 * 要求:与 `en/backtest.ts` 表达一致,不夸大收益,不构成投资建议。
 */
const backtest = {
  page: {
    title: '回测',
    description: '配置策略、设定时间窗口运行回测,查看权益曲线、回撤、指标与交易明细。',
    empty: '运行一次回测以查看结果。',
  },

  equity: {
    title: '权益曲线',
    strategy: '策略',
    benchmark: '基准',
    noData: '暂无权益曲线 —— 请先运行回测。',
  },

  drawdown: {
    title: '回撤',
    noData: '暂无回撤曲线 —— 请先运行回测。',
  },

  metrics: {
    title: '绩效指标',
    gross: 'Gross(费前)',
    net: 'Net(费后)',
    annual_return: '年化收益',
    volatility: '波动率',
    sharpe_ratio: '夏普',
    max_drawdown: '最大回撤',
    calmar_ratio: '卡玛',
    turnover: '换手率',
    win_rate: '胜率',
    beta: 'Beta',
    correlation: '相关系数',
  },

  trades: {
    title: '交易明细',
    empty: '无交易记录。',
    columns: {
      time: '日期',
      asset: '标的',
      side: '方向',
      quantity: '数量',
      price: '价格',
      cost: '成本',
    },
    side: { buy: '买入', sell: '卖出' },
  },

  form: {
    title: '配置',
    name: '回测名称',
    watchlist: '标的池(观察列表)',
    watchlistPlaceholder: '选择一个观察列表',
    strategy: '策略',
    dateRange: '时间范围',
    benchmark: '基准(可选)',
    benchmarkPlaceholder: '搜索 QQQ / SPY …',
    initialCapital: '初始资金',
    costBps: '交易成本(bps)',
    rebalance: '调仓频率',
    priceField: '价格字段',
    run: '运行回测',
    hint: '回测为模拟结果,不构成投资建议。',
  },

  strategy: {
    buy_hold: '买入持有',
    equal_weight: '等权',
    ma_crossover: '均线交叉',
    momentum: '动量',
    reversal: '反转',
    params: {
      fast: '快线 MA',
      slow: '慢线 MA',
      lookback: '回看周期(日)',
      topK: '做多数量',
      bottomK: '做多数量',
    },
  },

  rebalance: { daily: '每日', weekly: '每周', monthly: '每月' },
  priceField: { adjusted: '复权', raw: '原始' },

  status: {
    pending: '排队中',
    running: '运行中',
    success: '完成',
    failed: '失败',
  },

  run: {
    new: '新建回测',
    triggered: '回测已提交。',
    polling: '回测运行中…',
    success: '回测完成。',
    failed: '回测失败。',
    timeout: '回测仍在运行 —— 请稍后刷新查看结果。',
  },

  history: {
    title: '最近回测',
    empty: '暂无历史回测。',
    run: '回测',
    strategy: '策略',
    status: '状态',
    created: '创建时间',
  },

  preflight: {
    title: '缺少行情数据',
    body: '以下资产在 {{window}} 数据覆盖不足(数据源:{{source}})。现在拉取?',
    coverage: '覆盖 {{pct}}%',
    hint: '将从数据源拉取行情;完成后需重新运行回测。',
    syncButton: '拉取数据',
    syncDone: '数据已补齐,请重新运行回测。',
    syncFailed: '部分资产拉取失败。',
    syncTimeout: '拉取超时,请稍后重试。',
    enqueueFailed: '提交失败',
    rerunHint: '覆盖已更新,请再次点击「运行回测」。',
    job: {
      queued: '排队中',
      pending: '排队中…',
      running: '拉取中…',
      success: '完成',
      failed: '失败',
    },
  },
} as const;

export default backtest;
