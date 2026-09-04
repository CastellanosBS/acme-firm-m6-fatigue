#!/usr/bin/env python3
"""Verify the pre-run or final SHA-256 manifest without trusting its members."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


SOURCE_MANIFEST = "manifests/SOURCE_SHA256.txt"
FINAL_MANIFEST = "MANIFIESTO_SHA256.txt"
EXPECTED_PLANNED_PATHS = 159
EXPECTED_SOURCE_MEMBERS = 90
FIXED_SOURCE_MEMBERS = {
    "PROVENANCE.json",
    "config/resolved_instance.json",
    "manifests/BUILD_RECIPE.json",
    "manifests/GENERATION_TOPOLOGY.json",
    "sources/DERIVATION_LEDGER.csv",
    "sources/SOURCES.json",
}
SOURCE_PREFIXES = (
    "schemas/",
    "spec/",
    "src/",
    "scenarios/",
    "oracles/",
    "tests/",
)
CONTROLLED_PREFIXES = SOURCE_PREFIXES + ("commands/", "scripts/")
RECORD_RE = re.compile(r"^([0-9a-f]{64})  ([^\x00\r\n]+)$")


class VerificationError(RuntimeError):
    """A manifest or one of its members violates the integrity contract."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{path} must contain a JSON object")
    return value


