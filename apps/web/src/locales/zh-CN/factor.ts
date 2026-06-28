/**
 * 简体中文 — `factor` 命名空间(FRA-58)。
 *
 * 因子研究页面文案:配置表单(标的池/因子/窗口)、三类研究操作(IC / 分层 / 敏感性)、
 * 可视化(IC 时序+统计卡片、分层曲线+多空价差、敏感性热力图)、异步轮询状态、
 * 一页式因子表现报告与 JSON/Markdown 导出(FRA-77)。
 * 金融缩写(IC、ICIR、t-stat、p-value、Sharpe、bps)与因子名(momentum_21、macd_hist、rsi_14)
 * 保留原文。要求:与 `en/factor.ts` 表达一致,不夸大预测能力,不构成投资建议。
 */
const factor = {
  page: {
    title: '因子研究',
    description: '选标的池与因子,评估 IC、分层收益与参数敏感性(仅供研究,非投资建议)。',
    empty: '选择标的池与因子后运行分析。',
  },

  form: {
    watchlist: '标的池',
    watchlistPlaceholder: '选择一个观察列表作为标的池',
    factor: '因子',
    dateRange: '时间窗口',
    nQuantiles: '分层数',
    source: '数据源',
    priceField: '价格字段',
    run: '运行',
    hint: '计算在后台 worker 执行(IC 为即时查询)。',
  },

  factors: {
    momentum_21: '动量 21 日',
    momentum_63: '动量 63 日',
    momentum_126: '动量 126 日',
    reversal_5: '反转 5 日',
    reversal_21: '反转 21 日',
    macd_hist: 'MACD 柱状图',
    rsi_14: 'RSI 14',
    volatility_20d: '波动率 20 日',
    volatility_63d: '波动率 63 日',
  },

  priceField: {
    adjusted: '复权',
    raw: '原始',
  },

  tabs: {
    ic: 'IC 分析',
    ranking: '排名快照',
    quantile: '分层回测',
    sensitivity: '敏感性',
    report: '报告',
  },

  actions: {
    runIC: '计算 IC',
    runQuantile: '运行分层回测',
    runSensitivity: '运行敏感性扫描',
  },

  ic: {
    title: '信息系数 (IC)',
    series: '逐期 IC',
    mean: 'IC 均值',
    icir: 'ICIR',
    tStat: 't 统计量',
    pValue: 'p 值',
    n: '期数',
    positiveRate: '正向率',
    noData: '暂无 IC 序列 —— 请先运行 IC 分析。',
    minUniverse: 'IC 分析需要至少 2 个标的(截面排序),请在标的池中选择更多资产。',
  },

  quantile: {
    title: '分层收益曲线',
    bucket: '第 {{n}} 组',
    spread: '多空价差 (Top − Bottom)',
    monotonicity: '单调性',
    noData: '暂无分层曲线 —— 请先运行分层回测。',
  },

  ranking: {
    title: '横截面排名快照',
    snapshotDate: '日期',
    latestValid: '最近有效截面',
    snapshotTime: '快照日期: {{date}}',
    noData: '该日期/窗口暂无有效横截面 —— 预热期或缺失因子值不会被填充。',
    minUniverse: '排名快照需要至少 2 个标的,请在标的池中选择更多资产。',
    columns: {
      symbol: '标的',
      value: '因子值',
      rank: '排名',
      zScore: 'Z-score',
      bucket: '分层',
    },
  },

  heatmap: {
    title: '参数敏感性热力图',
    window: '窗口',
    cost: '成本',
    noData: '暂无敏感性数据 —— 请先运行敏感性扫描。',
    metric: {
      net_sharpe: '净夏普',
      gross_sharpe: '毛夏普',
    },
  },

  run: {
    triggered: '已提交,后台计算中…',
    polling: '计算中,正在轮询状态…',
    success: '计算完成。',
    failed: '计算失败。',
    timeout: '计算超时,请稍后重试。',
  },

  sweepUnsupported: '该因子不支持敏感性扫描(仅动量/RSI/波动率)。',

  preflight: {
    title: '缺少行情数据',
    body: '以下资产在 {{window}} 数据覆盖不足(数据源:{{source}})。现在拉取?',
    coverage: '覆盖 {{pct}}%',
    hint: '将从数据源拉取行情;完成后需重新运行分析。',
    syncButton: '拉取数据',
    syncDone: '数据已补齐,请重新运行分析。',
    syncFailed: '部分资产拉取失败。',
    syncTimeout: '拉取超时,请稍后重试。',
    enqueueFailed: '提交失败',
    rerunHint: '覆盖已更新,请再次运行分析。',
    job: {
      queued: '排队中',
      pending: '排队中…',
      running: '拉取中…',
      success: '完成',
      success_no_data: '无数据',
      failed: '失败',
    },
  },

  report: {
    title: '因子表现报告',
    intro: '当前配置下的因子表现一页式总结(历史模拟,非投资建议)。',
    notRun: '未运行',
    none: '无',
    headings: {
      config: '配置与假设',
      metrics: '表现汇总',
      limitations: '局限与声明',
    },
    config: {
      factor: '因子',
      source: '数据源',
      window: '数据窗口',
      universe: '标的池规模',
      horizon: 'IC 前瞻期',
      nQuantiles: '分层数',
      priceField: '价格字段',
      costBands: '成本档位 (bps)',
    },
    metrics: {
      icSummary: 'IC 汇总',
      quantile: '分层回测',
      sensitivity: '敏感性',
      monotonicity: '单调性',
      tmbEnding: '多空价差期末值',
      bestSharpe: '最佳净夏普',
      worstSharpe: '最差净夏普',
      highImpactParams: '高敏感参数',
      noHighImpact: '无高敏感参数',
    },
    export: {
      json: '导出 JSON',
      markdown: '导出 Markdown',
    },
    limitations: {
      title: '局限与声明',
      icNotAlpha:
        'IC 衡量截面排序预测力,不含交易成本、滑点、冲击成本、容量与卖空可行性;统计显著的 IC 在扣费与考虑可投资性后可能消失。',
      shortWindow:
        '默认 demo 窗口(~1 年、小样本)下 IC 的 t-stat 与分层单调性都不稳定;在敏感性网格上挑最优参数几乎必然过拟合。',
      singleSource:
        '数据仅来自 yfinance 单一免费源,可能存在拆分调整错误、退市数据缺失与延迟;因子值与 IC 继承该源的所有偏差。',
      survivorship:
        'universe 来自用户标的池,系统未接入历史指数成分与退市证券,无法完全消除幸存者偏差;结论仅为该给定股票池在该窗口的历史模拟。',
      lookAhead:
        '系统内部因子由滚动窗口 + 预热 NaN + shift(1) 边界保证无前视;未来若接入外部/LLM 生成因子,需单独保证其特征不含未来数据。',
      disclaimer: '历史模拟,仅供研究学习,不预测未来、不构成投资建议。',
    },
  },
} as const;

export default factor;
