"""License check for model and artifact manifests against an allow/deny policy.

Manifest: JSON list of {"name": str, "license": str}. Licenses are SPDX identifiers.
Policy: {"allow": [...], "deny": [...]}. Deny wins, anything not allowed is rejected,
and a missing license is always a failure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_SPLIT = re.compile(r"\s+(?:OR|AND)\s+", re.IGNORECASE)


@dataclass(frozen=True)
class Violation:
    name: str
    license: str
    reason: str


def _ids(expr: str) -> list[str]:
    return [p.strip("() ").lower() for p in _SPLIT.split(expr) if p.strip("() ")]


def check_manifest(items: list[dict[str, str]], policy: dict[str, list[str]]) -> list[Violation]:
    allow = {x.lower() for x in policy.get("allow", [])}
    deny = {x.lower() for x in policy.get("deny", [])}
    out: list[Violation] = []
    for it in items:
        name = it.get("name", "<unnamed>")
        lic = (it.get("license") or "").strip()
        if not lic or lic.lower() in {"unknown", "none", "noassertion"}:
            out.append(Violation(name, lic or "<missing>", "license missing or unknown"))
            continue
        ids = _ids(lic)
        # "A AND B" needs every id allowed; "A OR B" only needs one. Compound is treated
        # conservatively: any denied id fails, and every id must be on the allow list.
        if any(i in deny for i in ids):
            out.append(Violation(name, lic, "license is on the deny list"))
        elif not all(i in allow for i in ids):
            out.append(Violation(name, lic, "license is not on the allow list"))
    return out


def run(manifest: str | Path, policy: str | Path) -> list[Violation]:
    items = json.loads(Path(manifest).read_text())
    pol = json.loads(Path(policy).read_text())
    return check_manifest(items, pol)
