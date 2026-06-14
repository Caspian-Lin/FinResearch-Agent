# Notebooks

This directory holds exploratory Jupyter notebooks used during research and prototyping — factor research, sentiment experiments, and ad-hoc data exploration. These notebooks are not part of the production application; they feed insights and validated code back into `apps/` and `packages/`.

## Contents

- `factor_research.ipynb` — momentum / volatility / RSI factor exploration (Week 3).
- `sentiment_experiment.ipynb` — financial text sentiment scoring and signal combination (Week 4).

## Running

Start Jupyter from the repository root so that the project packages are importable:

```bash
jupyter lab
```

Select the `python3` kernel (Python 3.11). Notebooks rely on the project's database session and config — make sure the backend services are running (`docker compose up`) and the relevant environment variables are set before executing cells that query the database.

## Conventions

- File naming: `<YYYY-MM-DD>-<topic>.ipynb` (date prefix is optional for stable notebooks like `factor_research.ipynb`).
- Keep exploratory cells above the fold; move reusable logic into `packages/shared/` once it stabilises.
- Clear all outputs before committing large notebooks to keep diffs reviewable.
- Do not commit credentials, API keys, or large data dumps — load data from the database or from `data/` (gitignored).
