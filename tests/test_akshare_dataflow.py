import pandas as pd
import pytest

import tradingagents.default_config as default_config
from tradingagents.dataflows import akshare
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.interface import route_to_vendor


@pytest.fixture(autouse=True)
def reset_dataflow_config():
    set_config(default_config.DEFAULT_CONFIG.copy())
    yield
    set_config(default_config.DEFAULT_CONFIG.copy())


@pytest.fixture(autouse=True)
def isolate_akshare_cache(monkeypatch, tmp_path):
    from diskcache import Cache
    temp_cache = Cache(str(tmp_path / "test_akshare_cache"))
    monkeypatch.setattr(akshare, "cache", temp_cache)
    yield


class FakeAkShare:
    def __init__(self):
        self.calls = []

    def fund_etf_hist_em(self, **kwargs):
        self.calls.append(("fund_etf_hist_em", kwargs))
        return _ohlcv_frame()

    def fund_lof_hist_em(self, **kwargs):
        self.calls.append(("fund_lof_hist_em", kwargs))
        return _ohlcv_frame()

    def stock_zh_a_hist(self, **kwargs):
        self.calls.append(("stock_zh_a_hist", kwargs))
        return _ohlcv_frame()

    def stock_zh_a_daily(self, **kwargs):
        self.calls.append(("stock_zh_a_daily", kwargs))
        return _lowercase_ohlcv_frame()

    def stock_zh_a_hist_tx(self, **kwargs):
        self.calls.append(("stock_zh_a_hist_tx", kwargs))
        return _lowercase_ohlcv_frame()

    def fund_etf_hist_sina(self, **kwargs):
        self.calls.append(("fund_etf_hist_sina", kwargs))
        return _lowercase_ohlcv_frame()

    def fund_overview_em(self, **kwargs):
        self.calls.append(("fund_overview_em", kwargs))
        return pd.DataFrame(
            [
                {"项目": "基金简称", "内容": "沪深300ETF"},
                {"项目": "基金类型", "内容": "ETF"},
                {"项目": "基金规模", "内容": "100亿元"},
                {"项目": "基金管理人", "内容": "测试基金公司"},
            ]
        )

    def fund_fee_em(self, **kwargs):
        self.calls.append(("fund_fee_em", kwargs))
        return pd.DataFrame([{"费用类型": "管理费率", "费率": "0.50%"}])

    def fund_portfolio_hold_em(self, **kwargs):
        self.calls.append(("fund_portfolio_hold_em", kwargs))
        return pd.DataFrame([{"股票名称": "贵州茅台", "占净值比例": "5.00%"}])

    def stock_balance_sheet_by_report_em(self, **kwargs):
        self.calls.append(("stock_balance_sheet_by_report_em", kwargs))
        return _statement_frame()

    def stock_cash_flow_sheet_by_report_em(self, **kwargs):
        self.calls.append(("stock_cash_flow_sheet_by_report_em", kwargs))
        return _statement_frame()

    def stock_profit_sheet_by_report_em(self, **kwargs):
        self.calls.append(("stock_profit_sheet_by_report_em", kwargs))
        return _statement_frame()

    def stock_news_em(self, **kwargs):
        self.calls.append(("stock_news_em", kwargs))
        return pd.DataFrame(
            [
                {
                    "新闻标题": "公司新闻",
                    "文章来源": "测试来源",
                    "发布时间": "2026-01-02",
                    "新闻链接": "https://example.invalid/stock",
                }
            ]
        )

    def fund_announcement_report_em(self, **kwargs):
        self.calls.append(("fund_announcement_report_em", kwargs))
        return pd.DataFrame(
            [
                {
                    "公告标题": "基金定期报告",
                    "公告日期": "2026-01-02",
                    "公告链接": "https://example.invalid/fund-report",
                }
            ]
        )

    def fund_announcement_dividend_em(self, **kwargs):
        self.calls.append(("fund_announcement_dividend_em", kwargs))
        return pd.DataFrame()

    def fund_announcement_personnel_em(self, **kwargs):
        self.calls.append(("fund_announcement_personnel_em", kwargs))
        return pd.DataFrame()


