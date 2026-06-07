"""Live acceptance matrix for China-market localization.

This script intentionally performs real network calls. It is not part of the
pytest suite because AkShare, Tiantian Fund, and upstream news providers can be
unavailable or rate limited.

Usage:
    python scripts/smoke_akshare_live.py
    python scripts/smoke_akshare_live.py --end-date 2026-05-22
    python scripts/smoke_akshare_live.py --matrix-out china_market_matrix.md
"""

from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Sequence

import tradingagents.default_config as default_config
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.instruments import (
    InstrumentType,
    MarketType,
    detect_instrument_type,
    detect_market_type,
    normalize_ticker_symbol,
)
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.market_data_validator import build_verified_market_snapshot
from tradingagents.graph.propagation import Propagator


STATUS_OK = "OK"
STATUS_FAIL = "FAIL"

DEFAULT_TARGETS = ("600519", "000001", "510300", "159915", "012920")
DEFAULT_QDII_CANDIDATES = ("012920",)
PRICE_MARKERS = ("Date,Open,High,Low,Close,Volume",)
INDICATOR_MARKERS = ("## rsi values", "RSI:")


@dataclass(frozen=True)
class SmokeTarget:
    symbol: str
    label: str
    expected_market: MarketType
    expected_instrument: InstrumentType
    fundamentals_markers: tuple[str, ...]
    news_markers_any: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class SmokeResult:
    symbol: str
    label: str
    normalized: str
    market: str
    instrument: str
    capability: str
    status: str
    detail: str


TARGET_DEFINITIONS = {
    "600519": SmokeTarget(
        symbol="600519",
        label="A-share equity",
        expected_market=MarketType.CN_A,
        expected_instrument=InstrumentType.EQUITY,
        fundamentals_markers=("A-share Company Fundamentals", "Company Profile"),
        news_markers_any=("News", "No AkShare news found"),
    ),
    "000001": SmokeTarget(
        symbol="000001",
        label="A-share equity",
        expected_market=MarketType.CN_A,
        expected_instrument=InstrumentType.EQUITY,
        fundamentals_markers=("A-share Company Fundamentals", "Company Profile"),
        news_markers_any=("News", "No AkShare news found"),
    ),
    "510300": SmokeTarget(
        symbol="510300",
        label="China listed fund",
        expected_market=MarketType.CN_A,
        expected_instrument=InstrumentType.FUND,
        fundamentals_markers=("Listed Fund Profile", "Fund analysis focus"),
        news_markers_any=("Listed Fund Announcements", "No AkShare listed fund announcements found"),
    ),
    "159915": SmokeTarget(
        symbol="159915",
        label="China listed fund",
        expected_market=MarketType.CN_A,
        expected_instrument=InstrumentType.FUND,
        fundamentals_markers=("Listed Fund Profile", "Fund analysis focus"),
        news_markers_any=("Listed Fund Announcements", "No AkShare listed fund announcements found"),
    ),
    "012920": SmokeTarget(
        symbol="012920",
        label="China OTC fund / QDII sample",
        expected_market=MarketType.CN_FUND,
        expected_instrument=InstrumentType.FUND,
        fundamentals_markers=("China OTC Fund Profile", "Fund analysis focus"),
        news_markers_any=(
            "Otc Fund Announcements",
            "No AkShare OTC fund announcements found",
            "No Tiantian Fund",
        ),
        notes="Recognized as an OTC fund by ticker rules; use live fund profile data to confirm QDII-specific wording.",
    ),
}


def _default_end_date() -> str:
    return date.today().isoformat()


def _start_date(end_date: str, days: int) -> str:
    return (date.fromisoformat(end_date) - timedelta(days=days)).isoformat()


def _configure_akshare_routes() -> None:
    """Force all dataflow categories through AkShare for China-market smoke."""
    config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    config["data_vendors"] = {
        "core_stock_apis": "akshare",
        "technical_indicators": "akshare",
        "fundamental_data": "akshare",
        "news_data": "akshare",
    }
    config["tool_vendors"] = {
        "get_stock_data": "akshare",
        "get_indicators": "akshare",
        "get_fundamentals": "akshare",
        "get_news": "akshare",
        "get_global_news": "akshare",
    }
    set_config(config)


