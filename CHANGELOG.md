# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-06-01

### Added
- Vectorized pandas engine — uses `isin()`, `notna()`, `str.match()` instead of `apply(lambda)`, 10-100x faster on large DataFrames
- SQL validation CLI support — `dqguard validate --sql mysql://... --table users --rules rules.json`
- `py.typed` marker for PEP 561 type checking support
- Logging throughout the package (`dataguard` logger)
- `_validate_identifier()` guard in SQL engine to catch injection attempts early
- `_is_column_level` attribute on `unique()` check for better semantics

### Changed
- `DataGuard.from_sql()` no longer uses `cls.__new__()` — now goes through `__init__` properly
- `DataGuard.__init__` accepts SQL params directly (`_sql_connection`, `_sql_table`, etc.)
- `not_null()` no longer imports `math`/`pandas` per row — imports once at function creation
- `in_set()` gracefully handles unhashable elements (falls back to list containment)
- `_profile_via_info_schema()` now emits a warning instead of silently returning `{}`
- `ValidationError` imported directly in `core.py` instead of lazy import
- Dropped Python 3.8 support (EOL since 2024-10) — minimum is now 3.9
- CI now includes `pytest --cov` with coverage reporting

### Fixed
- **Threshold validation bypass** — `Rule.__post_init__` now validates threshold *before* the `check_name` early return
- **Dead code in `profile_sql`** — removed the unused `LIMIT 0` query line
- **Flink regex** — documented that `REGEXP_EXTRACT` as boolean is best-effort
- Column name used correctly in SQL sample failure queries (was `rule.column`, now uses quoted `col`)

## [0.4.0] - 2026-05-31

### Added
- SQL validation engine with SQLAlchemy — supports MySQL, Hive, Flink SQL, Doris, SelectDB
- `DataGuard.from_sql()` classmethod for SQL-based validation
- `sql_dialects.py` — per-dialect SQL generation (identifier quoting, regex operators, length functions)
- `sql_engine.py` — SQL validation and profiling backend
- `raise_on_error` parameter on `DataGuard.validate()`
- `_sql_params` attribute on check functions for SQL condition generation
- `_CHECK_REGISTRY` and `RuleSet.from_dict()` for config-driven rule definition
- CLI entry point (`dqguard validate`, `dqguard profile`)
- 33 SQL engine tests using SQLite

## [0.3.0] - 2026-05-31

### Added
- CI workflow with multi-version Python testing (3.9–3.12)
- Pre-commit configuration (ruff, formatting, private key detection)
- SECURITY.md security policy

### Changed
- Author email changed to GitHub noreply address for privacy
- Dependency version upper bounds added (`pandas<3`, `numpy<3`)

### Fixed
- `not_null()` now correctly handles `pd.NA` (Pandas 1.0+)
- `in_range()` validates that at least one bound is provided and min <= max
- `regex_match()` wraps `re.error` into `ValueError` with clear message
- `min_length()` / `max_length()` validate non-negative integer input
- `Rule.__post_init__` validates threshold is in [0.0, 1.0] range
- `_detect_engine()` raises `TypeError` for unsupported DataFrame types

## [0.2.0] - 2026-05-31

### Added
- ReDoS protection in `regex_match()` — nested quantifier patterns are rejected
- Parameter validation in `in_set()` — non-iterable arguments raise `TypeError`
- 5 new security-focused tests

### Changed
- Author email changed to GitHub noreply address for privacy
- Dependency version upper bounds added (`pandas<3`, `numpy<3`)

### Fixed
- `not_null()` now correctly handles `pd.NA` (Pandas 1.0+)
- `in_range()` validates that at least one bound is provided and min <= max
- `regex_match()` wraps `re.error` into `ValueError` with clear message
- `min_length()` / `max_length()` validate non-negative integer input
- `Rule.__post_init__` validates threshold is in [0.0, 1.0] range
- `_detect_engine()` raises `TypeError` for unsupported DataFrame types

## [0.1.0] - 2026-05-30

### Added
- Initial release
- Dual engine support (Pandas + PySpark)
- Declarative rule-based validation with threshold support
- Built-in checks: `not_null`, `unique`, `in_range`, `regex_match`, `in_set`, `min_length`, `max_length`, `custom`
- Data profiling for column-level statistics
- Validation report with summary + JSON export
- PyPI publishing via GitHub Actions
