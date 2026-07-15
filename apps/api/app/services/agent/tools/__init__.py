"""Agent tool registry — typed adapters wrapping existing service layer (FRA-87).

Public API:
    AgentTool, ToolResult, ToolError, ToolErrorKind — protocol + envelope types.
    TOOL_REGISTRY, get_tool, validate_caller — registry + access control.
    ResolveAssetsTool, CheckCoverageTool — Data agent tools.
    ComputeFactorTool, EvaluateFactorTool — Factor agent tools.
    RunBacktestTool, ReadBacktestTool — Backtest agent tools.

Design:
    Tools are thin wrappers that call service-layer Python functions directly
    (never via localhost HTTP). Each tool validates input against FRA-84
    allowlists, classifies errors into structured categories, and returns a
    sanitized ``ToolResult`` envelope suitable for the audit log.

Importing this package registers all tools in ``TOOL_REGISTRY``.
"""

from __future__ import annotations

# Import tool modules so their ``_register()`` calls execute at import time.
from app.services.agent.tools import backtest as _backtest_mod  # noqa: F401
from app.services.agent.tools import data as _data_mod  # noqa: F401
from app.services.agent.tools import factor as _factor_mod  # noqa: F401
from app.services.agent.tools.protocol import AgentTool, ToolError, ToolErrorKind, ToolResult
from app.services.agent.tools.registry import TOOL_REGISTRY, get_tool, validate_caller

__all__ = [
    "AgentTool",
    "ToolError",
    "ToolErrorKind",
    "ToolResult",
    "TOOL_REGISTRY",
    "get_tool",
    "validate_caller",
]
