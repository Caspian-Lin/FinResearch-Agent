/**
 * Agent Research page — the two-phase user-controllable research workflow.
 *
 * State machine:
 *   compose  → user enters NL hypothesis → POST /agent/plans
 *   review   → user reviews/edits plan → POST /agent/runs (approve)
 *   monitor  → poll GET /agent/runs/{id} + /agent/runs/{id}/trace
 *   result   → terminal (succeeded/failed/canceled)
 *
 * From any state the user can:
 *   - Start a new run (compose)
 *   - Open a past run from history sidebar (monitor/result)
 *   - Cancel a queued/running run (monitor)
 *
 * Safety boundaries enforced by this page:
 *   1. No tool fires until the user explicitly approves the plan.
 *   2. The plan hash must match what the planner returned.
 *   3. Cancel requires a confirmation modal (in RunTimeline).
 *   4. The disclaimer banner is always visible.
 *   5. Risk-fail results show the restricted banner.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, Button, Spin, Typography, message } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';

import { ApiError } from '@/api/client';
import {
  cancelAgentRun,
  createAgentPlan,
  createAgentRun,
  getAgentRun,
  getAgentTrace,
  listAgentRuns,
} from '@/api/agent';
import { AgentHistorySidebar } from '@/components/agent/AgentHistorySidebar';
import { QuestionComposer } from '@/components/agent/QuestionComposer';
import { PlanReview } from '@/components/agent/PlanReview';
import { RunResult } from '@/components/agent/RunResult';
import { RunTimeline } from '@/components/agent/RunTimeline';
import { SiderLayout } from '@/components/layout/SiderLayout';
import { TERMINAL_RUN_STATUSES } from '@finresearch/shared';
import type { ResearchPlanT } from '@finresearch/shared';
import type {
  AgentPlanResponse,
  AgentRunDetail,
  AgentRunSummary,
  AgentTraceResponse,
} from '@/types/api';

const { Title, Text } = Typography;

const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 150;

type Phase = 'compose' | 'review' | 'monitor' | 'result';

function AgentResearchPage() {
  const { t } = useTranslation('agent');
  const { t: tCommon } = useTranslation('common');
  const [messageApi, messageContext] = message.useMessage();

  // Phase
  const [phase, setPhase] = useState<Phase>('compose');

  // Compose state
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [planResponse, setPlanResponse] = useState<AgentPlanResponse | null>(null);

  // Approve state
  const [approving, setApproving] = useState(false);

  // Run state
  const [run, setRun] = useState<AgentRunDetail | null>(null);
  const [trace, setTrace] = useState<AgentTraceResponse | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [canceling, setCanceling] = useState(false);

  // History state
  const [history, setHistory] = useState<AgentRunSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  // Polling
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollCountRef = useRef(0);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);
  useEffect(() => clearTimer, [clearTimer]);

  // ── History ──────────────────────────────────────────────────────────

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await listAgentRuns(20, 0);
      setHistory(res.runs);
    } catch {
      // Stable error path — no language-dependent copy needed inside callback.
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  // ── Compose: generate plan ───────────────────────────────────────────

  const handleGeneratePlan = useCallback(
    async (hypothesis: string) => {
      setPlanLoading(true);
      setPlanError(null);
      try {
        const res = await createAgentPlan(hypothesis);
        setPlanResponse(res);
        setPhase('review');
        if (res.clarification_needed) {
          messageApi.info(res.clarification_needed);
        }
      } catch (err) {
        if (err instanceof ApiError) {
          setPlanError(t('errors.planFailed'));
        }
      } finally {
        setPlanLoading(false);
      }
    },
    [messageApi, t],
  );

  // ── Review: approve & run ────────────────────────────────────────────

  const handleApprove = useCallback(
    async (plan: ResearchPlanT, planHash: string) => {
      setApproving(true);
      try {
        const res = await createAgentRun(plan, planHash);
        setPhase('monitor');
        setSelectedRunId(res.run_id);
        void loadHistory();
        // Start polling
        pollCountRef.current = 0;
        void pollRun(res.run_id);
      } catch (err) {
        if (err instanceof ApiError) {
          messageApi.error(t('errors.runFailed'));
        }
      } finally {
        setApproving(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [messageApi, t, loadHistory],
  );

  // ── Monitor: poll run + trace ────────────────────────────────────────

  const pollRun = useCallback(
    async (runId: string) => {
      clearTimer();
      try {
        const [runDetail, traceDetail] = await Promise.all([
          getAgentRun(runId),
          getAgentTrace(runId),
        ]);
        setRun(runDetail);
        setTrace(traceDetail);
        setSelectedRunId(runId);

        const terminal = TERMINAL_RUN_STATUSES.has(
          runDetail.status as never,
        );

        if (terminal) {
          setPhase('result');
          void loadHistory();
        } else {
          pollCountRef.current += 1;
          if (pollCountRef.current >= MAX_POLLS) {
            messageApi.warning(t('run.timeout'));
            setPhase('result');
          } else {
            setPhase('monitor');
            timerRef.current = setTimeout(() => {
              timerRef.current = null;
              void pollRun(runId);
            }, POLL_INTERVAL_MS);
          }
        }
      } catch {
        pollCountRef.current += 1;
        if (pollCountRef.current >= MAX_POLLS) {
          messageApi.warning(t('run.timeout'));
          setPhase('result');
        } else {
          timerRef.current = setTimeout(() => {
            timerRef.current = null;
            void pollRun(runId);
          }, POLL_INTERVAL_MS);
        }
      }
    },
    [clearTimer, loadHistory, messageApi, t],
  );

  // ── Cancel ───────────────────────────────────────────────────────────

  const handleCancel = useCallback(async () => {
    if (!run) return;
    setCanceling(true);
    try {
      await cancelAgentRun(run.id);
      clearTimer();
      void pollRun(run.id);
    } catch {
      if (messageApi) messageApi.error(t('errors.cancelFailed'));
    } finally {
      setCanceling(false);
    }
  }, [run, clearTimer, pollRun, messageApi, t]);

  // ── Open past run ────────────────────────────────────────────────────

  const handleOpenRun = useCallback(
    async (runId: string) => {
      clearTimer();
      setSelectedRunId(runId);
      setPhase('monitor');
      setTraceLoading(true);
      try {
        const [runDetail, traceDetail] = await Promise.all([
          getAgentRun(runId),
          getAgentTrace(runId),
        ]);
        setRun(runDetail);
        setTrace(traceDetail);

        const terminal = TERMINAL_RUN_STATUSES.has(runDetail.status as never);
        if (terminal) {
          setPhase('result');
        } else {
          pollCountRef.current = 0;
          void pollRun(runId);
        }
      } catch {
        setPhase('compose');
      } finally {
        setTraceLoading(false);
      }
    },
    [clearTimer, pollRun],
  );

  // ── New run ──────────────────────────────────────────────────────────

  const handleNewRun = useCallback(() => {
    clearTimer();
    setPhase('compose');
    setPlanResponse(null);
    setRun(null);
    setTrace(null);
    setSelectedRunId(null);
    setPlanError(null);
  }, [clearTimer]);

  // ── Render ───────────────────────────────────────────────────────────

  const isRestricted =
    run?.synthesis && (run.synthesis.restricted as boolean) === true;

  return (
    <SiderLayout
      sidebar={
        <AgentHistorySidebar
          runs={history}
          loading={historyLoading}
          selectedRunId={selectedRunId}
          onOpenRun={(id) => void handleOpenRun(id)}
          onNewRun={handleNewRun}
        />
      }
    >
      <div className="page">
        {messageContext}

        <div className="page-header">
          <div>
            <Title level={2} className="page-title">
              {t('page.title')}
            </Title>
            <Text type="secondary" className="page-description">
              {t('page.description')}
            </Text>
          </div>
        </div>

        {/* Always-visible disclaimer */}
        <Alert
          type="warning"
          showIcon
          message={t('disclaimer.banner')}
          className="agent-alert agent-page-disclaimer"
        />

        {/* Compose phase */}
        {phase === 'compose' && (
          <QuestionComposer
            loading={planLoading}
            error={planError}
            onSubmit={(h) => void handleGeneratePlan(h)}
            examples={t('examples', { returnObjects: true }) as readonly string[]}
          />
        )}

        {/* Review phase */}
        {phase === 'review' && planResponse?.plan && (
          <>
            {phase === 'review' && (
              <Button
                type="link"
                icon={<ArrowLeftOutlined />}
                onClick={handleNewRun}
                className="agent-back-btn"
              >
                {tCommon('actions.cancel')}
              </Button>
            )}
            <PlanReview
              plan={planResponse.plan}
              planHash={planResponse.plan_hash}
              clarificationNeeded={planResponse.clarification_needed}
              validationErrors={planResponse.validation_errors}
              approving={approving}
              onApprove={(p, h) => void handleApprove(p, h)}
              onRegenerate={handleNewRun}
            />
          </>
        )}

        {/* Review phase — no plan (ambiguity / validation failure) */}
        {phase === 'review' && !planResponse?.plan && (
          <>
            <Button
              type="link"
              icon={<ArrowLeftOutlined />}
              onClick={handleNewRun}
              className="agent-back-btn"
            >
              {tCommon('actions.cancel')}
            </Button>
            {planResponse?.clarification_needed && (
              <Alert
                type="info"
                showIcon
                message={t('plan.clarification')}
                description={planResponse.clarification_needed}
                className="agent-alert"
              />
            )}
            {planResponse?.validation_errors && planResponse.validation_errors.length > 0 && (
              <Alert
                type="error"
                showIcon
                message={t('plan.validationErrors')}
                description={
                  <ul className="agent-validation-list">
                    {planResponse.validation_errors.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                }
                className="agent-alert"
              />
            )}
          </>
        )}

        {/* Monitor phase */}
        {phase === 'monitor' && run && (
          <RunTimeline
            run={run}
            trace={trace}
            traceLoading={traceLoading}
            canceling={canceling}
            onCancel={() => void handleCancel()}
          />
        )}

        {phase === 'monitor' && !run && (
          <div className="loading-block">
            <Spin tip={t('run.polling')}>
              <div style={{ height: 48 }} />
            </Spin>
          </div>
        )}

        {/* Result phase */}
        {phase === 'result' && run && (
          <>
            <RunTimeline
              run={run}
              trace={trace}
              traceLoading={false}
              canceling={false}
              onCancel={() => void handleCancel()}
            />
            <div className="agent-result-section">
              <RunResult synthesis={run.synthesis} restricted={Boolean(isRestricted)} />
            </div>
          </>
        )}

        {phase === 'result' && !run && (
          <Button type="primary" onClick={handleNewRun}>
            {t('history.newRun')}
          </Button>
        )}
      </div>
    </SiderLayout>
  );
}

export default AgentResearchPage;
