# Model and artifact governance

Status: design, with one implemented piece. The license check (`aidelivery license-check`) is real code with tests. Harbor, MLflow, the Hugging Face mirror, and signing are described as a design and are not deployed or exercised by this repo.

## Flow

```
 Hugging Face Hub (internet side)
        |
        |  1. pull by pinned revision, record sha256 of every file
        v
 Mirror / quarantine bucket
        |
        |  2. license check  (aidelivery license-check)     fail -> reject
        |  3. file scan: pickle/unsafe formats, Trivy secret scan
        |     prefer safetensors; reject pickle-based weights
        v
 MLflow Model Registry  (version, license, source revision, eval results, sha256 as tags)
        |
        |  4. eval gate: quality and hallucination scores recorded on the version
        |     (aidelivery gate reads the same numbers at canary time)
        v
 Harbor (OCI registry)
        |  5. model packaged as an OCI artifact; serving image built from a pinned base
        |  6. Trivy image scan + SBOM (CycloneDX) attached; signature with cosign
        |  7. replication to the air-gapped Harbor (pull-based, one direction)
        v
 Cluster: Argo CD syncs the Helm chart, image pulled only from the internal Harbor
```

## Decisions

- Pin everything by digest or revision. A tag such as `latest` or a branch name is not a version.
- Air-gapped operation: the cluster never talks to the public hub. `HF_HUB_OFFLINE=1` is set in the chart, and weights come from a volume populated from the internal registry.
- The registry record is the source of truth for what a model is: source revision, license, hashes, eval scores. Rollback means redeploying a previous registry version.
- Licenses are checked at ingest, not at deploy. A model with a missing or unknown license is rejected, the same as a denied one.
- Weights in pickle-based formats can run code on load. Prefer safetensors and treat anything else as an exception that needs review.

## License check (implemented)

Input is a JSON manifest of `{"name", "license"}` entries with SPDX identifiers, plus a policy with `allow` and `deny` lists (see `config/license-policy.json`).

```
aidelivery license-check --manifest tests/fixtures/manifest.json --policy config/license-policy.json
```

Rules:

- Missing, empty, `unknown`, `none`, or `NOASSERTION` fails.
- A license on the deny list fails, even if it also appears on the allow list.
- A license not on the allow list fails.
- For compound expressions (`A OR B`, `A AND B`) every identifier must be on the allow list and none on the deny list. This is stricter than SPDX semantics for `OR` on purpose.

Exit codes: 0 all clear, 1 violations, 2 bad input.

Limits: it trusts the license string in the manifest. It does not read model cards, detect custom or gated licenses with usage restrictions, or check the licenses of training data. Those need a human review step.

## Not implemented here

Harbor projects and replication rules, MLflow server and registry hooks, the HF mirror job, cosign signing, and admission-time signature verification (for example with Kyverno or a policy controller).
