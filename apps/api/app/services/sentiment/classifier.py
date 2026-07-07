"""Sentiment classifier service — prompt/model + reproducible scoring (FRA-68).

Turns news headlines/summaries into reproducible ``SentimentScore``(label,
score, confidence). Ships two adapters behind a registry:

* ``fixture`` — deterministic keyword-rule classifier (default; no LLM, no
  network, reproducible tests/demo).
* ``openai`` — calls an OpenAI-compatible chat completions endpoint via httpx
  (``response_format`` json_object, ``temperature=0``). Requires
  ``OPENAI_API_KEY``; gated behind the ``SENTIMENT_CLASSIFIER`` env switch so
  the default path stays offline and keyless.

Safety (agent-design.md): the classifier only emits label/score/confidence —
never buy/sell advice or return predictions. Parse failures are skipped (no
score produced) and logged, never silently coerced to neutral. ``published_at``
is preserved verbatim (anti-cheat; no forward-fill here — that is FRA-69's job).

Reproducibility: every ``SentimentScore`` carries ``model_name`` +
``prompt_version`` + ``params`` (temperature etc.) + ``raw_response`` so a later
run can be audited. ``PROMPT_VERSION`` is a code constant — changing the prompt
text requires bumping it, or the version field loses its meaning.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from typing import Any, cast

import httpx
from tenacity import Retrying

from app.core.config import settings
from app.services.datasources.base import build_default_retryer
from app.services.sentiment.protocols import SentimentClassifier
from app.services.sentiment.types import NewsItem, SentimentLabel, SentimentScore

logger = logging.getLogger(__name__)

# --- prompt + version (bump PROMPT_VERSION when the prompt text changes) ------
PROMPT_VERSION = "sentiment-v1"

_SYSTEM_PROMPT = (
    "You are a financial news sentiment classifier. Classify the given news "
    "headline (and summary if provided) into exactly one label: "
    '"positive", "neutral", or "negative". Also return a score in '
    "[-1.0, 1.0] (negative = bearish, 0.0 = neutral, positive = bullish) and "
    "a confidence in [0.0, 1.0]. Respond ONLY as a JSON object: "
    '{"label": "...", "score": ..., "confidence": ...}. '
    "Do not give investment advice or predict returns."
)


# --- fixture keyword lexicon -------------------------------------------------

_POSITIVE_WORDS: frozenset[str] = frozenset(
    {
        "surge",
        "surges",
        "surging",
        "soar",
        "soars",
        "jump",
        "jumps",
        "leap",
        "rally",
        "rallies",
        "beat",
        "beats",
        "raise",
        "raises",
        "raised",
        "high",
        "record",
        "inflows",
        "optimism",
        "strong",
        "stronger",
        "gain",
        "gains",
        "rise",
        "rises",
        "boost",
        "upgrade",
        "upgraded",
        "unveils",
        "announce",
        "announces",
    }
)
_NEGATIVE_WORDS: frozenset[str] = frozenset(
    {
        "slide",
        "slides",
        "slump",
        "drop",
        "drops",
        "fall",
        "falls",
        "decline",
        "downgrade",
        "downgraded",
        "fade",
        "fades",
        "concern",
        "concerns",
        "weak",
        "miss",
        "misses",
        "cut",
        "cuts",
        "fear",
        "selloff",
        "plunge",
        "loss",
        "losses",
        "sue",
        "sued",
        "probe",
        "investigation",
        "narrow",
        "narrows",
    }
)


def _tokenize(text: str) -> set[str]:
    """Lowercase word-tokenize, stripping punctuation (fixture classifier)."""
    return set(re.findall(r"[a-z]+", text.lower()))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _parse_llm_json(content: str) -> dict[str, Any]:
    """Parse the LLM's JSON response into {label, score, confidence}.

    Raises ``ValueError`` (or ``json.JSONDecodeError``) on malformed output so
    the caller can skip the item rather than silently coerce it to neutral.
    """
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")
    label = str(data.get("label", "")).strip().lower()
    if label not in ("positive", "neutral", "negative"):
        raise ValueError(f"invalid label from LLM: {label!r}")
    return {
        "label": label,
        "score": float(data.get("score", 0.0)),
        "confidence": float(data.get("confidence", 0.0)),
    }


# --- FixtureSentimentClassifier ----------------------------------------------


class FixtureSentimentClassifier:
    """Deterministic keyword-rule classifier (FRA-68 default, no network).

    Positive keyword hit -> positive (score +0.6, confidence 0.7); negative
    keyword hit -> negative (score -0.6, confidence 0.7); both or neither ->
    neutral (score 0.0, confidence 0.5). Fully reproducible so tests/demo never
    touch an LLM. The matched keywords are recorded in ``raw_response`` for
    audit.
    """

    #: Stable model name recorded in ``sentiment_scores.model_name``.
    name = "fixture-model"

    def classify(self, items: Sequence[NewsItem]) -> list[SentimentScore]:
        out: list[SentimentScore] = []
        for item in items:
            text = item.headline + " " + (item.summary or "")
            tokens = _tokenize(text)
            pos_hits = tokens & _POSITIVE_WORDS
            neg_hits = tokens & _NEGATIVE_WORDS
            if pos_hits and not neg_hits:
                label: SentimentLabel = "positive"
                score = 0.6
                confidence = 0.7
            elif neg_hits and not pos_hits:
                label = "negative"
                score = -0.6
                confidence = 0.7
            else:
                label = "neutral"
                score = 0.0
                confidence = 0.5
            out.append(
                SentimentScore(
                    asset_id=item.asset_id,
                    published_at=item.published_at,
                    source=item.source,
                    headline=item.headline,
                    model_name=self.name,
                    prompt_version=PROMPT_VERSION,
                    label=label,
                    score=score,
                    confidence=confidence,
                    summary=item.summary,
                    url=item.url,
                    raw_response={
                        "classifier": "fixture",
                        "positive_hits": sorted(pos_hits),
                        "negative_hits": sorted(neg_hits),
                    },
                    params={"temperature": 0.0, "rule": "keyword"},
                )
            )
        return out


# --- LlmSentimentClassifier --------------------------------------------------


class LlmSentimentClassifier:
    """OpenAI-compatible chat completions classifier via httpx (FRA-68).

    Calls ``{base_url}/chat/completions`` with ``response_format`` json_object
    and ``temperature=0`` for reproducibility. Requires ``OPENAI_API_KEY``;
    calling :meth:`classify` without a key raises ``ValueError`` (the default
    ``fixture`` path is unaffected). Parse failures are skipped and logged —
    never silently coerced to neutral.

    The httpx client and retryer are injectable so tests can drive the parse
    path without the network (mirroring the yfinance provider test pattern).
    """

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
    ) -> None:
        self._client = client
        self._retryer = retryer
        self._api_key = api_key if api_key is not None else settings.openai_api_key
        self._base_url = (base_url if base_url is not None else settings.openai_base_url).rstrip(
            "/"
        )
        self._model = model if model is not None else settings.openai_model
        self._temperature = (
            temperature if temperature is not None else settings.sentiment_temperature
        )
        self._timeout = (
            timeout if timeout is not None else float(settings.llm_request_timeout_seconds)
        )

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def _call_llm(self, headline: str, summary: str | None) -> dict[str, Any]:
        """POST one chat completion; return the raw response dict (retried)."""
        user_content = f"Headline: {headline}\nSummary: {summary or 'N/A'}"
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": self._temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        retryer: Retrying = self._retryer if self._retryer is not None else build_default_retryer()

        def _do_post() -> dict[str, Any]:
            resp = self._get_client().post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            return cast(dict[str, Any], resp.json())

        return retryer(_do_post)

    def classify(self, items: Sequence[NewsItem]) -> list[SentimentScore]:
        if not self._api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured; set it or use the fixture classifier"
            )
        out: list[SentimentScore] = []
        for item in items:
            try:
                raw = self._call_llm(item.headline, item.summary)
                content = raw["choices"][0]["message"]["content"]
                parsed = _parse_llm_json(content)
            except Exception:
                # Parse/transport failure: skip (no score) + log. Never silently
                # coerce to neutral — the orchestrator counts skipped items.
                logger.warning(
                    "LLM sentiment parse failed for headline=%r; skipping", item.headline
                )
                continue
            label: SentimentLabel = parsed["label"]
            score = _clamp(parsed["score"], -1.0, 1.0)
            confidence = _clamp(parsed["confidence"], 0.0, 1.0)
            out.append(
                SentimentScore(
                    asset_id=item.asset_id,
                    published_at=item.published_at,
                    source=item.source,
                    headline=item.headline,
                    model_name=self._model,
                    prompt_version=PROMPT_VERSION,
                    label=label,
                    score=score,
                    confidence=confidence,
                    summary=item.summary,
                    url=item.url,
                    raw_response=raw,
                    params={
                        "temperature": self._temperature,
                        "model": self._model,
                        "prompt_version": PROMPT_VERSION,
                    },
                )
            )
        return out


# --- registry ----------------------------------------------------------------

_FACTORIES: dict[str, Callable[[], SentimentClassifier]] = {
    "fixture": lambda: FixtureSentimentClassifier(),
    "openai": lambda: LlmSentimentClassifier(),
}

# Derived from the registry so the allow-list can never drift from the adapters.
SUPPORTED_CLASSIFIERS: tuple[str, ...] = tuple(_FACTORIES.keys())


def get_sentiment_classifier(key: str | None = None) -> SentimentClassifier:
    """Return the :class:`SentimentClassifier` adapter for ``key``.

    ``key=None`` falls back to ``settings.sentiment_classifier`` so callers can
    omit the argument and still respect operator config. Raises
    :class:`ValueError` for an unknown key so the caller (worker / API) can
    surface it as an input/config error rather than a silent miss.
    """
    resolved = key if key is not None else settings.sentiment_classifier
    factory = _FACTORIES.get(resolved)
    if factory is None:
        raise ValueError(
            f"unsupported sentiment classifier: {resolved!r}; "
            f"expected one of {SUPPORTED_CLASSIFIERS}"
        )
    return factory()
