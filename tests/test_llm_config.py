"""Tests for user-scoped LLM config: crypto, resolver, API (FRA-93)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from app.core.crypto import decrypt_api_key, encrypt_api_key, mask_api_key
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.user import User
from app.models.user_llm_config import UserLLMConfig
from app.services.llm_config import resolve_llm_config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

PREFIX = "FRA93TEST"


# ─── DB helpers ──────────────────────────────────────────────────────────────


def _cleanup(db: Session) -> None:
    p = f"{PREFIX}%"
    db.execute(
        text(
            "DELETE FROM user_llm_configs WHERE user_id IN (SELECT id FROM users WHERE email ILIKE :p)"
        ),
        {"p": p},
    )
    db.execute(text("DELETE FROM users WHERE email ILIKE :p"), {"p": p})
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


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _register(client: TestClient, suffix: str = "") -> tuple[str, uuid.UUID]:
    email = f"{PREFIX.lower()}{suffix}@test.com"
    res = client.post("/auth/register", json={"email": email, "password": "Test1234!"})
    assert res.status_code == 201, res.text
    user_id = uuid.UUID(res.json()["id"])
    token = client.post("/auth/login", json={"email": email, "password": "Test1234!"}).json()[
        "access_token"
    ]
    return token, user_id


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ─── Crypto ─────────────────────────────────────────────────────────────────


class TestCrypto:
    def test_encrypt_decrypt_roundtrip(self):
        plaintext = "sk-test-key-12345"
        token = encrypt_api_key(plaintext)
        assert token != plaintext
        assert decrypt_api_key(token) == plaintext

    def test_encrypt_produces_different_tokens(self):
        plaintext = "sk-same-key"
        t1 = encrypt_api_key(plaintext)
        t2 = encrypt_api_key(plaintext)
        assert t1 != t2
        assert decrypt_api_key(t1) == plaintext
        assert decrypt_api_key(t2) == plaintext

    def test_mask_api_key(self):
        assert mask_api_key("sk-abcd1234") == "••••••••1234"
        assert mask_api_key("ab") == ""
        assert mask_api_key("") == ""


# ─── Resolver ───────────────────────────────────────────────────────────────


class TestResolveLLMConfig:
    def test_no_user_config_returns_global_defaults(self, db_session: Session):
        user = User(
            id=(user_id := uuid.uuid4()),
            email=f"{PREFIX.lower()}resolv1@test.com",
            hashed_password="x",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        config = resolve_llm_config(user_id, db_session)
        assert config.provider == "fixture"

    def test_user_config_overrides_global(self, db_session: Session):
        user = User(
            id=(user_id := uuid.uuid4()),
            email=f"{PREFIX.lower()}resolv2@test.com",
            hashed_password="x",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        row = UserLLMConfig(
            user_id=user_id,
            provider="openai",
            encrypted_api_key=encrypt_api_key("sk-user-key"),
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
            temperature=0.3,
        )
        db_session.add(row)
        db_session.flush()

        config = resolve_llm_config(user_id, db_session)
        assert config.provider == "openai"
        assert config.api_key == "sk-user-key"
        assert config.base_url == "https://api.deepseek.com/v1"
        assert config.model == "deepseek-chat"
        assert config.temperature == 0.3

    def test_partial_user_config_falls_back(self, db_session: Session):
        user = User(
            id=(user_id := uuid.uuid4()),
            email=f"{PREFIX.lower()}resolv3@test.com",
            hashed_password="x",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        row = UserLLMConfig(
            user_id=user_id,
            provider="openai",
            encrypted_api_key=None,
            base_url=None,
            model="gpt-4o",
            temperature=None,
        )
        db_session.add(row)
        db_session.flush()

        config = resolve_llm_config(user_id, db_session)
        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert config.base_url != ""


# ─── API ────────────────────────────────────────────────────────────────────


class TestLLMConfigAPI:
    def test_get_empty_config(self, client: TestClient):
        token, _ = _register(client, "get")
        res = client.get("/settings/llm", headers=_auth_headers(token))
        assert res.status_code == 200
        data = res.json()
        assert data["provider"] == "fixture"
        assert data["has_api_key"] is False
        assert data["api_key_last4"] is None

    def test_put_then_get(self, client: TestClient):
        token, _ = _register(client, "put")
        res = client.put(
            "/settings/llm",
            headers=_auth_headers(token),
            json={
                "provider": "openai",
                "api_key": "sk-test-12345678",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "temperature": 0.1,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["provider"] == "openai"
        assert data["has_api_key"] is True
        assert data["model"] == "gpt-4o-mini"
        assert data["temperature"] == 0.1

        res2 = client.get("/settings/llm", headers=_auth_headers(token))
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["provider"] == "openai"
        assert data2["has_api_key"] is True

    def test_put_empty_api_key_keeps_existing(self, client: TestClient):
        token, _ = _register(client, "keep")
        client.put(
            "/settings/llm",
            headers=_auth_headers(token),
            json={"provider": "openai", "api_key": "sk-secret-key-9999"},
        )
        res = client.put(
            "/settings/llm",
            headers=_auth_headers(token),
            json={"provider": "openai", "model": "gpt-4o"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["has_api_key"] is True
        assert data["model"] == "gpt-4o"

    def test_never_returns_api_key_plaintext(self, client: TestClient):
        token, _ = _register(client, "mask")
        client.put(
            "/settings/llm",
            headers=_auth_headers(token),
            json={"provider": "openai", "api_key": "sk-never-expose-me"},
        )
        res = client.get("/settings/llm", headers=_auth_headers(token))
        body = res.text
        assert "sk-never-expose-me" not in body

    def test_temperature_validation(self, client: TestClient):
        token, _ = _register(client, "temp")
        res = client.put(
            "/settings/llm",
            headers=_auth_headers(token),
            json={"temperature": 3.0},
        )
        assert res.status_code == 422

    def test_cross_user_isolation(self, client: TestClient):
        token_a, _ = _register(client, "userA")
        token_b, _ = _register(client, "userB")

        client.put(
            "/settings/llm",
            headers=_auth_headers(token_a),
            json={"provider": "openai", "api_key": "sk-user-a-key"},
        )

        # User B reads their own config — should NOT see A's key
        res_b = client.get("/settings/llm", headers=_auth_headers(token_b))
        assert res_b.status_code == 200
        assert res_b.json()["has_api_key"] is False
        assert "sk-user-a-key" not in res_b.text

    def test_unauthenticated_blocked(self, client: TestClient):
        res = client.get("/settings/llm")
        assert res.status_code == 401
