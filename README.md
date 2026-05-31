<div align="center">

# 🛡️ DataGuard

**Lightweight Data Quality Validation Framework for Big Data Pipelines**

[![PyPI version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/zhangzhen9798/dataguard)
[![Python](https://img.shields.io/badge/python-3.8%2B-green.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

[English](#features) | [中文文档](#中文介绍)

</div>

---

## Why DataGuard?

Data quality issues cost organizations millions annually. Existing solutions like Great Expectations are powerful but heavy. **DataGuard** provides a **lightweight, intuitive** alternative that works seamlessly with both **Pandas** and **PySpark** — perfect for big data pipelines.

- ✅ **Dual Engine**: First-class support for both Pandas & PySpark
- ✅ **Declarative Rules**: Define validation rules cleanly, no boilerplate
- ✅ **Threshold-based**: Set pass-rate thresholds per rule (not just pass/fail)
- ✅ **Data Profiling**: Auto-generate column-level statistics
- ✅ **Rich Reports**: Human-readable summaries + JSON export for CI/CD
- ✅ **Zero Config**: Works out of the box, no setup files needed

## Quick Start

### Installation

```bash
# Basic (Pandas engine)
pip install dataguard

# With PySpark support
pip install dataguard[spark]
```

### Basic Usage

```python
import pandas as pd
from dataguard import DataGuard, RuleSet, not_null, in_range, in_set, regex_match

# Create a DataFrame
df = pd.DataFrame({
    "name": ["Alice", "Bob", "Charlie", None, "Eve"],
    "age": [25, 30, -1, 40, 150],
    "email": ["alice@example.com", "invalid", "charlie@example.com", "dana@example.com", "eve@example.com"],
    "status": ["active", "active", "inactive", "active", "unknown"],
})

# Define validation rules
rules = RuleSet()
rules.add("name", not_null())
rules.add("age", not_null())
rules.add("age", in_range(0, 120))
rules.add("email", regex_match(r"^[\w.-]+@[\w.-]+\.\w+$"))
rules.add("status", in_set(["active", "inactive"]))

# Run validation
guardian = DataGuard(df)
report = guardian.validate(rules)

# Print summary
print(report.summary())
```

Output:
```
DataGuard Validation Report
Engine: pandas
Total Rules: 5 | Passed: 1 | Failed: 4
Overall Status: INVALID
------------------------------------------------------------
[FAIL] name.not_null | pass_rate=80.00% (threshold=100%) | 4/5 rows passed
[PASS] age.not_null | pass_rate=100.00% (threshold=100%) | 5/5 rows passed
[FAIL] age.in_range(0, 120) | pass_rate=80.00% (threshold=100%) | 4/5 rows passed
[FAIL] email.regex_match(...) | pass_rate=80.00% (threshold=100%) | 4/5 rows passed
[FAIL] status.in_set(...) | pass_rate=80.00% (threshold=100%) | 4/5 rows passed
```

### With PySpark

```python
from pyspark.sql import SparkSession
from dataguard import DataGuard, RuleSet, not_null, in_range

spark = SparkSession.builder.appName("DataGuard").getOrCreate()
df = spark.read.parquet("s3://my-bucket/data/")

rules = RuleSet()
rules.add("user_id", not_null())
rules.add("user_id", unique())
rules.add("age", in_range(0, 120))

report = DataGuard(df).validate(rules)
```

### Threshold-based Validation

Not every dataset needs 100% compliance. Set thresholds per rule:

```python
rules = RuleSet()
# Allow up to 5% null values in optional fields
rules.add("middle_name", not_null(), threshold=0.95)
# Require 99.9% uniqueness for IDs
rules.add("transaction_id", unique(), threshold=0.999)
```

### Data Profiling

```python
guardian = DataGuard(df)
profile = guardian.profile()

for col, stats in profile.items():
    print(f"{col}: {stats['distinct_count']} distinct, {stats['null_rate']:.2%} nulls")
```

### JSON Export (for CI/CD integration)

```python
report = guardian.validate(rules)
print(report.to_json())
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

## Architecture

```
dataguard/
├── __init__.py          # Public API
├── core.py              # DataGuard main class
├── rules.py             # Rule & RuleSet definitions
├── checks.py            # Built-in check functions
├── report.py            # ValidationReport & ValidationResult
├── exceptions.py        # Custom exceptions
├── pandas_engine.py     # Pandas validation backend
└── spark_engine.py      # PySpark validation backend
```

## Roadmap

- [ ] Great Expectations interop layer
- [ ] dbt integration
- [ ] SQL-based validation engine
- [ ] Streaming data validation (Spark Structured Streaming)
- [ ] CLI tool for one-off validation jobs
- [ ] Visualization dashboard

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 中文介绍

DataGuard 是一个轻量级的大数据管道数据质量验证框架，核心特性：

- **双引擎支持**：原生支持 Pandas 和 PySpark，无需切换工具
- **声明式规则**：用简洁的语法定义验证规则，告别样板代码
- **阈值验证**：支持按规则设置通过率阈值，而非简单的二元判断
- **数据画像**：一键生成列级统计信息
- **丰富报告**：支持人类可读摘要 + JSON 导出，方便 CI/CD 集成
- **零配置**：开箱即用，无需配置文件

适用于数据工程师在 ETL/ELT 管道中进行数据质量检查，也适用于数据科学家在分析前验证数据完整性。
