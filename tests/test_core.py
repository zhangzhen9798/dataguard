"""
Tests for DataGuard core functionality.
"""

import pandas as pd
import numpy as np
import pytest

from dataguard import DataGuard, RuleSet, not_null, in_range, in_set, regex_match, unique


class TestNotNull:
    def test_pass(self):
        df = pd.DataFrame({"name": ["Alice", "Bob", "Charlie"]})
        rules = RuleSet()
        rules.add("name", not_null())
        report = DataGuard(df).validate(rules)
        assert report.is_valid
        assert report.passed_count == 1

    def test_fail_with_none(self):
        df = pd.DataFrame({"name": ["Alice", None, "Charlie"]})
        rules = RuleSet()
        rules.add("name", not_null())
        report = DataGuard(df).validate(rules)
        assert not report.is_valid
        assert report.failed_count == 1

    def test_fail_with_nan(self):
        df = pd.DataFrame({"name": ["Alice", float("nan"), "Charlie"]})
        rules = RuleSet()
        rules.add("name", not_null())
        report = DataGuard(df).validate(rules)
        assert not report.is_valid


class TestInRange:
    def test_pass(self):
        df = pd.DataFrame({"age": [25, 30, 40]})
        rules = RuleSet()
        rules.add("age", in_range(0, 120))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail_below_min(self):
        df = pd.DataFrame({"age": [-1, 30, 40]})
        rules = RuleSet()
        rules.add("age", in_range(0, 120))
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_fail_above_max(self):
        df = pd.DataFrame({"age": [25, 30, 150]})
        rules = RuleSet()
        rules.add("age", in_range(0, 120))
        report = DataGuard(df).validate(rules)
        assert not report.is_valid

    def test_boundary_values(self):
        df = pd.DataFrame({"age": [0, 120]})
        rules = RuleSet()
        rules.add("age", in_range(0, 120))
        report = DataGuard(df).validate(rules)
        assert report.is_valid


class TestInSet:
    def test_pass(self):
        df = pd.DataFrame({"status": ["active", "inactive", "active"]})
        rules = RuleSet()
        rules.add("status", in_set(["active", "inactive"]))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail(self):
        df = pd.DataFrame({"status": ["active", "unknown", "active"]})
        rules = RuleSet()
        rules.add("status", in_set(["active", "inactive"]))
        report = DataGuard(df).validate(rules)
        assert not report.is_valid


class TestRegexMatch:
    def test_pass(self):
        df = pd.DataFrame({"email": ["alice@example.com", "bob@test.org"]})
        rules = RuleSet()
        rules.add("email", regex_match(r"^[\w.-]+@[\w.-]+\.\w+$"))
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail(self):
        df = pd.DataFrame({"email": ["alice@example.com", "invalid"]})
        rules = RuleSet()
        rules.add("email", regex_match(r"^[\w.-]+@[\w.-]+\.\w+$"))
        report = DataGuard(df).validate(rules)
        assert not report.is_valid


class TestUnique:
    def test_pass(self):
        df = pd.DataFrame({"id": [1, 2, 3, 4, 5]})
        rules = RuleSet()
        rules.add("id", unique())
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail(self):
        df = pd.DataFrame({"id": [1, 2, 3, 2, 5]})
        rules = RuleSet()
        rules.add("id", unique())
        report = DataGuard(df).validate(rules)
        assert not report.is_valid


class TestThreshold:
    def test_pass_with_threshold(self):
        df = pd.DataFrame({"name": ["Alice", None, "Charlie"]})
        rules = RuleSet()
        rules.add("name", not_null(), threshold=0.6)
        report = DataGuard(df).validate(rules)
        assert report.is_valid

    def test_fail_below_threshold(self):
        df = pd.DataFrame({"name": ["Alice", None, "Charlie"]})
        rules = RuleSet()
        rules.add("name", not_null(), threshold=0.9)
        report = DataGuard(df).validate(rules)
        assert not report.is_valid


class TestMultipleRules:
    def test_multiple_rules_on_different_columns(self):
        df = pd.DataFrame({
            "name": ["Alice", "Bob"],
            "age": [25, 30],
            "email": ["alice@example.com", "bob@test.org"],
        })
        rules = RuleSet()
        rules.add("name", not_null())
        rules.add("age", in_range(0, 120))
        rules.add("email", regex_match(r"^[\w.-]+@[\w.-]+\.\w+$"))
        report = DataGuard(df).validate(rules)
        assert report.is_valid
        assert report.passed_count == 3

    def test_partial_failure(self):
        df = pd.DataFrame({
            "name": ["Alice", "Bob"],
            "age": [25, -1],
        })
        rules = RuleSet()
        rules.add("name", not_null())
        rules.add("age", in_range(0, 120))
        report = DataGuard(df).validate(rules)
        assert not report.is_valid
        assert report.passed_count == 1
        assert report.failed_count == 1


class TestMissingColumn:
    def test_missing_column(self):
        df = pd.DataFrame({"name": ["Alice"]})
        rules = RuleSet()
        rules.add("missing_col", not_null())
        report = DataGuard(df).validate(rules)
        assert not report.is_valid


class TestReport:
    def test_summary(self):
        df = pd.DataFrame({"age": [25, -1, None]})
        rules = RuleSet()
        rules.add("age", not_null())
        rules.add("age", in_range(0, 120))
        report = DataGuard(df).validate(rules)
        summary = report.summary()
        assert "DataGuard Validation Report" in summary

    def test_to_json(self):
        df = pd.DataFrame({"age": [25, 30]})
        rules = RuleSet()
        rules.add("age", in_range(0, 120))
        report = DataGuard(df).validate(rules)
        json_str = report.to_json()
        assert '"is_valid": true' in json_str

    def test_to_dict(self):
        df = pd.DataFrame({"age": [25]})
        rules = RuleSet()
        rules.add("age", in_range(0, 120))
        report = DataGuard(df).validate(rules)
        d = report.to_dict()
        assert "results" in d
        assert d["total"] == 1


class TestProfile:
    def test_profile_pandas(self):
        df = pd.DataFrame({
            "name": ["Alice", "Bob", "Charlie"],
            "age": [25, 30, None],
        })
        profile = DataGuard(df).profile()
        assert "name" in profile
        assert "age" in profile
        assert profile["age"]["null_count"] == 1
        assert profile["name"]["distinct_count"] == 3


class TestRaiseOnError:
    def test_raise_on_error(self):
        from dataguard.exceptions import ValidationError

        df = pd.DataFrame({"age": [-1]})
        rules = RuleSet()
        rules.add("age", in_range(0, 120))
        with pytest.raises(ValidationError):
            DataGuard(df).validate(rules, raise_on_error=True)

    def test_no_raise_when_valid(self):
        df = pd.DataFrame({"age": [25]})
        rules = RuleSet()
        rules.add("age", in_range(0, 120))
        # Should not raise
        report = DataGuard(df).validate(rules, raise_on_error=True)
        assert report.is_valid


class TestRuleSet:
    def test_method_chaining(self):
        rules = RuleSet()
        rules.add("a", not_null()).add("b", in_range(0, 10))
        assert len(rules) == 2

    def test_columns(self):
        rules = RuleSet()
        rules.add("a", not_null())
        rules.add("b", in_range(0, 10))
        rules.add("a", unique())
        assert rules.columns() == ["a", "b"]

    def test_get_rules_for_column(self):
        rules = RuleSet()
        rules.add("a", not_null())
        rules.add("a", unique())
        rules.add("b", in_range(0, 10))
        assert len(rules.get_rules_for_column("a")) == 2
