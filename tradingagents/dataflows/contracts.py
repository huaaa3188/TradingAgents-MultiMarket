from __future__ import annotations

from dataclasses import dataclass, field
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
