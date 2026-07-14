"""Tool registry — central dispatch for all agent tools (FRA-87).

Mirrors ``TOOL_CATALOG`` in :mod:`app.schemas.agent` but maps to actual
implementations. The registry is populated at import time; tests can override
entries via ``_register``.
"""

from __future__ import annotations

from app.schemas.agent import AGENT_ROLES
from app.services.agent.tools.protocol import AgentTool


class ToolAccessError(ValueError):
    """Raised when a caller attempts to invoke a tool it does not own."""


_REGISTRY: dict[str, AgentTool] = {}


def _register(tool: AgentTool) -> None:
    """Register a tool (called at import time by tool modules)."""
    if tool.name in _REGISTRY:
        raise ValueError(f"duplicate tool registration: {tool.name!r}")
    _REGISTRY[tool.name] = tool


def get_tool(name: str) -> AgentTool:
    """Return the tool registered under *name*.

    Raises :class:`ValueError` for an unknown name so the caller can surface
    it as a validation error rather than a silent miss.
    """
    tool = _REGISTRY.get(name)
    if tool is None:
        raise ValueError(f"unknown tool {name!r}; registered: {sorted(_REGISTRY)}")
    return tool


def validate_caller(tool_name: str, caller_role: str) -> None:
    """Ensure *caller_role* is permitted to invoke *tool_name*.

    Raises :class:`ToolAccessError` if the role is not in the tool's
    ``allowed_callers``. Unregistered tool names raise :class:`ValueError`.
    """
    if caller_role not in AGENT_ROLES:
        raise ToolAccessError(
            f"unknown agent role {caller_role!r}; expected one of {sorted(AGENT_ROLES)}"
        )
    tool = get_tool(tool_name)
    if caller_role not in tool.allowed_callers:
        raise ToolAccessError(
            f"role {caller_role!r} is not permitted to call {tool_name!r}; "
            f"allowed: {sorted(tool.allowed_callers)}"
        )


def registered_tool_names() -> frozenset[str]:
    """Return the set of registered tool names (for contract checks)."""
    return frozenset(_REGISTRY)


# Re-export for convenience.
TOOL_REGISTRY = _REGISTRY
