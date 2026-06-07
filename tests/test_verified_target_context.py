from types import SimpleNamespace

import pytest

from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
from tradingagents.agents.risk_mgmt.conservative_debator import create_conservative_debator
from tradingagents.agents.risk_mgmt.neutral_debator import create_neutral_debator
from tradingagents.agents.utils.agent_utils import (
    append_fund_semantic_warning,
    build_verified_target_context,
)


class CapturingLLM:
    def __init__(self):
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return SimpleNamespace(content="captured")


def _fund_state():
    return {
        "company_of_interest": "159696.SZ",
        "company_display_name": "纳斯达克ETF",
        "asset_type": "stock",
        "instrument_type": "fund",
        "market_type": "cn_a",
        "market_report": "market report",
        "sentiment_report": "sentiment report",
        "news_report": "news report",
        "fundamentals_report": "fund profile",
        "trader_investment_plan": "Hold with risk controls.",
        "investment_debate_state": {
            "history": "",
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "count": 0,
        },
        "risk_debate_state": {
            "history": "",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "latest_speaker": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "count": 0,
        },
    }


def _assert_verified_target_context(prompt):
    assert "Target identity:" in prompt
    assert "159696.SZ" in prompt
    assert "Verified Name: **纳斯达克ETF**" in prompt
    assert "You MUST strictly analyze this specific target" in prompt
    assert "not as an operating company" in prompt
    assert "quoted in CNY" in prompt


def test_build_verified_target_context_uses_state_identity():
    context = build_verified_target_context(_fund_state())

    _assert_verified_target_context("Target identity:\n" + context)


def test_fund_semantic_warning_flags_company_fundamentals_terms():
    report = "The ETF has strong company revenue and a resilient 资产负债表."

    guarded = append_fund_semantic_warning(_fund_state(), report)

    assert report in guarded
    assert "Fund semantics warning:" in guarded
    assert "company revenue" in guarded
    assert "资产负债表" in guarded


def test_fund_semantic_warning_ignores_clean_fund_report():
    report = "The listed fund has NAV momentum, low fees, and diversified holdings."

    assert append_fund_semantic_warning(_fund_state(), report) == report


def test_fund_semantic_warning_ignores_equity_state():
    state = {
        **_fund_state(),
        "instrument_type": "equity",
    }
    report = "Company revenue and cash flow are improving."

    assert append_fund_semantic_warning(state, report) == report


@pytest.mark.parametrize(
    "factory",
    [
        create_bull_researcher,
        create_bear_researcher,
    ],
)
def test_researcher_prompts_include_verified_target_context(factory):
    llm = CapturingLLM()
    node = factory(llm)

    node(_fund_state())

    _assert_verified_target_context(llm.prompts[-1])


@pytest.mark.parametrize(
    "factory",
    [
        create_aggressive_debator,
        create_conservative_debator,
        create_neutral_debator,
    ],
)
def test_risk_prompts_include_verified_target_context(factory):
    llm = CapturingLLM()
    node = factory(llm)

    node(_fund_state())

    _assert_verified_target_context(llm.prompts[-1])
