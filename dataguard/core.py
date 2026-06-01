"""
Core validation engine for DataGuard.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Union

from dataguard.rules import RuleSet
from dataguard.report import ValidationReport, ValidationResult
from dataguard.exceptions import ValidationError

logger = logging.getLogger(__name__)


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
        engine: Optional[str] = None,
        sensitive_columns: Optional[Set[str]] = None,
        # SQL-specific params (used internally by from_sql)
        _sql_connection: Any = None,
        _sql_table: Optional[str] = None,
        _sql_schema: Optional[str] = None,
        _sql_dialect: str = "mysql",
    ):
        self._sensitive_columns = sensitive_columns or set()

        # SQL mode
        if dataframe is None and _sql_connection is not None:
            self._dataframe = None
            self._engine = _sql_dialect
            self._is_sql = True
            self._sql_connection = _sql_connection
            self._sql_table = _sql_table
            self._sql_schema = _sql_schema
            return

        # DataFrame mode
        self._dataframe = dataframe
        self._engine = self._detect_engine(dataframe, engine)
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
        schema: Optional[str] = None,
        sensitive_columns: Optional[Set[str]] = None,
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
    def _detect_engine(dataframe: Any, engine: Optional[str]) -> str:
        if engine is not None:
            if engine not in ("pandas", "spark"):
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

    def validate(self, rules: RuleSet, raise_on_error: bool = False) -> ValidationReport:
        """Run all validation rules against the data source."""
        if self._is_sql:
            from dataguard.sql_engine import validate_sql
            results = validate_sql(
                self._sql_connection, self._sql_table, rules,
                dialect=self._engine, schema=self._sql_schema,
                sensitive_columns=self._sensitive_columns,
            )
        elif self._engine == "spark":
            from dataguard.spark_engine import validate_spark
            results = validate_spark(
                self._dataframe, rules,
                sensitive_columns=self._sensitive_columns,
            )
        else:
            from dataguard.pandas_engine import validate_pandas
            results = validate_pandas(
                self._dataframe, rules,
                sensitive_columns=self._sensitive_columns,
            )

        report = ValidationReport(results=results, engine=self._engine)

        if raise_on_error and report.failed_count > 0:
            raise ValidationError(report)

        return report

    def profile(self) -> Dict[str, Dict[str, Any]]:
        """Generate a data profile for all columns."""
        if self._is_sql:
            from dataguard.sql_engine import profile_sql
            return profile_sql(
                self._sql_connection, self._sql_table,
                dialect=self._engine, schema=self._sql_schema,
                sensitive_columns=self._sensitive_columns,
            )
        elif self._engine == "spark":
            from dataguard.spark_engine import profile_spark
            return profile_spark(
                self._dataframe,
                sensitive_columns=self._sensitive_columns,
            )
        else:
            from dataguard.pandas_engine import profile_pandas
            return profile_pandas(
                self._dataframe,
                sensitive_columns=self._sensitive_columns,
            )
