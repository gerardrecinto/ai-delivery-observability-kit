from pathlib import Path

import pytest

from aidelivery import gate
from aidelivery.cli import main

FX = Path(__file__).parent / "fixtures"


def run(prom: str, ev: str, *extra: str) -> int:
    return main(["gate", "--metrics", str(FX / prom), "--eval", str(FX / ev), *extra])


def test_good_canary_promotes(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("canary_good.prom", "eval_good.json") == 0
    assert "DECISION: PROMOTE" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("prom", "ev", "failing"),
    [
        ("canary_slow.prom", "eval_good.json", "p95_latency_seconds"),
        ("canary_bad_errors.prom", "eval_good.json", "error_rate"),
        ("canary_costly.prom", "eval_good.json", "cost_per_1k_tokens_usd"),
        ("canary_good.prom", "eval_bad.json", "eval_score"),
    ],
)
def test_each_signal_triggers_rollback(
    prom: str, ev: str, failing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(prom, ev) == 1
    out = capsys.readouterr().out
    assert f"FAIL {failing}" in out
    assert "DECISION: ROLLBACK" in out


def test_p95_interpolation_matches_promql() -> None:
    s = gate.parse_prometheus_text((FX / "canary_good.prom").read_text())
    q = gate.histogram_quantile(s, "aidelivery_request_duration_seconds", 0.95)
    assert q == pytest.approx(0.375)


def test_missing_data_fails_closed() -> None:
    d = gate.evaluate([], {}, gate.Thresholds())
    assert not d.promote
    assert all(not c.ok for c in d.checks)


def test_low_traffic_fails() -> None:
    s = gate.parse_prometheus_text((FX / "canary_good.prom").read_text())
    d = gate.evaluate(s, {"score": 1, "hallucination_rate": 0}, gate.Thresholds(min_requests=1000))
    assert not d.promote


def test_tenant_filter() -> None:
    s = gate.parse_prometheus_text((FX / "canary_good.prom").read_text())
    ev = {"score": 1.0, "hallucination_rate": 0.0}
    assert gate.evaluate(s, ev, gate.Thresholds(), tenant="acme").promote
    assert not gate.evaluate(s, ev, gate.Thresholds(), tenant="nobody").promote


def test_threshold_file_override(tmp_path: Path) -> None:
    t = tmp_path / "t.json"
    t.write_text('{"max_p95_latency_seconds": 0.1}')
    assert run("canary_good.prom", "eval_good.json", "--thresholds", str(t)) == 1


def test_bad_input_exit_code_2() -> None:
    assert main(["gate", "--metrics", "/nonexistent", "--eval", "/nonexistent"]) == 2


def test_unparseable_metrics_exit_code_2(tmp_path: Path) -> None:
    p = tmp_path / "bad.prom"
    p.write_text("this is not a metric line\n")
    assert main(["gate", "--metrics", str(p), "--eval", str(FX / "eval_good.json")]) == 2
