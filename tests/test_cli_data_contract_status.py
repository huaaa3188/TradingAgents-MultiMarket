from __future__ import annotations

import cli.main as cli_main


def _status():
    return {
        "overall": "warning",
        "checks": [
            {
                "status": "pass",
                "source": "tiantian_fund_nav",
                "symbol": "012920",
                "semantic": "nav",
                "expected_semantic": "nav",
                "as_of": "2026-05-22",
                "rows": 3,
                "failures": [],
                "warnings": ["nav_semantic"],
            }
        ],
    }


def test_message_buffer_includes_data_reliability_in_current_and_final_report():
    buffer = cli_main.MessageBuffer()
    buffer.init_for_analysis(["market"])

    buffer.update_report_section("market_report", "Market report body.")
    buffer.update_data_contract_status(_status())

    assert "### Data Reliability" in buffer.current_report
    assert "nav_semantic" in buffer.current_report
    assert "## Data Reliability" in buffer.final_report
    assert "Market report body." in buffer.final_report


def test_save_report_to_disk_writes_data_reliability(tmp_path):
    final_state = {
        "data_contract_status": _status(),
        "market_report": "Market report body.",
    }

    report_path = cli_main.save_report_to_disk(final_state, "012920", tmp_path)

    data_reliability = tmp_path / "data_reliability.md"
    assert data_reliability.exists()
    assert "## Data Reliability" in data_reliability.read_text(encoding="utf-8")
    assert "nav_semantic" in report_path.read_text(encoding="utf-8")
