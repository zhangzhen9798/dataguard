"""
Core validation engine for DataGuard.
"""

from typing import Any, Dict, List, Optional, Union
from dataguard.rules import RuleSet
from dataguard.report import ValidationReport, ValidationResult


class DataGuard:
    """
    Main entry point for data quality validation.

    Supports both Pandas DataFrames and PySpark DataFrames.

    Example:
        >>> import pandas as pd
        >>> from dataguard import DataGuard, RuleSet, not_null, in_range
        >>> df = pd.DataFrame({"age": [25, 30, -1, None], "name": ["Alice", "Bob", "Charlie", "Dana"]})
        >>> rules = RuleSet()
        >>> rules.add("age", not_null())
        >>> rules.add("age", in_range(0, 120))
        >>> guardian = DataGuard(df)
        >>> report = guardian.validate(rules)
        >>> print(report.summary())
    """

    def __init__(self, dataframe: Any, engine: Optional[str] = None):
        """
        Initialize DataGuard with a DataFrame.

        Args:
            dataframe: A Pandas DataFrame or PySpark DataFrame.
            engine: Force engine type ('pandas' or 'spark'). Auto-detected if None.
        """
        self._dataframe = dataframe
        self._engine = self._detect_engine(dataframe, engine)

    @staticmethod
    def _detect_engine(dataframe: Any, engine: Optional[str]) -> str:
        """Detect whether to use Pandas or Spark engine."""
        if engine is not None:
            if engine not in ("pandas", "spark"):
                raise ValueError(f"Unsupported engine: {engine}. Use 'pandas' or 'spark'.")
            return engine

        type_name = type(dataframe).__module__
        if "pandas" in type_name:
            return "pandas"
        elif "pyspark" in type_name or "spark" in type_name:
            return "spark"
        else:
            # Default to pandas
            return "pandas"

    @property
    def engine(self) -> str:
        """Return the active engine type."""
        return self._engine

    def validate(self, rules: RuleSet, raise_on_error: bool = False) -> ValidationReport:
        """
        Run all validation rules against the DataFrame.

        Args:
            rules: A RuleSet containing validation rules.
            raise_on_error: If True, raise ValidationError when any rule fails.

        Returns:
            ValidationReport with detailed results for each rule.
        """
        if self._engine == "spark":
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
        """
        Generate a data profile for all columns.

        Returns basic statistics: null count, distinct count, min, max, etc.
        """
        if self._engine == "spark":
            from dataguard.spark_engine import profile_spark
            return profile_spark(self._dataframe)
        else:
            from dataguard.pandas_engine import profile_pandas
            return profile_pandas(self._dataframe)
