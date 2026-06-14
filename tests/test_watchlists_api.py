"""Real tests for the /watchlists API (FRA-10).

Fixtures live in this file only — the shared ``tests/conftest.py`` is left
untouched to avoid merge conflicts with parallel work. Each test cleans up
only the rows it could have created (assets ``symbol LIKE 'FRA10TEST%'``,
users ``email LIKE 'fra10test%'``), so the shared host Postgres stays
pristine.

Cleanup honors the FK graph: ``watchlist_items`` → ``watchlist`` →
``users``/``assets``. ``watchlist_items`` has no ``ON DELETE CASCADE``
(FRA-5), so it is emptied explicitly first.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from app.db.session import SessionLocal, get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

# All rows created by this suite carry these prefixes so cleanup is surgical.
TEST_SYMBOL_PREFIX = "FRA10TEST"


def _cleanup(db: Session) -> None:
    """Delete only rows owned by this test suite, respecting FK order."""
    db.execute(
        text(
            "DELETE FROM watchlist_items "
            "WHERE watchlist_id IN ("
            "  SELECT id FROM watchlist WHERE user_id IN ("
            "    SELECT id FROM users WHERE email LIKE 'fra10test%'"
            "  )"
            ")"
        )
    )
    db.execute(
        text(
            "DELETE FROM watchlist WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'fra10test%')"
        )
    )
    db.execute(text("DELETE FROM assets WHERE symbol LIKE :p"), {"p": f"{TEST_SYMBOL_PREFIX}%"})
    db.execute(text("DELETE FROM users WHERE email LIKE 'fra10test%'"))
    db.commit()


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """Yield a SessionLocal-bound session and clean FRA10TEST rows around it."""
    db = SessionLocal()
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)
        db.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient wired so every request reuses the fixture's session."""

    def _override_get_db() -> Generator[Session, None, None]:
        try:
            yield db_session
        finally:
            # The fixture owns the session lifecycle; do not close here.
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_user(client: TestClient, email: str, password: str = "supersecretpw") -> str:
    """Register a user and return a bearer token via the login flow."""
    reg = client.post("/auth/register", json={"email": email, "password": password})
    assert reg.status_code == 201, reg.text
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_asset(client: TestClient, symbol: str) -> str:
    """Create a FRA10TEST asset and return its UUID."""
    resp = client.post(
        "/assets",
        json={
            "symbol": symbol,
            "name": f"Name {symbol}",
            "exchange": "NASDAQ",
            "asset_type": "stock",
            "currency": "USD",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["asset_id"]


def _create_watchlist(client: TestClient, token: str, name: str) -> str:
    """Create a watchlist as ``token`` and return its UUID."""
    resp = client.post("/watchlists", json={"name": name}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["watchlist_id"]


# ---------------------------------------------------------------------------
# POST /watchlists
# ---------------------------------------------------------------------------


def test_create_watchlist_returns_201(client: TestClient) -> None:
    token = _register_user(client, "fra10test_create@test.com")
    resp = client.post("/watchlists", json={"name": "My Stocks"}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "My Stocks"
    assert body["watchlist_id"]
    uuid.UUID(body["watchlist_id"])  # parseable UUID
    assert body["created_at"]
    assert body["items"] == []


def test_create_watchlist_trims_name(client: TestClient) -> None:
    token = _register_user(client, "fra10test_trim@test.com")
    resp = client.post("/watchlists", json={"name": "   Padded   "}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "Padded"


def test_create_empty_or_whitespace_name_returns_422(client: TestClient) -> None:
    token = _register_user(client, "fra10test_empty@test.com")

    # Truly empty name — schema min_length rejects it.
    empty = client.post("/watchlists", json={"name": ""}, headers=_auth(token))
    assert empty.status_code == 422

    # Whitespace-only name — trimmed to "" by str_strip_whitespace, then min_length fires.
    blank = client.post("/watchlists", json={"name": "    "}, headers=_auth(token))
    assert blank.status_code == 422


def test_create_duplicate_name_same_user_returns_409(client: TestClient) -> None:
    token = _register_user(client, "fra10test_dup@test.com")
    first = client.post("/watchlists", json={"name": "Growth"}, headers=_auth(token))
    assert first.status_code == 201

    second = client.post("/watchlists", json={"name": "Growth"}, headers=_auth(token))
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"].lower()

    # Same name with surrounding whitespace — must still conflict after trim.
    third = client.post("/watchlists", json={"name": "  Growth  "}, headers=_auth(token))
    assert third.status_code == 409


def test_create_duplicate_name_different_users_ok(client: TestClient) -> None:
    """The unique constraint is scoped to (user_id, name): two users may share a name."""
    token_a = _register_user(client, "fra10test_dupa@test.com")
    token_b = _register_user(client, "fra10test_dupb@test.com")
    a = client.post("/watchlists", json={"name": "Shared Name"}, headers=_auth(token_a))
    b = client.post("/watchlists", json={"name": "Shared Name"}, headers=_auth(token_b))
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["watchlist_id"] != b.json()["watchlist_id"]


# ---------------------------------------------------------------------------
# GET /watchlists
# ---------------------------------------------------------------------------


def test_list_returns_only_own_watchlists(client: TestClient) -> None:
    token_a = _register_user(client, "fra10test_lista@test.com")
    token_b = _register_user(client, "fra10test_listb@test.com")

    wl_a = _create_watchlist(client, token_a, "A-only")
    wl_b = _create_watchlist(client, token_b, "B-only")

    # A sees only A-only.
    a_list = client.get("/watchlists", headers=_auth(token_a))
    assert a_list.status_code == 200, a_list.text
    a_ids = {w["watchlist_id"] for w in a_list.json()}
    assert a_ids == {wl_a}
    assert wl_b not in a_ids

    # B sees only B-only.
    b_list = client.get("/watchlists", headers=_auth(token_b))
    assert b_list.status_code == 200
    b_ids = {w["watchlist_id"] for w in b_list.json()}
    assert b_ids == {wl_b}
    assert wl_a not in b_ids


def test_list_returns_empty_for_user_with_none(client: TestClient) -> None:
    token = _register_user(client, "fra10test_emptylist@test.com")
    resp = client.get("/watchlists", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# DELETE /watchlists/{watchlist_id}
# ---------------------------------------------------------------------------


def test_delete_watchlist_cascades_items(client: TestClient, db_session: Session) -> None:
    token = _register_user(client, "fra10test_del@test.com")
    wl_id = _create_watchlist(client, token, "To Delete")
    asset_id = _create_asset(client, "FRA10TEST-DEL1")

    add = client.post(f"/watchlists/{wl_id}/assets/{asset_id}", headers=_auth(token))
    assert add.status_code == 200, add.text
    assert len(add.json()["items"]) == 1

    # Delete the watchlist.
    dele = client.delete(f"/watchlists/{wl_id}", headers=_auth(token))
    assert dele.status_code == 204

    # Items must be gone too (FK has no ON DELETE CASCADE, so the handler deletes them).
    item_count = db_session.execute(
        text("SELECT count(*) FROM watchlist_items WHERE watchlist_id = :wid"),
        {"wid": wl_id},
    ).scalar_one()
    assert item_count == 0

    # And the watchlist itself is no longer listable.
    after = client.get("/watchlists", headers=_auth(token))
    assert after.status_code == 200
    assert all(w["watchlist_id"] != wl_id for w in after.json())


def test_delete_watchlist_not_found_returns_404(client: TestClient) -> None:
    token = _register_user(client, "fra10test_del404@test.com")
    resp = client.delete(f"/watchlists/{uuid.uuid4()}", headers=_auth(token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /watchlists/{watchlist_id}/assets/{asset_id}
# ---------------------------------------------------------------------------


def test_add_asset_to_watchlist(client: TestClient) -> None:
    token = _register_user(client, "fra10test_add@test.com")
    wl_id = _create_watchlist(client, token, "Add List")
    asset_id = _create_asset(client, "FRA10TEST-ADD1")

    resp = client.post(f"/watchlists/{wl_id}/assets/{asset_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["asset_id"] == asset_id
    assert item["symbol"] == "FRA10TEST-ADD1"
    assert item["exchange"] == "NASDAQ"
    assert item["name"] == "Name FRA10TEST-ADD1"
    assert item["added_at"]


def test_add_asset_idempotent(client: TestClient, db_session: Session) -> None:
    token = _register_user(client, "fra10test_idem@test.com")
    wl_id = _create_watchlist(client, token, "Idempotent List")
    asset_id = _create_asset(client, "FRA10TEST-IDEM1")

    first = client.post(f"/watchlists/{wl_id}/assets/{asset_id}", headers=_auth(token))
    assert first.status_code == 200
    assert len(first.json()["items"]) == 1

    # Adding the same asset again must not error and must not duplicate.
    second = client.post(f"/watchlists/{wl_id}/assets/{asset_id}", headers=_auth(token))
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1

    row_count = db_session.execute(
        text("SELECT count(*) FROM watchlist_items WHERE watchlist_id = :wid"),
        {"wid": wl_id},
    ).scalar_one()
    assert row_count == 1


def test_add_nonexistent_asset_returns_404(client: TestClient) -> None:
    token = _register_user(client, "fra10test_add404@test.com")
    wl_id = _create_watchlist(client, token, "No Asset List")
    resp = client.post(f"/watchlists/{wl_id}/assets/{uuid.uuid4()}", headers=_auth(token))
    assert resp.status_code == 404
    assert "asset" in resp.json()["detail"].lower()


def test_add_asset_to_nonexistent_watchlist_returns_404(client: TestClient) -> None:
    token = _register_user(client, "fra10test_addwl404@test.com")
    asset_id = _create_asset(client, "FRA10TEST-NOwl")
    resp = client.post(f"/watchlists/{uuid.uuid4()}/assets/{asset_id}", headers=_auth(token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /watchlists/{watchlist_id}/assets/{asset_id}
# ---------------------------------------------------------------------------


def test_remove_asset_from_watchlist(client: TestClient) -> None:
    token = _register_user(client, "fra10test_rm@test.com")
    wl_id = _create_watchlist(client, token, "Remove List")
    asset_id = _create_asset(client, "FRA10TEST-RM1")

    client.post(f"/watchlists/{wl_id}/assets/{asset_id}", headers=_auth(token))
    dele = client.delete(f"/watchlists/{wl_id}/assets/{asset_id}", headers=_auth(token))
    assert dele.status_code == 204

    after = client.get("/watchlists", headers=_auth(token))
    wl = next(w for w in after.json() if w["watchlist_id"] == wl_id)
    assert wl["items"] == []


def test_remove_asset_idempotent(client: TestClient) -> None:
    """Removing a non-member (never added, or already removed) is a 204 no-op."""
    token = _register_user(client, "fra10test_rmidem@test.com")
    wl_id = _create_watchlist(client, token, "Idempotent Remove")
    asset_id = _create_asset(client, "FRA10TEST-RMIDEM1")

    # Never added.
    first = client.delete(f"/watchlists/{wl_id}/assets/{asset_id}", headers=_auth(token))
    assert first.status_code == 204

    # Add then remove twice.
    client.post(f"/watchlists/{wl_id}/assets/{asset_id}", headers=_auth(token))
    client.delete(f"/watchlists/{wl_id}/assets/{asset_id}", headers=_auth(token))
    second = client.delete(f"/watchlists/{wl_id}/assets/{asset_id}", headers=_auth(token))
    assert second.status_code == 204


# ---------------------------------------------------------------------------
# Cross-user ownership isolation
# ---------------------------------------------------------------------------


def test_cross_user_access_returns_404(client: TestClient) -> None:
    """A user must not read, mutate, or probe another user's watchlist.

    All cross-user access collapses to a uniform 404 — never 403 — so the
    existence of another user's watchlist is not leaked.
    """
    token_a = _register_user(client, "fra10test_xa@test.com")
    token_b = _register_user(client, "fra10test_xb@test.com")

    wl_a = _create_watchlist(client, token_a, "A Private")
    asset_b = _create_asset(client, "FRA10TEST-XB1")

    # B cannot add an asset to A's watchlist.
    add = client.post(f"/watchlists/{wl_a}/assets/{asset_b}", headers=_auth(token_b))
    assert add.status_code == 404

    # B cannot remove an asset from A's watchlist.
    dele = client.delete(f"/watchlists/{wl_a}/assets/{asset_b}", headers=_auth(token_b))
    assert dele.status_code == 404

    # B cannot delete A's watchlist.
    delete_wl = client.delete(f"/watchlists/{wl_a}", headers=_auth(token_b))
    assert delete_wl.status_code == 404

    # And the watchlist still exists for A afterward (B's delete was a no-op).
    a_list = client.get("/watchlists", headers=_auth(token_a))
    assert any(w["watchlist_id"] == wl_a for w in a_list.json())


def test_cross_user_not_distinguished_from_missing(client: TestClient) -> None:
    """404 for another user's watchlist looks identical to a never-existed UUID.

    This is the existence-leak guarantee: the message must not reveal whether
    the id belongs to someone else or simply does not exist.
    """
    token_a = _register_user(client, "fra10test_leaka@test.com")
    token_b = _register_user(client, "fra10test_leakb@test.com")

    wl_a = _create_watchlist(client, token_a, "Leak Test")
    ghost = uuid.uuid4()

    # Both B accessing A's real watchlist and B accessing a ghost return 404
    # with the same generic detail.
    real_resp = client.delete(f"/watchlists/{wl_a}", headers=_auth(token_b))
    ghost_resp = client.delete(f"/watchlists/{ghost}", headers=_auth(token_b))
    assert real_resp.status_code == 404
    assert ghost_resp.status_code == 404
    assert real_resp.json()["detail"] == ghost_resp.json()["detail"]


# ---------------------------------------------------------------------------
# Item hydration
# ---------------------------------------------------------------------------


def test_items_include_asset_details(client: TestClient) -> None:
    token = _register_user(client, "fra10test_details@test.com")
    wl_id = _create_watchlist(client, token, "Details List")
    asset_id_1 = _create_asset(client, "FRA10TEST-DET1")
    asset_id_2 = _create_asset(client, "FRA10TEST-DET2")

    client.post(f"/watchlists/{wl_id}/assets/{asset_id_1}", headers=_auth(token))
    client.post(f"/watchlists/{wl_id}/assets/{asset_id_2}", headers=_auth(token))

    listed = client.get("/watchlists", headers=_auth(token))
    assert listed.status_code == 200
    wl = next(w for w in listed.json() if w["watchlist_id"] == wl_id)
    assert len(wl["items"]) == 2

    by_id = {it["asset_id"]: it for it in wl["items"]}
    assert set(by_id) == {asset_id_1, asset_id_2}
    for item in by_id.values():
        assert item["symbol"].startswith("FRA10TEST-DET")
        assert item["exchange"] == "NASDAQ"
        assert item["name"].startswith("Name FRA10TEST-DET")
        assert item["added_at"]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_unauthenticated_returns_401(client: TestClient) -> None:
    """Every endpoint requires a bearer token — none, no auth, returns 401."""
    assert client.get("/watchlists").status_code == 401
    assert client.post("/watchlists", json={"name": "X"}).status_code == 401
    assert client.delete(f"/watchlists/{uuid.uuid4()}").status_code == 401
    assert client.post(f"/watchlists/{uuid.uuid4()}/assets/{uuid.uuid4()}").status_code == 401
    assert client.delete(f"/watchlists/{uuid.uuid4()}/assets/{uuid.uuid4()}").status_code == 401


def test_malformed_watchlist_uuid_returns_422(client: TestClient) -> None:
    token = _register_user(client, "fra10test_baduuid@test.com")
    resp = client.delete("/watchlists/not-a-uuid", headers=_auth(token))
    assert resp.status_code == 422
