#!/usr/bin/env python3
"""Validate the exact internal T03 QA verdict and its evidence.

``evidence_refs`` use one of these closed forms::

    relative/path
    relative/path#/json/pointer
    relative/path|sha256=<64 lowercase hexadecimal characters>
    relative/path#/json/pointer|sha256=<64 lowercase hexadecimal characters>

Paths are package-relative regular files.  A localizer is an RFC 6901 JSON
pointer; when present, the referenced file must be valid JSON and the pointer
must resolve.  A supplied digest always covers the complete referenced file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


PERSPECTIVES = {
    "science_design_and_doctoral_methodology",
    "affective_computing_and_appraisal",
    "software_architecture_and_engineering",
    "verification_testing_and_reproducibility",
    "construct_validity_ethics_and_data_protection",
    "open_science_metadata_intellectual_property_and_licensing",
}

EXPECTED_VALIDATORS = {
    "VAL-DERIVATION-LEDGER-001": (
        "python3 -I -B -X utf8 scripts/validate_derivation_ledger.py "
        "--ledger sources/DERIVATION_LEDGER.csv "
        "--schema schemas/derivation_ledger.schema.json "
        "--provenance PROVENANCE.json"
    ),
    "VAL-QG-PROVENANCE-001": (
        "python3 -I -B -X utf8 commands/validate_qa_verdict.py "
        "--record reviews/T03_INTERNAL_QA.json "
        "--schema schemas/qa_verdict.schema.json"
    ),
}
REQUIRED_APPROVALS = {"T03-MP-013", "T03-QG-014"}
APPROVED_DECISION_STATUSES = {
    "approved_by_author",
    "approved_under_standing_authorization",
    "imported_approved_decision",
}
DECISION_ID_PATTERN = re.compile(r"^T(?:0[0-9]|1[0-7])-[A-Z0-9-]+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SAFE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")
EXPECTED_RECORD_PATH = "reviews/T03_INTERNAL_QA.json"
EXPECTED_SCHEMA_PATH = "schemas/qa_verdict.schema.json"

# T05-IP-001 is an unresolved publication decision, not an approval.  It may
# only be acknowledged by the internal gate in this non-blocking form.
OPEN_DECISION_FINDING_POLICY = {
    "T05-IP-001": {
        "perspective": "open_science_metadata_intellectual_property_and_licensing",
        "severity": "observation",
        "status": "accepted_with_rationale",
    }
}


class VerdictError(RuntimeError):
    """The verdict document, schema or cross-field decision is invalid."""


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting ambiguous duplicate members."""

    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise VerdictError(f"duplicate JSON member: {key!r}")
        value[key] = item
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerdictError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VerdictError(f"{path} must contain a JSON object")
    return value


