#!/usr/bin/env python3
"""Build the deterministic release only after every internal gate has passed.

The default mode materializes the two final internal nodes, verifies them, and
only then writes the external ZIP and sidecars. ``--preflight`` executes the
same gates and computes all bytes in memory without creating any final node.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


SOURCE_MANIFEST = "manifests/SOURCE_SHA256.txt"
BUILD_RECORD = "manifests/BUILD_RECORD.json"
FINAL_MANIFEST = "MANIFIESTO_SHA256.txt"
BUILD_RECIPE = "manifests/BUILD_RECIPE.json"
BUILD_RECORD_SCHEMA = "schemas/build_record.schema.json"
ARCHIVE_NAME = "ACME_FIRM_M6_FATIGA_v1.1.0-candidate.zip"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
EXPECTED_INTERNAL_PATHS = 159
EXPECTED_SOURCE_MEMBERS = 90
EXPECTED_GENERATORS = 10
EXPECTED_SCHEMAS = 17
REGULAR_FILE_MODE = 0o100644
PATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
MANIFEST_RECORD_RE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9._/-]+)$")
SCHEMA_VERSION_RE = re.compile(r":([0-9]+\.[0-9]+\.[0-9]+)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FINAL_INTERNAL_NODES = frozenset({BUILD_RECORD, FINAL_MANIFEST})
REQUIRED_FIELDS = [
    "recipe_id and BUILD_RECIPE.json hash",
    "SOURCE_SHA256.txt hash",
    "generator paths and hashes",
    "schema identifiers and versions",
    "declared input and output paths",
    "process exit code without nondeterministic timing data",
]
PROHIBITED_BUILD_RECORD_CONTENT = [
    "final manifest hash",
    "ZIP hash",
    "wall-clock timestamp",
    "duration",
]


class ReleaseError(RuntimeError):
    """The final package tree cannot be released reproducibly."""


def ascii_order(values: Iterable[str]) -> list[str]:
    return sorted(values, key=lambda value: value.encode("ascii"))


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_json_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _reject_float(value: str) -> None:
    raise ReleaseError(f"JSON floating-point numbers are prohibited: {value}")


def _reject_constant(value: str) -> None:
    raise ReleaseError(f"non-finite JSON value is prohibited: {value}")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    normalized: set[str] = set()
    for key, value in pairs:
        if key in result:
            raise ReleaseError(f"duplicate JSON member: {key!r}")
        normalized_key = unicodedata.normalize("NFC", key)
        if normalized_key in normalized:
            raise ReleaseError(f"NFC-colliding JSON member: {key!r}")
        result[key] = value
        normalized.add(normalized_key)
    return result


def validate_json_strings(value: Any, location: str = "$") -> None:
    if isinstance(value, str):
        if value != unicodedata.normalize("NFC", value):
            raise ReleaseError(f"non-NFC JSON string at {location}")
        if "\x00" in value or "\r" in value:
            raise ReleaseError(f"prohibited character in JSON string at {location}")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ReleaseError(f"surrogate code point in JSON string at {location}")
    elif isinstance(value, dict):
        for key, item in value.items():
            validate_json_strings(key, f"{location}.<key>")
            validate_json_strings(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_json_strings(item, f"{location}[{index}]")


def load_canonical_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ReleaseError(f"UTF-8 BOM is prohibited: {path}")
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_without_duplicates,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except ReleaseError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"cannot read canonical JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseError(f"{path} must contain one JSON object")
    validate_json_strings(value)
    if raw != canonical_json_bytes(value):
        raise ReleaseError(f"JSON bytes are not canonical IFM6-JSON-v1: {path}")
    return value


def safe_relative_path(value: object, *, label: str = "path") -> str:
    if type(value) is not str or not value:
        raise ReleaseError(f"{label} must be a nonempty string")
    if not value.isascii() or PATH_RE.fullmatch(value) is None:
        raise ReleaseError(f"{label} is not an ASCII package path: {value!r}")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
    ):
        raise ReleaseError(f"{label} is not canonical POSIX-relative: {value!r}")
    return value


def assert_unique_paths(values: Sequence[str], *, label: str) -> None:
    if len(values) != len(set(values)):
        raise ReleaseError(f"{label} contains duplicate paths")
    folded: dict[str, str] = {}
    for value in values:
        key = value.casefold()
        if key in folded and folded[key] != value:
            raise ReleaseError(
                f"{label} contains a Unicode-casefold collision: "
                f"{folded[key]!r} versus {value!r}"
            )
        folded[key] = value


def approved_decision(provenance: Mapping[str, Any], decision_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in provenance.get("decisions", [])
        if isinstance(item, dict) and item.get("id") == decision_id
    ]
    if len(matches) != 1 or not str(matches[0].get("status", "")).startswith("approved"):
        raise ReleaseError(f"{decision_id} is missing, duplicated or not approved")
    decision = matches[0].get("decision")
    if not isinstance(decision, dict):
        raise ReleaseError(f"{decision_id} has no decision object")
    return decision


def validate_runtime_profile(rp: Mapping[str, Any]) -> None:
    profile = rp.get("runtime_profile")
    if not isinstance(profile, dict):
        raise ReleaseError("T03-RP-012 runtime profile is absent")
    expected = {
        "dependencies": "Python standard library only",
        "network": "prohibited",
        "python_flags": ["-I", "-B", "-X", "utf8"],
        "randomness": "none",
        "runtime": "CPython 3.12.13",
        "system_clock_in_deterministic_logic": "prohibited",
        "unicode_database": "15.0.0",
    }
    if any(profile.get(key) != value for key, value in expected.items()):
        raise ReleaseError("T03-RP-012 runtime profile is incomplete or divergent")
    if sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 12, 13):
        raise ReleaseError(
            "release requires the exact runtime CPython 3.12.13; "
            f"found {sys.implementation.name} {sys.version_info.major}."
            f"{sys.version_info.minor}.{sys.version_info.micro}"
        )
    if unicodedata.unidata_version != "15.0.0":
        raise ReleaseError(
            "release requires Unicode database 15.0.0; "
            f"found {unicodedata.unidata_version}"
        )
    if not (
        sys.flags.isolated == 1
        and sys.flags.dont_write_bytecode == 1
        and sys.flags.utf8_mode == 1
    ):
        raise ReleaseError("release must run under python3 -I -B -X utf8")


def declared_paths(provenance: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    tree = provenance.get("planned_tree")
    file_sets = provenance.get("planned_file_sets")
    if not isinstance(tree, list) or not isinstance(file_sets, list):
        raise ReleaseError("PROVENANCE lacks planned_tree or planned_file_sets")
    for item in tree:
        if not isinstance(item, dict):
            raise ReleaseError("planned_tree contains a non-object")
        values.append(safe_relative_path(item.get("path"), label="declared path"))
    for file_set in file_sets:
        if not isinstance(file_set, dict) or not isinstance(file_set.get("paths"), list):
            raise ReleaseError("planned_file_sets contains an invalid entry")
        paths = [safe_relative_path(item, label="declared path") for item in file_set["paths"]]
        if file_set.get("expected_count") != len(paths):
            raise ReleaseError(f"file-set count mismatch: {file_set.get('set_id')!r}")
        values.extend(paths)
    assert_unique_paths(values, label="PROVENANCE")
    if len(values) != EXPECTED_INTERNAL_PATHS:
        raise ReleaseError(
            f"PROVENANCE must declare exactly {EXPECTED_INTERNAL_PATHS} internal paths; "
            f"found {len(values)}"
        )
    if not FINAL_INTERNAL_NODES.issubset(values):
        raise ReleaseError("PROVENANCE omits a final internal node")
    return ascii_order(values)


def validate_contracts(
    root: Path, provenance: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], list[str], list[str]]:
    declared = declared_paths(provenance)
    package_identity = provenance.get("package_identity")
    if not isinstance(package_identity, dict):
        raise ReleaseError("PROVENANCE package_identity is absent")
    expected_root = safe_relative_path(
        str(package_identity.get("root_directory", "")).removesuffix("/"),
        label="package root directory",
    )
    if "/" in expected_root or root.name != expected_root:
        raise ReleaseError(
            f"package root must be named {expected_root!r}; found {root.name!r}"
        )
    if package_identity.get("planned_archive") != ARCHIVE_NAME:
        raise ReleaseError("planned archive name diverges from build_release.py")

    rp = approved_decision(provenance, "T03-RP-012")
    mp = approved_decision(provenance, "T03-MP-013")
    validate_runtime_profile(rp)
    zip_profile = rp.get("zip_profile")
    expected_zip_atoms = {
        "allowZip64": False,
        "archive_comment": "empty",
        "compression": "ZIP_STORED",
        "compression_level": None,
        "create_system": 3,
        "directory_entries": False,
        "duplicate_and_casefold_collision_policy": "reject",
        "encryption": False,
        "external_attributes": "regular file mode 0100644 encoded as 0o100644 << 16",
        "extra_fields": "empty",
        "implementation": "Python standard-library zipfile",
        "member_names": "ASCII POSIX paths under exactly one top-level root directory",
        "member_order": "ascending ASCII relative path",
        "member_timestamp": "1980-01-01T00:00:00",
        "symbolic_links": False,
    }
    if not isinstance(zip_profile, dict) or any(
        zip_profile.get(key) != value for key, value in expected_zip_atoms.items()
    ):
        raise ReleaseError("T03-RP-012 ZIP profile is incomplete or divergent")

    recipe_path = safe_relative_path(mp.get("recipe_path"), label="recipe path")
    if recipe_path != BUILD_RECIPE:
        raise ReleaseError("T03-MP-013 recipe path is not canonical")
    recipe = load_canonical_json(root / recipe_path)
    equality_keys = (
        "recipe_id",
        "recipe_path",
        "source_manifest_path",
        "build_record_path",
        "topology_path",
        "build_order",
        "failure_policy",
        "generator_registry",
        "validator_registry",
        "manual_editing_of_derived_nodes",
    )
    for key in equality_keys:
        if recipe.get(key) != mp.get(key):
            raise ReleaseError(f"BUILD_RECIPE diverges from T03-MP-013 at {key}")
    if recipe.get("source_manifest_path") != SOURCE_MANIFEST:
        raise ReleaseError("BUILD_RECIPE source-manifest path is not canonical")
    if recipe.get("build_record_path") != BUILD_RECORD:
        raise ReleaseError("BUILD_RECIPE build-record path is not canonical")

    generators = recipe.get("generator_registry", {}).get("required_paths")
    if not isinstance(generators, list) or len(generators) != EXPECTED_GENERATORS:
        raise ReleaseError("BUILD_RECIPE must register exactly ten programs")
    generator_paths = [safe_relative_path(item, label="generator path") for item in generators]
    assert_unique_paths(generator_paths, label="generator registry")
    if "scripts/build_release.py" not in generator_paths:
        raise ReleaseError("build_release.py is absent from the frozen generator registry")

    external = provenance.get("external_distribution_tree")
    if not isinstance(external, list):
        raise ReleaseError("PROVENANCE external_distribution_tree is absent")
    if not all(isinstance(item, dict) for item in external):
        raise ReleaseError("external distribution tree contains a non-object")
    external_paths = [
        safe_relative_path(item.get("path"), label="external output path")
        for item in external
    ]
    expected_external = {
        f"dist/{ARCHIVE_NAME}",
        f"dist/{ARCHIVE_NAME}.sha256",
        f"dist/{FINAL_MANIFEST}",
    }
    if set(external_paths) != expected_external or len(external_paths) != 3:
        raise ReleaseError("external distribution tree is not the approved three-file set")
    assert_unique_paths(external_paths, label="external distribution tree")
    outputs = ascii_order([*FINAL_INTERNAL_NODES, *external_paths])
    return recipe, mp, declared, outputs


def scan_regular_files(root: Path) -> set[str]:
    result: set[str] = set()

    def visit(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.encode("utf-8"))
        except OSError as exc:
            raise ReleaseError(f"cannot scan package tree {directory}: {exc}") from exc
        for entry in entries:
            candidate = Path(entry.path)
            relative = candidate.relative_to(root).as_posix()
            safe_relative_path(relative, label="physical package path")
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise ReleaseError(f"cannot stat package path {relative}: {exc}") from exc
            if stat.S_ISLNK(mode):
                raise ReleaseError(f"symbolic links are prohibited: {relative}")
            if stat.S_ISDIR(mode):
                visit(candidate)
            elif stat.S_ISREG(mode):
                result.add(relative)
            else:
                raise ReleaseError(f"non-regular package object is prohibited: {relative}")

    visit(root)
    assert_unique_paths(ascii_order(result), label="physical package tree")
    return result


def validate_prebuild_membership(root: Path, declared: Sequence[str]) -> set[str]:
    physical = scan_regular_files(root)
    declared_set = set(declared)
    unexpected = ascii_order(physical - declared_set)
    missing_inputs = ascii_order((declared_set - FINAL_INTERNAL_NODES) - physical)
    present_final = physical & FINAL_INTERNAL_NODES
    if unexpected or missing_inputs:
        raise ReleaseError(
            f"prebuild membership mismatch; missing={missing_inputs}, unexpected={unexpected}"
        )
    if present_final not in (set(), set(FINAL_INTERNAL_NODES)):
        raise ReleaseError(
            f"partial final-node state is prohibited: {ascii_order(present_final)}"
        )
    return physical


def manifest_bytes_from_hashes(records: Mapping[str, str]) -> bytes:
    lines: list[str] = []
    for relative in ascii_order(records):
        safe_relative_path(relative, label="manifest path")
        digest = records[relative]
        if type(digest) is not str or SHA256_RE.fullmatch(digest) is None:
            raise ReleaseError(f"invalid SHA-256 for manifest member {relative}")
        lines.append(f"{digest}  {relative}\n")
    return "".join(lines).encode("ascii")


def parse_manifest_bytes(raw: bytes, *, label: str) -> dict[str, str]:
    if not raw or not raw.endswith(b"\n") or b"\r" in raw or b"\x00" in raw:
        raise ReleaseError(f"{label} must be nonempty, LF-only and LF-terminated")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ReleaseError(f"{label} must contain ASCII records") from exc
    records: dict[str, str] = {}
    order: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = MANIFEST_RECORD_RE.fullmatch(line)
        if match is None:
            raise ReleaseError(f"malformed {label} record on line {number}")
        digest, relative = match.groups()
        safe_relative_path(relative, label=f"{label} path")
        if relative in records:
            raise ReleaseError(f"duplicate {label} path: {relative}")
        records[relative] = digest
        order.append(relative)
    assert_unique_paths(order, label=label)
    if order != ascii_order(order):
        raise ReleaseError(f"{label} records are not in ASCII path order")
    if raw != manifest_bytes_from_hashes(records):
        raise ReleaseError(f"{label} bytes are not canonical")
    return records


def manifest_bytes(payloads: Mapping[str, bytes]) -> bytes:
    return manifest_bytes_from_hashes(
        {relative: sha256_bytes(payload) for relative, payload in payloads.items()}
    )


def run_python_json(root: Path, arguments: Sequence[str], *, gate: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic"
        raise ReleaseError(f"{gate} failed with exit {completed.returncode}: {detail}")
    try:
        report = json.loads(completed.stdout, object_pairs_hook=_object_without_duplicates)
    except (json.JSONDecodeError, ReleaseError) as exc:
        raise ReleaseError(f"{gate} emitted invalid JSON") from exc
    if not isinstance(report, dict):
        raise ReleaseError(f"{gate} did not emit a JSON object")
    return report


def verify_source_manifest(root: Path) -> tuple[dict[str, Any], dict[str, str], bytes]:
    report = run_python_json(
        root,
        ["scripts/verify_manifest.py", "--root", ".", "--manifest", SOURCE_MANIFEST],
        gate="source-manifest gate",
    )
    if (
        report.get("status") != "verified"
        or report.get("manifest_kind") != "pre_run_source"
        or report.get("records") != EXPECTED_SOURCE_MEMBERS
    ):
        raise ReleaseError("source manifest was not attested as the exact pre-run set")
    raw = (root / SOURCE_MANIFEST).read_bytes()
    records = parse_manifest_bytes(raw, label="source manifest")
    if len(records) != EXPECTED_SOURCE_MEMBERS:
        raise ReleaseError(
            f"source manifest must contain {EXPECTED_SOURCE_MEMBERS} records"
        )
    if report.get("manifest_sha256") != sha256_bytes(raw):
        raise ReleaseError("source-manifest report hash mismatch")
    return report, records, raw


def validator_arguments(entry: Mapping[str, Any]) -> list[str]:
    command = entry.get("validator_command")
    path = safe_relative_path(entry.get("path"), label="validator path")
    if type(command) is not str:
        raise ReleaseError(f"validator command is absent for {path}")
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ReleaseError(f"invalid validator command for {path}: {exc}") from exc
    prefix = ["python3", "-I", "-B", "-X", "utf8", path]
    if tokens[: len(prefix)] != prefix:
        raise ReleaseError(f"validator command is not the approved isolated form: {path}")
    for token in tokens[len(prefix) :]:
        if "\x00" in token or "\r" in token or "\n" in token:
            raise ReleaseError(f"unsafe validator argument for {path}")
        if token.startswith("/") or token == ".." or token.startswith("../"):
            raise ReleaseError(f"validator argument escapes package root: {token!r}")
    return tokens[5:]


def run_registered_validators(
    root: Path,
    recipe: Mapping[str, Any],
    source_records: Mapping[str, str],
) -> list[dict[str, Any]]:
    registry = recipe.get("validator_registry")
    if not isinstance(registry, dict) or not isinstance(registry.get("validators"), list):
        raise ReleaseError("BUILD_RECIPE validator registry is absent")
    entries = registry["validators"]
    if len(entries) != 2:
        raise ReleaseError("BUILD_RECIPE must register exactly two release gates")
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReleaseError("validator registry contains a non-object")
        validator_id = entry.get("validator_id")
        if type(validator_id) is not str or not validator_id:
            raise ReleaseError("validator registry contains an invalid identifier")
        path = safe_relative_path(entry.get("path"), label="validator path")
        if validator_id in seen_ids or path in seen_paths:
            raise ReleaseError("validator registry contains duplicate identifiers or paths")
        seen_ids.add(validator_id)
        seen_paths.add(path)
        if path not in source_records:
            raise ReleaseError(f"validator is absent from SOURCE_SHA256.txt: {path}")
        report = run_python_json(root, validator_arguments(entry), gate=validator_id)
        if path == "scripts/validate_derivation_ledger.py":
            if report.get("outcome") != "pass" or report.get("exit_code") != 0:
                raise ReleaseError("derivation-ledger validator did not return a passing verdict")
        elif path == "commands/validate_qa_verdict.py":
            if report.get("status") != "pass" or report.get("verdict") != "pass":
                raise ReleaseError("internal QA gate must have the exact verdict 'pass'")
        else:
            raise ReleaseError(f"unrecognized mandatory validator: {path}")
        result.append(
            {
                "execution_status": "pass",
                "exit_code": 0,
                "path": path,
                "validator_command": entry["validator_command"],
                "validator_id": validator_id,
            }
        )
    return result


def snapshot_inputs(root: Path, declared: Sequence[str]) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for relative in declared:
        if relative in FINAL_INTERNAL_NODES:
            continue
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ReleaseError(f"declared input is missing or non-regular: {relative}")
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ReleaseError(f"declared input escapes package root: {relative}") from exc
        payloads[relative] = path.read_bytes()
    if len(payloads) != EXPECTED_INTERNAL_PATHS - len(FINAL_INTERNAL_NODES):
        raise ReleaseError("prebuild snapshot does not contain exactly 157 inputs")
    return payloads


def validate_source_snapshot(
    payloads: Mapping[str, bytes], source_records: Mapping[str, str]
) -> None:
    missing = ascii_order(set(source_records) - set(payloads))
    mismatches = ascii_order(
        relative
        for relative, digest in source_records.items()
        if relative in payloads and sha256_bytes(payloads[relative]) != digest
    )
    if missing or mismatches:
        raise ReleaseError(
            f"source tree changed after manifest gate; missing={missing}, mismatches={mismatches}"
        )


def schema_version(document: Mapping[str, Any], path: str) -> str:
    schema_id = document.get("$id")
    if type(schema_id) is not str or not schema_id:
        raise ReleaseError(f"schema has no $id: {path}")
    match = SCHEMA_VERSION_RE.search(schema_id)
    if match is None:
        raise ReleaseError(f"schema $id has no semantic-version suffix: {path}")
    version = match.group(1)
    declared = document.get("schema_version")
    if declared is not None and declared != version:
        raise ReleaseError(f"schema version and $id diverge: {path}")
    return version


def build_record_document(
    root: Path,
    recipe: Mapping[str, Any],
    mp: Mapping[str, Any],
    declared: Sequence[str],
    declared_outputs: Sequence[str],
    payloads: Mapping[str, bytes],
    source_records: Mapping[str, str],
    source_manifest_raw: bytes,
    validator_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    generator_paths = recipe["generator_registry"]["required_paths"]
    generators = [
        {"path": path, "sha256": source_records[path]}
        for path in ascii_order(generator_paths)
    ]
    if len(generators) != EXPECTED_GENERATORS:
        raise ReleaseError("build record generator set is not exact")

    schema_paths = ascii_order(
        path for path in declared if path.startswith("schemas/") and path.endswith(".json")
    )
    if len(schema_paths) != EXPECTED_SCHEMAS:
        raise ReleaseError(
            f"build record requires exactly {EXPECTED_SCHEMAS} schemas; "
            f"found {len(schema_paths)}"
        )
    schemas: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for path in schema_paths:
        if path not in source_records or path not in payloads:
            raise ReleaseError(f"schema is absent from frozen source scope: {path}")
        document = load_canonical_json(root / path)
        schema_id = document.get("$id")
        if schema_id in seen_ids:
            raise ReleaseError(f"duplicate schema $id: {schema_id}")
        seen_ids.add(schema_id)
        schemas.append(
            {
                "path": path,
                "schema_id": schema_id,
                "schema_version": schema_version(document, path),
                "sha256": source_records[path],
            }
        )

    if mp.get("derived_record_requirements") != REQUIRED_FIELDS:
        raise ReleaseError("T03-MP-013 derived-record requirements have diverged")
    base_registry = recipe["validator_registry"]
    validator_registry = {
        "acceptance_rule": base_registry["acceptance_rule"],
        "execution_status": "pass",
        "source_manifest_membership": base_registry["source_manifest_membership"],
        "stage": base_registry["stage"],
        "validators": list(validator_records),
    }
    return {
        "$schema": "../schemas/build_record.schema.json",
        "declared_inputs": ascii_order(set(declared) - FINAL_INTERNAL_NODES),
        "declared_outputs": ascii_order(declared_outputs),
        "generators": generators,
        "manual_editing_of_derived_nodes": "prohibited",
        "process_exit_code": 0,
        "prohibited_content": PROHIBITED_BUILD_RECORD_CONTENT,
        "recipe_id": recipe["recipe_id"],
        "recipe_path": BUILD_RECIPE,
        "recipe_sha256": sha256_bytes(payloads[BUILD_RECIPE]),
        "record_id": "BUILD-RECORD-IFM6-1.1.0-CANDIDATE-001",
        "required_fields": REQUIRED_FIELDS,
        "schema_version": "1.0.0",
        "schemas": schemas,
        "source_manifest_sha256": sha256_bytes(source_manifest_raw),
        "status": "completed",
        "validator_registry": validator_registry,
    }


def json_equal(left: Any, right: Any) -> bool:
    return canonical_json(left) == canonical_json(right)


def type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "null": value is None,
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
    }.get(expected, False)


def validate_schema_instance(
    value: Any,
    schema: Any,
    *,
    location: str = "$",
    depth: int = 0,
) -> list[str]:
    if depth > 100:
        return [f"{location}: schema recursion limit exceeded"]
    if schema is True:
        return []
    if schema is False or not isinstance(schema, dict):
        return [f"{location}: invalid or false schema node"]
    errors: list[str] = []
    for keyword in ("allOf",):
        branches = schema.get(keyword)
        if isinstance(branches, list):
            for branch in branches:
                errors.extend(
                    validate_schema_instance(value, branch, location=location, depth=depth + 1)
                )
    for keyword in ("anyOf", "oneOf"):
        branches = schema.get(keyword)
        if isinstance(branches, list):
            matches = sum(
                not validate_schema_instance(
                    value, branch, location=location, depth=depth + 1
                )
                for branch in branches
            )
            if (keyword == "anyOf" and matches == 0) or (
                keyword == "oneOf" and matches != 1
            ):
                errors.append(f"{location}: {keyword} matched {matches} branches")
    if "const" in schema and not json_equal(value, schema["const"]):
        errors.append(f"{location}: differs from const")
    if "enum" in schema and not any(json_equal(value, item) for item in schema["enum"]):
        errors.append(f"{location}: outside enum")
    expected_type = schema.get("type")
    if expected_type is not None:
        expected = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(type_matches(value, item) for item in expected):
            errors.append(f"{location}: invalid type")
            return errors
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        properties = properties if isinstance(properties, dict) else {}
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{location}: missing {key!r}")
        for key, subschema in properties.items():
            if key in value:
                errors.extend(
                    validate_schema_instance(
                        value[key], subschema, location=f"{location}.{key}", depth=depth + 1
                    )
                )
        extra = sorted(set(value) - set(properties))
        if schema.get("additionalProperties") is False and extra:
            errors.append(f"{location}: additional properties {extra}")
    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{location}: fewer than minItems")
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(f"{location}: more than maxItems")
        if schema.get("uniqueItems") is True:
            fingerprints = [canonical_json(item) for item in value]
            if len(fingerprints) != len(set(fingerprints)):
                errors.append(f"{location}: duplicate array items")
        unique_by = schema.get("x-ifm6-unique-by")
        if isinstance(unique_by, list):
            for key in unique_by:
                values = [
                    canonical_json(item.get(key))
                    for item in value
                    if isinstance(item, dict) and key in item
                ]
                if len(values) != len(value) or len(values) != len(set(values)):
                    errors.append(f"{location}: items are not unique by {key}")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(
                    validate_schema_instance(
                        item, schema["items"], location=f"{location}[{index}]", depth=depth + 1
                    )
                )
    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            errors.append(f"{location}: shorter than minLength")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{location}: pattern mismatch")
    return errors


def validate_build_record(
    root: Path,
    record: Mapping[str, Any],
    expected: Mapping[str, Any],
    source_records: Mapping[str, str],
) -> None:
    schema = load_canonical_json(root / BUILD_RECORD_SCHEMA)
    errors = validate_schema_instance(record, schema)
    if errors:
        raise ReleaseError(f"BUILD_RECORD schema validation failed: {errors}")
    if not json_equal(record, expected):
        raise ReleaseError("BUILD_RECORD does not equal its deterministic derivation")
    if record.get("declared_inputs") != ascii_order(record["declared_inputs"]):
        raise ReleaseError("BUILD_RECORD declared inputs are not in ASCII order")
    if record.get("declared_outputs") != ascii_order(record["declared_outputs"]):
        raise ReleaseError("BUILD_RECORD declared outputs are not in ASCII order")
    generators = record.get("generators", [])
    generator_paths = [item.get("path") for item in generators if isinstance(item, dict)]
    if generator_paths != ascii_order(generator_paths):
        raise ReleaseError("BUILD_RECORD generator records are not in ASCII order")
    if any(
        item.get("sha256") != source_records.get(item.get("path"))
        for item in generators
        if isinstance(item, dict)
    ):
        raise ReleaseError("BUILD_RECORD generator hash diverges from SOURCE_SHA256.txt")
    schema_paths = [
        item.get("path") for item in record.get("schemas", []) if isinstance(item, dict)
    ]
    if schema_paths != ascii_order(schema_paths):
        raise ReleaseError("BUILD_RECORD schema records are not in ASCII order")


def prepare_release(root: Path) -> dict[str, Any]:
    supplied_root = root.absolute()
    if supplied_root.is_symlink():
        raise ReleaseError(f"package root may not be a symbolic link: {supplied_root}")
    root = supplied_root.resolve()
    if not root.is_dir():
        raise ReleaseError(f"package root is missing, non-directory or a symlink: {root}")
    provenance = load_canonical_json(root / "PROVENANCE.json")
    recipe, mp, declared, declared_outputs = validate_contracts(root, provenance)
    physical = validate_prebuild_membership(root, declared)
    source_report, source_records, source_raw = verify_source_manifest(root)
    validator_records = run_registered_validators(root, recipe, source_records)
    payloads = snapshot_inputs(root, declared)
    validate_source_snapshot(payloads, source_records)
    record = build_record_document(
        root,
        recipe,
        mp,
        declared,
        declared_outputs,
        payloads,
        source_records,
        source_raw,
        validator_records,
    )
    validate_build_record(root, record, record, source_records)
    record_raw = canonical_json_bytes(record)
    manifest_inputs = dict(payloads)
    manifest_inputs[BUILD_RECORD] = record_raw
    if len(manifest_inputs) != EXPECTED_INTERNAL_PATHS - 1:
        raise ReleaseError("final manifest must have exactly 158 records")
    final_manifest_raw = manifest_bytes(manifest_inputs)
    final_records = parse_manifest_bytes(final_manifest_raw, label="final manifest")
    if set(final_records) != set(declared) - {FINAL_MANIFEST}:
        raise ReleaseError("computed final manifest membership is not the declared set")
    if physical & FINAL_INTERNAL_NODES:
        expected_existing = {
            BUILD_RECORD: record_raw,
            FINAL_MANIFEST: final_manifest_raw,
        }
        for relative, expected_raw in expected_existing.items():
            if (root / relative).read_bytes() != expected_raw:
                raise ReleaseError(
                    f"existing final node is stale or invalid and will not be overwritten: {relative}"
                )
    return {
        "declared": declared,
        "declared_outputs": declared_outputs,
        "final_manifest_raw": final_manifest_raw,
        "input_payloads": payloads,
        "physical_final_nodes": ascii_order(physical & FINAL_INTERNAL_NODES),
        "record": record,
        "record_raw": record_raw,
        "source_records": source_records,
        "source_report": source_report,
        "validator_records": validator_records,
    }


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
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def restore_file(path: Path, previous: bytes | None) -> None:
    if previous is None:
        if path.exists() or path.is_symlink():
            path.unlink()
    else:
        atomic_write(path, previous)


def verify_materialized_internal_nodes(
    root: Path, prepared: Mapping[str, Any]
) -> dict[str, Any]:
    record = load_canonical_json(root / BUILD_RECORD)
    validate_build_record(root, record, prepared["record"], prepared["source_records"])
    if (root / BUILD_RECORD).read_bytes() != prepared["record_raw"]:
        raise ReleaseError("materialized BUILD_RECORD bytes are not deterministic")
    if (root / FINAL_MANIFEST).read_bytes() != prepared["final_manifest_raw"]:
        raise ReleaseError("materialized final-manifest bytes are not deterministic")
    report = run_python_json(
        root,
        ["scripts/verify_manifest.py", "--root", ".", "--manifest", FINAL_MANIFEST],
        gate="final-manifest gate",
    )
    if (
        report.get("status") != "verified"
        or report.get("manifest_kind") != "final_package"
        or report.get("records") != EXPECTED_INTERNAL_PATHS - 1
        or report.get("manifest_sha256") != sha256_bytes(prepared["final_manifest_raw"])
    ):
        raise ReleaseError("final manifest was not attested as the exact package set")
    physical = scan_regular_files(root)
    declared = set(prepared["declared"])
    if physical != declared:
        raise ReleaseError(
            "post-materialization package membership mismatch; "
            f"missing={ascii_order(declared - physical)}, "
            f"unexpected={ascii_order(physical - declared)}"
        )
    expected_payloads = dict(prepared["input_payloads"])
    expected_payloads[BUILD_RECORD] = prepared["record_raw"]
    expected_payloads[FINAL_MANIFEST] = prepared["final_manifest_raw"]
    for relative in prepared["declared"]:
        if (root / relative).read_bytes() != expected_payloads[relative]:
            raise ReleaseError(f"package member changed before ZIP creation: {relative}")
    return report


def zip_info(member_name: str) -> zipfile.ZipInfo:
    if not member_name.isascii():
        raise ReleaseError(f"ZIP member name is not ASCII: {member_name!r}")
    info = zipfile.ZipInfo(member_name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = REGULAR_FILE_MODE << 16
    info.internal_attr = 0
    info.extra = b""
    info.comment = b""
    info.flag_bits = 0
    return info


def write_archive(
    archive: Path,
    *,
    root_name: str,
    ordered_paths: Sequence[str],
    payloads: Mapping[str, bytes],
) -> None:
    safe_relative_path(root_name, label="ZIP top-level root")
    if "/" in root_name:
        raise ReleaseError("ZIP top-level root must be exactly one path segment")
    if ordered_paths != ascii_order(ordered_paths):
        raise ReleaseError("ZIP input order is not ascending ASCII")
    with zipfile.ZipFile(
        archive,
        mode="w",
        compression=zipfile.ZIP_STORED,
        allowZip64=False,
        strict_timestamps=True,
    ) as bundle:
        bundle.comment = b""
        for relative in ordered_paths:
            bundle.writestr(zip_info(f"{root_name}/{relative}"), payloads[relative])


def validate_non_zip64(raw: bytes, *, expected_entries: int) -> None:
    position = raw.rfind(b"PK\x05\x06", max(0, len(raw) - (65535 + 22)))
    if position < 0 or position + 22 != len(raw):
        raise ReleaseError("ZIP has no valid end-of-central-directory record")
    eocd = raw[position : position + 22]
    disk_number = int.from_bytes(eocd[4:6], "little")
    central_disk = int.from_bytes(eocd[6:8], "little")
    fields = (
        int.from_bytes(eocd[8:10], "little"),
        int.from_bytes(eocd[10:12], "little"),
        int.from_bytes(eocd[12:16], "little"),
        int.from_bytes(eocd[16:20], "little"),
    )
    comment_length = int.from_bytes(eocd[20:22], "little")
    if fields[0] == 0xFFFF or fields[1] == 0xFFFF or 0xFFFFFFFF in fields[2:]:
        raise ReleaseError("ZIP64 sentinel detected")
    if (
        disk_number != 0
        or central_disk != 0
        or fields[0] != expected_entries
        or fields[1] != expected_entries
        or fields[2] + fields[3] != position
        or comment_length != 0
    ):
        raise ReleaseError("ZIP end-of-central-directory fields are noncanonical")
    if position >= 20 and raw[position - 20 : position - 16] == b"PK\x06\x07":
        raise ReleaseError("ZIP64 locator detected")


def verify_archive(
    archive: Path,
    *,
    root_name: str,
    ordered_paths: Sequence[str],
    payloads: Mapping[str, bytes],
) -> dict[str, Any]:
    raw = archive.read_bytes()
    safe_relative_path(root_name, label="ZIP top-level root")
    if "/" in root_name:
        raise ReleaseError("ZIP top-level root must be exactly one path segment")
    validate_non_zip64(raw, expected_entries=len(ordered_paths))
    expected_names = [f"{root_name}/{relative}" for relative in ordered_paths]
    with zipfile.ZipFile(archive, mode="r", allowZip64=False) as bundle:
        if bundle.comment != b"":
            raise ReleaseError("ZIP archive comment must be empty")
        infos = bundle.infolist()
        names = [info.filename for info in infos]
        if names != expected_names:
            raise ReleaseError("ZIP membership or ASCII order diverges from package tree")
        assert_unique_paths(names, label="ZIP members")
        if bundle.testzip() is not None:
            raise ReleaseError("ZIP CRC verification failed")
        for info, relative in zip(infos, ordered_paths, strict=True):
            if (
                info.filename.endswith("/")
                or not info.filename.isascii()
                or info.date_time != FIXED_ZIP_TIME
                or info.compress_type != zipfile.ZIP_STORED
                or info.create_system != 3
                or info.external_attr != REGULAR_FILE_MODE << 16
                or info.extra != b""
                or info.comment != b""
                or info.flag_bits != 0
                or info.extract_version >= 45
                or info.create_version >= 45
                or info.file_size != len(payloads[relative])
                or info.compress_size != len(payloads[relative])
            ):
                raise ReleaseError(f"ZIP metadata profile violation: {info.filename}")
            if bundle.read(info) != payloads[relative]:
                raise ReleaseError(f"ZIP payload mismatch: {info.filename}")
    return {
        "archive_bytes": len(raw),
        "archive_sha256": sha256_bytes(raw),
        "entries": len(expected_names),
    }


def package_payloads(prepared: Mapping[str, Any]) -> dict[str, bytes]:
    payloads = dict(prepared["input_payloads"])
    payloads[BUILD_RECORD] = prepared["record_raw"]
    payloads[FINAL_MANIFEST] = prepared["final_manifest_raw"]
    if set(payloads) != set(prepared["declared"]):
        raise ReleaseError("virtual package payloads are not the exact declared set")
    return payloads


def virtual_distribution(
    *, root_name: str, prepared: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, bytes]]:
    payloads = package_payloads(prepared)
    with tempfile.TemporaryDirectory(prefix="ifatigue_release_preflight_") as directory:
        archive = Path(directory) / ARCHIVE_NAME
        write_archive(
            archive,
            root_name=root_name,
            ordered_paths=prepared["declared"],
            payloads=payloads,
        )
        report = verify_archive(
            archive,
            root_name=root_name,
            ordered_paths=prepared["declared"],
            payloads=payloads,
        )
        archive_raw = archive.read_bytes()
    sidecar_raw = f"{report['archive_sha256']}  {ARCHIVE_NAME}\n".encode("ascii")
    external = {
        ARCHIVE_NAME: archive_raw,
        f"{ARCHIVE_NAME}.sha256": sidecar_raw,
        FINAL_MANIFEST: prepared["final_manifest_raw"],
    }
    return report, external


def validate_external_state(
    output_dir: Path, expected_payloads: Mapping[str, bytes]
) -> dict[Path, bytes | None]:
    expected_names = set(expected_payloads)
    if not output_dir.exists():
        return {output_dir / name: None for name in expected_names}
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ReleaseError("distribution path exists but is not a regular directory")
    physical: set[str] = set()
    for entry in os.scandir(output_dir):
        path = Path(entry.path)
        mode = entry.stat(follow_symlinks=False).st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise ReleaseError(f"non-regular object in distribution directory: {path}")
        if not entry.name.isascii():
            raise ReleaseError(f"non-ASCII external output name: {entry.name!r}")
        physical.add(entry.name)
    unexpected = ascii_order(physical - expected_names)
    if unexpected:
        raise ReleaseError(f"unexpected external distribution files: {unexpected}")
    if physical not in (set(), expected_names):
        raise ReleaseError(
            f"partial external distribution state is prohibited: {ascii_order(physical)}"
        )
    previous: dict[Path, bytes | None] = {}
    for name in expected_names:
        path = output_dir / name
        raw = path.read_bytes() if name in physical else None
        if raw is not None and raw != expected_payloads[name]:
            raise ReleaseError(
                f"existing external output is stale or invalid and will not be overwritten: {path}"
            )
        previous[path] = raw
    return previous


def validate_output_directory(root: Path, output_dir: Path) -> Path:
    expected_path = (root.parent / "dist").absolute()
    actual_path = output_dir.absolute()
    if actual_path != expected_path:
        raise ReleaseError(f"distribution directory must be exactly {expected_path}")
    if expected_path.is_symlink():
        raise ReleaseError("distribution directory may not be a symbolic link")
    expected = expected_path.resolve()
    try:
        expected.relative_to(root)
    except ValueError:
        return expected
    raise ReleaseError("distribution directory must remain outside the package root")


def preflight(root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    supplied_root = root.absolute()
    if supplied_root.is_symlink():
        raise ReleaseError(f"package root may not be a symbolic link: {supplied_root}")
    root = supplied_root.resolve()
    output_dir = validate_output_directory(root, output_dir or root.parent / "dist")
    prepared = prepare_release(root)
    archive_report, external_payloads = virtual_distribution(
        root_name=root.name, prepared=prepared
    )
    validate_external_state(output_dir, external_payloads)
    return {
        "allowZip64": False,
        "archive_bytes": archive_report["archive_bytes"],
        "archive_sha256": archive_report["archive_sha256"],
        "build_record_sha256": sha256_bytes(prepared["record_raw"]),
        "declared_internal_paths": len(prepared["declared"]),
        "final_manifest_records": EXPECTED_INTERNAL_PATHS - 1,
        "final_manifest_sha256": sha256_bytes(prepared["final_manifest_raw"]),
        "final_nodes_currently_present": prepared["physical_final_nodes"],
        "mode": "preflight",
        "ready_for_t03_3_10": True,
        "source_manifest_sha256": prepared["source_report"]["manifest_sha256"],
        "status": "pass",
        "validators": len(prepared["validator_records"]),
        "would_write": prepared["declared_outputs"],
    }


def build(root: Path, output_dir: Path) -> dict[str, Any]:
    supplied_root = root.absolute()
    if supplied_root.is_symlink():
        raise ReleaseError(f"package root may not be a symbolic link: {supplied_root}")
    root = supplied_root.resolve()
    output_dir = validate_output_directory(root, output_dir)
    prepared = prepare_release(root)
    archive_report, external_payloads = virtual_distribution(
        root_name=root.name, prepared=prepared
    )
    internal_paths = [root / BUILD_RECORD, root / FINAL_MANIFEST]
    internal_previous = {
        path: path.read_bytes() if path.is_file() and not path.is_symlink() else None
        for path in internal_paths
    }
    external_previous = validate_external_state(output_dir, external_payloads)
    try:
        atomic_write(root / BUILD_RECORD, prepared["record_raw"])
        atomic_write(root / FINAL_MANIFEST, prepared["final_manifest_raw"])
        manifest_report = verify_materialized_internal_nodes(root, prepared)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name in (ARCHIVE_NAME, f"{ARCHIVE_NAME}.sha256", FINAL_MANIFEST):
            atomic_write(output_dir / name, external_payloads[name])
        verify_archive(
            output_dir / ARCHIVE_NAME,
            root_name=root.name,
            ordered_paths=prepared["declared"],
            payloads=package_payloads(prepared),
        )
        if (output_dir / FINAL_MANIFEST).read_bytes() != (root / FINAL_MANIFEST).read_bytes():
            raise ReleaseError("external final-manifest copy is not byte-identical")
        if (
            (output_dir / f"{ARCHIVE_NAME}.sha256").read_bytes()
            != external_payloads[f"{ARCHIVE_NAME}.sha256"]
        ):
            raise ReleaseError("archive sidecar bytes are not canonical")
        return {
            "allowZip64": False,
            "archive": f"dist/{ARCHIVE_NAME}",
            "archive_bytes": archive_report["archive_bytes"],
            "archive_sha256": archive_report["archive_sha256"],
            "build_record": BUILD_RECORD,
            "build_record_sha256": sha256_bytes(prepared["record_raw"]),
            "compression": "ZIP_STORED",
            "entries": archive_report["entries"],
            "file_mode": "0100644",
            "fixed_zip_timestamp": "1980-01-01T00:00:00",
            "manifest": FINAL_MANIFEST,
            "manifest_sha256": manifest_report["manifest_sha256"],
            "sidecar": f"dist/{ARCHIVE_NAME}.sha256",
            "status": "pass",
        }
    except BaseException:
        for path, previous in internal_previous.items():
            restore_file(path, previous)
        for path, previous in external_previous.items():
            restore_file(path, previous)
        raise


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    root_default = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root_default)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="run every internal gate and compute final bytes without writing them",
    )
    values = parser.parse_args(list(argv) if argv is not None else None)
    values.output_dir = values.output_dir or values.root.parent / "dist"
    return values


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        report = (
            preflight(args.root, args.output_dir)
            if args.preflight
            else build(args.root, args.output_dir)
        )
    except (ReleaseError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"build_release.py: ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
