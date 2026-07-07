"""Sentiment classifier + classification orchestrator tests (FRA-68).

Covers the classifier registry (:func:`get_sentiment_classifier` +
:data:`SUPPORTED_CLASSIFIERS`), the ``FixtureSentimentClassifier`` keyword path,
the ``LlmSentimentClassifier`` httpx/JSON path (no network — httpx.Client is
monkeypatched), :func:`upsert_sentiment_scores` idempotency, and the
:func:`classify_news_items` orchestrator + RQ entry point.

The LLM path is exercised by injecting a fake ``httpx.Client`` whose ``post``
returns hand-built chat-completion dicts, so the JSON parse, range clamp,
parse-failure-skip, and raw_response/params persistence paths run for real
without an API key or network. DB integration follows the per-file fixture
pattern (PREFIX ``FRA68TEST``, FK cleanup order ``sentiment_scores`` →
``news_items`` → ``assets``); the root conftest is untouched.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.news import NewsItem as NewsItemModel
from app.models.news import SentimentScore as SentimentScoreModel
from app.services.sentiment.classifier import (
    PROMPT_VERSION,
    SUPPORTED_CLASSIFIERS,
    FixtureSentimentClassifier,
    LlmSentimentClassifier,
    get_sentiment_classifier,
)
from app.services.sentiment.classify import classify_news_items, upsert_sentiment_scores
from app.services.sentiment.protocols import SentimentClassifier
from app.services.sentiment.types import NewsItem
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from worker.tasks.sentiment import classify_news as classify_news_task

PREFIX = "FRA68TEST"


# ---------------------------------------------------------------------------
# helpers — no-DB unit fixtures
# ---------------------------------------------------------------------------


def _mk_item(asset: str, headline: str, when: datetime | None = None) -> NewsItem:
    return NewsItem(
        asset_id=asset,
        published_at=when or datetime(2024, 6, 4, 14, 0, tzinfo=UTC),
        source="fixture",
        headline=headline,
    )


class _FakeResp:
    def __init__(self, data: Any) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        if isinstance(self._data, Exception):
            raise self._data

    def json(self) -> dict[str, Any]:
        assert not isinstance(self._data, Exception)
        return self._data


class _FakeClient:
    """Stand-in for httpx.Client; returns queued chat-completion dicts."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.posts: list[dict[str, Any]] = []

    def post(self, url: str, *, json: Any = None, headers: Any = None) -> _FakeResp:
        self.posts.append({"url": url, "json": json, "headers": headers})
        if not self._responses:
            raise AssertionError("no more fake responses queued")
        return _FakeResp(self._responses.pop(0))


def _llm_response(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, fake: _FakeClient) -> None:
    import app.services.sentiment.classifier as clf_mod

    monkeypatch.setattr(clf_mod.httpx, "Client", lambda **kw: fake)


# ---------------------------------------------------------------------------
# DB helpers + fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    asset_ids = "SELECT id FROM assets WHERE symbol LIKE :p"
    db.execute(
        text(f"DELETE FROM sentiment_scores WHERE asset_id IN ({asset_ids})"),
        {"p": f"{PREFIX}%"},
    )
    db.execute(text(f"DELETE FROM news_items WHERE asset_id IN ({asset_ids})"), {"p": f"{PREFIX}%"})
    db.execute(text("DELETE FROM assets WHERE symbol LIKE :p"), {"p": f"{PREFIX}%"})
    db.commit()


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)
        db.close()


def _hash(headline: str) -> str:
    return hashlib.sha256(headline.encode("utf-8")).hexdigest()


