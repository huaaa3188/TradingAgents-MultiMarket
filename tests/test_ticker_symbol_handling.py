import unittest

import pytest

from cli.utils import (
    detect_instrument_type,
    detect_market_type,
    normalize_ticker_symbol,
)
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.dataflows.instruments import InstrumentType, MarketType


@pytest.mark.unit
class TickerSymbolHandlingTests(unittest.TestCase):
    def test_normalize_ticker_symbol_preserves_exchange_suffix(self):
        self.assertEqual(normalize_ticker_symbol(" cnc.to "), "CNC.TO")

    def test_normalize_ticker_symbol_adds_a_share_suffixes(self):
        self.assertEqual(normalize_ticker_symbol("600519"), "600519.SH")
        self.assertEqual(normalize_ticker_symbol("000001"), "000001.SZ")
        self.assertEqual(normalize_ticker_symbol("300750"), "300750.SZ")

    def test_normalize_ticker_symbol_adds_listed_fund_suffixes(self):
        self.assertEqual(normalize_ticker_symbol("510300"), "510300.SH")
        self.assertEqual(normalize_ticker_symbol("159915"), "159915.SZ")
        self.assertEqual(normalize_ticker_symbol("161725"), "161725.SZ")
        self.assertEqual(normalize_ticker_symbol("508000"), "508000.SH")

    def test_detect_market_type(self):
        self.assertEqual(detect_market_type("600519"), MarketType.CN_A)
        self.assertEqual(detect_market_type("510300"), MarketType.CN_A)
        self.assertEqual(detect_market_type("AAPL"), MarketType.US)
        self.assertEqual(detect_market_type("0700.HK"), MarketType.HK)
        self.assertEqual(detect_market_type("BTC-USD"), MarketType.CRYPTO)

    def test_detect_instrument_type(self):
        self.assertEqual(detect_instrument_type("600519"), InstrumentType.EQUITY)
        self.assertEqual(detect_instrument_type("510300"), InstrumentType.FUND)
        self.assertEqual(detect_instrument_type("159915"), InstrumentType.FUND)
        self.assertEqual(detect_instrument_type("AAPL"), InstrumentType.EQUITY)
        self.assertEqual(detect_instrument_type("BTC-USD"), InstrumentType.CRYPTO)

    def test_unknown_bare_six_digit_code_is_not_guessed(self):
        self.assertEqual(normalize_ticker_symbol("900001"), "900001")
        self.assertEqual(detect_market_type("900001"), MarketType.OTHER)
        self.assertEqual(detect_instrument_type("900001"), InstrumentType.UNKNOWN)

    def test_build_instrument_context_mentions_exact_symbol(self):
        context = build_instrument_context("7203.T")
        self.assertIn("7203.T", context)
        self.assertIn("exchange suffix", context)

        context_with_name = build_instrument_context(
            "159696.SZ",
            company_display_name="纳斯达克ETF",
        )
        self.assertIn("159696.SZ", context_with_name)
        self.assertIn("Verified Name: **纳斯达克ETF**", context_with_name)
        self.assertIn("You MUST strictly analyze this specific target", context_with_name)

    def test_build_instrument_context_describes_cn_a_fund(self):
        context = build_instrument_context(
            "510300.SH",
            instrument_type=InstrumentType.FUND.value,
            market_type=MarketType.CN_A.value,
        )
        self.assertIn("listed fund", context)
        self.assertIn("not as an operating company", context)
        self.assertIn("quoted in CNY", context)

    def test_single_get_ticker_no_shadow(self):
        # Regression: cli/main.py had a duplicate get_ticker with an empty
        # questionary prompt (rendered as a bare "?") that shadowed the
        # descriptive one in cli/utils. Keep a single canonical definition.
        import cli.main
        import cli.utils
        self.assertIs(cli.main.get_ticker, cli.utils.get_ticker)


if __name__ == "__main__":
    unittest.main()
