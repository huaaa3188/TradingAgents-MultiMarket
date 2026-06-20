from __future__ import annotations

import pytest

import tradingagents.default_config as default_config
from scripts import smoke_akshare_live as smoke
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.contracts import DataResult, SourceMeta, data_notice


@pytest.fixture(autouse=True)
def reset_dataflow_config():
    set_config(default_config.DEFAULT_CONFIG.copy())
    yield
    set_config(default_config.DEFAULT_CONFIG.copy())


class FakePropagator:
    def create_initial_state(self, company_name: str, trade_date: str):
        return {
            "company_display_name": f"display:{company_name}",
            "market_type": smoke.detect_market_type(company_name).value,
            "instrument_type": smoke.detect_instrument_type(company_name).value,
        }


def _fake_snapshot(symbol: str, curr_date: str, look_back_days: int = 30):
    if smoke.detect_market_type(symbol) == smoke.MarketType.CN_FUND:
        return f"## Verified fund NAV snapshot for {symbol}"
    return f"## Verified market data snapshot for {symbol}"


def _fake_contract_result(
    symbol: str,
    semantic: str = "ohlcv",
    ok: bool = True,
    *,
    missing_reason: str | None = None,
    error_type: str | None = None,
    notices=(),
):
    return DataResult(
        meta=SourceMeta(
            vendor="akshare",
            source=f"fake_{semantic}",
            symbol=symbol,
            semantic=semantic,
            as_of="2026-05-22",
            retrieved_at="2026-05-22 12:00:00",
        ),
        payload="contract payload",
        notices=tuple(notices),
        ok=ok,
        missing_reason=missing_reason if missing_reason is not None else (None if ok else "no_rows"),
        error_type=error_type,
    )


def _fake_price_contract(symbol: str):
    semantic = "nav" if smoke.detect_market_type(symbol) == smoke.MarketType.CN_FUND else "ohlcv"
    return _fake_contract_result(symbol, semantic)


def _fake_fundamentals_contract(symbol: str):
    semantic = (
        "fund_profile"
        if smoke.detect_instrument_type(symbol) == smoke.InstrumentType.FUND
        else "company_profile"
    )
    return _fake_contract_result(symbol, semantic)


def _successful_route(method: str, *args):
    symbol = str(args[0]) if args else ""
    normalized = smoke.normalize_ticker_symbol(symbol) if symbol else symbol

    if method == "get_stock_data":
        return "# AkShare data\nDate,Open,High,Low,Close,Volume\n2026-05-22,1,2,1,2,100"
    if method == "get_indicators":
        return "## rsi values from 2026-05-12 to 2026-05-22:\nRSI: relative strength index"
    if method == "get_fundamentals":
        if smoke.detect_market_type(normalized) == smoke.MarketType.CN_FUND:
            return "# China OTC Fund Profile\nFund analysis focus: NAV and QDII/FX risk"
        if smoke.detect_instrument_type(normalized) == smoke.InstrumentType.FUND:
            return "# Listed Fund Profile\nFund analysis focus: benchmark/theme exposure"
        return "# A-share Company Fundamentals\nCompany Profile\nFinancial Abstract"
    if method == "get_news":
        if smoke.detect_market_type(normalized) == smoke.MarketType.CN_FUND:
            return "No AkShare OTC fund announcements found"
        if smoke.detect_instrument_type(normalized) == smoke.InstrumentType.FUND:
            return "No AkShare listed fund announcements found"
        return "## News\nNo AkShare news found"
    if method == "get_global_news":
        return "## China Macro and Policy News\npolicy update"
    raise AssertionError(f"unexpected method: {method}")


def test_default_targets_deduplicate_qdii_sample():
    targets = smoke._build_targets(("600519", "012920"), ("012920",))

    assert [target.symbol for target in targets] == ["600519", "012920"]
    assert targets[0].expected_market == smoke.MarketType.CN_A
    assert targets[1].expected_market == smoke.MarketType.CN_FUND
    assert targets[1].expected_instrument == smoke.InstrumentType.FUND


def test_run_matrix_reports_all_capabilities_ok(monkeypatch):
    monkeypatch.setattr(smoke, "route_to_vendor", _successful_route)
    monkeypatch.setattr(smoke, "build_verified_market_snapshot", _fake_snapshot)
    monkeypatch.setattr(smoke, "Propagator", FakePropagator)
    monkeypatch.setattr(smoke, "get_stock_result", lambda symbol, start, end: _fake_price_contract(symbol))
    monkeypatch.setattr(
        smoke,
        "get_fundamentals_result",
        lambda symbol, end: _fake_fundamentals_contract(symbol),
    )
    monkeypatch.setattr(smoke, "get_news_result", lambda symbol, start, end: _fake_contract_result(symbol, "news"))

    targets = smoke._build_targets(("600519", "510300", "012920"), ())
    results = smoke.run_matrix(targets, "2026-05-22", 10)

    assert all(result.status == smoke.STATUS_OK for result in results)
    assert {result.capability for result in results} == {
        "identity",
        "route_price",
        "indicators",
        "fundamentals",
        "news",
        "data_contract",
        "verified_snapshot",
        "graph_state",
        "macro_news",
    }
    assert any(result.symbol == "GLOBAL" and result.capability == "macro_news" for result in results)


