#!/usr/bin/env python3
"""Validate the Oculox EJBCA CA/profile plan against the PKI manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML est requis pour valider le plan EJBCA") from exc


PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_CA_PLAN = PROJECT_DIR / "dev/ejbca/profiles/ca-plan.yml"
DEFAULT_PKI_MANIFEST = PROJECT_DIR / "dev/ejbca/pki-manifest.yml"


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"Fichier absent : {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"YAML invalide : {path}")
    return data


def validate(ca_plan: dict[str, Any], pki_manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    cas = ca_plan.get("certificate_authorities")
    profiles = ca_plan.get("certificate_profiles")
    certificates = pki_manifest.get("certificates")

    if not isinstance(cas, dict):
        errors.append("certificate_authorities doit etre un dictionnaire")
        cas = {}
    if not isinstance(profiles, dict):
        errors.append("certificate_profiles doit etre un dictionnaire")
        profiles = {}
    if not isinstance(certificates, dict):
        errors.append("certificates doit etre un dictionnaire dans le manifeste PKI")
        certificates = {}

    for ca_name, ca_spec in cas.items():
        if not isinstance(ca_spec, dict):
            errors.append(f"CA {ca_name}: definition invalide")
            continue
        if ca_spec.get("type") == "intermediate":
            issuer = ca_spec.get("issuer")
            if issuer not in cas:
                errors.append(f"CA {ca_name}: issuer inconnu {issuer!r}")
        for required in ("display_name", "subject_dn", "key_algorithm", "key_size", "validity"):
            if required not in ca_spec:
                errors.append(f"CA {ca_name}: champ manquant {required}")

    for profile_name, profile_spec in profiles.items():
        if not isinstance(profile_spec, dict):
            errors.append(f"profil {profile_name}: definition invalide")
            continue
        issuer = profile_spec.get("issuer")
        if issuer not in cas:
            errors.append(f"profil {profile_name}: issuer inconnu {issuer!r}")
        for required in ("type", "key_algorithm", "key_size", "validity", "extended_key_usage"):
            if required not in profile_spec:
                errors.append(f"profil {profile_name}: champ manquant {required}")
        for target in profile_spec.get("target_manifest_entries", []):
            if target not in certificates:
                errors.append(f"profil {profile_name}: entree manifeste inconnue {target!r}")

    manifest_profiles = {
        spec.get("profile")
        for spec in certificates.values()
        if isinstance(spec, dict) and spec.get("required", True)
    }
    missing_profiles = sorted(profile for profile in manifest_profiles if profile not in profiles)
    for profile in missing_profiles:
        errors.append(f"profil obligatoire absent du plan EJBCA : {profile}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Valide le plan CA/profils EJBCA Oculox")
    parser.add_argument("--ca-plan", default=str(DEFAULT_CA_PLAN))
    parser.add_argument("--pki-manifest", default=str(DEFAULT_PKI_MANIFEST))
    args = parser.parse_args()

    ca_plan = load_yaml(Path(args.ca_plan))
    pki_manifest = load_yaml(Path(args.pki_manifest))
    errors = validate(ca_plan, pki_manifest)
    if errors:
        print("Plan EJBCA invalide :", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        "Plan EJBCA valide: "
        f"{len(ca_plan['certificate_authorities'])} CA, "
        f"{len(ca_plan['certificate_profiles'])} profils"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
