/**
 * English — `sentiment` namespace (FRA-72).
 *
 * Sentiment research page copy: config form (universe / window / provider /
 * classifier), the four research tabs (news, scores, factor, comparison),
 * async job poll status, and comparison result visualization. Financial
 * abbreviations (LLM, API) and model/classifier names stay verbatim. Keep
 * parity with `zh-CN/sentiment.ts`; do not overstate predictive power; not
 * investment advice.
 */
const sentiment = {
  page: {
    title: 'Sentiment Research',
    description:
      'Collect news, classify sentiment, compute a daily sentiment factor, and compare technical-only vs technical+sentiment strategies (research only, not investment advice).',
    empty: 'Configure parameters above, then trigger an action on a tab.',
  },

  form: {
    watchlist: 'Universe',
    watchlistPlaceholder: 'Select a watchlist as the universe',
    dateRange: 'Date range',
    modelName: 'Model name',
    modelNamePlaceholder: 'e.g. gpt-4o-mini',
    provider: 'News provider',
    providerPlaceholder: '(default)',
    classifier: 'Classifier',
    classifierPlaceholder: '(default)',
    hint: 'Each tab has its own action button using the shared configuration above.',
  },

  tabs: {
    news: 'News',
    scores: 'Scores',
    factor: 'Factor',
    comparison: 'Comparison',
  },

  news: {
    title: 'News items',
    sync: 'Sync news',
    syncAsync: 'Sync (async)',
    noData: 'No news synced yet — click "Sync news" to fetch.',
    columns: {
      publishedAt: 'Published',
      source: 'Source',
      headline: 'Headline',
      summary: 'Summary',
    },
    result: 'Fetched {{fetched}}, inserted {{inserted}}, updated {{updated}} ({{status}}).',
  },

  scores: {
    title: 'Sentiment scores',
    classify: 'Classify',
    classifyAsync: 'Classify (async)',
    noData: 'No scores yet — click "Classify" to score the news.',
    columns: {
      publishedAt: 'Published',
      asset: 'Asset',
      headline: 'Headline',
      label: 'Label',
      score: 'Score',
      confidence: 'Confidence',
      model: 'Model',
    },
    result: 'Classified {{classified}} of {{news}} news (inserted {{inserted}}, updated {{updated}}).',
    label: {
      positive: 'Positive',
      negative: 'Negative',
      neutral: 'Neutral',
    },
  },

  factor: {
    title: 'Daily sentiment factor',
    compute: 'Compute factor',
    computeAsync: 'Compute (async)',
    persist: 'Persist factor',
    noData: 'No factor computed yet — click "Compute factor" to generate.',
    series: 'Sentiment score',
    result: 'Assets: {{assets}}, rows written: {{rows}}, ({{status}}).',
    perAsset: 'Asset {{id}}',
  },

  comparison: {
    title: 'Technical-only vs technical + sentiment',
    run: 'Run comparison',
    runAsync: 'Run comparison',
    noData: 'No comparison run yet — configure strategy params and click "Run comparison".',
    params: 'Strategy parameters',
    technicalFactor: 'Technical factor',
    window: 'Window (days)',
    topK: 'Top K',
    modeLabel: 'Fusion mode',
    sentimentThreshold: 'Sentiment threshold',
    sentimentWeight: 'Sentiment weight',
    includeSentimentOnly: 'Include sentiment-only',
    costBps: 'Cost (bps)',
    initialCapital: 'Initial capital',
    rebalance: 'Rebalance',
    mode: {
      overlay: 'Overlay',
      combined: 'Combined',
    },
    role: {
      technical_only: 'Technical only',
      technical_sentiment: 'Technical + Sentiment',
      sentiment_only: 'Sentiment only',
    },
    metricsTable: {
      title: 'Metrics comparison',
      role: 'Strategy',
      metric: 'Metric',
      empty: 'No comparison results yet.',
    },
    equityTitle: 'Equity curves',
  },

  run: {
    triggered: 'Submitted — computing in the background…',
    polling: 'Computing — polling status…',
    success: 'Task complete.',
    failed: 'Task failed.',
    timeout: 'Timed out — please retry later.',
  },
} as const;

export default sentiment;
