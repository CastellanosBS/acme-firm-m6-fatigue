#!/usr/bin/env python3
"""Regenerate the T03 reference evidence transactionally after source freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import locale
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence


RUN_ID = "RUN-T03-REFERENCE-001"
SOURCE_MANIFEST = "manifests/SOURCE_SHA256.txt"
LOGICAL_EVALUATION_TIME = "2026-09-04T12:00:00Z"


class RegenerationError(RuntimeError):
    """A predecessor, command or staged evidence set failed closed."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


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


def source_manifest_report(root: Path) -> dict[str, Any]:
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
        raise RegenerationError(f"source-manifest gate failed: {detail}")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RegenerationError("source verifier emitted invalid JSON") from exc
    if report.get("status") != "verified" or report.get("records") != 90:
        raise RegenerationError("source verifier did not attest the closed 90-file gate")
    return report


def run_command(
    root: Path,
    command: Sequence[str],
    *,
    command_id: str,
    display: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    completed = subprocess.run(
        list(command),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    record = {
        "command_id": command_id,
        "command": display,
        "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
    }
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RegenerationError(f"{command_id} failed with exit {completed.returncode}: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RegenerationError(f"{command_id} emitted invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("status") != "pass":
        raise RegenerationError(f"{command_id} did not report pass")
    return record, payload


def expected_stage_paths() -> set[str]:
    return {
        *(f"results/reference_run/S{index:02d}.result.json" for index in range(16)),
        *(f"traces/reference_run/S{index:02d}.trace.json" for index in range(15)),
        "traces/reference_run/rejections/S15.rejection.json",
        "results/reference_run/conformance_summary.json",
        "results/reference_run/conformance_matrix.csv",
        "results/reference_run/unit_test_summary.json",
        "results/reference_run/run_metadata.json",
        "logs/reference_run/commands.jsonl",
        "logs/reference_run/scenarios.log",
        "logs/reference_run/unittest.log",
        "environment/runtime.txt",
        "environment/reference_environment.json",
    }


def observed_environment() -> dict[str, Any]:
    locale_name = locale.setlocale(locale.LC_ALL, None)
    return {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "implementation": "Python",
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "machine": platform.machine(),
        "locale": locale_name,
        "encoding": "UTF-8",
        "network_used": False,
        "randomness_used": False,
        "system_clock_used_by_tested_logic": False,
        "evaluation_time_source": "injected_scenario_field",
        "logical_evaluation_time": LOGICAL_EVALUATION_TIME,
        "dependency_policy": "Python_standard_library_only",
    }


def materialize_environment(stage: Path, environment: dict[str, Any]) -> None:
    atomic_write(
        stage / "environment/reference_environment.json",
        (canonical_json(environment) + "\n").encode("utf-8"),
    )
    lines = [
        f"run_id={RUN_ID}",
        f"python_implementation={environment['python_implementation']}",
        f"python_version={environment['python_version']}",
        f"platform_system={environment['platform_system']}",
        f"platform_release={environment['platform_release']}",
        f"machine={environment['machine']}",
        f"locale={environment['locale']}",
        "encoding=UTF-8",
        "dependency_policy=Python_standard_library_only",
        "network_used=false",
        "randomness_used=false",
        "system_clock_used_by_tested_logic=false",
        "evaluation_time_source=injected_scenario_field",
        f"logical_evaluation_time={LOGICAL_EVALUATION_TIME}",
    ]
    atomic_write(stage / "environment/runtime.txt", ("\n".join(lines) + "\n").encode("utf-8"))


def commit_stage(stage: Path, root: Path, expected: set[str]) -> None:
    actual = {
        path.relative_to(stage).as_posix()
        for path in stage.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        raise RegenerationError(
            f"staged evidence membership mismatch; missing={sorted(expected-actual)}, "
            f"unexpected={sorted(actual-expected)}"
        )
    groups = [
        Path("results/reference_run"),
        Path("traces/reference_run"),
        Path("logs/reference_run"),
        Path("environment"),
    ]
    transaction = Path(tempfile.mkdtemp(prefix=".ifm6-evidence-backup-", dir=root))
    installed: list[Path] = []
    backed_up: list[Path] = []
    try:
        for relative in groups:
            source = stage / relative
            destination = root / relative
            backup = transaction / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, backup)
                backed_up.append(relative)
            os.replace(source, destination)
            installed.append(relative)
    except Exception:
        for relative in reversed(installed):
            destination = root / relative
            if destination.exists():
                shutil.rmtree(destination)
        for relative in reversed(backed_up):
            backup = transaction / relative
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                os.replace(backup, destination)
        raise
    finally:
        shutil.rmtree(transaction, ignore_errors=True)


def regenerate(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise RegenerationError(f"package root is not a directory: {root}")
    source_report = source_manifest_report(root)
    temporary = Path(tempfile.mkdtemp(prefix=".ifm6-evidence-", dir=root))
    try:
        scenario_command = [
            sys.executable,
            "-I",
            "-B",
            "-X",
            "utf8",
            "scripts/run_scenarios.py",
            "--root",
            ".",
            "--output-root",
            str(temporary),
        ]
        test_command = [
            sys.executable,
            "-I",
            "-B",
            "-X",
            "utf8",
            "scripts/run_tests.py",
            "--root",
            ".",
            "--output-root",
            str(temporary),
        ]
        scenario_record, scenario_report = run_command(
            root,
            scenario_command,
            command_id="CMD-T03-REFERENCE-001",
            display="python3 -I -B -X utf8 scripts/run_scenarios.py --root . --output-root <staging>",
        )
        test_record, test_report = run_command(
            root,
            test_command,
            command_id="CMD-T03-REFERENCE-002",
            display="python3 -I -B -X utf8 scripts/run_tests.py --root . --output-root <staging>",
        )
        command_records = [
            {
                "command_id": "CMD-T03-SOURCE-GATE-001",
                "command": "python3 -I -B -X utf8 scripts/verify_manifest.py --root . --manifest manifests/SOURCE_SHA256.txt",
                "exit_code": 0,
                "manifest_sha256": source_report["manifest_sha256"],
            },
            scenario_record,
            test_record,
        ]
        atomic_write(
            temporary / "logs/reference_run/commands.jsonl",
            "".join(canonical_json(record) + "\n" for record in command_records).encode("utf-8"),
        )
        environment = observed_environment()
        materialize_environment(temporary, environment)
        metadata = {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "status": "pass",
            "logical_evaluation_time": LOGICAL_EVALUATION_TIME,
            "source_manifest_path": SOURCE_MANIFEST,
            "source_manifest_sha256": source_report["manifest_sha256"],
            "source_manifest_records": source_report["records"],
            "scenario_report": scenario_report,
            "unit_test_report": test_report,
            "command_exit_codes": [record["exit_code"] for record in command_records],
            "timing_metrics_recorded": False,
            "scope": "synthetic_contract_conformance_only",
        }
        atomic_write(
            temporary / "results/reference_run/run_metadata.json",
            (canonical_json(metadata) + "\n").encode("utf-8"),
        )
        expected = expected_stage_paths()
        commit_stage(temporary, root, expected)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return {
        "run_id": RUN_ID,
        "committed_files": len(expected_stage_paths()),
        "scenarios": 16,
        "tests": 18,
        "source_manifest_sha256": source_report["manifest_sha256"],
        "status": "pass",
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
        report = regenerate(args.root)
    except (RegenerationError, OSError, ValueError) as exc:
        print(f"regenerate_evidence.py: ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