def _target_for_symbol(symbol: str) -> SmokeTarget:
    normalized = normalize_ticker_symbol(symbol)
    pure_symbol = normalized.split(".", 1)[0]
    if pure_symbol in TARGET_DEFINITIONS:
        return TARGET_DEFINITIONS[pure_symbol]
    market = detect_market_type(normalized)
    instrument = detect_instrument_type(normalized)
    if instrument == InstrumentType.FUND and market == MarketType.CN_FUND:
        return SmokeTarget(
            symbol=symbol,
            label="China OTC fund",
            expected_market=market,
            expected_instrument=instrument,
            fundamentals_markers=("China OTC Fund Profile", "Fund analysis focus"),
            news_markers_any=("Otc Fund Announcements", "No AkShare OTC fund announcements found", "No Tiantian Fund"),
        )
    if instrument == InstrumentType.FUND:
        return SmokeTarget(
            symbol=symbol,
            label="China listed fund",
            expected_market=market,
            expected_instrument=instrument,
            fundamentals_markers=("Listed Fund Profile", "Fund analysis focus"),
            news_markers_any=("Listed Fund Announcements", "No AkShare listed fund announcements found"),
        )
    return SmokeTarget(
        symbol=symbol,
        label="A-share equity" if market == MarketType.CN_A else "Custom target",
        expected_market=market,
        expected_instrument=instrument,
        fundamentals_markers=("A-share Company Fundamentals", "Company Profile")
        if market == MarketType.CN_A
        else (),
        news_markers_any=("News", "No AkShare news found") if market == MarketType.CN_A else (),
    )


def _build_targets(symbols: Sequence[str], qdii_symbols: Sequence[str]) -> list[SmokeTarget]:
    ordered: list[str] = []
    for symbol in tuple(symbols) + tuple(qdii_symbols):
        if symbol not in ordered:
            ordered.append(symbol)
    return [_target_for_symbol(symbol) for symbol in ordered]


def _result(
    target: SmokeTarget,
    normalized: str,
    capability: str,
    status: str,
    detail: str,
) -> SmokeResult:
    market = detect_market_type(normalized).value
    instrument = detect_instrument_type(normalized).value
    return SmokeResult(
        symbol=target.symbol,
        label=target.label,
        normalized=normalized,
        market=market,
        instrument=instrument,
        capability=capability,
        status=status,
        detail=detail,
    )


def _check_required_markers(
    target: SmokeTarget,
    normalized: str,
    capability: str,
    text: str,
    markers: tuple[str, ...],
) -> SmokeResult:
    if not text or not text.strip():
        return _result(target, normalized, capability, STATUS_FAIL, "empty response")
    missing = [marker for marker in markers if marker not in text]
    if missing:
        return _result(target, normalized, capability, STATUS_FAIL, f"missing marker(s): {', '.join(missing)}")
    return _result(target, normalized, capability, STATUS_OK, "required marker(s) present")


def _check_any_marker(
    target: SmokeTarget,
    normalized: str,
    capability: str,
    text: str,
    markers: tuple[str, ...],
) -> SmokeResult:
    if not text or not text.strip():
        return _result(target, normalized, capability, STATUS_FAIL, "empty response")
    if markers and not any(marker in text for marker in markers):
        return _result(target, normalized, capability, STATUS_FAIL, f"missing any marker: {', '.join(markers)}")
    return _result(target, normalized, capability, STATUS_OK, "response present")


def _check_identity(target: SmokeTarget, normalized: str) -> SmokeResult:
    market = detect_market_type(normalized)
    instrument = detect_instrument_type(normalized)
    expected = f"{target.expected_market.value}/{target.expected_instrument.value}"
    observed = f"{market.value}/{instrument.value}"
    if market != target.expected_market or instrument != target.expected_instrument:
        return _result(target, normalized, "identity", STATUS_FAIL, f"expected {expected}, got {observed}")
    return _result(target, normalized, "identity", STATUS_OK, observed)


