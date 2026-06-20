import re
from enum import Enum


class InstrumentType(str, Enum):
    EQUITY = "equity"
    FUND = "fund"
    CRYPTO = "crypto"
    UNKNOWN = "unknown"


class MarketType(str, Enum):
    US = "us"
    CN_A = "cn_a"
    CN_FUND = "cn_fund"
    HK = "hk"
    JP = "jp"
    CRYPTO = "crypto"
    OTHER = "other"


CRYPTO_SUFFIXES = ("-USD", "-USDT", "-USDC", "-BTC", "-ETH")
CN_A_SUFFIXES = (".SH", ".SZ", ".BJ")
CN_A_FUND_SH_PREFIXES = ("5",)
CN_A_FUND_SZ_PREFIXES = ("159", "16", "18")
CN_OTC_FUND_PREFIXES = ("01", "02")
CN_A_EQUITY_SH_PREFIXES = ("6",)
CN_A_EQUITY_SZ_PREFIXES = ("0", "3")
CN_A_EQUITY_BJ_PREFIXES = ("8", "4")
_SIX_DIGIT_RE = re.compile(r"^\d{6}$")


def normalize_ticker_symbol(ticker: str) -> str:
    """Normalize user input while preserving or adding known exchange suffixes."""
    normalized = ticker.strip().upper()
    if not _SIX_DIGIT_RE.fullmatch(normalized):
        return normalized

    if _is_cn_a_fund_code(normalized):
        return f"{normalized}.{_cn_a_exchange_for_fund(normalized)}"
    if _is_cn_otc_fund_code(normalized):
        return normalized
    if normalized.startswith(CN_A_EQUITY_SH_PREFIXES):
        return f"{normalized}.SH"
    if normalized.startswith(CN_A_EQUITY_SZ_PREFIXES):
        return f"{normalized}.SZ"
    if normalized.startswith(CN_A_EQUITY_BJ_PREFIXES):
        return f"{normalized}.BJ"
    return normalized


def detect_market_type(ticker: str) -> MarketType:
    normalized = normalize_ticker_symbol(ticker)
    if normalized.endswith(CRYPTO_SUFFIXES):
        return MarketType.CRYPTO
    code, _, suffix = normalized.partition(".")
    if _SIX_DIGIT_RE.fullmatch(code) and _is_cn_otc_fund_code(code):
        return MarketType.CN_FUND
    if normalized.endswith(CN_A_SUFFIXES):
        return MarketType.CN_A
    if normalized.endswith(".HK"):
        return MarketType.HK
    if normalized.endswith(".T"):
        return MarketType.JP
    if _SIX_DIGIT_RE.fullmatch(normalized):
        return MarketType.OTHER
    if "." not in normalized and "-" not in normalized and normalized:
        return MarketType.US
    return MarketType.OTHER


def detect_instrument_type(ticker: str) -> InstrumentType:
    normalized = normalize_ticker_symbol(ticker)
    if normalized.endswith(CRYPTO_SUFFIXES):
        return InstrumentType.CRYPTO
    code, _, suffix = normalized.partition(".")
    if _SIX_DIGIT_RE.fullmatch(code) and _is_cn_otc_fund_code(code):
        return InstrumentType.FUND
    if suffix in ("SH", "SZ", "BJ") and _SIX_DIGIT_RE.fullmatch(code):
        if _is_cn_a_fund_code(code):
            return InstrumentType.FUND
        if code.startswith(CN_A_EQUITY_SH_PREFIXES + CN_A_EQUITY_SZ_PREFIXES + CN_A_EQUITY_BJ_PREFIXES):
            return InstrumentType.EQUITY
    if normalized and not _SIX_DIGIT_RE.fullmatch(normalized):
        return InstrumentType.EQUITY
    return InstrumentType.UNKNOWN


def is_cn_a_ticker(ticker: str) -> bool:
    return detect_market_type(ticker) == MarketType.CN_A


def is_cn_a_fund(ticker: str) -> bool:
    return detect_instrument_type(ticker) == InstrumentType.FUND and is_cn_a_ticker(ticker)


def is_cn_otc_fund(ticker: str) -> bool:
    return detect_market_type(ticker) == MarketType.CN_FUND and detect_instrument_type(ticker) == InstrumentType.FUND


def to_akshare_symbol(ticker: str) -> str:
    """Return the pure numeric symbol expected by AkShare's A-share APIs."""
    normalized = normalize_ticker_symbol(ticker)
    if normalized.endswith(CN_A_SUFFIXES):
        return normalized.split(".", 1)[0]
    return normalized


def _is_cn_a_fund_code(code: str) -> bool:
    return code.startswith(CN_A_FUND_SH_PREFIXES + CN_A_FUND_SZ_PREFIXES)


def _is_cn_otc_fund_code(code: str) -> bool:
    return code.startswith(CN_OTC_FUND_PREFIXES)


def _cn_a_exchange_for_fund(code: str) -> str:
    if code.startswith(CN_A_FUND_SH_PREFIXES):
        return "SH"
    return "SZ"
