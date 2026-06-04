"""
Core validation engine for DataGuard.
"""

from __future__ import annotations

import logging
from typing import Any

from dataguard.rules import RuleSet
from dataguard.report import ValidationReport
from dataguard.exceptions import ValidationError
from dataguard.utils import EngineType

logger = logging.getLogger(__name__)

# Engine lookup table — maps engine type to (module_name, validate_func, profile_func)
_ENGINE_REGISTRY: dict[EngineType, tuple[str, str, str]] = {
    EngineType.PANDAS: ("dataguard.pandas_engine", "validate_pandas", "profile_pandas"),
    EngineType.SPARK: ("dataguard.spark_engine", "validate_spark", "profile_spark"),
    EngineType.SQL: ("dataguard.sql_engine", "validate_sql", "profile_sql"),
}


class DataGuard:
    """
    Main entry point for data quality validation.

    Supports Pandas DataFrames, PySpark DataFrames, and SQL databases.

    Example:
        >>> import pandas as pd
        >>> from dataguard import DataGuard, RuleSet, not_null, in_range
        >>> df = pd.DataFrame({"age": [25, 30, -1, None]})
        >>> rules = RuleSet()
        >>> rules.add("age", not_null())
        >>> rules.add("age", in_range(0, 120))
        >>> report = DataGuard(df).validate(rules)
        >>> print(report.summary())
    """

    def __init__(
        self,
        dataframe: Any = None,
        engine: str | None = None,
        sensitive_columns: set[str] | None = None,
        # SQL-specific params (used internally by from_sql)
        _sql_connection: Any = None,
        _sql_table: str | None = None,
        _sql_schema: str | None = None,
        _sql_dialect: str = "mysql",
    ):
        self._sensitive_columns = sensitive_columns or set()

        # SQL mode
        if dataframe is None and _sql_connection is not None:
            self._dataframe = None
            self._engine = _sql_dialect
            self._engine_type = EngineType.SQL
            self._is_sql = True
            self._sql_connection = _sql_connection
            self._sql_table = _sql_table
            self._sql_schema = _sql_schema
            return

        # DataFrame mode
        self._dataframe = dataframe
        detected = self._detect_engine(dataframe, engine)
        self._engine_type = EngineType(detected)
        self._engine = detected
        self._is_sql = False
        self._sql_connection = None
        self._sql_table = None
        self._sql_schema = None

    @classmethod
    def from_sql(
        cls,
        connection: Any,
        table: str,
        dialect: str = "mysql",
        schema: str | None = None,
        sensitive_columns: set[str] | None = None,
    ) -> "DataGuard":
        """Create DataGuard for SQL-based validation.

        Args:
            connection: SQLAlchemy Engine or connection string.
                For security, prefer passing an Engine object or use
                the DQGUARD_DB_URL environment variable instead of
                embedding passwords in code.
            table: Table name to validate.
            dialect: SQL dialect (mysql, hive, flink, doris, selectdb).
            schema: Optional schema/database name.
            sensitive_columns: Set of column names containing PII —
                sample_failures and profile stats will be masked.

        Example:
            >>> guardian = DataGuard.from_sql(
            ...     engine,  # SQLAlchemy Engine object
            ...     table="users",
            ...     dialect="mysql",
            ...     sensitive_columns={"email", "phone"},
            ... )
            >>> report = guardian.validate(rules)
        """
        return cls(
            _sql_connection=connection,
            _sql_table=table,
            _sql_dialect=dialect,
            _sql_schema=schema,
            sensitive_columns=sensitive_columns,
        )

    @staticmethod
    def _detect_engine(dataframe: Any, engine: str | None) -> str:
        if engine is not None:
            if engine not in {"pandas", "spark"}:
                raise ValueError(
                    f"Unsupported engine: '{engine}'. Use 'pandas' or 'spark'."
                )
            return engine

        type_name = type(dataframe).__module__
        if "pandas" in type_name:
            return "pandas"
        elif "pyspark" in type_name or "spark" in type_name:
            return "spark"
        else:
            raise TypeError(
                f"Unsupported dataframe type: {type(dataframe).__name__}. "
                "Expected a Pandas DataFrame or PySpark DataFrame."
            )

    @property
    def engine(self) -> str:
        return self._engine

    @property
    def engine_type(self) -> EngineType:
        return self._engine_type

    def validate(
        self, rules: RuleSet, raise_on_error: bool = False
    ) -> ValidationReport:
        """Run all validation rules against the data source."""
        etype = self._engine_type

        if etype == EngineType.SQL:
            from dataguard.sql_engine import validate_sql

            # Type assertion: for SQL engine, these must be non-None
            assert self._sql_table is not None
            assert self._sql_connection is not None

            results = validate_sql(
                self._sql_connection,
                self._sql_table,
                rules,
                dialect=self._engine,
                schema=self._sql_schema,
                sensitive_columns=self._sensitive_columns,
            )
        elif etype == EngineType.SPARK:
            from dataguard.spark_engine import validate_spark

            results = validate_spark(
                self._dataframe,
                rules,
                sensitive_columns=self._sensitive_columns,
            )
        else:  # EngineType.PANDAS
            from dataguard.pandas_engine import validate_pandas

            results = validate_pandas(
                self._dataframe,
                rules,
                sensitive_columns=self._sensitive_columns,
            )

        report = ValidationReport(results=results, engine=self._engine)

        if raise_on_error and report.failed_count > 0:
            raise ValidationError(report)

        return report

    def profile(self) -> dict[str, dict[str, Any]]:
        """Generate a data profile for all columns."""
        etype = self._engine_type

        if etype == EngineType.SQL:
            from dataguard.sql_engine import profile_sql

            # Type assertion: for SQL engine, these must be non-None
            assert self._sql_table is not None
            assert self._sql_connection is not None

            return profile_sql(
                self._sql_connection,
                self._sql_table,
                dialect=self._engine,
                schema=self._sql_schema,
                sensitive_columns=self._sensitive_columns,
            )
        elif etype == EngineType.SPARK:
            from dataguard.spark_engine import profile_spark

            return profile_spark(
                self._dataframe,
                sensitive_columns=self._sensitive_columns,
            )
        else:  # EngineType.PANDAS
            from dataguard.pandas_engine import profile_pandas

            return profile_pandas(
                self._dataframe,
                sensitive_columns=self._sensitive_columns,
            )
