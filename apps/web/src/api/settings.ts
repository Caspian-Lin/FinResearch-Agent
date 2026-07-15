/**
 * Settings API client (FRA-93).
 *
 * Per-user LLM configuration: provider, API key, base URL, model, temperature.
 * The API key is never returned by the server — only `has_api_key` + last4.
 */
import { apiClient } from './client';
import type { LLMConfigRead, LLMConfigUpdate } from '@/types/api';

export async function getLLMConfig(): Promise<LLMConfigRead> {
  const { data } = await apiClient.get<LLMConfigRead>('/settings/llm');
  return data;
}

export async function updateLLMConfig(payload: LLMConfigUpdate): Promise<LLMConfigRead> {
  const { data } = await apiClient.put<LLMConfigRead>('/settings/llm', payload);
  return data;
}
