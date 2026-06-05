"""Deterministic market-data verification snapshot.

The market analyst is an LLM that can confabulate exact numbers — citing a
Bollinger band or a "historically validated bounce" that the underlying data
doesn't support (#830). This module computes a ground-truth snapshot (latest
OHLCV row on or before the analysis date, common indicators, recent closes)
the analyst is told to treat as the source of truth for any exact numeric
claim. Deterministic, no LLM involved.
"""

from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd
from stockstats import wrap

from tradingagents.dataflows.instruments import MarketType, detect_market_type, normalize_ticker_symbol
from tradingagents.dataflows.stockstats_utils import load_ohlcv
from tradingagents.dataflows.tiantian_fund import get_fund_nav_history

# A fixed, common indicator set so the snapshot is the same shape every run.
DEFAULT_SNAPSHOT_INDICATORS: tuple[str, ...] = (
    "close_10_ema", "close_50_sma", "close_200_sma",
    "rsi", "boll", "boll_ub", "boll_lb",
    "macd", "macds", "macdh", "atr",
)


def _verified_rows(symbol: str, curr_date: str) -> pd.DataFrame:
    """OHLCV on or before curr_date, date-sorted. Raises if nothing usable.

    ``load_ohlcv`` already normalizes the Date column and filters out
    look-ahead rows, but we re-apply the cutoff defensively — this is a
    verification path, so it must not trust its input to be pre-filtered.
    """
    normalized = normalize_ticker_symbol(symbol)
    if detect_market_type(normalized) == MarketType.CN_FUND:
        data = get_fund_nav_history(normalized, None, curr_date)
        no_data_label = "NAV"
    else:
        data = load_ohlcv(symbol, curr_date)
        no_data_label = "OHLCV"
    if data is None or data.empty:
        raise ValueError(f"No {no_data_label} data available for {symbol}.")

    df = data.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df = df[df["Date"] <= pd.to_datetime(curr_date)].sort_values("Date")
    if df.empty:
        raise ValueError(f"No {no_data_label} rows on or before {curr_date} for {symbol}.")
    return df


def _fmt(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def build_verified_market_snapshot(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    indicators: Optional[Iterable[str]] = None,
) -> str:
    """Render a ground-truth snapshot: latest OHLCV row, indicators, recent closes."""
    # `df` keeps the original capitalized OHLCV columns (Open/High/Low/Close/
    # Volume); stockstats `wrap()` lowercases columns and adds indicator
    # columns, so read raw prices from `df` and indicators from `stock_df`.
    normalized_symbol = normalize_ticker_symbol(symbol)
    is_otc_fund = detect_market_type(normalized_symbol) == MarketType.CN_FUND
    df = _verified_rows(normalized_symbol, curr_date)
    stock_df = wrap(df.copy())

    selected = tuple(indicators or DEFAULT_SNAPSHOT_INDICATORS)
    indicator_values: dict[str, str] = {}
    for name in selected:
        try:
            stock_df[name]  # triggers stockstats calculation
            indicator_values[name] = _fmt(stock_df.iloc[-1][name])
        except Exception as exc:  # noqa: BLE001 — one bad indicator shouldn't sink the snapshot
            indicator_values[name] = f"N/A ({type(exc).__name__})"

    latest = df.iloc[-1]
    latest_date = _fmt(latest["Date"])
    window = max(1, min(int(look_back_days), 30))
    recent = df.tail(window)

    lines = [
        (
            f"## Verified fund NAV snapshot for {normalized_symbol.upper()}"
            if is_otc_fund
            else f"## Verified market data snapshot for {symbol.upper()}"
        ),
        "",
        f"- Requested analysis date: {curr_date}",
        (
            f"- Latest NAV row used: {latest_date}"
            if is_otc_fund
            else f"- Latest trading row used: {latest_date}"
        ),
        "- Rows after the requested analysis date are excluded before verification.",
        "",
        "### Latest verified NAV row" if is_otc_fund else "### Latest verified OHLCV row",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    if is_otc_fund:
        lines.append(f"| NAV | {_fmt(latest.get('Close'))} |")
        if "Pct Change" in latest:
            lines.append(f"| NAV return (%) | {_fmt(latest.get('Pct Change'))} |")
    else:
        for field in ("Open", "High", "Low", "Close", "Volume"):
            lines.append(f"| {field} | {_fmt(latest.get(field))} |")

    lines += ["", "### Verified technical indicators (latest row)", "",
              "| Indicator | Value |", "|---|---:|"]
    for name, value in indicator_values.items():
        lines.append(f"| {name} | {value} |")

    recent_title = "Recent verified NAVs" if is_otc_fund else "Recent verified closes"
    value_title = "NAV" if is_otc_fund else "Close"
    lines += ["", f"### {recent_title} (last {len(recent)} rows)", "",
              f"| Date | {value_title} |", "|---|---:|"]
    for _, row in recent.iterrows():
        lines.append(f"| {_fmt(row['Date'])} | {_fmt(row.get('Close'))} |")

    if is_otc_fund:
        lines += [
            "",
            "Use this snapshot as the source of truth for exact NAV and indicator-value claims. "
            "This OTC fund snapshot is based on daily fund NAV, not exchange-traded OHLCV or volume. "
            "If another tool output conflicts with it, flag the discrepancy rather than inventing "
            "a reconciled number.",
        ]
    else:
        lines += [
            "",
            "Use this snapshot as the source of truth for exact OHLCV, price-level, "
            "and indicator-value claims. If another tool output conflicts with it, "
            "flag the discrepancy rather than inventing a reconciled number. Do not "
            "claim historical validation, support/resistance bounces, or exact "
            "percentage moves unless directly supported by tool output with concrete "
            "dates and prices.",
        ]
    return "\n".join(lines)
