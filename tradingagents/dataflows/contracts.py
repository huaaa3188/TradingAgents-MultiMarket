from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import pandas as pd


DataSemantic = Literal[
    "ohlcv",
    "nav",
    "fund_profile",
    "company_profile",
    "news",
    "notice",
]


@dataclass(frozen=True)
class SourceMeta:
    """Metadata needed to judge whether a vendor payload is safe to use."""

    vendor: str
    source: str
    symbol: str
    semantic: DataSemantic
    as_of: str | None = None
    retrieved_at: str | None = None


@dataclass(frozen=True)
class DataNotice:
    """Structured diagnostic for missing, stale, or schema-drifted data."""

    code: str
    message: str
    source: str | None = None
    detail: str | None = None
    severity: Literal["info", "warning", "error"] = "warning"


@dataclass(frozen=True)
class DataResult:
    """Structured dataflow result with explicit source, semantic, and notices."""

    meta: SourceMeta
    payload: pd.DataFrame | str | list[Any] | None = None
    notices: tuple[DataNotice, ...] = ()
    ok: bool = True
    stale: bool = False
    missing_reason: str | None = None
    error_type: str | None = None
    text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def rows(self) -> int:
        if isinstance(self.payload, pd.DataFrame):
            return len(self.payload)
        if isinstance(self.payload, list):
            return len(self.payload)
        if self.payload is None:
            return 0
        return 1

    def with_text(self, text: str) -> "DataResult":
        return DataResult(
            meta=self.meta,
            payload=self.payload,
            notices=self.notices,
            ok=self.ok,
            stale=self.stale,
            missing_reason=self.missing_reason,
            error_type=self.error_type,
            text=text,
            metadata=self.metadata,
        )


@dataclass(frozen=True)
class ContractGateResult:
    """Validation outcome for a structured data contract."""

    ok: bool
    result: DataResult
    failures: tuple[DataNotice, ...] = ()
    warnings: tuple[DataNotice, ...] = ()
    expected_semantic: DataSemantic | None = None

    @property
    def notices(self) -> tuple[DataNotice, ...]:
        return self.failures + self.warnings


def data_notice(
    code: str,
    message: str,
    *,
    source: str | None = None,
    detail: str | None = None,
    severity: Literal["info", "warning", "error"] = "warning",
) -> DataNotice:
    return DataNotice(
        code=code,
        message=message,
        source=source,
        detail=detail,
        severity=severity,
    )


def render_notices(notices: tuple[DataNotice, ...] | list[DataNotice]) -> str:
    if not notices:
        return ""
    lines = ["", "## Data Notices"]
    for notice in notices:
        source = f" source={notice.source};" if notice.source else ""
        detail = f" detail={notice.detail}" if notice.detail else ""
        lines.append(
            f"- {notice.severity.upper()} {notice.code}:{source} {notice.message}{detail}".strip()
        )
    return "\n".join(lines)


