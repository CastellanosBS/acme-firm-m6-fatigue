#!/usr/bin/env python3
"""Build the closed pre-run source manifest for IFATIGUE-INFRA6-M6.

The manifest freezes every execution-effective authored input plus every
registered generator and validator.  It intentionally excludes itself and all
reference-run descendants, build records, final manifests and distribution
artifacts.  No scenario or unit test is imported or executed by this command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


EXPECTED_PLANNED_PATHS = 159
EXPECTED_SOURCE_MEMBERS = 90
SOURCE_MANIFEST = "manifests/SOURCE_SHA256.txt"
FIXED_MEMBERS = {
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
FORBIDDEN_PREFIXES = ("results/", "traces/", "logs/", "environment/", "dist/")
FORBIDDEN_MEMBERS = {
    SOURCE_MANIFEST,
    "manifests/BUILD_RECORD.json",
    "MANIFIESTO_SHA256.txt",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(RuntimeError):
    """The source membership or a source file violates the frozen contract."""


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
        raise ManifestError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"{path.name} must contain a JSON object")
    return value


def valid_relative_path(value: object) -> str:
    if type(value) is not str or not value:
        raise ManifestError("every planned path must be a nonempty string")
    if "\x00" in value or "\n" in value or "\r" in value or "\\" in value:
        raise ManifestError(f"unsafe planned path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or ".." in path.parts:
        raise ManifestError(f"noncanonical planned path: {value!r}")
    return value


def planned_paths(provenance: Mapping[str, Any]) -> set[str]:
    paths: list[str] = []
    for entry in provenance.get("planned_tree", []):
        if not isinstance(entry, dict):
            raise ManifestError("planned_tree contains a non-object")
        paths.append(valid_relative_path(entry.get("path")))
    for file_set in provenance.get("planned_file_sets", []):
        if not isinstance(file_set, dict):
            raise ManifestError("planned_file_sets contains a non-object")
        raw_paths = file_set.get("paths")
        if not isinstance(raw_paths, list):
            raise ManifestError("a planned file set has no path array")
        paths.extend(valid_relative_path(path) for path in raw_paths)
    if len(paths) != len(set(paths)):
        raise ManifestError("PROVENANCE declares a duplicate planned path")
    if len(paths) != EXPECTED_PLANNED_PATHS:
        raise ManifestError(
            f"expected {EXPECTED_PLANNED_PATHS} planned paths, found {len(paths)}"
        )
    return set(paths)


def generator_registry(provenance: Mapping[str, Any]) -> set[str]:
    matches = [
        item
        for item in provenance.get("decisions", [])
        if isinstance(item, dict) and item.get("id") == "T03-MP-013"
    ]
    if len(matches) != 1 or not str(matches[0].get("status", "")).startswith(
        "approved"
    ):
        raise ManifestError("T03-MP-013 is missing or not approved")
    registry = (
        matches[0]
        .get("decision", {})
        .get("generator_registry", {})
        .get("required_paths")
    )
    if not isinstance(registry, list) or len(registry) != 10:
        raise ManifestError("T03-MP-013 must register exactly ten programs")
    paths = {valid_relative_path(item) for item in registry}
    if len(paths) != 10:
        raise ManifestError("the generator registry contains duplicates")
    return paths


def expected_members(root: Path) -> list[str]:
    provenance = load_json(root / "PROVENANCE.json")
    planned = planned_paths(provenance)
    generators = generator_registry(provenance)
    members = {
        path
        for path in planned
        if path in FIXED_MEMBERS or path.startswith(SOURCE_PREFIXES)
    }
    members.update(generators)
    if not members <= planned:
        raise ManifestError("source membership includes an undeclared path")
    prohibited = {
        path
        for path in members
        if path in FORBIDDEN_MEMBERS or path.startswith(FORBIDDEN_PREFIXES)
    }
    if prohibited:
        raise ManifestError(f"derived descendants entered source scope: {sorted(prohibited)}")
    if len(members) != EXPECTED_SOURCE_MEMBERS:
        raise ManifestError(
            f"expected {EXPECTED_SOURCE_MEMBERS} source members, found {len(members)}"
        )
    if "scripts/build_source_manifest.py" not in members:
        raise ManifestError("the source-manifest builder is not self-included")
    return sorted(members, key=lambda item: item.encode("utf-8"))


def controlled_physical_files(root: Path) -> set[str]:
    found: set[str] = set()
    for prefix in CONTROLLED_PREFIXES:
        directory = root / prefix.rstrip("/")
        if not directory.exists():
            continue
        for candidate in directory.rglob("*"):
            if candidate.is_symlink():
                raise ManifestError(
                    f"symbolic links are prohibited in source scope: {candidate}"
                )
            if candidate.is_file():
                relative = candidate.relative_to(root).as_posix()
                if "__pycache__" in candidate.parts or candidate.suffix == ".pyc":
                    raise ManifestError(f"bytecode/cache file in source scope: {relative}")
                found.add(relative)
    return found


def validate_member_files(root: Path, members: Sequence[str]) -> None:
    member_set = set(members)
    unexpected = controlled_physical_files(root) - member_set
    if unexpected:
        raise ManifestError(f"unexpected controlled source files: {sorted(unexpected)}")
    for relative in members:
        candidate = root / relative
        if candidate.is_symlink() or not candidate.is_file():
            raise ManifestError(f"required source member is missing or not regular: {relative}")
        try:
            candidate.resolve().relative_to(root)
        except ValueError as exc:
            raise ManifestError(f"source member escapes package root: {relative}") from exc


def manifest_bytes(root: Path, members: Sequence[str]) -> bytes:
    records: list[str] = []
    for relative in members:
        digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if SHA256_RE.fullmatch(digest) is None:
            raise ManifestError(f"invalid SHA-256 for {relative}")
        records.append(f"{digest}  {relative}\n")
    return "".join(records).encode("utf-8")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def resolve_output(root: Path, output: Path) -> Path:
    candidate = output if output.is_absolute() else root / output
    candidate = candidate.resolve()
    expected = (root / SOURCE_MANIFEST).resolve()
    if candidate != expected:
        raise ManifestError(f"output must be exactly {SOURCE_MANIFEST}")
    return candidate


def build(root: Path, output: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ManifestError(f"package root is not a directory: {root}")
    destination = resolve_output(root, output)
    members = expected_members(root)
    validate_member_files(root, members)
    payload = manifest_bytes(root, members)
    atomic_write(destination, payload)
    return {
        "algorithm": "SHA-256",
        "manifest": SOURCE_MANIFEST,
        "manifest_bytes": len(payload),
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "records": len(members),
        "source_builder_included": "scripts/build_source_manifest.py" in members,
        "status": "built_not_yet_verified",
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path, default=Path(SOURCE_MANIFEST))
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        report = build(args.root, args.output)
    except (ManifestError, OSError, ValueError) as exc:
        print(f"build_source_manifest.py: ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
