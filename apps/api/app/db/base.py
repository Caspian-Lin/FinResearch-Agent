"""Declarative base class for all ORM models.

Models defined in `app/models/` should inherit from `Base` so that
Alembic autogenerate can detect them.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-wide declarative base."""
