from datetime import datetime
from typing import Optional

import pandas as pd
from stockstats import wrap

from .config import get_config
from .instruments import (
    InstrumentType,
    detect_instrument_type,
    detect_market_type,
    MarketType,
    normalize_ticker_symbol,
    to_akshare_symbol,
)
from .tiantian_fund import get_fund_nav_history, get_fund_profile_tables


import functools
import sys
from diskcache import Cache

_UNINITIALIZED_CACHE = object()
cache = _UNINITIALIZED_CACHE


def _get_cache():
    global cache
    if cache is _UNINITIALIZED_CACHE:
        cache_dir = f"{get_config()['data_cache_dir']}/akshare"
        try:
            cache = Cache(cache_dir)
        except Exception as exc:
            print(f"[Warning] Failed to initialize DiskCache at {cache_dir}: {exc}", file=sys.stderr)
            cache = None
    return cache


def akshare_disk_cache(expire=14400):  # 默认缓存 4 小时 (14400 秒)
    """通用本地磁盘缓存装饰器，带高可用灾备穿透"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not get_config().get("enable_data_cache", True):
                return func(*args, **kwargs)

            active_cache = _get_cache()
            if active_cache is None:
                return func(*args, **kwargs)

            # 将函数名和参数组合序列化，作为唯一的 Cache Key
            key = f"disk:{func.__name__}:{args}:{sorted(kwargs.items())}"
            try:
                cached_val = active_cache.get(key)
                if cached_val is not None:
                    return cached_val
            except Exception as exc:
                # 磁盘读写异常时，优雅降级，直接穿透调用真实 API
                print(f"[Warning] DiskCache read failure for {func.__name__}: {exc}", file=sys.stderr)

            val = func(*args, **kwargs)

            try:
                active_cache.set(key, val, expire=expire)
            except Exception as exc:
                print(f"[Warning] DiskCache write failure for {func.__name__}: {exc}", file=sys.stderr)
            return val
        return wrapper
    return decorator


class AkShareDataError(RuntimeError):
    """Recoverable AkShare data-source error that allows configured fallback."""


def _ak():
    try:
        import akshare as ak
    except ImportError as exc:
        raise AkShareDataError(
            "AkShare is required for the 'akshare' data vendor. Install the project with the akshare dependency."
        ) from exc
    return ak


@akshare_disk_cache(expire=14400)
def get_stock(
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    """Retrieve A-share equity or listed fund OHLCV data using AkShare."""
    try:
        data = _load_ohlcv(symbol, start_date, end_date)
        if data.empty:
            normalized = normalize_ticker_symbol(symbol)
            return (
                f"[Data Availability Notice] No AkShare data found for symbol '{normalized}' between {start_date} and {end_date}. "
                "This might be because the requested date range consists entirely of non-trading days (weekends or public holidays), "
                "or the market was closed, or the ticker is temporarily suspended. "
                "If trading data is missing, check alternative vendors or rely on the latest available history."
            )

        csv_string = data.to_csv(index=False)
        normalized = normalize_ticker_symbol(symbol)
        if detect_market_type(normalized) == MarketType.CN_FUND:
            header = f"# Tiantian Fund NAV data for {normalized} from {start_date} to {end_date}\n"
        else:
            header = f"# AkShare data for {normalized} from {start_date} to {end_date}\n"
        header += f"# Total records: {len(data)}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return header + csv_string
    except AkShareDataError:
        raise
    except Exception as e:
        raise AkShareDataError(f"Error retrieving AkShare data for {symbol}: {str(e)}") from e


@akshare_disk_cache(expire=14400)
def get_indicator(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int = 30,
) -> str:
    supported = _indicator_descriptions()
    indicator = indicator.lower()
    if indicator not in supported:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(supported.keys())}"
        )

    try:
        end_dt = pd.to_datetime(curr_date)
        start_dt = end_dt - pd.DateOffset(days=max(look_back_days, 250))
        data = _load_ohlcv(
            symbol,
            start_dt.strftime("%Y-%m-%d"),
            curr_date,
        )
        if data.empty:
            return f"No AkShare OHLCV data found for {symbol} up to {curr_date}"

        df = data.rename(columns=str.lower)
        df["date"] = pd.to_datetime(df["date"])
        df = wrap(df)
        df[indicator]

        window_start = (end_dt - pd.DateOffset(days=look_back_days)).strftime("%Y-%m-%d")
        rows = pd.DataFrame(df).reset_index()
        rows["date"] = pd.to_datetime(rows["date"]).dt.strftime("%Y-%m-%d")
        rows = rows[rows["date"] >= window_start][["date", indicator]]
        lines = []
        for _, row in rows.iterrows():
            value = row[indicator]
            rendered = "N/A" if pd.isna(value) else str(value)
            lines.append(f"{row['date']}: {rendered}")

        result = (
            f"## {indicator} values from {window_start} to {curr_date}:\n\n"
            + "\n".join(lines)
            + "\n\n"
            + supported[indicator]
        )
        if detect_market_type(symbol) == MarketType.CN_FUND:
            result += (
                "\n\nFund NAV note: this indicator is computed from daily fund net asset value, "
                "not exchange-traded OHLCV. Volume-derived indicators are not meaningful for OTC mutual funds."
            )
        return result
    except AkShareDataError:
        raise
    except Exception as e:
        raise AkShareDataError(f"Error getting AkShare indicator data for {symbol}: {str(e)}") from e


@akshare_disk_cache(expire=14400)
def get_fundamentals(ticker: str, curr_date: Optional[str] = None) -> str:
    normalized = normalize_ticker_symbol(ticker)
    if detect_instrument_type(normalized) == InstrumentType.FUND:
        return _get_fund_profile(normalized, curr_date)
    return _get_equity_profile(normalized, curr_date)


@akshare_disk_cache(expire=14400)
def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    if detect_instrument_type(ticker) == InstrumentType.FUND:
        return _fund_statement_not_applicable(ticker, "balance sheet")
    return _financial_statement(ticker, "balance_sheet", freq, curr_date)


@akshare_disk_cache(expire=14400)
def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    if detect_instrument_type(ticker) == InstrumentType.FUND:
        return _fund_statement_not_applicable(ticker, "cash flow statement")
    return _financial_statement(ticker, "cashflow", freq, curr_date)


@akshare_disk_cache(expire=14400)
def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    if detect_instrument_type(ticker) == InstrumentType.FUND:
        return _fund_statement_not_applicable(ticker, "income statement")
    return _financial_statement(ticker, "income_statement", freq, curr_date)


@akshare_disk_cache(expire=14400)
def get_news(ticker: str, start_date: str, end_date: str) -> str:
    ak = _ak()
    normalized = normalize_ticker_symbol(ticker)
    symbol = to_akshare_symbol(ticker)
    try:
        if detect_instrument_type(normalized) == InstrumentType.FUND:
            fund_label = _fund_label(normalized)
            report_announcements = _safe_call(lambda: ak.fund_announcement_report_em(symbol=symbol))
            dividend_announcements = _safe_call(lambda: ak.fund_announcement_dividend_em(symbol=symbol))
            personnel_announcements = _safe_call(lambda: ak.fund_announcement_personnel_em(symbol=symbol))
            data = pd.concat(
                [
                    report_announcements.assign(_source="fund report announcement"),
                    dividend_announcements.assign(_source="fund dividend announcement"),
                    personnel_announcements.assign(_source="fund personnel announcement"),
                ],
                ignore_index=True,
            )
            if data.empty:
                return (
                    f"No AkShare {fund_label} announcements found for {normalized} between "
                    f"{start_date} and {end_date}. Use {_fund_context_hint(normalized)} instead."
                )
            data, used_fallback = _filter_fund_announcements(data, start_date, end_date)
            if data.empty:
                return f"No AkShare {fund_label} announcements found for {normalized} on or before {end_date}"
            rows = _render_news_rows(data)
            if used_fallback:
                heading = (
                    f"## {normalized} Recent {fund_label.title()} Announcements before {end_date} "
                    f"(none found from {start_date} to {end_date}):\n\n"
                )
            else:
                heading = f"## {normalized} {fund_label.title()} Announcements, from {start_date} to {end_date}:\n\n"
            return heading + "\n".join(rows)

        data = ak.stock_news_em(symbol=symbol)
        if data is None or data.empty:
            return f"No AkShare news found for {ticker}"
        data = _filter_date_rows(data, start_date, end_date)
        if data.empty:
            return f"No AkShare news found for {ticker} between {start_date} and {end_date}"
        rows = _render_news_rows(data)
        return f"## {normalize_ticker_symbol(ticker)} News, from {start_date} to {end_date}:\n\n" + "\n".join(rows)
    except AkShareDataError:
        raise
    except Exception as e:
        raise AkShareDataError(f"Error fetching AkShare news for {ticker}: {str(e)}") from e


def get_global_news(curr_date: str, look_back_days: Optional[int] = None, limit: Optional[int] = None) -> str:
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]
    return (
        "AkShare global macro news is not configured in this MVP. "
        f"Use China market context around {curr_date} with a {look_back_days}-day lookback and limit {limit}."
    )


def get_insider_transactions(ticker: str) -> str:
    if detect_instrument_type(ticker) == InstrumentType.FUND:
        normalized = normalize_ticker_symbol(ticker)
        return f"Insider transaction data is not applicable to {_fund_label(normalized)} {normalized}."
    return f"AkShare insider transaction data is not available in a stable MVP format for {normalize_ticker_symbol(ticker)}."


def _load_ohlcv(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    normalized = normalize_ticker_symbol(symbol)
    if detect_market_type(normalized) == MarketType.CN_FUND:
        return _normalize_ohlcv(get_fund_nav_history(normalized, start_date, end_date), start_date, end_date)

    ak = _ak()
    pure_symbol = to_akshare_symbol(normalized)
    start = _compact_date(start_date)
    end = _compact_date(end_date)

    errors = []
    empty_sources = []
    for source_name, loader in _ohlcv_source_loaders(ak, normalized, pure_symbol, start, end):
        try:
            data = _normalize_ohlcv(loader(), start_date, end_date)
        except Exception as exc:
            errors.append(f"{source_name}: {exc}")
            continue
        if data.empty:
            empty_sources.append(source_name)
            continue
        return data

    columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    if errors:
        details = " | ".join(errors)
        if empty_sources:
            details += " | empty sources: " + ", ".join(empty_sources)
        raise AkShareDataError(f"AkShare OHLCV sources failed for {normalized}: {details}")
    return pd.DataFrame(columns=columns)


def _ohlcv_source_loaders(ak, normalized: str, pure_symbol: str, start: str, end: str):
    if detect_instrument_type(normalized) == InstrumentType.FUND:
        if pure_symbol.startswith(("159", "5")):
            yield (
                "eastmoney_fund_etf_hist_em",
                lambda: ak.fund_etf_hist_em(
                    symbol=pure_symbol,
                    period="daily",
                    start_date=start,
                    end_date=end,
                    adjust="",
                ),
            )
        else:
            yield (
                "eastmoney_fund_lof_hist_em",
                lambda: ak.fund_lof_hist_em(
                    symbol=pure_symbol,
                    period="daily",
                    start_date=start,
                    end_date=end,
                    adjust="",
                ),
            )
        yield (
            "sina_fund_etf_hist_sina",
            lambda: ak.fund_etf_hist_sina(symbol=_prefixed_cn_symbol(normalized)),
        )
        return

    yield (
        "eastmoney_stock_zh_a_hist",
        lambda: ak.stock_zh_a_hist(
            symbol=pure_symbol,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="",
        ),
    )
    yield (
        "sina_stock_zh_a_daily",
        lambda: ak.stock_zh_a_daily(
            symbol=_prefixed_cn_symbol(normalized),
            start_date=start,
            end_date=end,
            adjust="",
        ),
    )
    yield (
        "tencent_stock_zh_a_hist_tx",
        lambda: ak.stock_zh_a_hist_tx(
            symbol=_prefixed_cn_symbol(normalized),
            start_date=start,
            end_date=end,
            adjust="",
        ),
    )


def _normalize_ohlcv(data: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    if data is None or data.empty:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])

    rename_map = {
        "日期": "Date",
        "开盘": "Open",
        "最高": "High",
        "最低": "Low",
        "收盘": "Close",
        "成交量": "Volume",
        "成交额": "Amount",
        "振幅": "Amplitude",
        "涨跌幅": "Pct Change",
        "涨跌额": "Change",
        "换手率": "Turnover",
        "date": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "amount": "Amount",
    }
    normalized = data.rename(columns={k: v for k, v in rename_map.items() if k in data.columns}).copy()
    required = ["Date", "Open", "High", "Low", "Close", "Volume"]
    for column in required:
        if column not in normalized.columns:
            normalized[column] = pd.NA
    normalized["Date"] = pd.to_datetime(normalized["Date"], errors="coerce")
    normalized = normalized.dropna(subset=["Date"])
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    normalized = normalized[(normalized["Date"] >= start_dt) & (normalized["Date"] <= end_dt)]
    for column in ["Open", "High", "Low", "Close", "Volume"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized = normalized.dropna(subset=["Close"])
    normalized["Date"] = normalized["Date"].dt.strftime("%Y-%m-%d")
    columns = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume", "Amount", "Pct Change", "Turnover"] if c in normalized.columns]
    return normalized[columns]


def _get_fund_profile(ticker: str, curr_date: Optional[str]) -> str:
    pure_symbol = to_akshare_symbol(ticker)
    is_otc_fund = detect_market_type(ticker) == MarketType.CN_FUND
    title = "China OTC Fund Profile" if is_otc_fund else "Listed Fund Profile"
    lines = [f"# {title} for {ticker}", f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]

    tiantian_tables = _safe_tiantian_fund_tables(pure_symbol, curr_date)
    for table in tiantian_tables:
        lines.extend(_render_table_like(table.title, table.data, max_rows=table.max_rows))

    if is_otc_fund:
        if not tiantian_tables:
            lines.append(f"No Tiantian Fund profile data found for {pure_symbol}.")
        lines.append(
            "Fund analysis focus: NAV trend, fund category/share class, fund manager, assets under management, fees, asset allocation, holdings concentration, QDII/FX risk where applicable, and redemption/subscription constraints. Do not use listed-company financial statement semantics."
        )
        return "\n".join(lines)

    ak = _ak()
    overview = _safe_call(lambda: ak.fund_overview_em(symbol=pure_symbol))
    fee = _safe_call(lambda: ak.fund_fee_em(symbol=pure_symbol, indicator="运作费用"))
    holdings = _safe_call(
        lambda: ak.fund_portfolio_hold_em(symbol=pure_symbol, date=_fund_holdings_year(curr_date))
    )

    lines.extend(_render_table_like("AkShare Fund Overview", overview))
    lines.extend(_render_table_like("AkShare Fund Fees", fee))
    lines.extend(_render_table_like("AkShare Fund Top Holdings", holdings, max_rows=10))
    lines.append(
        "Fund analysis focus: benchmark/theme exposure, premium or discount, liquidity, fund size, fees, holdings concentration, and market risk."
    )
    return "\n".join(lines)


def _get_equity_profile(ticker: str, curr_date: Optional[str]) -> str:
    ak = _ak()
    symbol = to_akshare_symbol(ticker)
    lines = [f"# A-share Company Fundamentals for {ticker}", f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
    spot = _safe_call(lambda: ak.stock_individual_info_em(symbol=symbol))
    financial = _safe_call(lambda: ak.stock_financial_abstract(symbol=symbol))
    lines.extend(_render_table_like("Company Profile", spot))
    lines.extend(_render_table_like("Financial Abstract", _filter_statement_by_date(financial, curr_date), max_rows=20))
    return "\n".join(lines)


def _financial_statement(ticker: str, statement: str, freq: str, curr_date: Optional[str]) -> str:
    ak = _ak()
    symbol = _to_akshare_statement_symbol(ticker)
    fn_name = {
        "balance_sheet": "stock_balance_sheet_by_report_em",
        "cashflow": "stock_cash_flow_sheet_by_report_em",
        "income_statement": "stock_profit_sheet_by_report_em",
    }[statement]
    try:
        data = getattr(ak, fn_name)(symbol=symbol)
        data = _filter_statement_by_date(data, curr_date)
        if data is None or data.empty:
            return f"No AkShare {statement.replace('_', ' ')} data found for {ticker}"
        header = f"# AkShare {statement.replace('_', ' ').title()} for {normalize_ticker_symbol(ticker)} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return header + data.to_csv(index=False)
    except AkShareDataError:
        raise
    except Exception as e:
        raise AkShareDataError(
            f"Error retrieving AkShare {statement.replace('_', ' ')} for {ticker}: {str(e)}"
        ) from e


def _fund_statement_not_applicable(ticker: str, statement_name: str) -> str:
    normalized = normalize_ticker_symbol(ticker)
    return (
        f"{statement_name.title()} is not applicable to {_fund_label(normalized)} {normalized}. "
        "Use fund overview, fees, holdings, NAV trend, asset allocation, liquidity or redemption terms, and benchmark/theme exposure instead."
    )


def _fund_label(ticker: str) -> str:
    return "OTC fund" if detect_market_type(ticker) == MarketType.CN_FUND else "listed fund"


def _fund_context_hint(ticker: str) -> str:
    if detect_market_type(ticker) == MarketType.CN_FUND:
        return "NAV trend, fund category, fees, asset allocation, holdings, fund manager, QDII/FX exposure, and subscription/redemption context"
    return "China market, benchmark/theme, liquidity, premium/discount, fees, and holdings context"


def _filter_statement_by_date(data: Optional[pd.DataFrame], curr_date: Optional[str]) -> pd.DataFrame:
    if data is None or data.empty or not curr_date:
        return pd.DataFrame() if data is None else data
    result = data.copy()
    date_columns = [c for c in result.columns if "日期" in str(c) or "date" in str(c).lower() or "报告期" in str(c)]
    if not date_columns:
        return result
    parsed = pd.to_datetime(result[date_columns[0]], errors="coerce")
    return result[parsed <= pd.to_datetime(curr_date)]


def _filter_date_rows(data: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    result = data.copy()
    date_columns = [c for c in result.columns if "时间" in str(c) or "日期" in str(c) or "date" in str(c).lower()]
    if not date_columns:
        return result
    parsed = pd.to_datetime(result[date_columns[0]], errors="coerce")
    end_exclusive = pd.to_datetime(end_date) + pd.DateOffset(days=1)
    return result[(parsed >= pd.to_datetime(start_date)) & (parsed < end_exclusive)]


def _filter_fund_announcements(
    data: pd.DataFrame,
    start_date: str,
    end_date: str,
    fallback_limit: int = 5,
) -> tuple[pd.DataFrame, bool]:
    result = data.copy()
    date_columns = [c for c in result.columns if "时间" in str(c) or "日期" in str(c) or "date" in str(c).lower()]
    if not date_columns:
        return result.head(fallback_limit), False

    parsed = pd.to_datetime(result[date_columns[0]], errors="coerce")
    result = result.assign(_parsed_date=parsed).dropna(subset=["_parsed_date"])
    if result.empty:
        return result, False

    start_dt = pd.to_datetime(start_date)
    end_exclusive = pd.to_datetime(end_date) + pd.DateOffset(days=1)
    in_window = result[(result["_parsed_date"] >= start_dt) & (result["_parsed_date"] < end_exclusive)]
    if not in_window.empty:
        return in_window.drop(columns=["_parsed_date"]), False

    fallback = result[result["_parsed_date"] < end_exclusive]
    fallback = fallback.sort_values("_parsed_date", ascending=False).head(fallback_limit)
    return fallback.drop(columns=["_parsed_date"]), True


def _render_table_like(title: str, data: Optional[pd.DataFrame], max_rows: int = 12) -> list[str]:
    if data is None or data.empty:
        return [f"## {title}", "No data available.", ""]
    return [f"## {title}", data.head(max_rows).to_csv(index=False), ""]


def _render_news_rows(data: pd.DataFrame) -> list[str]:
    rows = []
    for _, row in data.head(get_config()["news_article_limit"]).iterrows():
        title = _first_present(row, ["新闻标题", "标题", "公告标题", "title"], default="No title")
        source = _first_present(row, ["文章来源", "来源", "_source", "source"], default="Unknown")
        date = _first_present(row, ["发布时间", "日期", "公告日期", "date"], default="")
        url = _first_present(row, ["新闻链接", "链接", "公告链接", "url"], default="")
        rows.append(f"### {title} (source: {source})\nDate: {date}\nLink: {url}\n")
    return rows


def _safe_call(func):
    try:
        return func()
    except Exception:
        return pd.DataFrame()


def _safe_tiantian_fund_tables(symbol: str, curr_date: Optional[str]):
    try:
        return get_fund_profile_tables(symbol, curr_date)
    except Exception:
        return []


def _first_present(row: pd.Series, columns: list[str], default: str = ""):
    for column in columns:
        if column in row and pd.notna(row[column]):
            return row[column]
    return default


def _compact_date(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d").strftime("%Y%m%d")


def _to_akshare_statement_symbol(ticker: str) -> str:
    normalized = normalize_ticker_symbol(ticker)
    code, _, exchange = normalized.partition(".")
    if exchange in ("SH", "SZ", "BJ"):
        return f"{exchange}{code}"
    return to_akshare_symbol(ticker)


def _prefixed_cn_symbol(ticker: str) -> str:
    normalized = normalize_ticker_symbol(ticker)
    code, _, exchange = normalized.partition(".")
    if exchange == "SH":
        return f"sh{code}"
    if exchange == "SZ":
        return f"sz{code}"
    if exchange == "BJ":
        return f"bj{code}"
    return normalized.lower()


def _fund_holdings_year(curr_date: Optional[str]) -> str:
    if not curr_date:
        return str(datetime.now().year)
    return str(pd.to_datetime(curr_date).year)


def _indicator_descriptions() -> dict[str, str]:
    return {
        "close_50_sma": "50 SMA: medium-term trend indicator for support, resistance, and trend direction.",
        "close_200_sma": "200 SMA: long-term trend benchmark for strategic trend confirmation.",
        "close_10_ema": "10 EMA: short-term responsive trend indicator.",
        "macd": "MACD: momentum indicator based on moving-average convergence and divergence.",
        "macds": "MACD Signal: signal line used to identify crossovers.",
        "macdh": "MACD Histogram: visualizes the gap between MACD and signal line.",
        "rsi": "RSI: momentum indicator for overbought or oversold conditions.",
        "boll": "Bollinger Middle: moving-average basis for Bollinger Bands.",
        "boll_ub": "Bollinger Upper Band: upper volatility band.",
        "boll_lb": "Bollinger Lower Band: lower volatility band.",
        "atr": "ATR: average true range volatility indicator.",
        "vwma": "VWMA: volume-weighted moving average.",
        "mfi": "MFI: money flow index using price and volume.",
    }


def get_ticker_display_name(ticker: str) -> str:
    """Get verified Chinese display name (abbreviation or full name) for China instruments."""
    normalized = normalize_ticker_symbol(ticker)
    market_type = detect_market_type(normalized)
    if market_type == MarketType.CN_FUND:
        return _get_cn_fund_display_name(ticker, normalized)
    if market_type != MarketType.CN_A:
        return ticker
    return _get_cn_a_ticker_display_name(ticker, normalized)


@akshare_disk_cache(expire=86400 * 30)  # 超长本地磁盘缓存 30 天，确保极速读取与 IP 安全
def _get_cn_a_ticker_display_name(ticker: str, normalized: str) -> str:
    code = to_akshare_symbol(normalized)

    if detect_instrument_type(normalized) == InstrumentType.FUND:
        try:
            ak = _ak()
            df = ak.fund_overview_em(symbol=code)
            if not df.empty:
                for _, row in df.iterrows():
                    if row.get("项目") in ("基金简称", "基金简称：", "基金全称"):
                        return str(row.get("内容"))
        except Exception:
            pass
    else:
        try:
            ak = _ak()
            df = ak.stock_individual_info_em(symbol=code)
            if not df.empty:
                for _, row in df.iterrows():
                    if row.get("item") in ("股票简称", "股票全称"):
                        return str(row.get("value"))
        except Exception:
            pass
    return ticker


@akshare_disk_cache(expire=86400 * 30)
def _get_cn_fund_display_name(ticker: str, normalized: str) -> str:
    code = to_akshare_symbol(normalized)
    for table in _safe_tiantian_fund_tables(code, None):
        if table.title != "Tiantian Fund Overview":
            continue
        for _, row in table.data.iterrows():
            if row.get("项目") == "基金简称" and row.get("内容"):
                return str(row.get("内容"))
    return ticker
