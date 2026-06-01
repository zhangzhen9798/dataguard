"""
Core validation engine for DataGuard.
"""

from typing import Any, Dict, List, Optional, Union
from dataguard.rules import RuleSet
from dataguard.report import ValidationReport, ValidationResult


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

    def __init__(self, dataframe: Any, engine: Optional[str] = None):
        self._dataframe = dataframe
        self._engine = self._detect_engine(dataframe, engine)
        self._is_sql = False

    @classmethod
    def from_sql(
        cls,
        connection: Any,
        table: str,
        dialect: str = "mysql",
        schema: Optional[str] = None,
    ) -> "DataGuard":
        """Create DataGuard for SQL-based validation.

        Args:
            connection: SQLAlchemy Engine or connection string.
            table: Table name to validate.
            dialect: SQL dialect (mysql, hive, flink, doris, selectdb).
            schema: Optional schema/database name.

        Example:
            >>> guardian = DataGuard.from_sql(
            ...     "mysql://user:pass@localhost/mydb",
            ...     table="users",
            ...     dialect="mysql",
            ... )
            >>> report = guardian.validate(rules)
        """
        instance = cls.__new__(cls)
        instance._dataframe = None
        instance._engine = dialect
        instance._is_sql = True
        instance._sql_connection = connection
        instance._sql_table = table
        instance._sql_schema = schema
        return instance

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
            )
        elif self._engine == "spark":
            from dataguard.spark_engine import validate_spark
            results = validate_spark(self._dataframe, rules)
        else:
            from dataguard.pandas_engine import validate_pandas
            results = validate_pandas(self._dataframe, rules)

        report = ValidationReport(results=results, engine=self._engine)

        if raise_on_error and report.failed_count > 0:
            from dataguard.exceptions import ValidationError
            raise ValidationError(report)

        return report

    def profile(self) -> Dict[str, Dict[str, Any]]:
        """Generate a data profile for all columns."""
        if self._is_sql:
            from dataguard.sql_engine import profile_sql
            return profile_sql(
                self._sql_connection, self._sql_table,
                dialect=self._engine, schema=self._sql_schema,
            )
        elif self._engine == "spark":
            from dataguard.spark_engine import profile_spark
            return profile_spark(self._dataframe)
        else:
            from dataguard.pandas_engine import profile_pandas
            return profile_pandas(self._dataframe)
