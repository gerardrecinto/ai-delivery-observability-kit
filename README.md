# ai-delivery-observability-kit

A reference kit for shipping and observing AI inference services: per-tenant cost attribution and quotas, a canary verification gate, a multi-tenant OpenTelemetry Collector config, and deployment manifests, all runnable on a laptop against a mock server.

The inference server in this repo is a mock. It is not vLLM or Triton and it runs no model. Nothing here has been run on a GPU or a real cluster.

## Architecture

```
  client --x-tenant-id--> Envoy (tenant required, per-tenant limits, streaming-safe timeouts)
                             |
                             v
                   inference service (vLLM in deploy/, mock server locally)
                     |  /metrics (tokens, GPU seconds, cost, latency)   |  OTLP spans
                     v                                                  v
                 Prometheus <------ prometheus exporter <---- OpenTelemetry Collector
                     |                                          |  stamps tenant.id from header
                     |                                          |  scrapes DCGM exporter (GPU)
                     |                                          +--> Tempo / Loki / Kafka (optional)
                     v
     Grafana dashboards      Alert rules      Argo Rollouts AnalysisTemplate
                                                        |
   CI: aidelivery gate (p95, errors, cost/1k tokens, eval score) --> promote | rollback
```

## Layout

| Path | What |
|------|------|
| `src/aidelivery/` | rate card, cost attribution, token-bucket quotas, gate CLI, license check, mock server |
| `otel/` | collector config plus Kafka and local overlays |
| `deploy/helm/vllm-serving/` | Helm chart for vLLM (rendered and linted only) |
| `deploy/argo/` | Rollout, AnalysisTemplate, Argo CD Application |
| `deploy/envoy/` | Envoy config with rate limits and streaming timeouts |
| `deploy/prometheus/`, `deploy/grafana/` | alert rules, scrape config, dashboard JSON |
| `deploy/opencost/`, `docs/COST_ATTRIBUTION.md` | label conventions for per-tenant cost |
| `docs/GOVERNANCE.md` | model and artifact registry flow, license check |
| `.github/workflows/` | CI and a reusable `cicdcv` workflow |

## Quick start

Everything below was run on a laptop (macOS, Docker Desktop, Python 3.14 locally, 3.12 in CI and the image).

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[server,dev]"
pytest -q
```

```
35 passed, 1 warning in 0.41s
```

Canary gate against the mock server as a stand-in canary. Exit code 0 means promote, 1 means rollback.

```
$ scripts/canary_smoke.sh 0.5      # half of requests fail
PASS request_volume: 40 (need >= 20)
PASS p95_latency_seconds: 0.095 (need <= 2)
FAIL error_rate: 0.5 (need <= 0.02)
PASS cost_per_1k_tokens_usd: 0.00333 (need <= 0.01)
PASS eval_score: 0.93 (need >= 0.85)
PASS hallucination_rate: 0.02 (need <= 0.05)
DECISION: ROLLBACK        (exit 1)
```

With `scripts/canary_smoke.sh 0` the same run ends in `DECISION: PROMOTE` (exit 0). The eval score comes from a fixture JSON file, not from a real eval run.

Local stack: mock server, collector, Prometheus, Grafana.

```
docker compose up -d --build
curl -s localhost:8000/v1/chat/completions -H 'X-Tenant-ID: acme' -H 'content-type: application/json' \
  -d '{"model":"mock-model","messages":[{"role":"user","content":"hello"}]}'
```

```
{"id":"chatcmpl-2c7a81926f9c","object":"chat.completion","model":"mock-model","choices":[{"index":0,"message":{"role":"assistant","content":"This is a mock completion from the aidelivery mock server. No model is running."},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":14,"total_tokens":15}}
```

```
$ curl -s localhost:9090/api/v1/query --data-urlencode 'query=sum by (tenant) (aidelivery_requests_total)'
{"status":"success","data":{"resultType":"vector","result":[{"metric":{"tenant":"acme"},"value":[1795406619.951,"1"]}]}}
```

Tenant stamping at the collector. An OTLP metric sent with an `x-tenant-id` header gets a `tenant_id` label; one without gets `unknown`:

```
demo_gauge{job="demo",service_name="demo",tenant_id="header-tenant"} 1
demo_gauge{job="demo-nohdr",service_name="demo-nohdr",tenant_id="unknown"} 1
```

Grafana is at http://localhost:3000 (anonymous viewer) with the dashboard provisioned. Panels that use DCGM metric names stay empty locally because there is no GPU exporter.

Config validation commands (all run, all passed):

```
docker run --rm -v $PWD/otel:/c:ro otel/opentelemetry-collector-contrib:0.116.1 validate --config=/c/collector.yaml
docker run --rm --entrypoint promtool -v $PWD/deploy/prometheus:/p:ro prom/prometheus:v2.55.1 check rules /p/alerts.yaml
docker run --rm -v $PWD/deploy/envoy:/e:ro envoyproxy/envoy:v1.32.3 --mode validate -c /e/envoy.yaml
helm lint deploy/helm/vllm-serving
```

```
(otelcol validate prints nothing and exits 0 on success)
SUCCESS: 8 rules found
configuration '/e/envoy.yaml' OK
1 chart(s) linted, 0 chart(s) failed
```

## Validated

| Item | Status |
|------|--------|
| Cost attribution, rate card, budgets, token bucket (including 200-thread contention) | Unit tested, passing |
| Gate CLI thresholds, exit codes, missing-data handling, fixtures | Unit tested, passing |
| License check | Unit tested, passing |
| Mock server SSE streaming, 429s, metrics | Tested with FastAPI test client and with curl against compose |
| Collector config (base, Kafka overlay, local overlay) | `otelcol validate` passed; local overlay run in compose, tenant header stamping observed |
| Prometheus scraping the mock server and collector, query returns data | Run locally |
| Grafana dashboard loads via provisioning | Run locally, dashboard found through the API |
| Alert rules | `promtool check rules` passed |
| Envoy config | `envoy --mode validate` passed |
| Helm chart | `helm lint`, `helm template`, `kubeconform` passed |
| Argo Rollout, AnalysisTemplate, Application | `kubeconform` against the public CRD schema catalog passed |
| Trivy fs and config scans, CycloneDX SBOM | Run locally with no HIGH or CRITICAL findings |
| CI workflows | See the Actions tab for current status |

Rate card prices are placeholders.

## Notes

- The mock server trusts `X-Tenant-ID` and has no auth. Do not expose it.
- Partial streams are billed for the tokens already sent when the client disconnects.
- `requirements.txt` is a pinned snapshot of the server dependencies, used for vulnerability scanning and the SBOM.

## License

MIT. See `LICENSE` and `SECURITY.md`.
