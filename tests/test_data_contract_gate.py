from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.dataflows.contracts import (
    DataResult,
    SourceMeta,
    build_data_contract_status,
    collect_data_contract_status_from_messages,
    data_notice,
    merge_data_contract_status,
    parse_contract_gate_status,
    render_contract_gate,
    render_data_contract_status,
    validate_data_result,
)
from tradingagents.graph.propagation import Propagator


def _result(
    *,
    semantic: str = "ohlcv",
    as_of: str | None = "2026-05-22",
    ok: bool = True,
    missing_reason: str | None = None,
    error_type: str | None = None,
    notices=(),
    stale: bool = False,
) -> DataResult:
    return DataResult(
        meta=SourceMeta(
            vendor="akshare",
            source="fake_source",
            symbol="600519.SH",
            semantic=semantic,
            as_of=as_of,
        ),
        payload=pd.DataFrame([{"Date": as_of or "2026-05-22", "Close": 1.0}]) if ok else None,
        notices=tuple(notices),
        ok=ok,
        stale=stale,
        missing_reason=missing_reason,
        error_type=error_type,
    )


@pytest.mark.unit
def test_gate_fails_missing_result_by_default():
    gate = validate_data_result(
        _result(ok=False, missing_reason="no_rows"),
        analysis_date="2026-05-22",
        expected_semantic="ohlcv",
    )

    assert gate.ok is False
    assert [notice.code for notice in gate.failures] == ["no_rows"]


@pytest.mark.unit
def test_gate_fails_schema_drift_even_when_fallback_result_has_rows():
    gate = validate_data_result(
        _result(
            error_type="schema_drift",
            notices=(data_notice("schema_drift", "drift"),),
        ),
        analysis_date="2026-05-22",
        expected_semantic="ohlcv",
    )

    assert gate.ok is False
    assert "schema_drift" in [notice.code for notice in gate.failures]


@pytest.mark.unit
def test_gate_fails_future_data():
    gate = validate_data_result(
        _result(as_of="2026-05-23"),
        analysis_date="2026-05-22",
        expected_semantic="ohlcv",
    )

    assert gate.ok is False
    assert [notice.code for notice in gate.failures] == ["future_data"]


@pytest.mark.unit
def test_gate_fails_stale_data_when_threshold_exceeded():
    gate = validate_data_result(
        _result(as_of="2026-05-01"),
        analysis_date="2026-05-22",
        expected_semantic="ohlcv",
        max_staleness_days=10,
    )

    assert gate.ok is False
    assert [notice.code for notice in gate.failures] == ["stale_data"]


@pytest.mark.unit
def test_gate_warns_for_nav_semantic_restrictions():
    gate = validate_data_result(
        _result(semantic="nav"),
        analysis_date="2026-05-22",
        expected_semantic="nav",
    )

    assert gate.ok is True
    assert [notice.code for notice in gate.warnings] == ["nav_semantic"]
    rendered = render_contract_gate(gate)
    assert "Status: PASS" in rendered
    assert "daily fund NAV" in rendered


@pytest.mark.unit
def test_rendered_gate_can_be_collected_into_state_status():
    gate = validate_data_result(
        _result(semantic="nav"),
        analysis_date="2026-05-22",
        expected_semantic="nav",
    )

    checks = parse_contract_gate_status(render_contract_gate(gate, "Verified Market Data Contract Gate"))
    status = merge_data_contract_status(build_data_contract_status(), checks)
    summary = render_data_contract_status(status)

    assert status["overall"] == "warning"
    assert status["checks"][0]["semantic"] == "nav"
    assert status["checks"][0]["warnings"] == ["nav_semantic"]
    assert "## Data Reliability" in summary
    assert "nav_semantic" in summary


@pytest.mark.unit
def test_collect_data_contract_status_from_messages_deduplicates_checks():
    gate = validate_data_result(
        _result(error_type="schema_drift", notices=(data_notice("schema_drift", "drift"),)),
        analysis_date="2026-05-22",
        expected_semantic="ohlcv",
    )
    rendered = render_contract_gate(gate, "Verified Market Data Contract Gate")

    class Message:
        content = rendered

    status = collect_data_contract_status_from_messages([Message(), Message()])

    assert status["overall"] == "fail"
    assert len(status["checks"]) == 1
    assert status["checks"][0]["failures"] == ["schema_drift"]


@pytest.mark.unit
def test_initial_graph_state_has_empty_data_contract_status():
    state = Propagator().create_initial_state("COF", "2026-05-22")

    assert state["data_contract_status"] == {"overall": "not_checked", "checks": []}
