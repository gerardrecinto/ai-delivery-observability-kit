"""MOCK OpenAI-compatible inference server. It is NOT vLLM and runs no model.

It returns canned text, streams it as SSE, emits OpenTelemetry spans, and records the same
metrics the real stack would, so the pipeline can be exercised on a laptop without a GPU.
GPU seconds here are simulated as wall time spent generating.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .cost import CostAttributor, Metrics, Usage
from .quota import TenantLimiter
from .ratecard import ModelRate, RateCard

CANNED = "This is a mock completion from the aidelivery mock server. No model is running."
DEFAULT_CARD = RateCard(default=ModelRate(0.0005, 0.0015, 0.0004))


def _setup_tracing() -> trace.Tracer:
    provider = TracerProvider(resource=Resource.create({"service.name": "aidelivery-mock"}))
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    return provider.get_tracer("aidelivery.mock")


def create_app(
    rate_card: RateCard | None = None,
    limiter: TenantLimiter | None = None,
    budgets: dict[str, float] | None = None,
    token_delay: float | None = None,
) -> FastAPI:
    app = FastAPI(title="aidelivery mock inference server (not vLLM)")
    metrics = Metrics()
    card = rate_card
    if card is None and os.getenv("RATE_CARD"):
        card = RateCard.load(os.environ["RATE_CARD"])
    cost = CostAttributor(card or DEFAULT_CARD, metrics, budgets)
    lim = limiter or TenantLimiter(
        float(os.getenv("RATE_CAPACITY", "20")), float(os.getenv("RATE_REFILL", "10"))
    )
    delay = token_delay if token_delay is not None else float(os.getenv("TOKEN_DELAY", "0.02"))
    tracer = _setup_tracing()
    force_error = float(os.getenv("ERROR_RATE", "0"))
    counter = {"n": 0}

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "mode": "mock"}

    @app.get("/metrics")
    def metrics_endpoint() -> Response:
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/chat/completions", response_model=None)
    async def chat(request: Request) -> Any:
        tenant = request.headers.get("x-tenant-id", "anonymous")
        body = await request.json()
        model = str(body.get("model", "mock-model"))
        stream = bool(body.get("stream", False))
        prompt = " ".join(str(m.get("content", "")) for m in body.get("messages", []))
        prompt_tokens = max(1, len(prompt.split()))
        start = time.perf_counter()

        if cost.budget_exhausted(tenant):
            metrics.rate_limited.labels(tenant, "budget").inc()
            metrics.requests.labels(tenant, model, "429").inc()
            return JSONResponse({"error": "budget exhausted"}, status_code=429)
        if not lim.allow(tenant):
            metrics.rate_limited.labels(tenant, "rate").inc()
            metrics.requests.labels(tenant, model, "429").inc()
            return JSONResponse(
                {"error": "rate limited"}, status_code=429, headers={"Retry-After": "1"}
            )

        counter["n"] += 1
        if force_error and counter["n"] % max(1, round(1 / force_error)) == 0:
            metrics.requests.labels(tenant, model, "500").inc()
            metrics.duration.labels(tenant, model).observe(time.perf_counter() - start)
            return JSONResponse({"error": "injected failure"}, status_code=500)

        words = CANNED.split()
        cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"

        def finish(first_token_at: float | None) -> None:
            elapsed = time.perf_counter() - start
            cost.record(Usage(tenant, model, prompt_tokens, len(words), elapsed))
            metrics.requests.labels(tenant, model, "200").inc()
            metrics.duration.labels(tenant, model).observe(elapsed)
            if first_token_at is not None:
                metrics.ttft.labels(tenant, model).observe(first_token_at - start)

        if not stream:
            with tracer.start_as_current_span("mock.generate") as span:
                span.set_attribute("tenant.id", tenant)
                span.set_attribute("gen_ai.request.model", model)
                await asyncio.sleep(delay * len(words))
            finish(None)
            return {
                "id": cid,
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": CANNED},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": len(words),
                    "total_tokens": prompt_tokens + len(words),
                },
            }

        async def sse() -> AsyncIterator[str]:
            first: float | None = None
            with tracer.start_as_current_span("mock.generate_stream") as span:
                span.set_attribute("tenant.id", tenant)
                span.set_attribute("gen_ai.request.model", model)
                for i, w in enumerate(words):
                    await asyncio.sleep(delay)
                    if first is None:
                        first = time.perf_counter()
                    chunk = {
                        "id": cid,
                        "object": "chat.completion.chunk",
                        "model": model,
                        "choices": [
                            {"index": 0, "delta": {"content": w + " "}, "finish_reason": None}
                        ],
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
                    if i == len(words) - 1:
                        done = {
                            "id": cid,
                            "object": "chat.completion.chunk",
                            "model": model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                        }
                        yield f"data: {json.dumps(done)}\n\n"
            finish(first)
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            sse(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    return app


def main() -> None:
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(create_app(), host=os.getenv("HOST", "127.0.0.1"), port=port)


if __name__ == "__main__":
    main()