def safe_relative_path(value: object) -> str:
    if type(value) is not str or not value:
        raise VerificationError("manifest paths must be nonempty strings")
    if value != unicodedata.normalize("NFC", value):
        raise VerificationError(f"manifest path is not NFC-normalized: {value!r}")
    if "\x00" in value or "\r" in value or "\n" in value or "\\" in value:
        raise VerificationError(f"unsafe manifest path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or ".." in path.parts:
        raise VerificationError(f"noncanonical manifest path: {value!r}")
    return value


def declared_paths(provenance: Mapping[str, Any]) -> set[str]:
    values: list[str] = []
    for item in provenance.get("planned_tree", []):
        if not isinstance(item, dict):
            raise VerificationError("planned_tree contains a non-object")
        values.append(safe_relative_path(item.get("path")))
    for file_set in provenance.get("planned_file_sets", []):
        if not isinstance(file_set, dict) or not isinstance(file_set.get("paths"), list):
            raise VerificationError("planned_file_sets contains an invalid entry")
        values.extend(safe_relative_path(item) for item in file_set["paths"])
    if len(values) != len(set(values)):
        raise VerificationError("PROVENANCE declares duplicate paths")
    if len(values) != EXPECTED_PLANNED_PATHS:
        raise VerificationError(
            f"expected {EXPECTED_PLANNED_PATHS} planned paths, found {len(values)}"
        )
    return set(values)


def required_generators(provenance: Mapping[str, Any]) -> set[str]:
    decisions = [
        item
        for item in provenance.get("decisions", [])
        if isinstance(item, dict) and item.get("id") == "T03-MP-013"
    ]
    if len(decisions) != 1 or not str(decisions[0].get("status", "")).startswith(
        "approved"
    ):
        raise VerificationError("T03-MP-013 is missing or not approved")
    values = (
        decisions[0]
        .get("decision", {})
        .get("generator_registry", {})
        .get("required_paths")
    )
    if not isinstance(values, list) or len(values) != 10:
        raise VerificationError("T03-MP-013 does not register exactly ten programs")
    result = {safe_relative_path(item) for item in values}
    if len(result) != 10:
        raise VerificationError("generator registry contains duplicate paths")
    return result


def expected_source_members(root: Path) -> set[str]:
    provenance = load_json(root / "PROVENANCE.json")
    planned = declared_paths(provenance)
    members = {
        path
        for path in planned
        if path in FIXED_SOURCE_MEMBERS or path.startswith(SOURCE_PREFIXES)
    }
    members.update(required_generators(provenance))
    if len(members) != EXPECTED_SOURCE_MEMBERS:
        raise VerificationError(
            f"expected {EXPECTED_SOURCE_MEMBERS} source members, found {len(members)}"
        )
    forbidden = {
        SOURCE_MANIFEST,
        "manifests/BUILD_RECORD.json",
        FINAL_MANIFEST,
    }
    if members & forbidden:
        raise VerificationError("a derived manifest entered pre-run source scope")
    return members


def controlled_files(root: Path) -> set[str]:
    result: set[str] = set()
    for prefix in CONTROLLED_PREFIXES:
        directory = root / prefix.rstrip("/")
        if not directory.exists():
            continue
        for candidate in directory.rglob("*"):
            if candidate.is_symlink():
                raise VerificationError(f"symbolic link in source scope: {candidate}")
            if candidate.is_file():
                relative = candidate.relative_to(root).as_posix()
                if "__pycache__" in candidate.parts or candidate.suffix == ".pyc":
                    raise VerificationError(f"bytecode/cache file in source scope: {relative}")
                result.add(relative)
    return result


def expected_final_members(root: Path) -> set[str]:
    result: set[str] = set()
    for candidate in root.rglob("*"):
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            raise VerificationError(f"symbolic links are prohibited: {relative}")
        if not candidate.is_file():
            continue
        if (
            relative == FINAL_MANIFEST
            or relative == "dist"
            or relative.startswith("dist/")
            or "__pycache__" in candidate.parts
            or candidate.suffix == ".pyc"
            or any(part.startswith(".") and part.endswith(".tmp") for part in candidate.parts)
        ):
            continue
        result.add(relative)
    return result


def parse_manifest(path: Path) -> tuple[dict[str, str], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise VerificationError(f"cannot read manifest: {exc}") from exc
    if not raw or not raw.endswith(b"\n") or b"\r" in raw:
        raise VerificationError("manifest must be nonempty, LF-only and LF-terminated")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VerificationError("manifest is not UTF-8") from exc
    records: dict[str, str] = {}
    ordered_paths: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = RECORD_RE.fullmatch(line)
        if match is None:
            raise VerificationError(f"malformed manifest record on line {number}")
        digest, raw_path = match.groups()
        relative = safe_relative_path(raw_path)
        if relative in records:
            raise VerificationError(f"duplicate manifest path: {relative}")
        records[relative] = digest
        ordered_paths.append(relative)
    expected_order = sorted(ordered_paths, key=lambda item: item.encode("utf-8"))
    if ordered_paths != expected_order:
        raise VerificationError("manifest records are not in UTF-8 byte order")
    canonical = "".join(
        f"{records[relative]}  {relative}\n" for relative in expected_order
    ).encode("utf-8")
    if raw != canonical:
        raise VerificationError("manifest bytes are not canonical")
    return records, raw


def verify(root: Path, manifest: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise VerificationError(f"package root is not a directory: {root}")
    path = manifest if manifest.is_absolute() else root / manifest
    path = path.resolve()
    try:
        relative_manifest = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise VerificationError("manifest must be inside the package root") from exc
    if relative_manifest not in {SOURCE_MANIFEST, FINAL_MANIFEST}:
        raise VerificationError(
            f"manifest must be {SOURCE_MANIFEST} or {FINAL_MANIFEST}"
        )
    records, raw = parse_manifest(path)
    if relative_manifest == SOURCE_MANIFEST:
        expected = expected_source_members(root)
        unexpected_physical = controlled_files(root) - expected
        if unexpected_physical:
            raise VerificationError(
                f"unexpected controlled source files: {sorted(unexpected_physical)}"
            )
        manifest_kind = "pre_run_source"
    else:
        expected = expected_final_members(root)
        manifest_kind = "final_package"
    actual = set(records)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise VerificationError(
            f"manifest membership mismatch; missing={missing}, unexpected={unexpected}"
        )
    mismatches: list[str] = []
    for relative in sorted(actual, key=lambda item: item.encode("utf-8")):
        candidate = root / relative
        if candidate.is_symlink() or not candidate.is_file():
            mismatches.append(f"{relative}:missing_or_nonregular")
            continue
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            mismatches.append(f"{relative}:escapes_root")
            continue
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if digest != records[relative]:
            mismatches.append(f"{relative}:hash_mismatch")
    if mismatches:
        raise VerificationError(f"manifest verification failed: {mismatches}")
    return {
        "algorithm": "SHA-256",
        "manifest": relative_manifest,
        "manifest_bytes": len(raw),
        "manifest_kind": manifest_kind,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "records": len(records),
        "status": "verified",
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--manifest", type=Path, default=Path(FINAL_MANIFEST))
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        report = verify(args.root, args.manifest)
    except (VerificationError, OSError, ValueError) as exc:
        print(f"verify_manifest.py: ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
