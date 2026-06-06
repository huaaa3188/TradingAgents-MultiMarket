"""Tests for StockTwits graceful degradation."""

from __future__ import annotations

import logging
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from tradingagents.dataflows import stocktwits


@pytest.mark.unit
def test_http_error_returns_placeholder_without_warning_noise(caplog):
    err = HTTPError("url", 404, "Not Found", {}, None)

    with caplog.at_level(logging.DEBUG, logger=stocktwits.__name__):
        with patch.object(stocktwits, "urlopen", side_effect=err):
            out = stocktwits.fetch_stocktwits_messages("NOTREAL")

    assert out == "<stocktwits unavailable: HTTP 404>"
    assert "HTTP 404" in caplog.text
    assert "HTTP Error 404" not in caplog.text
    assert all(
        record.levelno < logging.WARNING
        for record in caplog.records
        if record.name == stocktwits.__name__
    )
