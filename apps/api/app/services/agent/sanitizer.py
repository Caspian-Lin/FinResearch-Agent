"""Secret / traceback sanitizer for agent tool-call payloads (FRA-85).

The repository runs every ``args_json`` / ``result_json`` through
:func:`sanitize` before flushing, so API keys, tokens, ``Authorization``
headers, passwords, and raw Python tracebacks are **never** persisted. This is
the boundary that satisfies the FRA-85 acceptance criterion:

    sanitizer 测试证明 token、secret、Authorization、traceback 不会被持久化

The sanitizer is a pure recursive function: it builds and returns a **new**
object and never mutates the input. Only JSON-serializable shapes
(dict / list / str / numbers / bool / None) are handled — anything arriving
here has already passed Pydantic/JSON serialization.
"""

from __future__ import annotations

import re
from typing import Any

#: Placeholder substituted for any redacted secret value.
REDACTED = "[REDACTED]"

#: Placeholder substituted for an entire raw traceback block.
TRACEBACK_REDACTED = "[REDACTED: traceback]"

# Keys whose values are always redacted (case-insensitive substring match).
# Covers the common spellings: api_key/api-key/apikey, secret, token,
# password/passwd/pwd, authorization/auth-header, bearer, private_key,
# credential, access_key.
_SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|secret|token|password|passwd|pwd|"
    r"authorization|auth[_-]?header|bearer|private[_-]?key|credential|access[_-]?key)",
    re.IGNORECASE,
)

# Raw Python traceback block — replaced wholesale so a full stack trace never
# lands in the audit log.
_TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\):")

# Bearer-token prefix — keep the scheme, redact the credential value.
_BEARER_RE = re.compile(r"(Bearer\s+)(\S+)", re.IGNORECASE)


def sanitize(value: Any) -> Any:
    """Recursively redact secrets and tracebacks from a JSON-serializable value.

    Returns a **new** object; the input is never mutated. Dict keys matching a
    sensitive pattern have their values replaced with :data:`REDACTED`; Bearer
    tokens keep their scheme but lose the credential; any string containing a
    raw traceback block is replaced with :data:`TRACEBACK_REDACTED`.

    Args:
        value: A JSON-serializable structure (dict / list / scalar).

    Returns:
        A sanitized deep copy of *value*.
    """
    if isinstance(value, dict):
        return {k: _sanitize_kv(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return _sanitize_str(value)
    # int / float / bool / None — immutable, return as-is.
    return value


def _sanitize_kv(key: str, val: Any) -> Any:
    """Redact a dict value when its key looks sensitive; recurse otherwise."""
    if _SENSITIVE_KEY_RE.search(key):
        return REDACTED
    return sanitize(val)


def _sanitize_str(text: str) -> str:
    """Redact traceback blocks and Bearer tokens inside a string value."""
    if _TRACEBACK_RE.search(text):
        return TRACEBACK_REDACTED
    return _BEARER_RE.sub(r"\1[REDACTED]", text)
