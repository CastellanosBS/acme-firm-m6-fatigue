#!/usr/bin/env python3
"""Independently compare generated results, traces and test summary to contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping


SOURCE_MANIFEST = "manifests/SOURCE_SHA256.txt"
EXPECTED_IDS = [f"S{index:02d}" for index in range(16)]


class ComparisonError(RuntimeError):
    """Generated evidence is absent, extra, malformed or nonconformant."""


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
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ComparisonError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ComparisonError(f"{path} must contain a JSON object")
    return value


def verify_source_gate(root: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-X",
            "utf8",
            "scripts/verify_manifest.py",
            "--root",
            ".",
            "--manifest",
            SOURCE_MANIFEST,
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise ComparisonError(completed.stderr.strip() or "source-manifest gate failed")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ComparisonError("source verifier emitted invalid JSON") from exc
    if report.get("status") != "verified" or report.get("records") != 90:
        raise ComparisonError("source verifier did not attest the closed gate")
    return report


def oracle_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    output_exists = "output" in result
    output_contract: dict[str, Any] = {"exists": output_exists}
    if output_exists:
        output_contract.update(
            {
                "appraisal_vector": result["output"],
                "protected_dimensions": "equal_to_scenario_baseline",
            }
        )
    required = {
        "classification",
        "diagnostics",
        "disposition",
        "factor_validation_performed",
        "modulation",
        "modulation_trace",
        "rejection_record",
    }
    missing = sorted(required - set(result))
    if missing:
        raise ComparisonError(f"result is missing required fields: {missing}")
    return {
        "classification": result["classification"],
        "diagnostics": result["diagnostics"],
        "disposition": result["disposition"],
        "factor_validation_performed": result["factor_validation_performed"],
        "modulation": result["modulation"],
        "modulation_trace": result["modulation_trace"],
        "output_contract": output_contract,
        "rejection_record": result["rejection_record"],
    }


def exact_json_set(directory: Path, pattern: str) -> set[str]:
    if not directory.is_dir():
        return set()
    return {path.name for path in directory.glob(pattern) if path.is_file()}


def compare(root: Path) -> dict[str, Any]:
    root = root.resolve()
    gate = verify_source_gate(root)
    expected_results = {f"{sid}.result.json" for sid in EXPECTED_IDS}
    actual_results = exact_json_set(root / "results/reference_run", "S*.result.json")
    expected_traces = {f"{sid}.trace.json" for sid in EXPECTED_IDS[:-1]}
    actual_traces = exact_json_set(root / "traces/reference_run", "S*.trace.json")
    expected_rejections = {"S15.rejection.json"}
    actual_rejections = exact_json_set(
        root / "traces/reference_run/rejections", "S*.rejection.json"
    )
    set_failures = {
        "results": {
            "missing": sorted(expected_results - actual_results),
            "unexpected": sorted(actual_results - expected_results),
        },
        "traces": {
            "missing": sorted(expected_traces - actual_traces),
            "unexpected": sorted(actual_traces - expected_traces),
        },
        "rejections": {
            "missing": sorted(expected_rejections - actual_rejections),
            "unexpected": sorted(actual_rejections - expected_rejections),
        },
    }
    if any(value["missing"] or value["unexpected"] for value in set_failures.values()):
        raise ComparisonError(f"generated evidence set mismatch: {set_failures}")

    source_path = str(root / "src")
    if source_path not in sys.path:
        sys.path.insert(0, source_path)
    try:
        from ifatigue_infra6.trace import trace_id_is_valid
    except (ImportError, SyntaxError) as exc:
        raise ComparisonError(f"cannot load trace verifier: {exc}") from exc

    comparisons: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for sid in EXPECTED_IDS:
        scenario = read_json(root / f"scenarios/{sid}.json")
        oracle_path = root / f"oracles/{sid}.expected.json"
        oracle = read_json(oracle_path)
        result = read_json(root / f"results/reference_run/{sid}.result.json")
        reasons: list[str] = []
        if scenario.get("scenario_id") != sid or oracle.get("scenario_id") != sid:
            reasons.append("input_identity_mismatch")
        if result.get("scenario_id") != sid:
            reasons.append("result_identity_mismatch")
        if result.get("evaluation_time") != scenario.get("evaluation_time"):
            reasons.append("evaluation_time_mismatch")
        if oracle_projection(result) != oracle.get("expected"):
            reasons.append("oracle_projection_mismatch")
        if sid == "S15":
            rejection = read_json(
                root / "traces/reference_run/rejections/S15.rejection.json"
            )
            expected_rejection = {
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
            if rejection != expected_rejection:
                reasons.append("rejection_contract_mismatch")
        else:
            trace = read_json(root / f"traces/reference_run/{sid}.trace.json")
            if not trace_id_is_valid(trace):
                reasons.append("trace_id_mismatch")
            if (
                trace.get("scenario_id") != sid
                or trace.get("evaluation_time") != result.get("evaluation_time")
                or trace.get("disposition") != result.get("disposition")
                or trace.get("diagnostics") != result.get("diagnostics")
            ):
                reasons.append("trace_wrapper_mismatch")
            core = trace.get("trace_core", {})
            if (
                not isinstance(core, dict)
                or set(core)
                != {
                    "event",
                    "state",
                    "baseline",
                    "output",
                    "policy",
                    "mask",
                    "formula",
                    "classification",
                    "versions",
                }
                or core.get("event") != scenario.get("event")
                or core.get("state") != scenario.get("factor_state")
                or core.get("baseline") != scenario.get("baseline")
                or core.get("output") != result.get("output")
            ):
                reasons.append("trace_core_binding_mismatch")
        record = {
            "scenario_id": sid,
            "match": not reasons,
            "result_sha256": hashlib.sha256(
                (root / f"results/reference_run/{sid}.result.json").read_bytes()
            ).hexdigest(),
            "oracle_sha256": hashlib.sha256(oracle_path.read_bytes()).hexdigest(),
        }
        comparisons.append(record)
        failures.extend({"scenario_id": sid, "reason": reason} for reason in reasons)

    test_summary = read_json(root / "results/reference_run/unit_test_summary.json")
    counts = test_summary.get("counts", {})
    if (
        test_summary.get("status") != "pass"
        or test_summary.get("expected_test_methods") != 18
        or test_summary.get("executed_test_methods") != 18
        or not isinstance(counts, dict)
        or counts.get("pass") != 18
        or sum(value for value in counts.values() if isinstance(value, int)) != 18
    ):
        failures.append({"scenario_id": "UNIT_TESTS", "reason": "unit_test_summary_mismatch"})
    conformance = read_json(root / "results/reference_run/conformance_summary.json")
    if (
        conformance.get("status") != "pass"
        or conformance.get("scenario_count") != 16
        or conformance.get("oracle_match_count") != 16
        or conformance.get("trace_count") != 15
        or conformance.get("rejection_count") != 1
    ):
        failures.append({"scenario_id": "SUMMARY", "reason": "conformance_summary_mismatch"})
    if failures:
        raise ComparisonError(f"output comparison findings: {failures}")
    return {
        "source_manifest_sha256": gate["manifest_sha256"],
        "scenario_comparisons": comparisons,
        "scenario_matches": 16,
        "trace_ids_verified": 15,
        "rejections_verified": 1,
        "unit_tests_verified": 18,
        "status": "pass",
        "scope": "synthetic_contract_conformance_only",
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        report = compare(args.root)
    except (ComparisonError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"compare_outputs.py: ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