def _check_graph_state(target: SmokeTarget, normalized: str, end_date: str) -> SmokeResult:
    state = Propagator().create_initial_state(normalized, end_date)
    expected_market = target.expected_market.value
    expected_instrument = target.expected_instrument.value
    if state.get("market_type") != expected_market or state.get("instrument_type") != expected_instrument:
        detail = (
            f"expected market_type={expected_market}, instrument_type={expected_instrument}; "
            f"got market_type={state.get('market_type')}, instrument_type={state.get('instrument_type')}"
        )
        return _result(target, normalized, "graph_state", STATUS_FAIL, detail)
    display = state.get("company_display_name") or normalized
    return _result(target, normalized, "graph_state", STATUS_OK, f"display={display}")


def _call_capability(target: SmokeTarget, normalized: str, capability: str, func) -> SmokeResult:
    try:
        return func()
    except Exception as exc:  # noqa: BLE001 - live smoke should report every upstream failure.
        return _result(target, normalized, capability, STATUS_FAIL, f"{type(exc).__name__}: {exc}")


def run_target_matrix(
    target: SmokeTarget,
    end_date: str,
    lookback_days: int,
    include_snapshot: bool = True,
    include_graph_state: bool = True,
) -> list[SmokeResult]:
    normalized = normalize_ticker_symbol(target.symbol)
    start_date = _start_date(end_date, lookback_days)
    results = [_check_identity(target, normalized)]

    results.append(
        _call_capability(
            target,
            normalized,
            "route_price",
            lambda: _check_required_markers(
                target,
                normalized,
                "route_price",
                route_to_vendor("get_stock_data", target.symbol, start_date, end_date),
                PRICE_MARKERS,
            ),
        )
    )
    results.append(
        _call_capability(
            target,
            normalized,
            "indicators",
            lambda: _check_required_markers(
                target,
                normalized,
                "indicators",
                route_to_vendor("get_indicators", target.symbol, "rsi", end_date, 10),
                INDICATOR_MARKERS,
            ),
        )
    )
    results.append(
        _call_capability(
            target,
            normalized,
            "fundamentals",
            lambda: _check_required_markers(
                target,
                normalized,
                "fundamentals",
                route_to_vendor("get_fundamentals", target.symbol, end_date),
                target.fundamentals_markers,
            ),
        )
    )
    results.append(
        _call_capability(
            target,
            normalized,
            "news",
            lambda: _check_any_marker(
                target,
                normalized,
                "news",
                route_to_vendor("get_news", target.symbol, start_date, end_date),
                target.news_markers_any,
            ),
        )
    )

    if include_snapshot:
        snapshot_markers = (
            ("Verified fund NAV snapshot",)
            if target.expected_market == MarketType.CN_FUND
            else ("Verified market data snapshot",)
        )
        results.append(
            _call_capability(
                target,
                normalized,
                "verified_snapshot",
                lambda: _check_required_markers(
                    target,
                    normalized,
                    "verified_snapshot",
                    build_verified_market_snapshot(target.symbol, end_date, look_back_days=lookback_days),
                    snapshot_markers,
                ),
            )
        )

    if include_graph_state:
        results.append(
            _call_capability(
                target,
                normalized,
                "graph_state",
                lambda: _check_graph_state(target, normalized, end_date),
            )
        )

    return results


def run_macro_matrix(end_date: str, lookback_days: int, limit: int) -> SmokeResult:
    target = SmokeTarget(
        symbol="GLOBAL",
        label="China macro and policy news",
        expected_market=MarketType.OTHER,
        expected_instrument=InstrumentType.UNKNOWN,
        fundamentals_markers=(),
    )
    try:
        text = route_to_vendor("get_global_news", end_date, lookback_days, limit)
        if not text or not text.strip():
            return _result(target, "GLOBAL", "macro_news", STATUS_FAIL, "empty response")
        markers = ("China Macro", "macro", "policy", "No AkShare China macro/policy news")
        if not any(marker in text for marker in markers):
            return _result(target, "GLOBAL", "macro_news", STATUS_FAIL, "missing macro/policy marker")
        return _result(target, "GLOBAL", "macro_news", STATUS_OK, "response present")
    except Exception as exc:  # noqa: BLE001 - live smoke should report upstream provider failures.
        return _result(target, "GLOBAL", "macro_news", STATUS_FAIL, f"{type(exc).__name__}: {exc}")


