"""Sanitizer unit tests (FRA-85) — proves secrets / tracebacks never persist.

Acceptance criterion: "sanitizer 测试证明 token、secret、Authorization、
traceback 不会被持久化".
"""

from __future__ import annotations

from app.services.agent.sanitizer import REDACTED, TRACEBACK_REDACTED, sanitize


def test_api_key_redacted() -> None:
    out = sanitize({"api_key": "sk-abc123", "name": "x"})
    assert out["api_key"] == REDACTED
    assert out["name"] == "x"


def test_nested_token_redacted() -> None:
    out = sanitize({"config": {"access_token": "xyz", "keep": 1}})
    assert out["config"]["access_token"] == REDACTED
    assert out["config"]["keep"] == 1


def test_authorization_header_redacted() -> None:
    out = sanitize({"headers": {"Authorization": "Bearer secret123"}})
    assert out["headers"]["Authorization"] == REDACTED


def test_bearer_in_string_value_keeps_scheme() -> None:
    out = sanitize("token: Bearer abc123def")
    assert out == "token: Bearer [REDACTED]"


def test_traceback_replaced_wholesale() -> None:
    tb = "Traceback (most recent call last):\n  File 'x.py', line 1\nValueError: boom"
    out = sanitize({"error": tb})
    assert out["error"] == TRACEBACK_REDACTED


def test_does_not_mutate_input() -> None:
    original = {"api_key": "sk-xxx", "nested": {"secret": "pw"}}
    sanitize(original)
    assert original == {"api_key": "sk-xxx", "nested": {"secret": "pw"}}


def test_list_recursive() -> None:
    out = sanitize([{"password": "pw1"}, {"ok": 2}])
    assert out[0]["password"] == REDACTED
    assert out[1]["ok"] == 2


def test_various_sensitive_key_spellings() -> None:
    for key in (
        "API_KEY",
        "api-key",
        "apikey",
        "client_secret",
        "passwd",
        "pwd",
        "auth_header",
        "PRIVATE_KEY",
        "credential",
        "access_key",
        "refresh_token",
    ):
        out = sanitize({key: "v"})
        assert out[key] == REDACTED, f"{key!r} not redacted"


def test_non_sensitive_passthrough() -> None:
    data = {"symbol": "AAPL", "price": 150.0, "active": True, "none_val": None}
    assert sanitize(data) == data


def test_deeply_nested_structure() -> None:
    data = {
        "level1": {
            "level2": [
                {"level3": {"api_key": "leaked", "safe": "ok"}},
                {"token": "t", "n": 42},
            ]
        }
    }
    out = sanitize(data)
    assert out["level1"]["level2"][0]["level3"]["api_key"] == REDACTED
    assert out["level1"]["level2"][0]["level3"]["safe"] == "ok"
    assert out["level1"]["level2"][1]["token"] == REDACTED
    assert out["level1"]["level2"][1]["n"] == 42