def test_get_stock_routes_etf_history(monkeypatch):
    fake = FakeAkShare()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    result = akshare.get_stock("510300", "2026-01-01", "2026-01-03")

    assert "AkShare data for 510300.SH" in result
    assert "Date,Open,High,Low,Close,Volume" in result
    assert fake.calls[0][0] == "fund_etf_hist_em"
    assert fake.calls[0][1]["symbol"] == "510300"


def test_get_stock_routes_lof_history(monkeypatch):
    fake = FakeAkShare()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    akshare.get_stock("161725", "2026-01-01", "2026-01-03")

    assert fake.calls[0][0] == "fund_lof_hist_em"
    assert fake.calls[0][1]["symbol"] == "161725"


def test_get_stock_routes_equity_history(monkeypatch):
    fake = FakeAkShare()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    akshare.get_stock("600519", "2026-01-01", "2026-01-03")

    assert fake.calls[0][0] == "stock_zh_a_hist"
    assert fake.calls[0][1]["symbol"] == "600519"


def test_get_stock_falls_back_to_sina_equity_history(monkeypatch):
    class FakeAkShareWithFailedEastmoney(FakeAkShare):
        def stock_zh_a_hist(self, **kwargs):
            self.calls.append(("stock_zh_a_hist", kwargs))
            raise RuntimeError("eastmoney unavailable")

    fake = FakeAkShareWithFailedEastmoney()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    result = akshare.get_stock("600519", "2026-01-01", "2026-01-03")

    assert "AkShare data for 600519.SH" in result
    assert "2026-01-03" in result
    assert fake.calls[1][0] == "stock_zh_a_daily"
    assert fake.calls[1][1]["symbol"] == "sh600519"


def test_get_stock_falls_back_to_sina_fund_history(monkeypatch):
    class FakeAkShareWithFailedEastmoney(FakeAkShare):
        def fund_etf_hist_em(self, **kwargs):
            self.calls.append(("fund_etf_hist_em", kwargs))
            raise RuntimeError("eastmoney unavailable")

    fake = FakeAkShareWithFailedEastmoney()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    result = akshare.get_stock("510300", "2026-01-01", "2026-01-03")

    assert "AkShare data for 510300.SH" in result
    assert "2026-01-03" in result
    assert fake.calls[1][0] == "fund_etf_hist_sina"
    assert fake.calls[1][1]["symbol"] == "sh510300"


def test_get_indicator_uses_normalized_ohlcv(monkeypatch):
    fake = FakeAkShare()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    result = akshare.get_indicator("510300", "rsi", "2026-01-03", 2)

    assert "## rsi values" in result
    assert "2026-01-02" in result
    assert "RSI:" in result


def test_get_fundamentals_returns_fund_profile(monkeypatch):
    fake = FakeAkShare()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    result = akshare.get_fundamentals("510300", "2026-01-03")

    assert "Listed Fund Profile for 510300.SH" in result
    assert "沪深300ETF" in result
    assert "管理费率" in result
    assert "贵州茅台" in result
    assert ("fund_portfolio_hold_em", {"symbol": "510300", "date": "2026"}) in fake.calls


def test_fund_financial_statements_are_not_applicable():
    assert "not applicable to listed fund 510300.SH" in akshare.get_balance_sheet("510300")
    assert "not applicable to listed fund 510300.SH" in akshare.get_cashflow("510300")
    assert "not applicable to listed fund 510300.SH" in akshare.get_income_statement("510300")


def test_equity_financial_statements_use_prefixed_akshare_symbol(monkeypatch):
    fake = FakeAkShare()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    result = akshare.get_balance_sheet("600519", curr_date="2026-01-03")

    assert "AkShare Balance Sheet for 600519.SH" in result
    assert ("stock_balance_sheet_by_report_em", {"symbol": "SH600519"}) in fake.calls


