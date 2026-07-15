/**
 * Settings page tests (FRA-93).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import SettingsPage from '@/pages/SettingsPage';
import i18n from '@/i18n';
import type { LLMConfigRead } from '@/types/api';

const mocks = vi.hoisted(() => ({
  getLLMConfig: vi.fn(),
  updateLLMConfig: vi.fn(),
}));

vi.mock('@/api/settings', () => ({
  getLLMConfig: mocks.getLLMConfig,
  updateLLMConfig: mocks.updateLLMConfig,
}));

const emptyConfig: LLMConfigRead = {
  provider: 'fixture',
  has_api_key: false,
  api_key_last4: null,
  base_url: null,
  model: null,
  temperature: null,
  updated_at: null,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getLLMConfig.mockReset();
  mocks.updateLLMConfig.mockReset();
  mocks.getLLMConfig.mockResolvedValue(emptyConfig);
  void i18n.changeLanguage('en');
});

describe('SettingsPage', () => {
  it('loads and displays the LLM config form', async () => {
    renderPage();
    expect(await screen.findByText('LLM Configuration')).toBeInTheDocument();
    expect(screen.getByText('Provider')).toBeInTheDocument();
    expect(screen.getByText('API Key')).toBeInTheDocument();
  });

  it('shows "Fixture" as default provider', async () => {
    renderPage();
    await screen.findByText('LLM Configuration');
    expect(screen.getByText('Fixture (offline, no API key needed)')).toBeInTheDocument();
  });

  it('shows existing key indicator when has_api_key is true', async () => {
    mocks.getLLMConfig.mockResolvedValue({
      ...emptyConfig,
      provider: 'openai',
      has_api_key: true,
      api_key_last4: '1234',
      model: 'gpt-4o-mini',
    });
    renderPage();
    expect(await screen.findByText(/Key configured/i)).toBeInTheDocument();
  });

  it('calls updateLLMConfig on save', async () => {
    mocks.updateLLMConfig.mockResolvedValue(emptyConfig);
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('LLM Configuration');
    const saveBtn = screen.getByRole('button', { name: /save configuration/i });
    await user.click(saveBtn);

    await waitFor(() => expect(mocks.updateLLMConfig).toHaveBeenCalledTimes(1));
  });

  it('shows security note about encryption', async () => {
    renderPage();
    expect(await screen.findByText(/encrypted with Fernet/i)).toBeInTheDocument();
  });
});
