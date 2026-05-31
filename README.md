<div align="center">

# DataGuard

**Lightweight data quality validation for big data pipelines**

[![PyPI](https://img.shields.io/pypi/v/dqguard.svg)](https://pypi.org/project/dqguard/)
[![Python](https://img.shields.io/pypi/pyversions/dqguard.svg)](https://pypi.org/project/dqguard/)
[![CI](https://github.com/zhangzhen9798/dataguard/actions/workflows/ci.yml/badge.svg)](https://github.com/zhangzhen9798/dataguard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

</div>

---

DataGuard is a lightweight data quality validation framework that works with both **Pandas** and **PySpark**. Define rules declaratively, set pass-rate thresholds, and get rich reports — without the boilerplate.

## Install

```bash
pip install dqguard          # Pandas engine
pip install dqguard[spark]   # With PySpark support
```

## Quick Start

```python
import pandas as pd
from dataguard import DataGuard, RuleSet, not_null, in_range, in_set, regex_match

df = pd.DataFrame({
    "name": ["Alice", "Bob", "Charlie", None, "Eve"],
    "age": [25, 30, -1, 40, 150],
    "email": ["alice@example.com", "invalid", "charlie@example.com", "dana@example.com", "eve@example.com"],
    "status": ["active", "active", "inactive", "active", "unknown"],
})

rules = RuleSet()
rules.add("name", not_null())
rules.add("age", in_range(0, 120))
rules.add("email", regex_match(r"^[\w.-]+@[\w.-]+\.\w+$"))
rules.add("status", in_set(["active", "inactive"]))

report = DataGuard(df).validate(rules)
print(report.summary())
```

```
DataGuard Validation Report
Engine: pandas
Total Rules: 4 | Passed: 0 | Failed: 4
Overall Status: INVALID
------------------------------------------------------------
[FAIL] name.not_null | pass_rate=80.00% (threshold=100%) | 4/5 rows passed
[FAIL] age.in_range(0, 120) | pass_rate=80.00% (threshold=100%) | 4/5 rows passed
[FAIL] email.regex_match(...) | pass_rate=80.00% (threshold=100%) | 4/5 rows passed
[FAIL] status.in_set(...) | pass_rate=80.00% (threshold=100%) | 4/5 rows passed
```

## Features

### Threshold-based validation

Not every column needs 100% compliance. Set thresholds per rule:

```python
rules.add("middle_name", not_null(), threshold=0.95)    # allow 5% nulls
rules.add("transaction_id", unique(), threshold=0.999)   # 99.9% unique
```

### Data profiling

```python
profile = DataGuard(df).profile()
for col, stats in profile.items():
    print(f"{col}: {stats['distinct_count']} distinct, {stats['null_rate']:.2%} nulls")
```

### RuleSet from dict

Define rules as data — useful for config-driven pipelines:

```python
from dataguard import RuleSet

config = {
    "name": [{"check": "not_null"}],
    "age": [{"check": "in_range", "params": {"min_val": 0, "max_val": 120}}],
    "email": [{"check": "regex_match", "params": {"pattern": r"^[\w.-]+@[\w.-]+\.\w+$"}}],
}
rules = RuleSet.from_dict(config)
```

### CLI

```bash
# Validate a CSV file against a rule config
dqguard validate data.csv --rules rules.json

# Profile a dataset
dqguard profile data.csv
```

### JSON export

```python
print(report.to_json())   # for CI/CD integration
```

## PySpark

```python
from pyspark.sql import SparkSession
from dataguard import DataGuard, RuleSet, not_null, in_range

spark = SparkSession.builder.appName("dqguard").getOrCreate()
df = spark.read.parquet("s3://my-bucket/data/")

rules = RuleSet()
rules.add("user_id", not_null())
rules.add("age", in_range(0, 120))

report = DataGuard(df).validate(rules)
```

## Built-in Checks

| Check | Description |
|-------|-------------|
| `not_null()` | Value must not be None/NaN |
| `unique()` | Column values must be unique |
| `in_range(min, max)` | Numeric value within range (inclusive) |
| `regex_match(pattern)` | String matches regex pattern |
| `in_set(values)` | Value in allowed set |
| `min_length(n)` | String has at least n characters |
| `max_length(n)` | String has at most n characters |
| `custom(fn, name)` | Custom validation function |

## Project Structure

```
dataguard/
├── __init__.py          # Public API
├── core.py              # DataGuard main class
├── rules.py             # Rule & RuleSet definitions
├── checks.py            # Built-in check functions
├── report.py            # ValidationReport & ValidationResult
├── exceptions.py        # Custom exceptions
├── pandas_engine.py     # Pandas validation backend
├── spark_engine.py      # PySpark validation backend
└── cli.py               # CLI entry point
```

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License — see [LICENSE](LICENSE) for details.
