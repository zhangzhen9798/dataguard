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
    is_numeric,
    is_email,
    is_date,
    not_empty_string,
    max_value,
    min_value,
    custom,
)
from dataguard.exceptions import ValidationError


# ─── Min Length Tests ──────────────────────────────────────

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


# ─── Max Length Tests ──────────────────────────────────────

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


# ─── IsNumeric Tests ──────────────────────────────────────

class TestIsNumeric:
    def test_pass_int(self):
        df = pd.DataFrame({"val": [1, 2, 3]})
        rules = RuleSet()
        rules.add("val", is_numeric())
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_pass_float(self):
        df = pd.DataFrame({"val": [1.5, -2.3, 0.0]})
        rules = RuleSet()
        rules.add("val", is_numeric())
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_pass_negative_zero(self):
        df = pd.DataFrame({"val": [0, -0.0, 3.14]})
        rules = RuleSet()
        rules.add("val", is_numeric())
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail_string(self):
        df = pd.DataFrame({"val": ["abc", "1.5", "xyz"]})
        rules = RuleSet()
        rules.add("val", is_numeric())
        report = DataGuard(df).validate(rules)
        assert report.results[0].failed_rows >= 2

    def test_fail_bool_rejected(self):
        """bool is subclass of int in Python; is_numeric() rejects it."""
        df = pd.DataFrame({"val": [True, False, 1]})
        rules = RuleSet()
        rules.add("val", is_numeric())
        report = DataGuard(df).validate(rules)
        # True/False should fail (rejected), 1 passes
        assert report.results[0].passed_rows == 1

    def test_none_passes(self):
        df = pd.DataFrame({"val": [1, None, 3.14]})
        rules = RuleSet()
        rules.add("val", is_numeric())
        report = DataGuard(df).validate(rules)
        assert report.is_valid  # None passes

    def test_nan_passes(self):
        df = pd.DataFrame({"val": [1.0, np.nan, 3.0]})
        rules = RuleSet()
        rules.add("val", is_numeric())
        report = DataGuard(df).validate(rules)
        assert report.is_valid  # NaN passes (None-like)


# ─── IsEmail Tests ──────────────────────────────────────

class TestIsEmail:
    def test_pass_valid_emails(self):
        df = pd.DataFrame({"email": [
            "alice@example.com",
            "b.ob+joe@company.co.uk",
            "user@local.host",
        ]})
        rules = RuleSet()
        rules.add("email", is_email())
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail_invalid_emails(self):
        df = pd.DataFrame({"email": [
            "no-at-sign",
            "@missing-local.org",
            "missing-domain@",
            "spaces not@allowed.com",
        ]})
        rules = RuleSet()
        rules.add("email", is_email())
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_none_passes(self):
        df = pd.DataFrame({"email": ["alice@example.com", None]})
        rules = RuleSet()
        rules.add("email", is_email())
        report = DataGuard(df).validate(rules)
        assert report.is_valid


# ─── IsDate Tests ──────────────────────────────────────

class TestIsDate:
    def test_pass_with_format(self):
        df = pd.DataFrame({"dt": ["2024-01-15", "2024-12-31"]})
        rules = RuleSet()
        rules.add("dt", is_date("%Y-%m-%d"))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail_wrong_format(self):
        df = pd.DataFrame({"dt": ["15/01/2024", "2024-01-15"]})
        rules = RuleSet()
        rules.add("dt", is_date("%Y-%m-%d"))
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_pass_auto_detect(self):
        df = pd.DataFrame({"dt": ["2024-01-15", "2024/06/30"]})
        rules = RuleSet()
        rules.add("dt", is_date())  # no format = auto-detect
        report = DataGuard(df).validate(rules)
        # At least one should be detected
        assert report.results[0].passed_rows >= 1

    def test_none_passes(self):
        df = pd.DataFrame({"dt": ["2024-01-15", None]})
        rules = RuleSet()
        rules.add("dt", is_date("%Y-%m-%d"))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid format string"):
            is_date("%Q")


# ─── NotEmptyString Tests ──────────────────────────────────────

