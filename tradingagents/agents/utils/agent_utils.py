from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)
from tradingagents.dataflows.instruments import InstrumentType, MarketType


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Applied to every agent whose output reaches the saved report —
    analysts, researchers, debaters, research manager, trader, and
    portfolio manager — so a non-English run produces a fully localized
    report rather than a mix of languages.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(
    ticker: str,
    asset_type: str = "stock",
    instrument_type: str = None,
    market_type: str = None,
    company_display_name: str = None,
) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    instrument_value = (instrument_type or "").lower()
    market_value = (market_type or "").lower()

    if asset_type == "crypto" or instrument_value == InstrumentType.CRYPTO.value:
        instrument_label = "asset"
        extra_hint = (
            " Treat it as a crypto asset rather than a company, and do not assume company fundamentals are available."
        )
    elif instrument_value == InstrumentType.FUND.value:
        instrument_label = "fund"
        extra_hint = (
            " Treat it as an exchange-traded fund or listed fund, not as an operating company."
            " Focus on the tracked benchmark or theme, premium/discount, liquidity, fund size,"
            " fees, holdings, and market risk; do not infer company revenue, earnings,"
            " balance-sheet, or cash-flow fundamentals."
        )
    else:
        instrument_label = "instrument"
        extra_hint = ""

    if market_value == MarketType.CN_A.value:
        extra_hint += (
            " This is a mainland China listed instrument quoted in CNY; account for A-share"
            " trading sessions, price-limit rules, settlement conventions, holidays, and"
            " China-specific disclosure and financial reporting cadence."
        )

    display_name_hint = ""
    if company_display_name and company_display_name != ticker:
        display_name_hint = f" (Verified Name: **{company_display_name}**). You MUST strictly analyze this specific target and strictly refer to it by its verified name. Do NOT hallucinate any other names or indexes."

    return (
        f"The {instrument_label} to analyze is `{ticker}`{display_name_hint}. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.SH`, `.SZ`, `.TO`, `.L`, `.HK`, `.T`, `-USD`)."
        + extra_hint
    )


def build_verified_target_context(state) -> str:
    """Build the shared target identity context from graph state."""
    return build_instrument_context(
        state.get("company_of_interest", ""),
        asset_type=state.get("asset_type", "stock"),
        instrument_type=state.get("instrument_type"),
        market_type=state.get("market_type"),
        company_display_name=state.get("company_display_name"),
    )


def get_instrument_target_label(state) -> str:
    instrument_type = state.get("instrument_type", "")
    if state.get("asset_type") == "crypto" or instrument_type == InstrumentType.CRYPTO.value:
        return "asset"
    if instrument_type == InstrumentType.FUND.value:
        return "listed fund"
    return "stock"


def get_fundamentals_report_label(state) -> str:
    instrument_type = state.get("instrument_type", "")
    if state.get("asset_type") == "crypto" or instrument_type == InstrumentType.CRYPTO.value:
        return "Asset fundamentals report (may be unavailable for crypto)"
    if instrument_type == InstrumentType.FUND.value:
        return "Fund profile report"
    return "Company fundamentals report"

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
