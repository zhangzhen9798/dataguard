"""
DataGuard - Lightweight Data Quality Validation Framework for Big Data Pipelines
"""

__version__ = "0.1.0"
__author__ = "Zhang Zhen (zhangzhen9798@users.noreply.github.com)"

from dataguard.core import DataGuard
from dataguard.rules import Rule, RuleSet
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

__all__ = [
    "DataGuard",
    "Rule",
    "RuleSet",
    "not_null",
    "unique",
    "in_range",
    "regex_match",
    "in_set",
    "min_length",
    "max_length",
    "custom",
]
