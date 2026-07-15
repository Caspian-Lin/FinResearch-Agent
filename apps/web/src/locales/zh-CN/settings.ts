const settings = {
  nav: {
    settings: '设置',
  },
  llm: {
    title: 'LLM 配置',
    description: '在此配置您的 LLM 提供商凭据。这些设置将全局应用于 Agent 研究和情绪分析。',
    provider: '提供商',
    providerFixture: 'Fixture（离线模式，无需 API Key）',
    providerOpenai: 'OpenAI 兼容',
    apiKey: 'API Key',
    apiKeyPlaceholder: '输入您的 API Key（例如 sk-...）',
    apiKeyHint: '留空则保持现有 Key 不变。Key 在数据库中加密存储。',
    apiKeySet: '已配置 Key（••••••••{{last4}}）',
    baseUrl: 'Base URL',
    model: '模型',
    temperature: '温度',
    save: '保存配置',
    saving: '保存中…',
    saved: '配置保存成功。',
    saveFailed: '保存配置失败。',
    loadFailed: '加载配置失败。',
    testConnection: '测试连接',
    testing: '测试中…',
    securityNote: '您的 API Key 使用 Fernet 对称加密存储，设置后不会再次返回给浏览器。',
  },
} as const;

export default settings;
