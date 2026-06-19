/**
 * 简体中文 — `common` 命名空间。
 *
 * 通用 UI 文案(应用名、导航、操作、通用状态、全项目风险免责声明)。
 *
 * 要求:与 `en/common.ts` 表达一致,不夸大收益,不构成投资建议。
 * 金融标准缩写(OHLCV、ETF、API、NASDAQ 等)与货币/标的代码(USD、QQQ、SPY)保留原文,不翻译。
 */

const common = {
  appName: 'FinResearch Agent',
  version: 'v0.1.0',
  tagline: 'LLM 驱动的金融研究与回测系统',

  nav: {
    dashboard: '仪表盘',
    watchlist: '观察列表',
    backtests: '回测',
    memos: '研报备忘',
    settings: '设置',
  },

  actions: {
    save: '保存',
    cancel: '取消',
    confirm: '确认',
    delete: '删除',
    edit: '编辑',
    add: '添加',
    refresh: '刷新',
    close: '关闭',
    retry: '重试',
    loading: '加载中…',
  },

  status: {
    online: '在线',
    offline: '离线',
    pending: '待处理',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
  },

  language: {
    label: '语言',
    english: 'English',
    chineseSimplified: '简体中文',
  },

  /** 全项目风险免责声明,两种语言下必须完整呈现且语义一致。 */
  disclaimer: {
    title: '重要免责声明',
    body: 'FinResearch Agent 是研究与可复现性工具。它不是自动化交易机器人,不接入券商,也不承诺盈利。任何输出均绑定于明确的数据窗口、资产范围与假设条件。本工具的内容不构成投资建议。',
  },
} as const;

export default common;
