import json

import pytest
from fastapi.testclient import TestClient

from aidelivery.mock_server import create_app
from aidelivery.quota import TenantLimiter

BODY = {"model": "mock-model", "messages": [{"role": "user", "content": "hello there"}]}


def post(c: TestClient, tenant: str):  # type: ignore[no-untyped-def]
    return c.post("/v1/chat/completions", json=BODY, headers={"X-Tenant-ID": tenant})


def client(**kw) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(token_delay=0, **kw))


def test_non_stream_response_and_metrics() -> None:
    c = client()
    r = c.post("/v1/chat/completions", json=BODY, headers={"X-Tenant-ID": "acme"})
    assert r.status_code == 200
    assert r.json()["usage"]["prompt_tokens"] == 2
    m = c.get("/metrics").text
    assert 'aidelivery_requests_total{model="mock-model",status="200",tenant="acme"} 1.0' in m
    assert "aidelivery_cost_usd_total" in m


def test_streaming_sse_ends_with_done() -> None:
    c = client()
    with c.stream(
        "POST", "/v1/chat/completions", json={**BODY, "stream": True}, headers={"X-Tenant-ID": "t"}
    ) as r:
        lines = [x for x in r.iter_lines() if x.startswith("data: ")]
    assert r.headers["content-type"].startswith("text/event-stream")
    assert lines[-1] == "data: [DONE]"
    first = json.loads(lines[0][6:])
    assert first["object"] == "chat.completion.chunk"
    assert 'tenant="t"' in c.get("/metrics").text


def test_rate_limit_returns_429() -> None:
    c = client(limiter=TenantLimiter(1, 0))
    assert (
        c.post("/v1/chat/completions", json=BODY, headers={"X-Tenant-ID": "a"}).status_code == 200
    )
    r = c.post("/v1/chat/completions", json=BODY, headers={"X-Tenant-ID": "a"})
    assert r.status_code == 429
    assert (
        c.post("/v1/chat/completions", json=BODY, headers={"X-Tenant-ID": "b"}).status_code == 200
    )


def test_budget_exhaustion_returns_429() -> None:
    c = client(budgets={"a": 0.0000001})
    assert (
        c.post("/v1/chat/completions", json=BODY, headers={"X-Tenant-ID": "a"}).status_code == 200
    )
    r = c.post("/v1/chat/completions", json=BODY, headers={"X-Tenant-ID": "a"})
    assert r.status_code == 429 and "budget" in r.json()["error"]


@pytest.mark.parametrize("path", ["/healthz"])
def test_health(path: str) -> None:
    assert client().get(path).json()["mode"] == "mock"
