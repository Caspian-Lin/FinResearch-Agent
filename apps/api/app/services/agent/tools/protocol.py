"""Protocol + envelope types for the agent tool registry (FRA-87).

Every tool implements :class:`AgentTool` and returns a :class:`ToolResult`.
The envelope separates success data from structured errors so the Orchestrator
can record, retry, or surface them without parsing free-text messages.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy.orm import Session


class ToolErrorKind(StrEnum):
    """Structured error categories for tool failures.

    * ``validation`` — input violates an allowlist or business rule (not retriable).
    * ``not_found`` — referenced asset / run / factor does not exist (not retriable).
    * ``insufficient_data`` — not enough OHLCV / factor data to proceed (not retriable).
    * ``provider`` — upstream data source returned an error (retriable).
    * ``timeout`` — operation exceeded the time budget (retriable).
    * ``internal`` — unexpected service-layer failure (retriable once, then escalate).
    """

    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    INSUFFICIENT_DATA = "insufficient_data"
    PROVIDER = "provider"
    TIMEOUT = "timeout"
    INTERNAL = "internal"


#: Error kinds that are generally safe to retry.
_RETRIABLE_KINDS: frozenset[ToolErrorKind] = frozenset(
    {ToolErrorKind.PROVIDER, ToolErrorKind.TIMEOUT, ToolErrorKind.INTERNAL}
)


@dataclass(frozen=True)
class ToolError:
    """Structured error from a tool execution.

    ``message`` is safe for the audit log — no traceback, ≤500 chars.
    Prefer :meth:`of` as the constructor; it auto-derives ``retriable``
    from ``kind``.
    """

    kind: ToolErrorKind
    message: str
    retriable: bool = False

    @staticmethod
    def of(kind: ToolErrorKind, message: str, *, retriable: bool | None = None) -> ToolError:
        """Create a :class:`ToolError`, auto-deriving ``retriable`` from ``kind``."""
        if len(message) > 500:
            message = message[:497] + "…"
        r = retriable if retriable is not None else kind in _RETRIABLE_KINDS
        return ToolError(kind=kind, message=message, retriable=r)


@dataclass(frozen=True)
class ToolResult:
    """Envelope returned by every tool execution.

    On success: ``success=True``, ``data`` carries the sanitized summary +
    evidence refs, ``error`` is ``None``.
    On failure: ``success=False``, ``data`` is ``None``, ``error`` explains why.

    ``side_effect_ref`` identifies the persisted artifact (e.g.
    ``"backtest_run:<uuid>"``) so the Orchestrator can link evidence.
    """

    tool: str
    success: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    elapsed_ms: int = 0
    tool_version: str = ""
    side_effect_ref: str | None = None

    @staticmethod
    def ok(
        tool: str,
        data: dict[str, Any],
        *,
        elapsed_ms: int = 0,
        tool_version: str = "",
        side_effect_ref: str | None = None,
    ) -> ToolResult:
        return ToolResult(
            tool=tool,
            success=True,
            data=data,
            elapsed_ms=elapsed_ms,
            tool_version=tool_version,
            side_effect_ref=side_effect_ref,
        )

    @staticmethod
    def fail(
        tool: str,
        error: ToolError,
        *,
        elapsed_ms: int = 0,
        tool_version: str = "",
    ) -> ToolResult:
        return ToolResult(
            tool=tool,
            success=False,
            error=error,
            elapsed_ms=elapsed_ms,
            tool_version=tool_version,
        )


class AgentTool(Protocol):
    """Protocol every registered tool satisfies.

    ``execute`` is synchronous (the existing service layer is sync). The
    ``db`` session is provided by the Orchestrator; side-effect tools that
    call functions with internal commits (e.g. ``execute_backtest_run``)
    must flush/commit their own writes before delegating.
    """

    #: Stable name matching the FRA-84 ``TOOL_CATALOG`` key.
    name: str
    #: Which agent role owns this tool.
    role: str
    #: Bumped on breaking interface changes; recorded in provenance.
    version: str
    #: Roles permitted to call this tool (subset of ``AGENT_ROLES``).
    allowed_callers: frozenset[str]
    #: Whether execution writes the DB or calls an external service.
    has_side_effects: bool
    #: Whether repeating the call with identical params is safe.
    idempotent: bool
    #: Soft timeout hint for the Orchestrator (seconds).
    timeout_seconds: int

    def execute(self, params: dict[str, Any], *, db: Session) -> ToolResult:
        """Run the tool; never raises — failures are returned as ``ToolResult.fail``."""
        ...


def run_tool_safely(tool_name: str, tool_version: str, fn: Any) -> ToolResult:
    """Execute *fn* (a zero-arg callable) and wrap the result in ``ToolResult``.

    *fn* should return ``ToolResult.ok(...)`` or ``ToolResult.fail(...)`` on its
    own. If it raises, the exception is classified into a safe
    :class:`ToolError` — the traceback goes only to the log, never to the result.
    """
    start = time.monotonic()
    try:
        result: ToolResult = fn()
        # Patch elapsed if the inner function didn't set it.
        if result.elapsed_ms == 0:
            result = ToolResult(
                tool=result.tool,
                success=result.success,
                data=result.data,
                error=result.error,
                elapsed_ms=int((time.monotonic() - start) * 1000),
                tool_version=result.tool_version or tool_version,
                side_effect_ref=result.side_effect_ref,
            )
        return result
    except Exception as exc:  # noqa: BLE001 — classify + log, never re-raise
        import logging

        logging.getLogger(__name__).exception("tool %s failed", tool_name)
        elapsed = int((time.monotonic() - start) * 1000)
        kind = _classify_exception(exc)
        return ToolResult.fail(
            tool_name,
            ToolError.of(kind, f"{type(exc).__name__}: {exc!s}"),
            elapsed_ms=elapsed,
            tool_version=tool_version,
        )


def _classify_exception(exc: Exception) -> ToolErrorKind:
    """Map a service-layer exception to a :class:`ToolErrorKind`."""
    msg = str(exc).lower()
    if "not found" in msg or "does not exist" in msg or "not in" in msg:
        return ToolErrorKind.NOT_FOUND
    if "insufficient" in msg or "no usable" in msg or "empty" in msg:
        return ToolErrorKind.INSUFFICIENT_DATA
    if "timeout" in msg or "timed out" in msg:
        return ToolErrorKind.TIMEOUT
    if "connection" in msg or "provider" in msg:
        return ToolErrorKind.PROVIDER
    return ToolErrorKind.INTERNAL
