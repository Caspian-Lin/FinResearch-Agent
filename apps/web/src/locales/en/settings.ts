const settings = {
  nav: {
    settings: 'Settings',
  },
  llm: {
    title: 'LLM Configuration',
    description:
      'Configure your LLM provider credentials here. These settings are used across Agent Research and Sentiment Analysis.',
    provider: 'Provider',
    providerFixture: 'Fixture (offline, no API key needed)',
    providerOpenai: 'OpenAI-compatible',
    apiKey: 'API Key',
    apiKeyPlaceholder: 'Enter your API key (e.g. sk-...)',
    apiKeyHint: 'Leave empty to keep the existing key. The key is encrypted at rest.',
    apiKeySet: 'Key configured (••••••••{{last4}})',
    baseUrl: 'Base URL',
    model: 'Model',
    temperature: 'Temperature',
    save: 'Save Configuration',
    saving: 'Saving…',
    saved: 'Configuration saved successfully.',
    saveFailed: 'Failed to save configuration.',
    loadFailed: 'Failed to load configuration.',
    testConnection: 'Test Connection',
    testing: 'Testing…',
    securityNote:
      'Your API key is encrypted with Fernet symmetric encryption and never returned to the browser after being set.',
  },
} as const;

export default settings;
