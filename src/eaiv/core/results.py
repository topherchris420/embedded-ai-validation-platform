"""Result dataclasses shared by the orchestrator and reporter.

Split into its own module to avoid a circular import between
`orchestrator` (which produces results) and `reporter` (which consumes
them for display).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class SuiteResult:
    name: str
    passed: bool
    metrics: dict = field(default_factory=dict)
    notes: str = ""

    def __repr__(self) -> str:
        flag = "PASS" if self.passed else "FAIL"
        return f"[{flag}] {self.name}: {self.metrics}"


@dataclass
class AggregateResult:
    suites: list[SuiteResult] = field(default_factory=list)

    def add(self, r: SuiteResult) -> None:
        self.suites.append(r)

    def all_passed(self) -> bool:
        return all(s.passed for s in self.suites)

    def __iter__(self) -> Iterator[SuiteResult]:
        return iter(self.suites)