def _make_asset(db: Session, symbol: str) -> Asset:
    asset = Asset(
        symbol=symbol,
        name=f"Test {symbol}",
        exchange="NASDAQ",
        asset_type="stock",
        currency="USD",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _make_news(
    db: Session,
    asset: Asset,
    headline: str,
    published_at: datetime | None = None,
    source: str = "fixture",
) -> NewsItemModel:
    news = NewsItemModel(
        asset_id=asset.id,
        source=source,
        published_at=published_at or datetime(2024, 6, 4, 14, 0, tzinfo=UTC),
        headline=headline,
        headline_hash=_hash(headline),
        raw_payload={"provider": "fixture"},
    )
    db.add(news)
    db.commit()
    db.refresh(news)
    return news


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_supported_classifiers_lists_both() -> None:
    assert SUPPORTED_CLASSIFIERS == ("fixture", "openai")


def test_get_classifier_routes_known() -> None:
    assert isinstance(get_sentiment_classifier("fixture"), FixtureSentimentClassifier)
    assert isinstance(get_sentiment_classifier("openai"), LlmSentimentClassifier)


def test_get_classifier_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unsupported sentiment classifier"):
        get_sentiment_classifier("huggingface")


def test_get_classifier_none_falls_back_to_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.sentiment.classifier as clf_mod

    monkeypatch.setattr(clf_mod.settings, "sentiment_classifier", "openai")
    assert isinstance(get_sentiment_classifier(None), LlmSentimentClassifier)


# ---------------------------------------------------------------------------
# FixtureSentimentClassifier — keyword rule
# ---------------------------------------------------------------------------


def test_fixture_classifier_positive_keyword() -> None:
    scores = FixtureSentimentClassifier().classify([_mk_item("NVDA", "NVDA surges on earnings")])
    assert len(scores) == 1
    assert scores[0].label == "positive"
    assert scores[0].score == 0.6
    assert scores[0].confidence == 0.7
    assert scores[0].model_name == "fixture-model"
    assert scores[0].prompt_version == PROMPT_VERSION
    assert "surges" in scores[0].raw_response["positive_hits"]


def test_fixture_classifier_negative_keyword() -> None:
    scores = FixtureSentimentClassifier().classify([_mk_item("AMD", "AMD downgraded on concerns")])
    assert scores[0].label == "negative"
    assert scores[0].score == -0.6
    assert "downgraded" in scores[0].raw_response["negative_hits"]


def test_fixture_classifier_neutral_when_no_keyword() -> None:
    scores = FixtureSentimentClassifier().classify([_mk_item("QQQ", "QQQ opens unchanged")])
    assert scores[0].label == "neutral"
    assert scores[0].score == 0.0
    assert scores[0].confidence == 0.5


def test_fixture_classifier_neutral_when_both_polarities() -> None:
    # Both a positive and negative word -> neutral (ambiguous).
    scores = FixtureSentimentClassifier().classify(
        [_mk_item("X", "Company raises guidance but faces probe")]
    )
    assert scores[0].label == "neutral"


def test_fixture_classifier_is_deterministic() -> None:
    items = [_mk_item("A", "surge"), _mk_item("B", "downgrade"), _mk_item("C", "flat")]
    first = FixtureSentimentClassifier().classify(items)
    second = FixtureSentimentClassifier().classify(items)
    assert [(s.label, s.score, s.confidence) for s in first] == [
        (s.label, s.score, s.confidence) for s in second
    ]


def test_fixture_classifier_records_reproducibility_fields() -> None:
    scores = FixtureSentimentClassifier().classify([_mk_item("A", "surge")])
    s = scores[0]
    assert s.model_name == "fixture-model"
    assert s.prompt_version == PROMPT_VERSION
    assert s.params["temperature"] == 0.0
    assert s.params["rule"] == "keyword"
    assert s.raw_response["classifier"] == "fixture"


# ---------------------------------------------------------------------------
# LlmSentimentClassifier — httpx path (no network)
# ---------------------------------------------------------------------------


def test_llm_classifier_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient([_llm_response('{"label": "positive", "score": 0.8, "confidence": 0.9}')])
    _patch_httpx(monkeypatch, fake)
    clf = LlmSentimentClassifier(api_key="fake", model="gpt-4o-mini")

    scores = clf.classify([_mk_item("AAPL", "AAPL beats estimates")])
    assert len(scores) == 1
    s = scores[0]
    assert s.label == "positive"
    assert s.score == 0.8
    assert s.confidence == 0.9
    assert s.model_name == "gpt-4o-mini"
    assert s.prompt_version == PROMPT_VERSION
    # prompt was sent as json_object with temperature 0
    assert fake.posts[0]["json"]["response_format"] == {"type": "json_object"}
    assert fake.posts[0]["json"]["temperature"] == 0.0
    assert fake.posts[0]["headers"]["Authorization"] == "Bearer fake"
    # raw_response preserved verbatim
    assert s.raw_response["choices"][0]["message"]["content"].startswith("{")


def test_llm_classifier_clamps_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient([_llm_response('{"label": "positive", "score": 5.0, "confidence": 2.0}')])
    _patch_httpx(monkeypatch, fake)
    clf = LlmSentimentClassifier(api_key="fake")

    scores = clf.classify([_mk_item("A", "surge")])
    assert scores[0].score == 1.0  # clamped to [-1, 1]
    assert scores[0].confidence == 1.0  # clamped to [0, 1]


def test_llm_classifier_skips_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient([_llm_response("not valid json")])
    _patch_httpx(monkeypatch, fake)
    clf = LlmSentimentClassifier(api_key="fake")

    scores = clf.classify([_mk_item("A", "surge")])
    assert scores == []  # parse failure -> skipped, not coerced to neutral


def test_llm_classifier_skips_bad_label(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient([_llm_response('{"label": "bullish", "score": 0.5, "confidence": 0.5}')])
    _patch_httpx(monkeypatch, fake)
    clf = LlmSentimentClassifier(api_key="fake")

    scores = clf.classify([_mk_item("A", "surge")])
    assert scores == []  # invalid label -> skipped


def test_llm_classifier_no_key_raises() -> None:
    clf = LlmSentimentClassifier(api_key="")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        clf.classify([_mk_item("A", "surge")])


def test_llm_classifier_records_params_with_prompt_version(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient([_llm_response('{"label": "neutral", "score": 0.1, "confidence": 0.4}')])
    _patch_httpx(monkeypatch, fake)
    clf = LlmSentimentClassifier(api_key="fake", model="gpt-4o-mini", temperature=0.0)

    scores = clf.classify([_mk_item("A", "flat day")])
    s = scores[0]
    assert s.params["model"] == "gpt-4o-mini"
    assert s.params["temperature"] == 0.0
    assert s.params["prompt_version"] == PROMPT_VERSION


# ---------------------------------------------------------------------------
# runtime_checkable
# ---------------------------------------------------------------------------


def test_classifiers_are_runtime_checkable() -> None:
    assert isinstance(FixtureSentimentClassifier(), SentimentClassifier)
    assert isinstance(LlmSentimentClassifier(api_key="x"), SentimentClassifier)


# ---------------------------------------------------------------------------
# upsert_sentiment_scores — idempotent (DB)
# ---------------------------------------------------------------------------


def _score_row(
    news: NewsItemModel, asset: Asset, model_name: str = "fixture-model", **extra: Any
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "news_item_id": news.id,
        "asset_id": asset.id,
        "published_at": news.published_at,
        "model_name": model_name,
        "label": "positive",
        "score": Decimal("0.600000"),
        "confidence": Decimal("0.700000"),
        "raw_response": {"classifier": "fixture"},
        "params": {"prompt_version": PROMPT_VERSION, "temperature": 0.0},
    }
    values.update(extra)
    return values


def test_upsert_scores_empty_returns_zero(db_session: Session) -> None:
    assert upsert_sentiment_scores(db_session, []) == (0, 0)


def test_upsert_scores_inserts_new(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA68TEST-U1")
    news = _make_news(db_session, asset, "surge")
    inserted, updated = upsert_sentiment_scores(db_session, [_score_row(news, asset)])
    db_session.commit()
    assert inserted == 1
    assert updated == 0
    assert (
        len(
            db_session.scalars(
                select(SentimentScoreModel).where(SentimentScoreModel.news_item_id == news.id)
            ).all()
        )
        == 1
    )


def test_upsert_scores_is_idempotent(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA68TEST-U2")
    news = _make_news(db_session, asset, "surge")
    row = _score_row(news, asset)

    upsert_sentiment_scores(db_session, [row])
    db_session.commit()
    inserted2, updated2 = upsert_sentiment_scores(db_session, [row])
    db_session.commit()

    assert inserted2 == 0
    assert updated2 == 1
    total = len(
        db_session.scalars(
            select(SentimentScoreModel).where(SentimentScoreModel.news_item_id == news.id)
        ).all()
    )
    assert total == 1


def test_upsert_scores_overwrites_same_conflict_key(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA68TEST-U3")
    news = _make_news(db_session, asset, "surge")
    upsert_sentiment_scores(
        db_session, [_score_row(news, asset, label="positive", score=Decimal("0.6"))]
    )
    db_session.commit()
    # Same (news_item_id, model_name), revised label/score.
    upsert_sentiment_scores(
        db_session,
        [_score_row(news, asset, label="negative", score=Decimal("-0.6"))],
    )
    db_session.commit()

    rows = db_session.scalars(
        select(SentimentScoreModel).where(SentimentScoreModel.news_item_id == news.id)
    ).all()
    assert len(rows) == 1  # overwritten, not duplicated
    assert rows[0].label == "negative"
    assert rows[0].score == Decimal("-0.600000")


def test_upsert_scores_distinct_models_coexist(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA68TEST-U4")
    news = _make_news(db_session, asset, "surge")
    upsert_sentiment_scores(
        db_session,
        [
            _score_row(news, asset, model_name="fixture-model"),
            _score_row(news, asset, model_name="gpt-4o-mini"),
        ],
    )
    db_session.commit()
    models = {
        r.model_name
        for r in db_session.scalars(
            select(SentimentScoreModel).where(SentimentScoreModel.news_item_id == news.id)
        ).all()
    }
    assert models == {"fixture-model", "gpt-4o-mini"}


# ---------------------------------------------------------------------------
# classify_news_items — orchestrator (DB)
# ---------------------------------------------------------------------------


def test_classify_writes_scores_and_persists_reproducibility(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA68TEST-C1")
    news = _make_news(db_session, asset, "NVDA surges on earnings")
    result = classify_news_items([news.id], classifier_key="fixture")

    assert result["status"] == "success"
    assert result["classified"] == 1
    assert result["inserted"] == 1
    assert result["classifier"] == "fixture"

    row = db_session.scalars(
        select(SentimentScoreModel).where(SentimentScoreModel.news_item_id == news.id)
    ).one()
    assert row.label == "positive"  # "surges" keyword
    assert row.model_name == "fixture-model"
    # reproducibility metadata persisted (FRA-68 acceptance)
    assert row.params["prompt_version"] == PROMPT_VERSION
    assert row.params["temperature"] == 0.0
    assert row.raw_response["classifier"] == "fixture"
    assert row.score == Decimal("0.600000")


def test_classify_is_idempotent_on_repeat(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA68TEST-C2")
    news = _make_news(db_session, asset, "AMD downgraded on concerns")
    first = classify_news_items([news.id], classifier_key="fixture")
    second = classify_news_items([news.id], classifier_key="fixture")

    assert first["inserted"] == 1
    assert second["inserted"] == 0
    assert second["updated"] == 1
    total = len(
        db_session.scalars(
            select(SentimentScoreModel).where(SentimentScoreModel.news_item_id == news.id)
        ).all()
    )
    assert total == 1


def test_classify_missing_news_raises(db_session: Session) -> None:
    fake_id = "00000000-0000-0000-0000-000000000010"
    import uuid as _uuid

    with pytest.raises(ValueError, match="news_items not found"):
        classify_news_items([_uuid.UUID(fake_id)], classifier_key="fixture")


def test_classify_empty_returns_no_data(db_session: Session) -> None:
    result = classify_news_items([], classifier_key="fixture")
    assert result["status"] == "success_no_data"
    assert result["classified"] == 0


def test_classify_too_many_raises(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.sentiment.classify as classify_mod

    monkeypatch.setattr(classify_mod.settings, "sentiment_classify_max_items", 2)
    asset = _make_asset(db_session, "FRA68TEST-C3")
    news1 = _make_news(db_session, asset, "surge")
    news2 = _make_news(db_session, asset, "drop")
    news3 = _make_news(db_session, asset, "flat")
    with pytest.raises(ValueError, match="too many news items"):
        classify_news_items([news1.id, news2.id, news3.id], classifier_key="fixture")


def test_classify_unknown_classifier_raises(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA68TEST-C4")
    news = _make_news(db_session, asset, "surge")
    with pytest.raises(ValueError, match="unsupported sentiment classifier"):
        classify_news_items([news.id], classifier_key="huggingface")


def test_classify_uses_llm_classifier_with_fake_httpx(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeClient([_llm_response('{"label": "negative", "score": -0.7, "confidence": 0.85}')])
    _patch_httpx(monkeypatch, fake)
    import app.services.sentiment.classifier as clf_mod

    monkeypatch.setattr(clf_mod.settings, "openai_api_key", "fake")
    asset = _make_asset(db_session, "FRA68TEST-C5")
    news = _make_news(db_session, asset, "AAPL plunged on weak guidance")

    result = classify_news_items([news.id], classifier_key="openai")
    assert result["status"] == "success"
    assert result["classified"] == 1
    row = db_session.scalars(
        select(SentimentScoreModel).where(SentimentScoreModel.news_item_id == news.id)
    ).one()
    assert row.label == "negative"
    assert row.score == Decimal("-0.700000")
    assert row.model_name  # settings.openai_model default
    assert row.params["prompt_version"] == PROMPT_VERSION
    assert row.raw_response["choices"][0]["message"]["content"].startswith("{")


# ---------------------------------------------------------------------------
# worker.tasks.sentiment.classify_news — RQ entry point
# ---------------------------------------------------------------------------


def test_task_classify_news_success(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA68TEST-T1")
    news = _make_news(db_session, asset, "NVDA surges on earnings")
    result = classify_news_task([str(news.id)], classifier="fixture")
    assert result["status"] == "success"
    assert result["inserted"] == 1
    rows = db_session.scalars(
        select(SentimentScoreModel).where(SentimentScoreModel.news_item_id == news.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].label == "positive"


def test_task_classify_news_missing_raises() -> None:
    fake_id = "00000000-0000-0000-0000-000000000011"
    with pytest.raises(ValueError, match="news_items not found"):
        classify_news_task([fake_id], classifier="fixture")