class TestNotEmptyString:
    def test_pass_normal_string(self):
        df = pd.DataFrame({"val": ["hello", "world"]})
        rules = RuleSet()
        rules.add("val", not_empty_string())
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail_empty_string(self):
        df = pd.DataFrame({"val": ["hello", "", "world"]})
        rules = RuleSet()
        rules.add("val", not_empty_string())
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_fail_whitespace_only(self):
        df = pd.DataFrame({"val": ["hello", "   ", "\t\n", "world"]})
        rules = RuleSet()
        rules.add("val", not_empty_string())
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_none_passes(self):
        df = pd.DataFrame({"val": ["hello", None]})
        rules = RuleSet()
        rules.add("val", not_empty_string())
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_number_converted(self):
        df = pd.DataFrame({"val": ["123", 456]})
        rules = RuleSet()
        rules.add("val", not_empty_string())
        report = DataGuard(df).validate(rules)
        assert report.is_valid


# ─── MaxValue Tests (Column-level) ──────────────────────────────

class TestMaxValue:
    def test_pass(self):
        df = pd.DataFrame({"age": [25, 30, 45]})
        rules = RuleSet()
        rules.add("age", max_value(100))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail(self):
        df = pd.DataFrame({"age": [25, 130, 45]})
        rules = RuleSet()
        rules.add("age", max_value(120))
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_exact_boundary(self):
        df = pd.DataFrame({"score": [0.0, 100.0, 50.5]})
        rules = RuleSet()
        rules.add("score", max_value(100.0))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_with_none(self):
        df = pd.DataFrame({"age": [25, None, 45]})
        rules = RuleSet()
        rules.add("age", max_value(120))
        report = DataGuard(df).validate(rules)
        assert report.is_valid  # None ignored

    def test_invalid_non_numeric_raises(self):
        with pytest.raises(ValueError, match="requires a numeric argument"):
            max_value("not_a_number")


# ─── MinValue Tests (Column-level) ──────────────────────────────

class TestMinValue:
    def test_pass(self):
        df = pd.DataFrame({"age": [25, 30, 45]})
        rules = RuleSet()
        rules.add("age", min_value(0))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail(self):
        df = pd.DataFrame({"age": [25, -5, 45]})
        rules = RuleSet()
        rules.add("age", min_value(0))
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_exact_boundary(self):
        df = pd.DataFrame({"score": [0.0, 100.0, 50.5]})
        rules = RuleSet()
        rules.add("score", min_value(0.0))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_with_none(self):
        df = pd.DataFrame({"age": [25, None, 45]})
        rules = RuleSet()
        rules.add("age", min_value(0))
        report = DataGuard(df).validate(rules)
        assert report.is_valid  # None ignored

    def test_invalid_non_numeric_raises(self):
        with pytest.raises(ValueError, match="requires a numeric argument"):
            min_value(None)


# ─── Custom Check Tests ──────────────────────────────────────

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


# ─── Threshold Edge Cases ──────────────────────────────────────

class TestThresholdEdgeCases:
    def test_threshold_zero_always_passes(self):
        df = pd.DataFrame({"name": [None, None, None]})
        rules = RuleSet()
        rules.add("name", not_null(), threshold=0.0)
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_threshold_one_strict(self):
        df = pd.DataFrame({"name": [None, "Alice"]})
        rules = RuleSet()
        rules.add("name", not_null(), threshold=1.0)
        report = DataGuard(df).validate(rules)
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
        from dataguard.rules import Rule
        for t in [0.0, 0.5, 1.0]:
            r = Rule(column="x", check=lambda: True, threshold=t)
            assert r.threshold == t


# ─── InRange Parameter Validation ──────────────────────────────────────

class TestInRangeValidation:
    def test_no_bounds_raises(self):
        with pytest.raises(ValueError):
            in_range()

    def test_min_greater_than_max_raises(self):
        with pytest.raises(ValueError):
            in_range(min_val=20, max_val=10)


# ─── Regex Match Edge Cases ──────────────────────────────────────

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


# ─── InSet Edge Cases ──────────────────────────────────────

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
        # False is not in {True}, so 2/3 rows pass
        assert report.total_count == 1
        assert not report.is_valid


# ─── Engine Detection Tests ──────────────────────────────────────

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


# ─── NotNull pd.NA Support ──────────────────────────────────────

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


# ─── Multiple Rules on Same Column ──────────────────────────────

class TestSameColumnMultipleRules:
    def test_same_column_two_rules(self):
        df = pd.DataFrame({"age": [25, -1, 150, None]})
        rules = RuleSet()
        rules.add("age", not_null())
        rules.add("age", in_range(0, 120))
        report = DataGuard(df).validate(rules)
        assert report.total_count == 2
        assert not report.is_valid


# ─── Profile Edge Cases ──────────────────────────────────────

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


# ─── Report Edge Cases ──────────────────────────────────────

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


# ─── Security Tests ──────────────────────────────────────

