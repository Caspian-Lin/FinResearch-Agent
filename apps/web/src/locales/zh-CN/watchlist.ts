/**
 * 简体中文 — `watchlist` 命名空间。
 *
 * 观察列表页 UI 文案,覆盖多观察列表管理与资产搜索 / 添加 / 移除。
 * 标的代码(如 AAPL、QQQ)、交易所代码(NASDAQ)、货币代码(USD)保留原文,不翻译
 * ——它们是运行时数据,在调用处插值,绝不出现在翻译 value 中。
 */

const watchlist = {
  title: '观察列表',
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
    exchange: '交易所',
    addedAt: '加入时间',
    actions: '操作',
  },
  /** 资产类型显示名。ETF 等标准缩写保留原文。 */
  assetType: {
    stock: '股票',
    etf: 'ETF',
    index: '指数',
  },

  /** 页面级 UI。 */
  page: {
    title: '自选股',
  },
  loading: '加载中…',

  /** 空状态。 */
  empty: {
    watchlists: '您还没有自选股列表,请新建一个以开始追踪资产。',
    assets: '该自选股列表为空,请添加一个资产以开始追踪。',
  },

  /** 创建自选股 Modal 与按钮。 */
  create: {
    button: '新建自选股',
    modal: {
      title: '创建自选股',
    },
    form: {
      name: {
        label: '名称',
        placeholder: '例如:科技龙头',
      },
    },
    submit: '创建',
  },

  /** 删除自选股操作。{{name}} 为自选股名称。 */
  delete: {
    button: '删除',
    confirm: '确定删除自选股"{{name}}"吗?此操作不可撤销。',
  },

  /** 自选股切换。 */
  switch: {
    label: '自选股',
    placeholder: '请选择一个自选股',
  },

  /** 自选股页面左侧栏(FRA-45)。 */
  sidebar: {
    title: '自选股列表',
    hint: '在此切换、创建或删除自选股列表。',
  },

  /** 添加资产 Modal 与流程。 */
  addAsset: {
    button: '添加资产',
    modal: {
      title: '添加资产',
    },
    form: {
      symbol: {
        label: '标的代码',
        placeholder: '例如 AAPL',
      },
      exchange: {
        label: '交易所(可选)',
        placeholder: '例如 NASDAQ',
      },
    },
    search: {
      button: '搜索',
      noResults: '没有匹配的资产。',
      /** {{count}} 为搜索返回的结果数。 */
      resultsCount: '找到 {{count}} 个资产,请选择一个添加。',
    },
    select: {
      prompt: '请选择一个资产进行添加。',
    },
    submit: '添加',
  },

  /** 移除资产操作。 */
  remove: {
    button: '移除',
    confirm: '确定将该资产从自选股中移除吗?',
  },

  /** 跳转到(FRA-11)仪表盘。{{symbol}} 为资产代码。 */
  viewInDashboard: '在仪表盘查看',
  /** {{symbol}} 为被选中的资产代码。 */
  selectForDashboard: '已选择 {{symbol}},将在仪表盘展示。',
} as const;

export default watchlist;
