# Per-tenant cost attribution

Two views of cost are used and they answer different questions.

1. Request-level, from this repo: `aidelivery_cost_usd_total{tenant,model}` is computed from tokens and GPU seconds with a rate card (`config/ratecard.json`). It is what the canary gate and the budgets use. The rates in the sample card are illustrative placeholders, not real prices.
2. Infrastructure-level, from OpenCost: allocates node, GPU, storage, and network cost to Kubernetes objects. This is the number finance reconciles against the cloud bill.

The request-level number can be reconciled against the infrastructure-level one: set the rate card's `gpu_second` from the real hourly GPU cost divided by 3600 and the totals should track each other, with idle GPU time showing up as the gap.

## Label conventions

Tenant identity is the same string everywhere.

| Where | Key | Example |
|-------|-----|---------|
| Namespace label | `tenant` | `acme` |
| Pod label | `tenant` | `acme` |
| Pod label | `team`, `cost-center` | `search`, `cc-1234` |
| Namespace label | `workload-class` | `inference` |
| HTTP request header | `x-tenant-id` | `acme` |
| OTel resource attribute | `tenant.id` | `acme` |
| Prometheus label | `tenant` (app metrics), `tenant_id` (collector output) | `acme` |

`deploy/opencost/tenant-namespace.yaml` shows the namespace labels. The Helm chart stamps the pod labels from `tenant`, `team`, and `costCenter` values.

Example OpenCost allocation query (not run here):

```
GET /allocation/compute?window=7d&aggregate=label:tenant&includeIdle=true&shareIdle=false
```

GPU cost needs the NVIDIA device plugin and node pricing configured in OpenCost. Shared inference pools that serve many tenants from one pod cannot be split by labels, so for those the request-level metric is the only per-tenant signal.

## Budgets and limits

- Token bucket per tenant (`aidelivery.quota`): burst size and refill rate, thread-safe, tested with 200 concurrent callers.
- Budget per tenant (`aidelivery.cost`): once spend reaches the budget the mock server answers 429. `aidelivery_budget_remaining_usd` is exported for alerting.
- Envoy applies a coarse per-tenant local rate limit in front (`deploy/envoy/envoy.yaml`). Local limits are per Envoy instance, not global.
