"""ORM metadata tests for factor value storage (FRA-48)."""

from __future__ import annotations

from app.models.factor import FactorValue


def test_factor_value_table_contract() -> None:
    table = FactorValue.__table__

    assert table.name == "factor_values"
    assert [column.name for column in table.primary_key.columns] == [
        "asset_id",
        "factor_name",
        "time",
        "source",
    ]
    assert table.c.asset_id.foreign_keys
    assert table.c.factor_name.type.python_type is str
    assert table.c.source.type.python_type is str
    assert table.c.value.type.precision == 20
    assert table.c.value.type.scale == 8

    index_columns = {
        index.name: [column.name for column in index.columns] for index in table.indexes
    }
    assert index_columns["ix_factor_values_factor_name_time"] == ["factor_name", "time"]
    assert index_columns["ix_factor_values_asset_id_time"] == ["asset_id", "time"]
