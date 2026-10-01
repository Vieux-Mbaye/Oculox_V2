#!/usr/bin/env python3
"""Install role-specific EJBCA CE profiles from reviewed XML templates."""

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
PROFILES = ROOT / "dev/ejbca/profiles"
CLI = "/opt/keyfactor/bin/ejbca.sh"
CONTAINER = "oculox-ejbca"
EKU = {"serverAuth": "1.3.6.1.5.5.7.3.1", "clientAuth": "1.3.6.1.5.5.7.3.2"}


def command(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def profile_put(root: ET.Element, key: str | int, tag: str, value: str) -> None:
    source = root.find("object")
    if source is None:
        raise ValueError("Invalid EJBCA XML template")
    for item in source.findall("void"):
        name = item.find("string") if isinstance(key, str) else item.find("int")
        if name is not None and name.text == str(key):
            for child in list(item)[1:]:
                item.remove(child)
            ET.SubElement(item, tag).text = value
            return
    item = ET.SubElement(source, "void", method="put")
    ET.SubElement(item, "string" if isinstance(key, str) else "int").text = str(key)
    ET.SubElement(item, tag).text = value


def profile_list(root: ET.Element, key: str, tag: str, values: list[str | int | bool]) -> None:
    source = root.find("object")
    if source is None:
        raise ValueError("Invalid EJBCA XML template")
    for item in source.findall("void"):
        name = item.find("string")
        if name is not None and name.text == key:
            for child in list(item)[1:]:
                item.remove(child)
            break
    else:
        item = ET.SubElement(source, "void", method="put")
        ET.SubElement(item, "string").text = key
    array = ET.SubElement(item, "object", {"class": "java.util.ArrayList"})
    for value in values:
        entry = ET.SubElement(array, "void", method="add")
        ET.SubElement(entry, tag).text = (str(value).lower() if isinstance(value, bool) else str(value))


def render_certificate(template: Path, destination: Path, ca_id: int, settings: dict) -> None:
    root = ET.parse(template).getroot()
    profile_put(root, "encodedvalidity", "string", str(settings["validity"]))
    profile_put(root, "useextendedkeyusage", "boolean", "true")
    profile_put(root, "allowextensionoverride", "boolean", "false")
    profile_put(root, "allowdnoverride", "boolean", "false")
    profile_put(root, "allowkeyusageoverride", "boolean", "false")
    profile_list(root, "availablecas", "int", [ca_id])
    profile_list(root, "availablekeyalgorithms", "string", ["RSA"])
    profile_list(root, "availablebitlengths", "int", [int(settings["key_size"])])
    profile_list(root, "extendedkeyusage", "string", [EKU[usage] for usage in settings["extended_key_usage"]])
    ku = settings["key_usage"]
    profile_list(root, "keyusage", "boolean", [value in ku for value in (
        "digitalSignature", "nonRepudiation", "keyEncipherment", "dataEncipherment",
        "keyAgreement", "keyCertSign", "cRLSign", "encipherOnly", "decipherOnly")])
    ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)


def render_entity(template: Path, destination: Path, ca_id: int, profile_id: int) -> None:
    root = ET.parse(template).getroot()
    source = root.find("object")
    assert source is not None
    number_array = next(item.find("object") for item in source.findall("void") if item.find("string") is not None and item.find("string").text == "NUMBERARRAY")
    assert number_array is not None
    fields = [item.find("int") for item in number_array.findall("void")]
    for field_id in (5, 11, 12, 16, 18, 19):
        count = 3 if field_id in (18, 19) else 1
        fields[field_id].text = str(count)
        for number in range(count):
            key = field_id + 100 * number
            profile_put(root, 10000 + key, "boolean", "true")
            profile_put(root, 20000 + key, "boolean", "false")
            profile_put(root, 30000 + key, "boolean", "true")
            profile_put(root, key, "string", "")
    for key, value in ((29, profile_id), (30, profile_id), (37, ca_id), (38, ca_id)):
        profile_put(root, key, "string", str(value))
    ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)


def xml_value(element: ET.Element):
    if element.tag in {"string", "int", "long", "float", "double", "boolean"}:
        return (element.text or "").strip()
    if element.tag == "null":
        return None
    return [xml_value(child[0]) for child in element.findall("void") if len(child)]


