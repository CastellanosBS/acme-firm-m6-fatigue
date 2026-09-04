#!/usr/bin/env python3
"""Validate the ACME-FIRM derivation ledger without third-party packages.

Exit codes are stable: 0 = pass, 1 = contract findings, 2 = usage/I/O/internal
error.  Standard output is one deterministic JSON document; diagnostics never
rewrite an input file.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import importlib.util
import io
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


VALIDATOR_ID = "ACME-FIRM-DERIVATION-LEDGER-VALIDATOR"
VALIDATOR_VERSION = "1.1.0"
EXIT_PASS = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

EXPECTED_HEADER = [
    "row_id",
    "derivation_id",
    "target_path",
    "target_locator",
    "target_field",
    "target_value",
    "purpose",
    "artifact_or_object_refs",
    "file_origin_class",
    "support_ref_type",
    "support_ref_id",
    "support_locator_or_decision",
    "parent_derivation_id",
    "claim_ref",
    "claim_provenance_class",
    "support_level",
    "transformation_type",
    "transformation_or_tension",
    "d_refs",
    "rl_refs",
    "r_refs",
    "f_refs",
    "a_refs",
    "m_level_refs",
    "effect_on_M6",
    "limits",
    "source_verification_status",
    "decision_approval_status",
    "approval_refs",
    "materialization_status",
    "materialization_refs",
    "reviewed_at_utc",
]

LEGACY_HEADER = [
    "row_id",
    "derivation_id",
    "target_path",
    "target_locator",
    "target_field",
    "target_value",
    "purpose",
    "artifact_or_object_ref",
    "file_origin_class",
    "support_ref_type",
    "support_ref_id",
    "support_locator_or_decision",
    "parent_derivation_id",
    "claim_ref",
    "claim_provenance_class",
    "support_level",
    "transformation_type",
    "transformation_or_tension",
    "d_refs",
    "rl_refs",
    "r_refs",
    "f_refs",
    "a_refs",
    "m_level_refs",
    "effect_on_M6",
    "limits",
    "status",
    "approval_ref",
    "reviewed_at_utc",
]

DECISION_RE = re.compile(r"^T(?:0[0-9]|1[0-7])-[A-Z0-9-]+$")
DECISION_SCAN_RE = re.compile(r"\bT(?:0[0-9]|1[0-7])-[A-Z0-9-]+\b")
EVIDENCE_RE = re.compile(r"^EV-[A-Z0-9-]+$")
CLAIM_RE = re.compile(r"^(?:CLM|REQ|LIM)-[A-Z0-9-]+$")

EDGE_COLUMNS = {
    "row_id",
    "support_ref_type",
    "support_ref_id",
    "support_locator_or_decision",
    "source_verification_status",
    "support_level",
}
NUMERIC_MULTI_FIELDS = {
    "d_refs": "D",
    "rl_refs": "RL",
    "r_refs": "R",
    "f_refs": "F",
    "a_refs": "A",
    "m_level_refs": "M",
}
ALL_MULTI_FIELDS = set(NUMERIC_MULTI_FIELDS) | {
    "artifact_or_object_refs",
    "approval_refs",
    "materialization_refs",
}
MATERIALIZED = {"materialized_t03", "verified_t04"}
INACTIVE = {"blocked", "excluded", "superseded"}
STATUS_ENUMS = {
    "source_verification_status": ["verified", "pending", "failed", "not_applicable"],
    "decision_approval_status": ["approved", "pending", "rejected", "not_required", "superseded"],
    "materialization_status": ["planned", "materialized_t03", "verified_t04", "blocked", "excluded", "superseded"],
}
DERIVED_PREFIXES = ("results/", "traces/", "logs/", "environment/")
POST_RUN_METADATA_PATH = "PACKAGE_METADATA.json"
POST_RUN_QA_PATH = "reviews/T03_INTERNAL_QA.json"
FINAL_BUILD_RECORD_PATH = "manifests/BUILD_RECORD.json"
FINAL_MANIFEST_PATH = "MANIFIESTO_SHA256.txt"
FINAL_INTERNAL_NODES = frozenset(
    {FINAL_BUILD_RECORD_PATH, FINAL_MANIFEST_PATH}
)
REFERENCE_DERIVED_PATHS = {
    *(f"results/reference_run/S{index:02d}.result.json" for index in range(16)),
    *(f"traces/reference_run/S{index:02d}.trace.json" for index in range(15)),
    "traces/reference_run/rejections/S15.rejection.json",
    "results/reference_run/conformance_matrix.csv",
    "results/reference_run/conformance_summary.json",
    "results/reference_run/run_metadata.json",
    "results/reference_run/unit_test_summary.json",
    "logs/reference_run/commands.jsonl",
    "logs/reference_run/scenarios.log",
    "logs/reference_run/unittest.log",
    "environment/reference_environment.json",
    "environment/runtime.txt",
}
PUBLISHED_SOURCE_CLASSES = {"conference_paper", "published_article", "book_chapter"}
PUBLISHED_FORBIDDEN_KEYS = {
    "canonical_name",
    "domain",
    "execution_policy",
    "execution_profile",
    "execution_status",
    "numeric_pipeline_eligible",
    "coping_label_source",
    "protected_labels_source",
}
PUBLISHED_FORBIDDEN_TEXT = (
    "pedagóg",
    "pedagog",
    "tutor",
    "doctoral",
    "synthetic_host",
    "synthetic_conformance",
)
PROHIBITED_CONTEXT_SUPPORTS = {"EV-THESIS-GEA", "EV-2019-GEA", "EV-2020-WRAPPER"}
SPEC_LAYER_PATHS = {
    "spec/published/host_appraisal_2018a.json",
    "spec/published/ga_ef_boundary_2018ab.json",
    "spec/published/rule_sadness_2018a.json",
    "spec/published/rule_anger_2018b.json",
    "spec/thesis/f6_specification_rc01.json",
    "spec/decisions/engineering_v1.1.0.json",
}
CONFIGURATION_LAYER_PATHS = {
    "spec/bindings/formula_bindings.json",
    "config/resolved_instance.json",
}
MATERIALIZED_SCHEMA_PATHS = {
    "schemas/provenance.schema.json",
    "schemas/config.schema.json",
    "schemas/scenario.schema.json",
    "schemas/oracle.schema.json",
    "schemas/scenario_catalog.schema.json",
    "schemas/oracle_catalog.schema.json",
    "schemas/test_catalog.schema.json",
    "schemas/result.schema.json",
    "schemas/trace.schema.json",
    "schemas/rejection.schema.json",
    "schemas/formula_bindings.schema.json",
    "schemas/build_recipe.schema.json",
    "schemas/generation_topology.schema.json",
    "schemas/build_record.schema.json",
    "schemas/qa_verdict.schema.json",
}
ALL_SCHEMA_PATHS = MATERIALIZED_SCHEMA_PATHS | {
    "schemas/sources.schema.json",
    "schemas/derivation_ledger.schema.json",
}
FROZEN_INPUT_PATHS = {
    *(f"scenarios/S{index:02d}.json" for index in range(16)),
    *(f"oracles/S{index:02d}.expected.json" for index in range(16)),
    "scenarios/catalog.json",
    "oracles/catalog.json",
    "tests/test_catalog.json",
    "tests/fixtures/sadness_2018a_symbolic.json",
    "tests/oracles/sadness_2018a_symbolic.expected.json",
}
IMPLEMENTATION_SOURCE_PATHS = {
    "src/ifatigue_infra6/__init__.py",
    "src/ifatigue_infra6/canonical_json.py",
    "src/ifatigue_infra6/contract.py",
    "src/ifatigue_infra6/host.py",
    "src/ifatigue_infra6/model.py",
    "src/ifatigue_infra6/modulator.py",
    "src/ifatigue_infra6/rules.py",
    "src/ifatigue_infra6/runner.py",
    "src/ifatigue_infra6/trace.py",
}
UNIT_TEST_MODULE_PATHS = {
    "tests/test_contract.py",
    "tests/test_model.py",
    "tests/test_rules.py",
    "tests/test_trace.py",
}
T03_3_6_CODE_PATHS = IMPLEMENTATION_SOURCE_PATHS | UNIT_TEST_MODULE_PATHS
T03_3_7_EXECUTABLE_PATHS = {
    "commands/validate_qa_verdict.py",
    "scripts/build_derivation_ledger.py",
    "scripts/build_source_manifest.py",
    "scripts/validate_derivation_ledger.py",
    "scripts/run_scenarios.py",
    "scripts/run_tests.py",
    "scripts/regenerate_evidence.py",
    "scripts/compare_outputs.py",
    "scripts/verify_manifest.py",
    "scripts/build_release.py",
}
T03_3_7_BUILD_CONTRACT_PATHS = {
    "manifests/BUILD_RECIPE.json",
    "manifests/GENERATION_TOPOLOGY.json",
}
SOURCE_MANIFEST_PATH = "manifests/SOURCE_SHA256.txt"
EXPECTED_SOURCE_MEMBERS = 90
CLOSED_JSON_PROJECTION_PATHS = SPEC_LAYER_PATHS | CONFIGURATION_LAYER_PATHS


class InputFailure(Exception):
    """An input or validator configuration cannot be read safely."""


class CSVProfileFailure(Exception):
    """The byte-valid text is not ACME-FIRM all-quoted CSV."""


class DuplicateJSONKey(ValueError):
    """A JSON object repeats a key."""


class Report:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.findings: list[dict[str, Any]] = []
        self.metrics: dict[str, Any] = {}
        self.inputs: dict[str, Any] = {}

    def add(
        self,
        code: str,
        message: str,
        *,
        severity: str = "error",
        row_id: str | None = None,
        details: Any | None = None,
    ) -> None:
        item: dict[str, Any] = {
            "code": code,
            "message": message,
            "severity": severity,
        }
        if row_id:
            item["row_id"] = row_id
        if details is not None:
            item["details"] = details
        self.findings.append(item)

    def document(self, exit_code: int) -> dict[str, Any]:
        severity_order = {"error": 0, "warning": 1, "info": 2}
        findings = sorted(
            self.findings,
            key=lambda item: (
                severity_order.get(item["severity"], 9),
                item["code"],
                item.get("row_id", ""),
                json.dumps(item.get("details"), ensure_ascii=False, sort_keys=True),
                item["message"],
            ),
        )
        counts = Counter(item["severity"] for item in findings)
        return {
            "exit_code": exit_code,
            "finding_summary": {key: counts.get(key, 0) for key in ("error", "warning", "info")},
            "findings": findings,
            "inputs": dict(sorted(self.inputs.items())),
            "metrics": self.metrics,
            "mode": self.mode,
            "outcome": "pass" if exit_code == EXIT_PASS else ("fail" if exit_code == EXIT_FINDINGS else "error"),
            "validator": {"id": VALIDATOR_ID, "version": VALIDATOR_VERSION},
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_display(path: Path, package_root: Path) -> str:
    try:
        return path.resolve().relative_to(package_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def read_json_file(path: Path, label: str, report: Report, package_root: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputFailure(f"cannot read {label}: {exc}") from exc
    report.inputs[label] = {
        "bytes": len(raw),
        "path": relative_display(path, package_root),
        "sha256": sha256_bytes(raw),
    }
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJSONKey) as exc:
        raise InputFailure(f"invalid {label} JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise InputFailure(f"{label} must contain a JSON object")
    return value


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKey(key)
        result[key] = value
    return result


def validate_final_internal_nodes(
    package_root: Path,
    provenance: dict[str, Any],
    declared: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Attest the atomic final pair without re-running this validator.

    PACKAGE_METADATA is an immutable T03.3-9 snapshot, so the T03.3-10 nodes
    are registered dynamically only after their exact deterministic derivation,
    membership and physical hashes have been verified.  The release module is
    imported solely for its pure contract/derivation helpers; invoking its
    validator runner here would recurse into this command.
    """

    present = {
        relative
        for relative in FINAL_INTERNAL_NODES
        if (package_root / relative).exists()
        or (package_root / relative).is_symlink()
    }
    if not present:
        return {}, []
    if present != set(FINAL_INTERNAL_NODES):
        return {}, [
            {
                "reason": "partial_final_node_state",
                "present": sorted(present),
                "missing": sorted(set(FINAL_INTERNAL_NODES) - present),
            }
        ]
    nonregular = sorted(
        relative
        for relative in FINAL_INTERNAL_NODES
        if (package_root / relative).is_symlink()
        or not (package_root / relative).is_file()
    )
    if nonregular:
        return {}, [
            {
                "reason": "final_node_nonregular_or_symlink",
                "paths": nonregular,
            }
        ]

    try:
        release_path = package_root / "scripts/build_release.py"
        specification = importlib.util.spec_from_file_location(
            "_acme_firm_build_release_contract", release_path
        )
        if specification is None or specification.loader is None:
            raise RuntimeError("cannot load scripts/build_release.py")
        release = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(release)

        recipe, materialization_policy, release_declared, declared_outputs = (
            release.validate_contracts(package_root, provenance)
        )
        if set(release_declared) != set(declared):
            raise release.ReleaseError(
                "release and post-run declarations do not identify the same paths"
            )
        physical = release.validate_prebuild_membership(
            package_root, release_declared
        )
        if physical & set(FINAL_INTERNAL_NODES) != set(FINAL_INTERNAL_NODES):
            raise release.ReleaseError("final internal pair is not physically complete")

        source_report, source_records, source_raw = release.verify_source_manifest(
            package_root
        )
        payloads = release.snapshot_inputs(package_root, release_declared)
        release.validate_source_snapshot(payloads, source_records)

        registry = recipe.get("validator_registry", {})
        entries = registry.get("validators", []) if isinstance(registry, dict) else []
        if not isinstance(entries, list) or len(entries) != 2:
            raise release.ReleaseError(
                "BUILD_RECIPE must register exactly two release validators"
            )
        validator_records: list[dict[str, Any]] = []
        validator_identities: set[tuple[str, str]] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise release.ReleaseError(
                    "validator registry contains a non-object"
                )
            path = release.safe_relative_path(
                entry.get("path"), label="validator path"
            )
            validator_id = entry.get("validator_id")
            command = entry.get("validator_command")
            release.validator_arguments(entry)
            if path not in source_records:
                raise release.ReleaseError(
                    f"validator is absent from SOURCE_SHA256.txt: {path}"
                )
            if type(validator_id) is not str or type(command) is not str:
                raise release.ReleaseError(
                    "validator registry identity or command is invalid"
                )
            validator_identities.add((validator_id, path))
            validator_records.append(
                {
                    "execution_status": "pass",
                    "exit_code": 0,
                    "path": path,
                    "validator_command": command,
                    "validator_id": validator_id,
                }
            )
        expected_validators = {
            ("VAL-DERIVATION-LEDGER-001", "scripts/validate_derivation_ledger.py"),
            ("VAL-QG-PROVENANCE-001", "commands/validate_qa_verdict.py"),
        }
        if validator_identities != expected_validators:
            raise release.ReleaseError(
                "validator registry identities are not the approved pair"
            )

        expected_record = release.build_record_document(
            package_root,
            recipe,
            materialization_policy,
            release_declared,
            declared_outputs,
            payloads,
            source_records,
            source_raw,
            validator_records,
        )
        actual_record = release.load_canonical_json(
            package_root / FINAL_BUILD_RECORD_PATH
        )
        release.validate_build_record(
            package_root, actual_record, expected_record, source_records
        )
        expected_record_raw = release.canonical_json_bytes(expected_record)
        if (package_root / FINAL_BUILD_RECORD_PATH).read_bytes() != expected_record_raw:
            raise release.ReleaseError(
                "BUILD_RECORD bytes do not equal the deterministic derivation"
            )

        manifest_inputs = dict(payloads)
        manifest_inputs[FINAL_BUILD_RECORD_PATH] = expected_record_raw
        expected_manifest_raw = release.manifest_bytes(manifest_inputs)
        actual_manifest_raw = (package_root / FINAL_MANIFEST_PATH).read_bytes()
        if actual_manifest_raw != expected_manifest_raw:
            raise release.ReleaseError(
                "final manifest bytes do not equal the deterministic derivation"
            )
        final_records = release.parse_manifest_bytes(
            actual_manifest_raw, label="final manifest"
        )
        if (
            len(final_records) != len(release_declared) - 1
            or set(final_records) != set(release_declared) - {FINAL_MANIFEST_PATH}
        ):
            raise release.ReleaseError(
                "final manifest membership is not the exact declared package set"
            )
        final_report = release.run_python_json(
            package_root,
            [
                "scripts/verify_manifest.py",
                "--root",
                ".",
                "--manifest",
                FINAL_MANIFEST_PATH,
            ],
            gate="final-manifest gate",
        )
        if (
            final_report.get("status") != "verified"
            or final_report.get("manifest_kind") != "final_package"
            or final_report.get("records") != len(release_declared) - 1
            or final_report.get("manifest_sha256")
            != sha256_bytes(actual_manifest_raw)
        ):
            raise release.ReleaseError(
                "final manifest verifier did not attest the exact package set"
            )
        if release.scan_regular_files(package_root) != set(release_declared):
            raise release.ReleaseError(
                "post-finalization physical membership is not exact"
            )
        if source_report.get("status") != "verified":
            raise release.ReleaseError("source snapshot was not verified")
    except Exception as exc:
        return {}, [
            {
                "reason": "final_node_attestation_failed",
                "details": str(exc),
            }
        ]

    records: dict[str, dict[str, Any]] = {}
    for relative in sorted(FINAL_INTERNAL_NODES):
        raw = (package_root / relative).read_bytes()
        records[relative] = {
            "bytes": len(raw),
            "materialization_status": "materialized_t03",
            "origin_class": declared.get(relative),
            "path": relative,
            "sha256": sha256_bytes(raw),
        }
    return records, []


