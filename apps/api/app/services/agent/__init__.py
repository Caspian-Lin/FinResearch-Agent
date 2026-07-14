"""Agent persistence service package (FRA-85).

* :mod:`app.services.agent.sanitizer` — strips secrets from tool-call payloads
  before they reach the database.
* :mod:`app.services.agent.repository` — atomic run/step/tool-call state
  transitions, user-scoped queries, and idempotent side-effect recording.
"""
