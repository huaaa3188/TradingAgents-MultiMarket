from unittest.mock import MagicMock

from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_initial_state_does_not_resolve_akshare_display_name_for_us_ticker(monkeypatch):
    from tradingagents.dataflows import akshare
    from tradingagents.graph.propagation import Propagator

    calls = []
    monkeypatch.setattr(
        akshare,
        "get_ticker_display_name",
        lambda ticker: calls.append(ticker) or "should-not-be-used",
    )

    state = Propagator().create_initial_state("NVDA", "2026-01-03")

    assert state["company_display_name"] == "NVDA"
    assert state["market_type"] == "us"
    assert calls == []


def test_propagate_normalizes_cn_a_ticker_before_running_graph():
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"checkpoint_enabled": False}
    graph._checkpointer_ctx = None
    graph._resolve_pending_entries = MagicMock()
    graph._run_graph = MagicMock(return_value=("state", "decision"))

    result = TradingAgentsGraph.propagate(graph, "510300", "2026-01-03")

    assert result == ("state", "decision")
    assert graph.ticker == "510300.SH"
    graph._resolve_pending_entries.assert_called_once_with("510300.SH")
    graph._run_graph.assert_called_once_with(
        "510300.SH",
        "2026-01-03",
        asset_type="stock",
    )


def test_sentiment_analyst_builds_prompt_adaptively_for_fund():
    from tradingagents.agents.analysts.sentiment_analyst import _build_system_message

    # 1. 验证 equity 股票提示词
    equity_msg = _build_system_message(
        ticker="AAPL",
        start_date="2026-01-01",
        end_date="2026-01-08",
        news_block="news",
        stocktwits_block="stocktwits",
        reddit_block="reddit",
        instrument_type="equity",
    )
    assert "Bullish/Bearish ratio as a leading retail-sentiment signal" in equity_msg
    assert "Absolutely avoid analyzing company revenue" not in equity_msg

    # 2. 验证 fund 基金提示词
    fund_msg = _build_system_message(
        ticker="510300",
        start_date="2026-01-01",
        end_date="2026-01-08",
        news_block="news",
        stocktwits_block="stocktwits",
        reddit_block="reddit",
        instrument_type="fund",
    )
    assert "leading indicator of thematic or index-level sentiment" in fund_msg
    assert "Absolutely avoid analyzing company revenue" in fund_msg


def test_news_analyst_prompt_adapts_for_fund():
    from tradingagents.agents.analysts.news_analyst import create_news_analyst

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm

    node = create_news_analyst(mock_llm)

    state = {
        "company_of_interest": "510300",
        "trade_date": "2026-01-08",
        "asset_type": "stock",
        "instrument_type": "fund",
        "market_type": "cn_a",
        "messages": [],
    }

    try:
        node(state)
    except Exception:
        # node 在 chain.invoke 时可能报错，我们只需拦截 mock_llm 的传参即可
        pass

    assert mock_llm.called
    args, kwargs = mock_llm.call_args
    prompt_text = str(args[0])

    assert "fund manager changes" in prompt_text
    assert "Do not describe the fund as an operating company" in prompt_text
