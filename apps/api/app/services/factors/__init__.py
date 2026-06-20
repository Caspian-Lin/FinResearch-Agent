"""Factor research — contracts + factor computation (FRA-47 / 49 / 51).

Week 3 foundation and factor modules:

* FRA-47 — typed factor data contracts and behaviour protocols.
* FRA-49 — momentum (1M / 3M / 6M) + short-term reversal factors.
* FRA-51 — cross-sectional ranking and normalization
  (rank / z-score / winsorize / quantile buckets).

Technical indicators (FRA-50), IC evaluation (FRA-52), quantile backtesting
(FRA-53) and factor sensitivity (FRA-54) are delivered by later issues. See
``docs/factor-research-methodology.md`` (FRA-59) and
``docs/backtesting-methodology.md`` §接口契约.
"""

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
    QuantileBacktester,
)
from app.services.factors.ranking import (
    cross_sectional_rank,
    quantile_bucket,
    winsorize,
    zscore,
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
    "QuantileBacktester",
    "QuantileResult",
    "cross_sectional_rank",
    "momentum",
    "momentum_126",
    "momentum_21",
    "momentum_63",
    "quantile_bucket",
    "reversal",
    "reversal_21",
    "reversal_5",
    "winsorize",
    "zscore",
]
