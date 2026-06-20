"""Factor research — interface contracts (FRA-47).

Week 3 foundation: typed factor data contracts and behaviour protocols. Factor
computation (momentum / technical indicators), cross-sectional ranking,
IC evaluation, and quantile backtesting are delivered by later issues
(FRA-49..54); this package only locks the contracts those issues code against.
See ``docs/factor-research-methodology.md`` (FRA-59) and
``docs/backtesting-methodology.md`` §接口契约.
"""

from app.services.factors.protocols import (
    Factor,
    InformationCoefficient,
    QuantileBacktester,
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
]
