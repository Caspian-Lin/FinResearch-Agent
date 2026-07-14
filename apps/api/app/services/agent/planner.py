"""Research Planner Agent — NL hypothesis → validated ResearchPlan (FRA-86).

Turns a free-text investment hypothesis into a fully-bound
:class:`~app.schemas.agent.ResearchPlan` (FRA-84 contract). The Planner is the
**single entry point** of the Week 5 agent pipeline; it never executes tools,
writes the DB, or gives investment advice — it only produces an auditable plan
draft for user review.

Two adapters behind a registry (mirrors the sentiment-classifier pattern):

* ``fixture`` — deterministic bilingual regex parser (default; no LLM, no
  network, reproducible tests/demo).
* ``openai`` — OpenAI-compatible chat completions via httpx
  (``response_format`` json_object, ``temperature=0``). Requires
  ``OPENAI_API_KEY``; gated behind ``PLANNER_PROVIDER`` so the default path
  stays offline and keyless.

Safety (agent-design.md): the Planner may never emit code, SQL, shell, or
broker/order tools. Its output is validated against the FRA-84 allowlists
(factor names, strategy names, baselines) via Pydantic v2 with
``extra="forbid"`` — there is no free-text escape hatch.

Reproducibility: every :class:`PlannerResult` carries
:class:`PlannerProvenance` (provider, model, prompt_version, request_id,
elapsed_ms, token_usage, repair_attempts). Secrets and model-internal reasoning
are never recorded.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.models.asset import Asset
from app.schemas.agent import (
    DEFAULT_COST_SENSITIVITY_BPS,
    SCHEMA_VERSION,
    STRATEGY_NAMES,
    TECHNICAL_FACTOR_NAMES,
    VALIDATION_BASELINE_KINDS,
    DataSource,
    PlanResolution,
    PriceField,
    RebalanceFrequency,
    ResearchPlan,
)

logger = logging.getLogger(__name__)

# ─── Prompt version ──────────────────────────────────────────────────────────

#: Bump when the system prompt text changes; recorded in provenance for audit.
PROMPT_VERSION = "planner-v1"

# ─── System prompt (LLM planner) ─────────────────────────────────────────────

_SYSTEM_PROMPT = f"""\
You are a financial research planner. Convert the user's investment hypothesis \
into a structured JSON research plan. The plan describes historical research \
only — never give investment advice or predict returns.

Respond with ONLY a JSON object (no markdown fences, no commentary) using \
these fields:

{{"research_question": "string",
  "universe": [{{"symbol": "TICKER"}}],
  "benchmark": {{"symbol": "TICKER"}},
  "data_source": "yfinance",
  "start_date": "YYYY-MM-DDT00:00:00Z",
  "end_date": "YYYY-MM-DDT00:00:00Z",
  "price_field": "adjusted",
  "factors": [{{"name": "momentum_126", "kind": "technical", "params": {{}}}}],
  "strategy": {{"name": "momentum", "params": {{"lookback": 126}}, "rebalance": "monthly"}},
  "transaction_cost_bps": 10.0,
  "validation": {{"baselines": ["buy_and_hold", "equal_weight", "benchmark"], \
"metrics": ["annual_return", "sharpe", "max_drawdown", "turnover"], \
"cost_sensitivity_bps": [0.0, 5.0, 10.0, 25.0]}},
  "assumptions": ["assumption 1", "assumption 2"],
  "requested_outputs": ["research_memo", "equity_curve", "ic_table"]}}

