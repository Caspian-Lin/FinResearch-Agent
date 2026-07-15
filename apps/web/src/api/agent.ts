/**
 * Agent Research API client (FRA-90 endpoints, FRA-91 consumer).
 *
 * Thin typed functions wrapping the six `/agent` endpoints. Each imports
 * the shared `ResearchPlanT` for type-safe plan transport — the plan hash
 * guards against drift between what the planner returned and what the
 * orchestrator executes.
 *
 * Security: no tool args, trace payloads, or synthesis content is logged
 * or cached client-side beyond React component state.
 */
import type { ResearchPlanT } from '@finresearch/shared';

import { apiClient } from './client';
import type {
  AgentCancelResponse,
  AgentPlanResponse,
  AgentRunDetail,
  AgentRunEnqueuedResponse,
  AgentRunListResponse,
  AgentTraceResponse,
} from '@/types/api';

/** `POST /agent/plans` — generate a plan draft from a natural-language hypothesis. */
export async function createAgentPlan(hypothesis: string): Promise<AgentPlanResponse> {
  const { data } = await apiClient.post<AgentPlanResponse>('/agent/plans', {
    hypothesis,
  });
  return data;
}

/** `POST /agent/runs` — submit an approved plan for execution (202 enqueued). */
export async function createAgentRun(
  plan: ResearchPlanT,
  planHash: string,
): Promise<AgentRunEnqueuedResponse> {
  const { data } = await apiClient.post<AgentRunEnqueuedResponse>('/agent/runs', {
    plan,
    plan_hash: planHash,
  });
  return data;
}

/** `GET /agent/runs` — paginated list of the caller's runs. */
export async function listAgentRuns(
  limit = 20,
  offset = 0,
): Promise<AgentRunListResponse> {
  const { data } = await apiClient.get<AgentRunListResponse>('/agent/runs', {
    params: { limit, offset },
  });
  return data;
}

/** `GET /agent/runs/{id}` — full run detail. */
export async function getAgentRun(runId: string): Promise<AgentRunDetail> {
  const { data } = await apiClient.get<AgentRunDetail>(`/agent/runs/${runId}`);
  return data;
}

/** `GET /agent/runs/{id}/trace` — ordered steps with nested tool calls. */
export async function getAgentTrace(runId: string): Promise<AgentTraceResponse> {
  const { data } = await apiClient.get<AgentTraceResponse>(`/agent/runs/${runId}/trace`);
  return data;
}

/** `POST /agent/runs/{id}/cancel` — idempotent cancel. */
export async function cancelAgentRun(runId: string): Promise<AgentCancelResponse> {
  const { data } = await apiClient.post<AgentCancelResponse>(`/agent/runs/${runId}/cancel`);
  return data;
}
