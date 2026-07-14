"""Factor research — contracts + factor computation + IC + quantile (FRA-47..53).

Week 3 foundation, factor modules, IC evaluation, and stratified backtest:

* FRA-47 — typed factor data contracts and behaviour protocols.
* FRA-49 — momentum (1M / 3M / 6M) + short-term reversal factors.
* FRA-50 — technical indicator factors (RSI / MACD / volatility).
* FRA-51 — cross-sectional ranking and normalization
  (rank / z-score / winsorize / quantile buckets).
* FRA-52 — information coefficient (IC) + IR + t-stat significance.
* FRA-53 — stratified (quantile) backtest framework.

Factor sensitivity (FRA-54) is delivered by a later issue. See
``docs/factor-research-methodology.md`` (FRA-59) and
``docs/backtesting-methodology.md`` §接口契约.
"""

from app.services.factors.evaluation import (
    RankIC,
    evaluate_ic,
    forward_returns,
    ic_series,
    summarize_ic,
)
from app.services.factors.momentum import (
    momentum,
    momentum_21,
    momentum_63,
    momentum_126,
    reversal,
    reversal_5,
    reversal_21,
)
from app.services.factors.protocols import (
    Factor,
    InformationCoefficient,
)
from app.services.factors.quantile import QuantileBacktester
from app.services.factors.ranking import (
    cross_sectional_rank,
    quantile_bucket,
    winsorize,
    zscore,
)
from app.services.factors.technical import (
    MacdResult,
    macd,
    macd_hist,
    rsi,
    rsi_14,
    volatility,
    volatility_20d,
    volatility_63d,
)
from app.services.factors.types import (
    FactorValue,
    ICResult,
    ICSummary,
    QuantileResult,
)

__all__ = [
    "Factor",
    "FactorValue",
    "ICResult",
    "ICSummary",
    "InformationCoefficient",
    "MacdResult",
    "QuantileBacktester",
    "QuantileResult",
    "RankIC",
    "cross_sectional_rank",
    "evaluate_ic",
    "forward_returns",
    "ic_series",
    "macd",
    "macd_hist",
    "momentum",
    "momentum_126",
    "momentum_21",
    "momentum_63",
    "quantile_bucket",
    "reversal",
    "reversal_21",
    "reversal_5",
    "rsi",
    "rsi_14",
    "summarize_ic",
    "volatility",
    "volatility_20d",
    "volatility_63d",
    "winsorize",
    "zscore",
]