def load_post_run_materialization_register(
    package_root: Path,
    provenance: dict[str, Any],
    report: Report,
) -> dict[str, dict[str, Any]]:
    """Validate the downstream T03.3-9 register without creating hash cycles.

    The frozen derivation ledger remains a pre-run contract.  PACKAGE_METADATA
    is deliberately outside SOURCE_SHA256 and attests the later state transition
    by path, byte count and SHA-256.  The QA record is excluded because it is
    created after, and cryptographically points back to, this metadata snapshot.
    """

    metadata_path = package_root / POST_RUN_METADATA_PATH
    if not metadata_path.is_file():
        report.metrics["post_run_materialization_register"] = {"present": False}
        return {}
    errors: list[dict[str, Any]] = []
    try:
        raw = metadata_path.read_bytes()
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=reject_duplicate_pairs
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJSONKey) as exc:
        report.add(
            "post_run.register.invalid",
            "PACKAGE_METADATA.json is not readable canonical JSON",
            details=str(exc),
        )
        return {}
    if not isinstance(document, dict):
        report.add(
            "post_run.register.invalid",
            "PACKAGE_METADATA.json must contain an object",
        )
        return {}
    canonical = (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    if raw != canonical:
        errors.append({"reason": "metadata_not_canonical_json"})
    identity = provenance.get("package_identity", {})
    expected_identity = {
        "package_id": identity.get("conceptual_id"),
        "package_version": identity.get("package_version"),
        "release_stage": identity.get("release_stage"),
    }
    for key, expected in expected_identity.items():
        if document.get(key) != expected:
            errors.append(
                {
                    "reason": "package_identity_mismatch",
                    "field": key,
                    "expected": expected,
                    "actual": document.get(key),
                }
            )
    if document.get("materialization_status") != (
        "materialized_t03_pending_finalization_and_T04"
    ):
        errors.append({"reason": "materialization_status_mismatch"})

    manifest_path = package_root / SOURCE_MANIFEST_PATH
    manifest_raw = manifest_path.read_bytes() if manifest_path.is_file() else b""
    source_snapshot = document.get("source_snapshot", {})
    manifest_records = len(manifest_raw.splitlines()) if manifest_raw else 0
    if not isinstance(source_snapshot, dict) or source_snapshot != {
        "manifest_path": SOURCE_MANIFEST_PATH,
        "records": manifest_records,
        "run_id": "RUN-T03-REFERENCE-001",
        "sha256": sha256_bytes(manifest_raw),
    }:
        errors.append({"reason": "source_snapshot_mismatch"})

    declared: dict[str, str] = {}
    declaration_conflicts: list[dict[str, str]] = []
    for item in provenance.get("planned_tree", []):
        if isinstance(item, dict):
            add_declared_path(
                declared,
                declaration_conflicts,
                item.get("path"),
                item.get("origin_class"),
                "planned_tree",
            )
    for file_set in provenance.get("planned_file_sets", []):
        if not isinstance(file_set, dict):
            continue
        for item_path in file_set.get("paths", []):
            add_declared_path(
                declared,
                declaration_conflicts,
                item_path,
                file_set.get("origin_class"),
                str(file_set.get("set_id", "planned_file_set")),
            )
    if declaration_conflicts:
        errors.append({"reason": "declaration_conflicts"})

    reference = document.get("reference_evidence", {})
    reference_items = reference.get("files", []) if isinstance(reference, dict) else []
    reference_by_path: dict[str, dict[str, Any]] = {}
    for item in reference_items if isinstance(reference_items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            errors.append({"reason": "malformed_reference_evidence_record"})
            continue
        item_path = item["path"]
        if item_path in reference_by_path:
            errors.append({"reason": "duplicate_reference_evidence_path", "path": item_path})
            continue
        reference_by_path[item_path] = item
    if set(reference_by_path) != REFERENCE_DERIVED_PATHS:
        errors.append(
            {
                "reason": "reference_evidence_path_set_mismatch",
                "missing": sorted(REFERENCE_DERIVED_PATHS - set(reference_by_path)),
                "unexpected": sorted(set(reference_by_path) - REFERENCE_DERIVED_PATHS),
            }
        )
    reference_records: list[str] = []
    for item_path, item in sorted(reference_by_path.items()):
        destination = package_root / item_path
        actual = destination.read_bytes() if destination.is_file() else None
        expected_keys = {
            "bytes",
            "generated_by",
            "materialization_status",
            "origin_class",
            "path",
            "sha256",
        }
        if set(item) != expected_keys:
            errors.append({"reason": "reference_evidence_record_shape", "path": item_path})
        if (
            actual is None
            or item.get("bytes") != len(actual)
            or item.get("sha256") != sha256_bytes(actual)
            or item.get("origin_class") != "derived_automatically"
            or item.get("materialization_status") != "materialized_t03"
            or item.get("generated_by") != "RUN-T03-REFERENCE-001"
        ):
            errors.append({"reason": "reference_evidence_fixity_mismatch", "path": item_path})
        if actual is not None:
            reference_records.append(
                f"{item_path}\0{sha256_bytes(actual)}\0{len(actual)}\n"
            )
    reference_aggregate = sha256_bytes("".join(reference_records).encode("utf-8"))
    if not isinstance(reference, dict) or any(
        (
            reference.get("expected_count") != 41,
            reference.get("aggregate_sha256") != reference_aggregate,
        )
    ):
        errors.append({"reason": "reference_evidence_summary_mismatch"})

    inventory = document.get("package_inventory", {})
    inventory_items = inventory.get("files", []) if isinstance(inventory, dict) else []
    inventory_by_path: dict[str, dict[str, Any]] = {}
    for item in inventory_items if isinstance(inventory_items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            errors.append({"reason": "malformed_inventory_record"})
            continue
        item_path = item["path"]
        if item_path in inventory_by_path:
            errors.append({"reason": "duplicate_inventory_path", "path": item_path})
            continue
        inventory_by_path[item_path] = item
    excluded = [POST_RUN_METADATA_PATH, POST_RUN_QA_PATH]
    if not isinstance(inventory, dict) or inventory.get("excluded_paths") != excluded:
        errors.append({"reason": "inventory_exclusions_mismatch"})
    if not isinstance(inventory, dict) or inventory.get("expected_declared_paths") != 159:
        errors.append({"reason": "inventory_declared_count_mismatch"})
    physical_package = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.relative_to(package_root).parts
        and path.suffix != ".pyc"
        and "dist" not in path.relative_to(package_root).parts[:1]
        and not any(
            part.startswith(".") and part.endswith(".tmp")
            for part in path.relative_to(package_root).parts
        )
    }
    unexpected_physical = sorted(physical_package - set(declared))
    if unexpected_physical:
        errors.append(
            {"reason": "undeclared_physical_package_files", "paths": unexpected_physical}
        )
    # PACKAGE_METADATA is the frozen T03.3-9 snapshot.  Its inventory and
    # pending set remain stable after the T03.3-10 pair is materialized.
    expected_inventory = set(declared) - set(excluded) - FINAL_INTERNAL_NODES
    if set(inventory_by_path) != expected_inventory:
        errors.append(
            {
                "reason": "package_inventory_path_set_mismatch",
                "missing": sorted(expected_inventory - set(inventory_by_path)),
                "unexpected": sorted(set(inventory_by_path) - expected_inventory),
            }
        )
    for item_path, item in sorted(inventory_by_path.items()):
        destination = package_root / item_path
        actual = destination.read_bytes() if destination.is_file() else None
        if (
            set(item)
            != {"bytes", "materialization_status", "origin_class", "path", "sha256"}
            or actual is None
            or item.get("bytes") != len(actual)
            or item.get("sha256") != sha256_bytes(actual)
            or item.get("origin_class") != declared.get(item_path)
            or item.get("materialization_status") != "materialized_t03"
        ):
            errors.append({"reason": "package_inventory_fixity_mismatch", "path": item_path})
    pending = sorted(FINAL_INTERNAL_NODES)
    if document.get("pending_paths") != pending:
        errors.append(
            {
                "reason": "pending_path_set_mismatch",
                "expected": pending,
                "actual": document.get("pending_paths"),
            }
        )
    final_register: dict[str, dict[str, Any]] = {}
    final_errors: list[dict[str, Any]] = []
    finalization_evaluated = False
    if errors:
        report.add(
            "post_run.register.invalid",
            "the downstream T03.3-9 materialization register is inconsistent",
            details=errors[:80],
        )
        register: dict[str, dict[str, Any]] = {}
    else:
        register = inventory_by_path | reference_by_path
        register[POST_RUN_METADATA_PATH] = {
            "path": POST_RUN_METADATA_PATH,
            "bytes": len(raw),
            "sha256": sha256_bytes(raw),
            "origin_class": declared.get(POST_RUN_METADATA_PATH),
            "materialization_status": "materialized_t03",
        }
        final_register, final_errors = validate_final_internal_nodes(
            package_root, provenance, declared
        )
        finalization_evaluated = True
        if final_errors:
            report.add(
                "post_run.finalization.invalid",
                "the T03.3-10 final internal nodes are partial, stale or invalid",
                details=final_errors,
            )
        else:
            register.update(final_register)
    physical_final_nodes = {
        relative
        for relative in FINAL_INTERNAL_NODES
        if (package_root / relative).exists()
        or (package_root / relative).is_symlink()
    }
    if not finalization_evaluated:
        finalization_state = "not_evaluated_snapshot_invalid"
    elif not physical_final_nodes:
        finalization_state = "prefinal_absent"
    elif physical_final_nodes != set(FINAL_INTERNAL_NODES):
        finalization_state = "invalid_partial"
    elif len(final_register) == len(FINAL_INTERNAL_NODES):
        finalization_state = "final_attested"
    else:
        finalization_state = "invalid_complete"
    report.inputs["post_run_metadata"] = {
        "bytes": len(raw),
        "path": POST_RUN_METADATA_PATH,
        "sha256": sha256_bytes(raw),
    }
    report.metrics["post_run_materialization_register"] = {
        "errors": len(errors),
        "finalization_attested": len(final_register) == len(FINAL_INTERNAL_NODES),
        "finalization_errors": len(final_errors),
        "finalization_evaluated": finalization_evaluated,
        "finalization_state": finalization_state,
        "inventory_records": len(inventory_by_path),
        "present": True,
        "reference_records": len(reference_by_path),
        "registered_paths": len(register),
        "final_nodes_registered": len(
            set(register) & FINAL_INTERNAL_NODES
        ),
    }
    return register


def reject_nonfinite(token: str) -> Any:
    raise ValueError(f"non-finite JSON number: {token}")


def parse_canonical_json(cell: str) -> Any:
    value = json.loads(
        cell,
        object_pairs_hook=reject_duplicate_pairs,
        parse_constant=reject_nonfinite,
    )
    if not finite_tree(value):
        raise ValueError("non-finite numeric value")
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if canonical != cell:
        raise ValueError(f"not canonical; expected {canonical}")
    return value


def finite_tree(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(finite_tree(item) for item in value)
    if isinstance(value, dict):
        return all(finite_tree(item) for item in value.values())
    return True


def validate_ledger_bytes(path: Path, report: Report, package_root: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputFailure(f"cannot read ledger: {exc}") from exc
    report.inputs["ledger"] = {
        "bytes": len(raw),
        "path": relative_display(path, package_root),
        "sha256": sha256_bytes(raw),
    }
    if raw.startswith(b"\xef\xbb\xbf"):
        report.add("bytes.bom", "UTF-8 BOM is forbidden")
    if b"\x00" in raw:
        report.add("bytes.nul", "NUL bytes are forbidden")
    if b"\r" in raw:
        report.add("bytes.cr", "CR bytes are forbidden; use LF only")
    if not raw.endswith(b"\n"):
        report.add("bytes.final_lf.missing", "the ledger must end in one LF")
    elif raw.endswith(b"\n\n"):
        report.add("bytes.final_lf.multiple", "the ledger must end in exactly one LF")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputFailure(f"ledger is not valid UTF-8: {exc}") from exc
    if unicodedata.normalize("NFC", text) != text:
        report.add("bytes.unicode.not_nfc", "ledger text is not Unicode NFC")
    trailing_lines = [
        index
        for index, line in enumerate(text.split("\n")[:-1], start=1)
        if line.endswith((" ", "\t"))
    ]
    if trailing_lines:
        report.add(
            "bytes.trailing_space",
            "physical lines end in space or tab",
            details={"count": len(trailing_lines), "lines": trailing_lines},
        )
    return text


def parse_all_quoted_csv(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    index = 0
    length = len(text)
    line_number = 1
    while index < length:
        if text[index] == "\n":
            raise CSVProfileFailure(f"blank record at line {line_number}")
        row: list[str] = []
        while True:
            if index >= length or text[index] != '"':
                raise CSVProfileFailure(f"unquoted field at line {line_number}, byte-character {index}")
            index += 1
            chars: list[str] = []
            while True:
                if index >= length:
                    raise CSVProfileFailure(f"unterminated quoted field at line {line_number}")
                char = text[index]
                if char == '"':
                    if index + 1 < length and text[index + 1] == '"':
                        chars.append('"')
                        index += 2
                        continue
                    index += 1
                    break
                if char in "\r\n":
                    raise CSVProfileFailure(f"embedded line break at line {line_number}")
                chars.append(char)
                index += 1
            value = "".join(chars)
            if value.endswith((" ", "\t")):
                raise CSVProfileFailure(f"field has trailing space at line {line_number}, column {len(row) + 1}")
            row.append(value)
            if index >= length:
                raise CSVProfileFailure("record is not terminated by LF")
            if text[index] == ",":
                index += 1
                continue
            if text[index] == "\n":
                index += 1
                line_number += 1
                break
            raise CSVProfileFailure(
                f"unexpected character after closing quote at line {line_number}, column {len(row)}"
            )
        rows.append(row)
    return rows


def parse_ledger(text: str, report: Report) -> tuple[list[str], list[dict[str, str]], bool]:
    try:
        table = parse_all_quoted_csv(text)
    except CSVProfileFailure as exc:
        report.add("csv.profile", str(exc))
        return [], [], False
    try:
        standard = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        report.add("csv.rfc4180", f"stdlib CSV parser rejected the ledger: {exc}")
        return [], [], False
    if standard != table:
        report.add("csv.parser_disagreement", "restricted parser and stdlib CSV parser disagree")
        return [], [], False
    if not table:
        report.add("csv.empty", "ledger contains no header")
        return [], [], False
    header = table[0]
    exact_header = header == EXPECTED_HEADER
    if not exact_header:
        report.add(
            "csv.header.migration_required",
            "header is not the approved 32-column v1.1.0 contract",
            details={
                "actual": header,
                "actual_count": len(header),
                "expected": EXPECTED_HEADER,
                "expected_count": len(EXPECTED_HEADER),
                "legacy_29_column_header": header == LEGACY_HEADER,
            },
        )
    duplicate_headers = sorted(name for name, count in Counter(header).items() if count > 1)
    if duplicate_headers:
        report.add("csv.header.duplicate", "header contains duplicate fields", details=duplicate_headers)
    records: list[dict[str, str]] = []
    bad_widths: list[dict[str, int]] = []
    for line_number, cells in enumerate(table[1:], start=2):
        if len(cells) != len(header):
            bad_widths.append({"line": line_number, "actual": len(cells), "expected": len(header)})
            continue
        row = dict(zip(header, cells))
        row["_line"] = str(line_number)
        if "artifact_or_object_refs" not in row and "artifact_or_object_ref" in row:
            row["artifact_or_object_refs"] = row["artifact_or_object_ref"]
        if "approval_refs" not in row and "approval_ref" in row:
            row["approval_refs"] = row["approval_ref"]
        if "status" in row:
            row["_legacy_status"] = row["status"]
        records.append(row)
    if bad_widths:
        report.add("csv.row.width", "records do not match the header width", details=bad_widths)
    return header, records, exact_header


def validate_schema_document(schema: dict[str, Any]) -> None:
    if schema.get("schema_version") != VALIDATOR_VERSION:
        raise InputFailure(
            f"schema_version must be {VALIDATOR_VERSION}, got {schema.get('schema_version')!r}"
        )
    header = schema.get("csv_contract", {}).get("header")
    if header != EXPECTED_HEADER:
        raise InputFailure("schema csv_contract.header is not the approved 32-column header")
    if schema.get("required") != EXPECTED_HEADER:
        raise InputFailure("schema required list must exactly match the approved header order")
    if set(schema.get("properties", {})) != set(EXPECTED_HEADER):
        raise InputFailure("schema properties do not exactly match the approved header")
    for field, expected in STATUS_ENUMS.items():
        actual = schema.get("properties", {}).get(field, {}).get("enum")
        if actual != expected:
            raise InputFailure(f"schema {field} enum is not the approved v1.1.0 vocabulary")


def validate_rows_against_schema(
    rows: list[dict[str, str]], schema: dict[str, Any], report: Report, exact_header: bool
) -> None:
    if not exact_header:
        report.add(
            "schema.rows.skipped_for_legacy_header",
            "row-schema checks were skipped; diagnostic checks use legacy aliases",
            severity="info",
        )
        return
    properties = schema["properties"]
    required = schema["required"]
    for row in rows:
        row_id = row.get("row_id") or f"line:{row.get('_line', '?')}"
        missing = [name for name in required if name not in row]
        extra = sorted(set(row) - set(properties) - {"_line"})
        if missing:
            report.add("schema.required", "required columns are missing", row_id=row_id, details=missing)
        if extra:
            report.add("schema.additional", "unexpected columns are present", row_id=row_id, details=extra)
        for name, contract in properties.items():
            if name not in row:
                continue
            value = row[name]
            if contract.get("type") == "string" and not isinstance(value, str):
                report.add("schema.type", f"{name} must be a string", row_id=row_id)
                continue
            if "minLength" in contract and len(value) < contract["minLength"]:
                report.add("schema.min_length", f"{name} is too short", row_id=row_id)
            if "enum" in contract and value not in contract["enum"]:
                report.add(
                    "schema.enum",
                    f"{name} is outside its controlled vocabulary",
                    row_id=row_id,
                    details={"actual": value, "allowed": contract["enum"]},
                )
            if "pattern" in contract and re.search(contract["pattern"], value) is None:
                report.add(
                    "schema.pattern",
                    f"{name} does not match its pattern",
                    row_id=row_id,
                    details={"actual": value, "pattern": contract["pattern"]},
                )
        validate_row_conditionals(row, report)


def validate_row_conditionals(row: dict[str, str], report: Report) -> None:
    row_id = row["row_id"]
    support_type = row["support_ref_type"]
    support_id = row["support_ref_id"]
    source_status = row["source_verification_status"]
    decision_status = row["decision_approval_status"]
    approvals = row["approval_refs"]
    materialization = row["materialization_status"]
    materialization_refs = row["materialization_refs"]
    if support_type == "evidence_unit":
        if not EVIDENCE_RE.fullmatch(support_id):
            report.add("state.evidence.ref", "evidence support must use EV-*", row_id=row_id)
        if source_status == "not_applicable":
            report.add("state.evidence.verification", "evidence support needs a source status", row_id=row_id)
    elif support_type == "approved_decision":
        if not DECISION_RE.fullmatch(support_id):
            report.add("state.decision.ref", "decision support must use T00-T17", row_id=row_id)
        if source_status != "not_applicable":
            report.add("state.decision.source_status", "decision support uses source status not_applicable", row_id=row_id)
        if decision_status != "approved":
            report.add("state.decision.approval", "approved decision support needs decision status approved", row_id=row_id)
    elif support_type == "" and materialization != "blocked":
        report.add("state.support.empty", "empty support is allowed only for a blocked row", row_id=row_id)
    if support_type == "" and (support_id or row["support_locator_or_decision"]):
        report.add("state.support.orphan_ref", "empty support type cannot carry a support id or locator", row_id=row_id)
    if support_type == "" and source_status != "not_applicable":
        report.add("state.support.source_status", "empty support uses source status not_applicable", row_id=row_id)
    if decision_status == "not_required" and approvals:
        report.add("state.approval.unexpected_refs", "not_required cannot have approval_refs", row_id=row_id)
    if decision_status != "not_required" and not approvals:
        report.add("state.approval.missing_refs", "decision status requires approval_refs", row_id=row_id)
    if materialization in MATERIALIZED and not materialization_refs:
        report.add("state.materialization.missing_refs", "materialized row needs materialization_refs", row_id=row_id)
    if materialization in {"planned", "blocked", "excluded"} and materialization_refs:
        report.add("state.materialization.unexpected_refs", "non-materialized row cannot have materialization_refs", row_id=row_id)
    if materialization == "blocked" and row["target_value"] != "null":
        report.add("state.materialization.blocked_value", "blocked row must use JSON null", row_id=row_id)
    if source_status in {"pending", "failed"} and materialization in MATERIALIZED:
        report.add("state.materialization.unverified_source", "unverified evidence cannot be materialized", row_id=row_id)
    if decision_status in {"pending", "rejected", "superseded"} and materialization in MATERIALIZED:
        report.add("state.materialization.unapproved_decision", "unapproved decision cannot be materialized", row_id=row_id)
    try:
        datetime.strptime(row["reviewed_at_utc"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        report.add("schema.date_time", "reviewed_at_utc is not a real UTC timestamp", row_id=row_id)


def active(row: dict[str, str]) -> bool:
    status = row.get("materialization_status", "")
    if not status:
        status = row.get("_legacy_status", "")
    return status not in INACTIVE


def materialization_status(row: dict[str, str]) -> str:
    status = row.get("materialization_status", "")
    if status:
        return status
    legacy = row.get("_legacy_status", "")
    if legacy == "blocked":
        return "blocked"
    if legacy == "excluded":
        return "excluded"
    if legacy == "superseded":
        return "superseded"
    return "planned"


def split_multi(value: str) -> list[str]:
    return [] if value == "" else value.split("|")


def support_edge(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        row.get("support_ref_type", ""),
        row.get("support_ref_id", ""),
        row.get("support_level", ""),
        row.get("support_locator_or_decision", ""),
    )


def decision_edge(decision_id: str, level: str = "direct") -> tuple[str, str, str, str]:
    return (
        "approved_decision",
        decision_id,
        level,
        f"PROVENANCE.json#decisions/{decision_id}",
    )


def evidence_edge(evidence_id: str, level: str = "direct") -> tuple[str, str, str, str]:
    return (
        "evidence_unit",
        evidence_id,
        level,
        f"SOURCES.json#{evidence_id}",
    )


def validate_json_cells(rows: list[dict[str, str]], report: Report) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for row in rows:
        row_id = row.get("row_id") or f"line:{row.get('_line', '?')}"
        try:
            parsed[row_id] = parse_canonical_json(row.get("target_value", ""))
        except (json.JSONDecodeError, DuplicateJSONKey, ValueError) as exc:
            report.add("target_value.canonical_json", str(exc), row_id=row_id)
    return parsed


def validate_identifiers_groups_and_graph(rows: list[dict[str, str]], report: Report) -> None:
    row_ids = [row.get("row_id", "") for row in rows]
    duplicates = sorted(value for value, count in Counter(row_ids).items() if value and count > 1)
    if duplicates:
        report.add("rows.row_id.duplicate", "row_id values are not unique", details=duplicates)
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        derivation_id = row.get("derivation_id", "")
        groups[derivation_id].append(row)
        expected_prefix = f"ROW-{derivation_id}-"
        if derivation_id and not row.get("row_id", "").startswith(expected_prefix):
            report.add(
                "rows.row_id.derivation_mismatch",
                "row_id does not encode derivation_id",
                row_id=row.get("row_id"),
                details={"expected_prefix": expected_prefix},
            )
    comparison_columns = [
        name for name in EXPECTED_HEADER if name not in EDGE_COLUMNS
    ]
    for derivation_id, group in sorted(groups.items()):
        if not derivation_id:
            continue
        for column in comparison_columns:
            values = {row.get(column, "") for row in group}
            if len(values) > 1:
                report.add(
                    "rows.derivation.semantic_mismatch",
                    "support edges disagree on a target/semantic column",
                    details={"column": column, "derivation_id": derivation_id, "values": sorted(values)},
                )
    derivations = set(groups)
    parent_by_derivation: dict[str, str] = {}
    unresolved: list[dict[str, str]] = []
    for derivation_id, group in groups.items():
        parent = group[0].get("parent_derivation_id", "")
        parent_by_derivation[derivation_id] = parent
        if parent and parent not in derivations:
            unresolved.append({"derivation_id": derivation_id, "parent": parent})
        if parent == derivation_id and parent:
            report.add("graph.self_parent", "derivation is its own parent", details={"derivation_id": derivation_id})
    if unresolved:
        report.add("graph.unresolved_parent", "parent derivations do not resolve", details=unresolved)
    cycles: set[tuple[str, ...]] = set()
    for start in sorted(parent_by_derivation):
        order: list[str] = []
        cursor = start
        while cursor:
            if cursor in order:
                cycle = order[order.index(cursor):] + [cursor]
                rotations = [tuple(cycle[index:-1] + cycle[:index] + [cycle[index]]) for index in range(len(cycle) - 1)]
                cycles.add(min(rotations))
                break
            order.append(cursor)
            cursor = parent_by_derivation.get(cursor, "")
    if cycles:
        report.add("graph.cycle", "derivation graph contains cycles", details=[list(cycle) for cycle in sorted(cycles)])


def validate_multi_values_and_coverage(rows: list[dict[str, str]], report: Report) -> None:
    for row in rows:
        row_id = row.get("row_id")
        for field in ALL_MULTI_FIELDS:
            values = split_multi(row.get(field, ""))
            if len(values) != len(set(values)):
                report.add("multi.duplicate", f"{field} contains duplicates", row_id=row_id, details=values)
            if field in NUMERIC_MULTI_FIELDS and values:
                prefix = NUMERIC_MULTI_FIELDS[field]
                try:
                    numbers = [int(value[len(prefix):]) for value in values]
                except ValueError:
                    continue
                if numbers != sorted(numbers):
                    report.add("multi.order", f"{field} is not numerically ordered", row_id=row_id, details=values)
    expected = {
        "d_refs": {f"D{index}" for index in range(1, 10)},
        "rl_refs": {f"RL{index}" for index in range(1, 10)},
        "r_refs": {f"R{index}" for index in range(1, 9)},
        "f_refs": {f"F{index}" for index in range(1, 7)},
        "a_refs": {f"A{index}" for index in range(1, 5)},
        "m_level_refs": {f"M{index}" for index in range(0, 7)},
    }
    coverage: dict[str, list[str]] = {}
    for field, required in expected.items():
        observed = {
            item
            for row in rows
            if materialization_status(row) != "superseded"
            for item in split_multi(row.get(field, ""))
        }
        coverage[field] = sorted(observed, key=natural_ref_key)
        missing = sorted(required - observed, key=natural_ref_key)
        if missing:
            report.add("coverage.taxonomy", f"{field} lacks required coverage", details=missing)
    a5_rows = [row.get("row_id", "") for row in rows if "A5" in split_multi(row.get("a_refs", ""))]
    if a5_rows:
        report.add("science.a5.forbidden", "the package may not claim A5", details=a5_rows)
    f6_scope_errors = []
    for row in rows:
        if "F6" in split_multi(row.get("f_refs", "")):
            invalid = set(split_multi(row.get("a_refs", ""))) - {"A3", "A4"}
            if invalid:
                f6_scope_errors.append({"row_id": row.get("row_id"), "invalid": sorted(invalid)})
    if f6_scope_errors:
        report.add("science.f6.scope", "F6 may use only A3 and A4", details=f6_scope_errors)
    report.metrics["taxonomy_coverage"] = coverage


def natural_ref_key(value: str) -> tuple[str, int]:
    match = re.fullmatch(r"([A-Z]+)([0-9]+)", value)
    return (match.group(1), int(match.group(2))) if match else (value, -1)


def find_output_root(package_root: Path) -> Path | None:
    for candidate in (package_root, *package_root.parents):
        if candidate.name == "output":
            return candidate
    return None


def scan_external_decisions(package_root: Path) -> dict[str, list[str]]:
    output_root = find_output_root(package_root)
    found: dict[str, list[str]] = defaultdict(list)
    if output_root is None:
        return {}
    for task_number in range(18):
        task_dir = output_root / f"t{task_number:02d}"
        if not task_dir.is_dir():
            continue
        for path in sorted(task_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".json", ".md", ".txt"}:
                continue
            if package_root == path or package_root in path.parents:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for decision_id in sorted(set(DECISION_SCAN_RE.findall(text))):
                found[decision_id].append(path.relative_to(output_root).as_posix())
    return dict(found)


def mapped_source_status(raw_status: str) -> str:
    lowered = raw_status.lower()
    if lowered.startswith("verified"):
        return "verified"
    if "pending" in lowered:
        return "pending"
    return "failed"


def mapped_decision_status(raw_status: str, *, external: bool = False) -> str:
    if external:
        return "approved"
    lowered = raw_status.lower()
    if lowered.startswith("approved") or "approved" in lowered:
        return "approved"
    if "superseded" in lowered:
        return "superseded"
    if "reject" in lowered:
        return "rejected"
    return "pending"


def validate_references(
    rows: list[dict[str, str]],
    provenance: dict[str, Any],
    sources: dict[str, Any],
    report: Report,
    package_root: Path,
    exact_header: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    evidence = {item.get("id"): item for item in sources.get("evidence_units", []) if item.get("id")}
    source_works = {item.get("id"): item for item in sources.get("source_works", []) if item.get("id")}
    claims = {item.get("claim_id"): item for item in provenance.get("scientific_claims", []) if item.get("claim_id")}
    decisions = {item.get("id"): item for item in provenance.get("decisions", []) if item.get("id")}
    open_decisions = {item.get("id"): item for item in provenance.get("open_decisions", []) if item.get("id")}
    # A migrated standalone package must import every operative decision into
    # PROVENANCE.  Legacy diagnostics may additionally locate prior task records.
    external = {} if exact_header else scan_external_decisions(package_root)
    unresolved_evidence: set[str] = set()
    unresolved_decisions: set[str] = set()
    unresolved_claims: set[str] = set()
    unapproved_decisions: set[str] = set()
    for row in rows:
        row_id = row.get("row_id")
        support_type = row.get("support_ref_type", "")
        support_id = row.get("support_ref_id", "")
        if support_type and not row.get("support_locator_or_decision", ""):
            report.add("reference.locator.empty", "support reference needs a locator", row_id=row_id)
        if support_type == "evidence_unit":
            expected_locator = f"SOURCES.json#{support_id}"
            if exact_header and row.get("support_locator_or_decision") != expected_locator:
                report.add(
                    "reference.evidence.locator_mismatch",
                    "evidence support locator must resolve exactly to its SOURCES.json evidence unit",
                    row_id=row_id,
                    details={"actual": row.get("support_locator_or_decision"), "expected": expected_locator},
                )
            record = evidence.get(support_id)
            if record is None:
                unresolved_evidence.add(support_id)
            else:
                mapped = mapped_source_status(str(record.get("verification_status", "")))
                if exact_header and row.get("source_verification_status") != mapped:
                    report.add(
                        "reference.evidence.status_mismatch",
                        "source_verification_status does not map to SOURCES.json",
                        row_id=row_id,
                        details={"ledger": row.get("source_verification_status"), "registry": record.get("verification_status"), "expected": mapped},
                    )
                if mapped != "verified" and materialization_status(row) in MATERIALIZED:
                    report.add("reference.evidence.not_verified", "active derivation uses unverified evidence", row_id=row_id, details=support_id)
        elif support_type == "approved_decision":
            expected_locator = f"PROVENANCE.json#decisions/{support_id}"
            if exact_header and row.get("support_locator_or_decision") != expected_locator:
                report.add(
                    "reference.decision.locator_mismatch",
                    "decision support locator must resolve exactly to its PROVENANCE.json decision",
                    row_id=row_id,
                    details={"actual": row.get("support_locator_or_decision"), "expected": expected_locator},
                )
            status = resolve_decision(support_id, decisions, open_decisions, external)
            if status is None:
                unresolved_decisions.add(support_id)
            elif status != "approved":
                unapproved_decisions.add(support_id)
            if exact_header and support_id not in split_multi(row.get("approval_refs", "")):
                report.add("reference.decision.missing_approval_ref", "decision support must also appear in approval_refs", row_id=row_id, details=support_id)
        claim_id = row.get("claim_ref", "")
        if claim_id and claim_id not in claims:
            unresolved_claims.add(claim_id)
        row_decision_states: list[str] = []
        for decision_id in split_multi(row.get("approval_refs", "")):
            if not DECISION_RE.fullmatch(decision_id):
                unresolved_decisions.add(decision_id)
                continue
            status = resolve_decision(decision_id, decisions, open_decisions, external)
            if status is None:
                unresolved_decisions.add(decision_id)
            elif status != "approved":
                if materialization_status(row) != "blocked":
                    unapproved_decisions.add(decision_id)
                if exact_header and row.get("decision_approval_status") != status:
                    report.add(
                        "reference.decision.status_mismatch",
                        "decision_approval_status does not map to the decision registry",
                        row_id=row_id,
                        details={"decision_id": decision_id, "expected": status, "ledger": row.get("decision_approval_status")},
                    )
            if status is not None:
                row_decision_states.append(status)
        if exact_header:
            expected_decision_status = "not_required" if not row_decision_states else aggregate_decision_status(row_decision_states)
            if row.get("decision_approval_status") != expected_decision_status:
                report.add(
                    "reference.decision.aggregate_status_mismatch",
                    "decision_approval_status does not summarize approval_refs",
                    row_id=row_id,
                    details={"expected": expected_decision_status, "ledger": row.get("decision_approval_status")},
                )
    if unresolved_evidence:
        report.add("reference.evidence.unresolved", "evidence units do not resolve", details=sorted(unresolved_evidence))
    if unresolved_decisions:
        report.add("reference.decision.unresolved", "T00-T17 decisions do not resolve", details=sorted(unresolved_decisions))
    if unapproved_decisions:
        report.add("reference.decision.not_approved", "active derivations use decisions that are not approved", details=sorted(unapproved_decisions))
    if unresolved_claims:
        report.add("reference.claim.unresolved", "claim references do not resolve", details=sorted(unresolved_claims))
    report.metrics["reference_counts"] = {
        "approval_ids": len({item for row in rows for item in split_multi(row.get("approval_refs", ""))}),
        "claim_ids": len({row.get("claim_ref") for row in rows if row.get("claim_ref")}),
        "decision_support_ids": len({row.get("support_ref_id") for row in rows if row.get("support_ref_type") == "approved_decision"}),
        "evidence_support_ids": len({row.get("support_ref_id") for row in rows if row.get("support_ref_type") == "evidence_unit"}),
    }
    return evidence, source_works


def resolve_decision(
    decision_id: str,
    decisions: dict[str, dict[str, Any]],
    open_decisions: dict[str, dict[str, Any]],
    external: dict[str, list[str]],
) -> str | None:
    if decision_id in decisions:
        return mapped_decision_status(str(decisions[decision_id].get("status", "")))
    if decision_id in open_decisions:
        return mapped_decision_status(str(open_decisions[decision_id].get("status", "")))
    if decision_id in external:
        return mapped_decision_status("approved_external_record", external=True)
    return None


def aggregate_decision_status(statuses: list[str]) -> str:
    for status in ("rejected", "pending", "superseded"):
        if status in statuses:
            return status
    return "approved"


def declared_paths(provenance: dict[str, Any], report: Report) -> dict[str, str]:
    result: dict[str, str] = {}
    conflicts: list[dict[str, str]] = []
    for item in provenance.get("planned_tree", []):
        add_declared_path(result, conflicts, item.get("path"), item.get("origin_class"), "planned_tree")
    for file_set in provenance.get("planned_file_sets", []):
        for path in file_set.get("paths", []):
            add_declared_path(result, conflicts, path, file_set.get("origin_class"), file_set.get("set_id", "planned_file_set"))
    if conflicts:
        report.add("paths.origin.conflict", "PROVENANCE declares conflicting origin classes", details=conflicts)
    return result


def add_declared_path(
    result: dict[str, str], conflicts: list[dict[str, str]], path: Any, origin: Any, source: str
) -> None:
    if not isinstance(path, str) or not isinstance(origin, str):
        return
    if path in result and result[path] != origin:
        conflicts.append({"path": path, "first": result[path], "second": origin, "source": source})
    result[path] = origin


def validate_paths_and_materialization(
    rows: list[dict[str, str]],
    provenance: dict[str, Any],
    parsed_values: dict[str, Any],
    report: Report,
    package_root: Path,
    exact_header: bool,
    post_run_register: dict[str, dict[str, Any]],
) -> None:
    declared = declared_paths(provenance, report)
    targeted = {row.get("target_path", "") for row in rows if materialization_status(row) != "superseded"}
    undeclared = sorted(targeted - set(declared))
    uncovered = sorted(set(declared) - targeted)
    if undeclared:
        report.add("paths.target.undeclared", "ledger targets are not declared by PROVENANCE", details=undeclared)
    if uncovered:
        report.add(
            "paths.coverage.incomplete",
            "ledger does not cover 100% of planned_tree plus planned_file_sets",
            details={"count": len(uncovered), "paths": uncovered},
        )
    if len(declared) != 159:
        report.add(
            "paths.declared_count",
            "the frozen T03 package contract must declare exactly 159 internal paths",
            details={"actual": len(declared), "expected": 159},
        )
    origin_errors: list[dict[str, str]] = []
    for row in rows:
        path = row.get("target_path", "")
        if path in declared and row.get("file_origin_class") != declared[path]:
            origin_errors.append({
                "row_id": row.get("row_id", ""),
                "path": path,
                "ledger": row.get("file_origin_class", ""),
                "provenance": declared[path],
            })
    if origin_errors:
        report.add("paths.origin.mismatch", "row origin differs from PROVENANCE", details=origin_errors)
    dist_targets = sorted(path for path in targeted if path == "dist" or path.startswith("dist/"))
    external_dist = {item.get("path") for item in provenance.get("external_distribution_tree", [])}
    leaked_external = sorted(path for path in targeted if path in external_dist)
    if dist_targets or leaked_external:
        report.add("paths.dist.forbidden", "internal ledger must not target external dist artifacts", details=sorted(set(dist_targets + leaked_external)))
    internal_dist = package_root / "dist"
    if internal_dist.exists() and any(path.is_file() for path in internal_dist.rglob("*")):
        report.add("paths.dist.present", "dist files must remain outside the package root")
    if exact_header:
        json_paths_with_atomic_pointers = {
            row.get("target_path", "")
            for row in rows
            if materialization_status(row) in MATERIALIZED
            and row.get("target_path", "").lower().endswith(".json")
            and (row.get("target_locator", "") == "" or row.get("target_locator", "").startswith("/"))
        }
        checked_targets: set[tuple[str, str]] = set()
        for row in rows:
            path_text = row.get("target_path", "")
            destination = package_root / path_text
            status = materialization_status(row)
            if status in MATERIALIZED:
                if not destination.is_file():
                    report.add("materialization.file.missing", "materialized target does not exist", row_id=row.get("row_id"), details=path_text)
                    continue
                key = (path_text, row.get("target_locator", ""))
                if key not in checked_targets and destination.suffix.lower() == ".json":
                    checked_targets.add(key)
                    if row.get("target_locator") == "@materialization-recipe":
                        continue
                    if row.get("target_locator") == "@document" and path_text in json_paths_with_atomic_pointers:
                        continue
                    verify_materialized_json_target(row, destination, parsed_values, report)
            elif status in {"planned", "blocked"} and destination.is_file():
                registered = post_run_register.get(path_text)
                if not registered:
                    report.add("materialization.file.premature", "non-materialized target already exists without a downstream T03.3-9 attestation", row_id=row.get("row_id"), details=path_text)
                elif (
                    registered.get("bytes") != destination.stat().st_size
                    or registered.get("sha256") != sha256_bytes(destination.read_bytes())
                ):
                    report.add("materialization.file.fixity", "downstream materialization attestation differs from the physical target", row_id=row.get("row_id"), details=path_text)
    report.metrics["path_coverage"] = {
        "declared": len(declared),
        "targeted": len(targeted),
        "uncovered": len(uncovered),
        "undeclared": len(undeclared),
    }
    if exact_header:
        validate_spec_layer_documents(rows, parsed_values, report, package_root)


def verify_materialized_json_target(
    row: dict[str, str], destination: Path, parsed_values: dict[str, Any], report: Report
) -> None:
    try:
        document = json.loads(destination.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJSONKey) as exc:
        report.add("materialization.json.invalid", f"materialized JSON cannot be read: {exc}", row_id=row.get("row_id"))
        return
    locator = row.get("target_locator", "")
    expected = parsed_values.get(row.get("row_id", ""))
    try:
        actual = document if locator == "@document" else resolve_json_pointer(document, locator)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        report.add("materialization.locator.unresolved", f"target locator does not resolve: {exc}", row_id=row.get("row_id"))
        return
    if actual != expected:
        report.add("materialization.value.mismatch", "materialized value differs from ledger", row_id=row.get("row_id"), details={"actual": actual, "expected": expected})


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("semantic anchor cannot be resolved as JSON Pointer")
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


_POINTER_MISSING = object()


def assign_json_pointer(document: dict[str, Any], pointer: str, value: Any) -> None:
    if not pointer.startswith("/"):
        raise ValueError(f"not a JSON Pointer: {pointer!r}")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    current: Any = document
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        next_is_index = not last and parts[index + 1].isdigit()
        if isinstance(current, dict):
            if last:
                existing = current.get(part, _POINTER_MISSING)
                if existing is not _POINTER_MISSING and existing != value:
                    raise ValueError(f"contradictory value at {pointer}")
                current[part] = value
                continue
            required_type = list if next_is_index else dict
            if part not in current:
                current[part] = required_type()
            elif not isinstance(current[part], required_type):
                raise ValueError(f"container type conflict at /{'/'.join(parts[:index + 1])}")
            current = current[part]
            continue
        if isinstance(current, list):
            if not part.isdigit():
                raise ValueError(f"named child {part!r} under an array at {pointer}")
            position = int(part)
            while len(current) <= position:
                current.append(_POINTER_MISSING)
            if last:
                existing = current[position]
                if existing is not _POINTER_MISSING and existing != value:
                    raise ValueError(f"contradictory value at {pointer}")
                current[position] = value
                continue
            required_type = list if next_is_index else dict
            if current[position] is _POINTER_MISSING:
                current[position] = required_type()
            elif not isinstance(current[position], required_type):
                raise ValueError(f"container type conflict at /{'/'.join(parts[:index + 1])}")
            current = current[position]
            continue
        raise ValueError(f"scalar parent while assigning {pointer}")


def reject_json_pointer_holes(value: Any, pointer: str = "") -> None:
    if isinstance(value, list):
        for index, child in enumerate(value):
            if child is _POINTER_MISSING:
                raise ValueError(f"array hole at {pointer}/{index}")
            reject_json_pointer_holes(child, f"{pointer}/{index}")
    elif isinstance(value, dict):
        for key, child in value.items():
            reject_json_pointer_holes(child, f"{pointer}/{key}")


def validate_spec_layer_documents(
    rows: list[dict[str, str]],
    parsed_values: dict[str, Any],
    report: Report,
    package_root: Path,
) -> None:
    errors: list[dict[str, Any]] = []
    checked_paths: set[str] = set()
    for path in sorted(CLOSED_JSON_PROJECTION_PATHS):
        path_rows = [row for row in rows if active(row) and row.get("target_path") == path]
        if not path_rows:
            errors.append({"path": path, "reason": "no_active_derivations"})
            continue
        locator_values: dict[str, Any] = {}
        try:
            for row in path_rows:
                locator = row.get("target_locator", "")
                value = parsed_values.get(row.get("row_id", ""))
                if locator in locator_values and locator_values[locator] != value:
                    raise ValueError(f"contradictory active values at {locator}")
                locator_values[locator] = value
            document: dict[str, Any] = {}
            for locator in sorted(
                locator_values,
                key=lambda item: (len(item.split("/")), item.encode("utf-8")),
            ):
                assign_json_pointer(document, locator, locator_values[locator])
            reject_json_pointer_holes(document)
        except (TypeError, ValueError) as exc:
            errors.append({"path": path, "reason": "projection_not_materializable", "detail": str(exc)})
            continue
        statuses = {materialization_status(row) for row in path_rows}
        if statuses.isdisjoint(MATERIALIZED):
            continue
        if not statuses.issubset(MATERIALIZED):
            errors.append({"path": path, "reason": "partial_materialization", "statuses": sorted(statuses)})
            continue
        destination = package_root / path
        if not destination.is_file():
            continue
        expected_bytes = (
            json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        actual_bytes = destination.read_bytes()
        if actual_bytes != expected_bytes:
            errors.append({
                "path": path,
                "reason": "noncanonical_or_unregistered_content",
                "actual_sha256": sha256_bytes(actual_bytes),
                "expected_sha256": sha256_bytes(expected_bytes),
            })
            continue
        checked_paths.add(path)
    if errors:
        report.add(
            "materialization.closed_json_projection",
            "materialized specification and configuration files must be exact canonical projections of their active ledger atoms",
            details=errors,
        )
    report.metrics["spec_layer_documents"] = {
        "declared": len(SPEC_LAYER_PATHS),
        "materialized_and_exact": len(checked_paths & SPEC_LAYER_PATHS),
        "projection_errors": sum(1 for item in errors if item.get("path") in SPEC_LAYER_PATHS),
    }
    report.metrics["closed_json_documents"] = {
        "configuration_declared": len(CONFIGURATION_LAYER_PATHS),
        "configuration_materialized_and_exact": len(
            checked_paths & CONFIGURATION_LAYER_PATHS
        ),
        "declared": len(CLOSED_JSON_PROJECTION_PATHS),
        "materialized_and_exact": len(checked_paths),
        "projection_errors": len(errors),
    }


def validate_contradictions(rows: list[dict[str, str]], report: Report) -> None:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if active(row):
            grouped[(row.get("target_path", ""), row.get("target_locator", ""))].append(row)
    conflicts = []
    for (path, locator), group in grouped.items():
        values = {(row.get("target_field", ""), row.get("target_value", "")) for row in group}
        if len(values) > 1:
            conflicts.append({
                "path": path,
                "locator": locator,
                "derivations": sorted({row.get("derivation_id", "") for row in group}),
                "values": sorted([{"field": field, "value": value} for field, value in values], key=lambda item: (item["field"], item["value"])),
            })
    if conflicts:
        report.add("targets.active_contradiction", "active target locators have contradictory values", details=conflicts)


def recursive_keys(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            result.add(key)
            result.update(recursive_keys(item))
    elif isinstance(value, list):
        for item in value:
            result.update(recursive_keys(item))
    return result


def validate_published_purity(
    rows: list[dict[str, str]],
    parsed_values: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    source_works: dict[str, dict[str, Any]],
    report: Report,
) -> None:
    violations: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("target_path", "").startswith("spec/published/"):
            continue
        reasons: list[str] = []
        evidence_record = evidence.get(row.get("support_ref_id", ""), {})
        source_record = source_works.get(evidence_record.get("source_work_ref"), {})
        negative_edge = row.get("support_level") == "does_not_support"
        source_is_negative = (
            evidence_record.get("support_level") == "does_not_support"
            or source_record.get("support_level") == "does_not_support"
        )
        if negative_edge:
            if row.get("transformation_type") != "preserve_and_exclude":
                reasons.append("negative_edge_not_preserve_and_exclude")
            if row.get("claim_provenance_class") != "excluded_from_execution":
                reasons.append("negative_edge_not_excluded_claim")
            if materialization_status(row) != "excluded":
                reasons.append("negative_edge_is_active_evidence")
            if reasons:
                violations.append({"derivation_id": row.get("derivation_id"), "row_id": row.get("row_id"), "reasons": reasons})
            # A does_not_support edge is a negative audit record.  It is never
            # evaluated as affirmative published content.
            continue
        if not active(row):
            continue
        if source_is_negative:
            reasons.append("negative_source_used_as_positive_evidence")
        if row.get("file_origin_class") != "reconstructed_from_published_specification":
            reasons.append("wrong_file_origin_class")
        if row.get("support_ref_type") != "evidence_unit":
            reasons.append("non_evidence_support")
        else:
            if source_record.get("source_class") not in PUBLISHED_SOURCE_CLASSES:
                reasons.append("support_is_not_published_source")
        if row.get("claim_provenance_class") != "explicit_source":
            reasons.append("claim_is_not_explicit_source")
        if row.get("transformation_type") not in {"verbatim_short_fragment", "paraphrase", "metadata_transcription"}:
            reasons.append("doctoral_or_executable_transformation")
        if split_multi(row.get("approval_refs", "")):
            reasons.append("doctoral_approval_attached_to_published_layer")
        value = parsed_values.get(row.get("row_id", ""))
        forbidden_keys = sorted(recursive_keys(value) & PUBLISHED_FORBIDDEN_KEYS)
        if forbidden_keys:
            reasons.append("forbidden_keys:" + ",".join(forbidden_keys))
        lowered = row.get("target_value", "").lower()
        forbidden_text = sorted(text for text in PUBLISHED_FORBIDDEN_TEXT if text in lowered)
        if forbidden_text:
            reasons.append("thesis_only_text:" + ",".join(forbidden_text))
        if reasons:
            violations.append({"derivation_id": row.get("derivation_id"), "row_id": row.get("row_id"), "reasons": reasons})
    if violations:
        report.add("science.published.impure", "spec/published mixes source transcription with doctoral or executable content", details=violations)


def validate_audit_boundaries(
    rows: list[dict[str, str]],
    parsed_values: dict[str, Any],
    provenance: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    report: Report,
) -> None:
    rs_decisions = [item for item in provenance.get("decisions", []) if item.get("id") == "T03-RS-005"]
    if len(rs_decisions) != 1 or mapped_decision_status(str(rs_decisions[0].get("status", ""))) != "approved":
        report.add(
            "audit.rs005.contract",
            "M1-M3 require exactly one approved T03-RS-005 decision",
            details={"records": len(rs_decisions)},
        )
        return
    rs = rs_decisions[0].get("decision", {})
    boundary = rs.get("boundary_terminology_adapter_contract", {})
    exact_sources = {
        "SRC-2018A-COGNITION-APPRAISAL": {
            "producer": "General Appraisal",
            "integration_boundary": "Emotional Filter",
        },
        "SRC-2018B-FLEXIBLE-SCHEME": {
            "producer": "General Appraisal (GA)",
            "integration_boundary": "Emotion Filter (EF)",
        },
    }
    exact_canonical = {"producer": "general_appraisal", "integration_boundary": "emotional_filter"}
    if (
        set(boundary) != {
            "canonical_doctoral_terms",
            "contract_layer",
            "failure_policy",
            "match_rule",
            "published_layer_mutation",
            "scope",
            "source_specific_adapters",
        }
        or boundary.get("contract_layer") != "decisions"
        or boundary.get("scope") != "source_specific_exact_lexemes"
        or boundary.get("source_specific_adapters") != exact_sources
        or boundary.get("canonical_doctoral_terms") != exact_canonical
        or boundary.get("published_layer_mutation") is not False
        or boundary.get("failure_policy") != "fail_closed_on_unknown_source_or_non_exact_lexeme"
    ):
        report.add("audit.m1.decision_contract", "M1 source-specific boundary terminology contract is not exact")
    evidence_source_contract = {
        "EV-2018A-GA-EF": "SRC-2018A-COGNITION-APPRAISAL",
        "EV-2018B-GA-EF": "SRC-2018B-FLEXIBLE-SCHEME",
        "EV-2018A-SADNESS": "SRC-2018A-COGNITION-APPRAISAL",
        "EV-2018B-RULES": "SRC-2018B-FLEXIBLE-SCHEME",
    }
    wrong_evidence_sources = {
        evidence_id: evidence.get(evidence_id, {}).get("source_work_ref")
        for evidence_id, source_id in evidence_source_contract.items()
        if evidence.get(evidence_id, {}).get("source_work_ref") != source_id
        or mapped_source_status(str(evidence.get(evidence_id, {}).get("verification_status", ""))) != "verified"
    }
    if wrong_evidence_sources:
        report.add(
            "audit.m1_m3.evidence_source_identity",
            "boundary and antecedent evidence units must resolve to their exact verified 2018a/2018b source works",
            details=wrong_evidence_sources,
        )

    published_path = "spec/published/ga_ef_boundary_2018ab.json"
    exact_published: dict[str, tuple[str, str]] = {
        "/sources/2018a/producer": ("General Appraisal", "EV-2018A-GA-EF"),
        "/sources/2018a/integration_boundary": ("Emotional Filter", "EV-2018A-GA-EF"),
        "/sources/2018b/producer": ("General Appraisal (GA)", "EV-2018B-GA-EF"),
        "/sources/2018b/integration_boundary": ("Emotion Filter (EF)", "EV-2018B-GA-EF"),
    }
    published_rows = [row for row in rows if active(row) and row.get("target_path") == published_path]
    published_errors: list[dict[str, Any]] = []
    if {row.get("target_locator", "") for row in published_rows} != set(exact_published):
        published_errors.append({
            "reason": "locator_set_mismatch",
            "actual": sorted({row.get("target_locator", "") for row in published_rows}),
            "expected": sorted(exact_published),
        })
    for locator, (value, evidence_id) in exact_published.items():
        matches = [row for row in published_rows if row.get("target_locator") == locator]
        if len(matches) != 1:
            published_errors.append({"locator": locator, "reason": "row_cardinality", "actual": len(matches), "expected": 1})
            continue
        row = matches[0]
        if (
            parsed_values.get(row.get("row_id", "")) != value
            or support_edge(row) != evidence_edge(evidence_id)
            or row.get("transformation_type") != "metadata_transcription"
            or row.get("claim_provenance_class") != "explicit_source"
            or row.get("claim_ref") != "CLM-GA-EF-001"
            or split_multi(row.get("approval_refs", ""))
        ):
            published_errors.append({"locator": locator, "reason": "lexeme_or_evidence_boundary_mismatch", "row_id": row.get("row_id")})
    def nested_strings(value: Any) -> Iterable[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, child in value.items():
                yield str(key)
                yield from nested_strings(child)
        elif isinstance(value, list):
            for child in value:
                yield from nested_strings(child)

    canonical_terms = set(exact_canonical.values())
    if any(
        active(row)
        and row.get("target_path", "").startswith("spec/published/")
        and canonical_terms.intersection(nested_strings(parsed_values.get(row.get("row_id", ""))))
        for row in rows
    ):
        published_errors.append({"reason": "canonical_boundary_term_leaked_into_published_layer"})
    if published_errors:
        report.add(
            "audit.m1.published_boundary",
            "published GA/EF terminology must preserve exactly four source-specific lexemes with direct source evidence",
            details=published_errors,
        )

    decisions_path = "spec/decisions/engineering_v1.1.0.json"
    canonical_errors: list[dict[str, Any]] = []
    expected_canonical_supports = {
        evidence_edge("EV-2018A-GA-EF", "interpreted"),
        evidence_edge("EV-2018B-GA-EF", "interpreted"),
        decision_edge("T03-RS-005"),
    }
    for field, value in exact_canonical.items():
        locator = f"/published_boundary_adapter/canonical/{field}"
        matches = [row for row in rows if active(row) and row.get("target_path") == decisions_path and row.get("target_locator") == locator]
        supports = {support_edge(row) for row in matches}
        values = {parsed_values.get(row.get("row_id", "")) for row in matches}
        if (
            values != {value}
            or supports != expected_canonical_supports
            or len(matches) != len(expected_canonical_supports)
            or any(row.get("transformation_type") != "lexical_adapter" for row in matches)
        ):
            canonical_errors.append({"locator": locator, "reason": "canonical_adapter_value_or_support_mismatch"})
    evidence_for_source = {
        "SRC-2018A-COGNITION-APPRAISAL": "EV-2018A-GA-EF",
        "SRC-2018B-FLEXIBLE-SCHEME": "EV-2018B-GA-EF",
    }
    for source_id, value in exact_sources.items():
        locator = f"/published_boundary_adapter/source_specific_adapters/{source_id}"
        matches = [row for row in rows if active(row) and row.get("target_path") == decisions_path and row.get("target_locator") == locator]
        supports = {support_edge(row) for row in matches}
        expected_supports = {
            evidence_edge(evidence_for_source[source_id], "interpreted"),
            decision_edge("T03-RS-005"),
        }
        encoded_values = {
            json.dumps(parsed_values.get(row.get("row_id", "")), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for row in matches
        }
        if (
            encoded_values != {json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}
            or supports != expected_supports
            or len(matches) != len(expected_supports)
            or any(row.get("transformation_type") != "lexical_adapter" for row in matches)
        ):
            canonical_errors.append({"locator": locator, "reason": "source_specific_adapter_value_or_support_mismatch"})
    boundary_policy = {key: value for key, value in boundary.items() if key not in {"canonical_doctoral_terms", "source_specific_adapters"}}
    policy_locator = "/published_boundary_adapter/policy"
    policy_rows = [row for row in rows if active(row) and row.get("target_path") == decisions_path and row.get("target_locator") == policy_locator]
    policy_values = {
        json.dumps(parsed_values.get(row.get("row_id", "")), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in policy_rows
    }
    if policy_values != {json.dumps(boundary_policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}:
        canonical_errors.append({"locator": policy_locator, "reason": "policy_value_mismatch"})
    policy_supports = {support_edge(row) for row in policy_rows}
    if policy_supports != {decision_edge("T03-RS-005")} or len(policy_rows) != 1:
        canonical_errors.append({"locator": policy_locator, "reason": "policy_support_mismatch"})
    expected_adapter_locators = {
        "/published_boundary_adapter/canonical/producer",
        "/published_boundary_adapter/canonical/integration_boundary",
        "/published_boundary_adapter/source_specific_adapters/SRC-2018A-COGNITION-APPRAISAL",
        "/published_boundary_adapter/source_specific_adapters/SRC-2018B-FLEXIBLE-SCHEME",
        "/published_boundary_adapter/policy",
    }
    adapter_rows = [
        row for row in rows
        if active(row)
        and row.get("target_path") == decisions_path
        and (
            row.get("target_locator", "") == "/published_boundary_adapter"
            or row.get("target_locator", "").startswith("/published_boundary_adapter/")
        )
    ]
    adapter_locators = {row.get("target_locator", "") for row in adapter_rows}
    if adapter_locators != expected_adapter_locators:
        canonical_errors.append({
            "reason": "published_boundary_adapter_namespace_not_closed",
            "missing": sorted(expected_adapter_locators - adapter_locators),
            "extra": sorted(adapter_locators - expected_adapter_locators),
        })
    wrong_adapter_claims = [
        row.get("row_id", "") for row in adapter_rows
        if row.get("claim_ref", "")
        or row.get("claim_provenance_class") != "generated_for_doctoral_instance"
    ]
    if wrong_adapter_claims:
        canonical_errors.append({
            "reason": "adapter_decision_rows_inherit_source_claim",
            "row_ids": sorted(wrong_adapter_claims),
        })
    if canonical_errors:
        report.add(
            "audit.m1.canonical_adapter",
            "canonical GA/EF adapters must exist only in the decisions layer with interpreted source context and direct T03-RS-005 authority",
            details=canonical_errors,
        )

    antecedent = rs.get("antecedent_lexeme_adapter_contract", {})
    exact_maps = {
        "SRC-2018A-COGNITION-APPRAISAL": {
            "Desirability(E)": "desirability",
            "Expectedness(E)": "expectedness",
            "Novelty (E)": "novelty",
            "Pleasantness(E)": "pleasure",
            "Goal conduciveness (E)": "goal_conduciveness",
            "Coping potential (E)": "coping_potential",
        },
        "SRC-2018B-FLEXIBLE-SCHEME": {
            "Desirability (E)": "desirability",
            "Expectation (E)": "expectedness",
            "Novelty (E)": "novelty",
            "Pleasure (E)": "pleasure",
            "Goal-conduciveness (E)": "goal_conduciveness",
            "Coping potential (E)": "coping_potential",
        },
    }
    map_errors: list[dict[str, Any]] = []
    if (
        set(antecedent) != {
            "contract_layer",
            "exact_match_required",
            "failure_policy",
            "global_adapter_precedence",
            "preservation_rule",
            "published_layer_mutation",
            "scope",
            "source_specific_maps",
        }
        or antecedent.get("contract_layer") != "decisions"
        or antecedent.get("exact_match_required") is not True
        or antecedent.get("published_layer_mutation") is not False
        or antecedent.get("source_specific_maps") != exact_maps
        or antecedent.get("failure_policy") != "fail_closed_on_unknown_source_missing_mapping_or_non_exact_lexeme"
    ):
        map_errors.append({"reason": "T03_RS_005_antecedent_contract_mismatch"})
    map_evidence = {
        "SRC-2018A-COGNITION-APPRAISAL": "EV-2018A-SADNESS",
        "SRC-2018B-FLEXIBLE-SCHEME": "EV-2018B-RULES",
    }
    for source_id, expected_map in exact_maps.items():
        locator = f"/antecedent_lexeme_adapter/source_specific_maps/{source_id}"
        matches = [row for row in rows if active(row) and row.get("target_path") == decisions_path and row.get("target_locator") == locator]
        supports = {support_edge(row) for row in matches}
        encoded_values = {
            json.dumps(parsed_values.get(row.get("row_id", "")), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for row in matches
        }
        if encoded_values != {json.dumps(expected_map, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}:
            map_errors.append({"locator": locator, "reason": "exact_six_lexeme_map_mismatch"})
        if supports != {
            evidence_edge(map_evidence[source_id], "interpreted"),
            decision_edge("T03-RS-005"),
        } or len(matches) != 2:
            map_errors.append({"locator": locator, "reason": "map_support_boundary_mismatch"})
    antecedent_policy = {key: value for key, value in antecedent.items() if key != "source_specific_maps"}
    antecedent_policy_rows = [
        row for row in rows
        if active(row) and row.get("target_path") == decisions_path and row.get("target_locator") == "/antecedent_lexeme_adapter/policy"
    ]
    antecedent_policy_values = {
        json.dumps(parsed_values.get(row.get("row_id", "")), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in antecedent_policy_rows
    }
    antecedent_policy_supports = {support_edge(row) for row in antecedent_policy_rows}
    if antecedent_policy_values != {json.dumps(antecedent_policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}:
        map_errors.append({"locator": "/antecedent_lexeme_adapter/policy", "reason": "fail_closed_policy_mismatch"})
    if antecedent_policy_supports != {decision_edge("T03-RS-005")} or len(antecedent_policy_rows) != 1:
        map_errors.append({"locator": "/antecedent_lexeme_adapter/policy", "reason": "policy_support_mismatch"})
    expected_antecedent_locators = {
        "/antecedent_lexeme_adapter/source_specific_maps/SRC-2018A-COGNITION-APPRAISAL",
        "/antecedent_lexeme_adapter/source_specific_maps/SRC-2018B-FLEXIBLE-SCHEME",
        "/antecedent_lexeme_adapter/policy",
    }
    actual_antecedent_locators = {
        row.get("target_locator", "")
        for row in rows
        if active(row)
        and row.get("target_path") == decisions_path
        and (
            row.get("target_locator", "") == "/antecedent_lexeme_adapter"
            or row.get("target_locator", "").startswith("/antecedent_lexeme_adapter/")
        )
    }
    if actual_antecedent_locators != expected_antecedent_locators:
        map_errors.append({
            "reason": "antecedent_lexeme_adapter_namespace_not_closed",
            "missing": sorted(expected_antecedent_locators - actual_antecedent_locators),
            "extra": sorted(actual_antecedent_locators - expected_antecedent_locators),
        })
    if map_errors:
        report.add(
            "audit.m3.fail_closed_lexemes",
            "M3 requires two exact source-specific six-lexeme maps, including each source's (E) spelling, and a decision-only fail-closed policy",
            details=map_errors,
        )

    sadness_paths = {
        "tests/fixtures/sadness_2018a_symbolic.json",
        "tests/oracles/sadness_2018a_symbolic.expected.json",
    }
    sadness_rows = [row for row in rows if active(row) and row.get("target_path") in sadness_paths and row.get("target_locator") != "@materialization-recipe"]
    expected_sadness_documents = {
        "tests/fixtures/sadness_2018a_symbolic.json": {
            "$schema": "../../schemas/scenario.schema.json",
            "schema_version": "1.0.0",
            "fixture_id": "sadness_2018a_symbolic",
            "event_context": {"cause_class": "unwanted_event_occurred", "consequence_target": "myself"},
            "fixture_class": "synthetic_symbolic_regression_fixture",
            "numeric_pipeline_input": False,
            "published_symbolic_payload": {
                "Consequence (E)": "myself",
                "Coping potential (E)": "positive",
                "Desirability(E)": "highly undesirable",
                "Expectedness(E)": "expected",
                "Goal conduciveness (E)": "negative",
                "Novelty (E)": "low novelty",
                "Pleasantness(E)": "unpleasant",
            },
            "provenance_refs": ["EV-2018A-SADNESS", "T03-RS-005", "T03-QA-011"],
            "source_rule_ref": "RULE-SADNESS-2018A",
        },
        "tests/oracles/sadness_2018a_symbolic.expected.json": {
            "$schema": "../../schemas/oracle.schema.json",
            "schema_version": "1.0.0",
            "oracle_id": "sadness_2018a_symbolic.expected",
            "fixture_ref": "tests/fixtures/sadness_2018a_symbolic.json",
            "frozen_before_implementation": True,
            "calculation_basis": {
                "execution_profile": "isolated_symbolic_regression",
                "published_rule_ref": "RULE-SADNESS-2018A",
                "source_of_truth": "PROVENANCE.json#decisions/T03-RS-005",
            },
            "expected": {"emotion": "sadness", "match": True, "numeric_pipeline_used": False},
            "oracle_class": "synthetic_symbolic_regression_oracle",
            "provenance_refs": ["EV-2018A-SADNESS", "T03-RS-005", "T03-QA-011"],
            "source_rule_ref": "RULE-SADNESS-2018A",
        },
    }
    sadness_errors: list[dict[str, Any]] = []
    for path, expected_document in expected_sadness_documents.items():
        reconstructed, actual_document = reconstruct_document(rows, parsed_values, path, report)
        if not reconstructed or actual_document != expected_document:
            sadness_errors.append({"path": path, "reason": "isolated_document_not_closed_or_exact"})
    evidence_edges = {
        (row.get("target_path", ""), row.get("target_locator", ""), row.get("support_level", ""))
        for row in sadness_rows
        if row.get("support_ref_type") == "evidence_unit" and row.get("support_ref_id") == "EV-2018A-SADNESS"
    }
    expected_evidence_edges = {
        ("tests/fixtures/sadness_2018a_symbolic.json", "/event_context", "interpreted"),
        ("tests/fixtures/sadness_2018a_symbolic.json", "/published_symbolic_payload", "direct"),
        ("tests/oracles/sadness_2018a_symbolic.expected.json", "/expected/emotion", "direct"),
        ("tests/oracles/sadness_2018a_symbolic.expected.json", "/expected/match", "interpreted"),
    }
    if evidence_edges != expected_evidence_edges:
        sadness_errors.append({
            "reason": "source_evidence_edge_set_mismatch",
            "actual": sorted(evidence_edges),
            "expected": sorted(expected_evidence_edges),
        })
    allowed_nonpublished_direct_atoms = {
        ("tests/fixtures/sadness_2018a_symbolic.json", "/published_symbolic_payload"),
        ("tests/oracles/sadness_2018a_symbolic.expected.json", "/expected/emotion"),
    }
    leaked_direct_edges = [
        {
            "path": row.get("target_path", ""),
            "locator": row.get("target_locator", ""),
            "row_id": row.get("row_id", ""),
        }
        for row in rows
        if active(row)
        and row.get("support_ref_type") == "evidence_unit"
        and row.get("support_ref_id") == "EV-2018A-SADNESS"
        and row.get("support_level") == "direct"
        and not row.get("target_path", "").startswith("spec/published/")
        and (row.get("target_path", ""), row.get("target_locator", "")) not in allowed_nonpublished_direct_atoms
    ]
    if leaked_direct_edges:
        sadness_errors.append({"reason": "direct_source_evidence_leaked_into_technical_atom", "rows": leaked_direct_edges})
    expected_scientific_claim_atoms = {
        ("tests/fixtures/sadness_2018a_symbolic.json", "/event_context"):
            ("CLM-SADNESS-001", "doctoral_inference"),
        ("tests/fixtures/sadness_2018a_symbolic.json", "/published_symbolic_payload"):
            ("CLM-SADNESS-001", "explicit_source"),
        ("tests/oracles/sadness_2018a_symbolic.expected.json", "/expected/emotion"):
            ("CLM-SADNESS-001", "explicit_source"),
        ("tests/oracles/sadness_2018a_symbolic.expected.json", "/expected/match"):
            ("CLM-SADNESS-001", "doctoral_inference"),
    }
    for row in sadness_rows:
        atom = (row.get("target_path", ""), row.get("target_locator", ""))
        expected_claim = expected_scientific_claim_atoms.get(atom)
        if expected_claim is None:
            if (
                row.get("claim_ref", "")
                or row.get("claim_provenance_class") != "generated_for_doctoral_instance"
            ):
                sadness_errors.append({
                    "path": atom[0],
                    "locator": atom[1],
                    "reason": "technical_metadata_inherits_scientific_claim",
                    "row_id": row.get("row_id"),
                })
        elif (
            row.get("claim_ref") != expected_claim[0]
            or row.get("claim_provenance_class") != expected_claim[1]
        ):
            sadness_errors.append({
                "path": atom[0],
                "locator": atom[1],
                "reason": "claim_ref_or_provenance_class_mismatch",
                "expected": {"claim_ref": expected_claim[0], "claim_provenance_class": expected_claim[1]},
                "row_id": row.get("row_id"),
            })
    for path in sorted(sadness_paths):
        locators = {row.get("target_locator", "") for row in sadness_rows if row.get("target_path") == path}
        for locator in sorted(locators):
            atom_rows = [
                row for row in sadness_rows
                if row.get("target_path") == path and row.get("target_locator") == locator
            ]
            expected_edges = {decision_edge("T03-RS-005"), decision_edge("T03-QA-011")}
            source_edge = next(
                (
                    evidence_edge("EV-2018A-SADNESS", level)
                    for edge_path, edge_locator, level in expected_evidence_edges
                    if edge_path == path and edge_locator == locator
                ),
                None,
            )
            if source_edge is not None:
                expected_edges.add(source_edge)
            actual_edges = {support_edge(row) for row in atom_rows}
            if actual_edges != expected_edges or len(atom_rows) != len(expected_edges):
                sadness_errors.append({
                    "path": path,
                    "locator": locator,
                    "reason": "support_graph_not_closed_or_wrong_cardinality",
                    "actual": sorted(actual_edges),
                    "expected": sorted(expected_edges),
                    "row_count": len(atom_rows),
                })
    if sadness_errors:
        report.add(
            "audit.m2.sadness_evidence_boundary",
            "EV-2018A-SADNESS may directly support only the published symbolic payload and expected emotion; context and match are interpreted and technical atoms are decision-derived",
            details=sadness_errors,
        )
    report.metrics["audit_boundaries"] = {
        "m1_published_lexemes": len(exact_published) - len(published_errors),
        "m2_source_edges": len(evidence_edges),
        "m3_source_maps": len(exact_maps) - sum(1 for item in map_errors if item.get("reason") == "exact_six_lexeme_map_mismatch"),
    }


def validate_claim_provenance_boundaries(
    rows: list[dict[str, str]], parsed_values: dict[str, Any], report: Report
) -> None:
    """Enforce source/doctoral/generated claim boundaries at sensitive atoms."""
    errors: list[dict[str, Any]] = []

    def require_atom(
        *,
        derivation_id: str,
        path: str,
        locator: str,
        expected_value: Any,
        expected_edges: set[tuple[str, str, str, str]],
        claim_ref: str,
        claim_class: str,
    ) -> None:
        matches = [
            row for row in rows
            if active(row)
            and row.get("derivation_id") == derivation_id
            and row.get("target_path") == path
            and row.get("target_locator") == locator
        ]
        actual_edges = {support_edge(row) for row in matches}
        actual_values = {
            json.dumps(parsed_values.get(row.get("row_id", "")), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for row in matches
        }
        expected_json = json.dumps(expected_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if (
            actual_edges != expected_edges
            or len(matches) != len(expected_edges)
            or actual_values != {expected_json}
            or any(row.get("claim_ref", "") != claim_ref for row in matches)
            or any(row.get("claim_provenance_class") != claim_class for row in matches)
        ):
            errors.append({
                "reason": "sensitive_atom_contract_mismatch",
                "derivation_id": derivation_id,
                "path": path,
                "locator": locator,
                "actual_edges": sorted(actual_edges),
                "expected_edges": sorted(expected_edges),
                "row_count": len(matches),
            })

    decisions_path = "spec/decisions/engineering_v1.1.0.json"
    require_atom(
        derivation_id="DL-CTX-001",
        path=decisions_path,
        locator="/rule_adapters/sadness/cause_guard",
        expected_value={
            "executable_role": "doctoral_applicability_guard",
            "source_role": "separate_cause_column",
            "source_value": "Unwanted event (E) occurred",
            "target": "event_context.cause_class",
            "target_value": "unwanted_event_occurred",
        },
        expected_edges={evidence_edge("EV-2018A-SADNESS", "interpreted"), decision_edge("T03-RS-005")},
        claim_ref="CLM-SADNESS-001",
        claim_class="doctoral_inference",
    )
    require_atom(
        derivation_id="DL-CTX-002",
        path=decisions_path,
        locator="/rule_adapters/sadness/consequence_binding",
        expected_value={
            "executable_role": "required_context_antecedent",
            "source_field": "Consequence (E)",
            "source_literal": "Consequence (E)",
            "target": "event_context.consequence_target",
            "whitespace_normalization": "approved_optional_space_before_parenthesized_event_marker",
        },
        expected_edges={evidence_edge("EV-2018A-SADNESS", "interpreted"), decision_edge("T03-RS-005")},
        claim_ref="CLM-SADNESS-001",
        claim_class="doctoral_inference",
    )
    generated_decision_atoms = (
        (
            "DL-CTX-003",
            "/rule_adapters/value_label_mapping_policy",
            {"coping_positive_equivalence": None, "implicit_value_label_mapping": False},
        ),
        (
            "DL-RUL-SAD-010",
            "/rules/sadness/execution_policy",
            {
                "execution_profile": "symbolic_regression_only",
                "missing_or_different_antecedent": "no_match",
                "numeric_pipeline_eligible": False,
            },
        ),
        (
            "DL-RUL-ANG-008",
            "/rules/anger/execution_policy",
            {
                "coping_label_source": "doctoral_crisp_partition",
                "evaluation": ["before", "after"],
                "multiple_match": "reject_with_ambiguous_published_subset_diagnostic",
                "profile": "S14_bounded_end_to_end_continuity",
                "protected_labels_source": "synthetic_host_fixture",
                "zero_match": "unclassified_by_published_subset",
            },
        ),
        (
            "DL-RUL-CONFLICT-002",
            "/rules/exclusions/2018b_conflicting_row",
            {
                "execution_status": "excluded_from_execution",
                "reason": "emotion_column_sadness_but_consequent_anger",
                "source_row_ref": "spec/published/rule_anger_2018b.json#/source/conflicting_row",
            },
        ),
    )
    for derivation_id, locator, value in generated_decision_atoms:
        require_atom(
            derivation_id=derivation_id,
            path=decisions_path,
            locator=locator,
            expected_value=value,
            expected_edges={decision_edge("T03-RS-005")},
            claim_ref="",
            claim_class="generated_for_doctoral_instance",
        )

    confidence_atoms = {
        "/factor_state/confidence/domain": ("[0,1]", {decision_edge("T03-CT-009")}, "", "generated_for_doctoral_instance"),
        "/factor_state/confidence/type": ("decimal_string", {decision_edge("T03-CT-009")}, "", "generated_for_doctoral_instance"),
        "/factor_state/confidence/valid_when": (
            "confidence >= 0.5",
            {evidence_edge("EV-THESIS-FACTOR", "interpreted"), decision_edge("T03-CT-009")},
            "REQ-CONF-001",
            "doctoral_inference",
        ),
    }
    confidence_rows = [
        row for row in rows
        if active(row)
        and row.get("target_path") == decisions_path
        and row.get("target_locator", "").startswith("/factor_state/confidence/")
    ]
    if {row.get("target_locator", "") for row in confidence_rows} != set(confidence_atoms):
        errors.append({
            "reason": "factor_confidence_namespace_not_closed",
            "actual": sorted({row.get("target_locator", "") for row in confidence_rows}),
            "expected": sorted(confidence_atoms),
        })
    for locator, (value, edges, claim_ref, claim_class) in confidence_atoms.items():
        atom_rows = [row for row in confidence_rows if row.get("target_locator") == locator]
        actual_edges = {support_edge(row) for row in atom_rows}
        actual_values = {parsed_values.get(row.get("row_id", "")) for row in atom_rows}
        if (
            actual_edges != edges
            or len(atom_rows) != len(edges)
            or actual_values != {value}
            or any(row.get("claim_ref", "") != claim_ref for row in atom_rows)
            or any(row.get("claim_provenance_class") != claim_class for row in atom_rows)
        ):
            errors.append({"reason": "factor_confidence_atom_mismatch", "locator": locator})
    if any(
        active(row)
        and row.get("target_path") == decisions_path
        and row.get("target_locator") == "/factor_state/confidence"
        for row in rows
    ):
        errors.append({"reason": "legacy_composite_factor_confidence_atom_present"})

    # This fail-closed policy is an engineering adapter, not a source claim.
    require_atom(
        derivation_id="DL-LX-SOURCE-MAP-POLICY-001",
        path=decisions_path,
        locator="/antecedent_lexeme_adapter/policy",
        expected_value=next(
            (
                parsed_values.get(row.get("row_id", ""))
                for row in rows
                if active(row)
                and row.get("derivation_id") == "DL-LX-SOURCE-MAP-POLICY-001"
                and row.get("target_locator") == "/antecedent_lexeme_adapter/policy"
            ),
            None,
        ),
        expected_edges={decision_edge("T03-RS-005")},
        claim_ref="",
        claim_class="generated_for_doctoral_instance",
    )

    s14_paths = {
        "scenarios/S14.json": {
            "decision_ids": {"T03-BL-006", "T03-QA-011", "T03-RS-005"},
            "special_locator": "/host_symbolic_payload",
            "expected_locator_count": 8,
        },
        "oracles/S14.expected.json": {
            "decision_ids": {"T03-BL-006", "T03-QA-011", "T03-RP-012", "T03-RS-005"},
            "special_locator": "/expected/classification",
            "expected_locator_count": 18,
        },
    }
    ordinary_atoms = 0
    for path, contract in s14_paths.items():
        path_rows = [
            row for row in rows
            if active(row) and row.get("target_path") == path and row.get("target_locator") != "@materialization-recipe"
        ]
        locators = {row.get("target_locator", "") for row in path_rows}
        if len(locators) != contract["expected_locator_count"] or contract["special_locator"] not in locators:
            errors.append({
                "reason": "S14_atom_set_or_special_locator_mismatch",
                "path": path,
                "actual_count": len(locators),
                "expected_count": contract["expected_locator_count"],
            })
        for locator in sorted(locators):
            atom_rows = [row for row in path_rows if row.get("target_locator") == locator]
            expected_edges = {decision_edge(decision_id) for decision_id in contract["decision_ids"]}
            if locator == contract["special_locator"]:
                expected_edges.add(evidence_edge("EV-2018B-RULES", "interpreted"))
                expected_claim_ref = "CLM-ANGER-001"
                expected_claim_class = "doctoral_inference"
            else:
                ordinary_atoms += 1
                expected_claim_ref = "LIM-EVIDENCE-001"
                expected_claim_class = "generated_for_doctoral_instance"
            actual_edges = {support_edge(row) for row in atom_rows}
            if (
                actual_edges != expected_edges
                or len(atom_rows) != len(expected_edges)
                or any(row.get("claim_ref", "") != expected_claim_ref for row in atom_rows)
                or any(row.get("claim_provenance_class") != expected_claim_class for row in atom_rows)
            ):
                errors.append({
                    "reason": "S14_claim_or_support_boundary_mismatch",
                    "path": path,
                    "locator": locator,
                    "actual_edges": sorted(actual_edges),
                    "expected_edges": sorted(expected_edges),
                })
            if any(
                row.get("support_ref_type") == "evidence_unit" and row.get("support_level") == "direct"
                for row in atom_rows
            ):
                errors.append({"reason": "S14_direct_source_evidence_forbidden", "path": path, "locator": locator})
    if ordinary_atoms != 24:
        errors.append({"reason": "S14_ordinary_atom_count_mismatch", "actual": ordinary_atoms, "expected": 24})

    active_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if active(row):
            active_groups[row.get("derivation_id", "")].append(row)
    orphan_explicit_groups = sorted(
        derivation_id
        for derivation_id, group in active_groups.items()
        if any(row.get("claim_provenance_class") == "explicit_source" for row in group)
        and not any(
            row.get("support_ref_type") == "evidence_unit" and row.get("support_level") == "direct"
            for row in group
        )
    )
    if orphan_explicit_groups:
        errors.append({
            "reason": "explicit_source_group_without_direct_evidence",
            "derivation_ids": orphan_explicit_groups,
        })
    if errors:
        report.add(
            "audit.claim_provenance.boundaries",
            "sensitive decision, confidence and S14 atoms must preserve exact source/doctoral/generated claim boundaries",
            details=errors,
        )
    report.metrics["claim_provenance_boundaries"] = {
        "explicit_source_groups_without_direct_evidence": len(orphan_explicit_groups),
        "S14_ordinary_atoms": ordinary_atoms,
        "sensitive_errors": len(errors),
    }


def validate_bindings(
    rows: list[dict[str, str]],
    parsed_values: dict[str, Any],
    provenance: dict[str, Any],
    report: Report,
) -> None:
    required = {
        "coping_potential": "host.baseline.coping_potential",
        "lambda": "influence.parameters.lambda",
        "z": "factor_state.level",
        "result": "output.coping_potential",
    }
    locator_contract = {
        "spec/bindings/formula_bindings.json": {
            key: f"/binding_map/{key}" for key in required
        },
        "config/resolved_instance.json": {
            key: f"/influence/binding_map/{key}" for key in required
        },
        "src/ifatigue_infra6/model.py": {
            key: f"@binding-{key.replace('_', '-')}" for key in required
        },
    }
    binding_paths = tuple(locator_contract)
    decisions = [item for item in provenance.get("decisions", []) if item.get("id") == "T03-MP-013"]
    decision_contract_errors: list[str] = []
    if len(decisions) != 1 or mapped_decision_status(str(decisions[0].get("status", ""))) != "approved":
        decision_contract_errors.append("T03-MP-013_not_exactly_one_approved_record")
        binding_artifacts: Any = {}
    else:
        binding_artifacts = decisions[0].get("decision", {}).get("binding_artifacts", {})
    expected_artifacts = {
        "binding_map_values": required,
        "input_keys": ["coping_potential", "lambda", "z"],
        "output_key": "result",
        "result_is_input": False,
        "registry": {
            "path": "spec/bindings/formula_bindings.json",
            "locators": locator_contract["spec/bindings/formula_bindings.json"],
        },
        "resolved_config": {
            "path": "config/resolved_instance.json",
            "locators": locator_contract["config/resolved_instance.json"],
        },
        "implementation": {
            "path": "src/ifatigue_infra6/model.py",
            "semantic_anchors": locator_contract["src/ifatigue_infra6/model.py"],
        },
    }
    if isinstance(binding_artifacts, dict):
        for field, expected in expected_artifacts.items():
            actual = binding_artifacts.get(field)
            if field in {"registry", "resolved_config", "implementation"} and isinstance(actual, dict):
                actual = {key: actual.get(key) for key in expected}
            if actual != expected:
                decision_contract_errors.append(f"binding_artifacts.{field}_mismatch")
    else:
        decision_contract_errors.append("binding_artifacts_not_object")
    if decision_contract_errors:
        report.add(
            "science.bindings.decision_contract",
            "T03-MP-013 does not freeze the canonical four-binding route-specific contract",
            details=sorted(set(decision_contract_errors)),
        )
    binding_values: dict[str, dict[str, dict[str, Any]]] = {
        path: {key: {} for key in required}
        for path in binding_paths
    }
    for row in rows:
        path = row.get("target_path", "")
        if not active(row) or path not in binding_values:
            continue
        locator = row.get("target_locator", "")
        value = parsed_values.get(row.get("row_id", ""))
        matches = [key for key, expected_locator in locator_contract[path].items() if locator == expected_locator]
        if matches:
            binding_values[path][matches[0]][row.get("target_value", "")] = value
    prohibited_result_inputs = sorted(
        {
            (row.get("target_path", ""), row.get("target_locator", ""), row.get("row_id", ""))
            for row in rows
            if active(row)
            and row.get("target_path", "") in binding_paths
            and re.search(r"(?:^|/)input_bindings/result$", row.get("target_locator", ""))
        }
    )
    if prohibited_result_inputs:
        report.add(
            "science.bindings.result_as_input",
            "result is the sole output binding and must never appear under input_bindings",
            details=[{"path": path, "locator": locator, "row_id": row_id} for path, locator, row_id in prohibited_result_inputs],
        )
    missing_or_wrong: dict[str, dict[str, Any]] = {}
    for path in binding_paths:
        path_errors: dict[str, Any] = {}
        for key, expected in required.items():
            values = binding_values[path][key]
            actual = [values[item] for item in sorted(values)]
            if actual != [expected]:
                path_errors[key] = {
                    "actual": actual,
                    "expected": expected,
                    "required_locator": locator_contract[path][key],
                }
        if path_errors:
            missing_or_wrong[path] = path_errors
    if missing_or_wrong:
        report.add(
            "science.bindings.incomplete",
            "canonical formula bindings are absent, ambiguous or inconsistently propagated",
            details=missing_or_wrong,
        )
    report.metrics["binding_contract"] = {
        "canonical_path": binding_paths[0],
        "propagation_paths": list(binding_paths[1:]),
        "required_bindings": len(required),
        "required_locations": len(required) * len(binding_paths),
        "valid_paths": len(binding_paths) - len(missing_or_wrong),
    }


def validate_resolution_documents(
    rows: list[dict[str, str]],
    parsed_values: dict[str, Any],
    provenance: dict[str, Any],
    report: Report,
    package_root: Path,
) -> None:
    """Independently verify the authored registry and one-way resolved config."""
    relative_paths = [
        "spec/published/host_appraisal_2018a.json",
        "spec/published/ga_ef_boundary_2018ab.json",
        "spec/published/rule_sadness_2018a.json",
        "spec/published/rule_anger_2018b.json",
        "spec/thesis/f6_specification_rc01.json",
        "spec/decisions/engineering_v1.1.0.json",
        "spec/bindings/formula_bindings.json",
        "config/resolved_instance.json",
    ]
    documents: dict[str, dict[str, Any]] = {}
    input_errors: list[dict[str, str]] = []
    for relative_path in relative_paths:
        try:
            documents[relative_path] = read_json_file(
                package_root / relative_path,
                f"resolution:{relative_path}",
                report,
                package_root,
            )
        except InputFailure as exc:
            input_errors.append({"path": relative_path, "reason": str(exc)})
    if input_errors:
        report.add(
            "resolution.inputs.invalid",
            "the binding/configuration resolution requires eight valid predecessor and output documents",
            details=input_errors,
        )
        report.metrics["resolved_configuration_contract"] = {
            "errors": len(input_errors),
            "future_code_anchor_locations": 0,
            "layers_resolved": 0,
            "materialized_binding_locations": 0,
        }
        return

    decision_records = {
        item.get("id"): item
        for item in provenance.get("decisions", [])
        if isinstance(item, dict) and item.get("id")
    }
    required_decisions = {"T03-RS-005", "T03-RP-012", "T03-MP-013"}
    invalid_decisions = sorted(
        decision_id
        for decision_id in required_decisions
        if decision_id not in decision_records
        or mapped_decision_status(str(decision_records[decision_id].get("status", "")))
        != "approved"
    )
    if invalid_decisions:
        report.add(
            "resolution.decisions.invalid",
            "the closed resolution depends on exactly three approved decision contracts",
            details=invalid_decisions,
        )
        report.metrics["resolved_configuration_contract"] = {
            "errors": len(invalid_decisions),
            "future_code_anchor_locations": 0,
            "layers_resolved": 0,
            "materialized_binding_locations": 0,
        }
        return

    errors: list[dict[str, Any]] = []
    try:
        rs = decision_records["T03-RS-005"]["decision"]
        mp = decision_records["T03-MP-013"]["decision"]
        formula = rs["formula_binding"]
        required_bindings = mp["required_executable_binding_map"]
        binding = documents["spec/bindings/formula_bindings.json"]
        thesis = documents["spec/thesis/f6_specification_rc01.json"]
        engineering = documents["spec/decisions/engineering_v1.1.0.json"]
        host_published = documents["spec/published/host_appraisal_2018a.json"]
        boundary_published = documents["spec/published/ga_ef_boundary_2018ab.json"]
        sadness_published = documents["spec/published/rule_sadness_2018a.json"]
        anger_published = documents["spec/published/rule_anger_2018b.json"]
        config = documents["config/resolved_instance.json"]

        expected_binding = {
            "$schema": "../../schemas/formula_bindings.schema.json",
            "schema_version": "1.0.0",
            "binding_id": formula["binding_id"],
            "formula_id": formula["formula_id"],
            "provenance_layer": formula["provenance_layer"],
            "not_attributed_to_published_rules": formula[
                "not_attributed_to_published_rules"
            ],
            "expression": formula["expression"],
            "input_bindings": formula["input_bindings"],
            "binding_map": required_bindings,
            "formula_to_binding_key_crosswalk": formula[
                "formula_to_binding_key_crosswalk"
            ],
            "binding_roles": formula["binding_roles"],
            "parameter_values": formula["parameter_values"],
            "authorized_output": formula["authorized_output"],
            "protected_dimensions": formula["protected_dimensions"],
            "published_rule_access": formula["published_rule_access"],
            "resolution_policy": formula["resolution_policy"],
            "collision_policy": mp["binding_artifacts"]["consistency_rule"],
            "source_layers": {
                "doctoral_specification": "spec/thesis/f6_specification_rc01.json",
                "engineering_decisions": "spec/decisions/engineering_v1.1.0.json",
            },
            "decision_refs": ["T03-RS-005", "T03-RP-012", "T03-MP-013"],
        }

        package = provenance["package_identity"]
        expected_host = dict(thesis["host"])
        expected_host["integration"] = engineering["published_boundary_adapter"][
            "canonical"
        ]
        expected_influence = dict(thesis["influence"])
        expected_influence["binding_map"] = required_bindings
        published_paths = [
            "spec/published/host_appraisal_2018a.json",
            "spec/published/ga_ef_boundary_2018ab.json",
            "spec/published/rule_sadness_2018a.json",
            "spec/published/rule_anger_2018b.json",
        ]
        expected_config = {
            "$schema": "../schemas/config.schema.json",
            "schema_version": "1.0.0",
            "instance": {
                "id": package["conceptual_id"],
                "package_version": package["package_version"],
                "artifact_internal_version": package["artifact_version_policy"][
                    "artifact_internal_versions"
                ],
                "release_stage": package["release_stage"],
                "conformance_target": "M6",
            },
            "resolution": {
                "profile_id": "IFM6-RESOLUTION-1.0.0",
                "derived_only": True,
                "reverse_edit_prohibited": True,
                "output_path": "config/resolved_instance.json",
                "binding_registry": "spec/bindings/formula_bindings.json",
                "composition_order": ["published", "decisions", "thesis", "bindings"],
                "source_layers": {
                    "published": published_paths,
                    "decisions": "spec/decisions/engineering_v1.1.0.json",
                    "thesis": "spec/thesis/f6_specification_rc01.json",
                    "bindings": "spec/bindings/formula_bindings.json",
                },
                "authorized_precedence": rs["layer_separation"][
                    "authorized_precedence"
                ],
                "conflict_policy": rs["layer_separation"][
                    "authorized_precedence"
                ][-1],
            },
            "host": expected_host,
            "perspective": thesis["perspective"],
            "factor": thesis["factor"],
            "influence": expected_influence,
            "coping_partition": thesis["coping_partition"],
            "rules": {
                "selected_subset": thesis["rules"]["selected_subset"],
                "published_sources": {
                    "sadness": "spec/published/rule_sadness_2018a.json#/source",
                    "anger": "spec/published/rule_anger_2018b.json#/source/consistent_row",
                },
                "execution": engineering["rules"],
                "adapters": {
                    "antecedent_lexemes": engineering["antecedent_lexeme_adapter"],
                    "boundary": engineering["published_boundary_adapter"],
                    "rule_context": engineering["rule_adapters"],
                },
            },
            "evaluation": thesis["evaluation"],
            "contract": {
                "host": engineering["host"],
                "factor_state": engineering["factor_state"],
                "validation_order": engineering["validation_order"],
                "failure_policy": engineering["failure_policy"],
                "temporal_policy": engineering["temporal_policy"],
                "diagnostics": engineering["diagnostics"],
            },
            "runtime": {
                "environment": engineering["runtime"],
                "canonical_json": engineering["canonical_json"],
                "numeric": engineering["numeric"],
                "time": engineering["time"],
                "trace_id": engineering["trace_id"],
            },
        }

        def top_level_difference(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
            return {
                "different": sorted(
                    key for key in set(actual) & set(expected) if actual[key] != expected[key]
                ),
                "extra": sorted(set(actual) - set(expected)),
                "missing": sorted(set(expected) - set(actual)),
            }

        if binding != expected_binding:
            errors.append(
                {
                    "path": "spec/bindings/formula_bindings.json",
                    "reason": "not_exact_approved_binding_projection",
                    **top_level_difference(binding, expected_binding),
                }
            )
        if config != expected_config:
            errors.append(
                {
                    "path": "config/resolved_instance.json",
                    "reason": "not_exact_one_way_layer_composition",
                    **top_level_difference(config, expected_config),
                }
            )
        if (
            host_published.get("variables")
            != [
                "Expectedness",
                "Desirability",
                "Novelty",
                "Goals conduciveness",
                "Pleasure",
                "Coping potential",
            ]
            or set(boundary_published.get("sources", {})) != {"2018a", "2018b"}
            or not isinstance(sadness_published.get("source"), dict)
            or not isinstance(
                anger_published.get("source", {}).get("consistent_row"), dict
            )
        ):
            errors.append({"reason": "published_predecessor_boundary_invalid"})
        if (
            binding.get("binding_roles", {}).get("input_keys")
            != ["coping_potential", "lambda", "z"]
            or binding.get("binding_roles", {}).get("output_key") != "result"
            or binding.get("binding_roles", {}).get("result_is_input") is not False
            or "result" in binding.get("input_bindings", {})
        ):
            errors.append({"reason": "three_inputs_one_distinct_output_not_preserved"})
        if (
            config.get("resolution", {}).get("derived_only") is not True
            or config.get("resolution", {}).get("reverse_edit_prohibited") is not True
            or config.get("resolution", {}).get("conflict_policy")
            != rs["layer_separation"]["authorized_precedence"][-1]
        ):
            errors.append({"reason": "resolution_is_not_one_way_and_fail_closed"})
    except (KeyError, IndexError, TypeError) as exc:
        errors.append(
            {
                "reason": "resolution_predecessor_structure_invalid",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        )
        required_bindings = {
            "coping_potential": "host.baseline.coping_potential",
            "lambda": "influence.parameters.lambda",
            "z": "factor_state.level",
            "result": "output.coping_potential",
        }

    materialized_binding_locations = {
        (row.get("target_path", ""), row.get("target_locator", ""))
        for row in rows
        if active(row)
        and materialization_status(row) in MATERIALIZED
        and row.get("target_path", "") in CONFIGURATION_LAYER_PATHS
        and row.get("target_locator", "")
        in {
            *(f"/binding_map/{key}" for key in required_bindings),
            *(f"/influence/binding_map/{key}" for key in required_bindings),
        }
    }
    future_code_anchor_locations = {
        row.get("target_locator", "")
        for row in rows
        if active(row)
        and row.get("target_path") == "src/ifatigue_infra6/model.py"
        and row.get("target_locator", "").startswith("@binding-")
    }
    if len(materialized_binding_locations) != 8:
        errors.append(
            {
                "reason": "materialized_binding_location_count_mismatch",
                "actual": len(materialized_binding_locations),
                "expected": 8,
            }
        )
    if len(future_code_anchor_locations) != 4:
        errors.append(
            {
                "reason": "implementation_anchor_count_mismatch",
                "actual": len(future_code_anchor_locations),
                "expected": 4,
            }
        )
    if errors:
        report.add(
            "resolution.binding_config.cross_layer",
            "binding registry and resolved configuration must be exact, one-way, fail-closed projections of the four approved layers",
            details=errors,
        )
    report.metrics["resolved_configuration_contract"] = {
        "errors": len(errors),
        "future_code_anchor_locations": len(future_code_anchor_locations),
        "layers_resolved": 4 if not errors else 0,
        "materialized_binding_locations": len(materialized_binding_locations),
    }


def validate_diagnostics_and_governance(
    rows: list[dict[str, str]],
    parsed_values: dict[str, Any],
    provenance: dict[str, Any],
    report: Report,
) -> None:
    decision_index = {
        item.get("id"): item
        for item in provenance.get("decisions", [])
        if isinstance(item, dict) and item.get("id")
    }
    diagnostic_errors: list[dict[str, Any]] = []
    ct = decision_index.get("T03-CT-009", {}).get("decision", {})
    qa = decision_index.get("T03-QA-011", {}).get("decision", {})
    ct_codes = ct.get("diagnostic_codes", []) if isinstance(ct, dict) else []
    qa_codes = qa.get("diagnostic_priority", []) if isinstance(qa, dict) else []
    ct_aggregation = ct.get("diagnostic_aggregation", {}) if isinstance(ct, dict) else {}
    qa_non_cascade = qa.get("diagnostic_non_cascade", {}) if isinstance(qa, dict) else {}
    exact_identity = "the diagnostic code string identifies a failure class, not an occurrence or failed-field record"
    exact_dedup = "represent the independently detected diagnostic class once even when multiple fields produce that same code"
    if (
        mapped_decision_status(str(decision_index.get("T03-CT-009", {}).get("status", ""))) != "approved"
        or mapped_decision_status(str(decision_index.get("T03-QA-011", {}).get("status", ""))) != "approved"
        or not isinstance(ct_codes, list)
        or ct_codes != qa_codes
        or len(ct_codes) != 22
        or len(set(ct_codes)) != 22
        or any(not isinstance(code, str) for code in ct_codes)
        or ct_aggregation.get("diagnostic_identity") != exact_identity
        or ct_aggregation.get("same_code_multiple_fields") != exact_dedup
        or qa_non_cascade.get("diagnostic_identity") != exact_identity
        or qa_non_cascade.get("same_code_multiple_fields") != exact_dedup
        or "deduplicate by code" not in str(ct_aggregation.get("independent_failure_policy", ""))
        or "deduplicate by code" not in str(qa_non_cascade.get("aggregation", ""))
    ):
        diagnostic_errors.append({"reason": "CT_QA_code_class_dedup_contract_mismatch"})
    forbidden_pair_language = ("code,field", "code, field", "code_and_field", "code and field", "failed-field pair")
    diagnostic_contract_text = json.dumps(
        {"ct": ct_aggregation, "qa": qa_non_cascade},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).casefold()
    leaked_language = sorted(term for term in forbidden_pair_language if term in diagnostic_contract_text)
    if leaked_language:
        diagnostic_errors.append({"reason": "residual_pair_identity_language", "terms": leaked_language})

    decisions_path = "spec/decisions/engineering_v1.1.0.json"
    aggregation_rows = [
        row for row in rows
        if active(row)
        and row.get("target_path") == decisions_path
        and row.get("target_locator") == "/diagnostics/aggregation"
    ]
    aggregation_values = {
        json.dumps(parsed_values.get(row.get("row_id", "")), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in aggregation_rows
    }
    expected_aggregation_value = json.dumps(ct_aggregation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    aggregation_supports = {
        (row.get("support_ref_type", ""), row.get("support_ref_id", ""), row.get("support_level", ""))
        for row in aggregation_rows
    }
    if aggregation_values != {expected_aggregation_value}:
        diagnostic_errors.append({"reason": "diagnostic_aggregation_projection_mismatch"})
    if aggregation_supports != {
        ("approved_decision", "T03-CT-009", "direct"),
        ("approved_decision", "T03-QA-011", "direct"),
    }:
        diagnostic_errors.append({"reason": "diagnostic_aggregation_support_mismatch", "actual": sorted(aggregation_supports)})
    code_rows = [
        row for row in rows
        if active(row)
        and row.get("target_path") == decisions_path
        and row.get("target_locator") == "/diagnostics/codes"
    ]
    code_values = {
        json.dumps(parsed_values.get(row.get("row_id", "")), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in code_rows
    }
    if code_values != {json.dumps(ct_codes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}:
        diagnostic_errors.append({"reason": "diagnostic_code_catalog_projection_mismatch"})
    if diagnostic_errors:
        report.add(
            "audit.dg01.diagnostic_identity",
            "diagnostics must be arrays of unique code-class strings, deduplicated by code and ordered by the shared CT/QA priority",
            details=diagnostic_errors,
        )

    governance_errors: list[dict[str, Any]] = []
    dl = decision_index.get("T03-DL-008", {}).get("decision", {})
    rp = decision_index.get("T03-RP-012", {}).get("decision", {})
    dl_csv = dl.get("csv_profile", {}) if isinstance(dl, dict) else {}
    rp_csv = rp.get("csv_profile", {}) if isinstance(rp, dict) else {}
    if (
        mapped_decision_status(str(decision_index.get("T03-DL-008", {}).get("status", ""))) != "approved"
        or mapped_decision_status(str(decision_index.get("T03-RP-012", {}).get("status", ""))) != "approved"
        or dl_csv.get("profile_id") != "ACME-FIRM-CSV-UTF8-LF-1.0"
        or rp_csv.get("profile_id") != "IFM6-CSV-v1"
        or rp_csv.get("ledger_alias") != dl_csv.get("profile_id")
        or dl_csv.get("strict_rfc4180_claim") is not False
        or rp_csv.get("strict_rfc4180_claim") is not False
        or dl_csv.get("encoding") != "UTF-8_without_BOM"
        or rp_csv.get("encoding") != "UTF-8_without_BOM"
        or dl_csv.get("unicode_normalization") != rp_csv.get("unicode_normalization")
        or dl_csv.get("line_endings") != "LF"
        or rp_csv.get("line_endings") != "LF_only"
        or dl_csv.get("final_lf") != rp_csv.get("final_lf")
        or dl_csv.get("quoting") != "all_fields"
        or rp_csv.get("quoting") != "QUOTE_ALL"
        or dl_csv.get("double_quote_escape") is not True
        or rp_csv.get("double_quote") is not True
        or rp_csv.get("sniffer_usage") != "prohibited"
    ):
        governance_errors.append({"reason": "DL008_RP012_csv_profile_alignment_mismatch"})
    dialect_rows = [
        row for row in rows
        if active(row)
        and row.get("derivation_id") == "DL-GOV-001"
        and row.get("target_path") == "sources/DERIVATION_LEDGER.csv"
        and row.get("target_locator") == "@dialect"
    ]
    dialect_values = {
        json.dumps(parsed_values.get(row.get("row_id", "")), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in dialect_rows
    }
    dialect_supports = {
        (row.get("support_ref_type", ""), row.get("support_ref_id", ""), row.get("support_level", ""))
        for row in dialect_rows
    }
    if dialect_values != {json.dumps(rp_csv, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}:
        governance_errors.append({"reason": "ledger_dialect_projection_not_exact_RP012_profile"})
    if dialect_supports != {
        ("approved_decision", "T03-DL-008", "direct"),
        ("approved_decision", "T03-RP-012", "direct"),
    }:
        governance_errors.append({"reason": "ledger_dialect_support_mismatch", "actual": sorted(dialect_supports)})
    if any(
        isinstance(parsed_values.get(row.get("row_id", "")), dict)
        and str(parsed_values[row["row_id"]].get("dialect", "")).upper() == "RFC4180"
        for row in dialect_rows
    ):
        governance_errors.append({"reason": "pure_RFC4180_dialect_claim_forbidden"})
    if governance_errors:
        report.add(
            "audit.gov001.csv_profile",
            "GOV-001 must project the exact UTF-8/NFC/LF all-quoted profile jointly authorized by T03-DL-008 and T03-RP-012, without a pure RFC4180 claim",
            details=governance_errors,
        )
    report.metrics["audit_diagnostics_governance"] = {
        "diagnostic_codes": len(ct_codes) if isinstance(ct_codes, list) else 0,
        "diagnostic_projection": not diagnostic_errors,
        "governance_profile_projection": not governance_errors,
    }


def validate_representation(
    rows: list[dict[str, str]], report: Report
) -> None:
    unsupported_representation = []
    for row in rows:
        if not active(row) or row.get("target_path") != "spec/thesis/f6_specification_rc01.json":
            continue
        if "decimal_string" in row.get("target_value", ""):
            decisions = set(split_multi(row.get("approval_refs", "")))
            if row.get("support_ref_type") == "approved_decision":
                decisions.add(row.get("support_ref_id", ""))
            if not decisions:
                unsupported_representation.append(row.get("row_id", ""))
    if unsupported_representation:
        report.add("science.representation.no_decision", "decimal_string is an engineering representation and needs an approved decision", details=unsupported_representation)


_UNSET = object()


def pointer_tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError("not a JSON Pointer")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def container_for_next(token: str) -> Any:
    return [] if token.isdigit() else {}


def assign_pointer(root: Any, tokens: list[str], value: Any) -> tuple[Any, str | None]:
    if not tokens:
        if root is _UNSET:
            return value, None
        if root != value:
            return root, "root_value_conflict"
        return root, None
    if root is _UNSET:
        root = container_for_next(tokens[0])
    current = root
    for index, token in enumerate(tokens):
        last = index == len(tokens) - 1
        next_token = tokens[index + 1] if not last else ""
        if isinstance(current, dict):
            if last:
                existing = current.get(token, _UNSET)
                if existing is not _UNSET and existing != value:
                    return root, "value_conflict"
                current[token] = value
                return root, None
            if token not in current:
                current[token] = container_for_next(next_token)
            elif not isinstance(current[token], (dict, list)):
                return root, "scalar_prefix_conflict"
            current = current[token]
            continue
        if isinstance(current, list):
            if not token.isdigit():
                return root, "array_index_not_numeric"
            position = int(token)
            while len(current) <= position:
                current.append(_UNSET)
            if last:
                existing = current[position]
                if existing is not _UNSET and existing != value:
                    return root, "value_conflict"
                current[position] = value
                return root, None
            if current[position] is _UNSET:
                current[position] = container_for_next(next_token)
            elif not isinstance(current[position], (dict, list)):
                return root, "scalar_prefix_conflict"
            current = current[position]
            continue
        return root, "scalar_prefix_conflict"
    return root, None


def has_unset(value: Any) -> bool:
    if value is _UNSET:
        return True
    if isinstance(value, list):
        return any(has_unset(item) for item in value)
    if isinstance(value, dict):
        return any(has_unset(item) for item in value.values())
    return False


def reconstruct_document(
    rows: list[dict[str, str]], parsed_values: dict[str, Any], path: str, report: Report
) -> tuple[bool, Any]:
    assignments: dict[str, dict[str, Any]] = defaultdict(dict)
    unknown_anchors: list[str] = []
    for row in rows:
        if not active(row) or row.get("target_path") != path or row.get("row_id") not in parsed_values:
            continue
        locator = row.get("target_locator", "")
        if locator == "@materialization-recipe":
            continue
        if locator == "@document":
            locator = ""
        elif locator.startswith("@"):
            unknown_anchors.append(locator)
            continue
        assignments[locator][row.get("target_value", "")] = parsed_values[row["row_id"]]
    if unknown_anchors:
        report.add(
            "document.anchor.unsupported",
            "semantic document rows may use JSON Pointers; @materialization-recipe is metadata only",
            details={"path": path, "anchors": sorted(set(unknown_anchors))},
        )
    conflicts = [
        {"locator": locator, "values": sorted(values)}
        for locator, values in sorted(assignments.items())
        if len(values) != 1
    ]
    if conflicts:
        report.add(
            "document.pointer.value_conflict",
            "a document pointer has more than one active value",
            details={"path": path, "conflicts": conflicts},
        )
        return False, None
    if not assignments:
        return False, None
    root: Any = _UNSET
    prefix_errors: list[dict[str, str]] = []
    ordered = sorted(assignments, key=lambda locator: (len(pointer_tokens(locator)), locator))
    for locator in ordered:
        try:
            tokens = pointer_tokens(locator)
        except ValueError:
            prefix_errors.append({"locator": locator, "reason": "invalid_json_pointer"})
            continue
        value = next(iter(assignments[locator].values()))
        root, error = assign_pointer(root, tokens, value)
        if error:
            prefix_errors.append({"locator": locator, "reason": error})
    if has_unset(root):
        prefix_errors.append({"locator": "", "reason": "sparse_array_or_incomplete_prefix"})
    if prefix_errors:
        report.add(
            "document.pointer.prefix_conflict",
            "atomic document pointers cannot be reconstructed deterministically",
            details={"path": path, "errors": prefix_errors},
        )
        return False, None
    return True, root


def canonical_json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def schema_json_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int equality aliasing."""
    try:
        return canonical_json_text(left) == canonical_json_text(right)
    except (TypeError, ValueError):
        return False


def schema_type_matches(instance: Any, expected: str) -> bool:
    return {
        "object": isinstance(instance, dict),
        "array": isinstance(instance, list),
        "string": isinstance(instance, str),
        "boolean": isinstance(instance, bool),
        "null": instance is None,
        "integer": isinstance(instance, int) and not isinstance(instance, bool),
        "number": (
            isinstance(instance, (int, float)) and not isinstance(instance, bool)
        ),
    }.get(expected, False)


def resolve_local_schema_ref(root: dict[str, Any], reference: str) -> Any:
    if reference == "#":
        return root
    if not reference.startswith("#/"):
        raise ValueError(f"only local JSON Pointer refs are supported: {reference}")
    current: Any = root
    for raw in reference[2:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise ValueError(f"unresolved local schema ref: {reference}")
    return current


def validate_json_schema_instance(
    instance: Any,
    schema: Any,
    *,
    root: dict[str, Any] | None = None,
    location: str = "$",
    depth: int = 0,
) -> list[str]:
    """Evaluate the dependency-free Draft 2020-12 subset used by this package."""
    if depth > 200:
        return [f"{location}: schema recursion limit exceeded"]
    if schema is True:
        return []
    if schema is False:
        return [f"{location}: false schema rejects the instance"]
    if not isinstance(schema, dict):
        return [f"{location}: schema node is not an object or boolean"]
    if root is None:
        root = schema
    errors: list[str] = []
    if "$ref" in schema:
        try:
            target = resolve_local_schema_ref(root, schema["$ref"])
        except ValueError as exc:
            return [f"{location}: {exc}"]
        errors.extend(
            validate_json_schema_instance(
                instance,
                target,
                root=root,
                location=location,
                depth=depth + 1,
            )
        )
    for keyword in ("allOf",):
        branches = schema.get(keyword)
        if isinstance(branches, list):
            for branch in branches:
                errors.extend(
                    validate_json_schema_instance(
                        instance,
                        branch,
                        root=root,
                        location=location,
                        depth=depth + 1,
                    )
                )
    for keyword in ("anyOf", "oneOf"):
        branches = schema.get(keyword)
        if isinstance(branches, list):
            matches = sum(
                not validate_json_schema_instance(
                    instance,
                    branch,
                    root=root,
                    location=location,
                    depth=depth + 1,
                )
                for branch in branches
            )
            if (keyword == "anyOf" and matches == 0) or (
                keyword == "oneOf" and matches != 1
            ):
                errors.append(
                    f"{location}: {keyword} matched {matches} of {len(branches)} branches"
                )
    if "not" in schema and not validate_json_schema_instance(
        instance,
        schema["not"],
        root=root,
        location=location,
        depth=depth + 1,
    ):
        errors.append(f"{location}: prohibited not-schema matched")
    if "const" in schema and not schema_json_equal(instance, schema["const"]):
        errors.append(f"{location}: value differs from const")
    if "enum" in schema and not any(
        schema_json_equal(instance, candidate) for candidate in schema["enum"]
    ):
        errors.append(f"{location}: value is outside enum")
    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = (
            expected_type if isinstance(expected_type, list) else [expected_type]
        )
        if not any(schema_type_matches(instance, item) for item in expected_types):
            errors.append(
                f"{location}: type {type(instance).__name__} is not one of {expected_types}"
            )
            return errors
    if isinstance(instance, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in instance:
                    errors.append(f"{location}: missing required property {key!r}")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        for key, subschema in properties.items():
            if key in instance:
                errors.extend(
                    validate_json_schema_instance(
                        instance[key],
                        subschema,
                        root=root,
                        location=f"{location}.{key}",
                        depth=depth + 1,
                    )
                )
        extra = sorted(set(instance) - set(properties))
        additional = schema.get("additionalProperties", True)
        if additional is False and extra:
            errors.append(f"{location}: additional properties {extra}")
        elif isinstance(additional, dict):
            for key in extra:
                errors.extend(
                    validate_json_schema_instance(
                        instance[key],
                        additional,
                        root=root,
                        location=f"{location}.{key}",
                        depth=depth + 1,
                    )
                )
        if isinstance(schema.get("minProperties"), int) and len(instance) < schema["minProperties"]:
            errors.append(f"{location}: fewer than minProperties")
        if isinstance(schema.get("maxProperties"), int) and len(instance) > schema["maxProperties"]:
            errors.append(f"{location}: more than maxProperties")
    if isinstance(instance, list):
        if isinstance(schema.get("minItems"), int) and len(instance) < schema["minItems"]:
            errors.append(f"{location}: fewer than minItems")
        if isinstance(schema.get("maxItems"), int) and len(instance) > schema["maxItems"]:
            errors.append(f"{location}: more than maxItems")
        if schema.get("uniqueItems") is True:
            fingerprints = [canonical_json_text(item) for item in instance]
            if len(fingerprints) != len(set(fingerprints)):
                errors.append(f"{location}: array items are not unique")
        unique_by = schema.get("x-ifm6-unique-by")
        if isinstance(unique_by, list):
            for field in unique_by:
                values = [
                    canonical_json_text(item.get(field))
                    for item in instance
                    if isinstance(item, dict) and field in item
                ]
                if len(values) != len(instance) or len(values) != len(set(values)):
                    errors.append(
                        f"{location}: array items are not uniquely keyed by {field!r}"
                    )
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(instance):
                errors.extend(
                    validate_json_schema_instance(
                        item,
                        item_schema,
                        root=root,
                        location=f"{location}[{index}]",
                        depth=depth + 1,
                    )
                )
        priority = schema.get("x-ifm6-priority-order")
        if isinstance(priority, list) and all(isinstance(item, str) for item in instance):
            positions = {item: index for index, item in enumerate(priority)}
            observed = [positions.get(item, -1) for item in instance]
            if any(index < 0 for index in observed) or observed != sorted(observed):
                errors.append(f"{location}: diagnostics violate fixed priority order")
    if isinstance(instance, str):
        if isinstance(schema.get("minLength"), int) and len(instance) < schema["minLength"]:
            errors.append(f"{location}: shorter than minLength")
        if isinstance(schema.get("maxLength"), int) and len(instance) > schema["maxLength"]:
            errors.append(f"{location}: longer than maxLength")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                matched = re.search(pattern, instance) is not None
            except re.error as exc:
                errors.append(f"{location}: invalid schema regex {exc}")
            else:
                if not matched:
                    errors.append(f"{location}: string does not match pattern")
        if schema.get("x-ifm6-domain") == "[0,1]":
            try:
                number = Decimal(instance)
            except InvalidOperation:
                errors.append(f"{location}: invalid IFM6 decimal")
            else:
                if number < 0 or number > 1:
                    errors.append(f"{location}: decimal is outside [0,1]")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{location}: number is below minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{location}: number is above maximum")
    return errors


def lint_json_schema_document(schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    def walk(node: Any, location: str) -> None:
        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{location}[{index}]")
            return
        if not isinstance(node, dict):
            return
        reference = node.get("$ref")
        if reference is not None:
            if not isinstance(reference, str):
                errors.append(f"{location}: $ref is not a string")
            else:
                try:
                    resolve_local_schema_ref(schema, reference)
                except ValueError as exc:
                    errors.append(f"{location}: {exc}")
        required = node.get("required")
        properties = node.get("properties")
        if required is not None:
            if not isinstance(required, list) or not all(
                isinstance(item, str) for item in required
            ):
                errors.append(f"{location}: required is not a string array")
            elif len(required) != len(set(required)):
                errors.append(f"{location}: required contains duplicates")
            elif (
                isinstance(properties, dict)
                and node.get("additionalProperties") is False
                and not set(required).issubset(properties)
            ):
                errors.append(f"{location}: required names are absent from properties")
        for key, value in node.items():
            if key not in {"const", "enum", "default", "examples"}:
                walk(value, f"{location}/{key}")

    walk(schema, "#")
    return errors


def load_schema_suite(
    package_root: Path, report: Report
) -> dict[str, dict[str, Any]]:
    schema_files = {
        path.relative_to(package_root).as_posix()
        for path in (package_root / "schemas").glob("*.json")
        if path.is_file()
    }
    if schema_files != ALL_SCHEMA_PATHS:
        report.add(
            "schemas.set",
            "the package must contain the exact seventeen-schema set",
            details={
                "missing": sorted(ALL_SCHEMA_PATHS - schema_files),
                "unexpected": sorted(schema_files - ALL_SCHEMA_PATHS),
            },
        )
    schemas: dict[str, dict[str, Any]] = {}
    for relative in sorted(ALL_SCHEMA_PATHS & schema_files):
        path = package_root / relative
        raw = path.read_bytes()
        report.inputs[f"schema:{relative}"] = {
            "bytes": len(raw),
            "path": relative,
            "sha256": sha256_bytes(raw),
        }
        try:
            value = json.loads(
                raw.decode("utf-8"), object_pairs_hook=reject_duplicate_pairs
            )
        except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJSONKey) as exc:
            report.add(
                "schemas.json",
                "a schema is not duplicate-safe UTF-8 JSON",
                details={"path": relative, "error": str(exc)},
            )
            continue
        if not isinstance(value, dict):
            report.add(
                "schemas.object",
                "every schema document must be an object",
                details={"path": relative},
            )
            continue
        schemas[relative] = value
        if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            report.add(
                "schemas.draft",
                "every schema must declare Draft 2020-12",
                details={"path": relative, "actual": value.get("$schema")},
            )
        lint_errors = lint_json_schema_document(value)
        if lint_errors:
            report.add(
                "schemas.lint",
                "a schema has unresolved refs or an inconsistent shape",
                details={"path": relative, "errors": lint_errors[:20]},
            )
        if relative in MATERIALIZED_SCHEMA_PATHS:
            expected_bytes = (canonical_json_text(value) + "\n").encode("utf-8")
            if raw != expected_bytes:
                report.add(
                    "schemas.canonical_bytes",
                    "new T03.3-5 schemas must use canonical IFM6-JSON-v1 bytes",
                    details={"path": relative},
                )
    schema_ids = {
        path: value.get("$id") for path, value in schemas.items()
    }
    duplicates = sorted(
        schema_id
        for schema_id, count in Counter(schema_ids.values()).items()
        if schema_id is not None and count > 1
    )
    missing_ids = sorted(path for path, schema_id in schema_ids.items() if not schema_id)
    if duplicates or missing_ids:
        report.add(
            "schemas.ids",
            "schema identifiers must be present and globally unique",
            details={"duplicates": duplicates, "missing": missing_ids},
        )
    return schemas


def decision_payload(provenance: dict[str, Any], decision_id: str) -> dict[str, Any]:
    records = [
        item
        for item in provenance.get("decisions", [])
        if isinstance(item, dict) and item.get("id") == decision_id
    ]
    if len(records) != 1 or not isinstance(records[0].get("decision"), dict):
        return {}
    return records[0]["decision"]


def result_sample_from_oracle(oracle: dict[str, Any]) -> dict[str, Any]:
    expected = oracle["expected"]
    result = {
        "$schema": "../../schemas/result.schema.json",
        "schema_version": "1.0.0",
        "scenario_id": oracle["scenario_id"],
        "evaluation_time": "2026-09-04T12:00:00Z",
        "disposition": expected["disposition"],
        "diagnostics": deepcopy(expected["diagnostics"]),
        "factor_validation_performed": expected["factor_validation_performed"],
        "modulation": deepcopy(expected["modulation"]),
        "classification": deepcopy(expected["classification"]),
        "modulation_trace": deepcopy(expected["modulation_trace"]),
        "rejection_record": deepcopy(expected["rejection_record"]),
    }
    if expected["output_contract"]["exists"]:
        result["output"] = deepcopy(
            expected["output_contract"]["appraisal_vector"]
        )
    return result


def validate_executable_schema_suite(
    rows: list[dict[str, str]],
    parsed_values: dict[str, Any],
    provenance: dict[str, Any],
    sources: dict[str, Any],
    report: Report,
    package_root: Path,
) -> None:
    """Verify all 17 schemas, including 15 positive and negative contract probes."""
    schemas = load_schema_suite(package_root, report)
    planned_schemas = {
        item.get("path"): item.get("status")
        for item in provenance.get("planned_tree", [])
        if isinstance(item, dict) and str(item.get("path", "")).startswith("schemas/")
    }
    if set(planned_schemas) != ALL_SCHEMA_PATHS:
        report.add(
            "schemas.provenance_set",
            "PROVENANCE must declare exactly the seventeen schema paths",
            details={"actual": sorted(planned_schemas)},
        )
    wrong_new_status = {
        path: planned_schemas.get(path)
        for path in sorted(MATERIALIZED_SCHEMA_PATHS)
        if planned_schemas.get(path) != "present_validated_T03_3_5"
    }
    if wrong_new_status:
        report.add(
            "schemas.provenance_status",
            "all fifteen T03.3-5 schemas require the exact validated status",
            details=wrong_new_status,
        )

    projection_errors: list[dict[str, Any]] = []
    for path in sorted(MATERIALIZED_SCHEMA_PATHS):
        reconstructed, document = reconstruct_document(
            rows, parsed_values, path, report
        )
        if not reconstructed or path not in schemas or document != schemas[path]:
            projection_errors.append(
                {"path": path, "reason": "ledger_projection_mismatch"}
            )
        active_rows = [
            row
            for row in rows
            if active(row) and row.get("target_path") == path
        ]
        if not active_rows or any(
            row.get("materialization_status") != "materialized_t03"
            or row.get("materialization_refs") != path
            for row in active_rows
        ):
            projection_errors.append(
                {"path": path, "reason": "ledger_materialization_status_mismatch"}
            )
    if projection_errors:
        report.add(
            "schemas.ledger_projection",
            "materialized schema bytes must equal their active ledger projections",
            details=projection_errors,
        )

    positive: list[tuple[str, str, Any]] = []
    if "schemas/provenance.schema.json" in schemas:
        positive.append(("PROVENANCE.json", "schemas/provenance.schema.json", provenance))
    if "schemas/sources.schema.json" in schemas:
        positive.append(("sources/SOURCES.json", "schemas/sources.schema.json", sources))

    reconstructed_documents: dict[str, Any] = {}
    reconstruction_paths = [
        *(f"scenarios/S{index:02d}.json" for index in range(16)),
        *(f"oracles/S{index:02d}.expected.json" for index in range(16)),
        "tests/fixtures/sadness_2018a_symbolic.json",
        "tests/oracles/sadness_2018a_symbolic.expected.json",
        "scenarios/catalog.json",
        "oracles/catalog.json",
        "tests/test_catalog.json",
        "manifests/BUILD_RECIPE.json",
        "manifests/GENERATION_TOPOLOGY.json",
        "manifests/BUILD_RECORD.json",
    ]
    for path in reconstruction_paths:
        reconstructed, document = reconstruct_document(rows, parsed_values, path, report)
        if reconstructed:
            reconstructed_documents[path] = document
    for index in range(16):
        path = f"scenarios/S{index:02d}.json"
        if path in reconstructed_documents:
            positive.append((path, "schemas/scenario.schema.json", reconstructed_documents[path]))
        path = f"oracles/S{index:02d}.expected.json"
        if path in reconstructed_documents:
            positive.append((path, "schemas/oracle.schema.json", reconstructed_documents[path]))
    for path, schema_path in [
        ("tests/fixtures/sadness_2018a_symbolic.json", "schemas/scenario.schema.json"),
        ("tests/oracles/sadness_2018a_symbolic.expected.json", "schemas/oracle.schema.json"),
        ("scenarios/catalog.json", "schemas/scenario_catalog.schema.json"),
        ("oracles/catalog.json", "schemas/oracle_catalog.schema.json"),
        ("tests/test_catalog.json", "schemas/test_catalog.schema.json"),
        ("manifests/BUILD_RECIPE.json", "schemas/build_recipe.schema.json"),
        ("manifests/GENERATION_TOPOLOGY.json", "schemas/generation_topology.schema.json"),
        ("manifests/BUILD_RECORD.json", "schemas/build_record.schema.json"),
    ]:
        if path in reconstructed_documents:
            positive.append((path, schema_path, reconstructed_documents[path]))

    for path, schema_path in [
        ("config/resolved_instance.json", "schemas/config.schema.json"),
        (
            "spec/bindings/formula_bindings.json",
            "schemas/formula_bindings.schema.json",
        ),
    ]:
        try:
            value = json.loads(
                (package_root / path).read_text(encoding="utf-8"),
                object_pairs_hook=reject_duplicate_pairs,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJSONKey):
            continue
        positive.append((path, schema_path, value))

    oracle_s00 = reconstructed_documents.get("oracles/S00.expected.json")
    oracle_s15 = reconstructed_documents.get("oracles/S15.expected.json")
    scenario_s00 = reconstructed_documents.get("scenarios/S00.json")
    qa = decision_payload(provenance, "T03-QA-011")
    qg = decision_payload(provenance, "T03-QG-014")
    if isinstance(oracle_s00, dict) and isinstance(scenario_s00, dict) and qa:
        template = qa["trace_materialization_template"]
        trace_core = {
            "event": deepcopy(scenario_s00["event"]),
            "state": deepcopy(scenario_s00["factor_state"]),
            "baseline": deepcopy(scenario_s00["baseline"]),
            "output": deepcopy(
                oracle_s00["expected"]["output_contract"]["appraisal_vector"]
            ),
            "policy": deepcopy(template["fixed_policy"]),
            "mask": deepcopy(template["fixed_mask"]),
            "formula": deepcopy(template["formula_records_by_scenario"]["S00"]),
            "classification": None,
            "versions": deepcopy(template["fixed_versions"]),
        }
        trace_sample = {
            "$schema": "../../schemas/trace.schema.json",
            "schema_version": "1.0.0",
            "scenario_id": "S00",
            "evaluation_time": scenario_s00["evaluation_time"],
            "disposition": oracle_s00["expected"]["disposition"],
            "diagnostics": deepcopy(oracle_s00["expected"]["diagnostics"]),
            "trace_core": trace_core,
            "trace_id": sha256_bytes(canonical_json_text(trace_core).encode("utf-8")),
        }
        positive.append(("probe:trace-S00", "schemas/trace.schema.json", trace_sample))
        positive.append(("probe:result-S00", "schemas/result.schema.json", result_sample_from_oracle(oracle_s00)))
    else:
        trace_sample = None
    if isinstance(oracle_s15, dict):
        positive.append(("probe:result-S15", "schemas/result.schema.json", result_sample_from_oracle(oracle_s15)))
    rejection_sample = {
        "$schema": "../../../schemas/rejection.schema.json",
        "schema_version": "1.0.0",
        "rejection_id": "S15.rejection",
        "scenario_id": "S15",
        "result_ref": "results/reference_run/S15.result.json",
        "phase": "host_baseline",
        "baseline_validation": "rejected",
        "diagnostics": ["HOST_BASELINE_OUT_OF_RANGE"],
        "factor_validation_performed": False,
        "modulation_attempted": False,
        "classification_attempted": False,
        "modulation_trace": False,
        "trace_id_present": False,
    }
    positive.append(("probe:rejection-S15", "schemas/rejection.schema.json", rejection_sample))
    if qg:
        qa_sample = {
            "$schema": "../schemas/qa_verdict.schema.json",
            "schema_version": "1.0.0",
            "gate_id": qg["gate_id"],
            "reviewed_object_path": "PROVENANCE.json",
            "reviewed_object_sha256": sha256_bytes((package_root / "PROVENANCE.json").read_bytes()),
            "perspective_statuses": [
                {
                    "perspective": perspective,
                    "status": "not_run",
                    "rationale": "Revisión aún no ejecutada.",
                }
                for perspective in qg["required_perspectives"]
            ],
            "validator_records": [
                {
                    "validator_id": "VAL-QG-PROVENANCE-001",
                    "validator_command": qg["required_output"]["validator_command"],
                    "execution_status": "not_run",
                    "exit_code": None,
                }
            ],
            "findings": [],
            "verdict": "not_run",
            "reviewed_at_utc": provenance["document"]["updated_at_utc"],
            "approval_refs": ["T03-QG-014"],
        }
        positive.append(("probe:qa-not-run", "schemas/qa_verdict.schema.json", qa_sample))
    else:
        qa_sample = None

    positive_failures: list[dict[str, Any]] = []
    for label, schema_path, instance in positive:
        schema = schemas.get(schema_path)
        if schema is None:
            positive_failures.append({"instance": label, "schema": schema_path, "errors": ["schema missing"]})
            continue
        errors = validate_json_schema_instance(instance, schema)
        if errors:
            positive_failures.append(
                {"instance": label, "schema": schema_path, "errors": errors[:12]}
            )
    if positive_failures:
        report.add(
            "schemas.positive_instances",
            "valid package instances or contract probes were rejected",
            details=positive_failures[:20],
        )

    ledger_schema = schemas.get("schemas/derivation_ledger.schema.json")
    ledger_row_failures: list[dict[str, Any]] = []
    if ledger_schema is not None:
        for row in rows:
            instance = {key: row.get(key, "") for key in EXPECTED_HEADER}
            errors = validate_json_schema_instance(instance, ledger_schema)
            if errors:
                ledger_row_failures.append(
                    {"row_id": row.get("row_id"), "errors": errors[:5]}
                )
                if len(ledger_row_failures) >= 20:
                    break
    if ledger_row_failures:
        report.add(
            "schemas.ledger_rows",
            "ledger rows fail their executable row schema",
            details=ledger_row_failures,
        )

    valid_by_schema = {
        schema_path: deepcopy(instance)
        for _label, schema_path, instance in positive
        if schema_path in MATERIALIZED_SCHEMA_PATHS
    }
    negatives: dict[str, Any] = {}
    for schema_path, valid in valid_by_schema.items():
        negatives[schema_path] = deepcopy(valid)
    if "schemas/provenance.schema.json" in negatives:
        negatives["schemas/provenance.schema.json"].pop("package_identity", None)
    if "schemas/config.schema.json" in negatives:
        negatives["schemas/config.schema.json"]["undeclared_layer"] = {}
    if "schemas/scenario.schema.json" in negatives:
        negatives["schemas/scenario.schema.json"]["expected"] = {}
    if "schemas/oracle.schema.json" in negatives:
        negatives["schemas/oracle.schema.json"]["observed"] = True
    if "schemas/scenario_catalog.schema.json" in negatives:
        negatives["schemas/scenario_catalog.schema.json"]["entries"][0]["result_path"] = "forbidden"
    if "schemas/oracle_catalog.schema.json" in negatives:
        negatives["schemas/oracle_catalog.schema.json"]["entries"][0]["expected"] = {}
    if "schemas/test_catalog.schema.json" in negatives:
        negatives["schemas/test_catalog.schema.json"]["test_catalog"][0]["observed"] = True
    if "schemas/result.schema.json" in negatives:
        if "output" in negatives["schemas/result.schema.json"]:
            negatives["schemas/result.schema.json"].pop("output", None)
        else:
            negatives["schemas/result.schema.json"]["output"] = {}
    if "schemas/trace.schema.json" in negatives:
        negatives["schemas/trace.schema.json"]["trace_id"] = "A" * 64
    if "schemas/rejection.schema.json" in negatives:
        negatives["schemas/rejection.schema.json"]["modulation_trace"] = True
    if "schemas/formula_bindings.schema.json" in negatives:
        negatives["schemas/formula_bindings.schema.json"]["binding_roles"]["result_is_input"] = True
    if "schemas/build_recipe.schema.json" in negatives:
        negatives["schemas/build_recipe.schema.json"].pop("failure_policy", None)
    if "schemas/generation_topology.schema.json" in negatives:
        negatives["schemas/generation_topology.schema.json"]["cycle"] = True
    if "schemas/build_record.schema.json" in negatives:
        negatives["schemas/build_record.schema.json"]["status"] = "completed"
    if "schemas/qa_verdict.schema.json" in negatives:
        negatives["schemas/qa_verdict.schema.json"]["external_peer_review"] = True
    unexpectedly_accepted = [
        path
        for path, invalid in sorted(negatives.items())
        if path in schemas and not validate_json_schema_instance(invalid, schemas[path])
    ]
    if set(negatives) != MATERIALIZED_SCHEMA_PATHS or unexpectedly_accepted:
        report.add(
            "schemas.negative_probes",
            "each new schema must reject its targeted contract violation",
            details={
                "probe_count": len(negatives),
                "missing_probes": sorted(MATERIALIZED_SCHEMA_PATHS - set(negatives)),
                "unexpectedly_accepted": unexpectedly_accepted,
            },
        )
    report.metrics["schema_suite"] = {
        "declared_schemas": len(ALL_SCHEMA_PATHS),
        "materialized_T03_3_5": len(MATERIALIZED_SCHEMA_PATHS & set(schemas)),
        "canonical_new_schema_files": sum(
            1
            for path in MATERIALIZED_SCHEMA_PATHS
            if path in schemas
            and (package_root / path).read_bytes()
            == (canonical_json_text(schemas[path]) + "\n").encode("utf-8")
        ),
        "positive_instance_checks": len(positive),
        "positive_instance_failures": len(positive_failures),
        "negative_contract_probes": len(negatives),
        "negative_contract_probes_rejected": len(negatives) - len(unexpectedly_accepted),
        "ledger_rows_schema_checked": len(rows) if ledger_schema is not None else 0,
        "ledger_row_schema_failures": len(ledger_row_failures),
        "schema_ids_unique": (
            len(schemas) == len(ALL_SCHEMA_PATHS)
            and all(schema.get("$id") for schema in schemas.values())
            and len({schema.get("$id") for schema in schemas.values()})
            == len(schemas)
        ),
    }


def validate_scenarios_and_oracles(
    rows: list[dict[str, str]], parsed_values: dict[str, Any], provenance: dict[str, Any], report: Report
) -> None:
    bl_decisions = [item for item in provenance.get("decisions", []) if item.get("id") == "T03-BL-006"]
    if len(bl_decisions) != 1 or mapped_decision_status(str(bl_decisions[0].get("status", ""))) != "approved":
        report.add(
            "science.scenarios.bl006_contract",
            "T03-BL-006 must be exactly one approved frozen scenario/oracle decision",
            details={"records": len(bl_decisions)},
        )
        bl_decision: dict[str, Any] = {}
    else:
        bl_decision = bl_decisions[0].get("decision", {})
    required_scenario_fields = {
        "scenario_id", "fixture_class", "empirical_support", "evaluation_time",
        "event", "baseline", "factor_state",
    }
    allowed_scenario_fields = required_scenario_fields | {"host_symbolic_payload"}
    exact_event = {"event_id": "EVT-CONFORMANCE-001", "kind": "synthetic_tutoring_event"}
    exact_sentinels = {
        "expectedness": "0.11",
        "desirability": "0.22",
        "novelty": "0.33",
        "pleasure": "0.44",
        "goal_conduciveness": "0.55",
    }
    exact_scenario_inputs = {
        "S00-S04": {"coping_potential": "0.6", "z": ["0", "0.2", "0.5", "0.8", "1"]},
        "S05": {"coping_potential": "0", "z": "1"},
        "S06": {"coping_potential": "1", "z": "0"},
        "S07": {"coping_potential": "0.6", "factor_state": None},
        "S08": {"coping_potential": "0.6", "z": "0.5", "age_seconds": 301},
        "S09": {"coping_potential": "0.6", "z": "-0.01"},
        "S10": {"coping_potential": "0.6", "z": "1.01"},
        "S11": {"coping_potential": "0.6", "z": "0.5", "confidence": "0.49"},
        "S12": {"coping_potential": "0.6", "z": "0.5", "future_seconds": 6},
        "S13": {"coping_potential": "0.6", "z": "0.5", "age_seconds": 300},
        "S14": {"coping_potential": "0.35", "z": "1"},
        "S15": {"coping_potential": "1.1", "z": "0.5"},
    }
    if (
        bl_decision.get("fixture_class") != "synthetic_conformance_fixture"
        or bl_decision.get("empirical_support") != "none"
        or bl_decision.get("evaluation_time") != "2026-09-04T12:00:00Z"
        or bl_decision.get("stable_conformance_event") != exact_event
        or bl_decision.get("protected_dimension_sentinels") != exact_sentinels
        or bl_decision.get("scenario_inputs") != exact_scenario_inputs
    ):
        report.add(
            "science.scenarios.frozen_values",
            "T03-BL-006 fixture metadata, sentinels and scenario overrides must match the frozen values exactly",
        )
    scenario_policy = bl_decision.get("scenario_payload_policy", {})
    scenario_closure = scenario_policy.get("schema_closure", {}) if isinstance(scenario_policy, dict) else {}
    expected_scenario_policy = {
        "required": required_scenario_fields,
        "optional": {"host_symbolic_payload"},
        "allowed": allowed_scenario_fields,
        "event": exact_event,
        "additionalProperties": False,
    }
    actual_scenario_policy = {
        "required": set(scenario_closure.get("required_top_level_fields", [])),
        "optional": set(scenario_closure.get("optional_top_level_fields", [])),
        "allowed": set(scenario_closure.get("allowed_top_level_fields", [])),
        "event": scenario_closure.get("event_value"),
        "additionalProperties": scenario_closure.get("additionalProperties"),
    }
    if actual_scenario_policy != expected_scenario_policy:
        report.add(
            "science.scenarios.closed_contract",
            "T03-BL-006 must freeze the exact closed input-only scenario shape",
            details={
                "actual": {key: sorted(value) if isinstance(value, set) else value for key, value in actual_scenario_policy.items()},
                "expected": {key: sorted(value) if isinstance(value, set) else value for key, value in expected_scenario_policy.items()},
            },
        )
    oracle_document_contract = (
        bl_decision.get("oracle_payload_policy", {}).get("document_contract", {})
        if isinstance(bl_decision.get("oracle_payload_policy", {}), dict)
        else {}
    )
    oracle_semantics = oracle_document_contract.get("scenario_semantics", {})
    required_oracle_fields = {
        "$schema", "schema_version", "oracle_id", "scenario_id", "scenario_ref",
        "oracle_class", "empirical_support", "frozen_before_implementation",
        "provenance_refs", "calculation_basis", "expected",
    }
    required_expected_fields = {
        "disposition", "diagnostics", "output_contract", "factor_validation_performed",
        "modulation", "classification", "modulation_trace", "rejection_record",
    }
    oracle_expected_contract = oracle_document_contract.get("expected_contract", {})
    if (
        set(oracle_document_contract.get("required_outer_fields", [])) != required_oracle_fields
        or set(oracle_document_contract.get("allowed_outer_fields", [])) != required_oracle_fields
        or oracle_document_contract.get("additionalProperties") is not False
        or set(oracle_expected_contract.get("required_fields", [])) != required_expected_fields
        or set(oracle_expected_contract.get("allowed_fields", [])) != required_expected_fields
        or oracle_expected_contract.get("additionalProperties") is not False
        or set(oracle_semantics) != {f"S{index:02d}" for index in range(16)}
    ):
        report.add(
            "science.oracles.closed_contract",
            "T03-BL-006 must freeze closed oracle and expected-object contracts for S00-S15",
        )
    expected_scenarios = {f"scenarios/S{index:02d}.json" for index in range(16)}
    expected_oracles = {f"oracles/S{index:02d}.expected.json" for index in range(16)}
    validate_planned_set(provenance, "SCENARIOS-16", expected_scenarios, report)
    validate_planned_set(provenance, "ORACLES-16", expected_oracles, report)
    targeted_scenarios = {
        row.get("target_path", "")
        for row in rows
        if re.fullmatch(r"scenarios/S[0-9]+\.json", row.get("target_path", ""))
        and materialization_status(row) != "superseded"
    }
    targeted_oracles = {
        row.get("target_path", "")
        for row in rows
        if re.fullmatch(r"oracles/S[0-9]+\.expected\.json", row.get("target_path", ""))
        and materialization_status(row) != "superseded"
    }
    if targeted_scenarios != expected_scenarios:
        report.add(
            "science.scenarios.target_set",
            "ledger must target exactly scenarios S00-S15",
            details={"missing": sorted(expected_scenarios - targeted_scenarios), "extra": sorted(targeted_scenarios - expected_scenarios)},
        )
    if targeted_oracles != expected_oracles:
        report.add(
            "science.oracles.target_set",
            "ledger must target exactly one oracle for S00-S15",
            details={"missing": sorted(expected_oracles - targeted_oracles), "extra": sorted(targeted_oracles - expected_oracles)},
        )
    scenario_missing: list[str] = []
    scenario_errors: list[dict[str, Any]] = []
    scenario_values: dict[str, dict[str, Any]] = {}
    forbidden_scenario_keys = set(scenario_policy.get("prohibited_fields", [])) | {
        "actual", "results", "trace_id", "passed",
    }
    event_fingerprints: dict[str, list[str]] = defaultdict(list)
    expected_scenario_values: dict[str, dict[str, Any]] = {}
    for index, level in enumerate(exact_scenario_inputs["S00-S04"]["z"]):
        expected_scenario_values[f"S{index:02d}"] = {"coping_potential": "0.6", "z": level}
    for scenario_id in (f"S{index:02d}" for index in range(5, 16)):
        expected_scenario_values[scenario_id] = dict(exact_scenario_inputs[scenario_id])
    for index in range(16):
        scenario_id = f"S{index:02d}"
        path = f"scenarios/{scenario_id}.json"
        reconstructed, document = reconstruct_document(rows, parsed_values, path, report)
        if not reconstructed:
            scenario_missing.append(path)
            continue
        if not isinstance(document, dict):
            scenario_errors.append({"scenario": scenario_id, "reason": "document_not_object"})
            continue
        scenario_values[scenario_id] = document
        missing_fields = sorted(required_scenario_fields - set(document))
        extra_fields = sorted(set(document) - allowed_scenario_fields)
        if missing_fields or extra_fields:
            scenario_errors.append({
                "scenario": scenario_id,
                "reason": "closed_top_level_shape_violation",
                "missing": missing_fields,
                "extra": extra_fields,
            })
        if scenario_id != "S14" and "host_symbolic_payload" in document:
            scenario_errors.append({"scenario": scenario_id, "reason": "host_symbolic_payload_not_permitted"})
        bad_keys = sorted(recursive_keys(document) & forbidden_scenario_keys)
        if bad_keys:
            scenario_errors.append({"scenario": scenario_id, "reason": "not_input_only", "keys": bad_keys})
        if document.get("scenario_id") != scenario_id:
            scenario_errors.append({"scenario": scenario_id, "reason": "scenario_id_mismatch", "actual": document.get("scenario_id")})
        if (
            document.get("fixture_class") != "synthetic_conformance_fixture"
            or document.get("empirical_support") != "none"
            or document.get("evaluation_time") != "2026-09-04T12:00:00Z"
        ):
            scenario_errors.append({"scenario": scenario_id, "reason": "fixture_boundary_missing"})
        baseline = document.get("baseline")
        required_baseline = {"expectedness", "desirability", "novelty", "pleasure", "goal_conduciveness", "coping_potential"}
        if not isinstance(baseline, dict) or set(baseline) != required_baseline:
            scenario_errors.append({"scenario": scenario_id, "reason": "baseline_not_exact_six_vector"})
        else:
            expected_values = expected_scenario_values[scenario_id]
            wrong_sentinels = sorted(key for key, value in exact_sentinels.items() if baseline.get(key) != value)
            if wrong_sentinels:
                scenario_errors.append({"scenario": scenario_id, "reason": "protected_sentinel_mismatch", "fields": wrong_sentinels})
            if scenario_id != "S07" and baseline.get("coping_potential") != expected_values.get("coping_potential"):
                scenario_errors.append({"scenario": scenario_id, "reason": "baseline_coping_potential_mismatch"})
            if scenario_id == "S07" and baseline.get("coping_potential") != "0.6":
                scenario_errors.append({"scenario": scenario_id, "reason": "S07_baseline_coping_potential_mismatch"})
        expected_values = expected_scenario_values[scenario_id]
        factor_state = document.get("factor_state")
        if scenario_id == "S07":
            if factor_state is not None:
                scenario_errors.append({"scenario": scenario_id, "reason": "S07_factor_state_must_be_null"})
        elif not isinstance(factor_state, dict):
            scenario_errors.append({"scenario": scenario_id, "reason": "factor_state_not_object"})
        else:
            if factor_state.get("level") != expected_values.get("z"):
                scenario_errors.append({"scenario": scenario_id, "reason": "factor_level_override_mismatch"})
            if "confidence" in expected_values and factor_state.get("confidence") != expected_values["confidence"]:
                scenario_errors.append({"scenario": scenario_id, "reason": "factor_confidence_override_mismatch"})
            expected_observed_at = datetime.fromisoformat("2026-09-04T12:00:00+00:00")
            if "age_seconds" in expected_values:
                expected_observed_at -= timedelta(seconds=expected_values["age_seconds"])
            if "future_seconds" in expected_values:
                expected_observed_at += timedelta(seconds=expected_values["future_seconds"])
            expected_observed_text = expected_observed_at.isoformat().replace("+00:00", "Z")
            if factor_state.get("observed_at") != expected_observed_text:
                scenario_errors.append({
                    "scenario": scenario_id,
                    "reason": "factor_temporal_override_mismatch",
                    "actual": factor_state.get("observed_at"),
                    "expected": expected_observed_text,
                })
        event = document.get("event")
        if event != exact_event:
            scenario_errors.append({"scenario": scenario_id, "reason": "stable_event_mismatch", "actual": event})
        else:
            event_fingerprints[json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))].append(scenario_id)
    if len(event_fingerprints) > 1:
        scenario_errors.append({
            "reason": "event_not_stable_across_scenarios",
            "variants": [
                {"event": key, "scenarios": event_fingerprints[key]}
                for key in sorted(event_fingerprints)
            ],
        })
    if scenario_missing:
        report.add("science.scenarios.documents", "each S00-S15 input must reconstruct deterministically from its atomic JSON Pointer rows", details=scenario_missing)
    if scenario_errors:
        report.add("science.scenarios.input_only", "scenario inputs violate their frozen profile", details=scenario_errors)
    oracle_missing: list[str] = []
    oracle_errors: list[dict[str, Any]] = []
    qa_decisions = [item for item in provenance.get("decisions", []) if item.get("id") == "T03-QA-011"]
    diagnostic_priority = (
        qa_decisions[0].get("decision", {}).get("diagnostic_priority", [])
        if len(qa_decisions) == 1
        else []
    )
    diagnostic_rank = {code: index for index, code in enumerate(diagnostic_priority)}
    protected = {"expectedness", "desirability", "novelty", "pleasure", "goal_conduciveness"}
    six_fields = protected | {"coping_potential"}
    for index in range(16):
        scenario_id = f"S{index:02d}"
        path = f"oracles/{scenario_id}.expected.json"
        reconstructed, document = reconstruct_document(rows, parsed_values, path, report)
        if not reconstructed:
            oracle_missing.append(path)
            continue
        if not isinstance(document, dict):
            oracle_errors.append({"scenario": scenario_id, "reason": "document_not_object"})
            continue
        if set(document) != required_oracle_fields:
            oracle_errors.append({
                "scenario": scenario_id,
                "reason": "closed_outer_shape_violation",
                "missing": sorted(required_oracle_fields - set(document)),
                "extra": sorted(set(document) - required_oracle_fields),
            })
        fixed_outer = {
            "$schema": "../schemas/oracle.schema.json",
            "schema_version": "1.0.0",
            "oracle_class": "synthetic_conformance_oracle",
            "empirical_support": "none",
            "frozen_before_implementation": True,
            "oracle_id": f"{scenario_id}.expected",
            "scenario_id": scenario_id,
            "scenario_ref": f"scenarios/{scenario_id}.json",
        }
        wrong_outer = {key: {"actual": document.get(key), "expected": value} for key, value in fixed_outer.items() if document.get(key) != value}
        if wrong_outer:
            oracle_errors.append({"scenario": scenario_id, "reason": "outer_identity_or_fixed_value_mismatch", "fields": wrong_outer})
        expected = document.get("expected")
        if not isinstance(expected, dict) or set(expected) != required_expected_fields:
            oracle_errors.append({
                "scenario": scenario_id,
                "reason": "closed_expected_shape_violation",
                "actual_keys": sorted(expected) if isinstance(expected, dict) else None,
            })
        if scenario_id not in oracle_semantics or expected != oracle_semantics.get(scenario_id):
            oracle_errors.append({"scenario": scenario_id, "reason": "expected_semantics_mismatch"})
        output_contract = expected.get("output_contract") if isinstance(expected, dict) else None
        if isinstance(expected, dict):
            diagnostics = expected.get("diagnostics")
            if (
                not isinstance(diagnostics, list)
                or any(not isinstance(code, str) for code in diagnostics)
                or len(diagnostics) != len(set(diagnostics))
                or any(code not in diagnostic_rank for code in diagnostics)
                or diagnostics != sorted(diagnostics, key=lambda code: diagnostic_rank.get(code, len(diagnostic_rank)))
            ):
                oracle_errors.append({"scenario": scenario_id, "reason": "diagnostics_not_unique_ordered_code_class_array"})
            modulation = expected.get("modulation")
            if (
                not isinstance(modulation, dict)
                or set(modulation) != {"attempted", "formula_evaluated", "coping_potential_changed"}
                or any(type(value) is not bool for value in modulation.values())
            ):
                oracle_errors.append({"scenario": scenario_id, "reason": "modulation_closed_boolean_shape_invalid"})
            classification = expected.get("classification")
            classification_keys = {"attempted", "before", "after"} if isinstance(classification, dict) and classification.get("attempted") is True else {"attempted"}
            if (
                not isinstance(classification, dict)
                or set(classification) != classification_keys
                or type(classification.get("attempted")) is not bool
            ):
                oracle_errors.append({"scenario": scenario_id, "reason": "classification_closed_variant_invalid"})
            modulation_trace = expected.get("modulation_trace")
            exact_trace = (
                {"exists": False}
                if scenario_id == "S15"
                else {"exists": True, "path": f"traces/reference_run/{scenario_id}.trace.json"}
            )
            if modulation_trace != exact_trace:
                oracle_errors.append({"scenario": scenario_id, "reason": "modulation_trace_route_mismatch"})
            rejection_record = expected.get("rejection_record")
            exact_rejection = (
                {"exists": True, "path": "traces/reference_run/rejections/S15.rejection.json"}
                if scenario_id == "S15"
                else {"exists": False}
            )
            if rejection_record != exact_rejection:
                oracle_errors.append({"scenario": scenario_id, "reason": "rejection_record_route_mismatch"})
        if scenario_id == "S15":
            if not isinstance(output_contract, dict) or output_contract.get("exists") is not False:
                oracle_errors.append({"scenario": scenario_id, "reason": "rejected_case_output_contract_must_be_absent"})
            elif set(output_contract) != {"exists"}:
                oracle_errors.append({"scenario": scenario_id, "reason": "rejected_case_must_not_have_partial_output", "keys": sorted(output_contract)})
            if isinstance(expected, dict) and any(key in expected for key in ("output", "appraisal_vector")):
                oracle_errors.append({"scenario": scenario_id, "reason": "rejected_case_has_output_sibling"})
            if not isinstance(expected, dict) or expected.get("disposition") != "rejected":
                oracle_errors.append({"scenario": scenario_id, "reason": "rejection_disposition_missing"})
        else:
            if not isinstance(output_contract, dict) or output_contract.get("exists") is not True:
                oracle_errors.append({"scenario": scenario_id, "reason": "output_contract_must_exist"})
                continue
            output = output_contract.get("appraisal_vector")
            if output_contract.get("protected_dimensions") != "equal_to_scenario_baseline":
                oracle_errors.append({"scenario": scenario_id, "reason": "protected_dimensions_contract_missing"})
            if set(output_contract) != {"exists", "appraisal_vector", "protected_dimensions"}:
                oracle_errors.append({"scenario": scenario_id, "reason": "output_contract_shape_invalid", "keys": sorted(output_contract)})
            if not isinstance(output, dict) or set(output) != six_fields:
                oracle_errors.append({"scenario": scenario_id, "reason": "full_six_vector_output_missing"})
            else:
                baseline = scenario_values.get(scenario_id, {}).get("baseline", {})
                changed = sorted(field for field in protected if output.get(field) != baseline.get(field))
                if changed:
                    oracle_errors.append({"scenario": scenario_id, "reason": "protected_values_changed", "fields": changed})
    if oracle_missing:
        report.add("science.oracles.documents", "exactly one frozen oracle is required for each S00-S15", details=oracle_missing)
    if oracle_errors:
        report.add("science.oracles.contract", "oracles do not freeze complete and protected outputs", details=oracle_errors)
    report.metrics["scenario_oracle_counts"] = {
        "oracle_documents": 16 - len(oracle_missing),
        "scenario_documents": 16 - len(scenario_missing),
        "targeted_oracles": len(targeted_oracles),
        "targeted_scenarios": len(targeted_scenarios),
    }


def validate_planned_set(
    provenance: dict[str, Any], set_id: str, expected_paths: set[str], report: Report
) -> None:
    matches = [item for item in provenance.get("planned_file_sets", []) if item.get("set_id") == set_id]
    if len(matches) != 1:
        report.add("provenance.file_set", f"{set_id} must occur exactly once", details={"count": len(matches)})
        return
    item = matches[0]
    actual = set(item.get("paths", []))
    if actual != expected_paths or item.get("expected_count") != len(expected_paths):
        report.add(
            "provenance.file_set.paths",
            f"{set_id} does not declare the exact expected paths",
            details={"missing": sorted(expected_paths - actual), "extra": sorted(actual - expected_paths), "expected_count": item.get("expected_count")},
        )


def validate_trace_schema_contract(
    rows: list[dict[str, str]], parsed_values: dict[str, Any], provenance: dict[str, Any], report: Report
) -> None:
    decision_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in provenance.get("decisions", []):
        if isinstance(item, dict) and item.get("id"):
            decision_records[item["id"]].append(item)
    decision_index = {
        item.get("id"): item
        for item in provenance.get("decisions", [])
        if isinstance(item, dict) and item.get("id")
    }
    qa = decision_index.get("T03-QA-011", {}).get("decision", {})
    rp = decision_index.get("T03-RP-012", {}).get("decision", {})
    mp = decision_index.get("T03-MP-013", {}).get("decision", {})
    errors: list[dict[str, Any]] = []
    required_trace_decisions = (
        "T03-BL-006", "T03-RS-005", "T03-TM-004", "T03-CT-009",
        "T03-QA-011", "T03-RP-012", "T03-MP-013",
    )
    bad_decision_cardinality = {
        decision_id: len(decision_records.get(decision_id, []))
        for decision_id in required_trace_decisions
        if len(decision_records.get(decision_id, [])) != 1
        or mapped_decision_status(
            str((decision_records.get(decision_id) or [{}])[0].get("status", ""))
        ) != "approved"
    }
    if bad_decision_cardinality:
        errors.append({
            "reason": "trace_authority_not_exactly_one_approved_record",
            "decisions": bad_decision_cardinality,
        })
    seed = qa.get("trace_schema_document_seed") if isinstance(qa, dict) else None
    trace_contract = qa.get("trace_contract", {}) if isinstance(qa, dict) else {}
    frozen_contract_hashes = {
        "trace_contract": "9392030895e89cf1a2876978b54268d4c5b1278e7b1d85470a7e31b9dbf3828a",
        "trace_schema_document_seed": "9397f87471463848df1545d1393861155e2d480428f86bc519ddbac80b0bcc47",
        "trace_result_projection_contract": "5feb75f80b00747295b6166fc477ec82d18b0081327b32ec7e614cb66e006058",
        "trace_materialization_template": "1d2c77eba838b6f212dce46982197306486626f7246b30bd18d2f6170a3d1da6",
    }
    for contract_name, expected_hash in frozen_contract_hashes.items():
        contract_value = qa.get(contract_name) if isinstance(qa, dict) else None
        if not isinstance(contract_value, dict):
            continue
        encoded_contract = json.dumps(
            contract_value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        actual_hash = hashlib.sha256(encoded_contract).hexdigest()
        if actual_hash != expected_hash:
            errors.append({
                "reason": "frozen_trace_contract_hash_mismatch",
                "contract": contract_name,
                "actual": actual_hash,
                "expected": expected_hash,
            })
    components = ["event", "state", "baseline", "output", "policy", "mask", "formula", "classification", "versions"]
    top_fields = {"$schema", "schema_version", "scenario_id", "evaluation_time", "disposition", "diagnostics", "trace_core", "trace_id"}
    expected_diagnostic_priority = [
        "HOST_BASELINE_MISSING_FIELD", "HOST_BASELINE_TYPE_INVALID", "HOST_BASELINE_OUT_OF_RANGE",
        "FACTOR_STATE_MISSING", "FACTOR_STATE_TYPE_INVALID", "FACTOR_LEVEL_MISSING",
        "FACTOR_LEVEL_TYPE_INVALID", "FACTOR_LEVEL_OUT_OF_RANGE", "FACTOR_CONFIDENCE_MISSING",
        "FACTOR_CONFIDENCE_TYPE_INVALID", "FACTOR_CONFIDENCE_OUT_OF_RANGE", "FACTOR_CONFIDENCE_BELOW_MIN",
        "FACTOR_OBSERVED_AT_MISSING", "FACTOR_OBSERVED_AT_INVALID", "FACTOR_STATE_STALE",
        "FACTOR_STATE_FROM_FUTURE", "FACTOR_SOURCE_ID_MISSING", "FACTOR_SOURCE_ID_TYPE_INVALID",
        "FACTOR_SCHEMA_VERSION_MISSING", "FACTOR_SCHEMA_VERSION_TYPE_INVALID",
        "FACTOR_SCHEMA_VERSION_UNSUPPORTED", "PUBLISHED_SUBSET_AMBIGUOUS",
    ]
    expected_diagnostics_schema = {
        "type": "array",
        "items": {"type": "string", "enum": expected_diagnostic_priority},
        "uniqueItems": True,
        "x-ifm6-priority-order": expected_diagnostic_priority,
    }
    expected_disposition_schema = {
        "type": "string",
        "enum": ["applied_no_change", "modulated", "abstained"],
    }
    expected_trace_properties = {
        "$schema": {"type": "string", "const": "../../schemas/trace.schema.json"},
        "schema_version": {"type": "string", "const": "1.0.0"},
        "scenario_id": {"type": "string", "pattern": "^S(?:0[0-9]|1[0-4])$"},
        "evaluation_time": {"type": "string", "const": "2026-09-04T12:00:00Z"},
        "disposition": expected_disposition_schema,
        "diagnostics": expected_diagnostics_schema,
        "trace_core": {"$ref": "#/$defs/trace_core"},
        "trace_id": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
            "x-ifm6-value": "sha256(IFM6-JSON-v1 canonical trace_core)",
        },
    }
    if not isinstance(seed, dict):
        errors.append({"reason": "trace_schema_document_seed_missing"})
    else:
        properties = seed.get("properties", {})
        definitions = seed.get("$defs", {})
        trace_core_schema = definitions.get("trace_core", {}) if isinstance(definitions, dict) else {}
        diagnostics_schema = properties.get("diagnostics", {}) if isinstance(properties, dict) else {}
        trace_id_schema = properties.get("trace_id", {}) if isinstance(properties, dict) else {}
        if (
            seed.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
            or seed.get("$id") != "urn:acme-firm:ifatigue-infra6-m6:schemas:trace:1.0.0"
            or seed.get("title") != "IFATIGUE-INFRA6-M6 Trace Schema 1.0.0"
            or seed.get("description") != "Normative, not-yet-materialized schema seed for traces/reference_run/S00.trace.json through S14.trace.json; it makes no execution or conformance claim."
            or seed.get("type") != "object"
            or seed.get("additionalProperties") is not False
            or set(seed.get("required", [])) != top_fields
            or properties != expected_trace_properties
            or qa.get("diagnostic_priority") != expected_diagnostic_priority
            or trace_contract.get("trace_core_components_in_semantic_order") != components
            or trace_contract.get("component_count") != 9
            or trace_core_schema.get("type") != "object"
            or trace_core_schema.get("additionalProperties") is not False
            or trace_core_schema.get("required") != components
            or set(trace_core_schema.get("properties", {})) != set(components)
            or diagnostics_schema.get("type") != "array"
            or diagnostics_schema.get("items", {}).get("type") != "string"
            or diagnostics_schema.get("items", {}).get("enum") != qa.get("diagnostic_priority")
            or diagnostics_schema.get("uniqueItems") is not True
            or diagnostics_schema.get("x-ifm6-priority-order") != qa.get("diagnostic_priority")
            or trace_id_schema.get("pattern") != "^[0-9a-f]{64}$"
            or trace_id_schema.get("x-ifm6-value") != "sha256(IFM6-JSON-v1 canonical trace_core)"
            or properties.get("scenario_id", {}).get("pattern") != "^S(?:0[0-9]|1[0-4])$"
        ):
            errors.append({"reason": "trace_schema_seed_not_closed_or_semantically_exact"})
        for nullable_name, reference in (
            ("state", "#/$defs/factor_state"),
            ("formula", "#/$defs/formula_record"),
            ("classification", "#/$defs/classification_record"),
        ):
            alternatives = trace_core_schema.get("properties", {}).get(nullable_name, {}).get("oneOf", [])
            if alternatives != [{"type": "null"}, {"$ref": reference}]:
                errors.append({"reason": "trace_core_nullable_union_mismatch", "component": nullable_name})
        open_definitions = sorted(
            name
            for name, definition in definitions.items()
            if isinstance(definition, dict)
            and definition.get("type") == "object"
            and definition.get("additionalProperties") is not False
        )
        if open_definitions:
            errors.append({"reason": "trace_schema_contains_open_object_definition", "definitions": open_definitions})
    reconstructed, schema_document = reconstruct_document(rows, parsed_values, "schemas/trace.schema.json", report)
    if not reconstructed or schema_document != seed:
        errors.append({"reason": "trace_schema_ledger_projection_mismatch"})
    schema_rows = [
        row for row in rows
        if active(row)
        and row.get("target_path") == "schemas/trace.schema.json"
        and row.get("target_locator") != "@materialization-recipe"
    ]
    qa_support = {"T03-QA-011"}
    qa_rp_support = {"T03-QA-011", "T03-RP-012"}
    expected_schema_support_ids: dict[str, set[str]] = {
        "/$schema": qa_rp_support,
        "/$id": qa_rp_support,
        "/title": qa_support,
        "/description": qa_support,
        "/type": qa_support,
        "/required": qa_support,
        "/additionalProperties": qa_support,
        "/properties/$schema": qa_rp_support,
        "/properties/schema_version": qa_rp_support,
        "/properties/scenario_id": {"T03-BL-006", "T03-QA-011"},
        "/properties/evaluation_time": {"T03-BL-006", "T03-TM-004", "T03-QA-011"},
        "/properties/disposition": {"T03-CT-009", "T03-QA-011"},
        "/properties/diagnostics": {"T03-CT-009", "T03-QA-011"},
        "/properties/trace_core": qa_support,
        "/properties/trace_id": qa_rp_support,
        "/$defs/decimal_string": qa_rp_support,
        "/$defs/event": {"T03-BL-006", "T03-QA-011"},
        "/$defs/factor_state": {"T03-BL-006", "T03-TM-004", "T03-CT-009", "T03-QA-011"},
        "/$defs/appraisal_vector": {"T03-BL-006", "T03-RS-005", "T03-QA-011", "T03-RP-012"},
        "/$defs/policy": {"T03-TM-004", "T03-CT-009", "T03-QA-011", "T03-RP-012"},
        "/$defs/mask": {"T03-RS-005", "T03-QA-011"},
        "/$defs/formula_record": {"T03-RS-005", "T03-QA-011", "T03-RP-012"},
        "/$defs/classification_record": {"T03-RS-005", "T03-QA-011"},
        "/$defs/versions": qa_rp_support,
        "/$defs/trace_core": qa_support,
    }
    actual_schema_locators = {row.get("target_locator", "") for row in schema_rows}
    if actual_schema_locators != set(expected_schema_support_ids):
        errors.append({
            "reason": "trace_schema_semantic_atom_set_mismatch",
            "missing": sorted(set(expected_schema_support_ids) - actual_schema_locators),
            "extra": sorted(actual_schema_locators - set(expected_schema_support_ids)),
        })
    for locator, expected_ids in sorted(expected_schema_support_ids.items()):
        locator_rows = [row for row in schema_rows if row.get("target_locator") == locator]
        supports = {support_edge(row) for row in locator_rows}
        expected_supports = {decision_edge(decision_id) for decision_id in expected_ids}
        if (
            supports != expected_supports
            or len(locator_rows) != len(expected_supports)
            or any(row.get("transformation_type") != "automatic_derivation" for row in locator_rows)
            or any(row.get("claim_ref", "") for row in locator_rows)
            or any(row.get("claim_provenance_class") != "generated_for_doctoral_instance" for row in locator_rows)
        ):
            errors.append({
                "reason": "trace_schema_atom_support_mismatch",
                "locator": locator,
                "actual": sorted(supports),
                "expected": sorted(expected_supports),
            })
    schema_support_union = {
        row.get("support_ref_id", "")
        for row in schema_rows
        if row.get("support_ref_type") == "approved_decision" and row.get("support_level") == "direct"
    }
    if schema_support_union != {
        "T03-BL-006", "T03-RS-005", "T03-TM-004", "T03-CT-009", "T03-QA-011", "T03-RP-012",
    }:
        errors.append({"reason": "trace_schema_support_union_mismatch", "actual": sorted(schema_support_union)})

    template = qa.get("trace_materialization_template") if isinstance(qa, dict) else None
    projection = qa.get("trace_result_projection_contract") if isinstance(qa, dict) else None
    scenario_ids = [f"S{index:02d}" for index in range(15)]
    recipe_fields = [
        "recipe_id", "template", "scenario", "oracle", "result", "trace", "schema",
        "trace_id_policy", "canonicalization_profile", "population_variant",
    ]
    expected_variant = {
        **{f"S{index:02d}": "FORMULA_RECORD_CLASSIFICATION_NULL" for index in range(7)},
        **{f"S{index:02d}": "FORMULA_NULL_CLASSIFICATION_NULL" for index in range(7, 14)},
        "S14": "FORMULA_RECORD_CLASSIFICATION_RECORD",
    }
    expected_recipes = [
        {
            "recipe_id": f"TRACE-BIND-{sid}",
            "template": "IFM6-TRACE-MATERIALIZATION-1.0.0",
            "scenario": f"scenarios/{sid}.json",
            "oracle": f"oracles/{sid}.expected.json",
            "result": f"results/reference_run/{sid}.result.json",
            "trace": f"traces/reference_run/{sid}.trace.json",
            "schema": "schemas/trace.schema.json",
            "trace_id_policy": "sha256(IFM6-JSON-v1 canonical trace_core)",
            "canonicalization_profile": "IFM6-JSON-v1",
            "population_variant": expected_variant[sid],
        }
        for sid in scenario_ids
    ]
    exact_population_variants = {
        "FORMULA_RECORD_CLASSIFICATION_NULL": {
            "scenario_ids": scenario_ids[:7],
            "formula": "formula_records_by_scenario/{scenario_id}",
            "classification": None,
        },
        "FORMULA_NULL_CLASSIFICATION_NULL": {
            "scenario_ids": scenario_ids[7:14],
            "formula": None,
            "classification": None,
        },
        "FORMULA_RECORD_CLASSIFICATION_RECORD": {
            "scenario_ids": ["S14"],
            "formula": "formula_records_by_scenario/S14",
            "classification": "classification_records_by_scenario/S14",
        },
    }
    expected_formula_scenarios = scenario_ids[:7] + ["S14"]
    expected_formula_records = {
        "S00": {"formula_id": "F6-COPING-MOD-001", "coping_potential_in": "0.6", "lambda": "0.3", "factor_level": "0", "multiplicative_factor": "1", "raw_result": "0.6", "bounded_result": "0.6"},
        "S01": {"formula_id": "F6-COPING-MOD-001", "coping_potential_in": "0.6", "lambda": "0.3", "factor_level": "0.2", "multiplicative_factor": "0.94", "raw_result": "0.564", "bounded_result": "0.564"},
        "S02": {"formula_id": "F6-COPING-MOD-001", "coping_potential_in": "0.6", "lambda": "0.3", "factor_level": "0.5", "multiplicative_factor": "0.85", "raw_result": "0.51", "bounded_result": "0.51"},
        "S03": {"formula_id": "F6-COPING-MOD-001", "coping_potential_in": "0.6", "lambda": "0.3", "factor_level": "0.8", "multiplicative_factor": "0.76", "raw_result": "0.456", "bounded_result": "0.456"},
        "S04": {"formula_id": "F6-COPING-MOD-001", "coping_potential_in": "0.6", "lambda": "0.3", "factor_level": "1", "multiplicative_factor": "0.7", "raw_result": "0.42", "bounded_result": "0.42"},
        "S05": {"formula_id": "F6-COPING-MOD-001", "coping_potential_in": "0", "lambda": "0.3", "factor_level": "1", "multiplicative_factor": "0.7", "raw_result": "0", "bounded_result": "0"},
        "S06": {"formula_id": "F6-COPING-MOD-001", "coping_potential_in": "1", "lambda": "0.3", "factor_level": "0", "multiplicative_factor": "1", "raw_result": "1", "bounded_result": "1"},
        "S14": {"formula_id": "F6-COPING-MOD-001", "coping_potential_in": "0.35", "lambda": "0.3", "factor_level": "1", "multiplicative_factor": "0.7", "raw_result": "0.245", "bounded_result": "0.245"},
    }
    expected_fixed_policy = {
        "qa_contract_id": "IFM6-QA-CONTRACT-1.0.0",
        "factor_contract_decision_id": "T03-CT-009",
        "temporal_policy_decision_id": "T03-TM-004",
        "evaluation_time": "2026-09-04T12:00:00Z",
        "validation_order": ["host_baseline", "factor_state"],
        "min_confidence": "0.5",
        "max_age_seconds": 300,
        "future_tolerance_seconds": 5,
        "stale_operator": ">=",
        "future_operator": ">",
    }
    expected_fixed_mask = {
        "writable_coordinate": "coping_potential",
        "protected_coordinates": ["expectedness", "desirability", "novelty", "pleasure", "goal_conduciveness"],
    }
    expected_fixed_versions = {
        "package_version": "1.1.0",
        "artifact_internal_version": "1.0.0",
        "scenario_schema_version": "1.0.0",
        "trace_schema_version": "1.0.0",
        "resolved_specification_version": "1.1.0",
        "qa_contract_id": "IFM6-QA-CONTRACT-1.0.0",
    }
    expected_hash_policy = {
        "canonicalization_profile": "IFM6-JSON-v1",
        "preimage_scope": "trace_core and no wrapper field",
        "preimage_bytes": "UTF-8 of json.dumps(trace_core, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) without terminal LF",
        "algorithm": "SHA-256",
        "trace_id_encoding": "64 lowercase hexadecimal characters",
        "evaluation_time_inclusion": "included through trace_core.policy.evaluation_time and required byte-equivalent to wrapper evaluation_time and scenario evaluation_time",
        "excluded": ["trace_id", "wrapper fields outside trace_core", "execution_time", "duration", "operating_system", "absolute_paths", "volatile_metadata"],
    }
    expected_outer_bindings = {
        "$schema": "literal ../../schemas/trace.schema.json",
        "schema_version": "literal 1.0.0",
        "scenario_id": "scenario#/scenario_id",
        "evaluation_time": "scenario#/evaluation_time; must equal trace_core#/policy/evaluation_time and 2026-09-04T12:00:00Z",
        "disposition": "trace_result_projection#/disposition, selected from result#/disposition after exact equality with oracle#/expected/disposition",
        "diagnostics": "trace_result_projection#/diagnostics, selected from result#/diagnostics after exact array equality with oracle#/expected/diagnostics and validation of uniqueness plus priority order",
        "trace_core": "assemble exactly the nine component bindings below",
        "trace_id": "lowercase SHA-256 of the IFM6-JSON-v1 canonical UTF-8 preimage of trace_core only",
    }
    expected_core_bindings = {
        "event": "exact deep copy of scenario#/event",
        "state": "exact deep copy of scenario#/factor_state; JSON null only for S07",
        "baseline": "exact deep copy of scenario#/baseline",
        "output": "exact deep copy of trace_result_projection#/output, selected from result#/output after exact equality with oracle#/expected/output_contract/appraisal_vector",
        "policy": "exact fixed_policy object below; policy/evaluation_time must equal scenario#/evaluation_time and wrapper#/evaluation_time",
        "mask": "exact fixed_mask object below",
        "formula": "exact formula_records_by_scenario entry for S00-S06 or S14; JSON null for S07-S13",
        "classification": "exact classification_records_by_scenario/S14 entry for S14; JSON null for S00-S13",
        "versions": "exact fixed_versions object below",
    }
    expected_component_authorities = {
        "event_state_baseline_and_evaluation_time": "frozen scenario selected through scenarios/catalog.json under T03-BL-006",
        "output_disposition_and_diagnostics": "reference-derived values selected through T03-QA-011.trace_result_projection_contract after result-schema validation and exact equality checks against the frozen SNN.expected oracle; values are never copied from the oracle",
        "policy": "config/resolved_instance.json plus T03-CT-009 and T03-TM-004",
        "mask": "spec/thesis/f6_specification_rc01.json plus T03-RS-005",
        "formula_and_classification": "execution record constrained by T03-RS-005 and the population variant below",
        "versions": "frozen package, schema and contract identifiers declared below",
        "canonicalization_and_trace_id": "T03-RP-012 IFM6-JSON-v1 and SHA-256 profile",
        "generation_topology": "T03-MP-013",
    }
    expected_runtime_authority = (
        "after freeze, read only the materialized scenario, oracle, result, schema, resolved configuration and specification files; "
        "PROVENANCE construction seeds are not runtime fallbacks, and every result-fed value must pass trace_result_projection_contract"
    )
    expected_validation_contract = [
        "materialize schemas/trace.schema.json as the exact IFM6-JSON-v1 canonical projection of trace_schema_document_seed before the reference run",
        "validate each S00-S14 trace against that materialized schema and reject any missing or additional field at every object level",
        "before trace assembly, validate each S00-S14 result against schemas/result.schema.json and build the exact closed five-field trace_result_projection_contract projection from result pointers only",
        "require wrapper evaluation_time, scenario evaluation_time and trace_core.policy.evaluation_time to be byte-identical",
        "require the projected scenario_id and evaluation_time to equal the scenario, and projected disposition, diagnostics and output to equal the frozen oracle, without copying oracle values into the result projection",
        "require diagnostics to contain unique code strings in the fixed T03-QA-011 priority order",
        "require exactly one binding recipe and the declared population variant for every S00-S14",
        "recompute trace_id from trace_core only under IFM6-JSON-v1 and require exact lowercase SHA-256 equality",
        "prohibit S15.trace.json and require the separate S15 rejection contract instead",
    ]
    expected_template_fields = {
        "template_id", "execution_or_materialization_claimed", "target_path_template", "schema_seed_source",
        "supports", "component_authorities", "runtime_authority_rule", "instance_required_fields",
        "trace_core_required_fields", "outer_field_bindings", "trace_core_bindings", "fixed_policy",
        "fixed_mask", "fixed_versions", "formula_records_by_scenario", "classification_records_by_scenario",
        "population_variants", "canonicalization_and_trace_id_policy", "binding_recipe_contract",
        "binding_recipes", "S15_exclusion", "validation_contract",
    }
    exact_s15_exclusion = {
        "scenario_id": "S15",
        "trace_recipe_present": False,
        "trace_path_prohibited": "traces/reference_run/S15.trace.json",
        "replacement_artifact": "traces/reference_run/rejections/S15.rejection.json",
        "reason": "host rejection precedes factor validation and modulation",
    }
    if not isinstance(template, dict):
        errors.append({"reason": "trace_materialization_template_missing"})
        binding_recipes: list[Any] = []
    else:
        binding_recipes = template.get("binding_recipes", [])
        recipe_contract = template.get("binding_recipe_contract", {})
        hash_policy = template.get("canonicalization_and_trace_id_policy", {})
        if (
            set(template) != expected_template_fields
            or template.get("template_id") != "IFM6-TRACE-MATERIALIZATION-1.0.0"
            or template.get("target_path_template") != "traces/reference_run/SNN.trace.json for S00-S14 only"
            or template.get("execution_or_materialization_claimed") is not False
            or template.get("instance_required_fields") != [
                "$schema", "schema_version", "scenario_id", "evaluation_time", "disposition",
                "diagnostics", "trace_core", "trace_id",
            ]
            or template.get("trace_core_required_fields") != components
            or template.get("outer_field_bindings") != expected_outer_bindings
            or template.get("trace_core_bindings") != expected_core_bindings
            or template.get("supports") != [
                "T03-BL-006", "T03-RS-005", "T03-TM-004", "T03-CT-009",
                "T03-QA-011", "T03-RP-012", "T03-MP-013",
            ]
            or template.get("population_variants") != exact_population_variants
            or template.get("formula_records_by_scenario") != expected_formula_records
            or template.get("classification_records_by_scenario") != {
                "S14": {
                    "published_rule_ref": "RULE-ANGER-2018B-CONSISTENT",
                    "before": "unclassified_by_published_subset",
                    "after": "anger",
                }
            }
            or recipe_contract.get("required_fields") != recipe_fields
            or recipe_contract.get("allowed_fields") != recipe_fields
            or recipe_contract.get("additionalProperties") is not False
            or recipe_contract.get("one_to_one_rule") != "exactly one recipe for each S00-S14 and none for S15"
            or binding_recipes != expected_recipes
            or template.get("S15_exclusion") != exact_s15_exclusion
            or hash_policy != expected_hash_policy
            or template.get("fixed_policy") != expected_fixed_policy
            or template.get("fixed_mask") != expected_fixed_mask
            or template.get("fixed_versions") != expected_fixed_versions
            or template.get("component_authorities") != expected_component_authorities
            or template.get("runtime_authority_rule") != expected_runtime_authority
            or template.get("schema_seed_source") != "T03-QA-011.trace_schema_document_seed -> schemas/trace.schema.json"
            or template.get("validation_contract") != expected_validation_contract
        ):
            errors.append({"reason": "trace_materialization_template_not_closed_or_exact"})
        formula_records = template.get("formula_records_by_scenario", {})
        formula_fields = {
            "formula_id", "coping_potential_in", "lambda", "factor_level",
            "multiplicative_factor", "raw_result", "bounded_result",
        }
        bad_formula_records = sorted(
            sid for sid in expected_formula_scenarios
            if not isinstance(formula_records.get(sid), dict)
            or set(formula_records[sid]) != formula_fields
        )
        if bad_formula_records:
            errors.append({"reason": "trace_formula_record_shape_mismatch", "scenarios": bad_formula_records})

    decimal_pattern = "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$"
    vector_fields = ["expectedness", "desirability", "novelty", "pleasure", "goal_conduciveness", "coping_potential"]
    expected_decimal_property = {
        "type": "string", "pattern": decimal_pattern, "x-ifm6-profile": "IFM6-DEC-v1",
    }
    expected_projection_output_schema = {
        "type": "object",
        "required": vector_fields,
        "additionalProperties": False,
        "properties": {field: expected_decimal_property for field in vector_fields},
    }
    expected_projection_properties = {
        "scenario_id": {"type": "string", "pattern": "^S(?:0[0-9]|1[0-4])$"},
        "evaluation_time": {"type": "string", "const": "2026-09-04T12:00:00Z"},
        "disposition": expected_disposition_schema,
        "diagnostics": expected_diagnostics_schema,
        "output": expected_projection_output_schema,
    }
    expected_projection_scope = {
        "scenario_ids": scenario_ids,
        "source_path_template": "results/reference_run/SNN.result.json",
        "source_schema": "schemas/result.schema.json",
        "excluded_scenario": "S15",
        "execution_or_observation_claimed": False,
    }
    if not isinstance(projection, dict):
        errors.append({"reason": "trace_result_projection_contract_missing"})
    else:
        projection_schema = projection.get("projection_schema", {})
        projection_properties = projection_schema.get("properties", {}) if isinstance(projection_schema, dict) else {}
        output_schema = projection_properties.get("output", {}) if isinstance(projection_properties, dict) else {}
        output_properties = output_schema.get("properties", {}) if isinstance(output_schema, dict) else {}
        diagnostics_projection = projection_properties.get("diagnostics", {}) if isinstance(projection_properties, dict) else {}
        if (
            set(projection) != {
                "contract_id", "purpose", "scope", "required_source_pointers", "projection_bindings",
                "projection_schema", "source_validation_precondition", "cross_source_equality",
                "data_origin_rule", "runtime_authority_rule", "failure_policy",
            }
            or projection.get("contract_id") != "IFM6-TRACE-RESULT-PROJECTION-1.0.0"
            or projection.get("required_source_pointers") != [
                "/scenario_id", "/evaluation_time", "/disposition", "/diagnostics", "/output",
            ]
            or projection.get("projection_bindings") != {
                "scenario_id": "result#/scenario_id",
                "evaluation_time": "result#/evaluation_time",
                "disposition": "result#/disposition",
                "diagnostics": "result#/diagnostics",
                "output": "result#/output",
            }
            or projection.get("scope") != expected_projection_scope
            or projection_schema.get("type") != "object"
            or projection_schema.get("additionalProperties") is not False
            or projection_schema.get("required") != [
                "scenario_id", "evaluation_time", "disposition", "diagnostics", "output",
            ]
            or projection_properties != expected_projection_properties
            or output_schema.get("type") != "object"
            or output_schema.get("additionalProperties") is not False
            or output_schema.get("required") != vector_fields
            or set(output_properties) != set(vector_fields)
            or any(
                output_properties.get(field) != expected_decimal_property
                for field in vector_fields
            )
            or diagnostics_projection.get("type") != "array"
            or diagnostics_projection.get("items", {}).get("type") != "string"
            or diagnostics_projection.get("items", {}).get("enum") != qa.get("diagnostic_priority")
            or diagnostics_projection.get("uniqueItems") is not True
            or diagnostics_projection.get("x-ifm6-priority-order") != qa.get("diagnostic_priority")
        ):
            errors.append({"reason": "trace_result_projection_not_closed_or_exact"})

    def require_projection(
        path: str,
        locator: str,
        expected_value: Any,
        expected_support_ids: set[str],
        transformation_type: str,
    ) -> None:
        matches = [
            row for row in rows
            if active(row) and row.get("target_path") == path and row.get("target_locator") == locator
        ]
        supports = {support_edge(row) for row in matches}
        expected_support_set = {decision_edge(decision_id) for decision_id in expected_support_ids}
        values = {
            json.dumps(parsed_values.get(row.get("row_id", "")), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for row in matches
        }
        expected_json = json.dumps(expected_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if (
            values != {expected_json}
            or supports != expected_support_set
            or len(matches) != len(expected_support_set)
            or any(row.get("transformation_type") != transformation_type for row in matches)
            or any(row.get("claim_ref", "") for row in matches)
            or any(row.get("claim_provenance_class") != "generated_for_doctoral_instance" for row in matches)
        ):
            errors.append({
                "reason": "trace_contract_ledger_projection_mismatch",
                "path": path,
                "locator": locator,
                "actual_supports": sorted(supports),
            })

    decisions_path = "spec/decisions/engineering_v1.1.0.json"
    projection_prefix = "/trace_result_projection_contract"
    expected_projection_support_ids: dict[str, set[str]] = {
        f"{projection_prefix}/contract_id": {"T03-QA-011"},
        f"{projection_prefix}/purpose": {"T03-QA-011"},
        f"{projection_prefix}/scope": {"T03-BL-006", "T03-QA-011"},
        f"{projection_prefix}/source_validation_precondition": {"T03-QA-011", "T03-RP-012"},
        f"{projection_prefix}/required_source_pointers": {"T03-QA-011", "T03-RP-012"},
        f"{projection_prefix}/projection_schema/type": {"T03-QA-011"},
        f"{projection_prefix}/projection_schema/required": {"T03-QA-011"},
        f"{projection_prefix}/projection_schema/additionalProperties": {"T03-QA-011"},
        f"{projection_prefix}/projection_schema/properties/scenario_id": {"T03-BL-006", "T03-QA-011"},
        f"{projection_prefix}/projection_schema/properties/evaluation_time": {"T03-BL-006", "T03-QA-011"},
        f"{projection_prefix}/projection_schema/properties/disposition": {"T03-CT-009", "T03-QA-011"},
        f"{projection_prefix}/projection_schema/properties/diagnostics": {"T03-CT-009", "T03-QA-011"},
        f"{projection_prefix}/projection_schema/properties/output/type": {"T03-BL-006", "T03-QA-011", "T03-RP-012"},
        f"{projection_prefix}/projection_schema/properties/output/required": {"T03-BL-006", "T03-QA-011", "T03-RP-012"},
        f"{projection_prefix}/projection_schema/properties/output/additionalProperties": {"T03-BL-006", "T03-QA-011", "T03-RP-012"},
        f"{projection_prefix}/data_origin_rule": {"T03-QA-011", "T03-RP-012"},
        f"{projection_prefix}/runtime_authority_rule": {"T03-QA-011", "T03-RP-012"},
        f"{projection_prefix}/failure_policy": {"T03-CT-009", "T03-QA-011", "T03-RP-012"},
    }
    for field in vector_fields:
        expected_projection_support_ids[
            f"{projection_prefix}/projection_schema/properties/output/properties/{field}"
        ] = {"T03-BL-006", "T03-QA-011", "T03-RP-012"}
    for field in ("scenario_id", "evaluation_time", "disposition", "diagnostics", "output"):
        expected_projection_support_ids[f"{projection_prefix}/projection_bindings/{field}"] = {
            "T03-QA-011", "T03-RP-012",
        }
    for field in ("scenario_id", "evaluation_time"):
        expected_projection_support_ids[f"{projection_prefix}/cross_source_equality/{field}"] = {
            "T03-BL-006", "T03-QA-011",
        }
    for field in ("disposition", "diagnostics"):
        expected_projection_support_ids[f"{projection_prefix}/cross_source_equality/{field}"] = {
            "T03-CT-009", "T03-QA-011",
        }
    expected_projection_support_ids[f"{projection_prefix}/cross_source_equality/output"] = {
        "T03-BL-006", "T03-QA-011", "T03-RP-012",
    }
    projection_rows = [
        row for row in rows
        if active(row)
        and row.get("target_path") == decisions_path
        and (
            row.get("target_locator", "") == projection_prefix
            or row.get("target_locator", "").startswith(f"{projection_prefix}/")
        )
    ]
    actual_projection_locators = {row.get("target_locator", "") for row in projection_rows}
    if actual_projection_locators != set(expected_projection_support_ids):
        errors.append({
            "reason": "trace_result_projection_atom_set_mismatch",
            "missing": sorted(set(expected_projection_support_ids) - actual_projection_locators),
            "extra": sorted(actual_projection_locators - set(expected_projection_support_ids)),
        })
    projection_root: Any = _UNSET
    projection_assignment_errors: list[dict[str, str]] = []
    for locator, expected_ids in sorted(expected_projection_support_ids.items()):
        locator_rows = [row for row in projection_rows if row.get("target_locator") == locator]
        supports = {support_edge(row) for row in locator_rows}
        expected_supports = {decision_edge(decision_id) for decision_id in expected_ids}
        values = {
            row.get("target_value", ""): parsed_values.get(row.get("row_id", ""))
            for row in locator_rows
        }
        if (
            len(values) != 1
            or supports != expected_supports
            or len(locator_rows) != len(expected_supports)
            or any(row.get("transformation_type") != "engineering_decision" for row in locator_rows)
            or any(row.get("claim_ref", "") for row in locator_rows)
            or any(row.get("claim_provenance_class") != "generated_for_doctoral_instance" for row in locator_rows)
        ):
            errors.append({
                "reason": "trace_result_projection_atom_support_mismatch",
                "locator": locator,
                "actual": sorted(supports),
                "expected": sorted(expected_supports),
            })
            continue
        relative_locator = locator[len(projection_prefix):]
        projection_root, assignment_error = assign_pointer(
            projection_root,
            pointer_tokens(relative_locator),
            next(iter(values.values())),
        )
        if assignment_error:
            projection_assignment_errors.append({"locator": locator, "reason": assignment_error})
    if projection_assignment_errors or has_unset(projection_root) or projection_root != projection:
        errors.append({
            "reason": "trace_result_projection_ledger_projection_mismatch",
            "assignment_errors": projection_assignment_errors,
        })
    projection_support_union = {
        row.get("support_ref_id", "")
        for row in projection_rows
        if row.get("support_ref_type") == "approved_decision" and row.get("support_level") == "direct"
    }
    if projection_support_union != {"T03-BL-006", "T03-CT-009", "T03-QA-011", "T03-RP-012"}:
        errors.append({"reason": "trace_result_projection_support_union_mismatch", "actual": sorted(projection_support_union)})
    if isinstance(template, dict):
        template_without_recipes = {key: value for key, value in template.items() if key != "binding_recipes"}
        require_projection(
            decisions_path,
            "/trace_materialization/template",
            template_without_recipes,
            {
                "T03-BL-006", "T03-RS-005", "T03-TM-004", "T03-CT-009",
                "T03-QA-011", "T03-RP-012", "T03-MP-013",
            },
            "engineering_decision",
        )
        for index, recipe in enumerate(expected_recipes):
            require_projection(
                decisions_path,
                f"/trace_materialization/binding_recipes/{index}",
                recipe,
                {"T03-QA-011", "T03-RP-012", "T03-MP-013"},
                "engineering_decision",
            )
            require_projection(
                f"traces/reference_run/S{index:02d}.trace.json",
                "@materialization-recipe",
                recipe,
                {"T03-QA-011", "T03-RP-012", "T03-MP-013"},
                "automatic_derivation",
            )
    expected_materialization_locators = {
        "/trace_materialization/template",
        *(f"/trace_materialization/binding_recipes/{index}" for index in range(15)),
    }
    actual_materialization_locators = {
        row.get("target_locator", "")
        for row in rows
        if active(row)
        and row.get("target_path") == decisions_path
        and (
            row.get("target_locator", "") == "/trace_materialization"
            or row.get("target_locator", "").startswith("/trace_materialization/")
        )
    }
    if actual_materialization_locators != expected_materialization_locators:
        errors.append({
            "reason": "trace_materialization_namespace_not_closed",
            "missing": sorted(expected_materialization_locators - actual_materialization_locators),
            "extra": sorted(actual_materialization_locators - expected_materialization_locators),
        })
    active_trace_paths = {
        row.get("target_path", "")
        for row in rows
        if active(row) and row.get("target_path", "").startswith("traces/reference_run/S")
    }
    expected_trace_paths = {f"traces/reference_run/{sid}.trace.json" for sid in scenario_ids}
    if active_trace_paths != expected_trace_paths or "traces/reference_run/S15.trace.json" in active_trace_paths:
        errors.append({
            "reason": "trace_path_set_not_exact_S00_S14",
            "actual": sorted(active_trace_paths),
            "expected": sorted(expected_trace_paths),
        })
    for path in sorted(expected_trace_paths):
        active_locators = {
            row.get("target_locator", "")
            for row in rows if active(row) and row.get("target_path") == path
        }
        if active_locators != {"@materialization-recipe"}:
            errors.append({
                "reason": "planned_trace_namespace_not_recipe_only",
                "path": path,
                "actual": sorted(active_locators),
            })
    rp_trace_policy = provenance.get("engineering_reproducibility_profile", {}).get("trace_id_policy", {})
    if (
        rp_trace_policy.get("algorithm") != "SHA-256"
        or rp_trace_policy.get("input") != "canonical_json(trace_core)"
        or rp_trace_policy.get("included") != components
        or trace_contract.get("trace_id") != "lowercase SHA-256 of IFM6-JSON-v1 canonical_json(trace_core)"
        or rp.get("profile_id") != "IFM6-REPRO-v1"
        or "schemas/trace.schema.json" not in {
            item.get("path") for item in provenance.get("planned_tree", []) if isinstance(item, dict)
        }
        or "scripts/run_scenarios.py" not in mp.get("generator_registry", {}).get("required_paths", [])
    ):
        errors.append({"reason": "trace_hash_or_materializer_authority_mismatch"})
    if errors:
        report.add(
            "audit.tr01.trace_schema",
            "TR-01 requires the exact closed QA trace schema, nine trace_core components, explicit null unions and the RP SHA-256 policy",
            details=errors,
        )
    report.metrics["trace_schema_contract"] = {
        "closed_seed_projected": reconstructed and schema_document == seed,
        "trace_core_components": len(components),
    }


def validate_catalog_seeds(
    rows: list[dict[str, str]], parsed_values: dict[str, Any], provenance: dict[str, Any], report: Report
) -> None:
    qa_decisions = [item for item in provenance.get("decisions", []) if item.get("id") == "T03-QA-011"]
    if len(qa_decisions) != 1 or mapped_decision_status(str(qa_decisions[0].get("status", ""))) != "approved":
        report.add(
            "science.catalogs.qa011_contract",
            "catalog seeds require exactly one approved T03-QA-011 decision",
            details={"records": len(qa_decisions)},
        )
        return
    decision = qa_decisions[0].get("decision", {})
    source_of_truth = decision.get("source_of_truth", {})
    catalog_specs = (
        (
            "scenario_index",
            "scenarios/catalog.json",
            {"$schema", "schema_version", "catalog_id", "expected_entry_count", "index_only", "source_of_truth", "entries"},
        ),
        (
            "oracle_index",
            "oracles/catalog.json",
            {"$schema", "schema_version", "catalog_id", "expected_entry_count", "index_only", "source_of_truth", "hash_policy", "entries"},
        ),
    )
    catalog_errors: list[dict[str, Any]] = []
    documents: dict[str, Any] = {}
    scenario_seed = deepcopy(
        source_of_truth.get("scenario_index", {}).get("document_seed")
    )
    oracle_seed = deepcopy(
        source_of_truth.get("oracle_index", {}).get("document_seed")
    )
    expected_documents = {
        "scenario_index": scenario_seed,
        "oracle_index": oracle_seed,
    }
    if isinstance(oracle_seed, dict) and isinstance(oracle_seed.get("entries"), list):
        for index, entry in enumerate(oracle_seed["entries"]):
            oracle_path = f"oracles/S{index:02d}.expected.json"
            reconstructed_oracle, oracle_document = reconstruct_document(
                rows, parsed_values, oracle_path, report
            )
            if not reconstructed_oracle:
                catalog_errors.append(
                    {
                        "catalog": "oracle_index",
                        "reason": "oracle_not_reconstructible_for_hash_freeze",
                        "path": oracle_path,
                    }
                )
                continue
            entry["sha256"] = sha256_bytes(
                (canonical_json_text(oracle_document) + "\n").encode("utf-8")
            )
    for name, path, exact_fields in catalog_specs:
        contract = source_of_truth.get(name, {}) if isinstance(source_of_truth, dict) else {}
        seed = contract.get("document_seed") if isinstance(contract, dict) else None
        outer = contract.get("outer_contract", {}) if isinstance(contract, dict) else {}
        if (
            not isinstance(seed, dict)
            or set(seed) != exact_fields
            or set(outer.get("required_fields", [])) != exact_fields
            or set(outer.get("allowed_fields", [])) != exact_fields
            or outer.get("additionalProperties") is not False
        ):
            catalog_errors.append({"catalog": name, "reason": "frozen_seed_or_closed_contract_invalid"})
        reconstructed, document = reconstruct_document(rows, parsed_values, path, report)
        if not reconstructed:
            catalog_errors.append({"catalog": name, "reason": "document_not_reconstructible", "path": path})
            continue
        documents[name] = document
        if document != expected_documents.get(name):
            catalog_errors.append(
                {
                    "catalog": name,
                    "reason": "document_differs_from_post_freeze_projection",
                    "path": path,
                }
            )

    scenario_entries = documents.get("scenario_index", {}).get("entries", []) if isinstance(documents.get("scenario_index"), dict) else []
    expected_scenario_entries = [
        {
            "scenario_id": f"S{index:02d}",
            "scenario_path": f"scenarios/S{index:02d}.json",
            "oracle_path": f"oracles/S{index:02d}.expected.json",
        }
        for index in range(16)
    ]
    if scenario_entries != expected_scenario_entries:
        catalog_errors.append({"catalog": "scenario_index", "reason": "main_bijection_not_exact_S00_S15"})

    oracle_entries = documents.get("oracle_index", {}).get("entries", []) if isinstance(documents.get("oracle_index"), dict) else []
    expected_oracle_entries = (
        expected_documents.get("oracle_index", {}).get("entries", [])
        if isinstance(expected_documents.get("oracle_index"), dict)
        else []
    )
    if oracle_entries != expected_oracle_entries:
        catalog_errors.append(
            {
                "catalog": "oracle_index",
                "reason": "frozen_main_catalog_not_exact_S00_S15_with_content_hashes",
            }
        )
    isolated_id = "sadness_2018a_symbolic.expected"
    if any(isinstance(item, dict) and item.get("oracle_id") == isolated_id for item in oracle_entries):
        catalog_errors.append({"catalog": "oracle_index", "reason": "isolated_UT014_oracle_leaked_into_main_catalog"})
    isolated_expected = {
        "oracle_id": isolated_id,
        "path": "tests/oracles/sadness_2018a_symbolic.expected.json",
        "used_by": "UT-014",
        "main_catalog_membership": False,
        "reason": "isolated published-rule symbolic regression outside the S00-S15 scenario-oracle bijection",
    }
    isolated_actual = (
        source_of_truth.get("oracle_index", {}).get("isolated_oracle_exclusion")
        if isinstance(source_of_truth, dict)
        else None
    )
    if isolated_actual != isolated_expected:
        catalog_errors.append({"catalog": "oracle_index", "reason": "isolated_UT014_exclusion_contract_mismatch"})
    active_targets = {row.get("target_path", "") for row in rows if active(row)}
    isolated_required_paths = {
        "tests/fixtures/sadness_2018a_symbolic.json",
        "tests/oracles/sadness_2018a_symbolic.expected.json",
    }
    if not isolated_required_paths <= active_targets:
        catalog_errors.append({
            "catalog": "oracle_index",
            "reason": "isolated_UT014_paths_not_targeted",
            "missing": sorted(isolated_required_paths - active_targets),
        })
    if catalog_errors:
        report.add(
            "science.catalogs.seed_contract",
            "scenario and oracle catalogs must be exact closed T03-QA-011 projections with post-freeze oracle hashes",
            details=catalog_errors,
        )
    report.metrics["catalog_seed_contract"] = {
        "main_oracle_entries": len(oracle_entries),
        "scenario_entries": len(scenario_entries),
        "seed_documents_reconstructed": len(documents),
        "post_freeze_oracle_hashes": sum(
            isinstance(item, dict)
            and isinstance(item.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is not None
            for item in oracle_entries
        ),
        "ut014_isolated": isolated_actual == isolated_expected,
    }


def validate_t03_3_6_materialization(
    rows: list[dict[str, str]],
    parsed_values: dict[str, Any],
    provenance: dict[str, Any],
    report: Report,
    package_root: Path,
    post_run_register: dict[str, dict[str, Any]],
) -> None:
    """Audit frozen inputs/code and distinguish pre-run from attested post-run state."""
    findings: list[dict[str, Any]] = []
    planned_status = {
        item.get("path"): item.get("status")
        for item in provenance.get("planned_tree", [])
        if isinstance(item, dict)
    }
    for file_set in provenance.get("planned_file_sets", []):
        if not isinstance(file_set, dict):
            continue
        for path in file_set.get("paths", []):
            planned_status.setdefault(path, file_set.get("status"))
    for path in sorted(FROZEN_INPUT_PATHS):
        if planned_status.get(path) != "present_frozen_validated_T03_3_6":
            findings.append(
                {
                    "path": path,
                    "reason": "provenance_frozen_status_mismatch",
                    "actual": planned_status.get(path),
                }
            )
    for path in sorted(T03_3_6_CODE_PATHS):
        if planned_status.get(path) != "present_static_validated_T03_3_6":
            findings.append(
                {
                    "path": path,
                    "reason": "provenance_code_status_mismatch",
                    "actual": planned_status.get(path),
                }
            )

    schema_path_by_document = {
        "scenarios/catalog.json": "schemas/scenario_catalog.schema.json",
        "oracles/catalog.json": "schemas/oracle_catalog.schema.json",
        "tests/test_catalog.json": "schemas/test_catalog.schema.json",
        "tests/fixtures/sadness_2018a_symbolic.json": "schemas/scenario.schema.json",
        "tests/oracles/sadness_2018a_symbolic.expected.json": "schemas/oracle.schema.json",
    }
    for index in range(16):
        schema_path_by_document[f"scenarios/S{index:02d}.json"] = (
            "schemas/scenario.schema.json"
        )
        schema_path_by_document[f"oracles/S{index:02d}.expected.json"] = (
            "schemas/oracle.schema.json"
        )
    schemas: dict[str, Any] = {}
    for schema_path in sorted(set(schema_path_by_document.values())):
        try:
            schemas[schema_path] = json.loads(
                (package_root / schema_path).read_text(encoding="utf-8"),
                object_pairs_hook=reject_duplicate_pairs,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJSONKey) as exc:
            findings.append(
                {
                    "path": schema_path,
                    "reason": "supporting_schema_unreadable",
                    "error": str(exc),
                }
            )

    frozen_documents: dict[str, Any] = {}
    artifact_hashes: dict[str, dict[str, Any]] = {}
    for path in sorted(FROZEN_INPUT_PATHS):
        reconstructed, expected = reconstruct_document(
            rows, parsed_values, path, report
        )
        destination = package_root / path
        if not reconstructed:
            findings.append({"path": path, "reason": "ledger_reconstruction_failed"})
            continue
        if not destination.is_file():
            findings.append({"path": path, "reason": "physical_file_missing"})
            continue
        raw = destination.read_bytes()
        canonical = (canonical_json_text(expected) + "\n").encode("utf-8")
        artifact_hashes[path] = {"bytes": len(raw), "sha256": sha256_bytes(raw)}
        if raw != canonical:
            findings.append(
                {"path": path, "reason": "physical_bytes_differ_from_ledger_projection"}
            )
        try:
            actual = json.loads(
                raw.decode("utf-8"), object_pairs_hook=reject_duplicate_pairs
            )
        except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJSONKey) as exc:
            findings.append(
                {"path": path, "reason": "physical_json_invalid", "error": str(exc)}
            )
            continue
        frozen_documents[path] = actual
        if not schema_json_equal(actual, expected):
            findings.append({"path": path, "reason": "physical_json_value_mismatch"})
        schema_path = schema_path_by_document[path]
        if schema_path in schemas:
            schema_errors = validate_json_schema_instance(actual, schemas[schema_path])
            if schema_errors:
                findings.append(
                    {
                        "path": path,
                        "reason": "frozen_document_schema_failure",
                        "errors": schema_errors[:8],
                    }
                )

    oracle_catalog = frozen_documents.get("oracles/catalog.json", {})
    oracle_entries = (
        oracle_catalog.get("entries", []) if isinstance(oracle_catalog, dict) else []
    )
    if len(oracle_entries) != 16:
        findings.append(
            {"path": "oracles/catalog.json", "reason": "oracle_catalog_count_not_16"}
        )
    else:
        for index, entry in enumerate(oracle_entries):
            oracle_path = f"oracles/S{index:02d}.expected.json"
            actual_hash = artifact_hashes.get(oracle_path, {}).get("sha256")
            if not isinstance(entry, dict) or entry.get("sha256") != actual_hash:
                findings.append(
                    {
                        "path": oracle_path,
                        "reason": "oracle_catalog_physical_hash_mismatch",
                    }
                )
    for path, document in sorted(frozen_documents.items()):
        if (
            path.startswith("tests/oracles/")
            or (path.startswith("oracles/") and path != "oracles/catalog.json")
        ):
            if document.get("frozen_before_implementation") is not True:
                findings.append(
                    {"path": path, "reason": "oracle_not_declared_preimplementation_frozen"}
                )
            if "observed" in document:
                findings.append({"path": path, "reason": "oracle_contains_observed_value"})
        if path.startswith("scenarios/") and path != "scenarios/catalog.json":
            forbidden = {"expected", "result", "trace", "observed"}.intersection(document)
            if forbidden:
                findings.append(
                    {
                        "path": path,
                        "reason": "scenario_not_input_only",
                        "forbidden": sorted(forbidden),
                    }
                )

    for path in sorted(FROZEN_INPUT_PATHS | T03_3_6_CODE_PATHS):
        active_rows = [
            row
            for row in rows
            if active(row) and row.get("target_path") == path
        ]
        if not active_rows:
            findings.append({"path": path, "reason": "active_ledger_rows_missing"})
        elif any(
            materialization_status(row) != "materialized_t03"
            or row.get("materialization_refs") != path
            for row in active_rows
        ):
            findings.append({"path": path, "reason": "ledger_materialization_mismatch"})

    physical_source_paths = {
        path.relative_to(package_root).as_posix()
        for path in (package_root / "src" / "ifatigue_infra6").glob("*.py")
        if path.is_file()
    }
    physical_test_paths = {
        path.relative_to(package_root).as_posix()
        for path in (package_root / "tests").glob("test_*.py")
        if path.is_file()
    }
    if physical_source_paths != IMPLEMENTATION_SOURCE_PATHS:
        findings.append(
            {
                "reason": "implementation_module_set_mismatch",
                "missing": sorted(IMPLEMENTATION_SOURCE_PATHS - physical_source_paths),
                "unexpected": sorted(physical_source_paths - IMPLEMENTATION_SOURCE_PATHS),
            }
        )
    if physical_test_paths != UNIT_TEST_MODULE_PATHS:
        findings.append(
            {
                "reason": "unit_test_module_set_mismatch",
                "missing": sorted(UNIT_TEST_MODULE_PATHS - physical_test_paths),
                "unexpected": sorted(physical_test_paths - UNIT_TEST_MODULE_PATHS),
            }
        )

    trees: dict[str, ast.Module] = {}
    source_texts: dict[str, str] = {}
    for path in sorted(T03_3_6_CODE_PATHS):
        destination = package_root / path
        if not destination.is_file():
            continue
        raw = destination.read_bytes()
        artifact_hashes[path] = {"bytes": len(raw), "sha256": sha256_bytes(raw)}
        try:
            text = raw.decode("utf-8")
            trees[path] = ast.parse(text, filename=path)
            source_texts[path] = text
        except (UnicodeDecodeError, SyntaxError) as exc:
            findings.append(
                {"path": path, "reason": "python_static_parse_failure", "error": str(exc)}
            )

    allowed_imports = {
        "__future__",
        "copy",
        "dataclasses",
        "datetime",
        "decimal",
        "hashlib",
        "json",
        "pathlib",
        "re",
        "sys",
        "types",
        "typing",
        "unicodedata",
        "unittest",
        "ifatigue_infra6",
    }
    prohibited_imports = {
        "http",
        "multiprocessing",
        "os",
        "random",
        "requests",
        "secrets",
        "socket",
        "subprocess",
        "time",
        "urllib",
    }
    for path, tree in sorted(trees.items()):
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                roots = [(node.module or "").split(".", 1)[0]]
            for root in roots:
                if root in prohibited_imports or root not in allowed_imports:
                    findings.append(
                        {"path": path, "reason": "nonapproved_import", "module": root}
                    )

    expected_definitions = {
        "src/ifatigue_infra6/__init__.py": set(),
        "src/ifatigue_infra6/canonical_json.py": {
            "CanonicalizationError", "parse_decimal_string", "decimal_to_string",
            "_json_ready", "canonical_json", "canonical_bytes", "canonical_sha256",
        },
        "src/ifatigue_infra6/contract.py": {
            "RuntimeContractError", "ordered_diagnostics", "_decimal_or_none",
            "parse_rfc3339_utc", "validate_host_baseline", "validate_factor_state",
            "assess_contracts", "validate_runtime_configuration",
        },
        "src/ifatigue_infra6/host.py": {
            "copy_appraisal_vector", "classify_coping_potential",
            "protected_coordinates_equal",
        },
        "src/ifatigue_infra6/model.py": {
            "ContractAssessment", "ModulationOutcome", "ExecutionOutcome",
        },
        "src/ifatigue_infra6/modulator.py": {"clamp", "modulate_coping_potential"},
        "src/ifatigue_infra6/rules.py": {
            "RuleAdapterError", "PublishedSubsetAmbiguity", "adapt_antecedent_field",
            "adapt_boundary", "select_unique_published_match", "classify_anger_subset",
            "classify_anger_before_after", "evaluate_sadness_symbolic",
            "conflicting_2018b_row_status",
        },
        "src/ifatigue_infra6/runner.py": {"_rejected_outcome", "evaluate_scenario"},
        "src/ifatigue_infra6/trace.py": {
            "trace_policy", "trace_versions", "trace_mask", "_classification_record",
            "build_trace_core", "trace_id", "build_trace", "trace_id_is_valid",
        },
    }
    for path, expected in expected_definitions.items():
        tree = trees.get(path)
        if tree is None:
            continue
        actual = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if actual != expected:
            findings.append(
                {
                    "path": path,
                    "reason": "top_level_definition_set_mismatch",
                    "missing": sorted(expected - actual),
                    "unexpected": sorted(actual - expected),
                }
            )

    exact_bindings = {
        "coping_potential": "host.baseline.coping_potential",
        "lambda": "influence.parameters.lambda",
        "z": "factor_state.level",
        "result": "output.coping_potential",
    }
    binding_anchors = (
        "# @binding-coping-potential: host.baseline.coping_potential",
        "# @binding-lambda: influence.parameters.lambda",
        "# @binding-z: factor_state.level",
        "# @binding-result: output.coping_potential",
    )
    combined_source = "\n".join(
        source_texts.get(path, "") for path in sorted(IMPLEMENTATION_SOURCE_PATHS)
    )
    for anchor in binding_anchors:
        if combined_source.count(anchor) != 1:
            findings.append(
                {"reason": "binding_anchor_cardinality_mismatch", "anchor": anchor}
            )
    model_tree = trees.get("src/ifatigue_infra6/model.py")
    binding_value: Any = None
    if model_tree is not None:
        for node in model_tree.body:
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "BINDING_MAP" for target in node.targets)
                and isinstance(node.value, ast.Call)
                and node.value.args
            ):
                try:
                    binding_value = ast.literal_eval(node.value.args[0])
                except (ValueError, TypeError):
                    binding_value = None
    if binding_value != exact_bindings:
        findings.append({"reason": "binding_map_static_value_mismatch"})

    modulator_tree = trees.get("src/ifatigue_infra6/modulator.py")
    if modulator_tree is not None:
        functions = {
            node.name: node
            for node in modulator_tree.body
            if isinstance(node, ast.FunctionDef)
        }
        modulation = functions.get("modulate_coping_potential")
        signature = (
            [argument.arg for argument in modulation.args.args],
            [argument.arg for argument in modulation.args.kwonlyargs],
        ) if modulation is not None else None
        if signature != (["baseline", "factor_state"], ["lambda_value"]):
            findings.append({"reason": "modulation_input_signature_mismatch"})

    runner_tree = trees.get("src/ifatigue_infra6/runner.py")
    if runner_tree is not None:
        oracle_names = sorted(
            {
                node.id
                for node in ast.walk(runner_tree)
                if isinstance(node, ast.Name) and "oracle" in node.id.lower()
            }
        )
        oracle_paths = sorted(
            {
                node.value
                for node in ast.walk(runner_tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "oracles/" in node.value.lower()
            }
        )
        file_calls = sorted(
            {
                node.func.id
                for node in ast.walk(runner_tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"open", "exec", "eval", "compile"}
            }
        )
        if oracle_names or oracle_paths or file_calls:
            findings.append(
                {
                    "path": "src/ifatigue_infra6/runner.py",
                    "reason": "runtime_oracle_or_file_io_dependency",
                    "oracle_names": oracle_names,
                    "oracle_paths": oracle_paths,
                    "calls": file_calls,
                }
            )

    catalog = frozen_documents.get("tests/test_catalog.json", {})
    expected_methods = [
        item.get("fq_method")
        for item in catalog.get("test_catalog", [])
        if isinstance(item, dict)
    ] if isinstance(catalog, dict) else []
    actual_methods: list[str] = []
    ordered_test_modules = (
        "tests/test_model.py",
        "tests/test_contract.py",
        "tests/test_rules.py",
        "tests/test_trace.py",
    )
    for path in ordered_test_modules:
        tree = trees.get(path)
        if tree is None:
            continue
        module_name = path[:-3].replace("/", ".")
        for class_node in (
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ):
            for method in (
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            ):
                actual_methods.append(
                    f"{module_name}.{class_node.name}.{method.name}"
                )
        hidden_test_controls = sorted(
            {
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and node.attr in {"skip", "skipIf", "skipUnless", "expectedFailure"}
            }
        )
        if hidden_test_controls:
            findings.append(
                {
                    "path": path,
                    "reason": "unit_test_skip_or_expected_failure_present",
                    "controls": hidden_test_controls,
                }
            )
    if actual_methods != expected_methods or len(actual_methods) != 18:
        findings.append(
            {
                "reason": "unit_test_ast_catalog_mismatch",
                "actual_count": len(actual_methods),
                "expected_count": len(expected_methods),
                "missing": sorted(set(expected_methods) - set(actual_methods)),
                "unexpected": sorted(set(actual_methods) - set(expected_methods)),
                "order_exact": actual_methods == expected_methods,
            }
        )

    cache_paths = sorted(
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("__pycache__")
    )
    if cache_paths:
        findings.append({"reason": "python_cache_present_before_test_gate", "paths": cache_paths})
    derived_files = sorted(
        path.relative_to(package_root).as_posix()
        for prefix in DERIVED_PREFIXES
        for path in (package_root / prefix).rglob("*")
        if path.is_file()
    )
    if post_run_register:
        if set(derived_files) != REFERENCE_DERIVED_PATHS:
            findings.append(
                {
                    "reason": "reference_execution_artifact_set_mismatch",
                    "missing": sorted(REFERENCE_DERIVED_PATHS - set(derived_files)),
                    "unexpected": sorted(set(derived_files) - REFERENCE_DERIVED_PATHS),
                }
            )
        unregistered = sorted(
            path for path in REFERENCE_DERIVED_PATHS if path not in post_run_register
        )
        if unregistered:
            findings.append(
                {"reason": "reference_execution_artifacts_not_attested", "paths": unregistered}
            )
    elif derived_files:
        findings.append(
            {"reason": "reference_execution_artifacts_present_before_gate", "paths": derived_files}
        )

    aggregate_records = "".join(
        f"{path}\0{record['sha256']}\0{record['bytes']}\n"
        for path, record in sorted(artifact_hashes.items())
    ).encode("utf-8")
    if findings:
        report.add(
            "t03_3_6.static_materialization",
            "T03.3-6 frozen inputs, implementation or unit-test source failed static audit",
            details=findings[:80],
        )
    report.metrics["t03_3_6"] = {
        "aggregate_sha256": sha256_bytes(aggregate_records),
        "artifact_hash_records": len(artifact_hashes),
        "binding_anchors": len(binding_anchors),
        "frozen_input_documents": len(frozen_documents),
        "implementation_modules": len(physical_source_paths),
        "oracle_runtime_dependency": False if not findings else None,
        "reference_runs_executed": 1 if post_run_register else 0,
        "static_findings": len(findings),
        "unit_test_methods_materialized": len(actual_methods),
        "unit_test_modules": len(physical_test_paths),
        "unit_tests_executed": 18 if post_run_register else 0,
    }


def validate_traces_rejection_and_premature_outputs(
    rows: list[dict[str, str]], parsed_values: dict[str, Any], provenance: dict[str, Any], report: Report
) -> None:
    traces = {f"traces/reference_run/S{index:02d}.trace.json" for index in range(15)}
    rejection = {"traces/reference_run/rejections/S15.rejection.json"}
    validate_planned_set(provenance, "TRACES-15", traces, report)
    validate_planned_set(provenance, "REJECTIONS-1", rejection, report)
    targeted_traces = {
        row.get("target_path", "")
        for row in rows
        if re.fullmatch(r"traces/reference_run/S[0-9]+\.trace\.json", row.get("target_path", ""))
        and materialization_status(row) != "superseded"
    }
    targeted_rejections = {
        row.get("target_path", "")
        for row in rows
        if row.get("target_path", "").startswith("traces/reference_run/rejections/")
        and materialization_status(row) != "superseded"
    }
    if targeted_traces != traces:
        report.add(
            "science.trace.target_set",
            "ledger must target exactly the 15 S00-S14 modulation traces and no S15 trace",
            details={"missing": sorted(traces - targeted_traces), "extra": sorted(targeted_traces - traces)},
        )
    if targeted_rejections != rejection:
        report.add(
            "science.rejection.target_set",
            "ledger must target exactly the single S15 rejection record",
            details={"missing": sorted(rejection - targeted_rejections), "extra": sorted(targeted_rejections - rejection)},
        )
    premature: list[dict[str, str]] = []
    for row in rows:
        path = row.get("target_path", "")
        if (
            not active(row)
            or not path.startswith(DERIVED_PREFIXES)
            or row.get("target_locator") == "@materialization-recipe"
        ):
            continue
        value = parsed_values.get(row.get("row_id", ""), object())
        status = materialization_status(row)
        if value is not None and status not in MATERIALIZED:
            premature.append({"row_id": row.get("row_id", ""), "path": path})
    if premature:
        report.add("science.observed_value.premature", "derived results, traces or logs contain values before their producing run", details=premature)
    report.metrics["trace_contract"] = {
        "declared_rejections": len(rejection),
        "declared_traces": len(traces),
        "targeted_rejection_paths": len(targeted_rejections),
        "targeted_trace_paths": len(targeted_traces),
    }


def validate_test_catalog(
    rows: list[dict[str, str]], parsed_values: dict[str, Any], provenance: dict[str, Any], report: Report
) -> None:
    qa_decisions = [item for item in provenance.get("decisions", []) if item.get("id") == "T03-QA-011"]
    qa_status = mapped_decision_status(str(qa_decisions[0].get("status", ""))) if len(qa_decisions) == 1 else None
    decision = qa_decisions[0].get("decision", {}) if len(qa_decisions) == 1 else {}
    test_contract = decision.get("test_catalog", {}) if isinstance(decision, dict) else {}
    expected_document = test_contract.get("document_seed") if isinstance(test_contract, dict) else None
    expected_entries = expected_document.get("test_catalog", []) if isinstance(expected_document, dict) else []
    exact_outer_fields = {
        "$schema", "schema_version", "expected_test_method_count", "framework",
        "oracle_values_imported_from_production", "source_of_truth", "test_catalog",
    }
    outer_contract = test_contract.get("outer_contract", {}) if isinstance(test_contract, dict) else {}
    if (
        len(qa_decisions) != 1
        or qa_status != "approved"
        or not isinstance(expected_document, dict)
        or set(expected_document) != exact_outer_fields
        or set(outer_contract.get("required_fields", [])) != exact_outer_fields
        or set(outer_contract.get("allowed_fields", [])) != exact_outer_fields
        or outer_contract.get("additionalProperties") is not False
        or len(expected_entries) != 18
        or any(not isinstance(item, dict) for item in expected_entries)
    ):
        report.add(
            "science.tests.qa011_contract",
            "T03-QA-011 must resolve exactly one approved closed 18-entry test-catalog document seed",
            details={"decision_records": len(qa_decisions), "decision_status": qa_status, "entries": len(expected_entries)},
        )
    reconstructed, actual_document = reconstruct_document(rows, parsed_values, "tests/test_catalog.json", report)
    actual_entries = actual_document.get("test_catalog", []) if reconstructed and isinstance(actual_document, dict) else []
    actual_ids = [item.get("test_id") for item in actual_entries if isinstance(item, dict)]
    actual_methods = [item.get("fq_method") for item in actual_entries if isinstance(item, dict)]
    if not reconstructed or actual_document != expected_document:
        report.add(
            "science.tests.document_seed_mismatch",
            "tests/test_catalog.json must be the exact closed projection of T03-QA-011 document_seed",
        )
    if not isinstance(actual_document, dict) or actual_document.get("expected_test_method_count") != 18:
        report.add("science.tests.expected_count", "test catalog must declare expected_test_method_count exactly 18")
    if len(actual_entries) != 18 or len(actual_ids) != 18 or len(set(actual_ids)) != 18 or len(set(actual_methods)) != 18:
        report.add(
            "science.tests.not_enumerated",
            "test catalog must enumerate exactly 18 unique test_id/fq_method pairs, not only their count",
            details={"entries": len(actual_entries), "unique_ids": len(set(actual_ids)), "unique_fq_methods": len(set(actual_methods))},
        )
    expected_pairs = [
        {"test_id": item.get("test_id"), "fq_method": item.get("fq_method")}
        for item in expected_entries if isinstance(item, dict)
    ]
    actual_pairs = [
        {"test_id": item.get("test_id"), "fq_method": item.get("fq_method")}
        for item in actual_entries if isinstance(item, dict)
    ]
    if expected_pairs and actual_pairs != expected_pairs:
        report.add(
            "science.tests.qa011_mismatch",
            "tests/test_catalog.json does not match the exact test_id/fq_method pairs and order approved by T03-QA-011",
            details={"order_matches": actual_pairs == expected_pairs},
        )
    exact_ut014 = {
        "test_id": "UT-014",
        "fq_method": "tests.test_rules.TestRules.test_sadness_source_terms_and_context_preserved",
        "scenario_refs": [],
        "oracle_refs": ["sadness_2018a_symbolic.expected"],
        "fixture_refs": ["tests/fixtures/sadness_2018a_symbolic.json"],
        "oracle_path": "tests/oracles/sadness_2018a_symbolic.expected.json",
    }
    ut014_entries = [item for item in actual_entries if isinstance(item, dict) and item.get("test_id") == "UT-014"]
    isolated_reference = (
        decision.get("test_catalog_entry_contract", {})
        .get("reference_mapping", {})
        .get("oracle_refs", {})
        .get("isolated_UT-014_exception", {})
    )
    isolated_reference_valid = (
        isolated_reference.get("test_id") == "UT-014"
        and isolated_reference.get("oracle_refs_exact") == ["sadness_2018a_symbolic.expected"]
        and isolated_reference.get("oracle_path_exact") == "tests/oracles/sadness_2018a_symbolic.expected.json"
        and isolated_reference.get("resolution_authority") == "source_of_truth.oracle_index.isolated_oracle_exclusion"
        and isolated_reference.get("main_catalog_membership") is False
        and isolated_reference.get("main_scenario_oracle_bijection_membership") is False
        and isolated_reference.get("additionalProperties") is False
    )
    if ut014_entries != [exact_ut014] or not isolated_reference_valid:
        report.add(
            "science.tests.ut014_isolation",
            "UT-014 must use only its exact isolated fixture/oracle contract outside the main S00-S15 catalogs",
            details={"entries": ut014_entries, "reference_contract_valid": isolated_reference_valid},
        )
    report.metrics["test_catalog"] = {
        "document_seed_exact": reconstructed and actual_document == expected_document,
        "entries": len(actual_entries),
        "qa011_entries": len(expected_entries),
        "unique_fq_methods": len(set(actual_methods)),
        "unique_test_ids": len(set(actual_ids)),
        "ut014_isolated": ut014_entries == [exact_ut014] and isolated_reference_valid,
    }


def validate_source_manifest_gate(
    rows: list[dict[str, str]], parsed_values: dict[str, Any], provenance: dict[str, Any], report: Report
) -> None:
    mp_decisions = [item for item in provenance.get("decisions", []) if item.get("id") == "T03-MP-013"]
    errors: list[dict[str, Any]] = []
    if len(mp_decisions) != 1 or mapped_decision_status(str(mp_decisions[0].get("status", ""))) != "approved":
        report.add(
            "science.source_manifest.mp013_contract",
            "source-manifest ordering requires exactly one approved T03-MP-013 decision",
            details={"records": len(mp_decisions)},
        )
        return
    decision = mp_decisions[0].get("decision", {})
    expected_gate = {
        "status": "planned_not_run",
        "build_command": "python3 -I -B -X utf8 scripts/build_source_manifest.py --root . --output manifests/SOURCE_SHA256.txt",
        "verify_command": "python3 -I -B -X utf8 scripts/verify_manifest.py --root . --manifest manifests/SOURCE_SHA256.txt",
        "stage": "after all authored inputs, generators and validators are frozen and before any reference run or unit test",
        "source_builder_inclusion": "scripts/build_source_manifest.py is itself an authored generator included in manifests/SOURCE_SHA256.txt",
        "failure_policy": "a missing source member, unexpected member, hash mismatch, malformed record or nonzero exit blocks every reference-run node",
    }
    gate = decision.get("pre_run_source_manifest_gate")
    if gate != expected_gate:
        errors.append({"reason": "pre_run_source_manifest_gate_mismatch"})
    build_order = decision.get("build_order")
    expected_build_order = [
        "validate authored source, decision, thesis and binding layers",
        "resolve config/resolved_instance.json",
        "validate and freeze input-only scenarios and independent oracles",
        f"run {expected_gate['build_command']}",
        f"run {expected_gate['verify_command']} and require exit code zero",
        "run the reference scenario recipe and unit tests",
        "validate coverage and all generated outputs",
        "execute every validator_registry entry and require zero exit codes",
        "write manifests/BUILD_RECORD.json",
        "generate and verify MANIFIESTO_SHA256.txt",
        "build deterministic ZIP and its external SHA-256 sidecar",
    ]
    if build_order != expected_build_order:
        errors.append({"reason": "frozen_build_order_mismatch"})
    required_generators = decision.get("generator_registry", {}).get("required_paths", [])
    if "scripts/build_source_manifest.py" not in required_generators:
        errors.append({"reason": "source_manifest_builder_absent_from_generator_registry"})
    if decision.get("source_manifest_path") != "manifests/SOURCE_SHA256.txt":
        errors.append({"reason": "source_manifest_path_mismatch"})

    def unique_recipe(path: str) -> Any:
        values: dict[str, Any] = {}
        for row in rows:
            if (
                active(row)
                and row.get("target_path") == path
                and row.get("target_locator") == "@materialization-recipe"
                and row.get("row_id") in parsed_values
            ):
                values[row.get("target_value", "")] = parsed_values[row["row_id"]]
        if len(values) != 1:
            errors.append({"reason": "materialization_recipe_cardinality", "path": path, "unique_values": len(values)})
            return None
        return values[sorted(values)[0]]

    builder_recipe = unique_recipe("scripts/build_source_manifest.py")
    expected_builder_recipe = {
        "action": "materialize_python_source",
        "path": "scripts/build_source_manifest.py",
        "runtime_dependencies": "standard_library_only",
        "source": "registered_derivations",
        "write_mode": "atomic",
    }
    if builder_recipe != expected_builder_recipe:
        errors.append({"reason": "source_manifest_builder_recipe_mismatch"})
    source_recipe = unique_recipe("manifests/SOURCE_SHA256.txt")
    expected_source_recipe = {
        "action": "build_and_verify_pre_run_source_manifest",
        "build_command": expected_gate["build_command"],
        "builder": "scripts/build_source_manifest.py",
        "failure_policy": expected_gate["failure_policy"],
        "manifest": "manifests/SOURCE_SHA256.txt",
        "source_builder_inclusion": expected_gate["source_builder_inclusion"],
        "stage": expected_gate["stage"],
        "status_before_run": expected_gate["status"],
        "verify_command": expected_gate["verify_command"],
        "write_mode": "atomic",
    }
    if source_recipe != expected_source_recipe:
        errors.append({"reason": "source_manifest_build_verify_recipe_mismatch"})

    reconstructed_recipe, build_recipe = reconstruct_document(
        rows, parsed_values, "manifests/BUILD_RECIPE.json", report
    )
    recipe_projection_fields = {
        "recipe_id", "recipe_path", "topology_path", "source_manifest_path", "build_record_path",
        "status", "required_executable_binding_map", "binding_coverage_rule", "binding_artifacts",
        "generator_registry", "pre_run_source_manifest_gate", "validator_registry", "planned_commands",
        "coverage_contract", "build_order", "failure_policy", "manual_editing_of_derived_nodes",
    }
    if not reconstructed_recipe or not isinstance(build_recipe, dict):
        errors.append({"reason": "build_recipe_not_reconstructible"})
    else:
        mismatched = sorted(
            field for field in recipe_projection_fields
            if build_recipe.get(field) != decision.get(field)
        )
        if mismatched:
            errors.append({"reason": "build_recipe_projection_mismatch", "fields": mismatched})

    reconstructed_topology, topology = reconstruct_document(
        rows, parsed_values, "manifests/GENERATION_TOPOLOGY.json", report
    )
    if not reconstructed_topology or not isinstance(topology, dict):
        errors.append({"reason": "generation_topology_not_reconstructible"})
    else:
        topology_projection = {
            "recipe_path": decision.get("recipe_path"),
            "source_manifest_path": decision.get("source_manifest_path"),
            "build_record_path": decision.get("build_record_path"),
            "status": decision.get("status"),
            "build_order": decision.get("build_order"),
            "dag": decision.get("dag"),
            "acyclicity_rules": decision.get("acyclicity_rules"),
            "failure_policy": decision.get("failure_policy"),
            "manual_editing_of_derived_nodes": decision.get("manual_editing_of_derived_nodes"),
        }
        mismatched = sorted(field for field, value in topology_projection.items() if topology.get(field) != value)
        if mismatched:
            errors.append({"reason": "generation_topology_projection_mismatch", "fields": mismatched})

    planned_commands = decision.get("planned_commands", [])
    try:
        build_index = planned_commands.index(expected_gate["build_command"])
        verify_index = planned_commands.index(expected_gate["verify_command"])
        scenario_index = planned_commands.index("python3 -I -B -X utf8 scripts/run_scenarios.py")
        test_index = planned_commands.index("python3 -I -B -X utf8 scripts/run_tests.py")
        if not build_index < verify_index < scenario_index < test_index:
            errors.append({"reason": "planned_command_order_does_not_enforce_pre_run_gate"})
    except (ValueError, AttributeError):
        errors.append({"reason": "planned_commands_missing_build_verify_or_execution_command"})

    if errors:
        report.add(
            "science.source_manifest.pre_run_gate",
            "build_source_manifest and verify_manifest must form a frozen gate before every reference run and test",
            details=errors,
        )
    report.metrics["source_manifest_gate"] = {
        "build_before_verify_before_run": not any(
            item["reason"] in {
                "frozen_build_order_mismatch",
                "planned_command_order_does_not_enforce_pre_run_gate",
                "planned_commands_missing_build_verify_or_execution_command",
            }
            for item in errors
        ),
        "builder_registered": "scripts/build_source_manifest.py" in required_generators,
        "recipes_exact": builder_recipe == expected_builder_recipe and source_recipe == expected_source_recipe,
    }


def validate_t03_3_7_infrastructure(
    rows: list[dict[str, str]],
    parsed_values: dict[str, Any],
    provenance: dict[str, Any],
    report: Report,
    package_root: Path,
    post_run_register: dict[str, dict[str, Any]],
) -> None:
    """Audit the pre-run program set and, once materialized, its 90-file gate."""
    findings: list[dict[str, Any]] = []
    decisions = {
        item.get("id"): item
        for item in provenance.get("decisions", [])
        if isinstance(item, dict)
    }
    mp = decisions.get("T03-MP-013", {}).get("decision", {})
    registered = set(mp.get("generator_registry", {}).get("required_paths", []))
    if registered != T03_3_7_EXECUTABLE_PATHS:
        findings.append(
            {
                "reason": "generator_registry_mismatch",
                "missing": sorted(T03_3_7_EXECUTABLE_PATHS - registered),
                "unexpected": sorted(registered - T03_3_7_EXECUTABLE_PATHS),
            }
        )

    physical_programs = {
        path.relative_to(package_root).as_posix()
        for directory in (package_root / "scripts", package_root / "commands")
        if directory.is_dir()
        for path in directory.glob("*.py")
        if path.is_file()
    }
    if physical_programs != T03_3_7_EXECUTABLE_PATHS:
        findings.append(
            {
                "reason": "physical_program_set_mismatch",
                "missing": sorted(T03_3_7_EXECUTABLE_PATHS - physical_programs),
                "unexpected": sorted(physical_programs - T03_3_7_EXECUTABLE_PATHS),
            }
        )

    program_hashes: dict[str, dict[str, Any]] = {}
    forbidden_imports = {"socket", "urllib", "http", "requests", "random", "secrets"}
    for path in sorted(T03_3_7_EXECUTABLE_PATHS):
        destination = package_root / path
        if not destination.is_file():
            continue
        raw = destination.read_bytes()
        program_hashes[path] = {"bytes": len(raw), "sha256": sha256_bytes(raw)}
        try:
            text = raw.decode("utf-8")
            tree = ast.parse(text, filename=path)
        except (UnicodeDecodeError, SyntaxError) as exc:
            findings.append(
                {"path": path, "reason": "python_static_parse_failure", "error": str(exc)}
            )
            continue
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 0
        }
        prohibited = sorted(imported & forbidden_imports)
        if prohibited:
            findings.append(
                {"path": path, "reason": "prohibited_import", "imports": prohibited}
            )
        functions = {
            node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if "main" not in functions or 'if __name__ == "__main__"' not in text:
            findings.append({"path": path, "reason": "missing_command_boundary"})
        active_rows = [
            row for row in rows if active(row) and row.get("target_path") == path
        ]
        if not active_rows or any(
            materialization_status(row) != "materialized_t03"
            or row.get("materialization_refs") != path
            for row in active_rows
        ):
            findings.append({"path": path, "reason": "ledger_materialization_mismatch"})

    for runner in ("scripts/run_scenarios.py", "scripts/run_tests.py"):
        destination = package_root / runner
        if destination.is_file():
            text = destination.read_text(encoding="utf-8")
            gate_position = text.find("gate = verify_source_gate(root)")
            execution_markers = (
                ("outcomes[sid] = evaluate_scenario",)
                if runner.endswith("run_scenarios.py")
                else ("suite.run(result)",)
            )
            execution_positions = [text.find(marker) for marker in execution_markers]
            if gate_position < 0 or any(
                position < 0 or position < gate_position for position in execution_positions
            ):
                findings.append({"path": runner, "reason": "source_gate_not_before_execution"})

    for path in sorted(T03_3_7_BUILD_CONTRACT_PATHS):
        reconstructed, expected = reconstruct_document(rows, parsed_values, path, report)
        destination = package_root / path
        if not reconstructed or not isinstance(expected, dict) or not destination.is_file():
            findings.append({"path": path, "reason": "build_contract_missing_or_unreconstructible"})
            continue
        try:
            actual = json.loads(
                destination.read_text(encoding="utf-8"),
                object_pairs_hook=reject_duplicate_pairs,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJSONKey) as exc:
            findings.append({"path": path, "reason": "build_contract_invalid_json", "error": str(exc)})
            continue
        expected_bytes = (canonical_json_text(expected) + "\n").encode("utf-8")
        if actual != expected or destination.read_bytes() != expected_bytes:
            findings.append({"path": path, "reason": "build_contract_not_exact_canonical_projection"})
        active_rows = [
            row for row in rows if active(row) and row.get("target_path") == path
        ]
        if not active_rows or any(
            materialization_status(row) != "materialized_t03"
            or row.get("materialization_refs") != path
            for row in active_rows
        ):
            findings.append({"path": path, "reason": "ledger_materialization_mismatch"})
    if (
        (package_root / FINAL_BUILD_RECORD_PATH).exists()
        and FINAL_BUILD_RECORD_PATH not in post_run_register
    ):
        findings.append({"reason": "build_record_prematurely_materialized"})

    manifest_rows = [
        row
        for row in rows
        if active(row) and row.get("target_path") == SOURCE_MANIFEST_PATH
    ]
    manifest_claimed = bool(manifest_rows) and all(
        materialization_status(row) == "materialized_t03" for row in manifest_rows
    )
    manifest_path = package_root / SOURCE_MANIFEST_PATH
    manifest_metrics: dict[str, Any] = {
        "present": manifest_path.is_file(),
        "ledger_materialized": manifest_claimed,
        "records": 0,
        "verified": False,
    }
    if manifest_claimed or manifest_path.exists():
        if not manifest_claimed or not manifest_path.is_file():
            findings.append({"reason": "source_manifest_file_ledger_state_mismatch"})
        else:
            raw = manifest_path.read_bytes()
            manifest_metrics["bytes"] = len(raw)
            manifest_metrics["sha256"] = sha256_bytes(raw)
            if not raw or not raw.endswith(b"\n") or b"\r" in raw:
                findings.append({"reason": "source_manifest_line_ending_or_empty"})
            else:
                try:
                    lines = raw.decode("utf-8").splitlines()
                except UnicodeDecodeError as exc:
                    findings.append({"reason": "source_manifest_not_utf8", "error": str(exc)})
                    lines = []
                records: dict[str, str] = {}
                ordered: list[str] = []
                record_re = re.compile(r"^([0-9a-f]{64})  ([^\x00\r\n]+)$")
                for number, line in enumerate(lines, start=1):
                    match = record_re.fullmatch(line)
                    if match is None:
                        findings.append({"reason": "source_manifest_malformed_record", "line": number})
                        continue
                    digest, path = match.groups()
                    if path in records:
                        findings.append({"reason": "source_manifest_duplicate_path", "path": path})
                    records[path] = digest
                    ordered.append(path)
                declared = declared_paths(provenance, report)
                fixed = {
                    "PROVENANCE.json",
                    "config/resolved_instance.json",
                    "manifests/BUILD_RECIPE.json",
                    "manifests/GENERATION_TOPOLOGY.json",
                    "sources/DERIVATION_LEDGER.csv",
                    "sources/SOURCES.json",
                }
                prefixes = ("schemas/", "spec/", "src/", "scenarios/", "oracles/", "tests/")
                expected_members = {
                    path for path in declared if path in fixed or path.startswith(prefixes)
                } | T03_3_7_EXECUTABLE_PATHS
                if len(expected_members) != EXPECTED_SOURCE_MEMBERS:
                    findings.append(
                        {"reason": "source_manifest_expected_membership_count", "actual": len(expected_members)}
                    )
                if set(records) != expected_members:
                    findings.append(
                        {
                            "reason": "source_manifest_membership_mismatch",
                            "missing": sorted(expected_members - set(records)),
                            "unexpected": sorted(set(records) - expected_members),
                        }
                    )
                if ordered != sorted(ordered, key=lambda item: item.encode("utf-8")):
                    findings.append({"reason": "source_manifest_order_mismatch"})
                mismatches = []
                for path, digest in records.items():
                    destination = package_root / path
                    if not destination.is_file() or sha256_bytes(destination.read_bytes()) != digest:
                        mismatches.append(path)
                if mismatches:
                    findings.append(
                        {"reason": "source_manifest_hash_mismatch", "paths": sorted(mismatches)}
                    )
                manifest_metrics["records"] = len(records)
                manifest_metrics["verified"] = not any(
                    item.get("reason", "").startswith("source_manifest") for item in findings
                )

    if findings:
        report.add(
            "science.t03_3_7.infrastructure",
            "the exact ten-program infrastructure, two build contracts and pre-run source gate must be materialized and internally coherent",
            details=findings,
        )
    report.metrics["t03_3_7"] = {
        "programs": len(program_hashes),
        "program_hashes": program_hashes,
        "build_contracts": sum(
            (package_root / path).is_file() for path in T03_3_7_BUILD_CONTRACT_PATHS
        ),
        "source_manifest": manifest_metrics,
        "reference_runs_executed": 0,
        "unit_tests_executed": 0,
        "static_findings": len(findings),
    }


def validate_prohibited_uses(
    rows: list[dict[str, str]], parsed_values: dict[str, Any], report: Report, exact_header: bool
) -> None:
    violations: list[dict[str, Any]] = []
    for row in rows:
        support_id = row.get("support_ref_id", "")
        text = " ".join((row.get("target_field", ""), row.get("target_value", ""), row.get("purpose", ""))).lower()
        is_benchmark = any(token in text for token in ("benchmark", "microsecond", "44.766"))
        if support_id not in PROHIBITED_CONTEXT_SUPPORTS and not is_benchmark:
            continue
        reasons = []
        if row.get("claim_provenance_class") != "excluded_from_execution":
            reasons.append("claim_not_excluded")
        if row.get("transformation_type") != "preserve_and_exclude":
            reasons.append("transformation_not_preserve_and_exclude")
        if exact_header and materialization_status(row) != "excluded":
            reasons.append("materialization_not_excluded")
        if not row.get("target_path", "").startswith("docs/"):
            reasons.append("target_not_documentation")
        if is_benchmark and row.get("target_path", "").startswith("results/"):
            reasons.append("benchmark_presented_as_result")
        if reasons:
            violations.append({"row_id": row.get("row_id"), "support_ref_id": support_id, "reasons": reasons})
    if violations:
        report.add("science.prohibited_context_use", "GEA, wrapper or benchmark escaped preserve-and-exclude boundaries", details=violations)


def summarize_rows(rows: list[dict[str, str]], report: Report) -> None:
    report.metrics.update({
        "data_rows": len(rows),
        "derivations": len({row.get("derivation_id") for row in rows}),
        "target_paths": len({row.get("target_path") for row in rows}),
        "row_ids": len({row.get("row_id") for row in rows}),
        "support_ref_types": dict(sorted(Counter(row.get("support_ref_type", "") for row in rows).items())),
    })
    for field in ("source_verification_status", "decision_approval_status", "materialization_status"):
        if any(field in row for row in rows):
            report.metrics[field] = dict(sorted(Counter(row.get(field, "") for row in rows).items()))
    if any("_legacy_status" in row for row in rows):
        report.metrics["legacy_status"] = dict(sorted(Counter(row.get("_legacy_status", "") for row in rows).items()))


def run_validation(args: argparse.Namespace) -> tuple[Report, int]:
    package_root = args.package_root.resolve()
    report = Report("diagnostic" if args.diagnostic else "strict")
    schema = read_json_file(args.schema, "schema", report, package_root)
    validate_schema_document(schema)
    provenance = read_json_file(args.provenance, "provenance", report, package_root)
    sources = read_json_file(args.sources, "sources", report, package_root)
    post_run_register = load_post_run_materialization_register(
        package_root, provenance, report
    )
    validator_raw = Path(__file__).read_bytes()
    report.inputs["validator"] = {
        "bytes": len(validator_raw),
        "path": relative_display(Path(__file__), package_root),
        "sha256": sha256_bytes(validator_raw),
    }
    text = validate_ledger_bytes(args.ledger, report, package_root)
    header, rows, exact_header = parse_ledger(text, report)
    report.metrics["csv"] = {
        "actual_columns": len(header),
        "expected_columns": len(EXPECTED_HEADER),
        "header_exact": exact_header,
        "legacy_29_column_header": header == LEGACY_HEADER,
    }
    if not rows:
        return report, EXIT_FINDINGS
    if not exact_header and not args.diagnostic:
        report.add("mode.strict.legacy_input", "use --diagnostic only to inspect an unmigrated ledger")
    summarize_rows(rows, report)
    validate_rows_against_schema(rows, schema, report, exact_header)
    parsed_values = validate_json_cells(rows, report)
    validate_identifiers_groups_and_graph(rows, report)
    validate_multi_values_and_coverage(rows, report)
    evidence, source_works = validate_references(rows, provenance, sources, report, package_root, exact_header)
    validate_paths_and_materialization(
        rows,
        provenance,
        parsed_values,
        report,
        package_root,
        exact_header,
        post_run_register,
    )
    validate_contradictions(rows, report)
    validate_published_purity(rows, parsed_values, evidence, source_works, report)
    validate_audit_boundaries(rows, parsed_values, provenance, evidence, report)
    validate_claim_provenance_boundaries(rows, parsed_values, report)
    validate_bindings(rows, parsed_values, provenance, report)
    validate_resolution_documents(
        rows, parsed_values, provenance, report, package_root
    )
    validate_diagnostics_and_governance(rows, parsed_values, provenance, report)
    validate_representation(rows, report)
    validate_scenarios_and_oracles(rows, parsed_values, provenance, report)
    validate_trace_schema_contract(rows, parsed_values, provenance, report)
    validate_catalog_seeds(rows, parsed_values, provenance, report)
    validate_traces_rejection_and_premature_outputs(rows, parsed_values, provenance, report)
    validate_test_catalog(rows, parsed_values, provenance, report)
    validate_source_manifest_gate(rows, parsed_values, provenance, report)
    validate_t03_3_7_infrastructure(
        rows,
        parsed_values,
        provenance,
        report,
        package_root,
        post_run_register,
    )
    validate_executable_schema_suite(
        rows,
        parsed_values,
        provenance,
        sources,
        report,
        package_root,
    )
    validate_t03_3_6_materialization(
        rows,
        parsed_values,
        provenance,
        report,
        package_root,
        post_run_register,
    )
    validate_prohibited_uses(rows, parsed_values, report, exact_header)
    exit_code = EXIT_FINDINGS if any(item["severity"] == "error" for item in report.findings) else EXIT_PASS
    return report, exit_code


def parser_for(script_path: Path) -> argparse.ArgumentParser:
    package_root = script_path.resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, default=package_root)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--diagnostic", action="store_true", help="continue semantic checks on the legacy 29-column ledger")
    return parser


def complete_paths(args: argparse.Namespace) -> argparse.Namespace:
    root = args.package_root.resolve()
    args.package_root = root
    args.ledger = (args.ledger or root / "sources" / "DERIVATION_LEDGER.csv").resolve()
    args.schema = (args.schema or root / "schemas" / "derivation_ledger.schema.json").resolve()
    args.provenance = (args.provenance or root / "PROVENANCE.json").resolve()
    args.sources = (args.sources or root / "sources" / "SOURCES.json").resolve()
    return args


def emit(document: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")


def main(argv: Iterable[str] | None = None) -> int:
    parser = parser_for(Path(__file__))
    try:
        args = complete_paths(parser.parse_args(list(argv) if argv is not None else None))
        report, exit_code = run_validation(args)
    except InputFailure as exc:
        report = Report("diagnostic" if "--diagnostic" in sys.argv else "strict")
        report.add("validator.input", str(exc))
        emit(report.document(EXIT_ERROR))
        return EXIT_ERROR
    except Exception as exc:  # pragma: no cover - defensive exit-code boundary
        report = Report("diagnostic" if "--diagnostic" in sys.argv else "strict")
        report.add("validator.internal", f"{type(exc).__name__}: {exc}")
        emit(report.document(EXIT_ERROR))
        return EXIT_ERROR
    emit(report.document(exit_code))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
