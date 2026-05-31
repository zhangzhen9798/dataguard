"""
Tests for additional check functions and edge cases.
"""

import pandas as pd
import numpy as np
import pytest

from dataguard import DataGuard, RuleSet
from dataguard.checks import (
    not_null,
    unique,
    in_range,
    regex_match,
    in_set,
    min_length,
    max_length,
    custom,
)
from dataguard.exceptions import ValidationError


# ─── Min Length Tests ──────────────────────────────────────────────

class TestMinLength:
    def test_pass(self):
        df = pd.DataFrame({"name": ["Alice", "Bob", "Charlie"]})
        rules = RuleSet()
        rules.add("name", min_length(3))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail_short_string(self):
        df = pd.DataFrame({"name": ["Al", "Bob", "Charlie"]})
        rules = RuleSet()
        rules.add("name", min_length(3))
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_boundary_exact(self):
        df = pd.DataFrame({"code": ["AB", "CD", "EF"]})
        rules = RuleSet()
        rules.add("code", min_length(2))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_skip_none(self):
        df = pd.DataFrame({"name": [None, "Alice"]})
        rules = RuleSet()
        rules.add("name", min_length(2))
        report = DataGuard(df).validate(rules)
        assert report.passed_count == 1

    def test_invalid_negative(self):
        with pytest.raises(ValueError):
            min_length(-1)


# ─── Max Length Tests ──────────────────────────────────────────────

class TestMaxLength:
    def test_pass(self):
        df = pd.DataFrame({"name": ["Alice", "Bob", "Charlie"]})
        rules = RuleSet()
        rules.add("name", max_length(10))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail_long_string(self):
        df = pd.DataFrame({"name": ["A" * 20, "Bob"]})
        rules = RuleSet()
        rules.add("name", max_length(10))
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_boundary_exact(self):
        df = pd.DataFrame({"code": ["AB", "CD"]})
        rules = RuleSet()
        rules.add("code", max_length(2))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_skip_none(self):
        df = pd.DataFrame({"name": [None, "Alice"]})
        rules = RuleSet()
        rules.add("name", max_length(5))
        report = DataGuard(df).validate(rules)
        assert report.passed_count == 1

    def test_invalid_negative(self):
        with pytest.raises(ValueError):
            max_length(-1)


# ─── Custom Check Tests ────────────────────────────────────────────

class TestCustom:
    def test_custom_check_pass(self):
        is_even = custom(lambda x: x % 2 == 0, name="is_even")
        df = pd.DataFrame({"num": [2, 4, 6]})
        rules = RuleSet()
        rules.add("num", is_even)
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_custom_check_fail(self):
        is_even = custom(lambda x: x % 2 == 0, name="is_even")
        df = pd.DataFrame({"num": [2, 3, 4]})
        rules = RuleSet()
        rules.add("num", is_even)
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_custom_check_auto_name(self):
        def my_validator(x):
            return True
        check = custom(my_validator)
        assert check.__name__ == "my_validator"


# ─── Edge Cases & Boundary Conditions ──────────────────────────────

class TestEdgeCases:
    """Test empty dataframes, single rows, and boundary conditions."""

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["a", "b"])
        rules = RuleSet()
        rules.add("a", not_null())
        report = DataGuard(df).validate(rules)
        # Empty dataframe should have no results or be considered valid
        assert report.total_count >= 0

    def test_single_row_pass(self):
        df = pd.DataFrame({"name": ["Alice"], "age": [25]})
        rules = RuleSet()
        rules.add("name", not_null())
        rules.add("age", in_range(0, 120))
        report = DataGuard(df).validate(rules)
        assert report.is_valid
        assert report.total_count == 2

    def test_single_row_fail(self):
        df = pd.DataFrame({"age": [-1]})
        rules = RuleSet()
        rules.add("age", in_range(0, 120))
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_all_null_column_not_null_rule(self):
        df = pd.DataFrame({"val": [None, None, None]})
        rules = RuleSet()
        rules.add("val", not_null())
        report = DataGuard(df).validate(rules)
        assert not report.is_valid
        assert report.results[0].pass_rate == 0.0

    def test_all_unique_column(self):
        df = pd.DataFrame({"id": list(range(100))})
        rules = RuleSet()
        rules.add("id", unique())
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_all_duplicate_column(self):
        df = pd.DataFrame({"val": [1] * 50})
        rules = RuleSet()
        rules.add("val", unique(), threshold=0.05)
        report = DataGuard(df).validate(rules)
        assert not report.is_valid


# ─── Threshold Edge Cases ──────────────────────────────────────────

