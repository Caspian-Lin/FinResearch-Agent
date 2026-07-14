/**
 * 简体中文 — `sentiment` 命名空间 (FRA-72)。
 *
 * 新闻情绪研究页文案:配置表单(universe / 窗口 / provider / classifier)、
 * 四个研究标签页(新闻、评分、因子、对照)、异步入队轮询状态、对照结果可视化。
 *
 * 要求:与 `en/sentiment.ts` 表达一致,不夸大收益,不构成投资建议。
 * 金融标准缩写(LLM、API)与模型/classifier 名称保留原文,不翻译。
 */

const sentiment = {
  page: {
    title: '新闻情绪研究',
    description:
      '采集新闻、分类情绪、计算日频情绪因子,并对照 technical-only vs technical+sentiment 策略(仅供研究,不构成投资建议)。',
    empty: '在上方配置参数,然后在标签页上触发操作。',
  },

  form: {
    watchlist: 'Universe',
    watchlistPlaceholder: '选择一个观察列表作为 universe',
    dateRange: '日期范围',
    modelName: '模型名称',
    modelNamePlaceholder: '例如 gpt-4o-mini',
    provider: '新闻源',
    providerPlaceholder: '(默认)',
    classifier: '分类器',
    classifierPlaceholder: '(默认)',
    hint: '每个标签页有各自的操作按钮,共用上方配置。',
  },

  tabs: {
    news: '新闻',
    scores: '评分',
    factor: '因子',
    comparison: '对照',
  },

  news: {
    title: '新闻列表',
    sync: '同步新闻',
    syncAsync: '同步(异步)',
    noData: '尚无新闻 — 点击"同步新闻"获取。',
    columns: {
      publishedAt: '发布时间',
      source: '来源',
      headline: '标题',
      summary: '摘要',
    },
    result: '获取 {{fetched}} 条,新增 {{inserted}},更新 {{updated}}({{status}})。',
  },

  scores: {
    title: '情绪评分',
    classify: '分类',
    classifyAsync: '分类(异步)',
    noData: '尚无评分 — 点击"分类"对新闻进行评分。',
    columns: {
      publishedAt: '发布时间',
      asset: '资产',
      headline: '标题',
      label: '标签',
      score: '评分',
      confidence: '置信度',
      model: '模型',
    },
    result: '已分类 {{classified}}/{{news}} 条新闻(新增 {{inserted}},更新 {{updated}})。',
    label: {
      positive: '正面',
      negative: '负面',
      neutral: '中性',
    },
  },

  factor: {
    title: '日频情绪因子',
    compute: '计算因子',
    computeAsync: '计算(异步)',
    persist: '持久化因子',
    noData: '尚无因子 — 点击"计算因子"生成。',
    series: '情绪评分',
    result: '资产: {{assets}},写入行数: {{rows}}({{status}})。',
    perAsset: '资产 {{id}}',
  },

  comparison: {
    title: 'Technical-only vs technical + sentiment',
    run: '运行对照',
    runAsync: '运行对照',
    noData: '尚无对照 — 配置策略参数后点击"运行对照"。',
    params: '策略参数',
    technicalFactor: '技术因子',
    window: '窗口(天)',
    topK: 'Top K',
    modeLabel: '融合模式',
    sentimentThreshold: '情绪阈值',
    sentimentWeight: '情绪权重',
    includeSentimentOnly: '包含纯情绪策略',
    costBps: '成本 (bps)',
    initialCapital: '初始资金',
    rebalance: '调仓频率',
    mode: {
      overlay: 'Overlay',
      combined: 'Combined',
    },
    role: {
      technical_only: '纯技术',
      technical_sentiment: '技术 + 情绪',
      sentiment_only: '纯情绪',
    },
    metricsTable: {
      title: '指标对照',
      role: '策略',
      metric: '指标',
      empty: '尚无对照结果。',
    },
    equityTitle: '净值曲线',
  },

  run: {
    triggered: '已提交 — 后台计算中…',
    polling: '计算中 — 轮询状态…',
    success: '任务完成。',
    failed: '任务失败。',
    timeout: '超时 — 请稍后重试。',
  },
} as const;

export default sentiment;