def test_sz_equity_financial_statements_use_prefixed_akshare_symbol(monkeypatch):
    fake = FakeAkShare()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    akshare.get_income_statement("000001", curr_date="2026-01-03")

    assert ("stock_profit_sheet_by_report_em", {"symbol": "SZ000001"}) in fake.calls


def test_fund_news_uses_fund_announcements_not_stock_news(monkeypatch):
    fake = FakeAkShare()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    result = akshare.get_news("510300", "2026-01-01", "2026-01-03")

    call_names = [name for name, _ in fake.calls]
    assert "510300.SH Listed Fund Announcements" in result
    assert "基金定期报告" in result
    assert "fund_announcement_report_em" in call_names
    assert "stock_news_em" not in call_names


def test_fund_news_falls_back_to_recent_announcements_before_end_date(monkeypatch):
    class FakeAkShareWithOldAnnouncements(FakeAkShare):
        def fund_announcement_report_em(self, **kwargs):
            self.calls.append(("fund_announcement_report_em", kwargs))
            return pd.DataFrame(
                [
                    {
                        "公告标题": "最近季度报告",
                        "公告日期": "2026-04-22",
                        "公告链接": "https://example.invalid/recent",
                    },
                    {
                        "公告标题": "更早年度报告",
                        "公告日期": "2026-03-31",
                        "公告链接": "https://example.invalid/older",
                    },
                ]
            )

    fake = FakeAkShareWithOldAnnouncements()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    result = akshare.get_news("510300", "2026-05-01", "2026-05-22")

    assert "Recent Listed Fund Announcements before 2026-05-22" in result
    assert "none found from 2026-05-01 to 2026-05-22" in result
    assert "最近季度报告" in result
    assert "更早年度报告" in result


def test_route_to_vendor_can_select_akshare(monkeypatch):
    fake = FakeAkShare()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)
    set_config({"tool_vendors": {"get_stock_data": "akshare"}})

    result = route_to_vendor("get_stock_data", "600519", "2026-01-01", "2026-01-03")

    assert "AkShare data for 600519.SH" in result
    assert fake.calls[0][0] == "stock_zh_a_hist"


def test_route_to_vendor_requires_explicit_akshare_for_cn_a(monkeypatch):
    def fallback_stock(symbol, start_date, end_date):
        return f"fallback:{symbol}:{start_date}:{end_date}"

    monkeypatch.setitem(route_to_vendor.__globals__["VENDOR_METHODS"]["get_stock_data"], "yfinance", fallback_stock)

    with pytest.raises(RuntimeError, match="Supported vendor\\(s\\): akshare"):
        route_to_vendor("get_stock_data", "600519.SH", "2026-01-01", "2026-01-03")


def test_route_to_vendor_does_not_fall_back_to_yfinance_for_cn_a(monkeypatch):
    def fail_stock(symbol, start_date, end_date):
        raise akshare.AkShareDataError("rate limited")

    def fallback_stock(symbol, start_date, end_date):
        return f"fallback:{symbol}:{start_date}:{end_date}"

    monkeypatch.setitem(route_to_vendor.__globals__["VENDOR_METHODS"]["get_stock_data"], "akshare", fail_stock)
    monkeypatch.setitem(route_to_vendor.__globals__["VENDOR_METHODS"]["get_stock_data"], "yfinance", fallback_stock)
    set_config({"tool_vendors": {"get_stock_data": "akshare,yfinance"}})

    with pytest.raises(RuntimeError, match="Last recoverable error: akshare: rate limited"):
        route_to_vendor("get_stock_data", "600519.SH", "2026-01-01", "2026-01-03")


def test_route_to_vendor_falls_back_on_akshare_data_error_for_us_ticker(monkeypatch):
    def fail_stock(symbol, start_date, end_date):
        raise akshare.AkShareDataError("rate limited")

    def fallback_stock(symbol, start_date, end_date):
        return f"fallback:{symbol}:{start_date}:{end_date}"

    monkeypatch.setitem(route_to_vendor.__globals__["VENDOR_METHODS"]["get_stock_data"], "akshare", fail_stock)
    monkeypatch.setitem(route_to_vendor.__globals__["VENDOR_METHODS"]["get_stock_data"], "yfinance", fallback_stock)
    set_config({"tool_vendors": {"get_stock_data": "akshare,yfinance"}})

    assert route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-03") == (
        "fallback:AAPL:2026-01-01:2026-01-03"
    )


