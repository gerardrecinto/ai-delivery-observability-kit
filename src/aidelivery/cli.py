"""Command line entry point: `aidelivery gate` and `aidelivery license-check`."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from . import gate, licensecheck


def _read_metrics(src: str) -> str:
    if src.startswith(("http://", "https://")):
        with urllib.request.urlopen(src, timeout=10) as r:  # noqa: S310
            return str(r.read().decode())
    return Path(src).read_text()


def _cmd_gate(a: argparse.Namespace) -> int:
    try:
        samples = gate.parse_prometheus_text(_read_metrics(a.metrics))
        eval_data = json.loads(Path(a.eval).read_text())
        t = gate.Thresholds.load(a.thresholds) if a.thresholds else gate.Thresholds()
    except (OSError, ValueError) as e:
        print(f"input error: {e}", file=sys.stderr)
        return gate.INPUT_ERROR
    d = gate.evaluate(samples, eval_data, t, tenant=a.tenant)
    print(gate.format_decision(d))
    return d.exit_code


def _cmd_license(a: argparse.Namespace) -> int:
    try:
        bad = licensecheck.run(a.manifest, a.policy)
    except (OSError, ValueError) as e:
        print(f"input error: {e}", file=sys.stderr)
        return 2
    for v in bad:
        print(f"FAIL {v.name}: {v.license} ({v.reason})")
    print("license check: " + ("FAILED" if bad else "ok"))
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aidelivery")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gate", help="decide promote (exit 0) or rollback (exit 1)")
    g.add_argument("--metrics", required=True, help="Prometheus text file or http(s) URL")
    g.add_argument("--eval", required=True, help="JSON file with score and hallucination_rate")
    g.add_argument("--thresholds", help="JSON file overriding default thresholds")
    g.add_argument("--tenant", help="only consider this tenant label")
    g.set_defaults(fn=_cmd_gate)

    lc = sub.add_parser("license-check", help="check a model manifest against a license policy")
    lc.add_argument("--manifest", required=True)
    lc.add_argument("--policy", required=True)
    lc.set_defaults(fn=_cmd_license)

    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
