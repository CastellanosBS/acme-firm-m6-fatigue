#!/usr/bin/env python3
"""Build the IFATIGUE-INFRA6-M6 derivation ledger deterministically.

The builder migrates the legacy 29-column ledger to the orthogonal 32-column
v1.1 contract, preserves stable row identifiers whenever a support relation
survives, rebuilds the scientifically sensitive derivations, and adds a
materialisation recipe for every path declared by PROVENANCE.json.

Only authored specification inputs, executable schemas and frozen synthetic
oracles are materialised in the ledger. Reference-run results, traces, logs,
and environment observations remain recipes with
``status_before_run=not_observed``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


HEADER = [
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

FROZEN_PROVENANCE_SHA256 = (
    "1818a4ee89dca14d3bf1c7583595cc3193aeb17a68420ded321692f5429ad319"
)
PRE_MIGRATION_LEDGER_SHA256 = (
    "ae5824820eb5fb558de1b774d3b7ffccfe24638abb23fff6f4d062b4a1fa7681"
)
PRE_MIGRATION_LEGACY_ROWS = 177
DECISION_REPLACEMENTS = {"T03-RP-007": "T03-RP-012"}
STABLE_SCENARIO_EVENT = {
    "event_id": "EVT-CONFORMANCE-001",
    "kind": "synthetic_tutoring_event",
}
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
CLOSED_JSON_PROJECTION_PATHS = SPEC_LAYER_PATHS | CONFIGURATION_LAYER_PATHS


def pre_migration_identity() -> dict[str, str]:
    """Return the audited 177 row IDs and their immutable 121 derivation IDs."""
    counts: dict[str, int] = {}

    def numbered(prefix: str, values: Sequence[int]) -> None:
        for index, count in enumerate(values, start=1):
            counts[f"{prefix}-{index:03d}"] = count

    numbered("DL-ART", [2] * 7)
    counts["DL-BLOCK-001"] = 1
    numbered("DL-CTX", [1] * 3)
    numbered("DL-EVAL", [1, 1, 2, 2])
    numbered("DL-EXC", [4, 2, 2, 4, 2])
    numbered("DL-FST", [1, 2, 2, 1, 2, 1, 2, 1, 1, 1, 2, 1, 1, 2])
    counts["DL-GOV-001"] = 1
    numbered("DL-HST", [1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1])
    numbered("DL-LIM", [3, 3, 2, 2])
    counts.update({"DL-LINEAGE-F1-001": 1, "DL-LINEAGE-F4-001": 2, "DL-LINEAGE-F5-001": 1})
    numbered("DL-LX", [2, 2, 1])
    numbered("DL-MAP", [1, 2, 1])
    numbered("DL-MOD", [1, 1, 1, 2, 1])
    numbered("DL-PKG", [1] * 3)
    numbered("DL-REP", [1] * 9)
    numbered("DL-RUL-ANG", [1] * 8)
    numbered("DL-RUL-CONFLICT", [2, 1])
    numbered("DL-RUL-SAD", [1] * 10)
    counts["DL-RUL-SELECT-001"] = 1
    for index in range(16):
        counts[f"DL-SCN-{index:02d}"] = 2 if index in {8, 12, 13, 14, 15} else 1
    numbered("DL-SCOPE", [2, 1, 1])
    identity = {
        f"ROW-{derivation_id}-{ordinal:02d}": derivation_id
        for derivation_id, count in counts.items()
        for ordinal in range(1, count + 1)
    }
    if len(counts) != 121 or len(identity) != PRE_MIGRATION_LEGACY_ROWS:
        raise AssertionError("pre-migration identity registry is internally inconsistent")
    return identity


PRE_MIGRATION_IDENTITY = pre_migration_identity()

REQUIRED_DECISIONS = {
    "T03-PR-001",
    "T03-AV-002",
    "T03-QG-003",
    "T03-TM-004",
    "T03-RS-005",
    "T03-BL-006",
    "T03-DL-008",
    "T03-CT-009",
    "T03-EX-010",
    "T03-QA-011",
    "T03-RP-012",
    "T03-MP-013",
}

REQUIRED_EVIDENCE = {
    "EV-THESIS-HOST",
    "EV-THESIS-DYADIC-PERSPECTIVE",
    "EV-THESIS-FACTOR",
    "EV-THESIS-CONTRACT-TESTS",
    "EV-THESIS-RESULTS-LIMITS",
    "EV-2018A-VARIABLES",
    "EV-2018A-SADNESS",
    "EV-2018B-GA-EF",
    "EV-2018B-VARIABLES",
    "EV-2018B-RULES",
}

PROTECTED_FIELDS = [
    "expectedness",
    "desirability",
    "novelty",
    "pleasure",
    "goal_conduciveness",
]
VECTOR_FIELDS = PROTECTED_FIELDS + ["coping_potential"]
PROTECTED_BASELINE = {
    "expectedness": "0.11",
    "desirability": "0.22",
    "novelty": "0.33",
    "pleasure": "0.44",
    "goal_conduciveness": "0.55",
}

PUBLISHED_VARIABLES = [
    "Expectedness",
    "Desirability",
    "Novelty",
    "Goals conduciveness",
    "Pleasure",
    "Coping potential",
]

SADNESS_ANTECEDENTS = [
    {"field": "Consequence (E)", "operator": "IS", "value": ["myself", "another"], "value_join": "OR"},
    {"field": "Goal conduciveness (E)", "operator": "IS", "value": "negative"},
    {"field": "Coping potential (E)", "operator": "IS", "value": "positive"},
    {"field": "Pleasantness(E)", "operator": "IS", "value": "unpleasant"},
    {"field": "Expectedness(E)", "operator": "IS", "value": "expected"},
    {"field": "Desirability(E)", "operator": "IS", "value": "highly undesirable"},
    {"field": "Novelty (E)", "operator": "IS", "value": "low novelty"},
]

ANGER_ANTECEDENTS = [
    {"field": "Desirability (E)", "operator": "IS", "value": "undesirable"},
    {"field": "Expectation (E)", "operator": "IS", "value": "unexpected"},
    {"field": "Novelty (E)", "operator": "IS", "value": "not_novelty"},
    {"field": "Pleasure (E)", "operator": "IS", "value": "not_pleasant"},
    {"field": "Goal-conduciveness (E)", "operator": "IS", "value": "negative"},
    {
        "field": "Coping potential (E)",
        "operator": "IS",
        "terminal_punctuation": ".",
        "value": "null",
    },
]

CONFLICT_ANTECEDENTS = [
    {"field": "Desirability (E)", "operator": "IS", "value": "highly undesirable"},
    {"field": "Expectation (E)", "operator": "IS", "value": "expected"},
    {"field": "Novelty (E)", "operator": "IS", "value": "low_novelty"},
    {"field": "Pleasure (E)", "operator": "IS", "value": "not_pleasant"},
    {"field": "Goal-conduciveness (E)", "operator": "IS", "value": "negative"},
    {"field": "Coping potential (E)", "operator": "IS", "value": "approachable"},
]


def canonical_json(value: Any) -> str:
    """Return the exact canonical JSON cell representation used by the ledger."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def split_refs(value: str) -> list[str]:
    return [part for part in value.split("|") if part]


