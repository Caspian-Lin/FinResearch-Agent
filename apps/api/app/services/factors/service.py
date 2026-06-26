"""Factor computation service — ohlcv → factors → store (FRA-55).

把「读价格 → 算因子 → 幂等 upsert 进 ``factor_values``」串成服务层,供 API /
worker 调用。复用 FRA-27 price reader(:func:`load_prices`)读 ohlcv → 价格宽表;
复用 FRA-49 / FRA-50 的因子计算函数(momentum / reversal / rsi / MACD / volatility);
以 ``pg_insert`` ``ON CONFLICT`` 幂等 upsert 进 FRA-48 的 ``factor_values``
hypertable(同 asset / factor / time / source 覆盖 ``value``)。

因子 registry:因子名(含参数,如 ``momentum_21``)→ 计算函数。按需单资产 /
批量 universe 计算。

防前视:因子函数均为滚动 / 扩展窗口(FRA-49/50),只用 ≤t 数据;``load_prices``
无 forward-fill。本服务层不引入新的 look-ahead。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.factor import FactorValue
from app.services.backtest.prices import load_prices
from app.services.backtest.types import PriceField
from app.services.factors.momentum import (
    momentum_21,
    momentum_63,
    momentum_126,
    reversal_5,
    reversal_21,
)
from app.services.factors.technical import macd_hist, rsi_14, volatility_20d, volatility_63d

logger = logging.getLogger(__name__)

#: 因子计算函数签名:(prices 宽表) → 因子值宽表(同 index/columns)。
FactorCompute = Callable[[pd.DataFrame], pd.DataFrame]

#: 因子 registry:因子名(含参数)→ 计算函数。覆盖 FRA-49(momentum / reversal)+
#: FRA-50(rsi / MACD / volatility)的默认参数档。调用方按名取用;新增因子在此注册一行。
FACTOR_REGISTRY: dict[str, FactorCompute] = {
    "momentum_21": momentum_21,
    "momentum_63": momentum_63,
    "momentum_126": momentum_126,
    "reversal_5": reversal_5,
    "reversal_21": reversal_21,
    "macd_hist": macd_hist,
    "rsi_14": rsi_14,
    "volatility_20d": volatility_20d,
    "volatility_63d": volatility_63d,
}


def compute_factors(
    prices: pd.DataFrame,
    factor_names: Sequence[str],
) -> dict[str, pd.DataFrame]:
    """对 ``prices`` 宽表计算多个因子,返回 ``{factor_name: 因子宽表}``。

    Args:
        prices: 价格宽表(index = UTC midnight, columns = ``str(asset_id)``)。
        factor_names: 要计算的因子名(必须在 :data:`FACTOR_REGISTRY` 中)。

    Raises:
        ValueError: 未知因子名。
    """
    result: dict[str, pd.DataFrame] = {}
    for name in factor_names:
        fn = FACTOR_REGISTRY.get(name)
        if fn is None:
            raise ValueError(f"unknown factor {name!r}; registered: {sorted(FACTOR_REGISTRY)}")
        result[name] = fn(prices)
    return result


def persist_factor_values(
    db: Session,
    *,
    factor_frames: Mapping[str, pd.DataFrame],
    asset_id_by_col: Mapping[str, uuid.UUID],
    source: str,
) -> int:
    """把因子宽表幂等 upsert 进 ``factor_values``。

    逐 ``(factor_name, time, asset)`` 写一行;NaN cell 跳过(``value`` NOT NULL)。
    冲突键 ``(asset_id, factor_name, time, source)`` 命中时覆盖 ``value`` ——
    重复调用幂等,不产生重复行(验收第 1 条)。

    Args:
        db: 已开启的 SQLAlchemy session(本函数末尾 ``commit``)。
        factor_frames: ``{factor_name: 因子宽表}``(:func:`compute_factors` 输出)。
        asset_id_by_col: ``str(asset_id)`` 列名 → ``UUID`` 映射(来自 load_prices
            的宽表列)。不在映射中的列跳过。
        source: 计算管线标识(写入 ``factor_values.source``,参与 PK)。

    Returns:
        写入(upsert)的行数。
    """
    rows: list[dict[str, Any]] = []
    for factor_name, frame in factor_frames.items():
        for ts, row in frame.iterrows():
            ts_dt = pd.Timestamp(ts).to_pydatetime()  # tz-aware UTC midnight → datetime
            for col, value in row.items():
                if pd.isna(value):
                    continue  # value NOT NULL;NaN 不存
                asset_id = asset_id_by_col.get(str(col))
                if asset_id is None:
                    continue
                rows.append(
                    {
                        "asset_id": asset_id,
                        "factor_name": factor_name,
                        "time": ts_dt,
                        "value": Decimal(str(value)),
                        "source": source,
                    }
                )
    if rows:
        # base / stmt 两变量:base.values() 返回 Insert,base.exposed.value 可用;
        # on_conflict_do_update 返回 ReturningInsert,单独成变量避免 ReturningInsert
        # 赋回 Insert 变量的 mypy 冲突(见 FRA-62 B 类债务)。
        base = pg_insert(FactorValue).values(rows)
        stmt = base.on_conflict_do_update(
            index_elements=["asset_id", "factor_name", "time", "source"],
            set_={"value": base.excluded.value},
        )
        db.execute(stmt)
        db.commit()
    return len(rows)


def compute_and_store_factors(
    db: Session,
    *,
    universe: Sequence[uuid.UUID],
    source: str,
    start: date,
    end: date,
    price_field: PriceField,
    factor_names: Sequence[str],
) -> int:
    """编排:``load_prices`` → ``compute_factors`` → ``persist_factor_values``。

    复用 FRA-27 price reader,不重写价格加载(验收第 2 条)。返回写入行数。
    """
    prices = load_prices(db, universe, source, start, end, price_field)
    asset_id_by_col = {col: uuid.UUID(col) for col in prices.columns}
    factor_frames = compute_factors(prices, factor_names)
    return persist_factor_values(
        db,
        factor_frames=factor_frames,
        asset_id_by_col=asset_id_by_col,
        source=source,
    )


def read_factor_values(
    db: Session,
    *,
    asset_ids: Sequence[uuid.UUID],
    factor_name: str,
    source: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """读回某因子的因子值宽表(index=time, columns=str(asset_id), values=float)。

    供「读回校验一致」(验收第 1 条)与下游消费。无数据时返回空 DataFrame。
    """
    rows = db.execute(
        select(FactorValue.asset_id, FactorValue.time, FactorValue.value).where(
            FactorValue.asset_id.in_(list(asset_ids)),
            FactorValue.factor_name == factor_name,
            FactorValue.source == source,
            FactorValue.time >= _utc_midnight(start),
            FactorValue.time < _utc_midnight(end) + timedelta(days=1),
        )
    ).all()
    if not rows:
        return pd.DataFrame()
    wide = pd.DataFrame(
        [(str(r.asset_id), r.time, float(r.value)) for r in rows],
        columns=["asset_id", "time", "value"],
    )
    return (
        wide.pivot(index="time", columns="asset_id", values="value").sort_index().astype("float64")
    )


def _utc_midnight(d: date) -> datetime:
    """A date as a tz-aware UTC-midnight datetime (matches ``factor_values.time``)."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC)
