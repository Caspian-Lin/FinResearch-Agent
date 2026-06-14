"""Top-level pytest configuration and shared fixtures.

This module is the root conftest for the FinResearch Agent backend test
suite. Week 1 placeholder — no fixtures are implemented yet. As the
backend services land, add shared fixtures here so that every
``test_<module>.py`` can depend on a consistent test database session,
FastAPI ``TestClient``, and seeded reference data.
"""
from __future__ import annotations


# TODO: add fixtures for test DB session (sqlalchemy + pytest fixtures)
# - Spin up a disposable Postgres (or sqlite fallback) schema per test
# - Yield a SQLAlchemy session bound to that schema
# - Tear down schema/table contents after each test


# TODO: add fixtures for FastAPI TestClient
# - Override app dependencies (settings, DB session) with test doubles
# - Yield a TestClient configured against the test app
# - Provide an authenticated client fixture (seeded JWT) for protected routes


pytest_plugins: list[str] = []
