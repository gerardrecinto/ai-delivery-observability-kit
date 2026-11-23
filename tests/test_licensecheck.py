from pathlib import Path

from aidelivery.cli import main
from aidelivery.licensecheck import check_manifest

POLICY = {"allow": ["apache-2.0", "mit"], "deny": ["agpl-3.0"]}
FX = Path(__file__).parent / "fixtures"
CFG = Path(__file__).parent.parent / "config"


def test_allowed_passes() -> None:
    assert check_manifest([{"name": "a", "license": "Apache-2.0"}], POLICY) == []


def test_denied_and_unlisted_and_missing_fail() -> None:
    items = [
        {"name": "d", "license": "AGPL-3.0"},
        {"name": "u", "license": "proprietary"},
        {"name": "m", "license": ""},
        {"name": "n", "license": "NOASSERTION"},
    ]
    reasons = {v.name: v.reason for v in check_manifest(items, POLICY)}
    assert "deny" in reasons["d"]
    assert "allow" in reasons["u"]
    assert "missing" in reasons["m"]
    assert "missing" in reasons["n"]


def test_compound_expressions_are_conservative() -> None:
    assert check_manifest([{"name": "x", "license": "MIT OR Apache-2.0"}], POLICY) == []
    assert check_manifest([{"name": "x", "license": "MIT AND AGPL-3.0"}], POLICY)
    assert check_manifest([{"name": "x", "license": "MIT OR proprietary"}], POLICY)


def test_cli_exit_codes() -> None:
    pol = str(CFG / "license-policy.json")
    assert main(["license-check", "--manifest", str(FX / "manifest.json"), "--policy", pol]) == 1
    assert main(["license-check", "--manifest", "/nope", "--policy", pol]) == 2
