from dataclasses import dataclass, field


@dataclass
class PullResult:
    new: int = 0
    updated: int = 0
    pruned: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ReconciliationReport:
    matched: list[dict] = field(default_factory=list)
    mismatched: list[dict] = field(default_factory=list)
    missing_in_db: list[dict] = field(default_factory=list)
    missing_in_statement: list[dict] = field(default_factory=list)
