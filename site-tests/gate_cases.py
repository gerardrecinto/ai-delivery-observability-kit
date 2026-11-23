"""Print JSON with the Python gate's decision for several cases.

Fixture cases run the real `aidelivery gate` CLI on the files in tests/fixtures/. Synthetic cases
write temporary Prometheus text and eval JSON, then run the same CLI. The slider values come
from the parsed metrics so the browser demo can be driven with the same inputs.
"""

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aidelivery import gate  # noqa: E402
from aidelivery.cli import main  # noqa: E402

FX = ROOT / "tests" / "fixtures"


def run_cli(prom: Path, ev: Path) -> tuple[int, list[str]]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(["gate", "--metrics", str(prom), "--eval", str(ev)])
    failed = [
        ln.split()[1].rstrip(":") for ln in buf.getvalue().splitlines() if ln.startswith("FAIL")
    ]
    # The demo holds hallucination_rate fixed, so only its four sliders are compared.
    return code, [f for f in failed if f != "hallucination_rate"]


def values_from(prom: Path, ev: Path) -> dict[str, float]:
    s = gate.parse_prometheus_text(prom.read_text())
    total = sum(x.value for x in s if x.name == "aidelivery_requests_total")
    errs = sum(
        x.value
        for x in s
        if x.name == "aidelivery_requests_total" and x.labels.get("status", "200").startswith("5")
    )
    tokens = sum(x.value for x in s if x.name == "aidelivery_tokens_total")
    cost = sum(x.value for x in s if x.name == "aidelivery_cost_usd_total")
    p95 = gate.histogram_quantile(s, "aidelivery_request_duration_seconds", 0.95)
    assert p95 is not None
    return {
        "err": errs / total,
        "p95": p95,
        "cost": cost / (tokens / 1000),
        "eval": json.loads(ev.read_text())["score"],
    }


def synthetic(err: float, p95: float, cost: float, score: float, tmp: Path) -> tuple[Path, Path]:
    bound = p95 / 0.95  # one bucket holding every request, so quantile 0.95 lands on p95
    prom = tmp / "m.prom"
    prom.write_text(
        f'aidelivery_requests_total{{tenant="t",status="200"}} {100 * (1 - err)}\n'
        f'aidelivery_requests_total{{tenant="t",status="500"}} {100 * err}\n'
        f'aidelivery_request_duration_seconds_bucket{{tenant="t",le="{bound}"}} 100\n'
        f'aidelivery_request_duration_seconds_bucket{{tenant="t",le="+Inf"}} 100\n'
        f'aidelivery_tokens_total{{tenant="t",type="prompt"}} 10000\n'
        f'aidelivery_cost_usd_total{{tenant="t"}} {cost * 10}\n'
    )
    ev = tmp / "e.json"
    ev.write_text(json.dumps({"score": score, "hallucination_rate": 0.02}))
    return prom, ev


def main_cases() -> list[dict]:
    out = []
    fixtures = [
        ("fixture good", "canary_good.prom", "eval_good.json"),
        ("fixture slow", "canary_slow.prom", "eval_good.json"),
        ("fixture bad errors", "canary_bad_errors.prom", "eval_good.json"),
        ("fixture costly", "canary_costly.prom", "eval_good.json"),
        ("fixture bad eval", "canary_good.prom", "eval_bad.json"),
    ]
    for name, p, e in fixtures:
        code, failed = run_cli(FX / p, FX / e)
        if name == "fixture bad eval":
            code = (
                1 if failed else 0
            )  # eval_bad.json also fails hallucination_rate, not modeled in the demo
        out.append(
            {"name": name, "values": values_from(FX / p, FX / e), "code": code, "failed": failed}
        )
    synth = [
        ("synthetic inside limits", 0.015, 1.9, 0.009, 0.86),
        ("synthetic error rate just over", 0.021, 0.5, 0.004, 0.9),
        ("synthetic error rate at limit", 0.02, 0.5, 0.004, 0.9),
        ("synthetic eval just under", 0.0, 0.5, 0.004, 0.84),
        ("synthetic eval at limit", 0.0, 0.5, 0.004, 0.85),
        ("synthetic everything bad", 0.05, 3.0, 0.02, 0.5),
    ]
    with tempfile.TemporaryDirectory() as d:
        for name, err, p95, cost, score in synth:
            prom, ev = synthetic(err, p95, cost, score, Path(d))
            code, failed = run_cli(prom, ev)
            out.append(
                {
                    "name": name,
                    "values": {"err": err, "p95": p95, "cost": cost, "eval": score},
                    "code": code,
                    "failed": failed,
                }
            )
    return out


if __name__ == "__main__":
    print(json.dumps(main_cases()))