RULES:
- Do NOT include asset_id, schema_version, or resolution — the system sets them.
- data_source ∈ {{yfinance, polygon, alpha_vantage, stooq, openbb}}.
- price_field ∈ {{raw, adjusted}}.
- rebalance ∈ {{daily, weekly, monthly}}.
- Factor names (technical): {sorted(TECHNICAL_FACTOR_NAMES)}. \
Sentiment factor: name="sentiment", kind="sentiment".
- Strategy names: {sorted(STRATEGY_NAMES)}. \
If using a sentiment factor, strategy.name must be "sentiment_tech".
- Baselines (non-empty): {sorted(VALIDATION_BASELINE_KINDS)}.
- transaction_cost_bps is MANDATORY (≥0; 0 allowed, omission rejected).
- assumptions must be non-empty; bind every conclusion to stated assumptions.
- requested_outputs must be non-empty.
- Do NOT include code, SQL, shell, or broker/order instructions.
- If the hypothesis is ambiguous, unsupported, or missing critical parameters, \
respond with: {{"clarification_needed": "what is ambiguous or missing"}}.
"""

# ─── Provenance & result types ───────────────────────────────────────────────


@dataclass(frozen=True)
class TokenUsage:
    """Token usage reported by the provider (None when unavailable)."""

    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


@dataclass(frozen=True)
class PlannerProvenance:
    """Audit trail for a single planning attempt.

    Records *how* the plan was produced so a later run can reproduce or audit
    it. Never includes the API key or the model's chain-of-thought.
    """

    provider: str
    model: str
    prompt_version: str
    request_id: str | None
    elapsed_ms: int
    token_usage: TokenUsage | None
    repair_attempts: int


@dataclass
class PlannerResult:
    """Outcome of a planning attempt.

    Exactly one of three states:
    * ``plan is not None`` — success (validated or draft).
    * ``clarification_needed is not None`` — the hypothesis is ambiguous; the
      string tells the user what to provide.
    * ``validation_errors`` non-empty — the plan failed validation after all
      repair attempts and the errors explain why.
    """

    plan: ResearchPlan | None
    validation_errors: list[str] = field(default_factory=list)
    clarification_needed: str | None = None
    provenance: PlannerProvenance | None = None

    @property
    def ok(self) -> bool:
        """True when a plan was successfully produced."""
        return self.plan is not None


# ─── Asset resolution ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AssetResolution:
    """Result of resolving one symbol against the ``assets`` table."""

    symbol: str
    asset_id: uuid.UUID | None
    found: bool
    ambiguous: bool
    exchanges: list[str]
    data_source: str


class AssetResolver(Protocol):
    """Resolve a ticker symbol to an asset UUID + metadata."""

    def resolve(self, symbol: str) -> AssetResolution: ...


class DbAssetResolver:
    """Database-backed resolver: queries the ``assets`` table by symbol.

    Detects ambiguity (same symbol on multiple exchanges) and respects the
    asset-bound ``data_source`` (FRA-78) for cross-source validation.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def resolve(self, symbol: str) -> AssetResolution:
        rows = list(
            self._session.execute(select(Asset).where(Asset.symbol == symbol.upper())).scalars()
        )
        if not rows:
            return AssetResolution(
                symbol=symbol,
                asset_id=None,
                found=False,
                ambiguous=False,
                exchanges=[],
                data_source="yfinance",
            )
        if len(rows) > 1:
            return AssetResolution(
                symbol=symbol,
                asset_id=None,
                found=True,
                ambiguous=True,
                exchanges=[r.exchange for r in rows],
                data_source=rows[0].data_source,
            )
        row = rows[0]
        return AssetResolution(
            symbol=symbol,
            asset_id=row.id,
            found=True,
            ambiguous=False,
            exchanges=[],
            data_source=row.data_source,
        )


@dataclass
class FixtureAssetResolver:
    """In-memory resolver for tests; maps ``symbol → asset_id``."""

    mapping: dict[str, uuid.UUID]

    def resolve(self, symbol: str) -> AssetResolution:
        asset_id = self.mapping.get(symbol.upper())
        if asset_id is None:
            return AssetResolution(
                symbol=symbol,
                asset_id=None,
                found=False,
                ambiguous=False,
                exchanges=[],
                data_source="yfinance",
            )
        return AssetResolution(
            symbol=symbol,
            asset_id=asset_id,
            found=True,
            ambiguous=False,
            exchanges=[],
            data_source="yfinance",
        )


