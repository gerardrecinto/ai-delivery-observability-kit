# Security Policy

This is a reference and portfolio project. It has not been run against real GPUs, real model servers, or production clusters.

## Reporting a vulnerability

Please open a private security advisory on the GitHub repository (Security tab, "Report a vulnerability"). Do not post details in a public issue. I will acknowledge within a few days.

## Scope

- The Python package in `src/aidelivery` and the mock server.
- The configuration and manifests under `otel/`, `deploy/`, and `.github/`.

The mock inference server has no authentication and trusts the `X-Tenant-ID` header. It is for local use only and must not be exposed to a network.

## Secrets

No credentials are stored in this repository. CI uses the default `GITHUB_TOKEN` with read-only permissions unless a job states otherwise.
