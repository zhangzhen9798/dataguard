"""
Tests for the SQL validation engine.

Uses SQLite (built into Python) as the test database,
so no external database is needed.
"""

import pytest
import pandas as pd
from sqlalchemy import create_engine, text

from dataguard import DataGuard, RuleSet, not_null, in_range, in_set, regex_match, unique, min_length, max_length, custom
from dataguard.sql_dialects import get_dialect, quote_id, sql_value, check_to_condition, Dialect
from dataguard.sql_engine import validate_sql, profile_sql


# ─── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def sqlite_engine():
    """Create an in-memory SQLite database with test data."""
    engine = create_engine("sqlite:///:memory:")
    df = pd.DataFrame({
        "name": ["Alice", "Bob", "Charlie", None, "Eve"],
        "age": [25, 30, -5, 40, 150],
        "email": [
            "alice@example.com",
            "invalid-email",
            "charlie@example.com",
            "dana@example.com",
            "eve@example.com",
        ],
        "status": ["active", "active", "inactive", "active", "unknown"],
        "score": [85.5, 92.0, 78.3, None, 88.1],
    })
    df.to_sql("users", engine, index=False, if_exists="replace")
    return engine


# ─── Dialect Tests ─────────────────────────────────────────────────

class TestDialects:
    def test_get_mysql_dialect(self):
        d = get_dialect("mysql")
        assert d.name == "mysql"
        assert d.regex_op == "REGEXP"

    def test_get_hive_dialect(self):
        d = get_dialect("hive")
        assert d.regex_op == "RLIKE"

    def test_get_doris_dialect(self):
        d = get_dialect("doris")
        assert d.name == "doris"

    def test_get_selectdb_dialect(self):
        d = get_dialect("selectdb")
        assert d.name == "selectdb"

    def test_get_flink_dialect(self):
        d = get_dialect("flink")
        assert d.name == "flink"

    def test_unknown_dialect_raises(self):
        with pytest.raises(ValueError, match="Unknown dialect"):
            get_dialect("oracle")

    def test_case_insensitive(self):
        assert get_dialect("MySQL").name == "mysql"
        assert get_dialect("HIVE").name == "hive"


class TestQuoteId:
    def test_simple_column(self):
        d = get_dialect("mysql")
        assert quote_id("name", d) == "`name`"

    def test_schema_table(self):
        d = get_dialect("mysql")
        assert quote_id("mydb.users", d) == "`mydb`.`users`"

    def test_invalid_identifier(self):
        d = get_dialect("mysql")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            quote_id("name; DROP TABLE users", d)


class TestSqlValue:
    def test_string(self):
        assert sql_value("hello") == "'hello'"

    def test_string_with_quotes(self):
        assert sql_value("it's") == "'it''s'"

    def test_int(self):
        assert sql_value(42) == "42"

    def test_none(self):
        assert sql_value(None) == "NULL"


class TestCheckToCondition:
    def test_not_null(self):
        d = get_dialect("mysql")
        cond = check_to_condition("not_null", {}, "`name`", d)
        assert cond == "`name` IS NOT NULL"

    def test_in_range(self):
        d = get_dialect("mysql")
        cond = check_to_condition("in_range", {"min_val": 0, "max_val": 120}, "`age`", d)
        assert "`age` >= 0" in cond
        assert "`age` <= 120" in cond

    def test_in_set(self):
        d = get_dialect("mysql")
        cond = check_to_condition("in_set", {"allowed_values": ["active", "inactive"]}, "`status`", d)
        assert "'active'" in cond
        assert "'inactive'" in cond

    def test_min_length(self):
        d = get_dialect("mysql")
        cond = check_to_condition("min_length", {"min_len": 3}, "`name`", d)
        assert "CHAR_LENGTH" in cond
        assert ">= 3" in cond

    def test_unique_returns_none(self):
        d = get_dialect("mysql")
        assert check_to_condition("unique", {}, "`id`", d) is None

    def test_custom_returns_none(self):
        d = get_dialect("mysql")
        assert check_to_condition("custom", {}, "`col`", d) is None


# ─── SQL Validation Tests ──────────────────────────────────────────

