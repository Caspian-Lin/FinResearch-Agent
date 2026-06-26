/**
 * 简体中文 — `factor` 命名空间(FRA-58)。
 *
 * 因子研究页面文案:配置表单(标的池/因子/窗口)、三类研究操作(IC / 分层 / 敏感性)、
 * 可视化(IC 时序+统计卡片、分层曲线+多空价差、敏感性热力图)、异步轮询状态。
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
    quantile: '分层回测',
    sensitivity: '敏感性',
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
} as const;

export default factor;