def test_data_contract_marks_schema_drift_failed(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "get_stock_result",
        lambda symbol, start, end: _fake_contract_result(
            symbol,
            "ohlcv",
            error_type="schema_drift",
            notices=(data_notice("schema_drift", "drift"),),
        ),
    )
    monkeypatch.setattr(
        smoke,
        "get_fundamentals_result",
        lambda symbol, end: _fake_contract_result(symbol, "company_profile"),
    )
    monkeypatch.setattr(smoke, "get_news_result", lambda symbol, start, end: _fake_contract_result(symbol, "news"))

    target = smoke._build_targets(("600519",), ())[0]
    result = smoke._check_data_contract(target, "600519.SH", "2026-05-12", "2026-05-22")

    assert result.status == smoke.STATUS_FAIL
    assert "schema_drift" in result.detail


def test_data_contract_marks_missing_result_failed(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "get_stock_result",
        lambda symbol, start, end: _fake_contract_result(symbol, "ohlcv", ok=False, missing_reason="no_rows"),
    )
    monkeypatch.setattr(
        smoke,
        "get_fundamentals_result",
        lambda symbol, end: _fake_contract_result(symbol, "company_profile"),
    )
    monkeypatch.setattr(smoke, "get_news_result", lambda symbol, start, end: _fake_contract_result(symbol, "news"))

    target = smoke._build_targets(("600519",), ())[0]
    result = smoke._check_data_contract(target, "600519.SH", "2026-05-12", "2026-05-22")

    assert result.status == smoke.STATUS_FAIL
    assert "no_rows" in result.detail


def test_data_contract_marks_optional_news_unavailable_warning(monkeypatch):
    monkeypatch.setattr(smoke, "get_stock_result", lambda symbol, start, end: _fake_contract_result(symbol, "ohlcv"))
    monkeypatch.setattr(
        smoke,
        "get_fundamentals_result",
        lambda symbol, end: _fake_contract_result(symbol, "company_profile"),
    )
    monkeypatch.setattr(
        smoke,
        "get_news_result",
        lambda symbol, start, end: _fake_contract_result(
            symbol,
            "news",
            ok=False,
            missing_reason="no_news",
        ),
    )

    target = smoke._build_targets(("600519",), ())[0]
    result = smoke._check_data_contract(target, "600519.SH", "2026-05-12", "2026-05-22")

    assert result.status == smoke.STATUS_WARN
    assert "news=fail:no_news" in result.detail


def test_missing_marker_marks_capability_failed(monkeypatch):
    def route_with_bad_price(method: str, *args):
        if method == "get_stock_data":
            return "no csv header"
        return _successful_route(method, *args)

    monkeypatch.setattr(smoke, "route_to_vendor", route_with_bad_price)
    monkeypatch.setattr(smoke, "build_verified_market_snapshot", _fake_snapshot)
    monkeypatch.setattr(smoke, "Propagator", FakePropagator)
    monkeypatch.setattr(smoke, "get_stock_result", lambda symbol, start, end: _fake_contract_result(symbol, "ohlcv"))
    monkeypatch.setattr(
        smoke,
        "get_fundamentals_result",
        lambda symbol, end: _fake_contract_result(symbol, "fund_profile"),
    )
    monkeypatch.setattr(smoke, "get_news_result", lambda symbol, start, end: _fake_contract_result(symbol, "news"))

    target = smoke._build_targets(("600519",), ())[0]
    results = smoke.run_matrix(
        (target,),
        "2026-05-22",
        10,
        include_macro=False,
        include_snapshot=False,
        include_graph_state=False,
    )

    route_price = next(result for result in results if result.capability == "route_price")
    assert route_price.status == smoke.STATUS_FAIL
    assert "missing marker" in route_price.detail


def test_render_markdown_contains_matrix_rows():
    result = smoke.SmokeResult(
        symbol="600519",
        label="A-share equity",
        normalized="600519.SH",
        market="cn_a",
        instrument="equity",
        capability="route_price",
        status=smoke.STATUS_OK,
        detail="required marker(s) present",
    )

    markdown = smoke.render_markdown([result], "2026-05-22", 10)

    assert "# China Market Localization Acceptance Matrix" in markdown
    assert "| 600519 | A-share equity | 600519.SH | cn_a | equity | route_price | OK |" in markdown
    assert "- WARN: core China price/fundamentals contracts passed" in markdown


def test_render_markdown_contains_cache_stats():
    result = smoke.SmokeResult(
        symbol="600519",
        label="A-share equity",
        normalized="600519.SH",
        market="cn_a",
        instrument="equity",
        capability="route_price",
        status=smoke.STATUS_OK,
        detail="required marker(s) present",
    )

    markdown = smoke.render_markdown(
        [result],
        "2026-05-22",
        10,
        {
            "akshare": {
                "get_stock": {
                    "hits": 1,
                    "misses": 2,
                    "writes": 2,
                }
            },
            "tiantian_fund": {},
        },
    )

    assert "## Dataflow Cache Stats" in markdown
    assert "| akshare | get_stock | 1 | 2 | 2 | 0 | 0 | 0 | 0 |" in markdown
