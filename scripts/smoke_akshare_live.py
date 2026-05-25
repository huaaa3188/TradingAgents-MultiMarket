"""Live smoke test for the AkShare dataflow.

This script intentionally performs real network calls. It is not part of the
pytest suite because AkShare and upstream data providers can be unavailable or
rate limited.

Usage:
    python scripts/smoke_akshare_live.py
    python scripts/smoke_akshare_live.py --end-date 2026-05-22
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from tradingagents.dataflows.akshare import (
    AkShareDataError,
    get_fundamentals,
    get_indicator,
    get_news,
    get_stock,
)
from tradingagents.dataflows.instruments import (
    InstrumentType,
    detect_instrument_type,
    normalize_ticker_symbol,
)


EQUITY_SYMBOLS = ("600519",)
FUND_SYMBOLS = ("510300", "159915", "159696")


def _default_end_date() -> str:
    return date.today().isoformat()


def _start_date(end_date: str, days: int) -> str:
    return (date.fromisoformat(end_date) - timedelta(days=days)).isoformat()


def _check_contains(name: str, text: str, markers: tuple[str, ...]) -> list[str]:
    missing = [marker for marker in markers if marker not in text]
    status = "PASS" if not missing else "FAIL"
    print(f"{status} {name}")
    if missing:
        for marker in missing:
            print(f"  missing: {marker!r}")
    return missing


def _check_not_empty(name: str, text: str) -> list[str]:
    if text and text.strip():
        print(f"PASS {name}")
        return []
    print(f"FAIL {name}")
    print("  empty response")
    return ["empty response"]


def _run_symbol(symbol: str, end_date: str, lookback_days: int) -> int:
    normalized = normalize_ticker_symbol(symbol)
    instrument = detect_instrument_type(normalized)
    start_date = _start_date(end_date, lookback_days)
    failures = 0

    print("\n" + "=" * 72)
    print(f"{symbol} -> {normalized} ({instrument.value}) from {start_date} to {end_date}")
    print("=" * 72)

    try:
        stock_text = get_stock(symbol, start_date, end_date)
        failures += len(_check_contains("OHLCV", stock_text, ("Date,Open,High,Low,Close,Volume",)))

        indicator_text = get_indicator(symbol, "rsi", end_date, look_back_days=10)
        failures += len(_check_contains("RSI indicator", indicator_text, ("## rsi values", "RSI:")))

        fundamentals_text = get_fundamentals(symbol, end_date)
        if instrument == InstrumentType.FUND:
            failures += len(
                _check_contains(
                    "Fund profile",
                    fundamentals_text,
                    ("Listed Fund Profile", "Overview", "Fees", "Top Holdings"),
                )
            )
        else:
            failures += len(
                _check_contains(
                    "A-share fundamentals",
                    fundamentals_text,
                    ("A-share Company Fundamentals", "Company Profile"),
                )
            )

        news_text = get_news(symbol, start_date, end_date)
        failures += len(_check_not_empty("News or announcement context", news_text))
        if instrument == InstrumentType.FUND:
            expected_news_markers = (
                "Listed Fund Announcements",
                "No AkShare listed fund announcements found",
            )
            if not any(marker in news_text for marker in expected_news_markers):
                failures += 1
                print("FAIL Fund announcement context")
                print("  missing listed fund announcement heading or fallback text")
            else:
                print("PASS Fund announcement context")
    except AkShareDataError as exc:
        failures += 1
        print(f"FAIL AkShare data error: {exc}")
    except Exception as exc:
        failures += 1
        print(f"FAIL unexpected error: {type(exc).__name__}: {exc}")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", default=_default_end_date(), help="YYYY-MM-DD end date")
    parser.add_argument("--lookback-days", type=int, default=10)
    args = parser.parse_args()

    total_failures = 0
    for symbol in EQUITY_SYMBOLS + FUND_SYMBOLS:
        total_failures += _run_symbol(symbol, args.end_date, args.lookback_days)

    print("\n" + "=" * 72)
    if total_failures:
        print(f"AkShare live smoke FAILED with {total_failures} failure(s).")
        return 1
    print("AkShare live smoke PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
