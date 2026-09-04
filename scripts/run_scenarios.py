#!/usr/bin/env python3
"""Execute the sixteen frozen scenarios only after the source-manifest gate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping


RUN_ID = "RUN-T03-REFERENCE-001"
SOURCE_MANIFEST = "manifests/SOURCE_SHA256.txt"
EXPECTED_IDS = [f"S{index:02d}" for index in range(16)]


class ScenarioRunError(RuntimeError):
    """The frozen reference recipe cannot be executed or compared safely."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def duplicate_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScenarioRunError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=duplicate_guard
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScenarioRunError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ScenarioRunError(f"{path} must contain a JSON object")
    return value


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
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    atomic_write(path, (canonical_json(dict(value)) + "\n").encode("utf-8"))


def verify_source_gate(root: Path) -> dict[str, Any]:
    command = [
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
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ScenarioRunError(f"source-manifest gate failed: {detail}")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ScenarioRunError("source-manifest verifier emitted invalid JSON") from exc
    if report.get("status") != "verified" or report.get("records") != 90:
        raise ScenarioRunError("source-manifest verifier did not attest the closed gate")
    return report


def scenario_entries(root: Path) -> list[dict[str, str]]:
    catalog = read_json(root / "scenarios/catalog.json")
    entries = catalog.get("entries")
    if (
        catalog.get("catalog_id") != "SCENARIOS-16"
        or catalog.get("expected_entry_count") != 16
        or not isinstance(entries, list)
        or len(entries) != 16
    ):
        raise ScenarioRunError("scenario catalog does not declare exactly sixteen entries")
    expected = [
        {
            "scenario_id": sid,
            "scenario_path": f"scenarios/{sid}.json",
            "oracle_path": f"oracles/{sid}.expected.json",
        }
        for sid in EXPECTED_IDS
    ]
    if entries != expected:
        raise ScenarioRunError("scenario catalog order or bindings are not canonical")
    return entries


def oracle_index(root: Path) -> dict[str, dict[str, str]]:
    catalog = read_json(root / "oracles/catalog.json")
    entries = catalog.get("entries")
    if (
        catalog.get("catalog_id") != "ORACLES-16"
        or catalog.get("expected_entry_count") != 16
        or not isinstance(entries, list)
        or len(entries) != 16
    ):
        raise ScenarioRunError("oracle catalog does not declare exactly sixteen entries")
    result: dict[str, dict[str, str]] = {}
    for index, entry in enumerate(entries):
        sid = f"S{index:02d}"
        expected_path = f"oracles/{sid}.expected.json"
        if not isinstance(entry, dict) or entry != {
            "oracle_id": f"{sid}.expected",
            "oracle_path": expected_path,
            "scenario_id": sid,
            "sha256": entry.get("sha256"),
        }:
            raise ScenarioRunError(f"oracle catalog binding is invalid for {sid}")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ScenarioRunError(f"oracle catalog hash is invalid for {sid}")
        actual = hashlib.sha256((root / expected_path).read_bytes()).hexdigest()
        if actual != digest:
            raise ScenarioRunError(f"frozen oracle hash mismatch for {sid}")
        result[sid] = entry
    return result


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


def load_runtime(root: Path):
    source = str(root / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    try:
        from ifatigue_infra6.canonical_json import canonical_bytes
        from ifatigue_infra6.runner import evaluate_scenario
    except (ImportError, SyntaxError) as exc:
        raise ScenarioRunError(f"cannot load reference implementation: {exc}") from exc
    return evaluate_scenario, canonical_bytes


def matrix_bytes(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "scenario_id",
            "disposition",
            "diagnostics",
            "oracle_match",
            "result_path",
            "trace_or_rejection_path",
        ],
        delimiter=",",
        quotechar='"',
        quoting=csv.QUOTE_ALL,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def execute(root: Path, output_root: Path) -> dict[str, Any]:
    root = root.resolve()
    output_root = output_root.resolve()
    gate = verify_source_gate(root)
    entries = scenario_entries(root)
    evaluate_scenario, canonical_bytes = load_runtime(root)
    config = read_json(root / "config/resolved_instance.json")

    # Phase 1 deliberately computes every outcome without reading any oracle.
    outcomes: dict[str, Any] = {}
    scenarios: dict[str, dict[str, Any]] = {}
    for entry in entries:
        sid = entry["scenario_id"]
        scenario = read_json(root / entry["scenario_path"])
        if scenario.get("scenario_id") != sid:
            raise ScenarioRunError(f"scenario identity mismatch for {sid}")
        scenarios[sid] = scenario
        outcomes[sid] = evaluate_scenario(scenario, config)

    # Phase 2 reads independent frozen oracles and compares exact projections.
    indexes = oracle_index(root)
    comparisons: list[dict[str, Any]] = []
    failures: list[str] = []
    for sid in EXPECTED_IDS:
        oracle = read_json(root / indexes[sid]["oracle_path"])
        if oracle.get("scenario_id") != sid or oracle.get("frozen_before_implementation") is not True:
            raise ScenarioRunError(f"oracle identity/freeze contract mismatch for {sid}")
        observed = oracle_projection(outcomes[sid].result)
        match = observed == oracle.get("expected")
        comparisons.append(
            {
                "scenario_id": sid,
                "match": match,
                "observed_sha256": hashlib.sha256(
                    canonical_bytes(observed)
                ).hexdigest(),
                "oracle_expected_sha256": hashlib.sha256(
                    canonical_bytes(oracle.get("expected"))
                ).hexdigest(),
            }
        )
        if not match:
            failures.append(sid)
    if failures:
        raise ScenarioRunError(f"oracle comparison failed for {failures}; no output written")

    for sid in EXPECTED_IDS:
        outcome = outcomes[sid]
        if sid == "S15":
            if outcome.trace is not None or outcome.rejection is None:
                raise ScenarioRunError("S15 must yield one rejection and no modulation trace")
        elif outcome.trace is None or outcome.rejection is not None:
            raise ScenarioRunError(f"{sid} must yield one trace and no rejection")

    matrix: list[dict[str, str]] = []
    log_lines: list[str] = []
    disposition_counts: dict[str, int] = {}
    for sid in EXPECTED_IDS:
        outcome = outcomes[sid]
        result_path = f"results/reference_run/{sid}.result.json"
        write_json(output_root / result_path, outcome.result)
        disposition = str(outcome.result["disposition"])
        disposition_counts[disposition] = disposition_counts.get(disposition, 0) + 1
        if sid == "S15":
            companion = "traces/reference_run/rejections/S15.rejection.json"
            write_json(output_root / companion, outcome.rejection)
        else:
            companion = f"traces/reference_run/{sid}.trace.json"
            write_json(output_root / companion, outcome.trace)
        diagnostic_text = "|".join(outcome.result["diagnostics"])
        matrix.append(
            {
                "scenario_id": sid,
                "disposition": disposition,
                "diagnostics": diagnostic_text,
                "oracle_match": "true",
                "result_path": result_path,
                "trace_or_rejection_path": companion,
            }
        )
        log_lines.append(
            f"{sid}\tPASS\t{disposition}\t{diagnostic_text or '-'}\t{companion}\n"
        )

    summary = {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "source_manifest_sha256": gate["manifest_sha256"],
        "scenario_count": 16,
        "oracle_match_count": 16,
        "trace_count": 15,
        "rejection_count": 1,
        "disposition_counts": dict(sorted(disposition_counts.items())),
        "comparisons": comparisons,
        "status": "pass",
        "scope": "synthetic_contract_conformance_only",
    }
    write_json(output_root / "results/reference_run/conformance_summary.json", summary)
    atomic_write(
        output_root / "results/reference_run/conformance_matrix.csv",
        matrix_bytes(matrix),
    )
    atomic_write(
        output_root / "logs/reference_run/scenarios.log",
        "".join(log_lines).encode("utf-8"),
    )
    return {
        "run_id": RUN_ID,
        "scenarios": 16,
        "oracle_matches": 16,
        "traces": 15,
        "rejections": 1,
        "source_manifest_sha256": gate["manifest_sha256"],
        "status": "pass",
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output-root", type=Path)
    values = parser.parse_args(list(argv) if argv is not None else None)
    values.output_root = values.output_root or values.root
    return values


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        report = execute(args.root, args.output_root)
    except (ScenarioRunError, OSError, ValueError) as exc:
        print(f"run_scenarios.py: ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