def _ohlcv_frame():
    return pd.DataFrame(
        [
            {"日期": "2026-01-01", "开盘": 10, "最高": 11, "最低": 9, "收盘": 10.5, "成交量": 1000},
            {"日期": "2026-01-02", "开盘": 10.5, "最高": 12, "最低": 10, "收盘": 11.5, "成交量": 1200},
            {"日期": "2026-01-03", "开盘": 11.5, "最高": 13, "最低": 11, "收盘": 12.5, "成交量": 1300},
        ]
    )


def _lowercase_ohlcv_frame():
    return pd.DataFrame(
        [
            {"date": "2026-01-01", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000},
            {"date": "2026-01-02", "open": 10.5, "high": 12, "low": 10, "close": 11.5, "volume": 1200},
            {"date": "2026-01-03", "open": 11.5, "high": 13, "low": 11, "close": 12.5, "volume": 1300},
        ]
    )


def _statement_frame():
    return pd.DataFrame(
        [
            {"报告期": "2025-12-31", "资产总计": 100},
            {"报告期": "2026-06-30", "资产总计": 120},
        ]
    )


def test_akshare_disk_cache_behavior(tmp_path, monkeypatch):
    from diskcache import Cache
    from tradingagents.dataflows import akshare

    # 1. 实例化一个临时隔离的 Cache，并替换全局全局对象
    temp_cache = Cache(str(tmp_path))
    monkeypatch.setattr(akshare, "cache", temp_cache)

    # 2. Mock 真正的底层 _load_ohlcv 数据源
    load_count = 0
    def mock_load_ohlcv(symbol, start, end):
        nonlocal load_count
        load_count += 1
        return _ohlcv_frame()
    monkeypatch.setattr(akshare, "_load_ohlcv", mock_load_ohlcv)

    # 3. 第一次调用：应该调用底层加载方法，并且回写磁盘
    res1 = akshare.get_stock("600519", "2026-01-01", "2026-01-03")
    assert load_count == 1

    # 4. 第二次调用：直接从缓存中获取，即使 _load_ohlcv 抛出异常也应该成功返回结果
    def fail_load_ohlcv(symbol, start, end):
        raise RuntimeError("Network API should not be called!")
    monkeypatch.setattr(akshare, "_load_ohlcv", fail_load_ohlcv)

    res2 = akshare.get_stock("600519", "2026-01-01", "2026-01-03")

    # 5. 断言两次结果 100% 一致且缓存拦截成功
    assert res1 == res2
    assert "AkShare data for 600519.SH" in res2


def test_akshare_disk_cache_graceful_fallback(monkeypatch):
    from tradingagents.dataflows import akshare

    # 1. 模拟缓存不可用（如宕机或损坏为 None）
    monkeypatch.setattr(akshare, "cache", None)

    # 2. Mock 正常的数据底层加载
    load_count = 0
    def mock_load_ohlcv(symbol, start, end):
        nonlocal load_count
        load_count += 1
        return _ohlcv_frame()
    monkeypatch.setattr(akshare, "_load_ohlcv", mock_load_ohlcv)

    # 3. 两次调用应该两次都透传到底层（虽然无缓存，但核心业务不被阻断）
    res1 = akshare.get_stock("600519", "2026-01-01", "2026-01-03")
    res2 = akshare.get_stock("600519", "2026-01-01", "2026-01-03")

    assert load_count == 2
    assert res1 == res2