def validate_data_result(
    result: DataResult,
    *,
    analysis_date: str | date | None = None,
    max_staleness_days: int | None = None,
    expected_semantic: DataSemantic | None = None,
    forbid_schema_drift: bool = True,
    allow_missing: bool = False,
    stale_fails: bool = True,
) -> ContractGateResult:
    """Fail closed when a structured data result is unsafe for factual claims."""
    failures: list[DataNotice] = []
    warnings: list[DataNotice] = []

    if not result.meta.source or not result.meta.symbol or not result.meta.semantic:
        failures.append(
            data_notice(
                "missing_contract_fields",
                "Data result is missing required source, symbol, or semantic contract fields.",
                severity="error",
            )
        )

    if expected_semantic is not None and result.meta.semantic != expected_semantic:
        failures.append(
            data_notice(
                "semantic_mismatch",
                f"Expected semantic={expected_semantic}, got semantic={result.meta.semantic}.",
                source=result.meta.source,
                severity="error",
            )
        )

    if result.error_type == "schema_drift" or any(n.code == "schema_drift" for n in result.notices):
        notice = data_notice(
            "schema_drift",
            "Vendor payload schema drift was detected before this result was produced.",
            source=result.meta.source,
            severity="error" if forbid_schema_drift else "warning",
        )
        if forbid_schema_drift:
            failures.append(notice)
        else:
            warnings.append(notice)

    if not result.ok and not allow_missing:
        failures.append(
            data_notice(
                result.missing_reason or result.error_type or "data_unavailable",
                "Data result is not OK and cannot be treated as reliable evidence.",
                source=result.meta.source,
                severity="error",
            )
        )

    if result.stale:
        notice = data_notice(
            "stale_data",
            "Data source marked this result as stale.",
            source=result.meta.source,
            severity="error" if stale_fails else "warning",
        )
        if stale_fails:
            failures.append(notice)
        else:
            warnings.append(notice)

    analysis_ts = _parse_date(analysis_date)
    as_of_ts = _parse_date(result.meta.as_of)
    if analysis_date is not None and result.meta.as_of and as_of_ts is None:
        failures.append(
            data_notice(
                "invalid_as_of",
                f"Could not parse as_of={result.meta.as_of!r} for contract validation.",
                source=result.meta.source,
                severity="error",
            )
        )
    if analysis_ts is not None and as_of_ts is not None:
        delta_days = (analysis_ts - as_of_ts).days
        if delta_days < 0:
            failures.append(
                data_notice(
                    "future_data",
                    f"Data as_of={result.meta.as_of} is after analysis_date={analysis_ts.date()}.",
                    source=result.meta.source,
                    severity="error",
                )
            )
        elif max_staleness_days is not None and delta_days > max_staleness_days:
            notice = data_notice(
                "stale_data",
                (
                    f"Data as_of={result.meta.as_of} is {delta_days} day(s) before "
                    f"analysis_date={analysis_ts.date()}, exceeding max_staleness_days={max_staleness_days}."
                ),
                source=result.meta.source,
                severity="error" if stale_fails else "warning",
            )
            if stale_fails:
                failures.append(notice)
            else:
                warnings.append(notice)

    if result.meta.semantic == "nav":
        warnings.append(
            data_notice(
                "nav_semantic",
                (
                    "This result is daily fund NAV, not exchange-traded OHLCV. Do not infer "
                    "intraday volume, exchange liquidity, or premium/discount unless another tool "
                    "explicitly provides those fields."
                ),
                source=result.meta.source,
                severity="warning",
            )
        )

    return ContractGateResult(
        ok=not failures,
        result=result,
        failures=tuple(failures),
        warnings=tuple(warnings),
        expected_semantic=expected_semantic,
    )


def render_contract_gate(gate: ContractGateResult, title: str = "Data Contract Gate") -> str:
    """Render a compact gate block for tool outputs and validation errors."""
    result = gate.result
    lines = [
        f"## {title}",
        "",
        f"- Status: {'PASS' if gate.ok else 'FAIL'}",
        f"- Source: {result.meta.source or 'n/a'}",
        f"- Symbol: {result.meta.symbol or 'n/a'}",
        f"- Semantic: {result.meta.semantic or 'n/a'}",
    ]
    if gate.expected_semantic:
        lines.append(f"- Expected semantic: {gate.expected_semantic}")
    lines.extend(
        [
            f"- As of: {result.meta.as_of or 'n/a'}",
            f"- Rows: {result.rows}",
        ]
    )
    if result.missing_reason:
        lines.append(f"- Missing reason: {result.missing_reason}")
    if result.error_type:
        lines.append(f"- Error type: {result.error_type}")

    if gate.failures:
        lines.extend(["", "### Failures"])
        lines.extend(_render_gate_notices(gate.failures))
    if gate.warnings:
        lines.extend(["", "### Warnings"])
        lines.extend(_render_gate_notices(gate.warnings))
    return "\n".join(lines)


def _render_gate_notices(notices: tuple[DataNotice, ...]) -> list[str]:
    lines = []
    for notice in notices:
        source = f" source={notice.source};" if notice.source else ""
        detail = f" detail={notice.detail}" if notice.detail else ""
        lines.append(
            f"- {notice.severity.upper()} {notice.code}:{source} {notice.message}{detail}".strip()
        )
    return lines


def _parse_date(value: str | date | None) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()
