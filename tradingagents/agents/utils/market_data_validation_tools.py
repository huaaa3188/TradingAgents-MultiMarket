from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.market_data_validator import build_verified_market_snapshot


@tool
def get_verified_market_snapshot(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "the current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[
        int, "number of recent trading rows to include for sanity-checking"
    ] = 30,
) -> str:
    """Deterministic verification snapshot and data-contract gate.

    Returns the latest verified OHLCV or NAV row on or before curr_date, common
    technical indicators, recent closes/NAVs, and China data-contract status
    when available. Call this before making exact claims about price levels,
    NAVs, Bollinger bands, RSI, MACD, moving averages, support / resistance, or
    historical comparisons, and treat a failed gate as unusable data.
    """
    return build_verified_market_snapshot(symbol, curr_date, look_back_days)
