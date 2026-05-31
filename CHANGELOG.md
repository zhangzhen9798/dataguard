# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-05-31

### Added
- `RuleSet.from_dict()` for config-driven rule definition
- CLI entry point (`dqguard validate`, `dqguard profile`)
- ReDoS protection in `regex_match()` — nested quantifier patterns are rejected
- Parameter validation in `in_set()` — non-iterable arguments raise `TypeError`
- CI workflow with multi-version Python testing (3.9–3.12)
- SECURITY.md security policy
- pre-commit configuration
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
