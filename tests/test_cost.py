import threading

import pytest
from prometheus_client import CollectorRegistry

from aidelivery.cost import CostAttributor, Metrics, Usage
from aidelivery.ratecard import ModelRate, RateCard

CARD = RateCard(
    default=ModelRate(1.0, 2.0, 0.5),
    models={"big": ModelRate(10.0, 20.0, 1.0)},
)


def make(budgets: dict[str, float] | None = None) -> CostAttributor:
    return CostAttributor(CARD, Metrics(CollectorRegistry()), budgets)


def test_cost_math_default_and_model_override() -> None:
    assert CARD.cost("x", 1000, 1000, 2) == pytest.approx(1.0 + 2.0 + 1.0)
    assert CARD.cost("big", 500, 500, 1) == pytest.approx(5.0 + 10.0 + 1.0)


def test_negative_usage_rejected() -> None:
    with pytest.raises(ValueError):
        CARD.cost("x", -1, 0, 0)


def test_metrics_labelled_per_tenant() -> None:
    c = make()
    c.record(Usage("a", "x", 1000, 0, 0))
    c.record(Usage("b", "x", 0, 1000, 0))
    reg = c.metrics.registry
    assert reg.get_sample_value("aidelivery_cost_usd_total", {"tenant": "a", "model": "x"}) == 1.0
    assert reg.get_sample_value("aidelivery_cost_usd_total", {"tenant": "b", "model": "x"}) == 2.0
    assert (
        reg.get_sample_value(
            "aidelivery_tokens_total", {"tenant": "b", "model": "x", "type": "completion"}
        )
        == 1000
    )


def test_budget_exhaustion_and_remaining_gauge() -> None:
    c = make({"a": 3.0})
    assert not c.budget_exhausted("a")
    c.record(Usage("a", "x", 1000, 0, 0))
    assert c.metrics.registry.get_sample_value(
        "aidelivery_budget_remaining_usd", {"tenant": "a"}
    ) == pytest.approx(2.0)
    c.record(Usage("a", "x", 2000, 0, 0))
    assert c.budget_exhausted("a")


def test_tenant_without_budget_never_exhausts() -> None:
    c = make({"a": 1.0})
    c.record(Usage("other", "x", 10**6, 0, 0))
    assert not c.budget_exhausted("other")


def test_concurrent_records_sum_exactly() -> None:
    c = make({"a": 1e9})
    threads = [
        threading.Thread(target=lambda: [c.record(Usage("a", "x", 1000, 0, 0)) for _ in range(100)])
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert c.spent("a") == pytest.approx(800.0)


def test_ratecard_load(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "rc.json"
    p.write_text('{"default": {"prompt_per_1k": 1, "completion_per_1k": 2}}')
    assert RateCard.load(p).cost("m", 1000, 1000, 5) == 3.0