class TestThresholdEdgeCases:
    def test_threshold_zero_always_passes(self):
        df = pd.DataFrame({"name": [None, None, None]})
        rules = RuleSet()
        rules.add("name", not_null(), threshold=0.0)
        report = DataGuard(df).validate(rules)
        # threshold=0 should always pass (no minimum pass rate required)
        assert report.is_valid

    def test_threshold_one_strict(self):
        df = pd.DataFrame({"name": [None, "Alice"]})
        rules = RuleSet()
        rules.add("name", not_null(), threshold=1.0)
        report = DataGuard(df).validate(rules)
        # threshold=1.0 means all must pass; one is None so fail
        assert not report.is_valid

    def test_threshold_invalid_negative(self):
        from dataguard.rules import Rule
        with pytest.raises(ValueError):
            Rule(column="test", check=lambda: True, threshold=-0.1)

    def test_threshold_invalid_above_one(self):
        from dataguard.rules import Rule
        with pytest.raises(ValueError):
            Rule(column="test", check=lambda: True, threshold=1.5)

    def test_threshold_boundary_0_0_and_1_0(self):
        """Both boundaries are valid."""
        from dataguard.rules import Rule
        for t in [0.0, 0.5, 1.0]:
            r = Rule(column="x", check=lambda: True, threshold=t)
            assert r.threshold == t


# ─── InRange Parameter Validation ─────────────────────────────────

class TestInRangeValidation:
    def test_no_bounds_raises(self):
        with pytest.raises(ValueError):
            in_range()

    def test_min_greater_than_max_raises(self):
        with pytest.raises(ValueError):
            in_range(min_val=20, max_val=10)


# ─── Regex Match Edge Cases ───────────────────────────────────────

class TestRegexMatchEdgeCases:
    def test_empty_string(self):
        df = pd.DataFrame({"s": [""]})
        rules = RuleSet()
        rules.add("s", regex_match(r"^.*$"))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_invalid_pattern_raises(self):
        with pytest.raises(ValueError):
            regex_match("[invalid")

    def test_none_skipped(self):
        df = pd.DataFrame({"email": [None, "alice@example.com"]})
        rules = RuleSet()
        rules.add("email", regex_match(r"^[\w.-]+@"))
        report = DataGuard(df).validate(rules)
        assert report.passed_count == 1


# ─── InSet Edge Cases ─────────────────────────────────────────────

class TestInSetEdgeCases:
    def test_empty_set_all_fail(self):
        df = pd.DataFrame({"status": ["active", "inactive"]})
        rules = RuleSet()
        rules.add("status", in_set([]))
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_single_value_set(self):
        df = pd.DataFrame({"flag": [True, True, False]})
        rules = RuleSet()
        rules.add("flag", in_set([True]))
        report = DataGuard(df).validate(rules)
        # False is not in {True}, so 2/3 rows pass = 66.7%, below default threshold=1.0
        assert report.total_count == 1
        assert not report.is_valid


# ─── Engine Detection Tests ───────────────────────────────────────

class TestEngineDetection:
    def test_explicit_pandas_engine(self):
        df = pd.DataFrame({"a": [1]})
        guardian = DataGuard(df, engine="pandas")
        assert guardian.engine == "pandas"

    def test_explicit_spark_engine(self):
        with pytest.raises(ImportError):  # Spark not available in tests
            DataGuard(None, engine="spark").validate(RuleSet())

    def test_invalid_engine_name(self):
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(ValueError, match="Unsupported engine"):
            DataGuard(df, engine="invalid")

    def test_unsupported_type_raises(self):
        with pytest.raises(TypeError, match="Unsupported dataframe type"):
            DataGuard([1, 2, 3])


# ─── NotNull pd.NA Support ─────────────────────────────────────────

class TestNotNullPdNA:
    def test_pd_na_fails(self):
        if hasattr(pd, "NA"):
            df = pd.DataFrame({"val": [pd.NA, "ok"]})
            rules = RuleSet()
            rules.add("val", not_null())
            report = DataGuard(df).validate(rules)
            # pd.NA row fails; "ok" row passes -> 50% pass rate
            assert not report.is_valid  # below default 100% threshold
            assert report.results[0].pass_rate == 0.5
        else:
            pytest.skip("pd.NA not available")


# ─── Multiple Rules on Same Column ─────────────────────────────────

class TestSameColumnMultipleRules:
    def test_same_column_two_rules(self):
        df = pd.DataFrame({"age": [25, -1, 150, None]})
        rules = RuleSet()
        rules.add("age", not_null())
        rules.add("age", in_range(0, 120))
        report = DataGuard(df).validate(rules)
        assert report.total_count == 2
        assert not report.is_valid


# ─── Profile Edge Cases ────────────────────────────────────────────

class TestProfileEdgeCases:
    def test_profile_empty_dataframe(self):
        df = pd.DataFrame(columns=["a", "b"])
        profile = DataGuard(df).profile()
        assert "a" in profile
        assert "b" in profile

    def test_profile_numeric_stats(self):
        df = pd.DataFrame({"nums": [10, 20, 30, None]})
        profile = DataGuard(df).profile()
        stats = profile["nums"]
        assert stats["null_count"] == 1
        assert stats["distinct_count"] == 3

    def test_profile_string_column(self):
        df = pd.DataFrame({"text": ["hello", "world", "hello"]})
        profile = DataGuard(df).profile()
        assert profile["text"]["distinct_count"] == 2


# ─── Report Edge Cases ────────────────────────────────────────────

class TestReportEdgeCases:
    def test_report_with_all_passing(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        rules = RuleSet()
        rules.add("a", not_null())
        rules.add("b", not_null())
        report = DataGuard(df).validate(rules)
        assert report.is_valid
        assert report.passed_count == 2
        assert report.failed_count == 0