def test_akshare_cache_lazy_loads_under_configured_cache_dir(monkeypatch, tmp_path):
    from tradingagents.dataflows import akshare

    created_paths = []

    class FakeCache:
        def __init__(self, path):
            created_paths.append(path)
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def set(self, key, value, expire=None):
            self.store[key] = value

    custom_cache_dir = tmp_path / "configured-cache"
    set_config({"data_cache_dir": str(custom_cache_dir)})
    monkeypatch.setattr(akshare, "cache", akshare._UNINITIALIZED_CACHE)
    monkeypatch.setattr(akshare, "Cache", FakeCache)
    monkeypatch.setattr(akshare, "_load_ohlcv", lambda symbol, start, end: _ohlcv_frame())

    result = akshare.get_stock("600519", "2026-01-01", "2026-01-03")

    assert "AkShare data for 600519.SH" in result
    assert created_paths == [f"{custom_cache_dir}/akshare"]


def test_bj_stock_routing_and_prefixes(monkeypatch):
    from tradingagents.dataflows import akshare
    from tradingagents.dataflows.instruments import (
        normalize_ticker_symbol,
        detect_market_type,
        detect_instrument_type,
        to_akshare_symbol,
        MarketType,
        InstrumentType,
    )

    # 1. 验证 830833 (北交所股票) 的识别与规范化
    assert normalize_ticker_symbol("830833") == "830833.BJ"
    assert detect_market_type("830833") == MarketType.CN_A
    assert detect_instrument_type("830833") == InstrumentType.EQUITY
    assert to_akshare_symbol("830833.BJ") == "830833"

    # 2. 验证财报接口前缀拼装
    assert akshare._to_akshare_statement_symbol("830833") == "BJ830833"

    # 3. 验证新浪备用数据源前缀拼装
    assert akshare._prefixed_cn_symbol("830833") == "bj830833"

    # 4. Mock 测试其能成功走向东财 A 股行情加载
    fake = FakeAkShare()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    akshare.get_stock("830833", "2026-01-01", "2026-01-03")
    assert fake.calls[0][0] == "stock_zh_a_hist"
    assert fake.calls[0][1]["symbol"] == "830833"


def test_akshare_get_display_name_cached(monkeypatch, tmp_path):
    from diskcache import Cache
    from tradingagents.dataflows import akshare

    # 1. 实例化一个临时隔离的 Cache
    temp_cache = Cache(str(tmp_path / "test_display_cache"))
    monkeypatch.setattr(akshare, "cache", temp_cache)

    # 2. 验证海外标的直接降级返回自身
    assert akshare.get_ticker_display_name("AAPL") == "AAPL"

    # 3. Mock 验证基金和股票简称拉取
    class FakeOverviewAkShare:
        def __init__(self):
            self.calls = []

        def fund_overview_em(self, symbol):
            self.calls.append(("fund_overview_em", symbol))
            if symbol == "510300":
                return pd.DataFrame(
                    [
                        {"项目": "基金简称", "内容": "沪深300ETF"},
                    ]
                )
            return pd.DataFrame()

        def stock_individual_info_em(self, symbol):
            self.calls.append(("stock_individual_info_em", symbol))
            if symbol == "600519":
                return pd.DataFrame(
                    [
                        {"item": "股票简称", "value": "贵州茅台"},
                    ]
                )
            return pd.DataFrame()

    fake = FakeOverviewAkShare()
    monkeypatch.setattr(akshare, "_ak", lambda: fake)

    # 第一次调用：基金拉取
    assert akshare.get_ticker_display_name("510300") == "沪深300ETF"
    assert len(fake.calls) == 1
    assert fake.calls[0] == ("fund_overview_em", "510300")

    # 缓存测试：第二次调用应该直接从缓存返回，不需要再次调用 _ak
    assert akshare.get_ticker_display_name("510300") == "沪深300ETF"
    assert len(fake.calls) == 1

    # 第一次调用：股票拉取
    assert akshare.get_ticker_display_name("600519") == "贵州茅台"
    assert len(fake.calls) == 2
    assert fake.calls[1] == ("stock_individual_info_em", "600519")

    # 缓存测试：第二次调用股票应该直接从缓存返回
    assert akshare.get_ticker_display_name("600519") == "贵州茅台"
    assert len(fake.calls) == 2
