"""Tests for the auth router (FRA-6).

Fixtures are defined locally here (NOT in the shared tests/conftest.py) so we
do not collide with the parallel FRA-7 work. Each test cleans only its own
rows — anything matching ``fra6_%`` — before and after the test runs.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.core.config import settings
from app.db.session import SessionLocal, get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

TEST_EMAIL = "fra6_user@example.com"
TEST_PASSWORD = "supersecretpw"  # 12 chars, satisfies min_length=8


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """Yield a SessionLocal-bound session and clean up fra6_ rows around it."""
    db = SessionLocal()
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)
        db.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with get_db overridden to the test session."""

    def _override_get_db() -> Generator[Session, None, None]:
        try:
            yield db_session
        finally:
            # The dependency normally closes the session; we keep it open for
            # test assertions, so no close here.
            pass

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _cleanup(db: Session) -> None:
    """Delete only rows belonging to these tests (email LIKE 'fra6_%')."""
    db.execute(text("DELETE FROM users WHERE email LIKE 'fra6_%'"))
    db.commit()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_returns_201_and_hashes_password(client: TestClient, db_session: Session) -> None:
    resp = client.post(
        "/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == TEST_EMAIL
    assert body["is_active"] is True
    assert "id" in body
    assert "password" not in body
    assert "hashed_password" not in body

    # Confirm the stored row is hashed, not plaintext.
    row = db_session.execute(
        text("SELECT hashed_password FROM users WHERE email = :e"),
        {"e": TEST_EMAIL},
    ).first()
    assert row is not None
    stored_hash = row[0]
    assert stored_hash != TEST_PASSWORD
    assert stored_hash.startswith("$2")  # bcrypt marker


def test_register_duplicate_email_returns_409(client: TestClient) -> None:
    payload = {"email": "fra6_dup@example.com", "password": TEST_PASSWORD}
    first = client.post("/auth/register", json=payload)
    assert first.status_code == 201
    second = client.post("/auth/register", json=payload)
    assert second.status_code == 409
    assert "already registered" in second.json()["detail"].lower()


def test_register_short_password_rejected(client: TestClient) -> None:
    resp = client.post(
        "/auth/register",
        json={"email": "fra6_short@example.com", "password": "short"},
    )
    assert resp.status_code == 422  # Pydantic validation


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_returns_token(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={"email": "fra6_login@example.com", "password": TEST_PASSWORD},
    )
    resp = client.post(
        "/auth/login",
        json={"email": "fra6_login@example.com", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["access_token"].count(".") == 2  # JWT shape header.payload.sig


def test_login_bad_password_returns_401(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={"email": "fra6_badpw@example.com", "password": TEST_PASSWORD},
    )
    resp = client.post(
        "/auth/login",
        json={"email": "fra6_badpw@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401
    assert "incorrect" in resp.json()["detail"].lower()


def test_login_unknown_email_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/auth/login",
        json={"email": "fra6_ghost@example.com", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Protected /me
# ---------------------------------------------------------------------------


def test_me_with_valid_token_returns_200(client: TestClient) -> None:
    reg = client.post(
        "/auth/register",
        json={"email": "fra6_me@example.com", "password": TEST_PASSWORD},
    )
    assert reg.status_code == 201
    login = client.post(
        "/auth/login",
        json={"email": "fra6_me@example.com", "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == "fra6_me@example.com"
    assert body["is_active"] is True


def test_me_without_token_returns_401(client: TestClient) -> None:
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_with_invalid_token_returns_401(client: TestClient) -> None:
    resp = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer not.a.real.token"},
    )
    assert resp.status_code == 401


def test_me_with_garbage_header_returns_401(client: TestClient) -> None:
    # Wrong scheme
    resp = client.get("/auth/me", headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Email normalization
# ---------------------------------------------------------------------------


def test_register_normalizes_email(client: TestClient) -> None:
    """Mixed-case / padded email must collapse to the lowercased, trimmed form."""
    resp = client.post(
        "/auth/register",
        json={"email": "  FRA6_Norm@Example.COM  ", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == "fra6_norm@example.com"


def test_login_normalizes_email(client: TestClient) -> None:
    """Login must match the normalized stored email even if the caller sends
    mixed case / surrounding whitespace."""
    client.post(
        "/auth/register",
        json={"email": "fra6_loginnorm@example.com", "password": TEST_PASSWORD},
    )
    resp = client.post(
        "/auth/login",
        json={"email": "  FRA6_LoginNorm@EXAMPLE.com ", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["token_type"] == "bearer"


# ---------------------------------------------------------------------------
# Token shape & expiry
# ---------------------------------------------------------------------------


def test_login_token_contains_expires_in(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={"email": "fra6_exp@example.com", "password": TEST_PASSWORD},
    )
    resp = client.post(
        "/auth/login",
        json={"email": "fra6_exp@example.com", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["expires_in"] == settings.jwt_expire_minutes * 60

    decoded = jwt.decode(
        body["access_token"],
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    assert decoded["sub"]
    assert "exp" in decoded
    assert "iat" in decoded


def test_me_with_expired_token_returns_401(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={"email": "fra6_expired@example.com", "password": TEST_PASSWORD},
    )

    # Build a token that already expired a minute ago.
    now = datetime.now(UTC)
    payload = {
        "sub": _get_user_id("fra6_expired@example.com"),
        "iat": now - timedelta(minutes=2),
        "exp": now - timedelta(minutes=1),
    }
    expired = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


def test_me_with_wrong_secret_token_returns_401(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={"email": "fra6_wrongsec@example.com", "password": TEST_PASSWORD},
    )
    now = datetime.now(UTC)
    payload = {
        "sub": _get_user_id("fra6_wrongsec@example.com"),
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    bad = jwt.encode(payload, "a-completely-different-secret", algorithm="HS256")
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {bad}"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Inactive user
# ---------------------------------------------------------------------------


def test_login_inactive_user_returns_401(client: TestClient, db_session: Session) -> None:
    client.post(
        "/auth/register",
        json={"email": "fra6_inactive@example.com", "password": TEST_PASSWORD},
    )
    # Flip the user to inactive directly in the DB.
    db_session.execute(
        text("UPDATE users SET is_active = FALSE WHERE email = :e"),
        {"e": "fra6_inactive@example.com"},
    )
    db_session.commit()

    resp = client.post(
        "/auth/login",
        json={"email": "fra6_inactive@example.com", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 401


def test_me_inactive_user_rejected(client: TestClient, db_session: Session) -> None:
    """A token issued to a user who is later deactivated must stop working."""
    client.post(
        "/auth/register",
        json={"email": "fra6_inactme@example.com", "password": TEST_PASSWORD},
    )
    login = client.post(
        "/auth/login",
        json={"email": "fra6_inactme@example.com", "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    db_session.execute(
        text("UPDATE users SET is_active = FALSE WHERE email = :e"),
        {"e": "fra6_inactme@example.com"},
    )
    db_session.commit()

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_user_id(email: str) -> str:
    """Look up a user id directly via a fresh SessionLocal (for token forging)."""
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT id FROM users WHERE email = :e"),
            {"e": email},
        ).first()
        assert row is not None, f"no user for {email}"
        return str(row[0])
    finally:
        db.close()
