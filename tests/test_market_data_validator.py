"""Tests for the deterministic market-data verification snapshot (#830/#881)."""

from __future__ import annotations

import pandas as pd
import pytest

import tradingagents.dataflows.market_data_validator as validator
from tradingagents.dataflows.contracts import DataResult, SourceMeta, data_notice


def _sample_ohlcv() -> pd.DataFrame:
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    return pd.DataFrame({
        "Date": dates,
        "Open": [c - 0.5 for c in closes],
        "High": [c + 1.0 for c in closes],
        "Low": [c - 1.0 for c in closes],
        "Close": closes,
        "Volume": [1_000_000 + i for i in range(len(dates))],
    })


def _contract_result(
    symbol: str,
    semantic: str,
    data: pd.DataFrame,
    *,
    as_of: str | None = None,
    ok: bool = True,
    missing_reason: str | None = None,
    error_type: str | None = None,
    notices=(),
) -> DataResult:
    parsed = pd.to_datetime(data.get("Date"), errors="coerce").dropna() if not data.empty else pd.Series(dtype="datetime64[ns]")
    return DataResult(
        meta=SourceMeta(
            vendor="akshare",
            source=f"fake_{semantic}",
            symbol=symbol,
            semantic=semantic,
            as_of=as_of if as_of is not None else (None if parsed.empty else parsed.max().strftime("%Y-%m-%d")),
            retrieved_at="2026-05-22 12:00:00",
        ),
        payload=data,
        notices=tuple(notices),
        ok=ok,
        missing_reason=missing_reason,
        error_type=error_type,
    )


@pytest.mark.unit
class TestVerifiedSnapshot:
    def test_excludes_future_rows(self, monkeypatch):
        data = pd.concat([
            _sample_ohlcv(),
            pd.DataFrame({"Date": [pd.Timestamp("2026-06-01")], "Open": [999.0],
                          "High": [999.0], "Low": [999.0], "Close": [999.0], "Volume": [999]}),
        ], ignore_index=True)
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: data)

        snap = validator.build_verified_market_snapshot("COF", "2026-05-13")
        assert "Verified market data snapshot for COF" in snap
        assert "Requested analysis date: 2026-05-13" in snap
        assert "Latest trading row used: 2026-05-13" in snap
        assert "999.00" not in snap          # future row excluded
        assert "boll_lb" in snap             # indicators present

    def test_uses_previous_trading_day_when_date_is_weekend(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        # 2026-05-16 is a Saturday; latest row should be Fri 2026-05-15
        snap = validator.build_verified_market_snapshot("COF", "2026-05-16")
        assert "Latest trading row used: 2026-05-15" in snap
        assert "Recent verified closes" in snap

    def test_raises_when_no_rows_on_or_before_date(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        with pytest.raises(ValueError):
            validator.build_verified_market_snapshot("COF", "2020-01-01")

    def test_raises_on_empty_data(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: pd.DataFrame())
        with pytest.raises(ValueError):
            validator.build_verified_market_snapshot("COF", "2026-05-13")

    def test_look_back_window_capped_at_30(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        snap = validator.build_verified_market_snapshot("COF", "2026-05-20", look_back_days=999)
        # last-N closes table has at most 30 data rows
        close_rows = [ln for ln in snap.splitlines() if ln.startswith("| 2026-")]
        assert 0 < len(close_rows) <= 30

    def test_cn_otc_fund_snapshot_uses_nav_history(self, monkeypatch):
        nav_data = pd.DataFrame(
            [
                {"Date": "2026-05-20", "Close": 4.5, "Open": 4.5, "High": 4.5, "Low": 4.5, "Volume": 0},
                {"Date": "2026-05-21", "Close": 4.6, "Open": 4.6, "High": 4.6, "Low": 4.6, "Volume": 0},
                {"Date": "2026-06-01", "Close": 9.9, "Open": 9.9, "High": 9.9, "Low": 9.9, "Volume": 0},
            ]
        )
        monkeypatch.setattr(
            validator,
            "load_ohlcv",
            lambda s, d: (_ for _ in ()).throw(AssertionError("yfinance loader should not be called")),
        )
        monkeypatch.setattr(
            validator,
            "get_stock_result",
            lambda symbol, start, end: _contract_result(symbol, "nav", nav_data, as_of="2026-05-21"),
        )

        snap = validator.build_verified_market_snapshot("012920", "2026-05-21")

        assert "Verified fund NAV snapshot for 012920" in snap
        assert "Latest NAV row used: 2026-05-21" in snap
        assert "Verified Market Data Contract Gate" in snap
        assert "daily fund NAV" in snap
        assert "| NAV | 4.60 |" in snap
        assert "9.90" not in snap

    def test_cn_a_equity_snapshot_uses_akshare_ohlcv(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            validator,
            "load_ohlcv",
            lambda s, d: (_ for _ in ()).throw(AssertionError("yfinance loader should not be called")),
        )
        monkeypatch.setattr(
            validator,
            "get_stock_result",
            lambda symbol, start, end: calls.append((symbol, start, end))
            or _contract_result(symbol, "ohlcv", _sample_ohlcv()),
        )

        snap = validator.build_verified_market_snapshot("600519", "2026-05-20")

        assert calls == [("600519.SH", "2021-05-20", "2026-05-20")]
        assert "Verified market data snapshot for 600519" in snap
        assert "Verified Market Data Contract Gate" in snap
        assert "Latest trading row used: 2026-05-20" in snap

    def test_cn_listed_fund_snapshot_uses_akshare_ohlcv(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            validator,
            "load_ohlcv",
            lambda s, d: (_ for _ in ()).throw(AssertionError("yfinance loader should not be called")),
        )
        monkeypatch.setattr(
            validator,
            "get_stock_result",
            lambda symbol, start, end: calls.append((symbol, start, end))
            or _contract_result(symbol, "ohlcv", _sample_ohlcv()),
        )

        snap = validator.build_verified_market_snapshot("510300", "2026-05-20")

        assert calls == [("510300.SH", "2021-05-20", "2026-05-20")]
        assert "Verified market data snapshot for 510300" in snap
        assert "Recent verified closes" in snap

    def test_cn_snapshot_blocks_schema_drift_contract(self, monkeypatch):
        monkeypatch.setattr(
            validator,
            "load_ohlcv",
            lambda s, d: (_ for _ in ()).throw(AssertionError("yfinance loader should not be called")),
        )
        monkeypatch.setattr(
            validator,
            "get_stock_result",
            lambda symbol, start, end: _contract_result(
                symbol,
                "ohlcv",
                _sample_ohlcv(),
                error_type="schema_drift",
                notices=(data_notice("schema_drift", "drift"),),
            ),
        )

        with pytest.raises(ValueError, match="schema_drift"):
            validator.build_verified_market_snapshot("600519", "2026-05-20")


@pytest.mark.unit
class TestTool:
    def test_tool_delegates_to_builder(self, monkeypatch):
        from tradingagents.agents.utils.market_data_validation_tools import (
            get_verified_market_snapshot,
        )
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        out = get_verified_market_snapshot.invoke(
            {"symbol": "COF", "curr_date": "2026-05-20"}
        )
        assert "Verified market data snapshot for COF" in out
