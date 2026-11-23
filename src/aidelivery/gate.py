"""Continuous-verification gate: decide promote or rollback from canary signals."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

PROMOTE = 0
ROLLBACK = 1
INPUT_ERROR = 2

_LINE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>.*)\})?\s+(?P<value>\S+)(?:\s+\d+)?$"
)
_LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Sample:
    name: str
    labels: dict[str, str]
    value: float


def parse_prometheus_text(text: str) -> list[Sample]:
    """Parse Prometheus text exposition format. Comments and blank lines are skipped."""
    out: list[Sample] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            raise ValueError(f"cannot parse metrics line: {line!r}")
        labels = dict(_LABEL.findall(m.group("labels") or ""))
        out.append(Sample(m.group("name"), labels, float(m.group("value"))))
    return out


def _sum(samples: list[Sample], name: str, tenant: str | None = None) -> float:
    return sum(
        s.value
        for s in samples
        if s.name == name and (tenant is None or s.labels.get("tenant") == tenant)
    )


def histogram_quantile(
    samples: list[Sample], metric: str, q: float, tenant: str | None = None
) -> float | None:
    """p-quantile from cumulative `_bucket` samples, interpolated like PromQL. None if empty."""
    cum: dict[float, float] = defaultdict(float)
    for s in samples:
        if s.name != f"{metric}_bucket":
            continue
        if tenant is not None and s.labels.get("tenant") != tenant:
            continue
        cum[float(s.labels["le"])] += s.value
    if not cum:
        return None
    bounds = sorted(cum)
    total = cum[bounds[-1]]
    if total == 0:
        return None
    rank = q * total
    prev_bound, prev_count = 0.0, 0.0
    for b in bounds:
        if cum[b] >= rank:
            if math.isinf(b):
                return prev_bound
            span = cum[b] - prev_count
            if span == 0:
                return b
            return prev_bound + (b - prev_bound) * (rank - prev_count) / span
        prev_bound, prev_count = b, cum[b]
    return prev_bound


@dataclass(frozen=True)
class Thresholds:
    max_p95_latency_seconds: float = 2.0
    max_error_rate: float = 0.02
    max_cost_per_1k_tokens: float = 0.01
    min_eval_score: float = 0.85
    max_hallucination_rate: float = 0.05
    min_requests: int = 20

    @classmethod
    def load(cls, path: str | Path) -> Thresholds:
        return cls(**json.loads(Path(path).read_text()))


@dataclass
class Check:
    name: str
    value: float | None
    limit: float
    op: str  # "<=" or ">="
    ok: bool
    note: str = ""


@dataclass
class Decision:
    promote: bool
    checks: list[Check] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return PROMOTE if self.promote else ROLLBACK


def evaluate(
    samples: list[Sample],
    eval_data: dict[str, float],
    t: Thresholds,
    tenant: str | None = None,
) -> Decision:
    """Missing data fails closed: a check with no value is a failed check."""
    checks: list[Check] = []

    total = _sum(samples, "aidelivery_requests_total", tenant)
    errors = sum(
        s.value
        for s in samples
        if s.name == "aidelivery_requests_total"
        and (tenant is None or s.labels.get("tenant") == tenant)
        and s.labels.get("status", "200").startswith("5")
    )
    enough = total >= t.min_requests
    checks.append(
        Check("request_volume", total, float(t.min_requests), ">=", enough, "too little traffic")
    )

    p95 = histogram_quantile(samples, "aidelivery_request_duration_seconds", 0.95, tenant)
    checks.append(
        Check(
            "p95_latency_seconds",
            p95,
            t.max_p95_latency_seconds,
            "<=",
            p95 is not None and p95 <= t.max_p95_latency_seconds,
        )
    )

    err = errors / total if total else None
    checks.append(
        Check(
            "error_rate", err, t.max_error_rate, "<=", err is not None and err <= t.max_error_rate
        )
    )

    tokens = _sum(samples, "aidelivery_tokens_total", tenant)
    cost = _sum(samples, "aidelivery_cost_usd_total", tenant)
    cp1k = cost / (tokens / 1000) if tokens else None
    checks.append(
        Check(
            "cost_per_1k_tokens_usd",
            cp1k,
            t.max_cost_per_1k_tokens,
            "<=",
            cp1k is not None and cp1k <= t.max_cost_per_1k_tokens,
        )
    )

    score = eval_data.get("score")
    checks.append(
        Check(
            "eval_score",
            score,
            t.min_eval_score,
            ">=",
            score is not None and score >= t.min_eval_score,
        )
    )
    hall = eval_data.get("hallucination_rate")
    checks.append(
        Check(
            "hallucination_rate",
            hall,
            t.max_hallucination_rate,
            "<=",
            hall is not None and hall <= t.max_hallucination_rate,
        )
    )
    return Decision(promote=all(c.ok for c in checks), checks=checks)


def format_decision(d: Decision) -> str:
    lines = []
    for c in d.checks:
        val = "missing" if c.value is None else f"{c.value:.6g}"
        lines.append(f"{'PASS' if c.ok else 'FAIL'} {c.name}: {val} (need {c.op} {c.limit:g})")
    lines.append("DECISION: " + ("PROMOTE" if d.promote else "ROLLBACK"))
    return "\n".join(lines)
