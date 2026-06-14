# Tests

Backend pytest test suite for FinResearch Agent.

## Running

```bash
make test
```

This invokes `pytest` via the project's Python toolchain (see `Makefile` and `pyproject.toml`).

## Conventions

- Test files are named `test_<module>.py`, mirroring the module under test (e.g. `test_assets_api.py` covers the assets API router).
- Shared fixtures live in `conftest.py` at this directory root. Add fixtures scoped to a single module via local `conftest.py` files.
- Tests are hermetic: use fixture-provided database sessions / FastAPI `TestClient` rather than hitting real services.
- Mark long-running or integration tests with `@pytest.mark.slow` so they can be excluded from the default CI gate.