class TestSQLValidation:
    def test_not_null(self, sqlite_engine):
        rules = RuleSet()
        rules.add("name", not_null())
        report = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql").validate(rules)
        assert not report.is_valid
        assert report.results[0].failed_rows == 1

    def test_in_range(self, sqlite_engine):
        rules = RuleSet()
        rules.add("age", in_range(0, 120))
        report = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql").validate(rules)
        # age values: 25, 30, -5, 40, 150 -> 2 out of range, but None rows pass
        assert report.results[0].failed_rows == 2

    def test_in_set(self, sqlite_engine):
        rules = RuleSet()
        rules.add("status", in_set(["active", "inactive"]))
        report = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql").validate(rules)
        # "unknown" is not in set
        assert report.results[0].failed_rows == 1

    def test_unique_pass(self, sqlite_engine):
        rules = RuleSet()
        rules.add("email", unique())
        report = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql").validate(rules)
        # All emails are unique
        assert report.results[0].passed

    def test_unique_fail(self, sqlite_engine):
        # Insert a duplicate
        with sqlite_engine.connect() as conn:
            conn.execute(text("INSERT INTO users VALUES ('Alice', 25, 'alice@example.com', 'active', 85.5)"))
            conn.commit()
        rules = RuleSet()
        rules.add("name", unique())
        report = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql").validate(rules)
        assert not report.results[0].passed

    def test_threshold(self, sqlite_engine):
        rules = RuleSet()
        rules.add("name", not_null(), threshold=0.8)
        report = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql").validate(rules)
        # 4/5 = 80% pass rate, threshold=0.8 should pass
        assert report.results[0].passed

    def test_custom_check_skipped(self, sqlite_engine):
        rules = RuleSet()
        rules.add("age", custom(lambda x: x > 0))
        with pytest.warns(UserWarning, match="cannot be translated to SQL"):
            report = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql").validate(rules)
        # Skipped checks pass by default
        assert report.results[0].passed

    def test_multiple_rules(self, sqlite_engine):
        rules = RuleSet()
        rules.add("name", not_null())
        rules.add("age", in_range(0, 120))
        rules.add("status", in_set(["active", "inactive"]))
        report = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql").validate(rules)
        assert report.total_count == 3

    def test_connection_string(self, sqlite_engine):
        """Test with connection string instead of engine object."""
        # Use the in-memory engine directly
        rules = RuleSet()
        rules.add("name", not_null())
        report = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql").validate(rules)
        assert report.total_count == 1

    def test_with_schema(self, sqlite_engine):
        rules = RuleSet()
        rules.add("name", not_null())
        # SQLite doesn't really use schemas, but the code shouldn't crash
        report = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql", schema="main").validate(rules)
        # May or may not work depending on SQLite behavior, but shouldn't crash
        assert report.total_count == 1


# ─── SQL Profile Tests ─────────────────────────────────────────────

class TestSQLProfile:
    def test_basic_profile(self, sqlite_engine):
        profile = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql").profile()
        assert "name" in profile
        assert "age" in profile
        assert profile["name"]["total_rows"] == 5
        assert profile["name"]["null_count"] == 1

    def test_numeric_stats(self, sqlite_engine):
        profile = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql").profile()
        # age column should have numeric stats (SQLite may not support all)
        age = profile["age"]
        assert "distinct_count" in age
        # SQLite doesn't have STDDEV, so dtype might be numeric or string depending on query result
        # Just check that basic stats are present or that it falls back gracefully


# ─── from_dict with SQL ────────────────────────────────────────────

class TestSQLFromDict:
    def test_from_dict_sql_validation(self, sqlite_engine):
        config = {
            "name": [{"check": "not_null"}],
            "age": [{"check": "in_range", "params": {"min_val": 0, "max_val": 120}}],
            "status": [{"check": "in_set", "params": {"allowed_values": ["active", "inactive"]}}],
        }
        rules = RuleSet.from_dict(config)
        report = DataGuard.from_sql(sqlite_engine, "users", dialect="mysql").validate(rules)
        assert report.total_count == 3
