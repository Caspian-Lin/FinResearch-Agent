/**
 * 简体中文 — `watchlist` 命名空间。
 *
 * 观察列表页 UI 文案。标的代码(如 AAPL、QQQ)与货币代码(USD)保留原文,不翻译。
 */

const watchlist = {
  title: '观察列表',
  empty: '观察列表为空,请先添加一个标的。',
  addSymbol: {
    label: '标的代码',
    placeholder: '例如 AAPL',
    submit: '加入观察列表',
  },
  columns: {
    symbol: '代码',
    name: '名称',
    type: '类型',
    lastClose: '最新收盘价',
    currency: '币种',
    updatedAt: '更新时间',
  },
  /** 资产类型显示名。ETF 等标准缩写保留原文。 */
  assetType: {
    stock: '股票',
    etf: 'ETF',
    index: '指数',
  },
} as const;

export default watchlist;
