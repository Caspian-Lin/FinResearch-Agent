/**
 * 简体中文 — `dashboard` 命名空间。
 *
 * 仪表盘 / 概览页文案。数值在运行时通过 Intl / 本地化辅助函数格式化,
 * 不在此处内联。金融缩写(OHLCV、ETF、Sharpe、NASDAQ)与数据源代码
 * (yfinance)保留原文。
 */

const dashboard = {
  welcome: {
    title: '欢迎使用 FinResearch Agent',
    intro:
      '当前为脚手架外壳。真正的仪表盘页面(观察列表、OHLCV 浏览器、数据质量、回测、研报)将按 Week 1 路线图在后续提交中补齐。',
  },
  scaffolding: {
    tag: 'Week 1 脚手架',
    backendApi: '后端 API',
    apiDocs: 'API 文档(OpenAPI)',
    healthProbe: '健康探针',
  },
  metrics: {
    sectionTitle: '关键指标',
    annualReturn: '年化收益',
    volatility: '波动率',
    sharpeRatio: 'Sharpe 比率',
    maxDrawdown: '最大回撤',
    benchmark: '基准',
  },
  dataWindow: {
    label: '数据窗口',
    /** 插值:{{start}}、{{end}} */
    range: '{{start}} → {{end}}',
  },

  page: {
    title: '仪表盘',
  },

  noSelection: {
    message: '请从自选股中选择一个资产以查看其仪表盘。',
    link: '前往自选股',
  },

  /** 仪表盘侧栏(FRA-45)—— 不离开页面直接选股。 */
  sidebar: {
    title: '自选股',
    /** 窄屏打开侧栏抽屉的按钮。 */
    toggle: '选择股票',
    /** 切换自选股列表的选择器无障碍标签与占位符。 */
    switch: '切换自选股列表',
    empty: {
      assets: '该自选股列表暂无股票。',
    },
    manage: '管理自选股列表',
  },

  filters: {
    source: '数据源',
    dateRange: '日期范围',
    chartType: '图表类型',
  },

  priceChart: {
    title: '价格',
    field: {
      adjustedClose: '复权收盘价',
      close: '收盘价',
    },
    /** 图表下方说明复权价缺失时回退到收盘价。 */
    fallbackNote: '使用复权收盘价,缺失时回退到收盘价。',
    noData: '所选区间无价格数据。',
    chartType: {
      line: '折线',
      candle: 'K线',
      area: '面积',
    },
    volume: {
      label: '成交量',
    },
    ma: {
      label: '均线',
      ma5: 'MA5',
      ma20: 'MA20',
    },
    adjust: {
      label: '复权',
      adjusted: '前复权',
      raw: '不复权',
    },
    size: {
      label: '高度',
      small: '小',
      medium: '中',
      large: '大',
    },
  },

  quality: {
    title: '数据质量',
    coverage: '覆盖率',
    expected: '预期交易日数',
    observed: '已观测交易日数',
    missing: {
      title: '缺失交易日',
      /** 插值:{{count}} —— 被折叠隐藏的数量。 */
      more: '另外 {{count}} 个',
    },
    anomalies: {
      title: '异常记录',
      /** 插值:{{count}}。 */
      count: '检测到 {{count}} 条',
      empty: '未检测到异常。',
    },
    rules: {
      non_positive_price: '非正价格',
      high_lt_low: '最高价低于最低价',
      negative_volume: '负成交量',
      zero_volume: '零成交量',
      large_return: '异常大幅变动',
    },
  },

  sync: {
    button: '同步数据',
    status: {
      pending: '排队中…',
      running: '同步中…',
      success: '同步完成,正在刷新数据…',
      failed: '同步失败。',
    },
    /** 轮询达到上限仍未终结时显示。 */
    timeout: '同步耗时较长,请稍后查看。',
    limit: {
      /** 选定窗口超过后端 1825 天上限时显示。 */
      window: '所选区间超过 1825 天的同步上限。',
    },
  },

  /**
   * 数据局限说明。依据 AGENTS.md 财务安全要求,必须在两种语言下完整、
   * 如实呈现;不构成投资建议。
   */
  dataLimit: {
    title: '数据局限说明',
    body: '行情数据来自 yfinance,可能存在延迟或不完整。质量统计依据各交易所公布的交易日历计算,仅作为数据健康参考,覆盖率与异常指标仅供示意,不保证穷尽。本内容不构成投资建议。',
  },

  loading: '加载中…',
} as const;

export default dashboard;
