"""Per-tenant cost attribution, budgets, and Prometheus metrics."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from .ratecard import RateCard

LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)


class Metrics:
    """All metrics live on one registry so tests and servers can isolate them."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        r = self.registry
        self.requests = Counter(
            "aidelivery_requests_total", "Requests", ["tenant", "model", "status"], registry=r
        )
        self.duration = Histogram(
            "aidelivery_request_duration_seconds",
            "Request latency",
            ["tenant", "model"],
            buckets=LATENCY_BUCKETS,
            registry=r,
        )
        self.ttft = Histogram(
            "aidelivery_time_to_first_token_seconds",
            "Time to first streamed token",
            ["tenant", "model"],
            buckets=LATENCY_BUCKETS,
            registry=r,
        )
        self.tokens = Counter(
            "aidelivery_tokens_total", "Tokens", ["tenant", "model", "type"], registry=r
        )
        self.gpu_seconds = Counter(
            "aidelivery_gpu_seconds_total", "GPU seconds", ["tenant", "model"], registry=r
        )
        self.cost = Counter(
            "aidelivery_cost_usd_total", "Attributed cost in USD", ["tenant", "model"], registry=r
        )
        self.budget_remaining = Gauge(
            "aidelivery_budget_remaining_usd", "Budget left in USD", ["tenant"], registry=r
        )
        self.rate_limited = Counter(
            "aidelivery_rate_limited_total",
            "Rejected by limiter or budget",
            ["tenant", "reason"],
            registry=r,
        )


@dataclass(frozen=True)
class Usage:
    tenant: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    gpu_seconds: float


class CostAttributor:
    """Turns usage into cost and tracks spend against optional per-tenant budgets."""

    def __init__(
        self,
        rate_card: RateCard,
        metrics: Metrics | None = None,
        budgets: dict[str, float] | None = None,
    ) -> None:
        self.rate_card = rate_card
        self.metrics = metrics or Metrics()
        self._budgets = dict(budgets or {})
        self._spent: dict[str, float] = {}
        self._lock = threading.Lock()
        for tenant, limit in self._budgets.items():
            self.metrics.budget_remaining.labels(tenant).set(limit)

    def record(self, u: Usage) -> float:
        """Record usage, update metrics, and return the cost in USD."""
        cost = self.rate_card.cost(u.model, u.prompt_tokens, u.completion_tokens, u.gpu_seconds)
        m = self.metrics
        m.tokens.labels(u.tenant, u.model, "prompt").inc(u.prompt_tokens)
        m.tokens.labels(u.tenant, u.model, "completion").inc(u.completion_tokens)
        m.gpu_seconds.labels(u.tenant, u.model).inc(u.gpu_seconds)
        m.cost.labels(u.tenant, u.model).inc(cost)
        with self._lock:
            self._spent[u.tenant] = self._spent.get(u.tenant, 0.0) + cost
            if u.tenant in self._budgets:
                m.budget_remaining.labels(u.tenant).set(
                    self._budgets[u.tenant] - self._spent[u.tenant]
                )
        return cost

    def spent(self, tenant: str) -> float:
        with self._lock:
            return self._spent.get(tenant, 0.0)

    def budget_exhausted(self, tenant: str) -> bool:
        """True once spend has reached the tenant budget. Tenants without a budget never exhaust."""
        with self._lock:
            limit = self._budgets.get(tenant)
            return limit is not None and self._spent.get(tenant, 0.0) >= limit
