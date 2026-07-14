"""Agent persistence + planning service package (FRA-85, FRA-86).

* :mod:`app.services.agent.sanitizer` — strips secrets from tool-call payloads
  before they reach the database.
* :mod:`app.services.agent.repository` — atomic run/step/tool-call state
  transitions, user-scoped queries, and idempotent side-effect recording.
* :mod:`app.services.agent.planner` — Research Planner: converts a natural-
  language hypothesis into a validated ``ResearchPlan`` (FRA-84 contract).
"""
