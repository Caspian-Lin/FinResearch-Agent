/**
 * 简体中文 — `dashboard` 命名空间。
 *
 * 仪表盘 / 概览页文案。数值在运行时通过 Intl / 本地化辅助函数格式化,
 * 不在此处内联。金融缩写(OHLCV、ETF、Sharpe、NASDAQ)保留原文。
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
} as const;

export default dashboard;