class TestSecurityChecks:
    def test_regex_redos_blocked(self):
        """Dangerous nested quantifier patterns should be rejected."""
        with pytest.raises(ValueError, match="catastrophic backtracking"):
            regex_match("(a+)+b")

    def test_regex_redos_star_variant_blocked(self):
        with pytest.raises(ValueError, match="catastrophic backtracking"):
            regex_match("(a+)*b")

    def test_regex_overlapping_alt_blocked(self):
        """Overlapping alternations with quantifiers should be rejected."""
        with pytest.raises(ValueError, match="catastrophic backtracking"):
            regex_match("(a|a)+b")

    def test_regex_excessive_repetition_blocked(self):
        """Excessive repetition counts should be rejected."""
        with pytest.raises(ValueError, match="excessive repetition"):
            regex_match(r"a{300,}")

    def test_regex_normal_pattern_allowed(self):
        """Normal patterns should still work fine."""
        check = regex_match(r"^[\w.-]+@[\w.-]+\.\w+$")
        assert check("test@example.com") is True

    def test_in_set_rejects_non_iterable(self):
        """Non-iterable allowed_values should raise TypeError."""
        with pytest.raises(TypeError, match="requires an iterable"):
            in_set(123)

    def test_in_set_accepts_list(self):
        check = in_set(["a", "b", "c"])
        assert check("a") is True
        assert check("d") is False


# ─── RuleSet.from_dict Tests ──────────────────────────────────────

class TestRuleSetFromDict:
    def test_basic_from_dict(self):
        config = {
            "name": [{"check": "not_null"}],
            "age": [{"check": "in_range", "params": {"min_val": 0, "max_val": 120}}],
        }
        rules = RuleSet.from_dict(config)
        assert len(rules) == 2
        assert rules.columns() == ["name", "age"]

    def test_from_dict_with_threshold(self):
        config = {
            "status": [{"check": "not_null", "threshold": 0.95}],
        }
        rules = RuleSet.from_dict(config)
        assert rules.rules[0].threshold == 0.95

    def test_from_dict_unknown_check(self):
        config = {"col": [{"check": "nonexistent"}]}
        with pytest.raises(ValueError, match="Unknown check"):
            RuleSet.from_dict(config)

    def test_from_dict_multiple_checks_per_column(self):
        config = {
            "age": [
                {"check": "not_null"},
                {"check": "in_range", "params": {"min_val": 0, "max_val": 120}},
            ],
        }
        rules = RuleSet.from_dict(config)
        assert len(rules) == 2

    def test_from_dict_regex_match(self):
        config = {
            "email": [{"check": "regex_match", "params": {"pattern": r"^[\w.-]+@[\w.-]+\.\w+$"}}],
        }
        rules = RuleSet.from_dict(config)
        assert len(rules) == 1

    def test_from_dict_unknown_keys_rejected(self):
        """Unknown keys in check definition should be rejected (injection prevention)."""
        config = {"col": [{"check": "not_null", "evil_key": "malicious"}]}
        with pytest.raises(ValueError, match="Unknown keys"):
            RuleSet.from_dict(config)

    def test_from_dict_invalid_params_rejected(self):
        """Invalid params should raise ValueError."""
        config = {"col": [{"check": "in_range", "params": {"invalid_param": 123}}]}
        with pytest.raises(ValueError, match="Invalid params"):
            RuleSet.from_dict(config)

    # ── New checks in from_dict ────────────────────────────

    def test_from_dict_is_numeric(self):
        config = {"val": [{"check": "is_numeric"}]}
        rules = RuleSet.from_dict(config)
        assert len(rules) == 1

    def test_from_dict_is_email(self):
        config = {"email": [{"check": "is_email"}]}
        rules = RuleSet.from_dict(config)
        assert len(rules) == 1

    def test_from_dict_is_date(self):
        config = {"dt": [{"check": "is_date", "params": {"format_str": "%Y-%m-%d"}}]}
        rules = RuleSet.from_dict(config)
        assert len(rules) == 1

    def test_from_dict_not_empty_string(self):
        config = {"name": [{"check": "not_empty_string"}]}
        rules = RuleSet.from_dict(config)
        assert len(rules) == 1

    def test_from_dict_max_value(self):
        config = {"age": [{"check": "max_value", "params": {"max_val": 120}}]}
        rules = RuleSet.from_dict(config)
        assert len(rules) == 1

    def test_from_dict_min_value(self):
        config = {"age": [{"check": "min_value", "params": {"min_val": 0}}]}
        rules = RuleSet.from_dict(config)
        assert len(rules) == 1