def package_file(package_root: Path, relative_path: str, *, label: str) -> Path:
    """Resolve one conservative POSIX package path without allowing escape."""

    if not isinstance(relative_path, str) or not relative_path:
        raise VerdictError(f"{label} must be a non-empty package-relative path")
    if (
        "\\" in relative_path
        or not SAFE_PATH_PATTERN.fullmatch(relative_path)
        or relative_path.startswith("/")
        or relative_path.endswith("/")
        or "//" in relative_path
    ):
        raise VerdictError(f"{label} is not a safe package-relative path: {relative_path!r}")
    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise VerdictError(f"{label} contains a prohibited path segment: {relative_path!r}")
    if PurePosixPath(relative_path).as_posix() != relative_path:
        raise VerdictError(f"{label} is not canonical POSIX syntax: {relative_path!r}")

    root = package_root.resolve(strict=True)
    lexical = root.joinpath(*parts)
    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise VerdictError(f"{label} does not resolve: {relative_path!r}: {exc}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise VerdictError(f"{label} escapes the package root: {relative_path!r}") from exc
    if not resolved.is_file():
        raise VerdictError(f"{label} is not a regular file: {relative_path!r}")
    return resolved


def checked_argument_file(package_root: Path, path: Path, *, label: str) -> Path:
    """Require a CLI path to resolve to a regular file inside the package."""

    root = package_root.resolve(strict=True)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise VerdictError(f"{label} does not resolve: {path}: {exc}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise VerdictError(f"{label} is outside the package root: {path}") from exc
    if not resolved.is_file():
        raise VerdictError(f"{label} is not a regular file: {path}")
    return resolved


def parse_evidence_ref(reference: str) -> tuple[str, str | None, str | None]:
    """Parse the closed evidence-reference grammar documented above."""

    if not isinstance(reference, str) or not reference:
        raise VerdictError("evidence reference must be a non-empty string")
    if reference.count("|sha256=") > 1:
        raise VerdictError(f"evidence reference has repeated SHA-256 clause: {reference!r}")
    body, separator, digest = reference.partition("|sha256=")
    if "|" in body or (not separator and "|" in reference):
        raise VerdictError(f"evidence reference has an unsupported clause: {reference!r}")
    expected_digest: str | None = None
    if separator:
        if not SHA256_PATTERN.fullmatch(digest):
            raise VerdictError(f"evidence reference has an invalid SHA-256: {reference!r}")
        expected_digest = digest

    if body.count("#") > 1:
        raise VerdictError(f"evidence reference has repeated localizer: {reference!r}")
    path_text, hash_mark, pointer = body.partition("#")
    json_pointer: str | None = None
    if hash_mark:
        if not pointer.startswith("/"):
            raise VerdictError(
                f"evidence localizer must be an RFC 6901 JSON pointer: {reference!r}"
            )
        json_pointer = pointer
    return path_text, json_pointer, expected_digest


def decode_pointer_token(token: str, reference: str) -> str:
    if re.search(r"~(?:[^01]|$)", token):
        raise VerdictError(f"invalid RFC 6901 escape in evidence reference: {reference!r}")
    return token.replace("~1", "/").replace("~0", "~")


def resolve_json_pointer(value: Any, pointer: str, reference: str) -> Any:
    """Resolve an RFC 6901 pointer over JSON objects and arrays."""

    current = value
    for raw_token in pointer[1:].split("/"):
        token = decode_pointer_token(raw_token, reference)
        if isinstance(current, dict):
            if token not in current:
                raise VerdictError(f"unresolved evidence pointer: {reference!r}")
            current = current[token]
        elif isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise VerdictError(f"invalid array index in evidence pointer: {reference!r}")
            index = int(token)
            if index >= len(current):
                raise VerdictError(f"array index out of range in evidence pointer: {reference!r}")
            current = current[index]
        else:
            raise VerdictError(f"evidence pointer traverses a scalar: {reference!r}")
    return current


def resolve_evidence_ref(
    package_root: Path, reference: str, *, label: str
) -> tuple[Path, Any | None]:
    """Resolve and, when declared, hash-check/localize one evidence file."""

    path_text, pointer, expected_digest = parse_evidence_ref(reference)
    path = package_file(package_root, path_text, label=label)
    content = path.read_bytes()
    if expected_digest is not None:
        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != expected_digest:
            raise VerdictError(
                f"{label} SHA-256 mismatch for {path_text!r}: "
                f"expected {expected_digest}, got {actual_digest}"
            )
    if pointer is None:
        return path, None
    try:
        document = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerdictError(
            f"{label} uses a JSON pointer but {path_text!r} is not valid JSON: {exc}"
        ) from exc
    return path, resolve_json_pointer(document, pointer, reference)


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


def resolve_ref(root: dict[str, Any], reference: str) -> Any:
    if reference == "#":
        return root
    if not reference.startswith("#/"):
        raise VerdictError(f"only local schema references are supported: {reference}")
    value: Any = root
    for raw in reference[2:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            raise VerdictError(f"unresolved schema reference: {reference}")
        value = value[token]
    return value


def validate_instance(
    value: Any,
    schema: Any,
    *,
    root: dict[str, Any],
    location: str = "$",
    depth: int = 0,
) -> list[str]:
    if depth > 100:
        return [f"{location}: schema recursion limit exceeded"]
    if schema is True:
        return []
    if schema is False:
        return [f"{location}: false schema matched"]
    if not isinstance(schema, dict):
        return [f"{location}: schema node is not an object"]
    errors: list[str] = []
    if "$ref" in schema:
        errors.extend(
            validate_instance(
                value,
                resolve_ref(root, schema["$ref"]),
                root=root,
                location=location,
                depth=depth + 1,
            )
        )
    for keyword in ("allOf",):
        if isinstance(schema.get(keyword), list):
            for branch in schema[keyword]:
                errors.extend(
                    validate_instance(
                        value,
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
                not validate_instance(
                    value,
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
        required = schema.get("required", [])
        if isinstance(required, list):
            errors.extend(
                f"{location}: missing {key!r}" for key in required if key not in value
            )
        properties = schema.get("properties", {})
        properties = properties if isinstance(properties, dict) else {}
        for key, subschema in properties.items():
            if key in value:
                errors.extend(
                    validate_instance(
                        value[key],
                        subschema,
                        root=root,
                        location=f"{location}.{key}",
                        depth=depth + 1,
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
                    validate_instance(
                        item,
                        schema["items"],
                        root=root,
                        location=f"{location}[{index}]",
                        depth=depth + 1,
                    )
                )
    if isinstance(value, str):
        if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
            errors.append(f"{location}: shorter than minLength")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{location}: pattern mismatch")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{location}: below minimum")
    return errors


def indexed_decisions(
    provenance: dict[str, Any], field: str
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Index a decision list while reporting structural ambiguity."""

    errors: list[str] = []
    values = provenance.get(field)
    if not isinstance(values, list):
        return {}, [f"PROVENANCE.json {field!r} must be an array"]
    indexed: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            errors.append(f"PROVENANCE.json {field}[{index}] must be an object")
            continue
        decision_id = item.get("id")
        if not isinstance(decision_id, str) or not DECISION_ID_PATTERN.fullmatch(decision_id):
            errors.append(f"PROVENANCE.json {field}[{index}] has an invalid decision id")
            continue
        if decision_id in indexed:
            errors.append(f"PROVENANCE.json repeats decision {decision_id!r} in {field}")
            continue
        indexed[decision_id] = item
    return indexed, errors


def approved_validator_registry(
    approved: dict[str, dict[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    """Resolve the validator registry from T03-MP-013 and pin its exact values."""

    errors: list[str] = []
    mp = approved.get("T03-MP-013", {})
    try:
        validators = mp["decision"]["validator_registry"]["validators"]
    except (KeyError, TypeError):
        return {}, ["T03-MP-013 does not contain the approved validator registry"]
    if not isinstance(validators, list):
        return {}, ["T03-MP-013 validator registry must be an array"]
    registry: dict[str, str] = {}
    for index, item in enumerate(validators):
        if not isinstance(item, dict):
            errors.append(f"T03-MP-013 validator registry item {index} is not an object")
            continue
        validator_id = item.get("validator_id")
        command = item.get("validator_command")
        if not isinstance(validator_id, str) or not isinstance(command, str):
            errors.append(f"T03-MP-013 validator registry item {index} is malformed")
            continue
        if validator_id in registry:
            errors.append(f"T03-MP-013 repeats validator id {validator_id!r}")
            continue
        registry[validator_id] = command
    if registry != EXPECTED_VALIDATORS:
        errors.append("T03-MP-013 does not register the two pinned validator IDs/commands")

    qg = approved.get("T03-QG-014", {})
    try:
        qg_command = qg["decision"]["required_output"]["validator_command"]
    except (KeyError, TypeError):
        errors.append("T03-QG-014 does not declare its QA validator command")
    else:
        if qg_command != EXPECTED_VALIDATORS["VAL-QG-PROVENANCE-001"]:
            errors.append("T03-QG-014 QA validator command differs from the pinned command")
    return registry, errors


def validate_validator_records(
    records: list[Any], expected: dict[str, str]
) -> tuple[dict[str, str], list[str]]:
    """Validate exact registry membership and status/exit-code coherence."""

    errors: list[str] = []
    actual: dict[str, str] = {}
    states: dict[str, str] = {}
    if len(records) != len(expected):
        errors.append(f"validator_records must contain exactly {len(expected)} validators")
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            errors.append(f"validator_records[{index}] must be an object")
            continue
        validator_id = item.get("validator_id")
        command = item.get("validator_command")
        if not isinstance(validator_id, str) or not isinstance(command, str):
            errors.append(f"validator_records[{index}] has an invalid id or command")
            continue
        if validator_id in actual:
            errors.append(f"validator_records repeats validator id {validator_id!r}")
            continue
        actual[validator_id] = command
        status = item.get("execution_status")
        exit_code = item.get("exit_code")
        states[validator_id] = status if isinstance(status, str) else "invalid"
        if status == "not_run":
            if exit_code is not None:
                errors.append(f"{validator_id}: not_run requires a null exit_code")
        elif status == "pass":
            if exit_code != 0:
                errors.append(f"{validator_id}: pass requires exit_code 0")
        elif status == "fail":
            if not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code <= 0:
                errors.append(f"{validator_id}: fail requires a positive nonzero exit_code")
        else:
            errors.append(f"{validator_id}: invalid execution_status")
    if actual != expected:
        errors.append("validator_records does not match the two approved validator IDs/commands")
    return states, errors


def validate_approval_refs(
    references: list[Any],
    approved: dict[str, dict[str, Any]],
    open_decisions: dict[str, dict[str, Any]],
) -> list[str]:
    """Require real, currently approved decisions; open items are not approvals."""

    errors: list[str] = []
    reference_ids = {item for item in references if isinstance(item, str)}
    missing = sorted(REQUIRED_APPROVALS - reference_ids)
    if missing:
        errors.append(f"approval_refs omits required contract decisions: {missing}")
    for reference in references:
        if not isinstance(reference, str) or not DECISION_ID_PATTERN.fullmatch(reference):
            errors.append(f"invalid approval reference: {reference!r}")
            continue
        if reference in open_decisions:
            errors.append(f"open decision {reference!r} cannot be used as an approval")
            continue
        decision = approved.get(reference)
        if decision is None:
            errors.append(f"approval reference does not resolve: {reference!r}")
        elif decision.get("status") not in APPROVED_DECISION_STATUSES:
            errors.append(
                f"approval reference {reference!r} has non-approved status "
                f"{decision.get('status')!r}"
            )
    return errors


def validate_open_decision_finding(
    finding: dict[str, Any], decision_id: str
) -> list[str]:
    policy = OPEN_DECISION_FINDING_POLICY.get(decision_id)
    if policy is None:
        return [f"open decision {decision_id!r} has no authorized QA finding policy"]
    errors = [
        f"open decision {decision_id!r} may only be recorded as "
        "an open-science observation accepted_with_rationale"
        for key, expected in policy.items()
        if finding.get(key) != expected
    ]
    return errors[:1]


def validate_semantics(record: dict[str, Any], package_root: Path) -> list[str]:
    errors: list[str] = []
    try:
        reviewed = package_file(
            package_root,
            record.get("reviewed_object_path", ""),
            label="reviewed_object_path",
        )
    except VerdictError as exc:
        return [str(exc)]
    if hashlib.sha256(reviewed.read_bytes()).hexdigest() != record.get(
        "reviewed_object_sha256"
    ):
        errors.append("reviewed object SHA-256 mismatch")
    try:
        provenance = read_json(reviewed)
    except VerdictError as exc:
        return errors + [str(exc)]

    approved, approved_errors = indexed_decisions(provenance, "decisions")
    open_decisions, open_errors = indexed_decisions(provenance, "open_decisions")
    errors.extend(approved_errors)
    errors.extend(open_errors)
    overlap = sorted(set(approved) & set(open_decisions))
    if overlap:
        errors.append(f"PROVENANCE.json lists decisions as both approved and open: {overlap}")
    for required_id in REQUIRED_APPROVALS:
        decision = approved.get(required_id)
        if decision is None:
            errors.append(f"PROVENANCE.json lacks required decision {required_id!r}")
        elif decision.get("status") not in APPROVED_DECISION_STATUSES:
            errors.append(f"required decision {required_id!r} is not approved")

    expected_validators, registry_errors = approved_validator_registry(approved)
    errors.extend(registry_errors)
    qg = approved.get("T03-QG-014", {}).get("decision", {})
    if not isinstance(qg, dict):
        errors.append("T03-QG-014 decision payload is malformed")
        qg = {}
    if record.get("gate_id") != qg.get("gate_id"):
        errors.append("gate_id differs from T03-QG-014")
    required_perspectives = qg.get("required_perspectives")
    if (
        not isinstance(required_perspectives, list)
        or len(required_perspectives) != len(PERSPECTIVES)
        or set(required_perspectives) != PERSPECTIVES
    ):
        errors.append("T03-QG-014 does not declare exactly the six pinned perspectives")
    errors.extend(
        validate_approval_refs(record.get("approval_refs", []), approved, open_decisions)
    )

    statuses = record.get("perspective_statuses", [])
    actual_perspectives = {
        item.get("perspective") for item in statuses if isinstance(item, dict)
    }
    if actual_perspectives != PERSPECTIVES:
        errors.append("the six required perspectives are not represented exactly once")
    validators = record.get("validator_records", [])
    findings = record.get("findings", [])
    verdict = record.get("verdict")
    if not isinstance(validators, list):
        validators = []
    validator_states, validator_errors = validate_validator_records(
        validators, expected_validators
    )
    errors.extend(validator_errors)

    minor_outstanding = False
    observation_requiring_action = False
    for index, finding in enumerate(findings if isinstance(findings, list) else []):
        if not isinstance(finding, dict):
            continue
        severity = finding.get("severity")
        status = finding.get("status")
        if severity in {"blocker", "major"} and status not in {
            "resolved",
            "not_applicable",
        }:
            errors.append(
                f"findings[{index}]: blocker/major must be resolved or not_applicable"
            )
        if severity == "minor" and status in {"open", "accepted_with_rationale"}:
            minor_outstanding = True
        if (
            severity == "observation"
            and status in {"open", "accepted_with_rationale"}
            and bool(finding.get("required_action"))
        ):
            observation_requiring_action = True

        evidence_refs = finding.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            errors.append(f"findings[{index}]: at least one evidence_ref is required")
            continue
        touched_open_decisions: set[str] = set()
        for evidence_index, reference in enumerate(evidence_refs):
            try:
                _, localized = resolve_evidence_ref(
                    package_root,
                    reference,
                    label=f"findings[{index}].evidence_refs[{evidence_index}]",
                )
            except VerdictError as exc:
                errors.append(str(exc))
                continue
            if isinstance(localized, dict):
                localized_id = localized.get("id")
                if isinstance(localized_id, str) and localized_id in open_decisions:
                    touched_open_decisions.add(localized_id)
            elif isinstance(localized, str) and localized in open_decisions:
                touched_open_decisions.add(localized)

        object_ref = finding.get("object_ref")
        if isinstance(object_ref, str) and DECISION_ID_PATTERN.fullmatch(object_ref):
            if object_ref in open_decisions:
                touched_open_decisions.add(object_ref)
            elif object_ref not in approved:
                errors.append(f"findings[{index}]: object_ref decision does not resolve")
        for decision_id in sorted(touched_open_decisions):
            errors.extend(validate_open_decision_finding(finding, decision_id))

    perspective_pending = any(
        isinstance(item, dict) and item.get("status") == "not_run" for item in statuses
    )
    perspectives_complete = bool(statuses) and all(
        isinstance(item, dict) and item.get("status") in {"complete", "not_applicable"}
        for item in statuses
    )
    validator_failed = any(state == "fail" for state in validator_states.values())
    validators_pending = any(state == "not_run" for state in validator_states.values())
    validators_pass = (
        len(validator_states) == len(EXPECTED_VALIDATORS)
        and all(state == "pass" for state in validator_states.values())
    )

    if validator_failed:
        expected_verdict = "fail"
    elif validators_pending or perspective_pending or not perspectives_complete:
        expected_verdict = "not_run"
    elif validators_pass and minor_outstanding:
        expected_verdict = "pass_with_minor"
    elif validators_pass and not observation_requiring_action:
        expected_verdict = "pass"
    else:
        expected_verdict = None
    if expected_verdict is None:
        errors.append(
            "verdict prerequisites are inconsistent: an outstanding observation "
            "requiring action must be resolved, made not_applicable or classified as minor"
        )
    elif verdict != expected_verdict:
        errors.append(
            f"verdict {verdict!r} conflicts with T03-QG-014; expected {expected_verdict!r}"
        )
    return errors


def validate(record_path: Path, schema_path: Path, package_root: Path) -> dict[str, Any]:
    root = package_root.resolve(strict=True)
    if not root.is_dir():
        raise VerdictError(f"package root is not a directory: {package_root}")
    record_path = checked_argument_file(root, record_path, label="record path")
    schema_path = checked_argument_file(root, schema_path, label="schema path")
    expected_record = package_file(root, EXPECTED_RECORD_PATH, label="required QA record")
    expected_schema = package_file(root, EXPECTED_SCHEMA_PATH, label="required QA schema")
    if record_path != expected_record:
        raise VerdictError(f"record path must be {EXPECTED_RECORD_PATH!r}")
    if schema_path != expected_schema:
        raise VerdictError(f"schema path must be {EXPECTED_SCHEMA_PATH!r}")

    record = read_json(record_path)
    schema = read_json(schema_path)
    schema_errors = validate_instance(record, schema, root=schema)
    semantic_errors = validate_semantics(record, root)
    errors = schema_errors + semantic_errors
    if errors:
        raise VerdictError(f"QA verdict rejected: {errors}")
    return {
        "gate_id": record["gate_id"],
        "reviewed_object_path": record["reviewed_object_path"],
        "reviewed_object_sha256": record["reviewed_object_sha256"],
        "perspectives": len(record["perspective_statuses"]),
        "validators": len(record["validator_records"]),
        "findings": len(record["findings"]),
        "verdict": record["verdict"],
        "status": "pass",
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    package_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, default=package_root)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    values = parser.parse_args(list(argv) if argv is not None else None)
    values.package_root = values.package_root.resolve()
    values.record = (
        values.record if values.record.is_absolute() else values.package_root / values.record
    ).resolve()
    values.schema = (
        values.schema if values.schema.is_absolute() else values.package_root / values.schema
    ).resolve()
    return values


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        report = validate(args.record, args.schema, args.package_root)
    except (VerdictError, OSError, ValueError) as exc:
        print(f"validate_qa_verdict.py: ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
