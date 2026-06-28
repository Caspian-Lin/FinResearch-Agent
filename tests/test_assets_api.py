"""Real tests for the /assets CRUD API (FRA-7).

Fixtures live in this file only — the shared ``tests/conftest.py`` is left
untouched to avoid merge conflicts with parallel work. Each test cleans up
only rows it could have created (``symbol LIKE 'FRA7TEST%'``) before and
after running, so the shared host Postgres stays pristine.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.asset import Asset
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

# All rows created by this suite carry this symbol prefix so cleanup is surgical.
TEST_PREFIX = "FRA7TEST"


def _cleanup(db: Session) -> None:
    """Delete only rows owned by this test suite."""
    db.execute(text("DELETE FROM assets WHERE symbol LIKE :p"), {"p": f"{TEST_PREFIX}%"})
    db.commit()


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """Yield a fresh SessionLocal bound to the host Postgres."""
    db = SessionLocal()
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)
        db.close()


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    """TestClient wired so every request reuses the fixture's session.

    Closing the session inside the dependency (after the request finishes)
    matches the production ``get_db`` lifecycle while keeping state visible
    to the fixture for assertions and cleanup.
    """

    def _override_get_db() -> Iterator[Session]:
        try:
            yield db_session
        finally:
            # Do not close here — the fixture owns the session lifecycle.
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /assets
# ---------------------------------------------------------------------------


def test_create_asset_returns_201_and_normalizes_case(client: TestClient) -> None:
    """Created asset echoes back with normalized symbol/exchange and a UUID id."""
    resp = client.post(
        "/assets",
        json={
            "symbol": " fra7test-aapl ",  # whitespace + lowercase -> FRA7TEST-AAPL
            "name": "Test Apple Inc",
            "exchange": "nasdaq",
            "asset_type": "stock",
            "currency": "usd",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["symbol"] == "FRA7TEST-AAPL"
    assert body["exchange"] == "NASDAQ"
    assert body["currency"] == "USD"
    assert body["name"] == "Test Apple Inc"
    # asset_id is a parseable UUID (identity key).
    parsed = uuid.UUID(body["asset_id"])
    assert body["asset_id"] == str(parsed)
    assert body["created_at"]


def test_create_asset_duplicate_symbol_exchange_returns_409(client: TestClient) -> None:
    """Same (symbol, exchange) — even with different case — yields 409, no 2nd insert."""
    payload = {
        "symbol": "FRA7TEST-DUP",
        "name": "Dup One",
        "exchange": "NYSE",
        "asset_type": "stock",
        "currency": "USD",
    }
    first = client.post("/assets", json=payload)
    assert first.status_code == 201, first.text

    # Same pair, different case + surrounding whitespace — must still conflict.
    second = client.post(
        "/assets",
        json={
            "symbol": " fra7test-dup ",
            "name": "Dup Two (different name, should not persist)",
            "exchange": "nyse",
            "asset_type": "stock",
            "currency": "USD",
        },
    )
    assert second.status_code == 409, second.text
    assert "already exists" in second.json()["detail"].lower()

    # Confirm only one row for that (symbol, exchange) survived.
    listed = client.get("/assets", params={"symbol": "FRA7TEST-DUP", "exchange": "NYSE"})
    assert listed.status_code == 200
    page = listed.json()
    assert page["total"] == 1
    assert page["items"][0]["name"] == "Dup One"


def test_create_asset_rejects_missing_fields(client: TestClient) -> None:
    """Pydantic validation surfaces a 422 when required fields are missing."""
    resp = client.post("/assets", json={"symbol": "FRA7TEST-BAD"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /assets
# ---------------------------------------------------------------------------


def test_list_assets_filter_and_pagination(client: TestClient) -> None:
    """Filter by exchange, paginate deterministically, get an accurate total."""
    # Seed three FRA7TEST rows on NASDAQ and one on NYSE.
    for sym, exch in [
        ("FRA7TEST-LIST-A", "NASDAQ"),
        ("FRA7TEST-LIST-B", "NASDAQ"),
        ("FRA7TEST-LIST-C", "NASDAQ"),
        ("FRA7TEST-LIST-D", "NYSE"),
    ]:
        resp = client.post(
            "/assets",
            json={
                "symbol": sym,
                "name": f"Name {sym}",
                "exchange": exch,
                "asset_type": "stock",
                "currency": "USD",
            },
        )
        assert resp.status_code == 201, resp.text

    # Filter by exchange=NASDAQ -> 3 NASDAQ rows, regardless of case.
    nas = client.get("/assets", params={"exchange": "nasdaq"})
    assert nas.status_code == 200
    nas_page = nas.json()
    assert nas_page["total"] == 3
    assert {it["symbol"] for it in nas_page["items"]} == {
        "FRA7TEST-LIST-A",
        "FRA7TEST-LIST-B",
        "FRA7TEST-LIST-C",
    }
    # Ordering must be stable/ascending by symbol.
    assert [it["symbol"] for it in nas_page["items"]] == sorted(
        [it["symbol"] for it in nas_page["items"]]
    )

    # Filter by exact symbol.
    sym_resp = client.get("/assets", params={"symbol": "fra7test-list-d"})
    assert sym_resp.status_code == 200
    sym_page = sym_resp.json()
    assert sym_page["total"] == 1
    assert sym_page["items"][0]["exchange"] == "NYSE"

    # Pagination: limit=2 offset=0 on the NASDAQ set returns 2, total still 3.
    page1 = client.get("/assets", params={"exchange": "NASDAQ", "limit": 2, "offset": 0})
    assert page1.status_code == 200
    p1 = page1.json()
    assert p1["total"] == 3
    assert len(p1["items"]) == 2
    assert [it["symbol"] for it in p1["items"]] == ["FRA7TEST-LIST-A", "FRA7TEST-LIST-B"]

    page2 = client.get("/assets", params={"exchange": "NASDAQ", "limit": 2, "offset": 2})
    assert page2.status_code == 200
    p2 = page2.json()
    assert p2["total"] == 3
    assert len(p2["items"]) == 1
    assert p2["items"][0]["symbol"] == "FRA7TEST-LIST-C"


# ---------------------------------------------------------------------------
# GET /assets/{asset_id}
# ---------------------------------------------------------------------------


def test_get_asset_by_uuid(client: TestClient) -> None:
    """Fetch by the UUID returned at creation time."""
    created = client.post(
        "/assets",
        json={
            "symbol": "FRA7TEST-GET",
            "name": "Get Me",
            "exchange": "NYSE",
            "asset_type": "stock",
            "currency": "USD",
        },
    )
    assert created.status_code == 201, created.text
    asset_id = created.json()["asset_id"]

    fetched = client.get(f"/assets/{asset_id}")
    assert fetched.status_code == 200
    assert fetched.json()["asset_id"] == asset_id
    assert fetched.json()["symbol"] == "FRA7TEST-GET"


def test_get_asset_unknown_uuid_returns_404(client: TestClient) -> None:
    """A random UUID that was never inserted returns 404."""
    unknown = uuid.uuid4()
    resp = client.get(f"/assets/{unknown}")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_get_asset_malformed_uuid_returns_422(client: TestClient) -> None:
    """A non-UUID path segment fails UUID validation with 422, not 404."""
    resp = client.get("/assets/not-a-uuid")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /assets — search filters (FRA-80)
# ---------------------------------------------------------------------------
# Each test seeds its own FRA7TEST rows directly (controlling data_source) and
# pairs the new filter with a name prefix so the assertion is independent of
# any seed rows the host DB may already hold (the exchange=NASDAQ pitfall from
# FRA-61).


def test_list_assets_name_partial_match(client: TestClient, db_session: Session) -> None:
    """``name`` is a case-insensitive partial match (FRA-80)."""
    db_session.add(
        Asset(
            symbol="FRA7TEST-NAME-1",
            exchange="NASDAQ",
            name="Apple Banana Corp",
            asset_type="stock",
            currency="USD",
            data_source="yfinance",
        )
    )
    db_session.add(
        Asset(
            symbol="FRA7TEST-NAME-2",
            exchange="NYSE",
            name="Cherry Durian Inc",
            asset_type="stock",
            currency="USD",
            data_source="yfinance",
        )
    )
    db_session.commit()

    resp = client.get("/assets", params={"name": "banana"})
    assert resp.status_code == 200
    symbols = {it["symbol"] for it in resp.json()["items"]}
    assert "FRA7TEST-NAME-1" in symbols
    assert "FRA7TEST-NAME-2" not in symbols


def test_list_assets_source_filter(client: TestClient, db_session: Session) -> None:
    """``source`` filters by data_source, scoped by a name prefix (FRA-80)."""
    db_session.add(
        Asset(
            symbol="FRA7TEST-SRC-AK",
            exchange="SSE",
            name="FRA7TEST Source A-share",
            asset_type="stock",
            currency="CNY",
            data_source="akshare",
        )
    )
    db_session.add(
        Asset(
            symbol="FRA7TEST-SRC-YF",
            exchange="NASDAQ",
            name="FRA7TEST Source yfinance",
            asset_type="stock",
            currency="USD",
            data_source="yfinance",
        )
    )
    db_session.commit()

    resp = client.get("/assets", params={"source": "akshare", "name": "FRA7TEST Source"})
    assert resp.status_code == 200
    page = resp.json()
    assert page["total"] == 1
    assert page["items"][0]["symbol"] == "FRA7TEST-SRC-AK"


def test_list_assets_exchanges_multi_select(client: TestClient, db_session: Session) -> None:
    """``exchanges`` is a multi-select OR within the set, scoped by name (FRA-80)."""
    for sym, exch, ds in [
        ("FRA7TEST-EX-NA", "NASDAQ", "yfinance"),
        ("FRA7TEST-EX-NY", "NYSE", "yfinance"),
        ("FRA7TEST-EX-SS", "SSE", "akshare"),
    ]:
        db_session.add(
            Asset(
                symbol=sym,
                exchange=exch,
                name=f"FRA7TEST Exch {sym.split('-')[-1]}",
                asset_type="stock",
                currency="USD" if ds == "yfinance" else "CNY",
                data_source=ds,
            )
        )
    db_session.commit()

    resp = client.get("/assets", params={"exchanges": ["NASDAQ", "NYSE"], "name": "FRA7TEST Exch"})
    assert resp.status_code == 200
    page = resp.json()
    assert page["total"] == 2
    assert {it["symbol"] for it in page["items"]} == {"FRA7TEST-EX-NA", "FRA7TEST-EX-NY"}


def test_list_assets_keyword_matches_symbol_or_name(
    client: TestClient, db_session: Session
) -> None:
    """``keyword`` is a case-insensitive partial match on symbol OR name (FRA-80)."""
    db_session.add(
        Asset(
            symbol="FRA7TEST-KW-SYM",
            exchange="NASDAQ",
            name="Generic Name One",
            asset_type="stock",
            currency="USD",
            data_source="yfinance",
        )
    )
    db_session.add(
        Asset(
            symbol="FRA7TEST-KW-XYZ",
            exchange="NYSE",
            name="Distinctive Keyword Co",
            asset_type="stock",
            currency="USD",
            data_source="yfinance",
        )
    )
    db_session.commit()

    by_symbol = client.get("/assets", params={"keyword": "FRA7TEST-KW-SYM"})
    assert by_symbol.status_code == 200
    assert any(it["symbol"] == "FRA7TEST-KW-SYM" for it in by_symbol.json()["items"])

    by_name = client.get("/assets", params={"keyword": "Distinctive Keyword"})
    assert by_name.status_code == 200
    assert any(it["symbol"] == "FRA7TEST-KW-XYZ" for it in by_name.json()["items"])
