from dataclasses import dataclass, field
from datetime import date


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
    # Which CSV header was used for each field (reference, amount, date).
    column_map: dict[str, str | None] = field(default_factory=dict)
    # First and last date on the statement; None if no row had a readable date.
    period: tuple[date, date] | None = None