def join_refs(values: Iterable[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return "|".join(ordered)


def utc_parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value}")
    return parsed.astimezone(timezone.utc)


def utc_format(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_source_status(value: Any) -> str:
    """Map registry-specific verification detail to the v1.1 ledger enum."""
    status = str(value or "").strip().casefold()
    if status.startswith("verified"):
        return "verified"
    if status == "failed" or status.startswith("failed_"):
        return "failed"
    if status in {"", "pending", "unverified"} or status.startswith(("pending_", "unverified_")):
        return "pending"
    return "pending"


def canonical_decision_id(value: str) -> str:
    """Resolve an explicitly superseded decision to its approved replacement."""
    return DECISION_REPLACEMENTS.get(value, value)


def decision_map(provenance: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {item["id"]: item for item in provenance.get("decisions", [])}


def evidence_map(sources: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {item["id"]: item for item in sources.get("evidence_units", [])}


def scientific_claim_map(provenance: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {item["claim_id"]: item for item in provenance.get("scientific_claims", [])}


def qa_test_catalog(provenance: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the exact T03-QA-011 catalogue; never invent test identifiers."""
    qa = decision_map(provenance).get("T03-QA-011", {}).get("decision", {})
    candidates: list[list[dict[str, Any]]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            if len(value) == 18 and all(isinstance(item, dict) for item in value):
                ids = [item.get("test_id", item.get("id")) for item in value]
                if ids == [f"UT-{index:03d}" for index in range(1, 19)] and all(
                    isinstance(item.get("fq_method"), str) and item["fq_method"]
                    for item in value
                ):
                    candidates.append(value)
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(qa)
    if len(candidates) != 1:
        raise ValueError(
            "T03-QA-011 must contain exactly one authoritative UT-001..UT-018 catalogue"
        )
    return deepcopy(candidates[0])


def expanded_plan(provenance: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    paths: list[str] = []
    origins: dict[str, str] = {}
    for item in provenance.get("planned_tree", []):
        path = item["path"]
        paths.append(path)
        origins[path] = item["origin_class"]
    for file_set in provenance.get("planned_file_sets", []):
        for path in file_set.get("paths", []):
            paths.append(path)
            origins[path] = file_set["origin_class"]
    if len(paths) != len(set(paths)):
        duplicates = sorted(path for path in set(paths) if paths.count(path) > 1)
        raise ValueError(f"duplicate planned paths: {duplicates}")
    return paths, origins


def _contains_all_casefold(haystack: str, needles: Sequence[str]) -> bool:
    folded = haystack.casefold()
    return all(needle.casefold() in folded for needle in needles)


def readiness_error(provenance: Mapping[str, Any], sources: Mapping[str, Any]) -> str | None:
    decisions = decision_map(provenance)
    missing_decisions = sorted(REQUIRED_DECISIONS - decisions.keys())
    if missing_decisions:
        return f"PROVENANCE is awaiting decisions {missing_decisions}"
    not_approved = sorted(
        did
        for did in REQUIRED_DECISIONS
        if not str(decisions[did].get("status", "")).startswith("approved")
    )
    if not_approved:
        return f"PROVENANCE decisions are not approved: {not_approved}"

    paths, _ = expanded_plan(provenance)
    if len(paths) != 159:
        return f"PROVENANCE must declare the frozen 159-path v1.1 plan, found {len(paths)}"
    if "scripts/build_derivation_ledger.py" not in paths:
        return "PROVENANCE does not yet declare scripts/build_derivation_ledger.py"
    if "scripts/build_source_manifest.py" not in paths:
        return "PROVENANCE does not yet declare scripts/build_source_manifest.py"

    sadness_paths = [path for path in paths if re.search(r"sadness|tristeza", path, re.I)]
    sadness_fixtures = [
        path
        for path in sadness_paths
        if re.search(r"fixture|scenario|escenario", path, re.I)
        and not re.search(r"oracle|expected|oraculo", path, re.I)
    ]
    sadness_oracles = [
        path for path in sadness_paths if re.search(r"oracle|expected|oraculo", path, re.I)
    ]
    if len(sadness_fixtures) != 1 or len(sadness_oracles) != 1:
        return "PROVENANCE must declare exactly one symbolic sadness fixture and one oracle"

    rs_text = canonical_json(decisions["T03-RS-005"].get("decision"))
    if not _contains_all_casefold(
        rs_text,
        [
            "event_context.cause_class",
            "event_context.consequence_target",
            "symbolic_regression_only",
            "Anger",
            "anger",
        ],
    ):
        return "T03-RS-005 has not yet incorporated the corrected rule-layer contract"

    qa_text = canonical_json(decisions["T03-QA-011"].get("decision"))
    if not _contains_all_casefold(qa_text, ["source_of_truth", "UT-001", "UT-018"]):
        return "T03-QA-011 has not yet incorporated the source-of-truth and UT-001..UT-018 contract"
    try:
        tests = qa_test_catalog(provenance)
    except ValueError as exc:
        return str(exc)
    if len({item["fq_method"] for item in tests}) != 18:
        return "T03-QA-011 contains duplicate fq_method values"

    diagnostic_codes = decisions["T03-CT-009"].get("decision", {}).get("diagnostic_codes", [])
    if len(diagnostic_codes) != 22 or len(diagnostic_codes) != len(set(diagnostic_codes)):
        return "T03-CT-009 must contain exactly twenty-two unique diagnostic codes"
    diagnostic_text = "|".join(str(code) for code in diagnostic_codes).upper()
    required_diagnostic_fragments = [
        "LEVEL_MISSING",
        "CONFIDENCE",
        "SOURCE_ID",
        "TYPE_INVALID",
    ]
    if not all(fragment in diagnostic_text for fragment in required_diagnostic_fragments):
        return "T03-CT-009 diagnostic catalogue is still the pre-audit version"
    qa_diagnostics = decisions["T03-QA-011"].get("decision", {}).get(
        "diagnostic_priority", []
    )
    if diagnostic_codes != qa_diagnostics:
        return "T03-CT-009 diagnostic codes and T03-QA-011 priority must be byte-identical"

    evidence = evidence_map(sources)
    missing_evidence = sorted(REQUIRED_EVIDENCE - evidence.keys())
    if missing_evidence:
        return f"SOURCES is awaiting evidence units {missing_evidence}"
    failed_evidence = sorted(
        eid
        for eid in REQUIRED_EVIDENCE
        if normalized_source_status(evidence[eid].get("verification_status")) != "verified"
    )
    if failed_evidence:
        return f"required evidence is not verified: {failed_evidence}"
    return None


def read_stable_inputs(root: Path, wait_seconds: float) -> tuple[dict[str, Any], dict[str, Any]]:
    provenance_path = root / "PROVENANCE.json"
    sources_path = root / "sources" / "SOURCES.json"
    deadline = time.monotonic() + wait_seconds
    last_error = "input files not read"
    while True:
        try:
            first_provenance = provenance_path.read_bytes()
            first_sources = sources_path.read_bytes()
            if hashlib.sha256(first_provenance).hexdigest() != FROZEN_PROVENANCE_SHA256:
                raise ValueError("PROVENANCE.json is not the frozen audited snapshot")
            provenance = json.loads(first_provenance)
            sources = json.loads(first_sources)
            error = readiness_error(provenance, sources)
            time.sleep(0.20)
            second_provenance = provenance_path.read_bytes()
            second_sources = sources_path.read_bytes()
            if first_provenance != second_provenance or first_sources != second_sources:
                last_error = "PROVENANCE/SOURCES changed during snapshot"
            elif error is None:
                return provenance, sources
            else:
                last_error = error
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        if time.monotonic() >= deadline:
            raise RuntimeError(f"readiness gate timed out: {last_error}")
        print(f"waiting for stable v1.1 provenance: {last_error}", file=sys.stderr)
        time.sleep(0.80)


def load_existing_rows(path: Path, evidence: Mapping[str, Any]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        raw_rows = list(reader)
    legacy = "artifact_or_object_ref" in fieldnames and "materialization_status" not in fieldnames
    if fieldnames != HEADER and not legacy:
        raise ValueError(f"unsupported existing ledger header ({len(fieldnames)} columns)")
    if not legacy:
        restored: list[dict[str, str]] = []
        for raw in raw_rows:
            row = {key: raw.get(key, "") for key in HEADER}
            # Early versions of this builder preserved five displaced legacy
            # edges under an invalid audit derivation.  Restore their immutable
            # row/derivation/support identities before rebuilding the atom.
            if row["derivation_id"].startswith("DL-AUDIT-LEGACY-"):
                try:
                    audit = json.loads(row["target_value"])
                except (json.JSONDecodeError, TypeError):
                    audit = {}
                original_derivation = audit.get("legacy_derivation_id")
                if isinstance(original_derivation, str) and original_derivation:
                    row["derivation_id"] = original_derivation
                    row["target_path"] = str(audit.get("legacy_target_path", row["target_path"]))
                    row["target_locator"] = str(audit.get("legacy_target_locator", row["target_locator"]))
                    row["support_ref_type"] = str(audit.get("legacy_support_ref_type", ""))
                    row["support_ref_id"] = str(audit.get("legacy_support_ref_id", ""))
            restored.append(row)
        return restored

    converted: list[dict[str, str]] = []
    for old in raw_rows:
        old_status = old.get("status", "")
        support_type = old.get("support_ref_type", "")
        support_id = old.get("support_ref_id", "")
        approvals = split_refs(old.get("approval_ref", ""))
        if support_type == "approved_decision" and support_id:
            approvals.append(support_id)
        if old_status == "blocked":
            materialization = "blocked"
            decision_status = "pending"
        elif old_status == "superseded":
            materialization = "superseded"
            decision_status = "superseded"
        else:
            materialization = "planned"
            decision_status = "approved" if approvals else "not_required"
        source_status = "not_applicable"
        if support_type == "evidence_unit":
            source_status = normalized_source_status(
                evidence.get(support_id, {}).get("verification_status", "pending")
            )
        converted.append(
            {
                "row_id": old.get("row_id", ""),
                "derivation_id": old.get("derivation_id", ""),
                "target_path": old.get("target_path", ""),
                "target_locator": old.get("target_locator", ""),
                "target_field": old.get("target_field", ""),
                "target_value": old.get("target_value", ""),
                "purpose": old.get("purpose", ""),
                "artifact_or_object_refs": old.get("artifact_or_object_ref", ""),
                "file_origin_class": old.get("file_origin_class", ""),
                "support_ref_type": support_type,
                "support_ref_id": support_id,
                "support_locator_or_decision": old.get("support_locator_or_decision", ""),
                "parent_derivation_id": old.get("parent_derivation_id", ""),
                "claim_ref": old.get("claim_ref", ""),
                "claim_provenance_class": old.get("claim_provenance_class", ""),
                "support_level": old.get("support_level", ""),
                "transformation_type": old.get("transformation_type", ""),
                "transformation_or_tension": old.get("transformation_or_tension", ""),
                "d_refs": old.get("d_refs", ""),
                "rl_refs": old.get("rl_refs", ""),
                "r_refs": old.get("r_refs", ""),
                "f_refs": old.get("f_refs", ""),
                "a_refs": old.get("a_refs", ""),
                "m_level_refs": old.get("m_level_refs", ""),
                "effect_on_M6": old.get("effect_on_M6", ""),
                "limits": old.get("limits", ""),
                "source_verification_status": source_status,
                "decision_approval_status": decision_status,
                "approval_refs": join_refs(approvals),
                "materialization_status": materialization,
                "materialization_refs": "",
                "reviewed_at_utc": old.get("reviewed_at_utc", ""),
            }
        )
    return converted


class LedgerBuilder:
    def __init__(
        self,
        root: Path,
        provenance: Mapping[str, Any],
        sources: Mapping[str, Any],
        existing_rows: Sequence[Mapping[str, str]],
    ) -> None:
        self.root = root
        self.provenance = provenance
        self.sources = sources
        self.decisions = decision_map(provenance)
        self.evidence = evidence_map(sources)
        self.claims = scientific_claim_map(provenance)
        self.planned_paths, self.origins = expanded_plan(provenance)
        self.reviewed_at = provenance["document"]["updated_at_utc"]
        self.open_decisions = {
            item["id"]: item for item in provenance.get("open_decisions", []) if item.get("id")
        }
        existing_by_id = {
            row["row_id"]: dict(row) for row in existing_rows if row.get("row_id")
        }
        missing_pre_migration = set(PRE_MIGRATION_IDENTITY) - set(existing_by_id)
        if missing_pre_migration:
            raise ValueError(
                f"pre-migration row identities are missing: {sorted(missing_pre_migration)}"
            )
        self.legacy_rows = {
            row_id: existing_by_id[row_id] for row_id in PRE_MIGRATION_IDENTITY
        }
        for row_id, derivation_id in PRE_MIGRATION_IDENTITY.items():
            self.legacy_rows[row_id]["derivation_id"] = derivation_id
        self.legacy_row_ids = set(PRE_MIGRATION_IDENTITY)
        self.rows: list[dict[str, str]] = []
        self.used_row_ids: set[str] = set()
        self._exact_ids: dict[tuple[str, str, str, str, str], list[str]] = defaultdict(list)
        self._fallback_ids: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        self._derivation_approvals: dict[str, list[str]] = defaultdict(list)
        for row in existing_rows:
            indexed_support_id = canonical_decision_id(row.get("support_ref_id", ""))
            exact = (
                row.get("derivation_id", ""),
                row.get("target_path", ""),
                row.get("target_locator", ""),
                row.get("support_ref_type", ""),
                indexed_support_id,
            )
            fallback = (
                row.get("derivation_id", ""),
                row.get("support_ref_type", ""),
                indexed_support_id,
            )
            if row.get("row_id"):
                self._exact_ids[exact].append(row["row_id"])
                self._fallback_ids[fallback].append(row["row_id"])
            self._derivation_approvals[row.get("derivation_id", "")].extend(
                canonical_decision_id(value)
                for value in split_refs(row.get("approval_refs", ""))
            )
            if row.get("support_ref_type") == "approved_decision" and row.get("support_ref_id"):
                self._derivation_approvals[row.get("derivation_id", "")].append(
                    indexed_support_id
                )
        self._derivation_approvals = {
            key: split_refs(join_refs(values))
            for key, values in self._derivation_approvals.items()
        }
        for candidates in list(self._exact_ids.values()) + list(self._fallback_ids.values()):
            candidates.sort()

    def _row_id(
        self,
        derivation_id: str,
        target_path: str,
        target_locator: str,
        support_type: str,
        support_id: str,
    ) -> str:
        exact = (derivation_id, target_path, target_locator, support_type, support_id)
        fallback = (derivation_id, support_type, support_id)
        for mapping, key in ((self._exact_ids, exact), (self._fallback_ids, fallback)):
            for candidate in mapping.get(key, []):
                if candidate not in self.used_row_ids:
                    self.used_row_ids.add(candidate)
                    return candidate
        number = 1
        while True:
            candidate = f"ROW-{derivation_id}-{number:02d}"
            if candidate not in self.used_row_ids:
                self.used_row_ids.add(candidate)
                return candidate
            number += 1

    def normalize_existing(self, row: Mapping[str, str]) -> dict[str, str]:
        fixed = {key: row.get(key, "") for key in HEADER}
        if fixed["target_path"] == "docs/SOURCE_MAP.md":
            # This is an authored human-readable synthesis reconciled against
            # the authoritative registries, not the byte output of a
            # registered generator.
            fixed["target_origin_class"] = "generated_for_doctoral_instance"
            fixed["claim_provenance_class"] = "generated_for_doctoral_instance"
        # T03.3-9-COR-002: two legacy pre-run rows named fields that the
        # accepted reference summary never exposes.  Preserve the derivation
        # identities while binding them to the actual, semantically equivalent
        # post-run fields.  Values remain null in the frozen source ledger; the
        # downstream materialization register attests the observed document.
        if fixed["derivation_id"] == "DL-EVAL-003":
            fixed["target_locator"] = "/trace_count"
            fixed["target_field"] = "trace.count"
        elif fixed["derivation_id"] == "DL-LIM-004":
            fixed["target_locator"] = "/scope"
            fixed["target_field"] = "results.evidence_scope"
        support_type = fixed["support_ref_type"]
        support_id = fixed["support_ref_id"]
        if support_type == "approved_decision":
            support_id = canonical_decision_id(support_id)
            fixed["support_ref_id"] = support_id
            fixed["support_locator_or_decision"] = (
                f"PROVENANCE.json#decisions/{support_id}" if support_id else ""
            )
        elif not support_type:
            fixed["support_ref_id"] = ""
            fixed["support_locator_or_decision"] = ""
        if support_type == "evidence_unit":
            fixed["source_verification_status"] = normalized_source_status(
                self.evidence.get(support_id, {}).get("verification_status", "pending")
            )
        else:
            fixed["source_verification_status"] = "not_applicable"
        approvals = [
            canonical_decision_id(value)
            for value in (
            self._derivation_approvals.get(
                fixed["derivation_id"], split_refs(fixed["approval_refs"])
            )
            )
        ]
        if support_type == "approved_decision" and support_id:
            approvals.append(support_id)
        fixed["approval_refs"] = join_refs(approvals)
        if approvals:
            approval_states = [
                "pending" if value in self.open_decisions else "approved"
                for value in approvals
            ]
            fixed["decision_approval_status"] = (
                "pending" if "pending" in approval_states else "approved"
            )
        else:
            fixed["decision_approval_status"] = "not_required"
        if fixed["derivation_id"] == "DL-BLOCK-001":
            fixed["approval_refs"] = "T05-IP-001"
            fixed["decision_approval_status"] = "pending"
        if fixed["derivation_id"].startswith("DL-EXC-"):
            fixed["materialization_status"] = "excluded"
            fixed["materialization_refs"] = ""
            fixed["claim_provenance_class"] = "excluded_from_execution"
            fixed["transformation_type"] = "preserve_and_exclude"
        if fixed["materialization_status"] in {"superseded", "excluded"}:
            fixed["materialization_refs"] = ""
        elif fixed["materialization_status"] == "blocked":
            fixed["materialization_refs"] = ""
        elif fixed["target_path"].startswith(("results/", "traces/", "logs/", "environment/")):
            fixed["materialization_status"] = "planned"
            fixed["materialization_refs"] = ""
            if fixed["target_locator"] != "@materialization-recipe":
                fixed["target_value"] = "null"
                fixed["limits"] = (
                    "Valor diferido hasta la ejecución registrada; el registro legacy no "
                    "constituye un resultado observado."
                )
        elif (
            fixed["target_path"]
            in {
                "PROVENANCE.json",
                "sources/SOURCES.json",
                "sources/DERIVATION_LEDGER.csv",
                "schemas/sources.schema.json",
                "schemas/derivation_ledger.schema.json",
                "scripts/build_derivation_ledger.py",
                "scripts/validate_derivation_ledger.py",
            }
            | CLOSED_JSON_PROJECTION_PATHS
            and (self.root / fixed["target_path"]).exists()
        ):
            fixed["materialization_status"] = "materialized_t03"
            fixed["materialization_refs"] = fixed["target_path"]
        elif (
            fixed["target_path"]
            not in {
                "CITATION.cff",
                "MANIFIESTO_SHA256.txt",
                "manifests/BUILD_RECORD.json",
            }
            and (self.root / fixed["target_path"]).is_file()
        ):
            # Authored and documentation targets are frozen before the final
            # source-manifest refresh.  Reference-derived outputs remain in the
            # pre-run state above and are attested downstream in
            # PACKAGE_METADATA.json to avoid a cryptographic cycle.
            fixed["materialization_status"] = "materialized_t03"
            fixed["materialization_refs"] = fixed["target_path"]
        else:
            fixed["materialization_status"] = "planned"
            fixed["materialization_refs"] = ""
        return fixed

    def keep(self, row: Mapping[str, str]) -> None:
        fixed = self.normalize_existing(row)
        if fixed["row_id"] in self.used_row_ids:
            raise ValueError(f"duplicate preserved row_id: {fixed['row_id']}")
        self.used_row_ids.add(fixed["row_id"])
        self.rows.append(fixed)

    def add(
        self,
        derivation_id: str,
        target_path: str,
        target_locator: str,
        target_field: str,
        target_value: Any,
        *,
        purpose: str,
        object_refs: str,
        supports: Sequence[tuple[str, str, str, str]],
        parent: str = "",
        claim_ref: str = "",
        claim_class: str | None = None,
        transformation_type: str = "engineering_decision",
        transformation: str = "Decisión explícita, separada de la evidencia fuente y trazable.",
        d_refs: str = "",
        rl_refs: str = "",
        r_refs: str = "",
        f_refs: str = "F6",
        a_refs: str = "A3|A4",
        m_refs: str = "M6",
        effect: str = "Hace materializable y auditable la instancia M6.",
        limits: str = "No constituye evidencia empírica ni acredita ejecución o validación externa.",
        approvals: Sequence[str] = (),
        materialization_status: str = "planned",
        materialization_refs: str = "",
        origin: str | None = None,
        forced_row_id: str | None = None,
    ) -> None:
        if target_path not in self.origins:
            raise ValueError(f"target path is not planned: {target_path}")
        origin = origin or self.origins[target_path]
        if (
            materialization_status == "planned"
            and not target_path.startswith(("results/", "traces/", "logs/", "environment/"))
            and target_path
            not in {
                "CITATION.cff",
                "MANIFIESTO_SHA256.txt",
                "manifests/BUILD_RECORD.json",
            }
            and (self.root / target_path).is_file()
        ):
            materialization_status = "materialized_t03"
            materialization_refs = target_path
        if claim_class is None:
            claim_class = (
                self.claims.get(claim_ref, {}).get("claim_provenance_class")
                if claim_ref
                else "generated_for_doctoral_instance"
            )
        effective_supports = list(supports) or [("", "", "", "")]
        shared_approval_values = list(approvals)
        shared_approval_values.extend(
            support_id
            for support_type, support_id, _support_level, _support_locator in effective_supports
            if support_type == "approved_decision" and support_id
        )
        shared_approval_text = join_refs(shared_approval_values)
        for support_type, support_id, support_level, support_locator in effective_supports:
            approval_text = shared_approval_text
            source_status = "not_applicable"
            if support_type == "evidence_unit":
                source_status = normalized_source_status(
                    self.evidence.get(support_id, {}).get("verification_status", "pending")
                )
            if approval_text:
                decision_status = (
                    "pending"
                    if any(value in self.open_decisions for value in split_refs(approval_text))
                    else "approved"
                )
            else:
                decision_status = "not_required"
            if forced_row_id is not None:
                if len(effective_supports) != 1:
                    raise ValueError("forced_row_id requires exactly one support edge")
                if forced_row_id in self.used_row_ids:
                    raise ValueError(f"duplicate forced row_id: {forced_row_id}")
                self.used_row_ids.add(forced_row_id)
                row_id = forced_row_id
            else:
                row_id = self._row_id(
                    derivation_id,
                    target_path,
                    target_locator,
                    support_type,
                    support_id,
                )
            self.rows.append(
                {
                    "row_id": row_id,
                    "derivation_id": derivation_id,
                    "target_path": target_path,
                    "target_locator": target_locator,
                    "target_field": target_field,
                    "target_value": canonical_json(target_value),
                    "purpose": purpose,
                    "artifact_or_object_refs": object_refs,
                    "file_origin_class": origin,
                    "support_ref_type": support_type,
                    "support_ref_id": support_id,
                    "support_locator_or_decision": support_locator,
                    "parent_derivation_id": parent,
                    "claim_ref": claim_ref,
                    "claim_provenance_class": claim_class or "generated_for_doctoral_instance",
                    "support_level": support_level,
                    "transformation_type": transformation_type,
                    "transformation_or_tension": transformation,
                    "d_refs": d_refs,
                    "rl_refs": rl_refs,
                    "r_refs": r_refs,
                    "f_refs": f_refs,
                    "a_refs": a_refs,
                    "m_level_refs": m_refs,
                    "effect_on_M6": effect,
                    "limits": limits,
                    "source_verification_status": source_status,
                    "decision_approval_status": decision_status,
                    "approval_refs": approval_text,
                    "materialization_status": materialization_status,
                    "materialization_refs": materialization_refs,
                    "reviewed_at_utc": self.reviewed_at,
                }
            )


def ev(evidence_id: str, level: str = "direct") -> tuple[str, str, str, str]:
    return ("evidence_unit", evidence_id, level, f"SOURCES.json#{evidence_id}")


def dec(decision_id: str) -> tuple[str, str, str, str]:
    return (
        "approved_decision",
        decision_id,
        "direct",
        f"PROVENANCE.json#decisions/{decision_id}",
    )


def rebuild_filter(derivation_id: str) -> bool:
    exact = {
        "DL-HST-003",
        "DL-HST-004",
        "DL-HST-005",
        "DL-HST-006",
        "DL-HST-007",
        "DL-HST-008",
        "DL-HST-009",
        "DL-HST-010",
        "DL-HST-011",
        "DL-HST-012",
        "DL-HST-016",
        "DL-FST-002",
        "DL-FST-006",
        "DL-FST-007",
        "DL-FST-008",
        "DL-FST-009",
        "DL-FST-010",
        "DL-FST-011",
        "DL-FST-012",
        "DL-FST-013",
        "DL-FST-014",
        "DL-FST-015",
        "DL-FST-016",
        "DL-FST-CONFIDENCE-DOMAIN-001",
        "DL-FST-CONFIDENCE-TYPE-001",
        "DL-GOV-001",
        "DL-MOD-001",
        "DL-MOD-002",
        "DL-MOD-005",
        "DL-MAP-001",
        "DL-CAT-001",
        "DL-CAT-002",
        "DL-CAT-003",
        "DL-CAT-004",
        "DL-DIAG-AGGREGATION-001",
        "DL-EVAL-001",
        "DL-EVAL-002",
        "DL-EVAL-004",
        "DL-REP-007",
        "DL-LIM-001",
        "DL-LIM-002",
    }
    prefixes = (
        "DL-LX-",
        "DL-HST-BND-",
        "DL-HST-PUB-",
        "DL-TRACE-",
        "DL-RUL-",
        "DL-CTX-",
        "DL-BIND-",
        "DL-CONFIG-",
        "DL-SCN-",
        "DL-ORC-",
        "DL-FIX-SADNESS-",
        "DL-ART-MIN-",
        "DL-REC-",
        "DL-EVAL-002-",
        "DL-BUILD-",
        "DL-TOPOLOGY-",
        "DL-SCHEMA-",
        "DL-AUDIT-LEGACY-",
    )
    return derivation_id in exact or derivation_id.startswith(prefixes) or derivation_id in {
        "DL-EXC-006",
        "DL-EXC-007",
    }


def add_host_layer_rows(builder: LedgerBuilder) -> None:
    builder.add(
        "DL-HST-003",
        "spec/thesis/f6_specification_rc01.json",
        "/host/appraisal_vector/order",
        "appraisal_vector.order",
        VECTOR_FIELDS,
        purpose="Fijar exclusivamente en la capa doctoral el orden de API y serialización.",
        object_refs="PA-INFRA6-1.0.0",
        supports=[
            ev("EV-THESIS-HOST"),
            ev("EV-2018A-VARIABLES", "does_not_support"),
        ],
        claim_ref="CLM-VECTOR-001",
        transformation_type="doctoral_synthesis",
        transformation="El orden F6 no se atribuye a la enumeración publicada de 2018a.",
        m_refs="M2|M6",
    )
    builder.add(
        "DL-HST-004",
        "spec/thesis/f6_specification_rc01.json",
        "/host/appraisal_vector/contract",
        "appraisal_vector.contract",
        {"cardinality": 6, "domain": {"inclusive": True, "maximum": "1", "minimum": "0"}},
        purpose="Fijar cardinalidad y dominio de la interfaz doctoral.",
        object_refs="PA-INFRA6-1.0.0|CI-FAT-INFRA6-1.0.0",
        supports=[
            ev("EV-THESIS-HOST"),
            ev("EV-THESIS-CONTRACT-TESTS"),
        ],
        claim_ref="CLM-HOST-001",
        transformation_type="doctoral_synthesis",
        transformation="El dominio numérico pertenece a F6 y no a la capa publicada.",
        m_refs="M2|M4|M6",
    )
    builder.add(
        "DL-HST-016",
        "spec/decisions/engineering_v1.1.0.json",
        "/host/scalar_type",
        "appraisal_vector.scalar_type",
        "decimal_string",
        purpose="Separar la representación decimal de la evidencia científica.",
        object_refs="CI-FAT-INFRA6-1.0.0",
        supports=[dec("T03-RP-012")],
        parent="DL-HST-004",
        m_refs="M4|M6",
    )
    for index, source_name in enumerate(PUBLISHED_VARIABLES):
        # Preserve both legacy support edges under their original identities as
        # one excluded migration snapshot.  The thesis edge never supports a
        # published name; the active replacement below is evidence-pure.
        builder.add(
            f"DL-HST-{index + 5:03d}",
            "spec/published/host_appraisal_2018a.json",
            f"/variables/{index}",
            f"published_variable.{index}",
            source_name,
            purpose="Preservar la pareja de aristas legacy como instantánea excluida de migración.",
            object_refs="PA-INFRA6-1.0.0",
            supports=[
                ev("EV-2018A-VARIABLES"),
                ev("EV-THESIS-HOST", "does_not_support"),
            ],
            claim_ref="CLM-HOST-001",
            claim_class="excluded_from_execution",
            transformation_type="preserve_and_exclude",
            transformation="La segunda arista no apoya el nombre publicado; el grupo legacy completo queda inactivo.",
            origin="reconstructed_from_published_specification",
            materialization_status="excluded",
            m_refs="M2|M6",
        )
        builder.add(
            f"DL-HST-PUB-{index + 5:03d}",
            "spec/published/host_appraisal_2018a.json",
            f"/variables/{index}",
            f"published_variable.{index}",
            source_name,
            purpose="Conservar exclusivamente el nombre fuente de la variable publicada.",
            object_refs="PA-INFRA6-1.0.0",
            supports=[ev("EV-2018A-VARIABLES")],
            claim_ref="CLM-HOST-001",
            transformation_type="metadata_transcription",
            transformation="No incorpora nombre canónico, orden F6, dominio ni especialización doctoral.",
            origin="reconstructed_from_published_specification",
            m_refs="M2|M6",
        )
    boundary_contract = builder.decisions["T03-RS-005"]["decision"][
        "boundary_terminology_adapter_contract"
    ]
    source_boundaries = boundary_contract["source_specific_adapters"]
    canonical_boundary = boundary_contract["canonical_doctoral_terms"]
    expected_source_boundaries = {
        "SRC-2018A-COGNITION-APPRAISAL": {
            "producer": "General Appraisal",
            "integration_boundary": "Emotional Filter",
        },
        "SRC-2018B-FLEXIBLE-SCHEME": {
            "producer": "General Appraisal (GA)",
            "integration_boundary": "Emotion Filter (EF)",
        },
    }
    if (
        source_boundaries != expected_source_boundaries
        or canonical_boundary
        != {"producer": "general_appraisal", "integration_boundary": "emotional_filter"}
        or boundary_contract["contract_layer"] != "decisions"
        or boundary_contract["published_layer_mutation"] is not False
    ):
        raise ValueError("T03-RS-005 boundary terminology contract is not exact")
    for derivation_id, field_name in (
        ("DL-HST-011", "producer"),
        ("DL-HST-012", "integration_boundary"),
    ):
        builder.add(
            derivation_id,
            "spec/decisions/engineering_v1.1.0.json",
            f"/published_boundary_adapter/canonical/{field_name}",
            f"published_boundary_adapter.canonical.{field_name}",
            canonical_boundary[field_name],
            purpose="Normalizar en la capa doctoral dos lexemas fuente sin modificar su transcripción publicada.",
            object_refs="PA-INFRA6-1.0.0|IF-GA-EF-1.0.0|BOUNDARY-TERMINOLOGY-ADAPTER",
            supports=[
                ev("EV-2018A-GA-EF", "interpreted"),
                ev("EV-2018B-GA-EF", "interpreted"),
                dec("T03-RS-005"),
            ],
            parent="DL-SCOPE-002",
            claim_ref="",
            claim_class="generated_for_doctoral_instance",
            transformation_type="lexical_adapter",
            transformation=(
                "Resolución fail-closed por source_id y lexema exacto; la forma canónica "
                "existe sólo en decisions/resolved."
            ),
            d_refs="D4|D6",
            rl_refs="RL4|RL7",
            r_refs="R2|R4|R5",
            m_refs="M2|M3|M4|M6",
            effect="Separa terminología fuente y vocabulario ejecutable sin colapsar 2018a/2018b.",
            limits="La normalización no reescribe ni homogeneiza retrospectivamente las publicaciones.",
        )
    boundary_rows = [
        (
            "DL-HST-PUB-GAEF-2018A-PRODUCER",
            "SRC-2018A-COGNITION-APPRAISAL",
            "EV-2018A-GA-EF",
            "producer",
        ),
        (
            "DL-HST-PUB-GAEF-2018A-BOUNDARY",
            "SRC-2018A-COGNITION-APPRAISAL",
            "EV-2018A-GA-EF",
            "integration_boundary",
        ),
        (
            "DL-HST-PUB-GAEF-2018B-PRODUCER",
            "SRC-2018B-FLEXIBLE-SCHEME",
            "EV-2018B-GA-EF",
            "producer",
        ),
        (
            "DL-HST-PUB-GAEF-2018B-BOUNDARY",
            "SRC-2018B-FLEXIBLE-SCHEME",
            "EV-2018B-GA-EF",
            "integration_boundary",
        ),
    ]
    source_branch = {
        "SRC-2018A-COGNITION-APPRAISAL": "2018a",
        "SRC-2018B-FLEXIBLE-SCHEME": "2018b",
    }
    for derivation_id, source_id, evidence_id, field_name in boundary_rows:
        branch = source_branch[source_id]
        builder.add(
            derivation_id,
            "spec/published/ga_ef_boundary_2018ab.json",
            f"/sources/{branch}/{field_name}",
            f"published_boundary.{branch}.{field_name}",
            source_boundaries[source_id][field_name],
            purpose="Transcribir literalmente un término de frontera propio de una publicación.",
            object_refs="PA-INFRA6-1.0.0|IF-GA-EF-1.0.0",
            supports=[ev(evidence_id)],
            parent="DL-SCOPE-002",
            claim_ref="CLM-GA-EF-001",
            transformation_type="metadata_transcription",
            transformation="Conserva mayúsculas, espacios y abreviatura exactamente como en la fuente.",
            origin="reconstructed_from_published_specification",
            d_refs="D4|D6",
            rl_refs="RL4|RL7",
            r_refs="R2|R4|R5",
            m_refs="M2|M6",
            effect="Hace explícita la frontera GA/EF por fuente sin insertar normalización doctoral.",
            limits="Describe terminología publicada; no implementa ni valida el cálculo de GA o EF.",
        )
    builder.add(
        "DL-FST-002",
        "spec/thesis/f6_specification_rc01.json",
        "/perspective",
        "factor_and_appraisal.perspective",
        {
            "appraisal_owner": "tutor",
            "coping_meaning": "tutor_perceived_capacity_for_pedagogical_response",
            "factor_owner": "student",
        },
        purpose="Fijar la perspectiva diádica de la miniinstanciación.",
        object_refs="PF-FAT-1.0.0|PA-INFRA6-1.0.0",
        supports=[
            ev("EV-THESIS-DYADIC-PERSPECTIVE", "interpreted"),
            ev("EV-2018A-VARIABLES", "does_not_support"),
        ],
        claim_ref="CLM-COPING-OWNER-001",
        transformation_type="doctoral_synthesis",
        transformation="La especialización pedagógica es doctoral; no se atribuye a 2018a.",
        m_refs="M1|M2|M6",
    )


def add_decision_contract_rows(builder: LedgerBuilder) -> None:
    ct = builder.decisions["T03-CT-009"]["decision"]
    tm = builder.decisions["T03-TM-004"]["decision"]
    dl_csv = builder.decisions["T03-DL-008"]["decision"]["csv_profile"]
    rp_csv = builder.decisions["T03-RP-012"]["decision"]["csv_profile"]
    if rp_csv != {
        "cell_policy": "all cells are strings; empty means absent; semantically required fields may not be empty; CR, LF and NUL are prohibited in cells",
        "decimal_cells": "IFM6-DEC-v1",
        "delimiter": ",",
        "double_quote": True,
        "encoding": "UTF-8_without_BOM",
        "escape_character": None,
        "final_lf": "exactly_one",
        "header_and_column_order": "schema-fixed",
        "identifier_uniqueness": True,
        "ledger_alias": "ACME-FIRM-CSV-UTF8-LF-1.0",
        "line_endings": "LF_only",
        "open_newline_argument": "",
        "profile_id": "IFM6-CSV-v1",
        "quote_character": '"',
        "quoting": "QUOTE_ALL",
        "row_order": "ascending ASCII primary key",
        "skip_initial_space": False,
        "sniffer_usage": "prohibited",
        "strict": True,
        "strict_rfc4180_claim": False,
        "unicode_normalization": "NFC",
    }:
        raise ValueError("T03-RP-012 IFM6-CSV-v1 profile is not exact")
    if not (
        dl_csv["delimiter"] == rp_csv["delimiter"]
        and dl_csv["quote_character"] == rp_csv["quote_character"]
        and dl_csv["escape_character"] == rp_csv["escape_character"]
        and dl_csv["unicode_normalization"] == rp_csv["unicode_normalization"]
        and dl_csv["strict_rfc4180_claim"] is False
        and rp_csv["strict_rfc4180_claim"] is False
    ):
        raise ValueError("T03-DL-008 and T03-RP-012 CSV profiles are incompatible")
    builder.add(
        "DL-GOV-001",
        "sources/DERIVATION_LEDGER.csv",
        "@dialect",
        "ledger.csv_profile",
        rp_csv,
        purpose="Fijar el perfil CSV reproducible exacto usado por el propio ledger.",
        object_refs="DERIVATION-LEDGER|IFM6-CSV-V1",
        supports=[dec("T03-DL-008"), dec("T03-RP-012")],
        transformation_type="engineering_decision",
        transformation="IFM6-CSV-v1 usa UTF-8 sin BOM, LF y QUOTE_ALL sin afirmar RFC 4180 estricto.",
        d_refs="D7|D9",
        rl_refs="RL7|RL9",
        r_refs="R5|R8",
        m_refs="M4|M6",
        effect="Hace verificable el dialecto exacto y evita una afirmación RFC 4180 incompatible con LF.",
        limits="El perfil restringido documenta serialización; no constituye evidencia científica independiente.",
        materialization_status="materialized_t03",
        materialization_refs="sources/DERIVATION_LEDGER.csv",
    )
    builder.add(
        "DL-FST-007",
        "spec/decisions/engineering_v1.1.0.json",
        "/factor_state/confidence/valid_when",
        "factor_state.confidence.valid_when",
        "confidence >= 0.5",
        purpose="Separar el umbral interpretado de confianza de su dominio y tipo técnicos.",
        object_refs="CI-FAT-INFRA6-1.0.0",
        supports=[
            ev("EV-THESIS-FACTOR", "interpreted"),
            dec("T03-CT-009"),
        ],
        claim_ref="REQ-CONF-001",
        claim_class="doctoral_inference",
        parent="DL-HST-004",
        transformation_type="engineering_decision",
        transformation="El umbral es una inferencia doctoral aprobada; no se atribuye literalmente a la tesis.",
        m_refs="M4|M6",
    )
    builder.add(
        "DL-FST-CONFIDENCE-DOMAIN-001",
        "spec/decisions/engineering_v1.1.0.json",
        "/factor_state/confidence/domain",
        "factor_state.confidence.domain",
        "[0,1]",
        purpose="Fijar separadamente el dominio técnico del campo confidence.",
        object_refs="CI-FAT-INFRA6-1.0.0",
        supports=[dec("T03-CT-009")],
        claim_ref="",
        claim_class="generated_for_doctoral_instance",
        parent="DL-FST-007",
        transformation_type="engineering_decision",
        m_refs="M4|M6",
    )
    builder.add(
        "DL-FST-CONFIDENCE-TYPE-001",
        "spec/decisions/engineering_v1.1.0.json",
        "/factor_state/confidence/type",
        "factor_state.confidence.type",
        "decimal_string",
        purpose="Fijar separadamente el tipo técnico del campo confidence.",
        object_refs="CI-FAT-INFRA6-1.0.0",
        supports=[dec("T03-CT-009")],
        claim_ref="",
        claim_class="generated_for_doctoral_instance",
        parent="DL-FST-007",
        transformation_type="engineering_decision",
        m_refs="M4|M6",
    )
    values = [
        ("DL-FST-006", "/factor_state/required_fields", "factor_state.required_fields", ct["factor_state"]["required_fields"]),
        ("DL-FST-008", "/factor_state/observed_at", "factor_state.observed_at", {"format": "RFC3339", "timezone": "UTC"}),
        ("DL-FST-009", "/factor_state/source_id", "factor_state.source_id", ct["factor_state"]["source_id"]),
        ("DL-FST-010", "/factor_state/state_schema_version", "factor_state.state_schema_version", ct["factor_state"]["state_schema_version"]),
        ("DL-FST-011", "/temporal_policy/age_seconds", "temporal.age_seconds", tm["age_seconds_definition"]),
        ("DL-FST-012", "/temporal_policy/stale", "temporal.stale", {"invalid_when": tm["stale_when"], "max_age_seconds": tm["max_age_seconds"]}),
        ("DL-FST-013", "/temporal_policy/future", "temporal.future", {"future_tolerance_seconds": tm["future_tolerance_seconds"], "invalid_when": tm["future_invalid_when"]}),
        ("DL-FST-014", "/failure_policy/factor", "factor_failure.policy", {"action": "abstain", "diagnostics": ct["diagnostic_aggregation"], "output": "baseline_unchanged"}),
        ("DL-FST-015", "/validation_order", "contract.validation_order", ct["validation_order"]),
        ("DL-FST-016", "/diagnostics/codes", "diagnostic.codes", ct["diagnostic_codes"]),
    ]
    for derivation_id, locator, field, value in values:
        support_id = "T03-TM-004" if derivation_id in {"DL-FST-011", "DL-FST-012", "DL-FST-013"} else "T03-CT-009"
        supports = [dec(support_id)]
        if derivation_id == "DL-FST-016":
            supports.append(dec("T03-QA-011"))
        if derivation_id in {"DL-FST-011", "DL-FST-014"}:
            supports.insert(0, ev("EV-THESIS-FACTOR", "interpreted"))
        builder.add(
            derivation_id,
            "spec/decisions/engineering_v1.1.0.json",
            locator,
            field,
            value,
            purpose="Materializar una condición explícita del contrato de ingeniería.",
            object_refs="CI-FAT-INFRA6-1.0.0",
            supports=supports,
            claim_ref="",
            parent="DL-HST-004",
            m_refs="M4|M6",
        )
    qa = builder.decisions["T03-QA-011"]["decision"]
    if ct["diagnostic_codes"] != qa["diagnostic_priority"]:
        raise ValueError("CT and QA diagnostic-code priorities diverge")
    diagnostic_aggregation = ct["diagnostic_aggregation"]
    if not (
        diagnostic_aggregation["form"]
        == "complete_ordered_set_of_independently_detected_diagnostic_code_classes"
        and diagnostic_aggregation["diagnostic_identity"]
        == "the diagnostic code string identifies a failure class, not an occurrence or failed-field record"
        and diagnostic_aggregation["same_code_multiple_fields"]
        == "represent the independently detected diagnostic class once even when multiple fields produce that same code"
        and "deduplicate by code"
        in diagnostic_aggregation["independent_failure_policy"]
    ):
        raise ValueError("diagnostic aggregation is not the approved complete code-only set")
    builder.add(
        "DL-DIAG-AGGREGATION-001",
        "spec/decisions/engineering_v1.1.0.json",
        "/diagnostics/aggregation",
        "diagnostic.aggregation",
        diagnostic_aggregation,
        purpose="Fijar una lista completa, ordenada y deduplicada por clase de código diagnóstico.",
        object_refs="CI-FAT-INFRA6-1.0.0|TESTS-18",
        supports=[dec("T03-CT-009"), dec("T03-QA-011")],
        parent="DL-FST-016",
        transformation_type="engineering_decision",
        transformation="La lista representa clases de fallo, no ocurrencias ni pares campo-código.",
        m_refs="M4|M5|M6",
    )


def add_rule_rows(builder: LedgerBuilder) -> None:
    builder.add(
        "DL-RUL-SAD-000",
        "spec/published/rule_sadness_2018a.json",
        "/source/emotion_column",
        "sadness_rule.source_emotion_column",
        "Sadness",
        purpose="Preservar la columna Emotion de la regla de tristeza.",
        object_refs="RULE-SADNESS-2018A",
        supports=[ev("EV-2018A-SADNESS")],
        claim_ref="CLM-SADNESS-001",
        transformation_type="metadata_transcription",
        transformation="Transcripción atómica de la etiqueta fuente.",
        origin="reconstructed_from_published_specification",
    )
    builder.add(
        "DL-RUL-SAD-001",
        "spec/published/rule_sadness_2018a.json",
        "/source/cause_column",
        "sadness_rule.source_cause_column",
        {"source_role": "separate_cause_column", "value": "Unwanted event (E) occurred"},
        purpose="Preservar Cause separado del antecedente IF publicado.",
        object_refs="RULE-SADNESS-2018A",
        supports=[ev("EV-2018A-SADNESS")],
        claim_ref="CLM-SADNESS-001",
        transformation_type="metadata_transcription",
        transformation="La columna Cause no se reescribe como antecedente publicado.",
        origin="reconstructed_from_published_specification",
    )
    for index, antecedent in enumerate(SADNESS_ANTECEDENTS):
        builder.add(
            f"DL-RUL-SAD-{index + 2:03d}",
            "spec/published/rule_sadness_2018a.json",
            f"/source/if_antecedents/{index}",
            f"sadness_rule.source_antecedent.{index}",
            antecedent,
            purpose="Preservar un antecedente y su etiqueta tal como aparecen en la tabla fuente.",
            object_refs="RULE-SADNESS-2018A",
            supports=[ev("EV-2018A-SADNESS")],
            claim_ref="CLM-SADNESS-001",
            transformation_type="metadata_transcription",
            transformation="Se conservan espacios, mayúsculas y etiquetas; no se normalizan valores lingüísticos.",
            origin="reconstructed_from_published_specification",
        )
    builder.add(
        "DL-RUL-SAD-009",
        "spec/published/rule_sadness_2018a.json",
        "/source/then",
        "sadness_rule.source_consequent",
        {"field": "Emotion E", "operator": "is", "value": "sadness"},
        purpose="Preservar el consecuente de la regla fuente.",
        object_refs="RULE-SADNESS-2018A",
        supports=[ev("EV-2018A-SADNESS")],
        claim_ref="CLM-SADNESS-001",
        transformation_type="metadata_transcription",
        transformation="Transcripción estructurada sin política ejecutable añadida.",
        origin="reconstructed_from_published_specification",
    )

    for index, antecedent in enumerate(ANGER_ANTECEDENTS):
        builder.add(
            f"DL-RUL-ANG-{index + 1:03d}",
            "spec/published/rule_anger_2018b.json",
            f"/source/consistent_row/if_antecedents/{index}",
            f"anger_rule.source_antecedent.{index}",
            antecedent,
            purpose="Preservar un antecedente de la fila consistente de ira.",
            object_refs="RULE-ANGER-2018B-CONSISTENT",
            supports=[ev("EV-2018B-RULES")],
            claim_ref="CLM-ANGER-001",
            transformation_type="metadata_transcription",
            transformation="Se conservan nombres y etiquetas de la publicación.",
            origin="reconstructed_from_published_specification",
        )
    builder.add(
        "DL-RUL-ANG-000",
        "spec/published/rule_anger_2018b.json",
        "/source/consistent_row/emotion_column",
        "anger_rule.source_emotion_column",
        "Anger",
        purpose="Preservar la columna Emotion de la fila consistente de ira.",
        object_refs="RULE-ANGER-2018B-CONSISTENT",
        supports=[ev("EV-2018B-RULES")],
        claim_ref="CLM-ANGER-001",
        transformation_type="metadata_transcription",
        transformation="La columna fuente se registra separada de antecedentes y consecuente.",
        origin="reconstructed_from_published_specification",
    )
    builder.add(
        "DL-RUL-ANG-007",
        "spec/published/rule_anger_2018b.json",
        "/source/consistent_row/then",
        "anger_rule.source_consequent",
        {"field": "Emotion (E)", "operator": "IS", "value": "Anger"},
        purpose="Preservar el consecuente de la fila consistente.",
        object_refs="RULE-ANGER-2018B-CONSISTENT",
        supports=[ev("EV-2018B-RULES")],
        claim_ref="CLM-ANGER-001",
        transformation_type="metadata_transcription",
        transformation="La minúscula canónica se decide en otra capa.",
        origin="reconstructed_from_published_specification",
    )
    builder.add(
        "DL-RUL-ANG-SOURCE-FRAGMENT-001",
        "spec/published/rule_anger_2018b.json",
        "/source/consistent_row/source_fragment_terminal",
        "anger_rule.source_fragment_terminal",
        "Coping potential (E) IS null.",
        purpose="Preservar literalmente el fragmento terminal con su punto fuente.",
        object_refs="RULE-ANGER-2018B-CONSISTENT",
        supports=[ev("EV-2018B-RULES")],
        claim_ref="CLM-ANGER-001",
        transformation_type="metadata_transcription",
        transformation="El valor lingüístico y la puntuación terminal permanecen distinguibles.",
        origin="reconstructed_from_published_specification",
    )
    builder.add(
        "DL-RUL-CONFLICT-001",
        "spec/published/rule_anger_2018b.json",
        "/source/conflicting_row",
        "source_conflict.complete_row",
        {
            "emotion_column": "Sadness",
            "if_antecedents": CONFLICT_ANTECEDENTS,
            "then": {"field": "Emotion (E)", "operator": "IS", "value": "Anger"},
        },
        purpose="Preservar el grupo legacy completo como instantánea excluida de migración.",
        object_refs="RULE-CONFLICT-2018B",
        supports=[ev("EV-2018B-RULES"), dec("T03-RS-005")],
        claim_ref="CLM-ANGER-001",
        claim_class="excluded_from_execution",
        transformation_type="preserve_and_exclude",
        transformation="La arista de decisión legacy no puede contaminar la capa publicada activa.",
        origin="reconstructed_from_published_specification",
        materialization_status="excluded",
    )
    builder.add(
        "DL-RUL-CONFLICT-PUBLISHED-001",
        "spec/published/rule_anger_2018b.json",
        "/source/conflicting_row",
        "source_conflict.complete_row",
        {
            "emotion_column": "Sadness",
            "if_antecedents": CONFLICT_ANTECEDENTS,
            "then": {"field": "Emotion (E)", "operator": "IS", "value": "Anger"},
        },
        purpose="Preservar completa la fila conflictiva sin corregir retrospectivamente la fuente.",
        object_refs="RULE-CONFLICT-2018B",
        supports=[ev("EV-2018B-RULES")],
        claim_ref="CLM-ANGER-001",
        transformation_type="metadata_transcription",
        transformation="La exclusión ejecutable se registra por separado en la capa de decisiones.",
        origin="reconstructed_from_published_specification",
    )

    adapters = [
        ("DL-LX-001", "Expectation", "expectedness", "field_name_adapter", "EV-2018B-VARIABLES"),
        ("DL-LX-002", "Goal Orientation", "goal_conduciveness", "field_name_adapter", "EV-2018B-VARIABLES"),
        ("DL-LX-003", "Pleasantness", "pleasure", "field_name_adapter", "EV-2018A-SADNESS"),
        ("DL-LX-004", "Goal-conduciveness", "goal_conduciveness", "field_name_adapter", "EV-2018B-RULES"),
        ("DL-LX-005", "Goal conduciveness", "goal_conduciveness", "field_name_adapter", "EV-2018A-SADNESS"),
        ("DL-LX-006", "Goals conduciveness", "goal_conduciveness", "field_name_adapter", "EV-2018A-VARIABLES"),
        ("DL-LX-007", "Consequence(E)", "event_context.consequence_target", "context_field_adapter", "EV-2018A-SADNESS"),
        ("DL-LX-008", "Cause", "event_context.cause_class", "context_field_adapter", "EV-2018A-SADNESS"),
        ("DL-LX-009", "Anger", "anger", "consequent_case_adapter", "EV-2018B-RULES"),
    ]
    for index, (derivation_id, source_term, canonical_term, kind, evidence_id) in enumerate(adapters):
        adapter_supports = [ev(evidence_id, "interpreted")]
        if derivation_id in {"DL-LX-001", "DL-LX-002"}:
            adapter_supports.append(dec("T01-AF-008"))
        adapter_supports.append(dec("T03-RS-005"))
        builder.add(
            derivation_id,
            "spec/decisions/engineering_v1.1.0.json",
            f"/lexical_adapters/{index}",
            f"lexical_adapter.{index}",
            {
                "canonical_term": canonical_term,
                "kind": kind,
                "source_term": source_term,
                "value_mapping": False,
            },
            purpose="Registrar un adaptador explícito sin alterar la capa publicada.",
            object_refs="LEXICAL-ADAPTERS-1.1.0",
            supports=adapter_supports,
            claim_ref="CLM-TERMS-001" if derivation_id != "DL-LX-005" else "",
            parent="DL-RUL-ANG-007" if derivation_id == "DL-LX-009" else "DL-HST-003",
        )
    rs = builder.decisions["T03-RS-005"]["decision"]
    lexeme_contract = rs["antecedent_lexeme_adapter_contract"]
    exact_lexeme_maps = {
        "SRC-2018A-COGNITION-APPRAISAL": {
            "Coping potential (E)": "coping_potential",
            "Desirability(E)": "desirability",
            "Expectedness(E)": "expectedness",
            "Goal conduciveness (E)": "goal_conduciveness",
            "Novelty (E)": "novelty",
            "Pleasantness(E)": "pleasure",
        },
        "SRC-2018B-FLEXIBLE-SCHEME": {
            "Coping potential (E)": "coping_potential",
            "Desirability (E)": "desirability",
            "Expectation (E)": "expectedness",
            "Goal-conduciveness (E)": "goal_conduciveness",
            "Novelty (E)": "novelty",
            "Pleasure (E)": "pleasure",
        },
    }
    if lexeme_contract["source_specific_maps"] != exact_lexeme_maps:
        raise ValueError("T03-RS-005 six-lexeme source maps are not exact")
    if (
        lexeme_contract["exact_match_required"] is not True
        or lexeme_contract["contract_layer"] != "decisions"
        or lexeme_contract["published_layer_mutation"] is not False
        or lexeme_contract["failure_policy"]
        != "fail_closed_on_unknown_source_missing_mapping_or_non_exact_lexeme"
    ):
        raise ValueError("T03-RS-005 lexeme-map failure policy is not closed")
    lexeme_evidence = {
        "SRC-2018A-COGNITION-APPRAISAL": "EV-2018A-SADNESS",
        "SRC-2018B-FLEXIBLE-SCHEME": "EV-2018B-RULES",
    }
    for suffix, source_id in (
        ("2018A", "SRC-2018A-COGNITION-APPRAISAL"),
        ("2018B", "SRC-2018B-FLEXIBLE-SCHEME"),
    ):
        builder.add(
            f"DL-LX-SOURCE-MAP-{suffix}",
            "spec/decisions/engineering_v1.1.0.json",
            f"/antecedent_lexeme_adapter/source_specific_maps/{source_id}",
            f"antecedent_lexeme_adapter.source_specific_maps.{source_id}",
            exact_lexeme_maps[source_id],
            purpose="Resolver de forma exhaustiva seis lexemas antecedentes por fuente exacta.",
            object_refs="LEXICAL-ADAPTERS-1.1.0|RULE-ADAPTERS-1.1.0",
            supports=[ev(lexeme_evidence[source_id], "interpreted"), dec("T03-RS-005")],
            parent="DL-HST-003",
            claim_ref="CLM-TERMS-001",
            transformation_type="lexical_adapter",
            transformation="El mapa exige source_id y lexema exactos; no permite sustitución entre fuentes.",
            m_refs="M2|M3|M6",
        )
    lexeme_policy = {
        key: deepcopy(value)
        for key, value in lexeme_contract.items()
        if key != "source_specific_maps"
    }
    builder.add(
        "DL-LX-SOURCE-MAP-POLICY-001",
        "spec/decisions/engineering_v1.1.0.json",
        "/antecedent_lexeme_adapter/policy",
        "antecedent_lexeme_adapter.policy",
        lexeme_policy,
        purpose="Materializar la política fail-closed que gobierna ambos mapas exhaustivos.",
        object_refs="LEXICAL-ADAPTERS-1.1.0|RULE-ADAPTERS-1.1.0",
        supports=[dec("T03-RS-005")],
        parent="DL-LX-SOURCE-MAP-2018A",
        claim_ref="",
        claim_class="generated_for_doctoral_instance",
        transformation_type="engineering_decision",
        m_refs="M2|M3|M6",
    )
    boundary_contract = rs["boundary_terminology_adapter_contract"]
    boundary_evidence = {
        "SRC-2018A-COGNITION-APPRAISAL": "EV-2018A-GA-EF",
        "SRC-2018B-FLEXIBLE-SCHEME": "EV-2018B-GA-EF",
    }
    for suffix, source_id in (
        ("2018A", "SRC-2018A-COGNITION-APPRAISAL"),
        ("2018B", "SRC-2018B-FLEXIBLE-SCHEME"),
    ):
        builder.add(
            f"DL-HST-BND-SOURCE-MAP-{suffix}",
            "spec/decisions/engineering_v1.1.0.json",
            f"/published_boundary_adapter/source_specific_adapters/{source_id}",
            f"published_boundary_adapter.source_specific_adapters.{source_id}",
            boundary_contract["source_specific_adapters"][source_id],
            purpose="Vincular los dos términos publicados de frontera a su source_id exacto.",
            object_refs="BOUNDARY-TERMINOLOGY-ADAPTER|IF-GA-EF-1.0.0",
            supports=[ev(boundary_evidence[source_id], "interpreted"), dec("T03-RS-005")],
            parent="DL-HST-011",
            claim_ref="",
            claim_class="generated_for_doctoral_instance",
            transformation_type="lexical_adapter",
            transformation="El mapa preserva los literales publicados y falla cerrado ante otra forma.",
            m_refs="M2|M3|M6",
        )
    boundary_policy = {
        key: deepcopy(value)
        for key, value in boundary_contract.items()
        if key not in {"canonical_doctoral_terms", "source_specific_adapters"}
    }
    builder.add(
        "DL-HST-BND-SOURCE-MAP-POLICY-001",
        "spec/decisions/engineering_v1.1.0.json",
        "/published_boundary_adapter/policy",
        "published_boundary_adapter.policy",
        boundary_policy,
        purpose="Materializar la política source-specific de normalización de la frontera GA/EF.",
        object_refs="BOUNDARY-TERMINOLOGY-ADAPTER|IF-GA-EF-1.0.0",
        supports=[dec("T03-RS-005")],
        parent="DL-HST-012",
        claim_ref="",
        claim_class="generated_for_doctoral_instance",
        transformation_type="engineering_decision",
        m_refs="M2|M3|M6",
    )
    builder.add(
        "DL-CTX-001",
        "spec/decisions/engineering_v1.1.0.json",
        "/rule_adapters/sadness/cause_guard",
        "sadness_rule.cause_guard",
        {
            "executable_role": "doctoral_applicability_guard",
            "source_role": "separate_cause_column",
            "source_value": "Unwanted event (E) occurred",
            "target": "event_context.cause_class",
            "target_value": "unwanted_event_occurred",
        },
        purpose="Convertir Cause en una guardia doctoral sin atribuirla al IF publicado.",
        object_refs="RULE-SADNESS-2018A|RULE-ADAPTERS-1.1.0",
        supports=[
            ev("EV-2018A-SADNESS", "interpreted"),
            dec("T03-RS-005"),
        ],
        parent="DL-RUL-SAD-001",
        claim_ref="CLM-SADNESS-001",
        claim_class="doctoral_inference",
    )
    builder.add(
        "DL-CTX-002",
        "spec/decisions/engineering_v1.1.0.json",
        "/rule_adapters/sadness/consequence_binding",
        "sadness_rule.consequence_binding",
        {
            "executable_role": "required_context_antecedent",
            "source_literal": "Consequence (E)",
            "source_field": "Consequence (E)",
            "target": "event_context.consequence_target",
            "whitespace_normalization": "approved_optional_space_before_parenthesized_event_marker",
        },
        purpose="Vincular Consequence(E) al contexto manteniéndolo como antecedente requerido.",
        object_refs="RULE-SADNESS-2018A|RULE-ADAPTERS-1.1.0",
        supports=[
            ev("EV-2018A-SADNESS", "interpreted"),
            dec("T03-RS-005"),
        ],
        parent="DL-RUL-SAD-002",
        claim_ref="CLM-SADNESS-001",
        claim_class="doctoral_inference",
    )
    builder.add(
        "DL-CTX-003",
        "spec/decisions/engineering_v1.1.0.json",
        "/rule_adapters/value_label_mapping_policy",
        "rule_adapter.value_label_mapping_policy",
        {"coping_positive_equivalence": None, "implicit_value_label_mapping": False},
        purpose="Prohibir equivalencias implícitas entre etiquetas lingüísticas.",
        object_refs="RULE-ADAPTERS-1.1.0",
        supports=[dec("T03-RS-005")],
        parent="DL-RUL-SAD-004",
        claim_ref="",
        claim_class="generated_for_doctoral_instance",
    )
    builder.add(
        "DL-RUL-SAD-010",
        "spec/decisions/engineering_v1.1.0.json",
        "/rules/sadness/execution_policy",
        "sadness_rule.execution_policy",
        {
            "execution_profile": "symbolic_regression_only",
            "missing_or_different_antecedent": "no_match",
            "numeric_pipeline_eligible": False,
        },
        purpose="Mantener la política ejecutable fuera de la transcripción publicada.",
        object_refs="RULE-SADNESS-2018A",
        supports=[dec("T03-RS-005")],
        parent="DL-CTX-002",
        claim_ref="",
        claim_class="generated_for_doctoral_instance",
    )
    builder.add(
        "DL-RUL-ANG-008",
        "spec/decisions/engineering_v1.1.0.json",
        "/rules/anger/execution_policy",
        "anger_rule.execution_policy",
        {
            "coping_label_source": "doctoral_crisp_partition",
            "evaluation": ["before", "after"],
            "multiple_match": "reject_with_ambiguous_published_subset_diagnostic",
            "profile": "S14_bounded_end_to_end_continuity",
            "protected_labels_source": "synthetic_host_fixture",
            "zero_match": "unclassified_by_published_subset",
        },
        purpose="Mantener la política ejecutable de ira en la capa de decisiones.",
        object_refs="RULE-ANGER-2018B-CONSISTENT",
        supports=[dec("T03-RS-005")],
        parent="DL-RUL-ANG-007",
        claim_ref="",
        claim_class="generated_for_doctoral_instance",
    )
    builder.add(
        "DL-RUL-CONFLICT-002",
        "spec/decisions/engineering_v1.1.0.json",
        "/rules/exclusions/2018b_conflicting_row",
        "source_conflict.execution_policy",
        {
            "execution_status": "excluded_from_execution",
            "reason": "emotion_column_sadness_but_consequent_anger",
            "source_row_ref": "spec/published/rule_anger_2018b.json#/source/conflicting_row",
        },
        purpose="Excluir la fila conflictiva sin eliminar su transcripción.",
        object_refs="RULE-CONFLICT-2018B",
        supports=[dec("T03-RS-005")],
        parent="DL-RUL-CONFLICT-PUBLISHED-001",
        claim_ref="",
        claim_class="generated_for_doctoral_instance",
    )
    builder.add(
        "DL-RUL-SELECT-001",
        "spec/thesis/f6_specification_rc01.json",
        "/rules/selected_subset",
        "rules.selected_subset",
        {
            "anger": "RULE-ANGER-2018B-CONSISTENT",
            "conflicting_2018b_row": "excluded",
            "sadness": "RULE-SADNESS-2018A-symbolic-only",
        },
        purpose="Declarar el subconjunto doctoral sin contaminar la capa publicada.",
        object_refs="PA-INFRA6-1.0.0|MOD-FAT-COP-1.0.0",
        supports=[dec("T03-RS-005")],
        parent="DL-RUL-ANG-008",
    )


def read_json_object(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON object and reject duplicate member names."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON member {key!r} in {path}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read canonical JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"canonical JSON input must be an object: {path}")
    return value


def resolution_documents(builder: LedgerBuilder) -> dict[str, dict[str, Any]]:
    """Compose the binding registry and resolved config from frozen source layers."""

    inputs = {
        path: read_json_object(builder.root / path)
        for path in sorted(SPEC_LAYER_PATHS)
    }
    thesis = inputs["spec/thesis/f6_specification_rc01.json"]
    engineering = inputs["spec/decisions/engineering_v1.1.0.json"]
    host_published = inputs["spec/published/host_appraisal_2018a.json"]
    boundary_published = inputs["spec/published/ga_ef_boundary_2018ab.json"]
    sadness_published = inputs["spec/published/rule_sadness_2018a.json"]
    anger_published = inputs["spec/published/rule_anger_2018b.json"]

    rs = builder.decisions["T03-RS-005"]["decision"]
    rp = builder.decisions["T03-RP-012"]["decision"]
    mp = builder.decisions["T03-MP-013"]["decision"]
    formula_binding = rs["formula_binding"]
    required_bindings = mp["required_executable_binding_map"]
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
        or not isinstance(anger_published.get("source", {}).get("consistent_row"), dict)
    ):
        raise ValueError("published predecessor layers do not satisfy the frozen resolution boundary")
    if (
        thesis.get("host", {}).get("appraisal_vector", {}).get("order") != VECTOR_FIELDS
        or thesis.get("influence", {}).get("formula") != formula_binding["expression"]
        or thesis.get("influence", {}).get("parameters", {}).get("lambda")
        != formula_binding["parameter_values"]["lambda"]
        or thesis.get("influence", {}).get("protected")
        != formula_binding["protected_dimensions"]
        or formula_binding["executable_binding_map"] != required_bindings
        or mp["binding_artifacts"]["binding_map_values"] != required_bindings
        or engineering.get("published_boundary_adapter", {}).get("canonical")
        != rs["boundary_terminology_adapter_contract"]["canonical_doctoral_terms"]
        or engineering.get("published_boundary_adapter", {}).get(
            "source_specific_adapters"
        )
        != rs["boundary_terminology_adapter_contract"]["source_specific_adapters"]
        or engineering.get("published_boundary_adapter", {}).get("policy")
        != {
            key: deepcopy(value)
            for key, value in rs["boundary_terminology_adapter_contract"].items()
            if key not in {"canonical_doctoral_terms", "source_specific_adapters"}
        }
    ):
        raise ValueError("authored predecessor layers diverge from the approved resolution contract")

    binding_registry = {
        "$schema": "../../schemas/formula_bindings.schema.json",
        "schema_version": "1.0.0",
        "binding_id": formula_binding["binding_id"],
        "formula_id": formula_binding["formula_id"],
        "provenance_layer": formula_binding["provenance_layer"],
        "not_attributed_to_published_rules": formula_binding[
            "not_attributed_to_published_rules"
        ],
        "expression": formula_binding["expression"],
        "input_bindings": deepcopy(formula_binding["input_bindings"]),
        "binding_map": deepcopy(required_bindings),
        "formula_to_binding_key_crosswalk": deepcopy(
            formula_binding["formula_to_binding_key_crosswalk"]
        ),
        "binding_roles": deepcopy(formula_binding["binding_roles"]),
        "parameter_values": deepcopy(formula_binding["parameter_values"]),
        "authorized_output": formula_binding["authorized_output"],
        "protected_dimensions": deepcopy(formula_binding["protected_dimensions"]),
        "published_rule_access": deepcopy(formula_binding["published_rule_access"]),
        "resolution_policy": formula_binding["resolution_policy"],
        "collision_policy": mp["binding_artifacts"]["consistency_rule"],
        "source_layers": {
            "doctoral_specification": "spec/thesis/f6_specification_rc01.json",
            "engineering_decisions": "spec/decisions/engineering_v1.1.0.json",
        },
        "decision_refs": ["T03-RS-005", "T03-RP-012", "T03-MP-013"],
    }
    if (
        binding_registry["binding_roles"]["input_keys"]
        != ["coping_potential", "lambda", "z"]
        or binding_registry["binding_roles"]["output_key"] != "result"
        or binding_registry["binding_roles"]["result_is_input"] is not False
        or "result" in binding_registry["input_bindings"]
    ):
        raise ValueError("binding registry does not preserve three inputs and one distinct output")

    package = builder.provenance["package_identity"]
    host = deepcopy(thesis["host"])
    host["integration"] = deepcopy(engineering["published_boundary_adapter"]["canonical"])
    influence = deepcopy(thesis["influence"])
    influence["binding_map"] = deepcopy(required_bindings)
    resolved_config = {
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
                "published": [
                    "spec/published/host_appraisal_2018a.json",
                    "spec/published/ga_ef_boundary_2018ab.json",
                    "spec/published/rule_sadness_2018a.json",
                    "spec/published/rule_anger_2018b.json",
                ],
                "decisions": "spec/decisions/engineering_v1.1.0.json",
                "thesis": "spec/thesis/f6_specification_rc01.json",
                "bindings": "spec/bindings/formula_bindings.json",
            },
            "authorized_precedence": deepcopy(
                rs["layer_separation"]["authorized_precedence"]
            ),
            "conflict_policy": rs["layer_separation"]["authorized_precedence"][-1],
        },
        "host": host,
        "perspective": deepcopy(thesis["perspective"]),
        "factor": deepcopy(thesis["factor"]),
        "influence": influence,
        "coping_partition": deepcopy(thesis["coping_partition"]),
        "rules": {
            "selected_subset": deepcopy(thesis["rules"]["selected_subset"]),
            "published_sources": {
                "sadness": "spec/published/rule_sadness_2018a.json#/source",
                "anger": "spec/published/rule_anger_2018b.json#/source/consistent_row",
            },
            "execution": deepcopy(engineering["rules"]),
            "adapters": {
                "antecedent_lexemes": deepcopy(engineering["antecedent_lexeme_adapter"]),
                "boundary": deepcopy(engineering["published_boundary_adapter"]),
                "rule_context": deepcopy(engineering["rule_adapters"]),
            },
        },
        "evaluation": deepcopy(thesis["evaluation"]),
        "contract": {
            "host": deepcopy(engineering["host"]),
            "factor_state": deepcopy(engineering["factor_state"]),
            "validation_order": deepcopy(engineering["validation_order"]),
            "failure_policy": deepcopy(engineering["failure_policy"]),
            "temporal_policy": deepcopy(engineering["temporal_policy"]),
            "diagnostics": deepcopy(engineering["diagnostics"]),
        },
        "runtime": {
            "environment": deepcopy(engineering["runtime"]),
            "canonical_json": deepcopy(engineering["canonical_json"]),
            "numeric": deepcopy(engineering["numeric"]),
            "time": deepcopy(engineering["time"]),
            "trace_id": deepcopy(engineering["trace_id"]),
        },
    }
    if (
        rp["json_profile"]["profile_id"] != "IFM6-JSON-v1"
        or resolved_config["runtime"]["canonical_json"]
        != {
            "allow_nan": False,
            "encoding": "UTF-8",
            "line_endings": "LF",
            "normalize_decimals": True,
            "separators": [",", ":"],
            "sort_keys": True,
        }
    ):
        raise ValueError("resolved canonical JSON profile diverges from T03-RP-012")
    return {
        "spec/bindings/formula_bindings.json": binding_registry,
        "config/resolved_instance.json": resolved_config,
    }


JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
DECIMAL_STRING_PATTERN = r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$"
RFC3339_UTC_PATTERN = (
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]+)?Z$"
)
SHA256_PATTERN = r"^[0-9a-f]{64}$"
SCENARIO_ID_PATTERN = r"^S(?:0[0-9]|1[0-5])$"
NON_REJECTED_SCENARIO_ID_PATTERN = r"^S(?:0[0-9]|1[0-4])$"
DIAGNOSTIC_CODES = [
    "HOST_BASELINE_MISSING_FIELD",
    "HOST_BASELINE_TYPE_INVALID",
    "HOST_BASELINE_OUT_OF_RANGE",
    "FACTOR_STATE_MISSING",
    "FACTOR_STATE_TYPE_INVALID",
    "FACTOR_LEVEL_MISSING",
    "FACTOR_LEVEL_TYPE_INVALID",
    "FACTOR_LEVEL_OUT_OF_RANGE",
    "FACTOR_CONFIDENCE_MISSING",
    "FACTOR_CONFIDENCE_TYPE_INVALID",
    "FACTOR_CONFIDENCE_OUT_OF_RANGE",
    "FACTOR_CONFIDENCE_BELOW_MIN",
    "FACTOR_OBSERVED_AT_MISSING",
    "FACTOR_OBSERVED_AT_INVALID",
    "FACTOR_STATE_STALE",
    "FACTOR_STATE_FROM_FUTURE",
    "FACTOR_SOURCE_ID_MISSING",
    "FACTOR_SOURCE_ID_TYPE_INVALID",
    "FACTOR_SCHEMA_VERSION_MISSING",
    "FACTOR_SCHEMA_VERSION_TYPE_INVALID",
    "FACTOR_SCHEMA_VERSION_UNSUPPORTED",
    "PUBLISHED_SUBSET_AMBIGUOUS",
]


def _closed_schema(
    properties: Mapping[str, Any],
    *,
    required: Sequence[str] | None = None,
    **keywords: Any,
) -> dict[str, Any]:
    """Return a closed JSON-object schema with an explicit required set."""
    schema: dict[str, Any] = {
        "type": "object",
        "required": list(required if required is not None else properties),
        "properties": deepcopy(dict(properties)),
        "additionalProperties": False,
    }
    schema.update(deepcopy(keywords))
    return schema


def _exact_instance_schema(value: Any) -> dict[str, Any]:
    """Describe an immutable seed without relying on a whole-document const."""
    if isinstance(value, dict):
        return _closed_schema(
            {key: _exact_instance_schema(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return {"type": "array", "const": deepcopy(value)}
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean", "const": value}
    if isinstance(value, int):
        return {"type": "integer", "const": value}
    if isinstance(value, str):
        return {"type": "string", "const": value}
    raise TypeError(f"unsupported exact-schema value {type(value).__name__}")


def _schema_document(
    schema_id: str,
    title: str,
    description: str,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    document = {
        "$schema": JSON_SCHEMA_DRAFT,
        "$id": schema_id,
        "title": title,
        "description": description,
    }
    document.update(deepcopy(dict(contract)))
    return document


def _decimal_schema(*, domain: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "string",
        "pattern": DECIMAL_STRING_PATTERN,
        "x-ifm6-profile": "IFM6-DEC-v1",
    }
    if domain is not None:
        schema["x-ifm6-domain"] = domain
    return schema


def _diagnostics_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": deepcopy(DIAGNOSTIC_CODES)},
        "x-ifm6-priority-order": deepcopy(DIAGNOSTIC_CODES),
    }


def _appraisal_vector_schema(*, enforce_domain: bool) -> dict[str, Any]:
    decimal = _decimal_schema(domain="[0,1]" if enforce_domain else None)
    return _closed_schema({field: deepcopy(decimal) for field in VECTOR_FIELDS})


def _classification_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            _closed_schema({"attempted": {"const": False, "type": "boolean"}}),
            _closed_schema(
                {
                    "attempted": {"const": True, "type": "boolean"},
                    "before": {"type": "string", "minLength": 1},
                    "after": {"type": "string", "minLength": 1},
                }
            ),
        ]
    }


def _route_schema(path_pattern: str) -> dict[str, Any]:
    return {
        "oneOf": [
            _closed_schema({"exists": {"const": False, "type": "boolean"}}),
            _closed_schema(
                {
                    "exists": {"const": True, "type": "boolean"},
                    "path": {"type": "string", "pattern": path_pattern},
                }
            ),
        ]
    }


def _modulation_schema() -> dict[str, Any]:
    return _closed_schema(
        {
            "attempted": {"type": "boolean"},
            "formula_evaluated": {"type": "boolean"},
            "coping_potential_changed": {"type": "boolean"},
        }
    )


def _provenance_schema(provenance: Mapping[str, Any]) -> dict[str, Any]:
    broad_types = {
        key: {"type": "array" if isinstance(value, list) else "object"}
        for key, value in provenance.items()
        if key not in {"$schema", "schema_version", "schema_resolution_status"}
    }
    broad_types.update(
        {
            "$schema": {"const": "schemas/provenance.schema.json", "type": "string"},
            "schema_version": {"const": "0.2.0", "type": "string"},
            "schema_resolution_status": {"type": "string", "minLength": 1},
            "document": _closed_schema(
                {
                    "created_at_utc": {"type": "string", "pattern": RFC3339_UTC_PATTERN},
                    "id": {"const": "IFATIGUE-INFRA6-M6-PROVENANCE", "type": "string"},
                    "language": {"const": "es", "type": "string"},
                    "origin_class": {
                        "const": "generated_for_doctoral_instance",
                        "type": "string",
                    },
                    "self_hash": {"type": "null"},
                    "self_hash_policy": {"type": "string", "minLength": 1},
                    "status": {"const": "candidate_under_construction", "type": "string"},
                    "title": {"type": "string", "minLength": 1},
                    "updated_at_utc": {"type": "string", "pattern": RFC3339_UTC_PATTERN},
                }
            ),
            "package_identity": _closed_schema(
                {
                    "artifact_version_policy": {"type": "object"},
                    "conceptual_id": {"const": "IFATIGUE-INFRA6-M6", "type": "string"},
                    "construction_started_at_utc": {
                        "type": "string",
                        "pattern": RFC3339_UTC_PATTERN,
                    },
                    "materialization_status": {"type": "string", "minLength": 1},
                    "package_version": {"const": "1.1.0", "type": "string"},
                    "planned_archive": {"type": "string", "minLength": 1},
                    "release_stage": {"const": "candidate", "type": "string"},
                    "root_directory": {
                        "const": "IFATIGUE-INFRA6-M6-v1.1.0/",
                        "type": "string",
                    },
                    "verification_status": {"type": "string", "minLength": 1},
                }
            ),
            "scientific_claims": {
                "type": "array",
                "minItems": 1,
                "items": _closed_schema(
                    {
                        "claim_id": {
                            "type": "string",
                            "pattern": r"^(?:CLM|REQ|LIM)-[A-Z0-9-]+$",
                        },
                        "claim_provenance_class": {"type": "string", "minLength": 1},
                        "statement": {"type": "string", "minLength": 1},
                        "source_refs": {"type": "array", "items": {"type": "object"}},
                        "transformation": {"type": "string", "minLength": 1},
                        "failure_condition": {"type": "string"},
                        "source_lexeme": {"type": "string"},
                        "value": {},
                    },
                    required=[
                        "claim_id",
                        "claim_provenance_class",
                        "statement",
                        "source_refs",
                        "transformation",
                    ],
                ),
            },
            "decisions": {
                "type": "array",
                "minItems": 1,
                "items": _closed_schema(
                    {
                        "id": {
                            "type": "string",
                            "pattern": r"^T(?:0[0-9]|1[0-7])-[A-Z0-9-]+$",
                        },
                        "subject": {"type": "string", "minLength": 1},
                        "status": {"type": "string", "minLength": 1},
                        "approved_at": {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
                        "claim_provenance_class": {"type": "string", "minLength": 1},
                        "decision": {},
                        "interpretation": {"type": "string"},
                        "source_refs": {"type": "array", "items": {"type": "object"}},
                        "approval_basis": {"type": "string"},
                        "approval_record": {"type": "object"},
                        "condition_or_route": {"type": "string"},
                        "semantic_amendment": {"type": "object"},
                    },
                    required=[
                        "id",
                        "subject",
                        "status",
                        "approved_at",
                        "claim_provenance_class",
                        "decision",
                    ],
                ),
            },
            "planned_tree": {
                "type": "array",
                "minItems": 1,
                "items": _closed_schema(
                    {
                        "path": {
                            "type": "string",
                            "pattern": r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$",
                        },
                        "function": {"type": "string", "minLength": 1},
                        "origin_class": {"type": "string", "minLength": 1},
                        "status": {"type": "string", "minLength": 1},
                        "generated_by": {"type": "string", "minLength": 1},
                    },
                    required=["path", "function", "origin_class", "status"],
                ),
            },
        }
    )
    return _schema_document(
        "urn:acme-firm:schema:provenance:0.2.0",
        "IFATIGUE-INFRA6-M6 provenance contract",
        (
            "Contrato estructural del registro canónico. Las unicidades, referencias, "
            "estados de materialización y fronteras de evidencia se verifican además "
            "mediante scripts/validate_derivation_ledger.py."
        ),
        _closed_schema(broad_types, required=list(provenance)),
    )


def _scenario_schema(builder: LedgerBuilder) -> dict[str, Any]:
    bl = builder.decisions["T03-BL-006"]["decision"]
    event = deepcopy(bl["stable_conformance_event"])
    numeric_common = {
        "scenario_id": {"type": "string"},
        "fixture_class": {"const": bl["fixture_class"], "type": "string"},
        "empirical_support": {"const": bl["empirical_support"], "type": "string"},
        "evaluation_time": {"const": bl["evaluation_time"], "type": "string"},
        "event": _exact_instance_schema(event),
        "baseline": {"$ref": "#/$defs/input_appraisal_vector"},
        "factor_state": {
            "oneOf": [{"$ref": "#/$defs/factor_state"}, {"type": "null"}]
        },
    }
    ordinary = deepcopy(numeric_common)
    ordinary["scenario_id"] = {
        "type": "string",
        "pattern": r"^S(?:0[0-9]|1[0-3]|15)$",
    }
    s14 = deepcopy(numeric_common)
    s14.update(
        {
            "scenario_id": {"const": "S14", "type": "string"},
            "host_symbolic_payload": _exact_instance_schema(
                {
                    "desirability": "undesirable",
                    "expectedness": "unexpected",
                    "goal_conduciveness": "negative",
                    "novelty": "not_novelty",
                    "pleasure": "not_pleasant",
                    "source": bl["s14_symbolic_context"],
                }
            ),
        }
    )
    symbolic = _closed_schema(
        {
            "$schema": {
                "const": "../../schemas/scenario.schema.json",
                "type": "string",
            },
            "schema_version": {"const": "1.0.0", "type": "string"},
            "fixture_id": {
                "const": "sadness_2018a_symbolic",
                "type": "string",
            },
            "fixture_class": {
                "const": "synthetic_symbolic_regression_fixture",
                "type": "string",
            },
            "numeric_pipeline_input": {"const": False, "type": "boolean"},
            "event_context": _closed_schema(
                {
                    "cause_class": {
                        "const": "unwanted_event_occurred",
                        "type": "string",
                    },
                    "consequence_target": {"const": "myself", "type": "string"},
                }
            ),
            "published_symbolic_payload": _closed_schema(
                {
                    "Consequence (E)": {"type": "string", "minLength": 1},
                    "Coping potential (E)": {"type": "string", "minLength": 1},
                    "Desirability(E)": {"type": "string", "minLength": 1},
                    "Expectedness(E)": {"type": "string", "minLength": 1},
                    "Goal conduciveness (E)": {"type": "string", "minLength": 1},
                    "Novelty (E)": {"type": "string", "minLength": 1},
                    "Pleasantness(E)": {"type": "string", "minLength": 1},
                }
            ),
            "provenance_refs": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "source_rule_ref": {"const": "RULE-SADNESS-2018A", "type": "string"},
        }
    )
    factor_state = _closed_schema(
        {
            "level": _decimal_schema(),
            "confidence": _decimal_schema(),
            "observed_at": {"type": "string", "pattern": RFC3339_UTC_PATTERN},
            "source_id": {"type": "string", "pattern": r".*\S.*"},
            "state_schema_version": {"const": "1.0.0", "type": "string"},
        }
    )
    return _schema_document(
        "urn:acme-firm:schema:scenario:1.0.0",
        "IFATIGUE-INFRA6-M6 scenario contract",
        "Contrato cerrado para S00-S15 y para el fixture simbólico aislado de tristeza.",
        {
            "$defs": {
                "factor_state": factor_state,
                "input_appraisal_vector": _appraisal_vector_schema(
                    enforce_domain=False
                ),
            },
            "oneOf": [
                _closed_schema(ordinary),
                _closed_schema(s14),
                symbolic,
            ],
        },
    )


def _oracle_expected_schema(*, rejected: bool) -> dict[str, Any]:
    if rejected:
        return _closed_schema(
            {
                "disposition": {"const": "rejected", "type": "string"},
                "diagnostics": {
                    "const": ["HOST_BASELINE_OUT_OF_RANGE"],
                    "type": "array",
                },
                "output_contract": {
                    "const": {"exists": False},
                    "type": "object",
                },
                "factor_validation_performed": {
                    "const": False,
                    "type": "boolean",
                },
                "modulation": {
                    "const": {
                        "attempted": False,
                        "formula_evaluated": False,
                        "coping_potential_changed": False,
                    },
                    "type": "object",
                },
                "classification": {
                    "const": {"attempted": False},
                    "type": "object",
                },
                "modulation_trace": {
                    "const": {"exists": False},
                    "type": "object",
                },
                "rejection_record": {
                    "const": {
                        "exists": True,
                        "path": "traces/reference_run/rejections/S15.rejection.json",
                    },
                    "type": "object",
                },
            }
        )
    return _closed_schema(
        {
            "disposition": {
                "type": "string",
                "enum": ["applied_no_change", "modulated", "abstained"],
            },
            "diagnostics": _diagnostics_schema(),
            "output_contract": _closed_schema(
                {
                    "exists": {"const": True, "type": "boolean"},
                    "appraisal_vector": {"$ref": "#/$defs/appraisal_vector"},
                    "protected_dimensions": {
                        "const": "equal_to_scenario_baseline",
                        "type": "string",
                    },
                }
            ),
            "factor_validation_performed": {"type": "boolean"},
            "modulation": _modulation_schema(),
            "classification": _classification_schema(),
            "modulation_trace": _closed_schema(
                {
                    "exists": {"const": True, "type": "boolean"},
                    "path": {
                        "type": "string",
                        "pattern": r"^traces/reference_run/S(?:0[0-9]|1[0-4])\.trace\.json$",
                    },
                }
            ),
            "rejection_record": {
                "const": {"exists": False},
                "type": "object",
            },
        }
    )


def _oracle_schema() -> dict[str, Any]:
    formula_calculation_basis = _closed_schema(
        {
            "decimal_profile": {"const": "IFM6-DEC-v1", "type": "string"},
            "formula": {"type": "string", "minLength": 1},
            "lambda": _decimal_schema(domain="[0,1]"),
            "source_of_truth": {"type": "string", "minLength": 1},
        }
    )
    rejection_calculation_basis = _closed_schema(
        {
            "host_validation_precedes_factor_validation": {
                "const": True,
                "type": "boolean",
            },
            "source_of_truth": {"type": "string", "minLength": 1},
        }
    )
    numeric_common = {
        "$schema": {"const": "../schemas/oracle.schema.json", "type": "string"},
        "schema_version": {"const": "1.0.0", "type": "string"},
        "oracle_id": {
            "type": "string",
            "pattern": r"^S(?:0[0-9]|1[0-5])\.expected$",
        },
        "scenario_id": {"type": "string", "pattern": SCENARIO_ID_PATTERN},
        "scenario_ref": {
            "type": "string",
            "pattern": r"^scenarios/S(?:0[0-9]|1[0-5])\.json$",
        },
        "oracle_class": {"const": "synthetic_conformance_oracle", "type": "string"},
        "empirical_support": {"const": "none", "type": "string"},
        "frozen_before_implementation": {"const": True, "type": "boolean"},
        "provenance_refs": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        },
        "calculation_basis": {},
        "expected": {},
    }
    numeric_non_rejected = deepcopy(numeric_common)
    numeric_non_rejected.update(
        {
            "oracle_id": {
                "type": "string",
                "pattern": r"^S(?:0[0-9]|1[0-4])\.expected$",
            },
            "scenario_id": {
                "type": "string",
                "pattern": NON_REJECTED_SCENARIO_ID_PATTERN,
            },
            "scenario_ref": {
                "type": "string",
                "pattern": r"^scenarios/S(?:0[0-9]|1[0-4])\.json$",
            },
            "calculation_basis": formula_calculation_basis,
            "expected": {"$ref": "#/$defs/non_rejected_expected"},
        }
    )
    numeric_rejected = deepcopy(numeric_common)
    numeric_rejected.update(
        {
            "oracle_id": {"const": "S15.expected", "type": "string"},
            "scenario_id": {"const": "S15", "type": "string"},
            "scenario_ref": {"const": "scenarios/S15.json", "type": "string"},
            "calculation_basis": rejection_calculation_basis,
            "expected": {"$ref": "#/$defs/rejected_expected"},
        }
    )
    symbolic = _closed_schema(
        {
            "$schema": {"const": "../../schemas/oracle.schema.json", "type": "string"},
            "schema_version": {"const": "1.0.0", "type": "string"},
            "oracle_id": {
                "const": "sadness_2018a_symbolic.expected",
                "type": "string",
            },
            "fixture_ref": {
                "const": "tests/fixtures/sadness_2018a_symbolic.json",
                "type": "string",
            },
            "source_rule_ref": {"const": "RULE-SADNESS-2018A", "type": "string"},
            "oracle_class": {
                "const": "synthetic_symbolic_regression_oracle",
                "type": "string",
            },
            "frozen_before_implementation": {"const": True, "type": "boolean"},
            "provenance_refs": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "calculation_basis": _closed_schema(
                {
                    "execution_profile": {
                        "const": "isolated_symbolic_regression",
                        "type": "string",
                    },
                    "published_rule_ref": {
                        "const": "RULE-SADNESS-2018A",
                        "type": "string",
                    },
                    "source_of_truth": {"type": "string", "minLength": 1},
                }
            ),
            "expected": _closed_schema(
                {
                    "emotion": {"const": "sadness", "type": "string"},
                    "match": {"const": True, "type": "boolean"},
                    "numeric_pipeline_used": {"const": False, "type": "boolean"},
                }
            ),
        }
    )
    return _schema_document(
        "urn:acme-firm:schema:oracle:1.0.0",
        "IFATIGUE-INFRA6-M6 oracle contract",
        "Contrato cerrado que mantiene separados entrada, esperado y observación.",
        {
            "$defs": {
                "appraisal_vector": _appraisal_vector_schema(enforce_domain=True),
                "non_rejected_expected": _oracle_expected_schema(rejected=False),
                "rejected_expected": _oracle_expected_schema(rejected=True),
            },
            "oneOf": [
                _closed_schema(numeric_non_rejected),
                _closed_schema(numeric_rejected),
                symbolic,
            ],
        },
    )


def _catalog_schemas(builder: LedgerBuilder) -> dict[str, dict[str, Any]]:
    qa = builder.decisions["T03-QA-011"]["decision"]
    scenario_entry = _closed_schema(
        {
            "scenario_id": {"type": "string", "pattern": SCENARIO_ID_PATTERN},
            "scenario_path": {
                "type": "string",
                "pattern": r"^scenarios/S(?:0[0-9]|1[0-5])\.json$",
            },
            "oracle_path": {
                "type": "string",
                "pattern": r"^oracles/S(?:0[0-9]|1[0-5])\.expected\.json$",
            },
        }
    )
    scenario = _schema_document(
        "urn:acme-firm:schema:scenario-catalog:1.0.0",
        "IFATIGUE-INFRA6-M6 scenario catalog contract",
        "Índice cerrado de dieciséis escenarios de entrada sin resultados embebidos.",
        _closed_schema(
            {
                "$schema": {
                    "const": "../schemas/scenario_catalog.schema.json",
                    "type": "string",
                },
                "schema_version": {"const": "1.0.0", "type": "string"},
                "catalog_id": {"const": "SCENARIOS-16", "type": "string"},
                "expected_entry_count": {"const": 16, "type": "integer"},
                "index_only": {"const": True, "type": "boolean"},
                "source_of_truth": {"type": "string", "minLength": 1},
                "entries": {
                    "type": "array",
                    "minItems": 16,
                    "maxItems": 16,
                    "uniqueItems": True,
                    "x-ifm6-unique-by": [
                        "scenario_id",
                        "scenario_path",
                        "oracle_path",
                    ],
                    "items": scenario_entry,
                },
            }
        ),
    )
    oracle_entry = _closed_schema(
        {
            "oracle_id": {
                "type": "string",
                "pattern": r"^S(?:0[0-9]|1[0-5])\.expected$",
            },
            "scenario_id": {"type": "string", "pattern": SCENARIO_ID_PATTERN},
            "oracle_path": {
                "type": "string",
                "pattern": r"^oracles/S(?:0[0-9]|1[0-5])\.expected\.json$",
            },
            "sha256": {
                "oneOf": [
                    {"type": "null"},
                    {"type": "string", "pattern": SHA256_PATTERN},
                ]
            },
        }
    )
    oracle_seed = qa["source_of_truth"]["oracle_index"]["document_seed"]
    oracle = _schema_document(
        "urn:acme-firm:schema:oracle-catalog:1.0.0",
        "IFATIGUE-INFRA6-M6 oracle catalog contract",
        "Índice cerrado de dieciséis oráculos; no embebe valores esperados.",
        _closed_schema(
            {
                "$schema": {
                    "const": "../schemas/oracle_catalog.schema.json",
                    "type": "string",
                },
                "schema_version": {"const": "1.0.0", "type": "string"},
                "catalog_id": {"const": "ORACLES-16", "type": "string"},
                "expected_entry_count": {"const": 16, "type": "integer"},
                "index_only": {"const": True, "type": "boolean"},
                "source_of_truth": {"type": "string", "minLength": 1},
                "hash_policy": _exact_instance_schema(oracle_seed["hash_policy"]),
                "entries": {
                    "type": "array",
                    "minItems": 16,
                    "maxItems": 16,
                    "uniqueItems": True,
                    "x-ifm6-unique-by": [
                        "oracle_id",
                        "scenario_id",
                        "oracle_path",
                    ],
                    "items": oracle_entry,
                },
            }
        ),
    )
    test_seed = qa["test_catalog"]["document_seed"]
    ut010 = next(item for item in test_seed["test_catalog"] if item["test_id"] == "UT-010")
    test_entry = _closed_schema(
        {
            "test_id": {"type": "string", "pattern": r"^UT-(?:00[1-9]|01[0-8])$"},
            "fq_method": {
                "type": "string",
                "pattern": r"^tests\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.test_[A-Za-z0-9_]+$",
            },
            "scenario_refs": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "pattern": SCENARIO_ID_PATTERN},
            },
            "oracle_refs": {
                "type": "array",
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "pattern": r"^(?:S(?:0[0-9]|1[0-5])\.expected|sadness_2018a_symbolic\.expected)$",
                },
            },
            "local_variant_contract": _exact_instance_schema(
                ut010["local_variant_contract"]
            ),
            "fixture_refs": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "oracle_path": {"type": "string", "minLength": 1},
        },
        required=["test_id", "fq_method", "scenario_refs", "oracle_refs"],
    )
    test = _schema_document(
        "urn:acme-firm:schema:test-catalog:1.0.0",
        "IFATIGUE-INFRA6-M6 test catalog contract",
        "Contrato exacto de descubrimiento para UT-001 a UT-018 sin observaciones prematuras.",
        _closed_schema(
            {
                "$schema": {
                    "const": "../schemas/test_catalog.schema.json",
                    "type": "string",
                },
                "schema_version": {"const": "1.0.0", "type": "string"},
                "expected_test_method_count": {"const": 18, "type": "integer"},
                "framework": {"const": "unittest", "type": "string"},
                "oracle_values_imported_from_production": {
                    "const": False,
                    "type": "boolean",
                },
                "source_of_truth": {"type": "string", "minLength": 1},
                "test_catalog": {
                    "type": "array",
                    "minItems": 18,
                    "maxItems": 18,
                    "uniqueItems": True,
                    "x-ifm6-unique-by": ["test_id", "fq_method"],
                    "items": test_entry,
                },
            }
        ),
    )
    return {
        "schemas/scenario_catalog.schema.json": scenario,
        "schemas/oracle_catalog.schema.json": oracle,
        "schemas/test_catalog.schema.json": test,
    }


def _result_schema() -> dict[str, Any]:
    common = {
        "$schema": {"const": "../../schemas/result.schema.json", "type": "string"},
        "schema_version": {"const": "1.0.0", "type": "string"},
        "scenario_id": {"type": "string"},
        "evaluation_time": {
            "const": "2026-09-04T12:00:00Z",
            "type": "string",
        },
        "disposition": {"type": "string"},
        "diagnostics": _diagnostics_schema(),
        "factor_validation_performed": {"type": "boolean"},
        "modulation": _modulation_schema(),
        "classification": _classification_schema(),
        "modulation_trace": {},
        "rejection_record": {},
    }
    non_rejected = deepcopy(common)
    non_rejected.update(
        {
            "scenario_id": {
                "type": "string",
                "pattern": NON_REJECTED_SCENARIO_ID_PATTERN,
            },
            "disposition": {
                "type": "string",
                "enum": ["applied_no_change", "modulated", "abstained"],
            },
            "output": {"$ref": "#/$defs/appraisal_vector"},
            "modulation_trace": _closed_schema(
                {
                    "exists": {"const": True, "type": "boolean"},
                    "path": {
                        "type": "string",
                        "pattern": r"^traces/reference_run/S(?:0[0-9]|1[0-4])\.trace\.json$",
                    },
                }
            ),
            "rejection_record": {
                "const": {"exists": False},
                "type": "object",
            },
        }
    )
    rejected = deepcopy(common)
    rejected.update(
        {
            "scenario_id": {"const": "S15", "type": "string"},
            "disposition": {"const": "rejected", "type": "string"},
            "diagnostics": {
                "const": ["HOST_BASELINE_OUT_OF_RANGE"],
                "type": "array",
            },
            "factor_validation_performed": {"const": False, "type": "boolean"},
            "modulation": {
                "const": {
                    "attempted": False,
                    "formula_evaluated": False,
                    "coping_potential_changed": False,
                },
                "type": "object",
            },
            "classification": {
                "const": {"attempted": False},
                "type": "object",
            },
            "modulation_trace": {
                "const": {"exists": False},
                "type": "object",
            },
            "rejection_record": {
                "const": {
                    "exists": True,
                    "path": "traces/reference_run/rejections/S15.rejection.json",
                },
                "type": "object",
            },
        }
    )
    return _schema_document(
        "urn:acme-firm:schema:result:1.0.0",
        "IFATIGUE-INFRA6-M6 reference result contract",
        "Contrato cerrado de resultados observados; S15 no admite salida parcial.",
        {
            "$defs": {
                "appraisal_vector": _appraisal_vector_schema(enforce_domain=True)
            },
            "oneOf": [_closed_schema(non_rejected), _closed_schema(rejected)],
        },
    )


def _rejection_schema() -> dict[str, Any]:
    return _schema_document(
        "urn:acme-firm:schema:rejection:1.0.0",
        "IFATIGUE-INFRA6-M6 pre-modulation rejection contract",
        "Único rechazo S15, separado de las quince trazas de modulación.",
        _closed_schema(
            {
                "$schema": {
                    "const": "../../../schemas/rejection.schema.json",
                    "type": "string",
                },
                "schema_version": {"const": "1.0.0", "type": "string"},
                "rejection_id": {"const": "S15.rejection", "type": "string"},
                "scenario_id": {"const": "S15", "type": "string"},
                "result_ref": {
                    "const": "results/reference_run/S15.result.json",
                    "type": "string",
                },
                "phase": {"const": "host_baseline", "type": "string"},
                "baseline_validation": {"const": "rejected", "type": "string"},
                "diagnostics": {
                    "const": ["HOST_BASELINE_OUT_OF_RANGE"],
                    "type": "array",
                },
                "factor_validation_performed": {"const": False, "type": "boolean"},
                "modulation_attempted": {"const": False, "type": "boolean"},
                "classification_attempted": {"const": False, "type": "boolean"},
                "modulation_trace": {"const": False, "type": "boolean"},
                "trace_id_present": {"const": False, "type": "boolean"},
            }
        ),
    )


def _build_recipe_schema(builder: LedgerBuilder) -> dict[str, Any]:
    recipe = build_contract_documents(builder)["manifests/BUILD_RECIPE.json"]
    contract = _exact_instance_schema(recipe)
    registry = contract["properties"]["generator_registry"]["properties"]
    generator_hashes = _closed_schema(
        {
            path: {"type": "string", "pattern": SHA256_PATTERN}
            for path in recipe["generator_registry"]["required_paths"]
        }
    )
    registry["current_hashes"] = {
        "oneOf": [
            {"type": "null"},
            generator_hashes,
        ]
    }
    registry["current_status"] = {
        "type": "string",
        "enum": [
            "hash_registry_planned_not_attested_in_this_decision",
            "materialized_and_hashed",
        ],
    }
    return _schema_document(
        "urn:acme-firm:schema:build-recipe:1.0.0",
        "IFATIGUE-INFRA6-M6 build recipe contract",
        "Receta canónica fail-closed con registro explícito de generadores y validadores.",
        contract,
    )


def _generation_topology_schema(builder: LedgerBuilder) -> dict[str, Any]:
    topology = build_contract_documents(builder)[
        "manifests/GENERATION_TOPOLOGY.json"
    ]
    return _schema_document(
        "urn:acme-firm:schema:generation-topology:1.0.0",
        "IFATIGUE-INFRA6-M6 generation topology contract",
        "DAG canónico y reglas de aciclicidad de la generación reproducible.",
        _exact_instance_schema(topology),
    )


def _executed_validator_registry_schema() -> dict[str, Any]:
    validator = _closed_schema(
        {
            "validator_id": {"type": "string", "minLength": 1},
            "path": {"type": "string", "minLength": 1},
            "validator_command": {"type": "string", "minLength": 1},
            "execution_status": {"const": "pass", "type": "string"},
            "exit_code": {"const": 0, "type": "integer"},
        }
    )
    return _closed_schema(
        {
            "acceptance_rule": {"type": "string", "minLength": 1},
            "execution_status": {"const": "pass", "type": "string"},
            "source_manifest_membership": {"type": "string", "minLength": 1},
            "stage": {"type": "string", "minLength": 1},
            "validators": {
                "type": "array",
                "minItems": 2,
                "uniqueItems": True,
                "x-ifm6-unique-by": ["validator_id", "path"],
                "items": validator,
            },
        }
    )


def _build_record_schema(builder: LedgerBuilder) -> dict[str, Any]:
    seed = build_contract_documents(builder)["manifests/BUILD_RECORD.json"]
    planned = _exact_instance_schema(seed)
    completed = _closed_schema(
        {
            "$schema": {
                "const": "../schemas/build_record.schema.json",
                "type": "string",
            },
            "schema_version": {"const": "1.0.0", "type": "string"},
            "record_id": {
                "const": "BUILD-RECORD-IFM6-1.1.0-CANDIDATE-001",
                "type": "string",
            },
            "recipe_id": {
                "const": "BUILD-IFM6-1.1.0-CANDIDATE-001",
                "type": "string",
            },
            "recipe_path": {"const": "manifests/BUILD_RECIPE.json", "type": "string"},
            "status": {"const": "completed", "type": "string"},
            "required_fields": _exact_instance_schema(seed["required_fields"]),
            "recipe_sha256": {"type": "string", "pattern": SHA256_PATTERN},
            "source_manifest_sha256": {"type": "string", "pattern": SHA256_PATTERN},
            "generators": {
                "type": "array",
                "minItems": 10,
                "uniqueItems": True,
                "x-ifm6-unique-by": ["path"],
                "items": _closed_schema(
                    {
                        "path": {"type": "string", "minLength": 1},
                        "sha256": {"type": "string", "pattern": SHA256_PATTERN},
                    }
                ),
            },
            "schemas": {
                "type": "array",
                "minItems": 17,
                "uniqueItems": True,
                "x-ifm6-unique-by": ["path", "schema_id"],
                "items": _closed_schema(
                    {
                        "path": {"type": "string", "minLength": 1},
                        "schema_id": {"type": "string", "minLength": 1},
                        "schema_version": {"type": "string", "minLength": 1},
                        "sha256": {"type": "string", "pattern": SHA256_PATTERN},
                    }
                ),
            },
            "declared_inputs": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "declared_outputs": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "process_exit_code": {"const": 0, "type": "integer"},
            "validator_registry": _executed_validator_registry_schema(),
            "prohibited_content": _exact_instance_schema(seed["prohibited_content"]),
            "manual_editing_of_derived_nodes": {
                "const": "prohibited",
                "type": "string",
            },
        }
    )
    return _schema_document(
        "urn:acme-firm:schema:build-record:1.0.0",
        "IFATIGUE-INFRA6-M6 build record contract",
        "Distingue la plantilla no ejecutada del registro final determinista.",
        {"oneOf": [planned, completed]},
    )


def _qa_verdict_schema(builder: LedgerBuilder) -> dict[str, Any]:
    qg = builder.decisions["T03-QG-014"]["decision"]
    perspective = _closed_schema(
        {
            "perspective": {
                "type": "string",
                "enum": deepcopy(qg["required_perspectives"]),
            },
            "status": {
                "type": "string",
                "enum": ["not_run", "complete", "not_applicable"],
            },
            "rationale": {"type": "string", "minLength": 1},
        }
    )
    validator = _closed_schema(
        {
            "validator_id": {"type": "string", "minLength": 1},
            "validator_command": {"type": "string", "minLength": 1},
            "execution_status": {
                "type": "string",
                "enum": ["not_run", "pass", "fail"],
            },
            "exit_code": {
                "oneOf": [{"type": "null"}, {"type": "integer", "minimum": 0}]
            },
        }
    )
    finding_contract = qg["finding_contract"]
    finding = _closed_schema(
        {
            "finding_id": {"type": "string", "minLength": 1},
            "perspective": {
                "type": "string",
                "enum": deepcopy(qg["required_perspectives"]),
            },
            "severity": {
                "type": "string",
                "enum": deepcopy(finding_contract["severity_vocabulary"]),
            },
            "status": {
                "type": "string",
                "enum": deepcopy(finding_contract["status_vocabulary"]),
            },
            "object_ref": {"type": "string", "minLength": 1},
            "claim": {"type": "string", "minLength": 1},
            "evidence_refs": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "rationale": {"type": "string", "minLength": 1},
            "required_action": {"type": "string"},
        },
        required=finding_contract["required_fields"],
    )
    return _schema_document(
        "urn:acme-firm:schema:qa-verdict:1.0.0",
        "IFATIGUE-INFRA6-M6 internal QA verdict contract",
        "Dictamen interno ligado al hash exacto de PROVENANCE; no representa revisión externa.",
        _closed_schema(
            {
                "$schema": {
                    "const": "../schemas/qa_verdict.schema.json",
                    "type": "string",
                },
                "schema_version": {"const": "1.0.0", "type": "string"},
                "gate_id": {"const": qg["gate_id"], "type": "string"},
                "reviewed_object_path": {
                    "const": qg["required_review_object"]["path"],
                    "type": "string",
                },
                "reviewed_object_sha256": {
                    "type": "string",
                    "pattern": SHA256_PATTERN,
                },
                "perspective_statuses": {
                    "type": "array",
                    "minItems": len(qg["required_perspectives"]),
                    "maxItems": len(qg["required_perspectives"]),
                    "uniqueItems": True,
                    "x-ifm6-unique-by": ["perspective"],
                    "items": perspective,
                },
                "validator_records": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "x-ifm6-unique-by": ["validator_id"],
                    "items": validator,
                },
                "findings": {
                    "type": "array",
                    "uniqueItems": True,
                    "x-ifm6-unique-by": ["finding_id"],
                    "items": finding,
                },
                "verdict": {
                    "type": "string",
                    "enum": deepcopy(qg["verdict_contract"]["vocabulary"]),
                },
                "reviewed_at_utc": {
                    "type": "string",
                    "pattern": RFC3339_UTC_PATTERN,
                },
                "approval_refs": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
            },
            required=[
                "$schema",
                "schema_version",
                *qg["required_output"]["required_summary_fields"],
            ],
        ),
    )


def schema_documents(builder: LedgerBuilder) -> dict[str, dict[str, Any]]:
    """Return the fifteen T03.3-5 schemas from approved contracts only."""
    qa = builder.decisions["T03-QA-011"]["decision"]
    resolution = resolution_documents(builder)
    config_schema = _schema_document(
        "urn:acme-firm:schema:config:1.0.0",
        "IFATIGUE-INFRA6-M6 resolved configuration contract",
        "Contrato exacto de la configuración derivada; no autoriza edición inversa.",
        _exact_instance_schema(resolution["config/resolved_instance.json"]),
    )
    bindings_schema = _schema_document(
        "urn:acme-firm:schema:formula-bindings:1.0.0",
        "IFATIGUE-INFRA6-M6 formula binding contract",
        "Contrato exacto de tres entradas y una salida distinta, con colisiones fail-closed.",
        _exact_instance_schema(
            resolution["spec/bindings/formula_bindings.json"]
        ),
    )
    documents = {
        "schemas/provenance.schema.json": _provenance_schema(builder.provenance),
        "schemas/config.schema.json": config_schema,
        "schemas/scenario.schema.json": _scenario_schema(builder),
        "schemas/oracle.schema.json": _oracle_schema(),
        "schemas/result.schema.json": _result_schema(),
        "schemas/trace.schema.json": deepcopy(qa["trace_schema_document_seed"]),
        "schemas/rejection.schema.json": _rejection_schema(),
        "schemas/formula_bindings.schema.json": bindings_schema,
        "schemas/build_recipe.schema.json": _build_recipe_schema(builder),
        "schemas/generation_topology.schema.json": _generation_topology_schema(builder),
        "schemas/build_record.schema.json": _build_record_schema(builder),
        "schemas/qa_verdict.schema.json": _qa_verdict_schema(builder),
    }
    documents.update(_catalog_schemas(builder))
    if set(documents) != MATERIALIZED_SCHEMA_PATHS:
        raise ValueError("T03.3-5 schema registry is not the exact fifteen-path set")
    ids = [document.get("$id") for document in documents.values()]
    if len(ids) != len(set(ids)) or any(not schema_id for schema_id in ids):
        raise ValueError("schema identifiers must be present and unique")
    if documents["schemas/trace.schema.json"] != qa["trace_schema_document_seed"]:
        raise ValueError("trace schema must remain the exact T03-QA-011 seed")
    return documents


def add_resolution_document_rows(builder: LedgerBuilder) -> None:
    """Register every authored binding atom and every derived configuration atom."""

    documents = resolution_documents(builder)
    binding = documents["spec/bindings/formula_bindings.json"]
    for index, key in enumerate(sorted(set(binding) - {"binding_map"}), start=1):
        escaped = key.replace("~", "~0").replace("/", "~1")
        builder.add(
            f"DL-BIND-REGISTRY-{index:03d}",
            "spec/bindings/formula_bindings.json",
            f"/{escaped}",
            f"binding_registry.{key}",
            binding[key],
            purpose="Materializar un átomo explícito del registro canónico de enlaces de fórmula.",
            object_refs="BIND-F6-COPING-001|MI-FAT-COP-1.0.0",
            supports=[dec("T03-RS-005"), dec("T03-MP-013")],
            parent="DL-MOD-001",
            claim_ref="CLM-FORMULA-001",
            transformation_type="engineering_decision",
            transformation=(
                "Proyección explícita del contrato aprobado; no atribuye la fórmula ni los "
                "enlaces a las publicaciones fundacionales."
            ),
            m_refs="M3|M6",
        )

    config = documents["config/resolved_instance.json"]
    config_atoms: list[tuple[str, Any, Sequence[tuple[str, str, str, str]], str]] = [
        ("/$schema", config["$schema"], [dec("T03-RP-012"), dec("T03-MP-013")], "DL-BIND-001"),
        ("/schema_version", config["schema_version"], [dec("T03-RP-012"), dec("T03-MP-013")], "DL-BIND-001"),
        ("/instance", config["instance"], [dec("T03-AV-002"), dec("T03-MP-013")], "DL-BIND-001"),
        ("/resolution", config["resolution"], [dec("T03-RS-005"), dec("T03-MP-013")], "DL-BIND-001"),
        ("/host", config["host"], [ev("EV-THESIS-HOST"), ev("EV-2018A-GA-EF", "interpreted"), ev("EV-2018B-GA-EF", "interpreted"), dec("T03-RS-005")], "DL-HST-003"),
        ("/perspective", config["perspective"], [ev("EV-THESIS-F6"), dec("T03-RS-005")], "DL-SCOPE-001"),
        ("/factor", config["factor"], [ev("EV-THESIS-FACTOR"), dec("T03-CT-009")], "DL-FST-011"),
        ("/coping_partition", config["coping_partition"], [ev("EV-THESIS-F6"), dec("T03-RS-005")], "DL-CAT-001"),
        ("/rules", config["rules"], [ev("EV-2018A-SADNESS", "interpreted"), ev("EV-2018B-RULES", "interpreted"), dec("T03-RS-005")], "DL-RUL-SELECT-001"),
        ("/evaluation", config["evaluation"], [ev("EV-THESIS-CONTRACT-TESTS"), dec("T03-RP-012")], "DL-MOD-005"),
        ("/contract", config["contract"], [dec("T03-CT-009"), dec("T03-TM-004"), dec("T03-RP-012")], "DL-FST-011"),
        ("/runtime", config["runtime"], [dec("T03-RP-012"), dec("T03-CT-009"), dec("T03-QA-011")], "DL-REP-007"),
    ]
    for key in sorted(set(config["influence"]) - {"binding_map"}):
        escaped = key.replace("~", "~0").replace("/", "~1")
        config_atoms.append(
            (
                f"/influence/{escaped}",
                config["influence"][key],
                [ev("EV-THESIS-FACTOR"), dec("T03-RS-005"), dec("T03-RP-012")],
                "DL-MOD-001",
            )
        )
    for index, (locator, value, supports, parent) in enumerate(config_atoms, start=1):
        builder.add(
            f"DL-CONFIG-{index:03d}",
            "config/resolved_instance.json",
            locator,
            f"resolved_instance.{locator[1:].replace('/', '.')}",
            value,
            purpose="Componer determinísticamente un átomo de la configuración ejecutable resuelta.",
            object_refs="IFATIGUE-INFRA6-M6|BIND-F6-COPING-001|ME-FAT-INFRA6-1.0.0",
            supports=supports,
            parent=parent,
            claim_class="generated_for_doctoral_instance",
            transformation_type="automatic_derivation",
            transformation=(
                "Composición unidireccional de las capas publicadas, doctoral, de decisiones y "
                "bindings; se prohíbe editar hacia atrás cualquiera de sus fuentes."
            ),
            m_refs="M3|M4|M6",
        )


def add_bindings_and_limits(builder: LedgerBuilder) -> None:
    builder.add(
        "DL-MAP-001",
        "spec/thesis/f6_specification_rc01.json",
        "/influence/mask",
        "influence.mask",
        {field: field == "coping_potential" for field in VECTOR_FIELDS},
        purpose="Autorizar una sola coordenada sin representar banderas semánticas como enteros JSON.",
        object_refs="MFV-FAT-COP-1.0.0",
        supports=[ev("EV-THESIS-FACTOR")],
        parent="DL-SCOPE-001",
        claim_ref="CLM-FAT-COP-001",
        transformation_type="doctoral_synthesis",
        transformation="La máscara booleana operacionaliza la misma hipótesis monofactorial.",
        m_refs="M3|M6",
    )
    builder.add(
        "DL-MOD-001",
        "spec/thesis/f6_specification_rc01.json",
        "/influence/formula",
        "influence.formula",
        "coping_potential_out = clamp(coping_potential_in * (1 - lambda * z), 0, 1)",
        purpose="Congelar la fórmula aprobada y sus cuatro enlaces explícitos.",
        object_refs="MI-FAT-COP-1.0.0|BIND-F6-COPING-001",
        supports=[ev("EV-THESIS-FACTOR"), dec("T03-RS-005")],
        parent="DL-SCOPE-001",
        claim_ref="CLM-FORMULA-001",
        transformation_type="doctoral_synthesis",
        transformation="La expresión es una decisión doctoral acotada y no una ley psicológica.",
        m_refs="M3|M6",
    )
    builder.add(
        "DL-MOD-002",
        "spec/thesis/f6_specification_rc01.json",
        "/influence/parameters/lambda",
        "influence.lambda",
        "0.3",
        purpose="Congelar el parámetro versionado con la forma decimal canónica.",
        object_refs="MI-FAT-COP-1.0.0",
        supports=[ev("EV-THESIS-FACTOR"), dec("T03-RP-012")],
        parent="DL-MOD-001",
        claim_ref="CLM-FORMULA-001",
        transformation_type="doctoral_synthesis",
        transformation="El valor es configurable, no una constante psicológica; IFM6-DEC-v1 elimina ceros finales.",
        m_refs="M3|M6",
    )
    builder.add(
        "DL-MOD-005",
        "spec/thesis/f6_specification_rc01.json",
        "/evaluation/numeric_tolerance",
        "evaluation.numeric_tolerance",
        "0.000000000001",
        purpose="Fijar la tolerancia canónica de comparación sin notación exponencial.",
        object_refs="ME-FAT-INFRA6-1.0.0",
        supports=[ev("EV-THESIS-CONTRACT-TESTS"), dec("T03-RP-012")],
        parent="DL-MOD-004",
        transformation_type="doctoral_synthesis",
        transformation="La tolerancia gobierna comparaciones; no redondea ni representa incertidumbre empírica.",
        m_refs="M4|M5|M6",
    )
    mp = builder.decisions["T03-MP-013"]["decision"]
    binding_map = mp["required_executable_binding_map"]
    binding_artifacts = mp["binding_artifacts"]
    expected_bindings = {
        "coping_potential": "host.baseline.coping_potential",
        "lambda": "influence.parameters.lambda",
        "z": "factor_state.level",
        "result": "output.coping_potential",
    }
    if (
        binding_map != expected_bindings
        or binding_artifacts["binding_map_values"] != expected_bindings
        or binding_artifacts["input_keys"] != ["coping_potential", "lambda", "z"]
        or binding_artifacts["output_key"] != "result"
        or binding_artifacts["result_is_input"] is not False
    ):
        raise ValueError("T03-MP-013 executable binding map is not the approved four-binding contract")
    formula_binding = builder.decisions["T03-RS-005"]["decision"]["formula_binding"]
    if formula_binding["executable_binding_map"] != expected_bindings:
        raise ValueError("T03-RS-005 and T03-MP-013 binding maps diverge")
    if formula_binding["binding_roles"] != {
        "input_binding_count": 3,
        "input_keys": ["coping_potential", "lambda", "z"],
        "output_binding_count": 1,
        "output_key": "result",
        "result_is_input": False,
    }:
        raise ValueError("T03-RS-005 does not freeze three inputs and one distinct output")
    if formula_binding["formula_to_binding_key_crosswalk"] != {
        "coping_potential_in": "coping_potential",
        "coping_potential_out": "result",
        "lambda": "lambda",
        "z": "z",
    }:
        raise ValueError("T03-RS-005 formula-to-binding crosswalk is incomplete")
    binding_targets = [
        (
            "DL-BIND",
            binding_artifacts["registry"]["path"],
            binding_artifacts["registry"]["locators"],
        ),
        (
            "DL-BIND-RESOLVED",
            binding_artifacts["resolved_config"]["path"],
            binding_artifacts["resolved_config"]["locators"],
        ),
        (
            "DL-BIND-CODE",
            binding_artifacts["implementation"]["path"],
            binding_artifacts["implementation"]["semantic_anchors"],
        ),
    ]
    if len({target_path for _, target_path, _ in binding_targets}) != 3:
        raise ValueError("T03-MP-013 must identify three distinct binding artifacts")
    for prefix, target_path, locators in binding_targets:
        if set(locators) != set(expected_bindings):
            raise ValueError(f"incomplete binding locator registry for {target_path}")
        for index, key in enumerate(("coping_potential", "lambda", "z", "result"), start=1):
            builder.add(
                f"{prefix}-{index:03d}",
                target_path,
                locators[key],
                (
                    f"influence.output_binding.{key}"
                    if key == "result"
                    else f"influence.input_bindings.{key}"
                ),
                binding_map[key],
                purpose=(
                    "Propagar explícitamente una entrada, parámetro o salida de la fórmula "
                    "sin usar rutas implícitas."
                ),
                object_refs="BIND-F6-COPING-001|MI-FAT-COP-1.0.0",
                supports=[dec("T03-RS-005"), dec("T03-MP-013")],
                parent="DL-MOD-001",
                claim_ref="CLM-FORMULA-001",
                m_refs="M3|M6",
            )
    add_resolution_document_rows(builder)
    partition = [
        ("DL-CAT-001", 0, {"label": "null", "predicate": "coping_potential <= 0.3"}),
        (
            "DL-CAT-002",
            1,
            {
                "label": "approachable",
                "predicate": "coping_potential > 0.3 and coping_potential <= 0.7",
            },
        ),
        (
            "DL-CAT-003",
            2,
            {"label": "highly_approachable", "predicate": "coping_potential > 0.7"},
        ),
    ]
    for derivation_id, index, value in partition:
        builder.add(
            derivation_id,
            "spec/thesis/f6_specification_rc01.json",
            f"/coping_partition/categories/{index}",
            f"coping_partition.{index}",
            value,
            purpose="Congelar una banda de la partición crisp doctoral con decimales canónicos.",
            object_refs="MI-FAT-COP-1.0.0",
            supports=[ev("EV-THESIS-FACTOR")],
            parent="DL-MOD-004",
            claim_ref="CLM-THRESHOLDS-001",
            transformation_type="doctoral_synthesis",
            transformation="La partición apoya conformidad interna; no se atribuye a la publicación.",
            m_refs="M3|M6",
        )
    builder.add(
        "DL-CAT-004",
        "spec/thesis/f6_specification_rc01.json",
        "/coping_partition/source_status",
        "coping_partition.source_status",
        {
            "f6_partition_is_historical_fuzzy_function": False,
            "kind": "doctoral_crisp_partition",
            "positive_equivalence": None,
        },
        purpose="Distinguir la partición F6 de las funciones difusas históricas.",
        object_refs="MI-FAT-COP-1.0.0",
        supports=[ev("EV-THESIS-FACTOR"), dec("T03-RS-005")],
        parent="DL-CAT-003",
        claim_ref="CLM-THRESHOLDS-001",
        m_refs="M3|M6",
    )
    builder.add(
        "DL-LIM-001",
        "docs/SCOPE_AND_LIMITATIONS.md",
        "@permitted-claims",
        "evidence.permitted_claims",
        {
            "dsr_claims": ["instantiation", "technical_conformance", "traceability"],
            "technical_conformance_dimensions": ["determinism", "reproducibility", "locality"],
        },
        purpose="Conservar la jerarquía exacta de afirmaciones permitidas.",
        object_refs="ME-FAT-INFRA6-1.0.0",
        supports=[
            ev("EV-THESIS-RESULTS-LIMITS"),
            dec("T03-QG-003"),
            dec("T03-QA-011"),
        ],
        claim_ref="LIM-EVIDENCE-001",
        parent="DL-SCOPE-001",
        transformation_type="doctoral_synthesis",
        m_refs="M5|M6",
    )
    prohibited = builder.sources["dsr_claim_policy"]["prohibited_DSR_claims_without_later_evidence"]
    builder.add(
        "DL-LIM-002",
        "docs/SCOPE_AND_LIMITATIONS.md",
        "@prohibited-claims",
        "evidence.prohibited_claims",
        prohibited,
        purpose="Copiar el vocabulario vinculante de afirmaciones prohibidas.",
        object_refs="ME-FAT-INFRA6-1.0.0",
        supports=[
            dec("T01-AF-021"),
            dec("T03-QG-003"),
            dec("T03-QA-011"),
        ],
        claim_ref="LIM-EVIDENCE-001",
        parent="DL-SCOPE-001",
        transformation_type="metadata_transcription",
        m_refs="M5|M6",
    )
    builder.add(
        "DL-EXC-006",
        "docs/SCOPE_AND_LIMITATIONS.md",
        "@historical-m6-bytes",
        "historical_m6.material_status",
        {"available": False, "continuity_claimed": False, "reused": False, "reported_version": "1.0.0"},
        purpose="Excluir explícitamente los bytes históricos ausentes de M6 v1.0.0.",
        object_refs="SOURCE-EXCLUSION",
        supports=[dec("T03-EX-010")],
        parent="DL-PKG-003",
        claim_class="excluded_from_execution",
        transformation_type="preserve_and_exclude",
        materialization_status="excluded",
    )
    builder.add(
        "DL-EXC-007",
        "docs/DATA_ETHICS_AND_CONSTRUCT_VALIDITY.md",
        "@source-redistribution",
        "source_files.redistribution",
        {"source_files_redistributed": False},
        purpose="Prohibir redistribuir los archivos fuente dentro del paquete.",
        object_refs="SOURCE-EXCLUSION",
        supports=[dec("T03-EX-010")],
        parent="DL-EXC-001",
        claim_class="excluded_from_execution",
        transformation_type="preserve_and_exclude",
        materialization_status="excluded",
    )
    trace_policy = deepcopy(builder.provenance["engineering_reproducibility_profile"]["trace_id_policy"])
    builder.add(
        "DL-REP-007",
        "spec/decisions/engineering_v1.1.0.json",
        "/trace_id",
        "trace.id",
        trace_policy,
        purpose="Fijar el trace_core y separar sus campos de la observación de ejecución.",
        object_refs="REPRODUCIBILITY-PROFILE",
        supports=[dec("T03-RP-012")],
        parent="DL-REP-006",
        m_refs="M4|M6",
    )
    builder.add(
        "DL-EVAL-004",
        "traces/reference_run/rejections/S15.rejection.json",
        "@materialization-recipe",
        "rejection.materialization_recipe",
        {
            "action": "emit_after_host_rejection",
            "baseline_validation": "rejected",
            "classification_attempted": False,
            "diagnostics": ["HOST_BASELINE_OUT_OF_RANGE"],
            "factor_validation_performed": False,
            "modulation_attempted": False,
            "modulation_trace": False,
            "phase": "host_baseline",
            "rejection_record": True,
            "scenario_id": "S15",
            "status_before_run": "not_observed",
            "trace_id_present": False,
        },
        purpose="Fijar la receta del rechazo separado de S15 sin afirmar que ya ocurrió.",
        object_refs="ME-FAT-INFRA6-1.0.0",
        supports=[
            ev("EV-THESIS-RESULTS-LIMITS"),
            dec("T01-AF-015"),
            dec("T03-QA-011"),
        ],
        parent="DL-SCOPE-001",
        claim_ref="LIM-EVIDENCE-001",
        claim_class="pending_verification",
        transformation_type="doctoral_synthesis",
        transformation="Un rechazo del anfitrión no es una traza de modulación ni un resultado preexistente.",
        m_refs="M5|M6",
    )


def scenario_documents(builder: LedgerBuilder) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    bl = builder.decisions["T03-BL-006"]["decision"]
    evaluation_time = bl["evaluation_time"]
    t0 = utc_parse(evaluation_time)
    baseline = lambda coping: {**PROTECTED_BASELINE, "coping_potential": coping}

    def factor(
        sid: str,
        level: str,
        *,
        confidence: str = "1",
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return {
            "confidence": confidence,
            "level": level,
            "observed_at": observed_at or evaluation_time,
            "source_id": f"synthetic:T03-BL-006:{sid}",
            "state_schema_version": "1.0.0",
        }

    def metadata(sid: str) -> dict[str, Any]:
        return {
            "scenario_id": sid,
            "event": deepcopy(STABLE_SCENARIO_EVENT),
            "fixture_class": "synthetic_conformance_fixture",
            "empirical_support": "none",
            "evaluation_time": evaluation_time,
        }

    scenarios: dict[str, dict[str, Any]] = {}
    levels = ["0", "0.2", "0.5", "0.8", "1"]
    for index, level in enumerate(levels):
        sid = f"S{index:02d}"
        scenarios[sid] = {
            **metadata(sid),
            "baseline": baseline("0.6"),
            "factor_state": factor(sid, level),
        }
    scenarios["S05"] = {
        **metadata("S05"),
        "baseline": baseline("0"),
        "factor_state": factor("S05", "1"),
    }
    scenarios["S06"] = {
        **metadata("S06"),
        "baseline": baseline("1"),
        "factor_state": factor("S06", "0"),
    }
    s07_seed = bl["scenario_inputs"]["S07"]
    if s07_seed != {"coping_potential": "0.6", "factor_state": None}:
        raise ValueError("T03-BL-006 S07 input seed is incomplete")
    scenarios["S07"] = {
        **metadata("S07"),
        "baseline": baseline(s07_seed["coping_potential"]),
        "factor_state": s07_seed["factor_state"],
    }
    scenarios["S08"] = {
        **metadata("S08"),
        "baseline": baseline("0.6"),
        "factor_state": factor("S08", "0.5", observed_at=utc_format(t0 - timedelta(seconds=301))),
    }
    scenarios["S09"] = {
        **metadata("S09"),
        "baseline": baseline("0.6"),
        "factor_state": factor("S09", "-0.01"),
    }
    scenarios["S10"] = {
        **metadata("S10"),
        "baseline": baseline("0.6"),
        "factor_state": factor("S10", "1.01"),
    }
    scenarios["S11"] = {
        **metadata("S11"),
        "baseline": baseline("0.6"),
        "factor_state": factor("S11", "0.5", confidence="0.49"),
    }
    scenarios["S12"] = {
        **metadata("S12"),
        "baseline": baseline("0.6"),
        "factor_state": factor("S12", "0.5", observed_at=utc_format(t0 + timedelta(seconds=6))),
    }
    scenarios["S13"] = {
        **metadata("S13"),
        "baseline": baseline("0.6"),
        "factor_state": factor("S13", "0.5", observed_at=utc_format(t0 - timedelta(seconds=300))),
    }
    scenarios["S14"] = {
        **metadata("S14"),
        "baseline": baseline("0.35"),
        "factor_state": factor("S14", "1"),
        "host_symbolic_payload": {
            "desirability": "undesirable",
            "expectedness": "unexpected",
            "goal_conduciveness": "negative",
            "novelty": "not_novelty",
            "pleasure": "not_pleasant",
            "source": bl["s14_symbolic_context"],
        },
    }
    scenarios["S15"] = {
        **metadata("S15"),
        "baseline": baseline("1.1"),
        "factor_state": factor("S15", "0.5"),
    }

    oracle_policy = bl["oracle_payload_policy"]["document_contract"]
    fixed_outer = oracle_policy["fixed_outer_values"]
    expected_semantics = oracle_policy["scenario_semantics"]
    if set(expected_semantics) != {f"S{index:02d}" for index in range(16)}:
        raise ValueError("T03-BL-006 must freeze exactly S00-S15 oracle semantics")
    if fixed_outer != {
        "$schema": "../schemas/oracle.schema.json",
        "empirical_support": "none",
        "frozen_before_implementation": True,
        "oracle_class": "synthetic_conformance_oracle",
        "schema_version": "1.0.0",
    }:
        raise ValueError("T03-BL-006 oracle fixed outer values have changed")
    oracles: dict[str, dict[str, Any]] = {}
    for sid in [f"S{index:02d}" for index in range(16)]:
        expected = deepcopy(expected_semantics[sid])
        provenance_refs = ["T03-BL-006", "T03-QA-011", "T03-RP-012"]
        if sid == "S14":
            provenance_refs.append("T03-RS-005")
        if sid == "S15":
            provenance_refs = ["T03-BL-006", "T03-CT-009", "T03-QA-011"]
        calculation_basis: dict[str, Any]
        if sid == "S15":
            calculation_basis = {
                "host_validation_precedes_factor_validation": True,
                "source_of_truth": "PROVENANCE.json#decisions/T03-QA-011",
            }
        else:
            calculation_basis = {
                "decimal_profile": "IFM6-DEC-v1",
                "formula": "coping_potential_out = clamp(coping_potential_in * (1 - lambda * z), 0, 1)",
                "lambda": "0.3",
                "source_of_truth": "PROVENANCE.json#decisions/T03-BL-006/oracle_payload_policy/document_contract/scenario_semantics",
            }
        oracle: dict[str, Any] = {
            **deepcopy(fixed_outer),
            "oracle_id": f"{sid}.expected",
            "scenario_id": sid,
            "scenario_ref": f"scenarios/{sid}.json",
            "calculation_basis": calculation_basis,
            "expected": expected,
            "provenance_refs": provenance_refs,
        }
        oracles[sid] = oracle
    return scenarios, oracles


def _top_level_atomic_entries(document: Mapping[str, Any]) -> list[tuple[str, str, Any]]:
    """Split a fixture into semantic atoms without copying its whole document."""
    entries: list[tuple[str, str, Any]] = []
    for key in sorted(document):
        value = document[key]
        if key == "expected" and isinstance(value, dict):
            for expected_key in sorted(value):
                entries.append(
                    (
                        f"/expected/{expected_key}",
                        f"expected.{expected_key}",
                        value[expected_key],
                    )
                )
        else:
            pointer_key = key.replace("~", "~0").replace("/", "~1")
            entries.append((f"/{pointer_key}", key, value))
    return entries


def add_atomic_document(
    builder: LedgerBuilder,
    *,
    base_derivation_id: str,
    target_path: str,
    document: Mapping[str, Any],
    supports: Sequence[tuple[str, str, str, str]],
    parent: str,
    claim_ref: str,
    purpose: str,
    supports_by_locator: Mapping[
        str, Sequence[tuple[str, str, str, str]]
    ] | None = None,
    claim_ref_by_locator: Mapping[str, str] | None = None,
    claim_class_by_locator: Mapping[str, str] | None = None,
    transformation_type: str = "engineering_decision",
) -> None:
    """Register one row per semantic atom, as mandated by T03-QA-011."""
    entries = _top_level_atomic_entries(document)
    for index, (locator, field, value) in enumerate(entries):
        atom_supports = (
            supports_by_locator.get(locator, supports)
            if supports_by_locator is not None
            else supports
        )
        if not atom_supports:
            raise ValueError(f"atomic target {target_path}#{locator} lacks support")
        atom_claim_ref = (
            claim_ref_by_locator.get(locator, claim_ref)
            if claim_ref_by_locator is not None
            else claim_ref
        )
        atom_claim_class = (
            claim_class_by_locator.get(locator)
            if claim_class_by_locator is not None
            else None
        )
        derivation_id = (
            base_derivation_id
            if index == 0
            else f"{base_derivation_id}-ATOM-{index:02d}"
        )
        builder.add(
            derivation_id,
            target_path,
            locator,
            field,
            value,
            purpose=purpose,
            object_refs="ME-FAT-INFRA6-1.0.0",
            supports=atom_supports,
            parent=parent if index == 0 else base_derivation_id,
            claim_ref=atom_claim_ref,
            claim_class=atom_claim_class,
            transformation_type=transformation_type,
            transformation=(
                "Registro atómico; la unión de las hojas se materializa sólo en la ruta canónica "
                "y el ledger nunca funciona como entrada de implementación."
            ),
            m_refs="M5|M6",
        )


def add_scenarios_oracles_and_tests(builder: LedgerBuilder) -> None:
    scenarios, oracles = scenario_documents(builder)
    qa = builder.decisions["T03-QA-011"]["decision"]
    for index in range(16):
        sid = f"S{index:02d}"
        scenario_supports = [dec("T03-BL-006"), dec("T03-QA-011")]
        if sid in {"S08", "S12", "S13"}:
            scenario_supports.append(dec("T03-TM-004"))
        elif sid == "S14":
            scenario_supports.append(dec("T03-RS-005"))
        elif sid == "S15":
            scenario_supports.append(dec("T03-CT-009"))
        scenario_supports_by_locator = None
        scenario_claim_refs = None
        scenario_claim_classes = None
        if sid == "S14":
            scenario_supports_by_locator = {
                "/host_symbolic_payload": [
                    ev("EV-2018B-RULES", "interpreted"),
                    *scenario_supports,
                ]
            }
            scenario_claim_refs = {"/host_symbolic_payload": "CLM-ANGER-001"}
            scenario_claim_classes = {
                "/host_symbolic_payload": "doctoral_inference"
            }
        add_atomic_document(
            builder,
            base_derivation_id=f"DL-SCN-{index:02d}",
            target_path=f"scenarios/{sid}.json",
            document=scenarios[sid],
            supports=scenario_supports,
            parent="DL-SCOPE-001",
            claim_ref="LIM-EVIDENCE-001",
            purpose="Congelar una entrada sintética antes de implementar el código; no contiene esperado.",
            supports_by_locator=scenario_supports_by_locator,
            claim_ref_by_locator=scenario_claim_refs,
            claim_class_by_locator=scenario_claim_classes,
        )
        oracle_supports = [dec("T03-BL-006"), dec("T03-QA-011")]
        if sid != "S15":
            oracle_supports.append(dec("T03-RP-012"))
        if sid == "S14":
            oracle_supports.append(dec("T03-RS-005"))
        if sid == "S15":
            oracle_supports.append(dec("T03-CT-009"))
        oracle_supports_by_locator = None
        oracle_claim_refs = None
        oracle_claim_classes = None
        if sid == "S14":
            oracle_supports_by_locator = {
                "/expected/classification": [
                    ev("EV-2018B-RULES", "interpreted"),
                    *oracle_supports,
                ]
            }
            oracle_claim_refs = {"/expected/classification": "CLM-ANGER-001"}
            oracle_claim_classes = {
                "/expected/classification": "doctoral_inference"
            }
        add_atomic_document(
            builder,
            base_derivation_id=f"DL-ORC-{index:02d}",
            target_path=f"oracles/{sid}.expected.json",
            document=oracles[sid],
            supports=oracle_supports,
            parent=f"DL-SCN-{index:02d}",
            claim_ref="LIM-EVIDENCE-001",
            purpose="Congelar por átomos un oráculo independiente previo a la implementación.",
            supports_by_locator=oracle_supports_by_locator,
            claim_ref_by_locator=oracle_claim_refs,
            claim_class_by_locator=oracle_claim_classes,
        )

    scenario_catalog_seed = deepcopy(
        qa["source_of_truth"]["scenario_index"]["document_seed"]
    )
    scenario_catalog_entries = scenario_catalog_seed.pop("entries")
    scenario_expected_entry_count = scenario_catalog_seed.pop("expected_entry_count")
    add_atomic_document(
        builder,
        base_derivation_id="DL-SCN-CATALOG",
        target_path="scenarios/catalog.json",
        document=scenario_catalog_seed,
        supports=[dec("T03-QA-011")],
        parent="DL-SCOPE-001",
        claim_ref="LIM-EVIDENCE-001",
        purpose="Materializar un índice uno-a-uno que no embebe entradas ni esperados.",
    )
    builder.add(
        "DL-EVAL-001",
        "scenarios/catalog.json",
        "/expected_entry_count",
        "scenario.expected_entry_count",
        scenario_expected_entry_count,
        purpose="Fijar exactamente dieciséis escenarios canónicos de entrada.",
        object_refs="SCENARIOS-16|ME-FAT-INFRA6-1.0.0",
        supports=[ev("EV-THESIS-CONTRACT-TESTS"), dec("T03-QA-011")],
        parent="DL-SCOPE-001",
        claim_ref="LIM-EVIDENCE-001",
        transformation="El conteo normativo no equivale a calidad ni evidencia empírica.",
        m_refs="M5|M6",
    )
    for index, entry in enumerate(scenario_catalog_entries):
        builder.add(
            f"DL-SCN-CATALOG-ENTRY-{index:02d}",
            "scenarios/catalog.json",
            f"/entries/{index}",
            f"scenario_catalog.entries.{index}",
            entry,
            purpose="Registrar una entrada de índice sin duplicar el escenario ni el oráculo.",
            object_refs="SCENARIOS-16|ME-FAT-INFRA6-1.0.0",
            supports=[dec("T03-QA-011")],
            parent="DL-SCN-CATALOG",
            claim_ref="LIM-EVIDENCE-001",
            m_refs="M5|M6",
        )
    oracle_catalog_seed = deepcopy(
        qa["source_of_truth"]["oracle_index"]["document_seed"]
    )
    oracle_catalog_entries = oracle_catalog_seed.pop("entries")
    for index, entry in enumerate(oracle_catalog_entries):
        sid = f"S{index:02d}"
        if entry != {
            "oracle_id": f"{sid}.expected",
            "oracle_path": f"oracles/{sid}.expected.json",
            "scenario_id": sid,
            "sha256": None,
        }:
            raise ValueError(f"oracle catalogue seed entry diverges for {sid}")
        oracle_bytes = (canonical_json(oracles[sid]) + "\n").encode("utf-8")
        entry["sha256"] = hashlib.sha256(oracle_bytes).hexdigest()
    add_atomic_document(
        builder,
        base_derivation_id="DL-ORC-CATALOG",
        target_path="oracles/catalog.json",
        document=oracle_catalog_seed,
        supports=[dec("T03-QA-011"), dec("T03-RP-012")],
        parent="DL-SCOPE-001",
        claim_ref="LIM-EVIDENCE-001",
        purpose="Definir metadatos normativos del índice de oráculos sin embebidos.",
    )
    for index, entry in enumerate(oracle_catalog_entries):
        builder.add(
            f"DL-ORC-CATALOG-ENTRY-{index:02d}",
            "oracles/catalog.json",
            f"/entries/{index}",
            f"oracle_catalog.entries.{index}",
            entry,
            purpose="Registrar una entrada de índice con el hash del oráculo independiente congelado.",
            object_refs="ORACLES-16|ME-FAT-INFRA6-1.0.0",
            supports=[dec("T03-QA-011"), dec("T03-RP-012")],
            parent="DL-ORC-CATALOG",
            claim_ref="LIM-EVIDENCE-001",
            transformation="El índice referencia el oráculo canónico, registra sus bytes congelados y no duplica su contenido.",
            m_refs="M5|M6",
        )

    exact_methods = qa_test_catalog(builder.provenance)
    test_catalog_seed = deepcopy(qa["test_catalog"]["document_seed"])
    seeded_methods = test_catalog_seed.pop("test_catalog")
    if seeded_methods != exact_methods:
        raise ValueError("T03-QA-011 test catalog seed diverges from its registry")
    add_atomic_document(
        builder,
        base_derivation_id="DL-EVAL-002",
        target_path="tests/test_catalog.json",
        document=test_catalog_seed,
        supports=[dec("T03-QA-011")],
        parent="DL-SCOPE-001",
        claim_ref="LIM-EVIDENCE-001",
        purpose="Definir los metadatos del catálogo único de pruebas.",
    )
    for index, method in enumerate(exact_methods):
        builder.add(
            f"DL-EVAL-002-ENTRY-{index + 1:03d}",
            "tests/test_catalog.json",
            f"/test_catalog/{index}",
            f"unit_test.test_catalog.{index}",
            method,
            purpose="Copiar una entrada exacta del catálogo aprobado, sin redefinir fq_method.",
            object_refs="ME-FAT-INFRA6-1.0.0|TESTS-18",
            supports=[dec("T03-QA-011")],
            parent="DL-EVAL-002",
            claim_ref="LIM-EVIDENCE-001",
            m_refs="M5|M6",
        )


def locate_sadness_paths(paths: Sequence[str]) -> tuple[str, str]:
    sadness_paths = [path for path in paths if re.search(r"sadness|tristeza", path, re.I)]
    fixture = [
        path
        for path in sadness_paths
        if re.search(r"fixture|scenario|escenario", path, re.I)
        and not re.search(r"oracle|expected|oraculo", path, re.I)
    ]
    oracle = [path for path in sadness_paths if re.search(r"oracle|expected|oraculo", path, re.I)]
    if len(fixture) != 1 or len(oracle) != 1:
        raise ValueError("cannot resolve the unique sadness fixture/oracle paths")
    return fixture[0], oracle[0]


def add_sadness_fixture(builder: LedgerBuilder) -> None:
    fixture_path, oracle_path = locate_sadness_paths(builder.planned_paths)
    fixture = {
        "$schema": "../../schemas/scenario.schema.json",
        "schema_version": "1.0.0",
        "fixture_id": "sadness_2018a_symbolic",
        "event_context": {
            "cause_class": "unwanted_event_occurred",
            "consequence_target": "myself",
        },
        "fixture_class": "synthetic_symbolic_regression_fixture",
        "numeric_pipeline_input": False,
        "published_symbolic_payload": {
            antecedent["field"]: antecedent["value"] for antecedent in SADNESS_ANTECEDENTS[1:]
        },
        "provenance_refs": ["EV-2018A-SADNESS", "T03-RS-005", "T03-QA-011"],
        "source_rule_ref": "RULE-SADNESS-2018A",
    }
    fixture["published_symbolic_payload"]["Consequence (E)"] = "myself"
    oracle = {
        "$schema": "../../schemas/oracle.schema.json",
        "schema_version": "1.0.0",
        "oracle_id": "sadness_2018a_symbolic.expected",
        "fixture_ref": fixture_path,
        "frozen_before_implementation": True,
        "calculation_basis": {
            "execution_profile": "isolated_symbolic_regression",
            "published_rule_ref": "RULE-SADNESS-2018A",
            "source_of_truth": "PROVENANCE.json#decisions/T03-RS-005",
        },
        "expected": {
            "emotion": "sadness",
            "match": True,
            "numeric_pipeline_used": False,
        },
        "oracle_class": "synthetic_symbolic_regression_oracle",
        "provenance_refs": ["EV-2018A-SADNESS", "T03-RS-005", "T03-QA-011"],
        "source_rule_ref": "RULE-SADNESS-2018A",
    }
    sadness_decision_supports = [dec("T03-RS-005"), dec("T03-QA-011")]
    fixture_supports_by_locator = {
        "/event_context": [
            ev("EV-2018A-SADNESS", "interpreted"),
            *sadness_decision_supports,
        ],
        "/published_symbolic_payload": [
            ev("EV-2018A-SADNESS", "direct"),
            *sadness_decision_supports,
        ],
    }
    oracle_supports_by_locator = {
        "/expected/emotion": [
            ev("EV-2018A-SADNESS", "direct"),
            *sadness_decision_supports,
        ],
        "/expected/match": [
            ev("EV-2018A-SADNESS", "interpreted"),
            *sadness_decision_supports,
        ],
    }
    fixture_claim_refs = {
        "/event_context": "CLM-SADNESS-001",
        "/published_symbolic_payload": "CLM-SADNESS-001",
    }
    fixture_claim_classes = {
        "/event_context": "doctoral_inference",
        "/published_symbolic_payload": "explicit_source",
    }
    oracle_claim_refs = {
        "/expected/emotion": "CLM-SADNESS-001",
        "/expected/match": "CLM-SADNESS-001",
    }
    oracle_claim_classes = {
        "/expected/emotion": "explicit_source",
        "/expected/match": "doctoral_inference",
    }
    add_atomic_document(
        builder,
        base_derivation_id="DL-FIX-SADNESS-001",
        target_path=fixture_path,
        document=fixture,
        supports=sadness_decision_supports,
        parent="DL-RUL-SAD-010",
        claim_ref="",
        purpose="Ejercer atómicamente la regla de tristeza con términos fuente y contexto explícito.",
        supports_by_locator=fixture_supports_by_locator,
        claim_ref_by_locator=fixture_claim_refs,
        claim_class_by_locator=fixture_claim_classes,
    )
    add_atomic_document(
        builder,
        base_derivation_id="DL-ORC-SADNESS-001",
        target_path=oracle_path,
        document=oracle,
        supports=sadness_decision_supports,
        parent="DL-FIX-SADNESS-001",
        claim_ref="",
        purpose="Congelar atómicamente el esperado de la regresión simbólica de tristeza.",
        supports_by_locator=oracle_supports_by_locator,
        claim_ref_by_locator=oracle_claim_refs,
        claim_class_by_locator=oracle_claim_classes,
    )


def add_trace_contract_rows(builder: LedgerBuilder) -> None:
    """Project the frozen trace schema, shared template and fifteen bindings."""
    qa = builder.decisions["T03-QA-011"]["decision"]
    schema_seed = deepcopy(qa["trace_schema_document_seed"])
    projection = deepcopy(qa["trace_result_projection_contract"])
    template = deepcopy(qa["trace_materialization_template"])
    binding_recipes = template.pop("binding_recipes")
    expected_sids = [f"S{index:02d}" for index in range(15)]
    if [item["recipe_id"] for item in binding_recipes] != [
        f"TRACE-BIND-{sid}" for sid in expected_sids
    ]:
        raise ValueError("trace binding recipes are not an exact S00-S14 sequence")
    if [item["trace"] for item in binding_recipes] != [
        f"traces/reference_run/{sid}.trace.json" for sid in expected_sids
    ]:
        raise ValueError("trace binding paths are not an exact S00-S14 sequence")
    if any("S15" in canonical_json(item) for item in binding_recipes):
        raise ValueError("S15 must not have a modulation-trace binding recipe")
    if template["execution_or_materialization_claimed"] is not False:
        raise ValueError("trace template prematurely claims materialization")
    binding_fields = set(template["binding_recipe_contract"]["required_fields"])
    if any(set(item) != binding_fields for item in binding_recipes):
        raise ValueError("trace binding recipe violates its closed field set")
    expected_projection_bindings = {
        "diagnostics": "result#/diagnostics",
        "disposition": "result#/disposition",
        "evaluation_time": "result#/evaluation_time",
        "output": "result#/output",
        "scenario_id": "result#/scenario_id",
    }
    if projection["projection_bindings"] != expected_projection_bindings:
        raise ValueError("trace result projection does not bind the five required result pointers")
    bl_supports = [dec("T03-BL-006")]
    rs_supports = [dec("T03-RS-005")]
    tm_supports = [dec("T03-TM-004")]
    ct_supports = [dec("T03-CT-009")]
    qa_supports = [dec("T03-QA-011")]
    rp_supports = [dec("T03-RP-012")]
    mp_supports = [dec("T03-MP-013")]

    def joined(*groups: Sequence[tuple[str, str, str, str]]) -> list[tuple[str, str, str, str]]:
        return [support for group in groups for support in group]

    # The schema is split at semantic boundaries.  This prevents a decision
    # about, for example, diagnostic priority from being represented as support
    # for an unrelated formula or source-field shape.
    schema_entries: list[
        tuple[str, str, Any, Sequence[tuple[str, str, str, str]]]
    ] = [
        ("/$schema", "$schema", schema_seed["$schema"], joined(qa_supports, rp_supports)),
        ("/$id", "$id", schema_seed["$id"], joined(qa_supports, rp_supports)),
        ("/title", "title", schema_seed["title"], qa_supports),
        ("/description", "description", schema_seed["description"], qa_supports),
        ("/type", "type", schema_seed["type"], qa_supports),
        (
            "/additionalProperties",
            "additionalProperties",
            schema_seed["additionalProperties"],
            qa_supports,
        ),
        ("/required", "required", schema_seed["required"], qa_supports),
    ]
    schema_property_supports = {
        "$schema": joined(qa_supports, rp_supports),
        "schema_version": joined(qa_supports, rp_supports),
        "scenario_id": joined(bl_supports, qa_supports),
        "evaluation_time": joined(bl_supports, tm_supports, qa_supports),
        "disposition": joined(ct_supports, qa_supports),
        "diagnostics": joined(ct_supports, qa_supports),
        "trace_core": qa_supports,
        "trace_id": joined(qa_supports, rp_supports),
    }
    for key, value in schema_seed["properties"].items():
        escaped = key.replace("~", "~0").replace("/", "~1")
        schema_entries.append(
            (
                f"/properties/{escaped}",
                f"properties.{key}",
                value,
                schema_property_supports[key],
            )
        )
    schema_definition_supports = {
        "decimal_string": joined(qa_supports, rp_supports),
        "event": joined(bl_supports, qa_supports),
        "factor_state": joined(bl_supports, tm_supports, ct_supports, qa_supports),
        "appraisal_vector": joined(bl_supports, rs_supports, qa_supports, rp_supports),
        "policy": joined(tm_supports, ct_supports, qa_supports, rp_supports),
        "mask": joined(rs_supports, qa_supports),
        "formula_record": joined(rs_supports, qa_supports, rp_supports),
        "classification_record": joined(rs_supports, qa_supports),
        "versions": joined(qa_supports, rp_supports),
        "trace_core": qa_supports,
    }
    for key, value in schema_seed["$defs"].items():
        escaped = key.replace("~", "~0").replace("/", "~1")
        schema_entries.append(
            (
                f"/$defs/{escaped}",
                f"definitions.{key}",
                value,
                schema_definition_supports[key],
            )
        )
    for index, (locator, field, value, supports) in enumerate(schema_entries):
        derivation_id = (
            "DL-TRACE-SCHEMA"
            if index == 0
            else f"DL-TRACE-SCHEMA-ATOM-{index:02d}"
        )
        builder.add(
            derivation_id,
            "schemas/trace.schema.json",
            locator,
            field,
            value,
            purpose="Proyectar atómicamente el esquema cerrado de trazas aprobado antes de ejecutar.",
            object_refs="TRACE-CONTRACT-1.0.0|ME-FAT-INFRA6-1.0.0",
            supports=supports,
            parent="DL-REP-007" if index == 0 else "DL-TRACE-SCHEMA",
            transformation_type="automatic_derivation",
            transformation="Proyección determinista del seed normativo; no afirma una ejecución ni una traza.",
            m_refs="M4|M5|M6",
        )

    # The result projection is likewise split so that baseline, diagnostics and
    # canonicalization authorities remain distinguishable in the audit graph.
    projection_root = "/trace_result_projection_contract"
    projection_entries: list[
        tuple[str, str, Any, Sequence[tuple[str, str, str, str]]]
    ] = [
        (f"{projection_root}/contract_id", "contract_id", projection["contract_id"], qa_supports),
        (f"{projection_root}/purpose", "purpose", projection["purpose"], qa_supports),
        (f"{projection_root}/scope", "scope", projection["scope"], joined(bl_supports, qa_supports)),
        (
            f"{projection_root}/source_validation_precondition",
            "source_validation_precondition",
            projection["source_validation_precondition"],
            joined(qa_supports, rp_supports),
        ),
        (
            f"{projection_root}/required_source_pointers",
            "required_source_pointers",
            projection["required_source_pointers"],
            joined(qa_supports, rp_supports),
        ),
    ]
    projection_schema = projection["projection_schema"]
    for key in ("type", "additionalProperties", "required"):
        projection_entries.append(
            (
                f"{projection_root}/projection_schema/{key}",
                f"projection_schema.{key}",
                projection_schema[key],
                qa_supports,
            )
        )
    for key in ("scenario_id", "evaluation_time"):
        projection_entries.append(
            (
                f"{projection_root}/projection_schema/properties/{key}",
                f"projection_schema.properties.{key}",
                projection_schema["properties"][key],
                joined(bl_supports, qa_supports),
            )
        )
    for key in ("disposition", "diagnostics"):
        projection_entries.append(
            (
                f"{projection_root}/projection_schema/properties/{key}",
                f"projection_schema.properties.{key}",
                projection_schema["properties"][key],
                joined(ct_supports, qa_supports),
            )
        )
    output_schema = projection_schema["properties"]["output"]
    for key in ("type", "additionalProperties", "required"):
        projection_entries.append(
            (
                f"{projection_root}/projection_schema/properties/output/{key}",
                f"projection_schema.properties.output.{key}",
                output_schema[key],
                joined(bl_supports, qa_supports, rp_supports),
            )
        )
    for key, value in output_schema["properties"].items():
        projection_entries.append(
            (
                f"{projection_root}/projection_schema/properties/output/properties/{key}",
                f"projection_schema.properties.output.properties.{key}",
                value,
                joined(bl_supports, qa_supports, rp_supports),
            )
        )
    for key, value in projection["projection_bindings"].items():
        projection_entries.append(
            (
                f"{projection_root}/projection_bindings/{key}",
                f"projection_bindings.{key}",
                value,
                joined(qa_supports, rp_supports),
            )
        )
    equality_supports = {
        "scenario_id": joined(bl_supports, qa_supports),
        "evaluation_time": joined(bl_supports, qa_supports),
        "disposition": joined(ct_supports, qa_supports),
        "diagnostics": joined(ct_supports, qa_supports),
        "output": joined(bl_supports, qa_supports, rp_supports),
    }
    for key, value in projection["cross_source_equality"].items():
        projection_entries.append(
            (
                f"{projection_root}/cross_source_equality/{key}",
                f"cross_source_equality.{key}",
                value,
                equality_supports[key],
            )
        )
    for key in ("data_origin_rule", "runtime_authority_rule"):
        projection_entries.append(
            (
                f"{projection_root}/{key}",
                key,
                projection[key],
                joined(qa_supports, rp_supports),
            )
        )
    projection_entries.append(
        (
            f"{projection_root}/failure_policy",
            "failure_policy",
            projection["failure_policy"],
            joined(ct_supports, qa_supports, rp_supports),
        )
    )
    for index, (locator, field, value, supports) in enumerate(projection_entries):
        derivation_id = (
            "DL-TRACE-RESULT-PROJECTION-001"
            if index == 0
            else f"DL-TRACE-RESULT-PROJECTION-ATOM-{index:02d}"
        )
        builder.add(
            derivation_id,
            "spec/decisions/engineering_v1.1.0.json",
            locator,
            field,
            value,
            purpose="Congelar atómicamente la proyección cerrada de cinco valores observados desde cada resultado validado.",
            object_refs="TRACE-CONTRACT-1.0.0|ME-FAT-INFRA6-1.0.0",
            supports=supports,
            parent="DL-REP-007" if index == 0 else "DL-TRACE-RESULT-PROJECTION-001",
            transformation_type="engineering_decision",
            transformation="Los valores se seleccionan del resultado tras ejecución; el oráculo sólo valida igualdad.",
            m_refs="M4|M5|M6",
        )
    template_supports = joined(
        bl_supports,
        rs_supports,
        tm_supports,
        ct_supports,
        qa_supports,
        rp_supports,
        mp_supports,
    )
    builder.add(
        "DL-TRACE-TEMPLATE-001",
        "spec/decisions/engineering_v1.1.0.json",
        "/trace_materialization/template",
        "trace.materialization_template",
        template,
        purpose="Congelar una plantilla compartida que determina wrapper y nueve componentes de trace_core.",
        object_refs="TRACE-CONTRACT-1.0.0|TRACES-15",
        supports=template_supports,
        parent="DL-TRACE-RESULT-PROJECTION-001",
        transformation_type="engineering_decision",
        transformation="La plantilla fija autoridades, valores y nulabilidad sin afirmar una corrida.",
        m_refs="M4|M5|M6",
    )
    binding_supports = [
        dec("T03-QA-011"),
        dec("T03-RP-012"),
        dec("T03-MP-013"),
    ]
    for index, (sid, binding) in enumerate(zip(expected_sids, binding_recipes, strict=True)):
        builder.add(
            f"DL-TRACE-BINDING-{sid}",
            "spec/decisions/engineering_v1.1.0.json",
            f"/trace_materialization/binding_recipes/{index}",
            f"trace.materialization_binding.{sid}",
            binding,
            purpose="Vincular de forma uno-a-uno escenario, oráculo, resultado, esquema y traza.",
            object_refs="TRACE-CONTRACT-1.0.0|TRACES-15",
            supports=binding_supports,
            parent="DL-TRACE-TEMPLATE-001",
            transformation_type="engineering_decision",
            transformation="El binding sólo referencia entradas y salidas canónicas; no contiene un resultado observado.",
            m_refs="M4|M5|M6",
        )
        builder.add(
            f"DL-REC-TRACE-{sid}",
            binding["trace"],
            "@materialization-recipe",
            f"trace.materialization_recipe.{sid}",
            binding,
            purpose="Materializar la traza sólo después de validar escenario, resultado y oráculo.",
            object_refs="TRACE-CONTRACT-1.0.0|TRACES-15",
            supports=binding_supports,
            parent=f"DL-TRACE-BINDING-{sid}",
            transformation_type="automatic_derivation",
            transformation="Receta diferida y unívoca; no afirma que la traza ni su hash ya existan.",
            m_refs="M4|M5|M6",
        )


def build_contract_documents(builder: LedgerBuilder) -> dict[str, dict[str, Any]]:
    """Return the recipe, topology and explicitly unexecuted record template."""
    mp = builder.decisions["T03-MP-013"]["decision"]
    recipe = {
        "$schema": "../schemas/build_recipe.schema.json",
        "schema_version": "1.0.0",
        "recipe_id": mp["recipe_id"],
        "recipe_path": mp["recipe_path"],
        "status": mp["status"],
        "source_manifest_path": mp["source_manifest_path"],
        "topology_path": mp["topology_path"],
        "build_record_path": mp["build_record_path"],
        "required_executable_binding_map": deepcopy(mp["required_executable_binding_map"]),
        "binding_artifacts": deepcopy(mp["binding_artifacts"]),
        "binding_coverage_rule": mp["binding_coverage_rule"],
        "generator_registry": deepcopy(mp["generator_registry"]),
        "validator_registry": deepcopy(mp["validator_registry"]),
        "planned_commands": deepcopy(mp["planned_commands"]),
        "pre_run_source_manifest_gate": deepcopy(mp["pre_run_source_manifest_gate"]),
        "coverage_contract": deepcopy(mp["coverage_contract"]),
        "build_order": deepcopy(mp["build_order"]),
        "failure_policy": mp["failure_policy"],
        "manual_editing_of_derived_nodes": mp["manual_editing_of_derived_nodes"],
    }
    topology = {
        "$schema": "../schemas/generation_topology.schema.json",
        "schema_version": "1.0.0",
        "topology_id": "TOPOLOGY-IFM6-1.1.0-CANDIDATE-001",
        "status": mp["status"],
        "recipe_path": mp["recipe_path"],
        "source_manifest_path": mp["source_manifest_path"],
        "build_record_path": mp["build_record_path"],
        "dag": deepcopy(mp["dag"]),
        "acyclicity_rules": deepcopy(mp["acyclicity_rules"]),
        "build_order": deepcopy(mp["build_order"]),
        "failure_policy": mp["failure_policy"],
        "manual_editing_of_derived_nodes": mp["manual_editing_of_derived_nodes"],
    }
    validator_registry = deepcopy(mp["validator_registry"])
    validator_registry["execution_status"] = "planned_not_run"
    for validator in validator_registry["validators"]:
        validator["execution_status"] = "not_run"
        validator["exit_code"] = None
    record_template = {
        "$schema": "../schemas/build_record.schema.json",
        "schema_version": "1.0.0",
        "record_id": "BUILD-RECORD-IFM6-1.1.0-CANDIDATE-001",
        "recipe_id": mp["recipe_id"],
        "recipe_path": mp["recipe_path"],
        "status": "planned_not_executed",
        "required_fields": deepcopy(mp["derived_record_requirements"]),
        "validator_registry": validator_registry,
        "prohibited_content": [
            "final manifest hash",
            "ZIP hash",
            "wall-clock timestamp",
            "duration",
        ],
        "manual_editing_of_derived_nodes": mp["manual_editing_of_derived_nodes"],
    }
    return {
        mp["recipe_path"]: recipe,
        mp["topology_path"]: topology,
        mp["build_record_path"]: record_template,
    }


def add_build_contract_rows(builder: LedgerBuilder) -> None:
    """Register authored build contracts and an explicitly unexecuted record template."""
    mp = builder.decisions["T03-MP-013"]["decision"]
    documents = build_contract_documents(builder)
    for base, path, document, purpose in [
        (
            "DL-BUILD-RECIPE",
            mp["recipe_path"],
            documents[mp["recipe_path"]],
            "Fijar atómicamente la receta normativa, aún no ejecutada.",
        ),
        (
            "DL-TOPOLOGY-CONTRACT",
            mp["topology_path"],
            documents[mp["topology_path"]],
            "Fijar atómicamente el DAG normativo y sus reglas de aciclicidad.",
        ),
        (
            "DL-BUILD-RECORD-TEMPLATE",
            mp["build_record_path"],
            documents[mp["build_record_path"]],
            "Fijar una plantilla de registro sin hashes, tiempos, resultados ni códigos observados.",
        ),
    ]:
        add_atomic_document(
            builder,
            base_derivation_id=base,
            target_path=path,
            document=document,
            supports=[dec("T03-MP-013"), dec("T03-RP-012")],
            parent="DL-SCOPE-001",
            claim_ref="LIM-EVIDENCE-001",
            purpose=purpose,
        )


def add_schema_contract_rows(builder: LedgerBuilder) -> None:
    """Register every T03.3-5 schema as a closed ledger projection."""
    documents = schema_documents(builder)
    support_map: dict[str, list[tuple[str, str, str, str]]] = {
        "schemas/provenance.schema.json": [
            dec("T03-QG-014"),
            dec("T03-RP-012"),
            dec("T03-MP-013"),
        ],
        "schemas/config.schema.json": [
            dec("T03-RS-005"),
            dec("T03-CT-009"),
            dec("T03-RP-012"),
            dec("T03-MP-013"),
        ],
        "schemas/scenario.schema.json": [
            dec("T03-BL-006"),
            dec("T03-CT-009"),
            dec("T03-QA-011"),
            dec("T03-RP-012"),
        ],
        "schemas/oracle.schema.json": [
            dec("T03-BL-006"),
            dec("T03-RS-005"),
            dec("T03-CT-009"),
            dec("T03-QA-011"),
            dec("T03-RP-012"),
        ],
        "schemas/scenario_catalog.schema.json": [
            dec("T03-BL-006"),
            dec("T03-QA-011"),
        ],
        "schemas/oracle_catalog.schema.json": [
            dec("T03-BL-006"),
            dec("T03-QA-011"),
            dec("T03-RP-012"),
        ],
        "schemas/test_catalog.schema.json": [dec("T03-QA-011")],
        "schemas/result.schema.json": [
            dec("T03-BL-006"),
            dec("T03-CT-009"),
            dec("T03-QA-011"),
            dec("T03-RP-012"),
        ],
        "schemas/rejection.schema.json": [
            dec("T03-CT-009"),
            dec("T03-QA-011"),
            dec("T03-MP-013"),
        ],
        "schemas/formula_bindings.schema.json": [
            dec("T03-RS-005"),
            dec("T03-RP-012"),
            dec("T03-MP-013"),
        ],
        "schemas/build_recipe.schema.json": [
            dec("T03-RP-012"),
            dec("T03-MP-013"),
        ],
        "schemas/generation_topology.schema.json": [
            dec("T03-RP-012"),
            dec("T03-MP-013"),
        ],
        "schemas/build_record.schema.json": [
            dec("T03-RP-012"),
            dec("T03-MP-013"),
        ],
        "schemas/qa_verdict.schema.json": [
            dec("T03-QG-014"),
            dec("T03-RP-012"),
        ],
    }
    if set(support_map) != MATERIALIZED_SCHEMA_PATHS - {
        "schemas/trace.schema.json"
    }:
        raise ValueError("schema support registry is incomplete")
    for path in sorted(support_map):
        slug = path.removeprefix("schemas/").removesuffix(".schema.json")
        base = f"DL-SCHEMA-{re.sub(r'[^A-Za-z0-9]+', '-', slug).strip('-').upper()}"
        add_atomic_document(
            builder,
            base_derivation_id=base,
            target_path=path,
            document=documents[path],
            supports=support_map[path],
            parent="DL-SCOPE-001",
            claim_ref="LIM-EVIDENCE-001",
            purpose=(
                "Materializar un contrato JSON Schema Draft 2020-12 cerrado y "
                "trazable antes de implementar el código ejecutable."
            ),
            transformation_type="automatic_derivation",
        )


def artifact_minimums() -> list[tuple[str, str, str, list[str], list[str], str]]:
    return [
        (
            "DL-ART-MIN-001",
            "artifacts/01_PF-FAT-1.0.0.md",
            "DL-ART-001",
            ["identity", "operational_definition", "construct_boundary", "state", "neutrality", "confidence", "temporality", "freshness", "failures", "governance", "limits", "traceability"],
            [
                "DL-FST-001", "DL-FST-002", "DL-FST-003", "DL-FST-004",
                "DL-FST-005", "DL-FST-006", "DL-FST-007",
                "DL-FST-CONFIDENCE-DOMAIN-001",
                "DL-FST-CONFIDENCE-TYPE-001",
                "DL-FST-008", "DL-FST-009", "DL-FST-010", "DL-FST-011",
                "DL-FST-012", "DL-FST-013", "DL-FST-014", "DL-FST-015",
                "DL-FST-016", "DL-LIM-003",
            ],
            "M1|M6",
        ),
        (
            "DL-ART-MIN-002",
            "artifacts/02_PA-INFRA6-1.0.0.md",
            "DL-ART-002",
            ["identity_and_provenance", "six_variables", "doctoral_order", "published_semantics", "doctoral_domain", "baseline", "ga_ef_boundary", "published_rules", "adapters", "interfaces", "restrictions"],
            [
                "DL-HST-001", "DL-HST-002", "DL-HST-003", "DL-HST-004",
                "DL-HST-PUB-005", "DL-HST-PUB-006", "DL-HST-PUB-007",
                "DL-HST-PUB-008", "DL-HST-PUB-009", "DL-HST-PUB-010",
                "DL-HST-PUB-GAEF-2018A-PRODUCER",
                "DL-HST-PUB-GAEF-2018A-BOUNDARY",
                "DL-HST-PUB-GAEF-2018B-PRODUCER",
                "DL-HST-PUB-GAEF-2018B-BOUNDARY",
                "DL-HST-011", "DL-HST-012", "DL-HST-013", "DL-HST-014",
                "DL-HST-015", "DL-HST-016",
                "DL-HST-BND-SOURCE-MAP-2018A", "DL-HST-BND-SOURCE-MAP-2018B",
                "DL-HST-BND-SOURCE-MAP-POLICY-001",
                "DL-LX-SOURCE-MAP-2018A", "DL-LX-SOURCE-MAP-2018B",
                "DL-LX-SOURCE-MAP-POLICY-001", "DL-RUL-SELECT-001",
            ],
            "M2|M6",
        ),
        (
            "DL-ART-MIN-003",
            "artifacts/03_MFV-FAT-COP-1.0.0.md",
            "DL-ART-003",
            ["factor", "appraisal", "perspective", "authorized_variable", "protected_variables", "mask", "preconditions", "postconditions", "prohibitions"],
            ["DL-FST-002", "DL-MAP-001", "DL-MAP-002", "DL-MAP-003"],
            "M3|M6",
        ),
        (
            "DL-ART-MIN-004",
            "artifacts/04_MI-FAT-COP-1.0.0.md",
            "DL-ART-004",
            ["formula", "bindings", "parameter", "projection", "domain", "neutrality", "monotonicity", "temporality", "abstention", "coping_partition", "transfer_limits"],
            ["DL-MOD-001", "DL-MOD-002", "DL-MOD-003", "DL-MOD-004", "DL-MOD-005", "DL-BIND-001", "DL-BIND-002", "DL-BIND-003", "DL-BIND-004", "DL-FST-011", "DL-FST-012", "DL-FST-013", "DL-FST-014", "DL-CAT-001", "DL-CAT-002", "DL-CAT-003", "DL-CAT-004"],
            "M3|M6",
        ),
        (
            "DL-ART-MIN-005",
            "artifacts/05_MOD-FAT-COP-1.0.0_IF-GA-EF-1.0.0.md",
            "DL-ART-005",
            ["modules", "api", "flow", "validation", "diagnostics", "modulation", "classification_before_after", "traces", "rejection", "commands", "execution_status"],
            [
                "DL-BIND-RESOLVED-001", "DL-BIND-RESOLVED-002",
                "DL-BIND-RESOLVED-003", "DL-BIND-RESOLVED-004",
                "DL-RUL-SELECT-001", "DL-DIAG-AGGREGATION-001", "DL-REP-007",
                "DL-TRACE-SCHEMA", "DL-TRACE-RESULT-PROJECTION-001",
                "DL-TRACE-TEMPLATE-001",
                *[f"DL-TRACE-BINDING-S{index:02d}" for index in range(15)],
            ],
            "M3|M6",
        ),
        (
            "DL-ART-MIN-006",
            "artifacts/06_CI-FAT-INFRA6-1.0.0.md",
            "DL-ART-006",
            ["data_contract", "semantic_contract", "preconditions", "postconditions", "validation_order", "failures", "diagnostics", "tolerance", "versions", "acceptance_criteria"],
            [
                "DL-HST-004", "DL-HST-014", "DL-HST-016", "DL-FST-006",
                "DL-FST-007", "DL-FST-CONFIDENCE-DOMAIN-001",
                "DL-FST-CONFIDENCE-TYPE-001", "DL-FST-008", "DL-FST-009", "DL-FST-010",
                "DL-FST-011", "DL-FST-012", "DL-FST-013", "DL-FST-014",
                "DL-FST-015", "DL-FST-016", "DL-DIAG-AGGREGATION-001",
                "DL-MOD-005", "DL-TRACE-SCHEMA",
                "DL-TRACE-RESULT-PROJECTION-001",
            ],
            "M4|M6",
        ),
        (
            "DL-ART-MIN-007",
            "artifacts/07_ME-FAT-INFRA6-1.0.0.md",
            "DL-ART-007",
            ["purpose", "scenarios_16", "oracles_16", "results_16", "traces_15", "rejection_1", "tests_18", "invariants", "judgement_rules", "evidence_limits", "execution_status"],
            [
                "DL-EVAL-001", "DL-EVAL-002", "DL-EVAL-003", "DL-EVAL-004",
                "DL-LIM-001", "DL-LIM-002", "DL-LIM-003", "DL-LIM-004",
                "DL-TRACE-SCHEMA", "DL-TRACE-RESULT-PROJECTION-001",
                "DL-TRACE-TEMPLATE-001",
                *[f"DL-TRACE-BINDING-S{index:02d}" for index in range(15)],
                *[f"DL-REC-TRACE-S{index:02d}" for index in range(15)],
            ],
            "M5|M6",
        ),
    ]


def add_artifact_minimums(builder: LedgerBuilder) -> None:
    for derivation_id, path, parent, sections, sources, levels in artifact_minimums():
        status_gate = "pending_reference_run" if derivation_id in {"DL-ART-MIN-005", "DL-ART-MIN-007"} else "specification_review"
        builder.add(
            derivation_id,
            path,
            "@minimum-content",
            "artifact.minimum_content",
            {
                "epistemic_status": "new_materialization_not_recovered_historical_bytes",
                "render": "markdown",
                "required_front_matter": ["artifact_id", "artifact_version", "package_id", "package_version", "origin_class", "status", "source_derivations"],
                "required_sections": sections,
                "source_derivations": sources,
                "status_gate": status_gate,
            },
            purpose="Fijar contenido mínimo suficiente para materializar el artefacto sin conocimiento tácito.",
            object_refs=path.rsplit("/", 1)[-1].replace(".md", ""),
            supports=[dec("T03-MP-013")],
            parent=parent,
            transformation="La receta no permite declarar el artefacto ejecutado ni verificado antes de la corrida correspondiente.",
            m_refs=levels,
        )


def recipe_id(path: str) -> str:
    result_match = re.fullmatch(r"results/reference_run/(S\d{2})\.result\.json", path)
    trace_match = re.fullmatch(r"traces/reference_run/(S\d{2})\.trace\.json", path)
    if result_match:
        return f"DL-REC-RESULT-{result_match.group(1)}"
    if trace_match:
        return f"DL-REC-TRACE-{trace_match.group(1)}"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-").upper()
    return f"DL-REC-{slug}"


def recipe_for_path(path: str, mp: Mapping[str, Any]) -> dict[str, Any]:
    result_match = re.fullmatch(r"results/reference_run/(S\d{2})\.result\.json", path)
    trace_match = re.fullmatch(r"traces/reference_run/(S\d{2})\.trace\.json", path)
    if result_match:
        sid = result_match.group(1)
        recipe = {
            "action": "execute_and_compare",
            "compare_to": f"oracles/{sid}.expected.json",
            "runner": "scripts/run_scenarios.py",
            "scenario": f"scenarios/{sid}.json",
            "schema": "schemas/result.schema.json",
            "status_before_run": "not_observed",
        }
        if sid == "S15":
            recipe.update(
                {
                    "expected_disposition": "rejected",
                    "expected_output_contract": {"exists": False},
                    "rejection_record": "traces/reference_run/rejections/S15.rejection.json",
                }
            )
        return recipe
    if trace_match:
        sid = trace_match.group(1)
        return {
            "action": "emit_after_non_rejected_execution",
            "result": f"results/reference_run/{sid}.result.json",
            "scenario": f"scenarios/{sid}.json",
            "schema": "schemas/trace.schema.json",
            "status_before_run": "not_observed",
            "trace_id_policy": "T03-RP-012",
        }
    if path == "PROVENANCE.json":
        return {"action": "preserve_and_validate", "instance": path, "schema": "schemas/provenance.schema.json", "write_mode": "atomic"}
    if path == "sources/SOURCES.json":
        return {"action": "preserve_and_validate", "instance": path, "schema": "schemas/sources.schema.json", "write_mode": "atomic"}
    if path == "VERSION":
        return {"action": "write_exact_text", "content": "1.1.0\n", "encoding": "UTF-8", "line_endings": "LF"}
    if path == "manifests/SOURCE_SHA256.txt":
        gate = mp["pre_run_source_manifest_gate"]
        return {
            "action": "build_and_verify_pre_run_source_manifest",
            "builder": "scripts/build_source_manifest.py",
            "build_command": gate["build_command"],
            "failure_policy": gate["failure_policy"],
            "manifest": path,
            "source_builder_inclusion": gate["source_builder_inclusion"],
            "stage": gate["stage"],
            "status_before_run": gate["status"],
            "verify_command": gate["verify_command"],
            "write_mode": "atomic",
        }
    if path == "MANIFIESTO_SHA256.txt":
        return {"action": "generate_sha256_manifest", "exclude": ["MANIFIESTO_SHA256.txt", "dist/"], "ordering": "UTF-8_bytewise_path", "timing": "after_all_internal_files"}
    if path == "CITATION.cff":
        return {
            "action": "render_minimal_cff_after_author_decision",
            "excluded_until_T05": ["contact", "doi", "license", "orcid", "repository_url"],
            "required_decision": "T03-CIT-015",
            "write_before_resolution": False,
        }
    if path.startswith(("results/", "traces/", "logs/", "environment/")):
        return {"action": "derive_after_reference_run", "path": path, "run_id": "RUN-T03-REFERENCE-001", "status_before_run": "not_observed", "write_mode": "atomic"}
    if path.startswith("schemas/"):
        return {"action": "materialize_json_schema", "draft": "2020-12", "path": path, "source": "registered_derivations", "write_mode": "atomic"}
    if path.endswith(".py"):
        return {"action": "materialize_python_source", "path": path, "runtime_dependencies": "standard_library_only", "source": "registered_derivations", "write_mode": "atomic"}
    if path.endswith(".json"):
        return {"action": "materialize_canonical_json", "path": path, "source": "registered_derivations", "write_mode": "atomic"}
    if path.endswith(".md"):
        return {"action": "render_markdown", "path": path, "source": "registered_derivations", "write_mode": "atomic"}
    return {"action": "materialize_from_registered_derivations", "path": path, "write_mode": "atomic"}


def add_missing_path_recipes(builder: LedgerBuilder) -> None:
    covered = {row["target_path"] for row in builder.rows}
    existing_json_atoms = {
        "PROVENANCE.json": "/schema_version",
        "sources/SOURCES.json": "/schema_version",
        "schemas/derivation_ledger.schema.json": "/schema_version",
        "schemas/sources.schema.json": "/$id",
    }
    mp = builder.decisions["T03-MP-013"]["decision"]
    for path in builder.planned_paths:
        if path in covered:
            continue
        citation_authorized = (
            path == "CITATION.cff" and "T03-CIT-015" in builder.decisions
        )
        blocked = path == "CITATION.cff" and not citation_authorized
        support = (
            [dec("T03-CIT-015")]
            if citation_authorized
            else ([] if blocked else [dec("T03-MP-013")])
        )
        status = "blocked" if blocked else "planned"
        material_refs = ""
        locator = "@materialization-recipe"
        field = "file.materialization_recipe"
        value: Any = None if blocked else recipe_for_path(path, mp)
        if not blocked and (builder.root / path).exists() and not path.startswith(("results/", "traces/", "logs/", "environment/")):
            status = "materialized_t03"
            material_refs = path
            if path.endswith(".json") and path in existing_json_atoms:
                locator = existing_json_atoms[path]
                field = "file.materialized_identity"
                document = json.loads((builder.root / path).read_text(encoding="utf-8"))
                value = document[locator[1:]]
        builder.add(
            recipe_id(path),
            path,
            locator,
            field,
            value,
            purpose=(
                "Mantener CITATION.cff bloqueado hasta una decisión explícita de autoría mínima."
                if blocked
                else "Fijar una receta determinista para la ruta sin atribuir resultados observados."
            ),
            object_refs="FILE-MATERIALIZATION-RECIPE",
            supports=support,
            parent="",
            transformation="La receta autoriza construcción futura y separa esperado, ejecución y verificación.",
            effect="Cierra la cobertura de rutas del paquete M6 sin fabricar evidencia.",
            limits=(
                "Requiere T03-CIT-015; no se escribe identidad de citación por inferencia."
                if blocked
                else "La existencia de la receta no acredita que la ruta haya sido generada, ejecutada o verificada."
            ),
            approvals=(
                ("T05-IP-001",)
                if blocked
                else (("T03-CIT-015",) if citation_authorized else ("T03-MP-013",))
            ),
            materialization_status=status,
            materialization_refs=material_refs,
            claim_class="pending_verification" if blocked else "generated_for_doctoral_instance",
        )
        covered.add(path)


def register_t03_3_6_code_materialization(
    builder: LedgerBuilder,
) -> dict[str, dict[str, Any]]:
    """Register the exact authored implementation/test set without executing it."""
    declared = set(builder.planned_paths)
    if not T03_3_6_CODE_PATHS <= declared:
        missing = sorted(T03_3_6_CODE_PATHS - declared)
        raise ValueError(f"T03.3-6 code paths are not declared: {missing}")
    present = {
        path for path in T03_3_6_CODE_PATHS if (builder.root / path).is_file()
    }
    if present and present != T03_3_6_CODE_PATHS:
        missing = sorted(T03_3_6_CODE_PATHS - present)
        raise ValueError(f"partial T03.3-6 code materialization: {missing}")
    if not present:
        return {}

    report: dict[str, dict[str, Any]] = {}
    for path in sorted(present):
        raw = (builder.root / path).read_bytes()
        report[path] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    for row in builder.rows:
        if (
            row["target_path"] in present
            and row["materialization_status"] not in {"excluded", "superseded"}
        ):
            row["materialization_status"] = "materialized_t03"
            row["materialization_refs"] = row["target_path"]
    return report


def register_t03_3_7_executable_materialization(
    builder: LedgerBuilder,
) -> dict[str, dict[str, Any]]:
    """Register the exact ten-program infrastructure set without running tests."""
    declared = set(builder.planned_paths)
    if not T03_3_7_EXECUTABLE_PATHS <= declared:
        missing = sorted(T03_3_7_EXECUTABLE_PATHS - declared)
        raise ValueError(f"T03.3-7 executable paths are not declared: {missing}")
    present = {
        path for path in T03_3_7_EXECUTABLE_PATHS if (builder.root / path).is_file()
    }
    if present and present != T03_3_7_EXECUTABLE_PATHS:
        missing = sorted(T03_3_7_EXECUTABLE_PATHS - present)
        raise ValueError(f"partial T03.3-7 executable materialization: {missing}")
    if not present:
        return {}

    expected_registry = set(
        builder.decisions["T03-MP-013"]["decision"]["generator_registry"][
            "required_paths"
        ]
    )
    if expected_registry != T03_3_7_EXECUTABLE_PATHS:
        raise ValueError("T03.3-7 executable set diverges from T03-MP-013")
    report: dict[str, dict[str, Any]] = {}
    for path in sorted(present):
        raw = (builder.root / path).read_bytes()
        try:
            compile(raw.decode("utf-8"), path, "exec", dont_inherit=True)
        except (UnicodeDecodeError, SyntaxError) as exc:
            raise ValueError(f"invalid T03.3-7 executable {path}: {exc}") from exc
        report[path] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    for row in builder.rows:
        if (
            row["target_path"] in present
            and row["materialization_status"] not in {"excluded", "superseded"}
        ):
            row["materialization_status"] = "materialized_t03"
            row["materialization_refs"] = row["target_path"]
    return report


def register_source_manifest_materialization(
    builder: LedgerBuilder,
) -> dict[str, Any]:
    """Register an existing canonical source manifest before its final rebuild."""
    path = builder.root / SOURCE_MANIFEST_PATH
    if not path.is_file():
        return {}
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n") or b"\r" in raw:
        raise ValueError("SOURCE_SHA256.txt must be nonempty LF-terminated UTF-8")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("SOURCE_SHA256.txt is not UTF-8") from exc
    pattern = re.compile(r"^[0-9a-f]{64}  ([^\x00\r\n]+)$")
    members: list[str] = []
    for line in lines:
        match = pattern.fullmatch(line)
        if match is None:
            raise ValueError("SOURCE_SHA256.txt contains a malformed record")
        members.append(match.group(1))
    if members != sorted(members, key=lambda item: item.encode("utf-8")):
        raise ValueError("SOURCE_SHA256.txt records are not in UTF-8 byte order")
    if len(members) != len(set(members)):
        raise ValueError("SOURCE_SHA256.txt contains duplicate paths")
    if "scripts/build_source_manifest.py" not in members:
        raise ValueError("SOURCE_SHA256.txt omits its own builder")
    for row in builder.rows:
        if (
            row["target_path"] == SOURCE_MANIFEST_PATH
            and row["materialization_status"] != "superseded"
        ):
            row["materialization_status"] = "materialized_t03"
            row["materialization_refs"] = SOURCE_MANIFEST_PATH
    return {
        "bytes": len(raw),
        "records": len(lines),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def add_legacy_audit_rows(builder: LedgerBuilder) -> None:
    """Preserve any displaced input row under its original immutable identity."""
    for row_id in sorted(builder.legacy_row_ids - builder.used_row_ids):
        legacy = builder.legacy_rows[row_id]
        derivation_id = legacy.get("derivation_id", "")
        active_group = [row for row in builder.rows if row["derivation_id"] == derivation_id]
        if active_group:
            # A prior interrupted builder may have emitted redundant row IDs.
            # Keep their identity without creating a second semantic atom: they
            # become explicitly qualified support edges of the rebuilt group.
            fixed = dict(active_group[0])
            fixed["row_id"] = row_id
            support_type = legacy.get("support_ref_type", "")
            support_id = legacy.get("support_ref_id", "")
            if support_type == "approved_decision":
                support_id = canonical_decision_id(support_id)
            fixed["support_ref_type"] = support_type
            fixed["support_ref_id"] = support_id
            fixed["support_locator_or_decision"] = (
                f"SOURCES.json#{support_id}"
                if support_type == "evidence_unit"
                else f"PROVENANCE.json#decisions/{support_id}"
                if support_type == "approved_decision" and support_id
                else ""
            )
            used_levels = {
                row["support_level"]
                for row in active_group
                if row["support_ref_type"] == support_type
                and row["support_ref_id"] == support_id
            }
            fixed["support_level"] = next(
                (
                    level
                    for level in (
                        "direct",
                        "reported_by",
                        "interpreted",
                        "context_only",
                        "metadata_only",
                        "does_not_support",
                        "",
                    )
                    if level not in used_levels
                ),
                "metadata_only",
            )
            fixed["source_verification_status"] = (
                normalized_source_status(
                    builder.evidence.get(support_id, {}).get("verification_status")
                )
                if support_type == "evidence_unit"
                else "not_applicable"
            )
            builder.used_row_ids.add(row_id)
            builder.rows.append(fixed)
            continue
        fixed = builder.normalize_existing(legacy)
        fixed["materialization_status"] = "superseded"
        fixed["materialization_refs"] = ""
        fixed["reviewed_at_utc"] = builder.reviewed_at
        if fixed["transformation_type"] not in {
            "verbatim_short_fragment",
            "paraphrase",
            "lexical_adapter",
            "doctoral_synthesis",
            "engineering_decision",
            "metadata_transcription",
            "preserve_and_exclude",
            "automatic_derivation",
        }:
            fixed["transformation_type"] = "automatic_derivation"
        builder.used_row_ids.add(row_id)
        builder.rows.append(fixed)


def reconstruct_pointer_document(
    rows: Sequence[Mapping[str, str]], target_path: str
) -> dict[str, Any]:
    """Reconstruct a document only for QA; generated code never reads the ledger."""
    document: dict[str, Any] = {}
    selected = sorted(
        (
            row
            for row in rows
            if row["target_path"] == target_path
            and row["materialization_status"] != "superseded"
            and row["target_locator"].startswith("/")
        ),
        key=lambda row: row["target_locator"].encode("ascii"),
    )
    seen_locators: set[str] = set()
    # Multiple support rows for one derivation carry the same atom.  Collapse only
    # after asserting equality, thereby retaining every atomic support relation.
    by_locator: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in selected:
        by_locator[row["target_locator"]].append(row)
    for locator, group in by_locator.items():
        values = {row["target_value"] for row in group}
        if len(values) != 1:
            raise ValueError(f"conflicting atomic values at {target_path}#{locator}")
        if locator in seen_locators:
            raise ValueError(f"duplicate locator {target_path}#{locator}")
        seen_locators.add(locator)
        parts = [
            part.replace("~1", "/").replace("~0", "~")
            for part in locator[1:].split("/")
        ]
        if not parts or any(part == "" for part in parts):
            raise ValueError(f"invalid JSON pointer {target_path}#{locator}")
        cursor: Any = document
        for position, part in enumerate(parts):
            last = position == len(parts) - 1
            next_is_index = not last and parts[position + 1].isdigit()
            value = json.loads(next(iter(values))) if last else None
            if isinstance(cursor, dict):
                if last:
                    if part in cursor:
                        raise ValueError(f"pointer collision at {target_path}#{locator}")
                    cursor[part] = value
                else:
                    desired_type = list if next_is_index else dict
                    child = cursor.get(part)
                    if child is None:
                        child = desired_type()
                        cursor[part] = child
                    if not isinstance(child, desired_type):
                        raise ValueError(f"pointer collision at {target_path}#{locator}")
                    cursor = child
            elif isinstance(cursor, list) and part.isdigit():
                index = int(part)
                while len(cursor) <= index:
                    cursor.append(None)
                if last:
                    if cursor[index] is not None:
                        raise ValueError(f"pointer collision at {target_path}#{locator}")
                    cursor[index] = value
                else:
                    desired_type = list if next_is_index else dict
                    child = cursor[index]
                    if child is None:
                        child = desired_type()
                        cursor[index] = child
                    if not isinstance(child, desired_type):
                        raise ValueError(f"pointer collision at {target_path}#{locator}")
                    cursor = child
            else:
                raise ValueError(f"invalid array pointer at {target_path}#{locator}")
    return document


def validate_rows(builder: LedgerBuilder) -> dict[str, Any]:
    rows = builder.rows
    if not rows:
        raise ValueError("ledger is empty")
    if any(list(row) != HEADER for row in rows):
        raise ValueError("row dictionary does not follow the 32-column header")
    row_ids = [row["row_id"] for row in rows]
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("duplicate row_id")
    missing_legacy_row_ids = builder.legacy_row_ids - set(row_ids)
    if missing_legacy_row_ids:
        raise ValueError(
            f"legacy row IDs were lost: {sorted(missing_legacy_row_ids)}"
        )
    output_derivation_by_row = {row["row_id"]: row["derivation_id"] for row in rows}
    changed_legacy_derivations = {
        row_id: {
            "before": legacy["derivation_id"],
            "after": output_derivation_by_row.get(row_id),
        }
        for row_id, legacy in builder.legacy_rows.items()
        if output_derivation_by_row.get(row_id) != legacy["derivation_id"]
    }
    if changed_legacy_derivations:
        raise ValueError(
            f"legacy derivation identities changed: {changed_legacy_derivations}"
        )
    derivation_ids = {row["derivation_id"] for row in rows}
    source_statuses = {"verified", "pending", "failed", "not_applicable"}
    decision_statuses = {"approved", "pending", "rejected", "not_required", "superseded"}
    materialization_statuses = {
        "planned",
        "materialized_t03",
        "verified_t04",
        "blocked",
        "excluded",
        "superseded",
    }
    support_columns = {
        "row_id",
        "support_ref_type",
        "support_ref_id",
        "support_locator_or_decision",
        "support_level",
        "source_verification_status",
        "decision_approval_status",
    }
    by_derivation: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_derivation[row["derivation_id"]].append(row)
        json.loads(row["target_value"])
        if row["source_verification_status"] not in source_statuses:
            raise ValueError(f"invalid source_verification_status in {row['row_id']}")
        if row["decision_approval_status"] not in decision_statuses:
            raise ValueError(f"invalid decision_approval_status in {row['row_id']}")
        if row["materialization_status"] not in materialization_statuses:
            raise ValueError(f"invalid materialization_status in {row['row_id']}")
        if row["support_ref_type"] == "evidence_unit":
            if row["support_ref_id"] not in builder.evidence:
                raise ValueError(f"unresolved evidence: {row['support_ref_id']}")
            expected = normalized_source_status(
                builder.evidence[row["support_ref_id"]].get("verification_status")
            )
            if row["source_verification_status"] != expected:
                raise ValueError(f"wrong source status in {row['row_id']}")
        if row["support_ref_type"] == "approved_decision" and row["support_ref_id"] not in builder.decisions:
            raise ValueError(f"unresolved decision: {row['support_ref_id']}")
        for approval in split_refs(row["approval_refs"]):
            if approval not in builder.decisions and approval not in builder.open_decisions:
                raise ValueError(f"unresolved approval: {approval}")
        if row["claim_ref"] and row["claim_ref"] not in builder.claims:
            raise ValueError(f"unresolved claim: {row['claim_ref']}")
    for derivation_id, group in by_derivation.items():
        reference = {key: value for key, value in group[0].items() if key not in support_columns}
        for row in group[1:]:
            current = {key: value for key, value in row.items() if key not in support_columns}
            if current != reference:
                raise ValueError(f"semantic columns differ within {derivation_id}")
    explicit_source_groups = 0
    for derivation_id, group in by_derivation.items():
        active_group = [
            row
            for row in group
            if row["materialization_status"] not in {"excluded", "superseded"}
        ]
        if not active_group:
            continue
        if active_group[0]["claim_provenance_class"] == "explicit_source":
            explicit_source_groups += 1
            if not any(
                row["support_ref_type"] == "evidence_unit"
                and row["support_level"] == "direct"
                for row in active_group
            ):
                raise ValueError(
                    f"explicit-source group lacks direct evidence: {derivation_id}"
                )
    for row in rows:
        if row["parent_derivation_id"] and row["parent_derivation_id"] not in derivation_ids:
            raise ValueError(f"unresolved parent {row['parent_derivation_id']} in {row['row_id']}")

    planned = set(builder.planned_paths)
    targeted = {row["target_path"] for row in rows}
    if targeted != planned:
        raise ValueError(
            f"path coverage mismatch: missing={sorted(planned-targeted)}, extra={sorted(targeted-planned)}"
        )

    for row in rows:
        if row["target_path"].startswith("spec/published/"):
            if row["materialization_status"] in {"excluded", "superseded"}:
                continue
            if row["support_ref_type"] != "evidence_unit":
                raise ValueError(f"decision contamination in published layer: {row['row_id']}")
            if row["file_origin_class"] != "reconstructed_from_published_specification":
                raise ValueError(f"wrong published origin: {row['row_id']}")
            if row["approval_refs"] or row["decision_approval_status"] != "not_required":
                raise ValueError(f"approval contamination in published layer: {row['row_id']}")
            forbidden = ("canonical_name", "execution_policy", "decimal_string", '"domain"')
            if any(token in row["target_value"] for token in forbidden):
                raise ValueError(f"derived content in published layer: {row['row_id']}")
        if row["target_path"] == "spec/decisions/engineering_v1.1.0.json":
            if row["support_ref_type"] not in {"approved_decision", "evidence_unit"}:
                raise ValueError(f"invalid support in decision layer: {row['row_id']}")
    decision_derivations = {
        row["derivation_id"]
        for row in rows
        if row["target_path"] == "spec/decisions/engineering_v1.1.0.json"
        and row["materialization_status"] != "superseded"
    }
    for derivation_id in decision_derivations:
        if not any(
            row["support_ref_type"] == "approved_decision"
            for row in by_derivation[derivation_id]
        ):
            raise ValueError(f"decision-layer derivation lacks a decision: {derivation_id}")

    scenario_rows = {
        f"scenarios/S{index:02d}.json": reconstruct_pointer_document(
            rows, f"scenarios/S{index:02d}.json"
        )
        for index in range(16)
    }
    if any(not value for value in scenario_rows.values()):
        raise ValueError("the sixteen scenarios must be registered as atomic JSON pointers")
    for path, scenario in scenario_rows.items():
        sid = re.search(r"S\d{2}", path).group(0)
        if any(key in scenario for key in ("expected", "result", "trace")):
            raise ValueError(f"scenario {sid} is not input-only")
        required = {
            "scenario_id",
            "event",
            "fixture_class",
            "empirical_support",
            "evaluation_time",
            "baseline",
            "factor_state",
        }
        if not required.issubset(scenario):
            raise ValueError(f"scenario {sid} lacks {sorted(required-set(scenario))}")
        if scenario["scenario_id"] != sid:
            raise ValueError(f"scenario identifier mismatch in {path}")
        event = scenario["event"]
        if event != STABLE_SCENARIO_EVENT:
            raise ValueError(f"scenario {sid} does not have its stable event")
        permitted = required | ({"host_symbolic_payload"} if sid == "S14" else set())
        if set(scenario) != permitted:
            raise ValueError(f"scenario {sid} violates its closed top-level shape")
    bl = builder.decisions["T03-BL-006"]["decision"]
    if STABLE_SCENARIO_EVENT != bl["stable_conformance_event"]:
        raise ValueError("scenario event constant diverges from T03-BL-006")
    if (
        scenario_rows["scenarios/S14.json"]["host_symbolic_payload"]["source"]
        != bl["s14_symbolic_context"]
    ):
        raise ValueError("S14 symbolic source is not the exact T03-BL-006 context")

    oracle_rows = {
        f"oracles/S{index:02d}.expected.json": reconstruct_pointer_document(
            rows, f"oracles/S{index:02d}.expected.json"
        )
        for index in range(16)
    }
    if len(oracle_rows) != 16:
        raise ValueError("expected exactly sixteen scenario oracles")
    oracle_contract = bl["oracle_payload_policy"]["document_contract"]
    expected_semantics = oracle_contract["scenario_semantics"]
    required_outer = set(oracle_contract["required_outer_fields"])
    allowed_outer = set(oracle_contract["allowed_outer_fields"])
    if required_outer != allowed_outer:
        raise ValueError("oracle outer contract must be closed and fully required")
    for path, oracle in oracle_rows.items():
        sid = re.search(r"S\d{2}", path).group(0)
        if set(oracle) != required_outer:
            raise ValueError(f"oracle {sid} violates its closed outer contract")
        for key, value in oracle_contract["fixed_outer_values"].items():
            if oracle.get(key) != value:
                raise ValueError(f"oracle {sid} violates fixed outer value {key}")
        if oracle["scenario_id"] != sid or oracle["oracle_id"] != f"{sid}.expected":
            raise ValueError(f"oracle identity mismatch in {path}")
        if oracle["scenario_ref"] != f"scenarios/{sid}.json":
            raise ValueError(f"oracle scenario_ref mismatch in {path}")
        if not isinstance(oracle["calculation_basis"], dict) or not oracle["calculation_basis"]:
            raise ValueError(f"oracle {sid} lacks an explicit calculation basis")
        if not isinstance(oracle["provenance_refs"], list) or not oracle["provenance_refs"]:
            raise ValueError(f"oracle {sid} lacks provenance references")
        oracle_support_ids = {
            row["support_ref_id"]
            for row in rows
            if row["target_path"] == path
            and row["support_ref_type"] == "approved_decision"
            and row["materialization_status"] not in {"excluded", "superseded"}
        }
        if oracle_support_ids != set(oracle["provenance_refs"]):
            raise ValueError(f"oracle {sid} provenance_refs lack matching support edges")
        if oracle["expected"] != expected_semantics[sid]:
            raise ValueError(f"oracle {sid} diverges from frozen T03-BL-006 semantics")
        expected = expected_semantics[sid]
        output_contract = expected.get("output_contract")
        if sid == "S15":
            if output_contract != {"exists": False}:
                raise ValueError("S15 output_contract must be exactly {exists:false}")
        else:
            if not isinstance(output_contract, dict) or output_contract.get("exists") is not True:
                raise ValueError(f"oracle {sid} has no expected output contract")
            if output_contract.get("protected_dimensions") != "equal_to_scenario_baseline":
                raise ValueError(f"oracle {sid} lacks exact protected equality")
            output = output_contract.get("appraisal_vector")
            if not isinstance(output, dict) or set(output) != set(VECTOR_FIELDS):
                raise ValueError(f"oracle {sid} does not contain the full six-coordinate vector")
            if any(output[field] != PROTECTED_BASELINE[field] for field in PROTECTED_FIELDS):
                raise ValueError(f"oracle {sid} changes a protected coordinate")
    if oracle_rows["oracles/S05.expected.json"]["expected"]["output_contract"]["appraisal_vector"]["coping_potential"] != "0":
        raise ValueError("S05 must use the minimal decimal string 0")
    if oracle_rows["oracles/S06.expected.json"]["expected"]["output_contract"]["appraisal_vector"]["coping_potential"] != "1":
        raise ValueError("S06 must use the minimal decimal string 1")

    sadness_fixture_path, sadness_oracle_path = locate_sadness_paths(builder.planned_paths)
    sadness_fixture = reconstruct_pointer_document(rows, sadness_fixture_path)
    sadness_oracle = reconstruct_pointer_document(rows, sadness_oracle_path)
    rs_sadness = builder.decisions["T03-RS-005"]["decision"]["sadness_2018a"]
    bl_sadness = bl["independent_sadness_symbolic_regression"]
    qa = builder.decisions["T03-QA-011"]["decision"]
    isolated_oracle = qa["source_of_truth"]["oracle_index"]["isolated_oracle_exclusion"]
    ut14 = qa["test_catalog"]["document_seed"]["test_catalog"][13]
    if not (
        sadness_fixture_path
        == rs_sadness["required_fixture"]
        == bl_sadness["fixture"]
        == ut14["fixture_refs"][0]
        and sadness_oracle_path
        == rs_sadness["required_oracle"]
        == bl_sadness["oracle"]
        == isolated_oracle["path"]
        == ut14["oracle_path"]
    ):
        raise ValueError("symbolic sadness paths diverge across RS/BL/QA")
    if (
        bl_sadness["scenario_membership"] != "outside_S00-S15"
        or rs_sadness["execution_profile"] != "symbolic_regression_only"
        or bl_sadness["execution_profile"] != "isolated_symbolic_regression"
        or rs_sadness["numeric_pipeline_eligible"] is not False
    ):
        raise ValueError("symbolic sadness execution boundary is not frozen")
    expected_sadness_payload = {
        antecedent["field"]: antecedent["value"]
        for antecedent in SADNESS_ANTECEDENTS[1:]
    }
    expected_sadness_payload["Consequence (E)"] = "myself"
    expected_sadness_fixture = {
        "$schema": "../../schemas/scenario.schema.json",
        "schema_version": "1.0.0",
        "fixture_id": "sadness_2018a_symbolic",
        "event_context": {
            "cause_class": "unwanted_event_occurred",
            "consequence_target": "myself",
        },
        "fixture_class": "synthetic_symbolic_regression_fixture",
        "numeric_pipeline_input": False,
        "published_symbolic_payload": expected_sadness_payload,
        "provenance_refs": ["EV-2018A-SADNESS", "T03-RS-005", "T03-QA-011"],
        "source_rule_ref": "RULE-SADNESS-2018A",
    }
    expected_sadness_oracle = {
        "$schema": "../../schemas/oracle.schema.json",
        "schema_version": "1.0.0",
        "oracle_id": "sadness_2018a_symbolic.expected",
        "fixture_ref": sadness_fixture_path,
        "frozen_before_implementation": True,
        "calculation_basis": {
            "execution_profile": bl_sadness["execution_profile"],
            "published_rule_ref": "RULE-SADNESS-2018A",
            "source_of_truth": "PROVENANCE.json#decisions/T03-RS-005",
        },
        "expected": {
            "emotion": "sadness",
            "match": True,
            "numeric_pipeline_used": False,
        },
        "oracle_class": "synthetic_symbolic_regression_oracle",
        "provenance_refs": ["EV-2018A-SADNESS", "T03-RS-005", "T03-QA-011"],
        "source_rule_ref": "RULE-SADNESS-2018A",
    }
    if sadness_fixture != expected_sadness_fixture:
        raise ValueError("symbolic sadness fixture is not the exact isolated input contract")
    if sadness_oracle != expected_sadness_oracle:
        raise ValueError("symbolic sadness oracle is not the exact frozen expected contract")
    if ut14 != {
        "fixture_refs": [sadness_fixture_path],
        "fq_method": "tests.test_rules.TestRules.test_sadness_source_terms_and_context_preserved",
        "oracle_path": sadness_oracle_path,
        "oracle_refs": ["sadness_2018a_symbolic.expected"],
        "scenario_refs": [],
        "test_id": "UT-014",
    }:
        raise ValueError("UT-014 does not resolve the isolated sadness fixture and oracle")
    if isolated_oracle != {
        "main_catalog_membership": False,
        "oracle_id": "sadness_2018a_symbolic.expected",
        "path": sadness_oracle_path,
        "reason": "isolated published-rule symbolic regression outside the S00-S15 scenario-oracle bijection",
        "used_by": "UT-014",
    }:
        raise ValueError("sadness oracle exclusion from the main catalogue is incomplete")
    oracle_ref_policy = qa["test_catalog_entry_contract"]["reference_mapping"][
        "oracle_refs"
    ]
    if oracle_ref_policy.get("isolated_UT-014_exception") != {
        "additionalProperties": False,
        "main_catalog_membership": False,
        "main_scenario_oracle_bijection_membership": False,
        "oracle_path_exact": sadness_oracle_path,
        "oracle_refs_exact": ["sadness_2018a_symbolic.expected"],
        "prohibited_effects": [
            "do not add sadness_2018a_symbolic.expected to oracles/catalog.json",
            "do not add a seventeenth S00-S15 scenario or oracle",
            "do not resolve the isolated oracle by fallback through the main catalog",
        ],
        "resolution_authority": "source_of_truth.oracle_index.isolated_oracle_exclusion",
        "test_id": "UT-014",
    }:
        raise ValueError("UT-014 isolated oracle-ref exception is not exact")
    if oracle_ref_policy.get("main_catalog_allowed_ids") != (
        "S00.expected through S15.expected exactly"
    ):
        raise ValueError("main oracle catalogue range is not closed to S00-S15")
    sadness_evidence = builder.evidence["EV-2018A-SADNESS"]
    if (
        normalized_source_status(sadness_evidence.get("verification_status")) != "verified"
        or "sadness_regression_fixture_with_context"
        not in sadness_evidence.get("eligible_claim_scope", [])
    ):
        raise ValueError("EV-2018A-SADNESS is not verified for the symbolic regression scope")
    sadness_rows = [
        row
        for row in rows
        if row["target_path"] in {sadness_fixture_path, sadness_oracle_path}
        and row["materialization_status"] not in {"excluded", "superseded"}
    ]
    evidence_edges = {
        (row["target_path"], row["target_locator"], row["support_level"])
        for row in sadness_rows
        if row["support_ref_type"] == "evidence_unit"
        and row["support_ref_id"] == "EV-2018A-SADNESS"
    }
    if evidence_edges != {
        (sadness_fixture_path, "/event_context", "interpreted"),
        (sadness_fixture_path, "/published_symbolic_payload", "direct"),
        (sadness_oracle_path, "/expected/emotion", "direct"),
        (sadness_oracle_path, "/expected/match", "interpreted"),
    }:
        raise ValueError("sadness source evidence leaks into technical atoms or has wrong strength")
    expected_scientific_claim_atoms = {
        (sadness_fixture_path, "/event_context"): "doctoral_inference",
        (sadness_fixture_path, "/published_symbolic_payload"): "explicit_source",
        (sadness_oracle_path, "/expected/emotion"): "explicit_source",
        (sadness_oracle_path, "/expected/match"): "doctoral_inference",
    }
    for row in sadness_rows:
        atom_key = (row["target_path"], row["target_locator"])
        expected_class = expected_scientific_claim_atoms.get(atom_key)
        if expected_class is None:
            if (
                row["claim_ref"]
                or row["claim_provenance_class"] != "generated_for_doctoral_instance"
            ):
                raise ValueError("technical sadness atom inherits a scientific claim")
        elif (
            row["claim_ref"] != "CLM-SADNESS-001"
            or row["claim_provenance_class"] != expected_class
        ):
            raise ValueError(f"wrong sadness claim class at {atom_key}")
    for path in (sadness_fixture_path, sadness_oracle_path):
        locators = {
            row["target_locator"] for row in sadness_rows if row["target_path"] == path
        }
        for locator in locators:
            decision_supports = {
                row["support_ref_id"]
                for row in sadness_rows
                if row["target_path"] == path
                and row["target_locator"] == locator
                and row["support_ref_type"] == "approved_decision"
            }
            if decision_supports != {"T03-RS-005", "T03-QA-011"}:
                raise ValueError(f"{path}#{locator} lacks exact RS/QA decision support")
    published_sadness = reconstruct_pointer_document(
        rows, "spec/published/rule_sadness_2018a.json"
    )
    if published_sadness != {
        "source": {
            "cause_column": {
                "source_role": "separate_cause_column",
                "value": "Unwanted event (E) occurred",
            },
            "emotion_column": "Sadness",
            "if_antecedents": SADNESS_ANTECEDENTS,
            "then": {"field": "Emotion E", "operator": "is", "value": "sadness"},
        }
    }:
        raise ValueError("published sadness Cause/IF/THEN transcription is not exact")
    engineering = reconstruct_pointer_document(
        rows, "spec/decisions/engineering_v1.1.0.json"
    )
    if engineering["rule_adapters"]["sadness"]["cause_guard"] != {
        "executable_role": "doctoral_applicability_guard",
        "source_role": "separate_cause_column",
        "source_value": "Unwanted event (E) occurred",
        "target": "event_context.cause_class",
        "target_value": "unwanted_event_occurred",
    }:
        raise ValueError("sadness Cause is not a separate doctoral guard")
    if engineering["rule_adapters"]["sadness"]["consequence_binding"] != {
        "executable_role": "required_context_antecedent",
        "source_field": "Consequence (E)",
        "source_literal": "Consequence (E)",
        "target": "event_context.consequence_target",
        "whitespace_normalization": "approved_optional_space_before_parenthesized_event_marker",
    }:
        raise ValueError("sadness Consequence is not preserved as contextual antecedent")
    if engineering["rules"]["sadness"]["execution_policy"] != {
        "execution_profile": rs_sadness["execution_profile"],
        "missing_or_different_antecedent": "no_match",
        "numeric_pipeline_eligible": rs_sadness["numeric_pipeline_eligible"],
    }:
        raise ValueError("sadness symbolic execution policy diverges from T03-RS-005")

    def active_support_signature(
        target_path: str, target_locator: str
    ) -> set[tuple[str, str, str]]:
        return {
            (
                row["support_ref_type"],
                row["support_ref_id"],
                row["support_level"],
            )
            for row in rows
            if row["target_path"] == target_path
            and row["target_locator"] == target_locator
            and row["materialization_status"] not in {"excluded", "superseded"}
        }

    def direct_decisions(*decision_ids: str) -> set[tuple[str, str, str]]:
        return {
            ("approved_decision", decision_id, "direct")
            for decision_id in decision_ids
        }

    s14_scenario_path = "scenarios/S14.json"
    s14_oracle_path = "oracles/S14.expected.json"
    s14_paths = {s14_scenario_path, s14_oracle_path}
    s14_rows = [
        row
        for row in rows
        if row["target_path"] in s14_paths
        and row["materialization_status"] not in {"excluded", "superseded"}
    ]
    s14_scenario_locators = {
        row["target_locator"]
        for row in s14_rows
        if row["target_path"] == s14_scenario_path
    }
    s14_oracle_locators = {
        row["target_locator"]
        for row in s14_rows
        if row["target_path"] == s14_oracle_path
    }
    if (
        s14_scenario_locators
        != {entry[0] for entry in _top_level_atomic_entries(scenario_rows[s14_scenario_path])}
        or s14_oracle_locators
        != {entry[0] for entry in _top_level_atomic_entries(oracle_rows[s14_oracle_path])}
        or len(s14_scenario_locators) != 8
        or len(s14_oracle_locators) != 18
    ):
        raise ValueError("S14 does not contain its exact 8+18 semantic atoms")
    s14_scientific_atoms = {
        (s14_scenario_path, "/host_symbolic_payload"),
        (s14_oracle_path, "/expected/classification"),
    }
    s14_evidence_edges = {
        (
            row["target_path"],
            row["target_locator"],
            row["support_ref_id"],
            row["support_level"],
        )
        for row in s14_rows
        if row["support_ref_type"] == "evidence_unit"
    }
    if s14_evidence_edges != {
        (
            s14_scenario_path,
            "/host_symbolic_payload",
            "EV-2018B-RULES",
            "interpreted",
        ),
        (
            s14_oracle_path,
            "/expected/classification",
            "EV-2018B-RULES",
            "interpreted",
        ),
    }:
        raise ValueError("S14 evidence must be interpreted and confined to two semantic atoms")
    for row in s14_rows:
        atom_key = (row["target_path"], row["target_locator"])
        if atom_key in s14_scientific_atoms:
            if (
                row["claim_ref"] != "CLM-ANGER-001"
                or row["claim_provenance_class"] != "doctoral_inference"
            ):
                raise ValueError(f"S14 semantic atom has wrong claim attribution: {atom_key}")
        elif (
            row["claim_ref"] != "LIM-EVIDENCE-001"
            or row["claim_provenance_class"]
            != "generated_for_doctoral_instance"
        ):
            raise ValueError(f"S14 technical atom inherits the anger claim: {atom_key}")
    for path, locators, decision_ids in (
        (
            s14_scenario_path,
            s14_scenario_locators,
            ("T03-BL-006", "T03-QA-011", "T03-RS-005"),
        ),
        (
            s14_oracle_path,
            s14_oracle_locators,
            ("T03-BL-006", "T03-QA-011", "T03-RP-012", "T03-RS-005"),
        ),
    ):
        for locator in locators:
            expected_signature = direct_decisions(*decision_ids)
            if (path, locator) in s14_scientific_atoms:
                expected_signature = expected_signature | {
                    ("evidence_unit", "EV-2018B-RULES", "interpreted")
                }
            if active_support_signature(path, locator) != expected_signature:
                raise ValueError(f"S14 atom has incomplete or extraneous support: {path}#{locator}")

    decision_purity_contract = {
        "DL-CTX-001": {
            "claim_ref": "CLM-SADNESS-001",
            "claim_class": "doctoral_inference",
            "supports": {
                ("evidence_unit", "EV-2018A-SADNESS", "interpreted"),
                ("approved_decision", "T03-RS-005", "direct"),
            },
        },
        "DL-CTX-002": {
            "claim_ref": "CLM-SADNESS-001",
            "claim_class": "doctoral_inference",
            "supports": {
                ("evidence_unit", "EV-2018A-SADNESS", "interpreted"),
                ("approved_decision", "T03-RS-005", "direct"),
            },
        },
    }
    for derivation_id in (
        "DL-CTX-003",
        "DL-RUL-SAD-010",
        "DL-RUL-ANG-008",
        "DL-RUL-CONFLICT-002",
        "DL-LX-SOURCE-MAP-POLICY-001",
    ):
        decision_purity_contract[derivation_id] = {
            "claim_ref": "",
            "claim_class": "generated_for_doctoral_instance",
            "supports": direct_decisions("T03-RS-005"),
        }
    for derivation_id, contract in decision_purity_contract.items():
        group = by_derivation[derivation_id]
        signature = {
            (row["support_ref_type"], row["support_ref_id"], row["support_level"])
            for row in group
        }
        if (
            not group
            or signature != contract["supports"]
            or any(
                row["claim_ref"] != contract["claim_ref"]
                or row["claim_provenance_class"] != contract["claim_class"]
                for row in group
            )
        ):
            raise ValueError(f"decision claim/support purity mismatch: {derivation_id}")
    # The conflict decision participates in exclusion governance and is not an
    # excluded audit record itself.
    if any(
        row["materialization_status"] == "excluded"
        or row["claim_provenance_class"] == "excluded_from_execution"
        for row in by_derivation["DL-RUL-CONFLICT-002"]
    ):
        raise ValueError("the active conflict-exclusion decision is incorrectly excluded")

    confidence_valid_group = by_derivation["DL-FST-007"]
    if (
        {row["target_locator"] for row in confidence_valid_group}
        != {"/factor_state/confidence/valid_when"}
        or {row["target_value"] for row in confidence_valid_group}
        != {canonical_json("confidence >= 0.5")}
        or {
            (row["support_ref_type"], row["support_ref_id"], row["support_level"])
            for row in confidence_valid_group
        }
        != {
            ("evidence_unit", "EV-THESIS-FACTOR", "interpreted"),
            ("approved_decision", "T03-CT-009", "direct"),
        }
        or any(
            row["claim_ref"] != "REQ-CONF-001"
            or row["claim_provenance_class"] != "doctoral_inference"
            for row in confidence_valid_group
        )
    ):
        raise ValueError("DL-FST-007 confidence threshold is not an atomic doctoral inference")
    if {
        row["row_id"] for row in confidence_valid_group
    } != {"ROW-DL-FST-007-01", "ROW-DL-FST-007-02"}:
        raise ValueError("DL-FST-007 did not preserve both legacy row identities")
    for derivation_id, locator, value in (
        (
            "DL-FST-CONFIDENCE-DOMAIN-001",
            "/factor_state/confidence/domain",
            "[0,1]",
        ),
        (
            "DL-FST-CONFIDENCE-TYPE-001",
            "/factor_state/confidence/type",
            "decimal_string",
        ),
    ):
        group = by_derivation[derivation_id]
        if (
            {row["target_locator"] for row in group} != {locator}
            or {row["target_value"] for row in group} != {canonical_json(value)}
            or {
                (row["support_ref_type"], row["support_ref_id"], row["support_level"])
                for row in group
            }
            != direct_decisions("T03-CT-009")
            or any(
                row["claim_ref"]
                or row["claim_provenance_class"]
                != "generated_for_doctoral_instance"
                for row in group
            )
        ):
            raise ValueError(f"technical confidence atom is impure: {derivation_id}")
    if engineering["factor_state"]["confidence"] != {
        "domain": "[0,1]",
        "type": "decimal_string",
        "valid_when": "confidence >= 0.5",
    }:
        raise ValueError("atomic confidence rows do not reconstruct the approved contract")

    # M1: keep the two publications verbatim and move every canonical term to
    # the decisions layer.  The four new published atoms each have one and only
    # one direct evidence edge.
    rs = builder.decisions["T03-RS-005"]["decision"]
    boundary_contract = rs["boundary_terminology_adapter_contract"]
    expected_published_boundary = {
        "sources": {
            "2018a": {
                "producer": "General Appraisal",
                "integration_boundary": "Emotional Filter",
            },
            "2018b": {
                "producer": "General Appraisal (GA)",
                "integration_boundary": "Emotion Filter (EF)",
            },
        }
    }
    boundary_path = "spec/published/ga_ef_boundary_2018ab.json"
    if reconstruct_pointer_document(rows, boundary_path) != expected_published_boundary:
        raise ValueError("published GA/EF terminology is not an exact source-specific transcription")
    expected_boundary_evidence = {
        "/sources/2018a/producer": "EV-2018A-GA-EF",
        "/sources/2018a/integration_boundary": "EV-2018A-GA-EF",
        "/sources/2018b/producer": "EV-2018B-GA-EF",
        "/sources/2018b/integration_boundary": "EV-2018B-GA-EF",
    }
    for locator, evidence_id in expected_boundary_evidence.items():
        if active_support_signature(boundary_path, locator) != {
            ("evidence_unit", evidence_id, "direct")
        }:
            raise ValueError(f"published boundary atom has impure support: {locator}")
        atom_rows = [
            row
            for row in rows
            if row["target_path"] == boundary_path
            and row["target_locator"] == locator
            and row["materialization_status"] not in {"excluded", "superseded"}
        ]
        if any(
            row["transformation_type"] != "metadata_transcription"
            or row["claim_provenance_class"] != "explicit_source"
            for row in atom_rows
        ):
            raise ValueError(f"published boundary attribution is not explicit-source metadata: {locator}")
    if engineering["published_boundary_adapter"] != {
        "canonical": boundary_contract["canonical_doctoral_terms"],
        "source_specific_adapters": boundary_contract["source_specific_adapters"],
        "policy": {
            key: deepcopy(value)
            for key, value in boundary_contract.items()
            if key not in {"canonical_doctoral_terms", "source_specific_adapters"}
        },
    }:
        raise ValueError("doctoral GA/EF adapter does not equal T03-RS-005")
    active_boundary_adapter_rows = [
        row
        for row in rows
        if row["target_path"] == "spec/decisions/engineering_v1.1.0.json"
        and row["target_locator"].startswith("/published_boundary_adapter/")
        and row["materialization_status"] not in {"excluded", "superseded"}
    ]
    if not active_boundary_adapter_rows or any(
        row["claim_ref"]
        or row["claim_provenance_class"] != "generated_for_doctoral_instance"
        for row in active_boundary_adapter_rows
    ):
        raise ValueError("decision-layer boundary adapter must be generated engineering metadata")
    for derivation_id, field in (
        ("DL-HST-011", "producer"),
        ("DL-HST-012", "integration_boundary"),
    ):
        group = by_derivation[derivation_id]
        if {
            row["support_ref_id"]: row["support_level"] for row in group
        } != {
            "EV-2018A-GA-EF": "interpreted",
            "EV-2018B-GA-EF": "interpreted",
            "T03-RS-005": "direct",
        }:
            raise ValueError(f"{derivation_id} does not preserve interpreted evidence plus RS authority")
        if any(
            row["target_locator"]
            != f"/published_boundary_adapter/canonical/{field}"
            or row["claim_ref"]
            or row["claim_provenance_class"] != "generated_for_doctoral_instance"
            for row in group
        ):
            raise ValueError(f"{derivation_id} is not an explicitly doctoral normalization")
    for row_id in {
        "ROW-DL-HST-011-01",
        "ROW-DL-HST-011-02",
        "ROW-DL-HST-012-01",
        "ROW-DL-HST-012-02",
    }:
        if output_derivation_by_row.get(row_id) not in {"DL-HST-011", "DL-HST-012"}:
            raise ValueError(f"legacy GA/EF audit identity was not preserved: {row_id}")
    for derivation_id, evidence_id in {
        "DL-HST-BND-SOURCE-MAP-2018A": "EV-2018A-GA-EF",
        "DL-HST-BND-SOURCE-MAP-2018B": "EV-2018B-GA-EF",
    }.items():
        if {
            (row["support_ref_type"], row["support_ref_id"], row["support_level"])
            for row in by_derivation[derivation_id]
        } != {
            ("evidence_unit", evidence_id, "interpreted"),
            ("approved_decision", "T03-RS-005", "direct"),
        }:
            raise ValueError(f"{derivation_id} has an invalid boundary-map attribution")
    if {
        (row["support_ref_type"], row["support_ref_id"], row["support_level"])
        for row in by_derivation["DL-HST-BND-SOURCE-MAP-POLICY-001"]
    } != direct_decisions("T03-RS-005"):
        raise ValueError("boundary-adapter policy must have only direct RS-005 authority")

    # M3: all twelve source lexemes are resolved by source ID and exact spelling
    # under one closed policy.  Evidence records the spelling only; RS-005 is the
    # direct authority for the equivalence.
    lexeme_contract = rs["antecedent_lexeme_adapter_contract"]
    if engineering["antecedent_lexeme_adapter"] != {
        "source_specific_maps": lexeme_contract["source_specific_maps"],
        "policy": {
            key: deepcopy(value)
            for key, value in lexeme_contract.items()
            if key != "source_specific_maps"
        },
    }:
        raise ValueError("source-specific six-lexeme adapter is incomplete or not fail-closed")
    lexeme_support_contract = {
        "DL-LX-SOURCE-MAP-2018A": "EV-2018A-SADNESS",
        "DL-LX-SOURCE-MAP-2018B": "EV-2018B-RULES",
    }
    for derivation_id, evidence_id in lexeme_support_contract.items():
        group = by_derivation[derivation_id]
        if {
            (row["support_ref_type"], row["support_ref_id"], row["support_level"])
            for row in group
        } != {
            ("evidence_unit", evidence_id, "interpreted"),
            ("approved_decision", "T03-RS-005", "direct"),
        }:
            raise ValueError(f"{derivation_id} misattributes lexical equivalence")
        if any(row["claim_provenance_class"] != "doctoral_inference" for row in group):
            raise ValueError(f"{derivation_id} must be a doctoral lexical decision")
    if {
        (row["support_ref_type"], row["support_ref_id"], row["support_level"])
        for row in by_derivation["DL-LX-SOURCE-MAP-POLICY-001"]
    } != direct_decisions("T03-RS-005"):
        raise ValueError("lexeme fail-closed policy must be supported only by T03-RS-005")

    # DG-01 and GOV-001 remain code-only and serialization-exact respectively.
    if engineering["diagnostics"]["codes"] != qa["diagnostic_priority"]:
        raise ValueError("diagnostic code list does not equal QA priority")
    if engineering["diagnostics"]["aggregation"] != builder.decisions["T03-CT-009"]["decision"]["diagnostic_aggregation"]:
        raise ValueError("diagnostic aggregation is not the complete ordered code-class policy")
    gov_group = by_derivation["DL-GOV-001"]
    rp_csv = builder.decisions["T03-RP-012"]["decision"]["csv_profile"]
    if (
        {row["target_value"] for row in gov_group} != {canonical_json(rp_csv)}
        or {row["target_locator"] for row in gov_group} != {"@dialect"}
        or {
            (row["support_ref_type"], row["support_ref_id"], row["support_level"])
            for row in gov_group
        }
        != direct_decisions("T03-DL-008", "T03-RP-012")
        or any(
            row["materialization_status"] != "materialized_t03"
            or row["transformation_type"] != "engineering_decision"
            for row in gov_group
        )
    ):
        raise ValueError("DL-GOV-001 is not the exact IFM6-CSV-v1 serialization profile")
    if output_derivation_by_row.get("ROW-DL-GOV-001-01") != "DL-GOV-001":
        raise ValueError("legacy GOV-001 row identity was not preserved")

    # TR-01: reconstruct the normative schema and all decision contracts before
    # accepting a recipe.  This checks exact atoms, exact support attribution,
    # a closed nine-component trace_core and the absence of an S15 trace.
    trace_schema_path = "schemas/trace.schema.json"
    expected_trace_schema = qa["trace_schema_document_seed"]
    actual_trace_schema = reconstruct_pointer_document(rows, trace_schema_path)
    if actual_trace_schema != expected_trace_schema:
        raise ValueError("trace schema atoms do not reconstruct the frozen QA seed")
    expected_schema_supports = {
        "/$schema": ("T03-QA-011", "T03-RP-012"),
        "/$id": ("T03-QA-011", "T03-RP-012"),
        "/title": ("T03-QA-011",),
        "/description": ("T03-QA-011",),
        "/type": ("T03-QA-011",),
        "/required": ("T03-QA-011",),
        "/additionalProperties": ("T03-QA-011",),
        "/properties/$schema": ("T03-QA-011", "T03-RP-012"),
        "/properties/schema_version": ("T03-QA-011", "T03-RP-012"),
        "/properties/scenario_id": ("T03-BL-006", "T03-QA-011"),
        "/properties/evaluation_time": ("T03-BL-006", "T03-TM-004", "T03-QA-011"),
        "/properties/disposition": ("T03-CT-009", "T03-QA-011"),
        "/properties/diagnostics": ("T03-CT-009", "T03-QA-011"),
        "/properties/trace_core": ("T03-QA-011",),
        "/properties/trace_id": ("T03-QA-011", "T03-RP-012"),
        "/$defs/decimal_string": ("T03-QA-011", "T03-RP-012"),
        "/$defs/event": ("T03-BL-006", "T03-QA-011"),
        "/$defs/factor_state": ("T03-BL-006", "T03-TM-004", "T03-CT-009", "T03-QA-011"),
        "/$defs/appraisal_vector": ("T03-BL-006", "T03-RS-005", "T03-QA-011", "T03-RP-012"),
        "/$defs/policy": ("T03-TM-004", "T03-CT-009", "T03-QA-011", "T03-RP-012"),
        "/$defs/mask": ("T03-RS-005", "T03-QA-011"),
        "/$defs/formula_record": ("T03-RS-005", "T03-QA-011", "T03-RP-012"),
        "/$defs/classification_record": ("T03-RS-005", "T03-QA-011"),
        "/$defs/versions": ("T03-QA-011", "T03-RP-012"),
        "/$defs/trace_core": ("T03-QA-011",),
    }
    actual_schema_locators = {
        row["target_locator"]
        for row in rows
        if row["target_path"] == trace_schema_path
        and row["materialization_status"] not in {"excluded", "superseded"}
    }
    if actual_schema_locators != set(expected_schema_supports):
        raise ValueError("trace schema does not use the exact semantic atom set")
    for locator, decision_ids in expected_schema_supports.items():
        if active_support_signature(trace_schema_path, locator) != direct_decisions(*decision_ids):
            raise ValueError(f"trace schema support mismatch at {locator}")
    root_required = expected_trace_schema["required"]
    if (
        expected_trace_schema["additionalProperties"] is not False
        or set(root_required) != set(expected_trace_schema["properties"])
        or expected_trace_schema["properties"]["trace_id"]["pattern"] != "^[0-9a-f]{64}$"
        or expected_trace_schema["properties"]["diagnostics"].get("uniqueItems") is not True
        or expected_trace_schema["properties"]["diagnostics"]["items"]["enum"]
        != qa["diagnostic_priority"]
    ):
        raise ValueError("trace wrapper is not closed, complete and diagnostic-order safe")
    trace_core = expected_trace_schema["$defs"]["trace_core"]
    expected_core_fields = {
        "event", "state", "baseline", "output", "policy", "mask",
        "formula", "classification", "versions",
    }
    if (
        trace_core["additionalProperties"] is not False
        or set(trace_core["required"]) != expected_core_fields
        or set(trace_core["properties"]) != expected_core_fields
    ):
        raise ValueError("trace_core is not the exact closed nine-component object")
    for definition_name in (
        "event", "factor_state", "appraisal_vector", "policy", "mask",
        "formula_record", "classification_record", "versions", "trace_core",
    ):
        definition = expected_trace_schema["$defs"][definition_name]
        if (
            definition.get("type") != "object"
            or definition.get("additionalProperties") is not False
            or set(definition.get("required", [])) != set(definition.get("properties", {}))
        ):
            raise ValueError(f"trace schema definition is not closed: {definition_name}")
    nullability = trace_core["properties"]
    for key in ("state", "formula", "classification"):
        one_of = nullability[key].get("oneOf", [])
        if len(one_of) != 2 or {tuple(sorted(item)) for item in one_of} == set():
            raise ValueError(f"trace {key} nullability is not explicit")
        if not any(item == {"type": "null"} for item in one_of):
            raise ValueError(f"trace {key} does not allow explicit JSON null")

    expected_projection = qa["trace_result_projection_contract"]
    if engineering["trace_result_projection_contract"] != expected_projection:
        raise ValueError("trace result projection does not reconstruct the frozen QA contract")
    projection_prefix = "/trace_result_projection_contract"
    projection_support_ids: dict[str, tuple[str, ...]] = {
        f"{projection_prefix}/contract_id": ("T03-QA-011",),
        f"{projection_prefix}/purpose": ("T03-QA-011",),
        f"{projection_prefix}/scope": ("T03-BL-006", "T03-QA-011"),
        f"{projection_prefix}/source_validation_precondition": ("T03-QA-011", "T03-RP-012"),
        f"{projection_prefix}/required_source_pointers": ("T03-QA-011", "T03-RP-012"),
        f"{projection_prefix}/projection_schema/type": ("T03-QA-011",),
        f"{projection_prefix}/projection_schema/additionalProperties": ("T03-QA-011",),
        f"{projection_prefix}/projection_schema/required": ("T03-QA-011",),
        f"{projection_prefix}/projection_schema/properties/scenario_id": ("T03-BL-006", "T03-QA-011"),
        f"{projection_prefix}/projection_schema/properties/evaluation_time": ("T03-BL-006", "T03-QA-011"),
        f"{projection_prefix}/projection_schema/properties/disposition": ("T03-CT-009", "T03-QA-011"),
        f"{projection_prefix}/projection_schema/properties/diagnostics": ("T03-CT-009", "T03-QA-011"),
    }
    for key in ("type", "additionalProperties", "required"):
        projection_support_ids[
            f"{projection_prefix}/projection_schema/properties/output/{key}"
        ] = ("T03-BL-006", "T03-QA-011", "T03-RP-012")
    for key in VECTOR_FIELDS:
        projection_support_ids[
            f"{projection_prefix}/projection_schema/properties/output/properties/{key}"
        ] = ("T03-BL-006", "T03-QA-011", "T03-RP-012")
    for key in expected_projection["projection_bindings"]:
        projection_support_ids[f"{projection_prefix}/projection_bindings/{key}"] = (
            "T03-QA-011", "T03-RP-012"
        )
    projection_equality_supports = {
        "scenario_id": ("T03-BL-006", "T03-QA-011"),
        "evaluation_time": ("T03-BL-006", "T03-QA-011"),
        "disposition": ("T03-CT-009", "T03-QA-011"),
        "diagnostics": ("T03-CT-009", "T03-QA-011"),
        "output": ("T03-BL-006", "T03-QA-011", "T03-RP-012"),
    }
    for key, decision_ids in projection_equality_supports.items():
        projection_support_ids[f"{projection_prefix}/cross_source_equality/{key}"] = decision_ids
    for key in ("data_origin_rule", "runtime_authority_rule"):
        projection_support_ids[f"{projection_prefix}/{key}"] = ("T03-QA-011", "T03-RP-012")
    projection_support_ids[f"{projection_prefix}/failure_policy"] = (
        "T03-CT-009", "T03-QA-011", "T03-RP-012"
    )
    actual_projection_locators = {
        row["target_locator"]
        for row in rows
        if row["target_path"] == "spec/decisions/engineering_v1.1.0.json"
        and row["target_locator"].startswith(f"{projection_prefix}/")
        and row["materialization_status"] not in {"excluded", "superseded"}
    }
    if actual_projection_locators != set(projection_support_ids):
        raise ValueError("trace result projection does not use its exact semantic atom set")
    for locator, decision_ids in projection_support_ids.items():
        if active_support_signature(
            "spec/decisions/engineering_v1.1.0.json", locator
        ) != direct_decisions(*decision_ids):
            raise ValueError(f"trace projection support mismatch at {locator}")

    expected_template = deepcopy(qa["trace_materialization_template"])
    expected_binding_recipes = expected_template.pop("binding_recipes")
    if engineering["trace_materialization"] != {
        "template": expected_template,
        "binding_recipes": expected_binding_recipes,
    }:
        raise ValueError("trace template or bindings diverge from T03-QA-011")
    template_decisions = (
        "T03-BL-006", "T03-RS-005", "T03-TM-004", "T03-CT-009",
        "T03-QA-011", "T03-RP-012", "T03-MP-013",
    )
    if expected_template["supports"] != list(template_decisions):
        raise ValueError("trace template's embedded support order is not frozen")
    if active_support_signature(
        "spec/decisions/engineering_v1.1.0.json",
        "/trace_materialization/template",
    ) != direct_decisions(*template_decisions):
        raise ValueError("trace template does not have its exact seven direct support edges")
    if (
        set(expected_template["instance_required_fields"])
        != set(expected_trace_schema["required"])
        or set(expected_template["trace_core_required_fields"]) != expected_core_fields
        or expected_template["execution_or_materialization_claimed"] is not False
    ):
        raise ValueError("trace template shape diverges from the closed trace schema")
    template_hash_policy = expected_template["canonicalization_and_trace_id_policy"]
    rp_decision = builder.decisions["T03-RP-012"]["decision"]
    if (
        template_hash_policy["canonicalization_profile"]
        != rp_decision["json_profile"]["profile_id"]
        or template_hash_policy["algorithm"] != "SHA-256"
        or template_hash_policy["preimage_scope"] != "trace_core and no wrapper field"
        or template_hash_policy["trace_id_encoding"]
        != "64 lowercase hexadecimal characters"
    ):
        raise ValueError("trace template hash policy diverges from T03-RP-012")
    required_binding_fields = set(
        expected_template["binding_recipe_contract"]["required_fields"]
    )
    if required_binding_fields != set(
        expected_template["binding_recipe_contract"]["allowed_fields"]
    ) or expected_template["binding_recipe_contract"]["additionalProperties"] is not False:
        raise ValueError("trace binding contract is not closed")
    trace_recipe_supports = direct_decisions("T03-QA-011", "T03-RP-012", "T03-MP-013")
    if len(expected_binding_recipes) != 15:
        raise ValueError("trace binding contract must contain exactly S00-S14")
    for index, binding in enumerate(expected_binding_recipes):
        sid = f"S{index:02d}"
        if (
            binding["recipe_id"] != f"TRACE-BIND-{sid}"
            or binding["trace"] != f"traces/reference_run/{sid}.trace.json"
            or set(binding) != required_binding_fields
            or "S15" in canonical_json(binding)
        ):
            raise ValueError(f"invalid trace binding recipe for {sid}")
        decision_locator = f"/trace_materialization/binding_recipes/{index}"
        if active_support_signature(
            "spec/decisions/engineering_v1.1.0.json", decision_locator
        ) != trace_recipe_supports:
            raise ValueError(f"trace binding lacks QA/RP/MP support: {sid}")
        trace_path = binding["trace"]
        active_trace_rows = [
            row
            for row in rows
            if row["target_path"] == trace_path
            and row["materialization_status"] not in {"excluded", "superseded"}
        ]
        if (
            {row["target_locator"] for row in active_trace_rows}
            != {"@materialization-recipe"}
            or {row["target_value"] for row in active_trace_rows}
            != {canonical_json(binding)}
            or active_support_signature(trace_path, "@materialization-recipe")
            != trace_recipe_supports
            or any(
                row["materialization_status"] != "planned"
                or row["transformation_type"] != "automatic_derivation"
                for row in active_trace_rows
            )
        ):
            raise ValueError(f"trace recipe is not a deferred exact binding for {sid}")

    catalog = reconstruct_pointer_document(rows, "tests/test_catalog.json")
    methods = catalog.get("test_catalog", [])
    if catalog != qa["test_catalog"]["document_seed"]:
        raise ValueError("test catalogue is not the exact frozen T03-QA-011 document seed")
    if catalog.get("expected_test_method_count") != 18 or len(methods) != 18:
        raise ValueError("test catalogue must contain exactly eighteen methods")
    if len({item["fq_method"] for item in methods}) != 18:
        raise ValueError("duplicate fq_method")
    if [item["test_id"] for item in methods] != [f"UT-{index:03d}" for index in range(1, 19)]:
        raise ValueError("test catalogue identifiers must be UT-001 through UT-018")
    if methods != qa_test_catalog(builder.provenance):
        raise ValueError("test catalogue diverges from T03-QA-011")
    oracle_catalog = reconstruct_pointer_document(rows, "oracles/catalog.json")
    scenario_catalog = reconstruct_pointer_document(rows, "scenarios/catalog.json")
    expected_oracle_catalog = deepcopy(
        qa["source_of_truth"]["oracle_index"]["document_seed"]
    )
    for index, entry in enumerate(expected_oracle_catalog["entries"]):
        sid = f"S{index:02d}"
        oracle = reconstruct_pointer_document(rows, f"oracles/{sid}.expected.json")
        oracle_bytes = (canonical_json(oracle) + "\n").encode("utf-8")
        entry["sha256"] = hashlib.sha256(oracle_bytes).hexdigest()
    if oracle_catalog != expected_oracle_catalog:
        raise ValueError(
            "oracle catalogue is not the exact post-freeze T03-QA-011 projection"
        )
    if scenario_catalog != qa["source_of_truth"]["scenario_index"]["document_seed"]:
        raise ValueError("scenario catalogue is not the exact frozen T03-QA-011 document seed")
    if len(oracle_catalog.get("entries", [])) != 16:
        raise ValueError("oracle catalog must index exactly sixteen external oracle documents")
    if any("expected" in entry for entry in oracle_catalog["entries"]):
        raise ValueError("oracle catalog embeds expected payloads")
    if [entry.get("oracle_id") for entry in oracle_catalog["entries"]] != [
        f"S{index:02d}.expected" for index in range(16)
    ]:
        raise ValueError("oracle catalog identifiers do not resolve QA oracle_refs")
    if len(scenario_catalog.get("entries", [])) != 16:
        raise ValueError("scenario catalog must index exactly sixteen input documents")

    mp = builder.decisions["T03-MP-013"]["decision"]
    expected_bindings = mp["required_executable_binding_map"]
    binding_artifacts = mp["binding_artifacts"]
    binding_locations = {
        binding_artifacts["registry"]["path"]: binding_artifacts["registry"]["locators"],
        binding_artifacts["resolved_config"]["path"]: binding_artifacts["resolved_config"]["locators"],
        binding_artifacts["implementation"]["path"]: binding_artifacts["implementation"]["semantic_anchors"],
    }
    for binding_path, locators in binding_locations.items():
        actual_bindings = {
            key: json.loads(row["target_value"])
            for key, locator in locators.items()
            for row in rows
            if row["target_path"] == binding_path
            and row["target_locator"] == locator
            and row["materialization_status"] != "superseded"
        }
        if actual_bindings != expected_bindings:
            raise ValueError(f"binding propagation incomplete in {binding_path}")

    expected_resolution_documents = resolution_documents(builder)
    for target_path, expected_document in expected_resolution_documents.items():
        reconstructed = reconstruct_pointer_document(rows, target_path)
        if reconstructed != expected_document:
            raise ValueError(
                f"closed ledger projection diverges from the approved resolution: {target_path}"
            )
        path = builder.root / target_path
        active_rows = [
            row
            for row in rows
            if row["target_path"] == target_path
            and row["materialization_status"] not in {"excluded", "superseded"}
        ]
        if path.is_file():
            expected_bytes = (canonical_json(expected_document) + "\n").encode("utf-8")
            if path.read_bytes() != expected_bytes:
                raise ValueError(f"noncanonical or stale materialized projection: {target_path}")
            if any(
                row["materialization_status"] != "materialized_t03"
                or row["materialization_refs"] != target_path
                for row in active_rows
            ):
                raise ValueError(f"materialized projection has stale ledger status: {target_path}")
        elif any(row["materialization_status"] == "materialized_t03" for row in active_rows):
            raise ValueError(f"ledger asserts a missing materialized projection: {target_path}")

    declared_schema_paths = {
        path for path in builder.planned_paths if path.startswith("schemas/")
    }
    if declared_schema_paths != ALL_SCHEMA_PATHS:
        raise ValueError("PROVENANCE does not declare the exact seventeen-schema set")
    expected_schema_documents = schema_documents(builder)
    for target_path, expected_document in expected_schema_documents.items():
        reconstructed = reconstruct_pointer_document(rows, target_path)
        if reconstructed != expected_document:
            raise ValueError(
                f"schema ledger projection diverges from its contract: {target_path}"
            )
        path = builder.root / target_path
        active_rows = [
            row
            for row in rows
            if row["target_path"] == target_path
            and row["materialization_status"] not in {"excluded", "superseded"}
        ]
        if path.is_file():
            expected_bytes = (canonical_json(expected_document) + "\n").encode("utf-8")
            if path.read_bytes() != expected_bytes:
                raise ValueError(f"noncanonical or stale materialized schema: {target_path}")
            if any(
                row["materialization_status"] != "materialized_t03"
                or row["materialization_refs"] != target_path
                for row in active_rows
            ):
                raise ValueError(f"materialized schema has stale ledger status: {target_path}")
        elif any(row["materialization_status"] == "materialized_t03" for row in active_rows):
            raise ValueError(f"ledger asserts a missing materialized schema: {target_path}")

    build_recipe = reconstruct_pointer_document(rows, mp["recipe_path"])
    topology = reconstruct_pointer_document(rows, mp["topology_path"])
    build_record = reconstruct_pointer_document(rows, mp["build_record_path"])
    if build_recipe.get("generator_registry") != mp["generator_registry"]:
        raise ValueError("BUILD_RECIPE generator registry diverges from T03-MP-013")
    if build_recipe.get("validator_registry") != mp["validator_registry"]:
        raise ValueError("BUILD_RECIPE validator registry diverges from T03-MP-013")
    if build_recipe.get("planned_commands") != mp["planned_commands"]:
        raise ValueError("BUILD_RECIPE commands diverge from T03-MP-013")
    if build_recipe.get("binding_artifacts") != mp["binding_artifacts"]:
        raise ValueError("BUILD_RECIPE binding artifacts diverge from T03-MP-013")
    if build_recipe.get("pre_run_source_manifest_gate") != mp["pre_run_source_manifest_gate"]:
        raise ValueError("BUILD_RECIPE source-manifest gate diverges from T03-MP-013")
    source_manifest_rows = [
        row
        for row in rows
        if row["target_path"] == "manifests/SOURCE_SHA256.txt"
        and row["materialization_status"] != "superseded"
    ]
    if len(source_manifest_rows) != 1:
        raise ValueError("SOURCE_SHA256 manifest must have exactly one active build recipe")
    source_manifest_row = source_manifest_rows[0]
    if (
        source_manifest_row["target_locator"] != "@materialization-recipe"
        or json.loads(source_manifest_row["target_value"])
        != recipe_for_path("manifests/SOURCE_SHA256.txt", mp)
    ):
        raise ValueError("SOURCE_SHA256 recipe diverges from the frozen pre-run gate")
    if topology.get("dag") != mp["dag"] or topology.get("acyclicity_rules") != mp["acyclicity_rules"]:
        raise ValueError("generation topology diverges from T03-MP-013")
    if build_record.get("status") != "planned_not_executed":
        raise ValueError("BUILD_RECORD template falsely asserts execution")
    if build_record.get("required_fields") != mp["derived_record_requirements"]:
        raise ValueError("BUILD_RECORD template omits normative future fields")
    if any(
        validator.get("execution_status") != "not_run"
        or validator.get("exit_code") is not None
        for validator in build_record.get("validator_registry", {}).get("validators", [])
    ):
        raise ValueError("BUILD_RECORD template invents validator execution")
    ct_diagnostics = builder.decisions["T03-CT-009"]["decision"]["diagnostic_codes"]
    qa_diagnostics = builder.decisions["T03-QA-011"]["decision"]["diagnostic_priority"]
    if ct_diagnostics != qa_diagnostics or len(ct_diagnostics) != 22:
        raise ValueError("CT diagnostic codes must equal QA priority exactly")

    trace_row = next(row for row in rows if row["derivation_id"] == "DL-REP-007")
    trace_value = json.loads(trace_row["target_value"])
    if len(trace_value.get("included", [])) != 9 or not trace_value.get("excluded"):
        raise ValueError("trace_core must contain exactly nine identity fields plus explicit exclusions")
    if any(row["target_path"].endswith("S15.trace.json") for row in rows):
        raise ValueError("S15 modulation trace is forbidden")
    for row in rows:
        if row["target_path"].startswith(("results/", "traces/", "logs/", "environment/")):
            if row["materialization_status"] != "planned":
                raise ValueError(f"generated evidence was prematurely materialized: {row['row_id']}")
    artifact_rows = [row for row in rows if row["target_locator"] == "@minimum-content"]
    if len(artifact_rows) != 7:
        raise ValueError("the seven artifacts require seven minimum-content recipes")
    active_derivations = {
        row["derivation_id"]
        for row in rows
        if row["materialization_status"] not in {"excluded", "superseded"}
    }
    for row in artifact_rows:
        minimum = json.loads(row["target_value"])
        unresolved_sources = set(minimum.get("source_derivations", [])) - active_derivations
        if unresolved_sources:
            raise ValueError(
                f"artifact minimum {row['derivation_id']} has inactive or unresolved sources: "
                f"{sorted(unresolved_sources)}"
            )
    citation_rows = [
        row
        for row in rows
        if row["target_path"] == "CITATION.cff"
        and row["materialization_status"] != "superseded"
    ]
    if len(citation_rows) != 1:
        raise ValueError("CITATION.cff must have exactly one active lifecycle row")
    citation = citation_rows[0]
    citation_authorized = "T03-CIT-015" in builder.decisions
    if citation_authorized:
        if (
            citation["materialization_status"] != "materialized_t03"
            or citation["materialization_refs"] != "CITATION.cff"
            or not (builder.root / "CITATION.cff").is_file()
            or "T03-CIT-015" not in split_refs(citation["approval_refs"])
        ):
            raise ValueError(
                "authorized CITATION.cff must be present and materialized under T03-CIT-015"
            )
    elif (
        citation["target_value"] != "null"
        or citation["materialization_status"] != "blocked"
        or citation["materialization_refs"]
    ):
        raise ValueError("CITATION.cff must be blocked with JSON null and no materialization ref")

    decimal_scope = [
        row
        for row in rows
        if row["target_path"].startswith(("scenarios/", "oracles/"))
        or row["derivation_id"].startswith(("DL-MOD-", "DL-CAT-"))
    ]
    noncanonical_decimal = re.compile(
        r"(?<![A-Za-z0-9_.])-?(?:0|[1-9][0-9]*)\.([0-9]*0)(?![A-Za-z0-9_.])"
    )
    exponent_decimal = re.compile(
        r"(?<![A-Za-z0-9_.])-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?[eE][+-]?[0-9]+(?![A-Za-z0-9_.])"
    )
    for row in decimal_scope:
        if noncanonical_decimal.search(row["target_value"]) or exponent_decimal.search(
            row["target_value"]
        ):
            raise ValueError(f"noncanonical semantic decimal in {row['row_id']}")

    return {
        "columns": len(HEADER),
        "derivations": len(by_derivation),
        "expanded_planned_paths": len(planned),
        "materialization_status_counts": {
            status: sum(1 for row in rows if row["materialization_status"] == status)
            for status in sorted({row["materialization_status"] for row in rows})
        },
        "rows": len(rows),
        "target_paths": len(targeted),
        "explicit_source_groups_with_direct_evidence": explicit_source_groups,
        "legacy_row_ids_preserved": PRE_MIGRATION_LEGACY_ROWS,
        "legacy_row_ids_total": PRE_MIGRATION_LEGACY_ROWS,
        "input_row_ids_preserved": len(builder.legacy_row_ids),
        "input_row_ids_total": len(builder.legacy_row_ids),
        "pre_migration_ledger_sha256": PRE_MIGRATION_LEDGER_SHA256,
    }


def atomic_write_csv(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=HEADER,
                delimiter=",",
                quotechar='"',
                doublequote=True,
                escapechar=None,
                quoting=csv.QUOTE_ALL,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(
                sorted(rows, key=lambda row: row["row_id"].encode("ascii"))
            )
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


def atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    """Replace one canonical UTF-8 JSON document atomically and durably."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write((canonical_json(document) + "\n").encode("utf-8"))
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


def materialize_configuration_documents(
    builder: LedgerBuilder, *, check_only: bool
) -> dict[str, dict[str, Any]]:
    """Materialize or verify the two closed T03.3-4 ledger projections."""
    expected_documents = resolution_documents(builder)
    report: dict[str, dict[str, Any]] = {}
    for target_path in sorted(CONFIGURATION_LAYER_PATHS):
        expected = expected_documents[target_path]
        reconstructed = reconstruct_pointer_document(builder.rows, target_path)
        if reconstructed != expected:
            raise ValueError(f"cannot materialize an inconsistent projection: {target_path}")
        destination = builder.root / target_path
        expected_bytes = (canonical_json(expected) + "\n").encode("utf-8")
        if check_only:
            if not destination.is_file():
                raise ValueError(f"required materialized projection is missing: {target_path}")
            if destination.read_bytes() != expected_bytes:
                raise ValueError(f"materialized projection is stale: {target_path}")
        else:
            atomic_write_json(destination, expected)
        report[target_path] = {
            "bytes": len(expected_bytes),
            "sha256": hashlib.sha256(expected_bytes).hexdigest(),
        }
    for row in builder.rows:
        if (
            row["target_path"] in CONFIGURATION_LAYER_PATHS
            and row["materialization_status"] not in {"excluded", "superseded"}
        ):
            row["materialization_status"] = "materialized_t03"
            row["materialization_refs"] = row["target_path"]
    return report


def materialize_schema_documents(
    builder: LedgerBuilder, *, check_only: bool
) -> dict[str, dict[str, Any]]:
    """Materialize or verify the exact fifteen-schema T03.3-5 projection."""
    expected_documents = schema_documents(builder)
    report: dict[str, dict[str, Any]] = {}
    for target_path in sorted(MATERIALIZED_SCHEMA_PATHS):
        expected = expected_documents[target_path]
        reconstructed = reconstruct_pointer_document(builder.rows, target_path)
        if reconstructed != expected:
            raise ValueError(
                f"cannot materialize an inconsistent schema projection: {target_path}"
            )
        destination = builder.root / target_path
        expected_bytes = (canonical_json(expected) + "\n").encode("utf-8")
        if check_only:
            if not destination.is_file():
                raise ValueError(f"required materialized schema is missing: {target_path}")
            if destination.read_bytes() != expected_bytes:
                raise ValueError(f"materialized schema is stale: {target_path}")
        else:
            atomic_write_json(destination, expected)
        report[target_path] = {
            "bytes": len(expected_bytes),
            "sha256": hashlib.sha256(expected_bytes).hexdigest(),
        }
    for row in builder.rows:
        if (
            row["target_path"] in MATERIALIZED_SCHEMA_PATHS
            and row["materialization_status"] not in {"excluded", "superseded"}
        ):
            row["materialization_status"] = "materialized_t03"
            row["materialization_refs"] = row["target_path"]
    return report


def materialize_frozen_input_documents(
    builder: LedgerBuilder, *, check_only: bool
) -> dict[str, dict[str, Any]]:
    """Materialize the T03.3-6 inputs and independent pre-implementation oracles."""
    documents = {
        target_path: reconstruct_pointer_document(builder.rows, target_path)
        for target_path in sorted(FROZEN_INPUT_PATHS)
    }
    if set(documents) != FROZEN_INPUT_PATHS:
        raise ValueError("frozen input document set is incomplete")

    report: dict[str, dict[str, Any]] = {}
    for target_path, document in documents.items():
        destination = builder.root / target_path
        expected_bytes = (canonical_json(document) + "\n").encode("utf-8")
        if check_only:
            if not destination.is_file():
                raise ValueError(f"required frozen input is missing: {target_path}")
            if destination.read_bytes() != expected_bytes:
                raise ValueError(f"frozen input projection is stale: {target_path}")
        else:
            atomic_write_json(destination, document)
        report[target_path] = {
            "bytes": len(expected_bytes),
            "sha256": hashlib.sha256(expected_bytes).hexdigest(),
        }

    oracle_catalog = documents["oracles/catalog.json"]
    entries = oracle_catalog.get("entries", [])
    if len(entries) != 16:
        raise ValueError("frozen oracle catalogue must contain exactly sixteen entries")
    for index, entry in enumerate(entries):
        sid = f"S{index:02d}"
        oracle_path = f"oracles/{sid}.expected.json"
        if (
            entry.get("oracle_id") != f"{sid}.expected"
            or entry.get("scenario_id") != sid
            or entry.get("oracle_path") != oracle_path
            or entry.get("sha256") != report[oracle_path]["sha256"]
        ):
            raise ValueError(f"frozen oracle catalogue hash mismatch for {sid}")

    for row in builder.rows:
        if (
            row["target_path"] in FROZEN_INPUT_PATHS
            and row["materialization_status"] not in {"excluded", "superseded"}
        ):
            row["materialization_status"] = "materialized_t03"
            row["materialization_refs"] = row["target_path"]
    return report


def materialize_build_contract_documents(
    builder: LedgerBuilder, *, check_only: bool
) -> dict[str, dict[str, Any]]:
    """Materialize the authored recipe and DAG, never the future build record."""
    documents = build_contract_documents(builder)
    report: dict[str, dict[str, Any]] = {}
    for target_path in sorted(T03_3_7_BUILD_CONTRACT_PATHS):
        expected = documents[target_path]
        reconstructed = reconstruct_pointer_document(builder.rows, target_path)
        if reconstructed != expected:
            raise ValueError(
                f"cannot materialize an inconsistent build contract: {target_path}"
            )
        destination = builder.root / target_path
        expected_bytes = (canonical_json(expected) + "\n").encode("utf-8")
        if check_only:
            if not destination.is_file():
                raise ValueError(f"required build contract is missing: {target_path}")
            if destination.read_bytes() != expected_bytes:
                raise ValueError(f"materialized build contract is stale: {target_path}")
        else:
            atomic_write_json(destination, expected)
        report[target_path] = {
            "bytes": len(expected_bytes),
            "sha256": hashlib.sha256(expected_bytes).hexdigest(),
        }
    for row in builder.rows:
        if (
            row["target_path"] in T03_3_7_BUILD_CONTRACT_PATHS
            and row["materialization_status"] not in {"excluded", "superseded"}
        ):
            row["materialization_status"] = "materialized_t03"
            row["materialization_refs"] = row["target_path"]
    return report


def build(
    root: Path,
    wait_seconds: float,
    check_only: bool,
    materialize_configuration: bool,
    materialize_schemas: bool,
    materialize_frozen_inputs: bool,
    materialize_build_contracts: bool,
) -> dict[str, Any]:
    provenance, sources = read_stable_inputs(root, wait_seconds)
    ledger_path = root / "sources" / "DERIVATION_LEDGER.csv"
    existing = load_existing_rows(ledger_path, evidence_map(sources))
    builder = LedgerBuilder(root, provenance, sources, existing)

    for row in existing:
        if rebuild_filter(row["derivation_id"]):
            continue
        if row["target_path"] == "spec/decisions/engineering_v1.1.0.json" and row["support_ref_type"] != "approved_decision":
            continue
        builder.keep(row)

    add_host_layer_rows(builder)
    add_decision_contract_rows(builder)
    add_rule_rows(builder)
    add_bindings_and_limits(builder)
    add_scenarios_oracles_and_tests(builder)
    add_sadness_fixture(builder)
    add_trace_contract_rows(builder)
    add_build_contract_rows(builder)
    add_schema_contract_rows(builder)
    add_artifact_minimums(builder)
    add_missing_path_recipes(builder)
    materialized_code = register_t03_3_6_code_materialization(builder)
    materialized_executables = register_t03_3_7_executable_materialization(builder)
    source_manifest = register_source_manifest_materialization(builder)
    add_legacy_audit_rows(builder)
    materialized_documents: dict[str, dict[str, Any]] = {}
    if materialize_configuration:
        materialized_documents = materialize_configuration_documents(
            builder, check_only=check_only
        )
    materialized_schemas: dict[str, dict[str, Any]] = {}
    if materialize_schemas:
        materialized_schemas = materialize_schema_documents(
            builder, check_only=check_only
        )
    materialized_frozen_inputs: dict[str, dict[str, Any]] = {}
    if materialize_frozen_inputs:
        materialized_frozen_inputs = materialize_frozen_input_documents(
            builder, check_only=check_only
        )
    materialized_build_contracts: dict[str, dict[str, Any]] = {}
    if materialize_build_contracts:
        materialized_build_contracts = materialize_build_contract_documents(
            builder, check_only=check_only
        )
    metrics = validate_rows(builder)
    metrics["configuration_documents"] = materialized_documents
    metrics["schema_documents"] = materialized_schemas
    metrics["frozen_input_documents"] = materialized_frozen_inputs
    metrics["implementation_and_test_modules"] = materialized_code
    metrics["t03_3_7_executables"] = materialized_executables
    metrics["t03_3_7_build_contracts"] = materialized_build_contracts
    metrics["source_manifest"] = source_manifest
    if not check_only:
        atomic_write_csv(ledger_path, builder.rows)
        metrics["sha256"] = sha256_path(ledger_path)
        metrics["bytes"] = ledger_path.stat().st_size
    else:
        metrics["sha256"] = None
        metrics["bytes"] = None
    return metrics


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="package root (defaults to the parent of scripts/)",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=180.0,
        help="maximum time to wait for a stable, updated PROVENANCE/SOURCES snapshot",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="build and validate in memory without replacing DERIVATION_LEDGER.csv",
    )
    parser.add_argument(
        "--materialize-bindings-config",
        action="store_true",
        help=(
            "materialize formula_bindings.json and resolved_instance.json from "
            "their closed ledger projections"
        ),
    )
    parser.add_argument(
        "--materialize-schemas",
        action="store_true",
        help="materialize the fifteen T03.3-5 schemas from their ledger projections",
    )
    parser.add_argument(
        "--materialize-frozen-inputs",
        action="store_true",
        help=(
            "materialize the sixteen scenarios, sixteen independent oracles, "
            "their catalogues, the exact test catalogue and the isolated "
            "symbolic sadness fixture/oracle before implementation"
        ),
    )
    parser.add_argument(
        "--materialize-build-contracts",
        action="store_true",
        help=(
            "materialize manifests/BUILD_RECIPE.json and "
            "manifests/GENERATION_TOPOLOGY.json without creating BUILD_RECORD.json"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        metrics = build(
            args.root.resolve(),
            args.wait_seconds,
            args.check_only,
            args.materialize_bindings_config,
            args.materialize_schemas,
            args.materialize_frozen_inputs,
            args.materialize_build_contracts,
        )
    except Exception as exc:  # noqa: BLE001 - command boundary reports a concise failure.
        print(f"build_derivation_ledger.py: ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
