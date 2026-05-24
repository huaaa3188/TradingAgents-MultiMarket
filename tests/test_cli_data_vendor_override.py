import copy

import pytest
from typer.testing import CliRunner

import cli.main as cli_main
from tradingagents.default_config import DEFAULT_CONFIG


def test_apply_data_vendor_override_updates_all_data_categories():
    config = copy.deepcopy(DEFAULT_CONFIG)

    cli_main._apply_data_vendor_override(config, " akshare, yfinance ")

    assert config["data_vendors"] == {
        "core_stock_apis": "akshare,yfinance",
        "technical_indicators": "akshare,yfinance",
        "fundamental_data": "akshare,yfinance",
        "news_data": "akshare,yfinance",
    }


def test_apply_data_vendor_override_rejects_empty_value():
    config = copy.deepcopy(DEFAULT_CONFIG)

    with pytest.raises(ValueError, match="No valid data vendor"):
        cli_main._apply_data_vendor_override(config, " , ")


def test_analyze_command_passes_data_vendor_override(monkeypatch):
    captured = {}

    def fake_run_analysis(
        *,
        checkpoint=False,
        data_vendors=None,
        save_report=None,
        display_report=None,
    ):
        captured["checkpoint"] = checkpoint
        captured["data_vendors"] = data_vendors
        captured["save_report"] = save_report
        captured["display_report"] = display_report

    monkeypatch.setattr(cli_main, "run_analysis", fake_run_analysis)

    result = CliRunner().invoke(
        cli_main.app,
        [
            "--data-vendors",
            "akshare,yfinance",
            "--no-save-report",
            "--no-display-report",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "checkpoint": False,
        "data_vendors": "akshare,yfinance",
        "save_report": False,
        "display_report": False,
    }


def test_analyze_command_keeps_report_prompt_flags_unset_by_default(monkeypatch):
    captured = {}

    def fake_run_analysis(
        *,
        checkpoint=False,
        data_vendors=None,
        save_report=None,
        display_report=None,
    ):
        captured["save_report"] = save_report
        captured["display_report"] = display_report

    monkeypatch.setattr(cli_main, "run_analysis", fake_run_analysis)

    result = CliRunner().invoke(cli_main.app, [])

    assert result.exit_code == 0
    assert captured == {"save_report": None, "display_report": None}