def run_matrix(
    targets: Sequence[SmokeTarget],
    end_date: str,
    lookback_days: int,
    include_macro: bool = True,
    macro_limit: int = 10,
    include_snapshot: bool = True,
    include_graph_state: bool = True,
) -> list[SmokeResult]:
    _configure_akshare_routes()
    results: list[SmokeResult] = []
    for target in targets:
        results.extend(
            run_target_matrix(
                target,
                end_date,
                lookback_days,
                include_snapshot=include_snapshot,
                include_graph_state=include_graph_state,
            )
        )
    if include_macro:
        results.append(run_macro_matrix(end_date, lookback_days, macro_limit))
    return results


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_markdown(results: Sequence[SmokeResult], end_date: str, lookback_days: int) -> str:
    lines = [
        "# China Market Localization Acceptance Matrix",
        "",
        f"- End date: {end_date}",
        f"- Lookback days: {lookback_days}",
        "- Vendor route: AkShare for price, indicators, fundamentals, news, and macro news",
        "",
        "| Symbol | Label | Normalized | Market | Instrument | Capability | Status | Detail |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            "| "
            + " | ".join(
                _escape_cell(value)
                for value in (
                    result.symbol,
                    result.label,
                    result.normalized,
                    result.market,
                    result.instrument,
                    result.capability,
                    result.status,
                    result.detail,
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Legend",
            "",
            "- OK: observed output matched the deterministic marker for that capability.",
            "- FAIL: the vendor, routing layer, snapshot builder, or graph state did not meet the marker.",
        ]
    )
    return "\n".join(lines) + "\n"


def print_results(results: Sequence[SmokeResult]) -> None:
    print("\nChina market localization acceptance matrix")
    print("=" * 100)
    for result in results:
        print(
            f"{result.status:<4} {result.symbol:<8} {result.normalized:<10} "
            f"{result.market:<8} {result.instrument:<8} {result.capability:<18} {result.detail}"
        )


def _parse_symbols(raw: str | None, fallback: Iterable[str]) -> tuple[str, ...]:
    if not raw:
        return tuple(fallback)
    return tuple(symbol.strip() for symbol in raw.split(",") if symbol.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", default=_default_end_date(), help="YYYY-MM-DD end date")
    parser.add_argument("--lookback-days", type=int, default=10)
    parser.add_argument(
        "--symbols",
        help="Comma-separated target symbols. Defaults to A-share equity, listed funds, and OTC fund samples.",
    )
    parser.add_argument(
        "--qdii-symbols",
        help="Comma-separated QDII or overseas-exposure OTC fund symbols to include in addition to --symbols.",
    )
    parser.add_argument("--matrix-out", help="Write a Markdown acceptance matrix to this path")
    parser.add_argument("--skip-macro", action="store_true", help="Skip China macro/policy news check")
    parser.add_argument("--skip-snapshot", action="store_true", help="Skip verified market snapshot check")
    parser.add_argument("--skip-graph-state", action="store_true", help="Skip graph initial state check")
    parser.add_argument("--macro-limit", type=int, default=10)
    args = parser.parse_args()

    symbols = _parse_symbols(args.symbols, DEFAULT_TARGETS)
    qdii_symbols = _parse_symbols(args.qdii_symbols, DEFAULT_QDII_CANDIDATES)
    targets = _build_targets(symbols, qdii_symbols)
    results = run_matrix(
        targets,
        args.end_date,
        args.lookback_days,
        include_macro=not args.skip_macro,
        macro_limit=args.macro_limit,
        include_snapshot=not args.skip_snapshot,
        include_graph_state=not args.skip_graph_state,
    )
    print_results(results)

    if args.matrix_out:
        output_path = Path(args.matrix_out)
        output_path.write_text(render_markdown(results, args.end_date, args.lookback_days), encoding="utf-8")
        print(f"\nWrote matrix: {output_path}")

    failures = [result for result in results if result.status == STATUS_FAIL]
    print("\n" + "=" * 100)
    if failures:
        print(f"China market localization smoke FAILED with {len(failures)} failure(s).")
        return 1
    print("China market localization smoke PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