def _resolve_plan_assets(
    plan_dict: dict[str, Any],
    resolver: AssetResolver,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Resolve every universe + benchmark symbol via *resolver*.

    Returns ``(updated_dict, [])`` on success, or ``(None, errors)`` on failure.
    Also enforces data-source consistency (all assets must share the same
    ``data_source``) per acceptance: "尊重 asset-bound data source".
    """
    errors: list[str] = []

    # Resolve benchmark.
    bench_symbol = plan_dict.get("benchmark", {}).get("symbol", "")
    bench_res = resolver.resolve(bench_symbol)
    if not bench_res.found:
        errors.append(f"benchmark symbol '{bench_symbol}' not found in asset database")
    elif bench_res.ambiguous:
        errors.append(
            f"benchmark symbol '{bench_symbol}' is ambiguous "
            f"(exchanges: {', '.join(bench_res.exchanges)})"
        )
    else:
        assert bench_res.asset_id is not None
        plan_dict["benchmark"]["asset_id"] = str(bench_res.asset_id)

    # Resolve universe.
    for ref in plan_dict.get("universe", []):
        sym = ref.get("symbol", "")
        res = resolver.resolve(sym)
        if not res.found:
            errors.append(f"universe symbol '{sym}' not found in asset database")
        elif res.ambiguous:
            errors.append(
                f"universe symbol '{sym}' is ambiguous (exchanges: {', '.join(res.exchanges)})"
            )
        else:
            assert res.asset_id is not None
            ref["asset_id"] = str(res.asset_id)

    if errors:
        return None, errors

    # Data-source consistency: all assets (universe + benchmark) must share
    # the same ``data_source``. Mixed-source backtests are rejected.
    all_symbols = [plan_dict["benchmark"]["symbol"]] + [r["symbol"] for r in plan_dict["universe"]]
    sources = {resolver.resolve(s).data_source for s in all_symbols}
    if len(sources) > 1:
        errors.append(
            f"assets use mixed data sources {sorted(sources)}; "
            "cannot mix sources in a single backtest"
        )
        return None, errors

    # Adopt the asset-bound source (overriding the LLM/fixture default) so the
    # data agent (FRA-87) uses the right adapter.
    sole_source = sources.pop()
    if sole_source in {ds.value for ds in DataSource}:
        plan_dict["data_source"] = sole_source

    plan_dict["resolution"] = PlanResolution.VALIDATED.value
    return plan_dict, []


# ─── Planner protocol ────────────────────────────────────────────────────────


class Planner(Protocol):
    """Convert a natural-language hypothesis into a :class:`PlannerResult`."""

    #: Stable name recorded in provenance.
    name: str

    def plan(
        self,
        hypothesis: str,
        *,
        resolver: AssetResolver | None = None,
    ) -> PlannerResult: ...


# ─── Fixture planner (deterministic, offline) ────────────────────────────────

# Bilingual benchmark markers (split universe from benchmark).
_BENCHMARK_RE = re.compile(
    r"(?:\bvs\.?\b|\bversus\b|\bagainst\b|与|对比|和|相比|对标)",
    re.IGNORECASE,
)

# Ticker extraction: 2–6 uppercase letters, optionally followed by a dot + 1–2
# uppercase letters (e.g. BRK.B). Excludes single-letter tokens to avoid
# matching units like "M" in "6M".
_TICKER_RE = re.compile(r"\b([A-Z]{2,6}(?:\.[A-Z]{1,2})?)\b")

# Date range: 2022-2025, 2022–2025, 2022到2025, 2022~2025.
_DATE_RANGE_RE = re.compile(r"(\d{4})\s*(?:[-–到至~]|到)\s*(\d{4})")

# Lookback: 6M, 3m, 12W, 1w.
_LOOKBACK_RE = re.compile(r"(\d+)\s*([mMwW])\b")

# Rebalance keywords (bilingual).
_REBALANCE_PATTERNS: list[tuple[re.Pattern[str], RebalanceFrequency]] = [
    (re.compile(r"daily|日度|每日", re.IGNORECASE), RebalanceFrequency.DAILY),
    (re.compile(r"weekly|周度|每周", re.IGNORECASE), RebalanceFrequency.WEEKLY),
    (re.compile(r"monthly|月度|每月", re.IGNORECASE), RebalanceFrequency.MONTHLY),
]

# Factor keywords → factor family.
_FACTOR_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"momentum|动量", re.IGNORECASE), "momentum"),
    (re.compile(r"reversal|反转|mean.?revert", re.IGNORECASE), "reversal"),
    (re.compile(r"volatility|波动", re.IGNORECASE), "volatility"),
    (re.compile(r"\bRSI\b", re.IGNORECASE), "rsi"),
    (re.compile(r"\bMACD\b", re.IGNORECASE), "macd"),
    (re.compile(r"sentiment|情绪|舆情", re.IGNORECASE), "sentiment"),
]

# Unsupported strategy keywords → actionable rejection.
_UNSUPPORTED_RE = re.compile(
    r"machine.?learning|deep.?learning|neural.?network|reinforcement|"
    r"LSTM|transformer|GPT|bitcoin|crypto|forex|高频|机器学习|深度学习|神经网络|"
    r"加密货币|比特币",
    re.IGNORECASE,
)

# Stopwords for ticker filtering (common ALL-CAPS words in hypotheses).
_TICKER_STOPWORDS: frozenset[str] = frozenset(
    {
        "RSI",
        "MACD",
        "YM",
        "QM",
        "EM",
        "IT",
        "AI",
        "ETF",
        "GDP",
        "CPI",
        "USD",
        "EUR",
        "JPY",
        "CNY",
        "HKD",
        "GBP",
        "PE",
        "PB",
        "ROE",
        "ROA",
        "IPO",
        "SPAC",
        "CEO",
        "CFO",
        "CTO",
        "COO",
        "API",
        "SQL",
        "SSH",
        "JSON",
        "HTML",
        "CSS",
        "URL",
        "PDF",
        "FRA",
    }
)


def _lookback_to_momentum(periods: int, unit: str) -> str:
    """Map (number, unit) to a canonical momentum factor name."""
    if unit.lower() == "w":
        # Weeks → reversal lookback.
        days = periods * 5
        return "reversal_5" if days <= 5 else "reversal_21"
    # Months → momentum lookback (21 trading days/month).
    if periods <= 1:
        return "momentum_21"
    if periods <= 3:
        return "momentum_63"
    return "momentum_126"


def _extract_tickers(text: str) -> list[str]:
    """Extract candidate ticker symbols from *text*, filtering stopwords."""
    raw = _TICKER_RE.findall(text)
    # Flatten tuples from optional group.
    flat: list[str] = []
    for m in raw:
        flat.append(m if isinstance(m, str) else m[0])
    seen: set[str] = set()
    result: list[str] = []
    for t in flat:
        if t.upper() in _TICKER_STOPWORDS:
            continue
        if t.upper() not in seen:
            seen.add(t.upper())
            result.append(t.upper())
    return result


def _split_benchmark(text: str, tickers: list[str]) -> tuple[str | None, list[str]]:
    """Identify the benchmark (first ticker after a benchmark marker)."""
    marker = _BENCHMARK_RE.search(text)
    if marker is None:
        return None, list(tickers)
    after_text = text[marker.end() :]
    for t in tickers:
        if re.search(rf"\b{re.escape(t)}\b", after_text):
            universe = [x for x in tickers if x != t]
            return t, universe
    return None, list(tickers)


class FixturePlanner:
    """Deterministic rule-based planner — no LLM, no network (FRA-86 default).

    Parses bilingual (EN/ZH) hypotheses with regex to extract universe,
    benchmark, factor, lookback, window, and rebalance cadence. Produces a
    ``draft`` :class:`ResearchPlan` that passes FRA-84 validation. When an
    :class:`AssetResolver` is provided, symbols are resolved and the plan is
    upgraded to ``validated``.
    """

    name = "fixture-planner"

    def plan(
        self,
        hypothesis: str,
        *,
        resolver: AssetResolver | None = None,
    ) -> PlannerResult:
        start = time.monotonic()

        # ── Unsupported strategy → actionable rejection ──────────────────
        unsupported_match = _UNSUPPORTED_RE.search(hypothesis)
        if unsupported_match:
            return PlannerResult(
                plan=None,
                clarification_needed=(
                    f"Strategy '{unsupported_match.group()}' is not supported. "
                    "This platform covers historical factor research (momentum, "
                    "reversal, volatility, RSI, MACD, sentiment) and does not "
                    "support ML/DL/crypto/HFT strategies."
                ),
                provenance=self._provenance(start),
            )

        # ── Extract components ───────────────────────────────────────────
        tickers = _extract_tickers(hypothesis)
        benchmark, universe = _split_benchmark(hypothesis, tickers)

        # ── Missing-window → clarification ───────────────────────────────
        date_match = _DATE_RANGE_RE.search(hypothesis)
        if date_match is None:
            return PlannerResult(
                plan=None,
                clarification_needed=(
                    "Could not detect a time range. Please specify a date window "
                    "(e.g. '2022-2025' or 'Jan 2022 to Dec 2025')."
                ),
                provenance=self._provenance(start),
            )

        # ── Missing-benchmark → clarification ────────────────────────────
        if not benchmark:
            return PlannerResult(
                plan=None,
                clarification_needed=(
                    "Could not identify a benchmark. Please specify one (e.g. "
                    "'vs QQQ', '与沪深300对比')."
                ),
                provenance=self._provenance(start),
            )

        # ── Missing-universe → clarification ─────────────────────────────
        if not universe:
            return PlannerResult(
                plan=None,
                clarification_needed=(
                    "Could not identify any universe assets. Please list the "
                    "tickers to research (e.g. 'NVDA/AMD')."
                ),
                provenance=self._provenance(start),
            )

        # ── Factor detection ─────────────────────────────────────────────
        factor_family = "momentum"  # default
        for pat, fam in _FACTOR_KEYWORDS:
            if pat.search(hypothesis):
                factor_family = fam
                break

        lookback_match = _LOOKBACK_RE.search(hypothesis)
        lookback_periods = int(lookback_match.group(1)) if lookback_match else 6
        lookback_unit = lookback_match.group(2) if lookback_match else "m"

        factors: list[dict[str, Any]] = []
        strategy_name = "factor"
        strategy_params: dict[str, Any] = {}

        if factor_family == "momentum":
            factor_name = _lookback_to_momentum(lookback_periods, lookback_unit)
            factors.append({"name": factor_name, "kind": "technical", "params": {}})
            strategy_name = "momentum"
            lookback_days = (
                lookback_periods * 5 if lookback_unit.lower() == "w" else lookback_periods * 21
            )
            strategy_params = {
                "lookback": lookback_days,
                "top_k": min(2, len(universe)),
            }
        elif factor_family == "reversal":
            factor_name = _lookback_to_momentum(lookback_periods, lookback_unit)
            factors.append({"name": factor_name, "kind": "technical", "params": {}})
            strategy_name = "reversal"
            strategy_params = {"lookback": lookback_periods * 21}
        elif factor_family == "volatility":
            factors.append({"name": "volatility_20d", "kind": "technical", "params": {}})
            strategy_name = "factor"
            strategy_params = {"window": 20}
        elif factor_family == "rsi":
            factors.append({"name": "rsi_14", "kind": "technical", "params": {}})
            strategy_name = "factor"
            strategy_params = {"period": 14}
        elif factor_family == "macd":
            factors.append({"name": "macd_hist", "kind": "technical", "params": {}})
            strategy_name = "ma_crossover"
            strategy_params = {"fast": 12, "slow": 26}
        elif factor_family == "sentiment":
            factors.append({"name": "sentiment", "kind": "sentiment", "params": {}})
            factors.append({"name": "momentum_63", "kind": "technical", "params": {}})
            strategy_name = "sentiment_tech"
            strategy_params = {"lookback": 63, "top_k": min(2, len(universe))}

        # ── Rebalance detection ──────────────────────────────────────────
        rebalance = RebalanceFrequency.MONTHLY
        for pat, freq in _REBALANCE_PATTERNS:
            if pat.search(hypothesis):
                rebalance = freq
                break

        # ── Build plan dict ──────────────────────────────────────────────
        start_year = int(date_match.group(1))
        end_year = int(date_match.group(2))
        if start_year > end_year:
            start_year, end_year = end_year, start_year

        plan_dict: dict[str, Any] = {
            "research_question": hypothesis.strip(),
            "resolution": PlanResolution.DRAFT.value,
            "universe": [{"symbol": s} for s in universe],
            "benchmark": {"symbol": benchmark},
            "data_source": DataSource.YFINANCE.value,
            "start_date": datetime(start_year, 1, 1, tzinfo=UTC).isoformat(),
            "end_date": datetime(end_year, 12, 31, tzinfo=UTC).isoformat(),
            "price_field": PriceField.ADJUSTED.value,
            "factors": factors,
            "strategy": {
                "name": strategy_name,
                "params": strategy_params,
                "rebalance": rebalance.value,
            },
            "transaction_cost_bps": 10.0,
            "validation": {
                "baselines": ["buy_and_hold", "equal_weight", "benchmark"],
                "metrics": ["annual_return", "sharpe", "max_drawdown", "turnover"],
                "cost_sensitivity_bps": list(DEFAULT_COST_SENSITIVITY_BPS),
            },
            "assumptions": [
                "Universe is survivorship-biased (current constituents only).",
                "Cost model is single-side proportional in bps; no slippage or impact.",
                "Trading calendar is the US exchange calendar.",
            ],
            "requested_outputs": [
                "research_memo",
                "equity_curve",
                "ic_table",
                "cost_sensitivity_grid",
            ],
        }

        # Sentiment provenance (pending for draft).
        if factor_family == "sentiment":
            plan_dict["sentiment_provenance"] = {
                "provider": None,
                "model_name": None,
                "prompt_version": None,
                "pending": True,
            }

        # ── Validate against FRA-84 schema ───────────────────────────────
        try:
            plan = ResearchPlan.model_validate(plan_dict)
        except ValueError as exc:
            return PlannerResult(
                plan=None,
                validation_errors=[str(exc)],
                provenance=self._provenance(start),
            )

        # ── Asset resolution (if resolver provided) ──────────────────────
        if resolver is not None:
            resolved_dict, errors = _resolve_plan_assets(plan_dict, resolver)
            if errors:
                return PlannerResult(
                    plan=plan,  # return the draft for partial inspection
                    validation_errors=errors,
                    provenance=self._provenance(start),
                )
            assert resolved_dict is not None
            try:
                plan = ResearchPlan.model_validate(resolved_dict)
            except ValueError as exc:
                return PlannerResult(
                    plan=None,
                    validation_errors=[str(exc)],
                    provenance=self._provenance(start),
                )

        return PlannerResult(
            plan=plan,
            provenance=self._provenance(start),
        )

    def _provenance(self, start: float) -> PlannerProvenance:
        return PlannerProvenance(
            provider="fixture",
            model="fixture-rule",
            prompt_version=PROMPT_VERSION,
            request_id=None,
            elapsed_ms=int((time.monotonic() - start) * 1000),
            token_usage=None,
            repair_attempts=0,
        )


# ─── LLM planner (OpenAI-compatible) ─────────────────────────────────────────

_MAX_HTTP_RETRIES = 3
_MAX_BACKOFF = 10


def _should_retry(exc: BaseException) -> bool:
    """Predicate: retry on httpx transient errors + 429/5xx."""
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return False


def _build_planner_retryer() -> Retrying:
    return Retrying(
        retry=retry_if_exception(_should_retry),
        wait=wait_exponential(multiplier=1, max=_MAX_BACKOFF),
        stop=stop_after_attempt(_MAX_HTTP_RETRIES),
        reraise=True,
    )


class LLMPlanner:
    """OpenAI-compatible chat-completions planner via httpx (FRA-86).

    Calls ``{base_url}/chat/completions`` with ``response_format`` json_object
    and ``temperature=0`` for reproducibility. Requires ``OPENAI_API_KEY``;
    calling :meth:`plan` without a key raises :class:`ValueError`.

    On Pydantic validation failure, the planner feeds the error back to the LLM
    and retries up to ``max_repairs`` times (bounded repair). After exhaustion,
    the structured errors are returned — the planner never guesses or silently
    fills in missing financial parameters.

    The httpx client and retryer are injectable so tests can drive the parse /
    repair path without the network (mirrors the sentiment-classifier pattern).
    """

    name = "openai-planner"

    def __init__(
        self,
        client: httpx.Client | None = None,
        retryer: Retrying | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
        max_repairs: int | None = None,
    ) -> None:
        self._client = client
        self._retryer = retryer
        self._api_key = api_key if api_key is not None else settings.openai_api_key
        self._base_url = (base_url if base_url is not None else settings.openai_base_url).rstrip(
            "/"
        )
        self._model = model if model is not None else settings.openai_model
        self._temperature = temperature if temperature is not None else settings.planner_temperature
        self._timeout = (
            timeout if timeout is not None else float(settings.llm_request_timeout_seconds)
        )
        self._max_repairs = max_repairs if max_repairs is not None else settings.planner_max_repairs

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def _call_llm(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """POST one chat completion; return raw response dict (HTTP-retried)."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        retryer = self._retryer if self._retryer is not None else _build_planner_retryer()

        def _do_post() -> dict[str, Any]:
            resp = self._get_client().post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            return cast(dict[str, Any], resp.json())

        return retryer(_do_post)

    @staticmethod
    def _sanitize_plan_dict(raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize the LLM's JSON dict before Pydantic validation.

        - Force ``schema_version`` and ``resolution=draft``.
        - Strip ``asset_id`` from universe/benchmark (the LLM cannot know them).
        - Remove ``clarification_needed`` (handled by caller).
        """
        raw.pop("clarification_needed", None)
        raw["schema_version"] = SCHEMA_VERSION
        raw["resolution"] = PlanResolution.DRAFT.value
        for ref in raw.get("universe", []):
            ref.pop("asset_id", None)
        bench = raw.get("benchmark")
        if isinstance(bench, dict):
            bench.pop("asset_id", None)
        return raw

    @staticmethod
    def _repair_message(exc: Exception) -> str:
        """Build a concise, safe repair prompt (no secrets, no CoT)."""
        msg = str(exc)
        if len(msg) > 500:
            msg = msg[:500] + "…"
        return (
            f"The JSON failed validation: {msg}. "
            "Please fix the errors and return the complete JSON plan again."
        )

    def plan(
        self,
        hypothesis: str,
        *,
        resolver: AssetResolver | None = None,
    ) -> PlannerResult:
        if not self._api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured; set it or use the fixture planner "
                "(PLANNER_PROVIDER=fixture)"
            )

        start = time.monotonic()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": hypothesis},
        ]

        last_errors: list[str] = []
        request_id: str | None = None
        token_usage: TokenUsage | None = None
        repair_attempts = 0

        for attempt in range(self._max_repairs + 1):
            # ── HTTP call (bounded retry for transient errors) ────────────
            try:
                raw = self._call_llm(messages)
            except Exception as exc:
                return PlannerResult(
                    plan=None,
                    validation_errors=[
                        f"LLM request failed after retries: {type(exc).__name__}: {exc!s}"
                    ],
                    provenance=PlannerProvenance(
                        provider="openai",
                        model=self._model,
                        prompt_version=PROMPT_VERSION,
                        request_id=request_id,
                        elapsed_ms=int((time.monotonic() - start) * 1000),
                        token_usage=token_usage,
                        repair_attempts=repair_attempts,
                    ),
                )

            request_id = cast(str | None, raw.get("id"))
            usage_raw = raw.get("usage")
            if isinstance(usage_raw, dict):
                token_usage = TokenUsage(
                    prompt_tokens=usage_raw.get("prompt_tokens"),
                    completion_tokens=usage_raw.get("completion_tokens"),
                    total_tokens=usage_raw.get("total_tokens"),
                )

            content = cast(str, raw["choices"][0]["message"]["content"])

            # ── Parse JSON ────────────────────────────────────────────────
            try:
                plan_dict = json.loads(content)
            except json.JSONDecodeError as exc:
                last_errors = [f"invalid JSON: {exc}"]
                if attempt < self._max_repairs:
                    repair_attempts += 1
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": self._repair_message(exc)})
                    continue
                break  # max repairs exhausted

            if not isinstance(plan_dict, dict):
                last_errors = ["LLM response is not a JSON object"]
                if attempt < self._max_repairs:
                    repair_attempts += 1
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": "Response must be a JSON object."})
                    continue
                break

            # ── Clarification shortcut ────────────────────────────────────
            clarification = plan_dict.get("clarification_needed")
            if isinstance(clarification, str) and clarification.strip():
                return PlannerResult(
                    plan=None,
                    clarification_needed=clarification.strip(),
                    provenance=PlannerProvenance(
                        provider="openai",
                        model=self._model,
                        prompt_version=PROMPT_VERSION,
                        request_id=request_id,
                        elapsed_ms=int((time.monotonic() - start) * 1000),
                        token_usage=token_usage,
                        repair_attempts=repair_attempts,
                    ),
                )

            # ── Validate against FRA-84 schema ────────────────────────────
            try:
                plan_dict = self._sanitize_plan_dict(plan_dict)
                plan = ResearchPlan.model_validate(plan_dict)
            except ValueError as exc:
                last_errors = [str(exc)]
                if attempt < self._max_repairs:
                    repair_attempts += 1
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": self._repair_message(exc)})
                    continue
                break  # max repairs exhausted

            # ── Asset resolution ──────────────────────────────────────────
            if resolver is not None:
                resolved_dict, errors = _resolve_plan_assets(plan_dict, resolver)
                if errors:
                    return PlannerResult(
                        plan=plan,
                        validation_errors=errors,
                        provenance=PlannerProvenance(
                            provider="openai",
                            model=self._model,
                            prompt_version=PROMPT_VERSION,
                            request_id=request_id,
                            elapsed_ms=int((time.monotonic() - start) * 1000),
                            token_usage=token_usage,
                            repair_attempts=repair_attempts,
                        ),
                    )
                assert resolved_dict is not None
                try:
                    plan = ResearchPlan.model_validate(resolved_dict)
                except ValueError as exc:
                    return PlannerResult(
                        plan=None,
                        validation_errors=[str(exc)],
                        provenance=PlannerProvenance(
                            provider="openai",
                            model=self._model,
                            prompt_version=PROMPT_VERSION,
                            request_id=request_id,
                            elapsed_ms=int((time.monotonic() - start) * 1000),
                            token_usage=token_usage,
                            repair_attempts=repair_attempts,
                        ),
                    )

            # ── Success ───────────────────────────────────────────────────
            return PlannerResult(
                plan=plan,
                provenance=PlannerProvenance(
                    provider="openai",
                    model=self._model,
                    prompt_version=PROMPT_VERSION,
                    request_id=request_id,
                    elapsed_ms=int((time.monotonic() - start) * 1000),
                    token_usage=token_usage,
                    repair_attempts=repair_attempts,
                ),
            )

        # ── Max repairs exhausted ────────────────────────────────────────
        return PlannerResult(
            plan=None,
            validation_errors=last_errors,
            provenance=PlannerProvenance(
                provider="openai",
                model=self._model,
                prompt_version=PROMPT_VERSION,
                request_id=request_id,
                elapsed_ms=int((time.monotonic() - start) * 1000),
                token_usage=token_usage,
                repair_attempts=repair_attempts,
            ),
        )


# ─── Registry

_FACTORIES: dict[str, Callable[[], Planner]] = {
    "fixture": lambda: FixturePlanner(),
    "openai": lambda: LLMPlanner(),
}

#: Derived from the registry so the allow-list can never drift.
SUPPORTED_PLANNERS: tuple[str, ...] = tuple(_FACTORIES.keys())


def get_planner(key: str | None = None) -> Planner:
    """Return the :class:`Planner` adapter for *key*.

    ``key=None`` falls back to ``settings.planner_provider`` so callers can
    omit the argument and still respect operator config. Raises
    :class:`ValueError` for an unknown key.
    """
    resolved = key if key is not None else settings.planner_provider
    factory = _FACTORIES.get(resolved)
    if factory is None:
        raise ValueError(f"unsupported planner: {resolved!r}; expected one of {SUPPORTED_PLANNERS}")
    return factory()


__all__ = [
    "PROMPT_VERSION",
    "TokenUsage",
    "PlannerProvenance",
    "PlannerResult",
    "AssetResolution",
    "AssetResolver",
    "DbAssetResolver",
    "FixtureAssetResolver",
    "Planner",
    "FixturePlanner",
    "LLMPlanner",
    "SUPPORTED_PLANNERS",
    "get_planner",
]