def profile_values(path: Path) -> dict:
    root = ET.parse(path).getroot().find("object")
    if root is None:
        raise ValueError(f"Invalid profile export: {path.name}")
    return {xml_value(item[0]): xml_value(item[1]) for item in root.findall("void")
            if item.get("method") == "put" and len(item) == 2}


def verify_profile(expected: Path, actual: Path, entity: bool) -> None:
    wanted, found = profile_values(expected), profile_values(actual)
    keys = ({"NUMBERARRAY", "29", "30", "37", "38"} |
            {str(offset + field + 100 * number) for field in (5, 11, 12, 16, 18, 19)
             for number in range(3 if field in (18, 19) else 1) for offset in (0, 10000, 20000, 30000)}) if entity else {
        "type", "encodedvalidity", "usekeyusage", "keyusage", "useextendedkeyusage", "extendedkeyusage",
        "availablecas", "availablekeyalgorithms", "availablebitlengths", "allowextensionoverride",
        "allowdnoverride", "allowkeyusageoverride", "basicconstraintscritical"}
    drift = sorted(key for key in keys if wanted.get(key) != found.get(key))
    if drift:
        raise RuntimeError(f"EJBCA profile drift: {actual.name}: {', '.join(drift)}; active profile was not changed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    plan = yaml.safe_load((PROFILES / "ca-plan.yml").read_text())
    ca_output = command("docker", "exec", CONTAINER, CLI, "ca", "listcas")
    ca_ids = dict((name, int(ident)) for name, ident in re.findall(r"CA Name: ([^\n]+).*?Id: (-?\d+)", ca_output, re.S))
    run_id = "oculox-identity-profiles"
    with tempfile.TemporaryDirectory(prefix="oculox-ejbca-profiles-") as directory:
        staging = Path(directory)
        exported = staging / "existing"
        exported.mkdir()
        remote_export = f"/tmp/{run_id}-{staging.name}"
        command("docker", "exec", CONTAINER, "mkdir", "-p", remote_export)
        try:
            command("docker", "exec", CONTAINER, CLI, "ca", "exportprofiles", "-d", remote_export)
            command("docker", "cp", f"{CONTAINER}:{remote_export}/.", str(exported))
        finally:
            command("docker", "exec", CONTAINER, "rm", "-rf", remote_export)
        existing = {}
        for path in exported.glob("*.xml"):
            prefix, ident = path.stem.rsplit("-", 1)
            existing[prefix] = (path, int(ident))
        count = 0
        for index, (name, settings) in enumerate(plan["certificate_profiles"].items(), 1):
            if settings["type"] == "ca":
                continue
            ca_name = plan["certificate_authorities"][settings["issuer"]]["display_name"]
            ca_id = ca_ids[ca_name]
            profile_id = existing.get(f"certprofile_{name}", (None, 61000 + index))[1]
            render_certificate(PROFILES / "certificate-profile-template.xml", staging / f"certprofile_{name}-{profile_id}.xml", ca_id, settings)
            render_entity(PROFILES / "entity-profile-template.xml", staging / f"entityprofile_{name}-enroll-v3-{65000 + index}.xml", ca_id, profile_id)
            count += 1
        if args.dry_run:
            print(f"Prepared {count} certificate and end entity profiles")
            return
        for path in staging.glob("*.xml"):
            prefix = path.stem.rsplit("-", 1)[0]
            if prefix in existing:
                verify_profile(path, existing[prefix][0], prefix.startswith("entityprofile_"))
                path.unlink()
        missing = list(staging.glob("*.xml"))
        if args.verify_only:
            if missing:
                raise RuntimeError("Missing EJBCA profiles: " + ", ".join(path.name for path in missing))
            print(f"Verified {count} Oculox profile pairs against EJBCA exports")
            return
        remote = f"/tmp/{run_id}-{staging.name}-new"
        command("docker", "exec", CONTAINER, "mkdir", "-p", remote)
        try:
            for path in missing:
                command("docker", "cp", str(path), f"{CONTAINER}:{remote}/{path.name}")
            if missing:
                command("docker", "exec", CONTAINER, CLI, "ca", "importprofiles", "-d", remote)
        finally:
            command("docker", "exec", CONTAINER, "rm", "-rf", remote)
    print(f"Provisioned {count} Oculox profile pairs in EJBCA")


if __name__ == "__main__":
    main()
