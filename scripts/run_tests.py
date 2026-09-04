#!/usr/bin/env python3
"""Run exactly UT-001..UT-018 in frozen catalogue order after the source gate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, Iterable


RUN_ID = "RUN-T03-REFERENCE-001"
SOURCE_MANIFEST = "manifests/SOURCE_SHA256.txt"


class TestRunError(RuntimeError):
    """The frozen unit-test recipe cannot be executed safely."""


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
        raise TestRunError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TestRunError(f"{path} must contain a JSON object")
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
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise TestRunError(f"source-manifest gate failed: {detail}")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise TestRunError("source-manifest verifier emitted invalid JSON") from exc
    if report.get("status") != "verified" or report.get("records") != 90:
        raise TestRunError("source-manifest verifier did not attest the closed gate")
    return report


def catalog_entries(root: Path) -> list[dict[str, Any]]:
    catalog = read_json(root / "tests/test_catalog.json")
    entries = catalog.get("test_catalog")
    if (
        catalog.get("framework") != "unittest"
        or catalog.get("expected_test_method_count") != 18
        or not isinstance(entries, list)
        or len(entries) != 18
    ):
        raise TestRunError("test catalog does not declare exactly eighteen methods")
    expected_ids = [f"UT-{index:03d}" for index in range(1, 19)]
    actual_ids = [entry.get("test_id") for entry in entries if isinstance(entry, dict)]
    methods = [entry.get("fq_method") for entry in entries if isinstance(entry, dict)]
    if actual_ids != expected_ids or len(methods) != 18 or len(set(methods)) != 18:
        raise TestRunError("test identifiers or fully-qualified methods are not canonical")
    return entries


def load_module(root: Path, module_name: str):
    relative = Path(*module_name.split(".")).with_suffix(".py")
    path = root / relative
    if not path.is_file():
        raise TestRunError(f"catalogued test module is missing: {relative.as_posix()}")
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise TestRunError(f"cannot create import specification for {module_name}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return module


def build_suite(root: Path, entries: list[dict[str, Any]]) -> unittest.TestSuite:
    source_path = str(root / "src")
    root_path = str(root)
    for value in (root_path, source_path):
        if value not in sys.path:
            sys.path.insert(0, value)
    namespace = types.ModuleType("tests")
    namespace.__path__ = [str(root / "tests")]
    sys.modules["tests"] = namespace
    modules: dict[str, Any] = {}
    suite = unittest.TestSuite()
    catalogued: set[str] = set()
    for entry in entries:
        fq_method = entry["fq_method"]
        parts = fq_method.split(".")
        if len(parts) != 4 or parts[0] != "tests":
            raise TestRunError(f"invalid fully-qualified method: {fq_method}")
        module_name = ".".join(parts[:2])
        class_name, method_name = parts[2:]
        if module_name not in modules:
            modules[module_name] = load_module(root, module_name)
        module = modules[module_name]
        case_class = getattr(module, class_name, None)
        if not isinstance(case_class, type) or not issubclass(case_class, unittest.TestCase):
            raise TestRunError(f"catalogued test class is invalid: {fq_method}")
        if not callable(getattr(case_class, method_name, None)):
            raise TestRunError(f"catalogued test method is missing: {fq_method}")
        suite.addTest(case_class(method_name))
        catalogued.add(fq_method)

    discovered: set[str] = set()
    for module_name, module in modules.items():
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, unittest.TestCase):
                for method in unittest.defaultTestLoader.getTestCaseNames(value):
                    discovered.add(f"{module_name}.{value.__name__}.{method}")
    if discovered != catalogued:
        raise TestRunError(
            "catalog/module mismatch; "
            f"missing={sorted(catalogued-discovered)}, extra={sorted(discovered-catalogued)}"
        )
    return suite


class DeterministicResult(unittest.TestResult):
    def __init__(self, id_map: dict[str, str]) -> None:
        super().__init__()
        self.id_map = id_map
        self.records: dict[str, dict[str, str]] = {}

    def _key(self, test: unittest.TestCase) -> str:
        key = test.id()
        if key not in self.id_map:
            raise TestRunError(f"uncatalogued test executed: {key}")
        return key

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        key = self._key(test)
        self.records[key] = {
            "test_id": self.id_map[key],
            "fq_method": key,
            "status": "running",
            "detail": "",
        }

    def addSuccess(self, test: unittest.TestCase) -> None:
        super().addSuccess(test)
        self.records[self._key(test)]["status"] = "pass"

    def _failure(self, test: unittest.TestCase, err: tuple[type, BaseException, Any], status: str) -> None:
        key = self._key(test)
        self.records[key]["status"] = status
        self.records[key]["detail"] = f"{err[0].__name__}: {err[1]}"

    def addFailure(self, test: unittest.TestCase, err) -> None:
        super().addFailure(test, err)
        self._failure(test, err, "failure")

    def addError(self, test: unittest.TestCase, err) -> None:
        super().addError(test, err)
        self._failure(test, err, "error")

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        key = self._key(test)
        self.records[key]["status"] = "skipped"
        self.records[key]["detail"] = reason

    def addExpectedFailure(self, test: unittest.TestCase, err) -> None:
        super().addExpectedFailure(test, err)
        self._failure(test, err, "expected_failure")

    def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:
        super().addUnexpectedSuccess(test)
        self.records[self._key(test)]["status"] = "unexpected_success"

    def addSubTest(self, test: unittest.TestCase, subtest, err) -> None:
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._failure(test, err, "failure")


def execute(root: Path, output_root: Path) -> tuple[dict[str, Any], int]:
    root = root.resolve()
    output_root = output_root.resolve()
    gate = verify_source_gate(root)
    entries = catalog_entries(root)
    suite = build_suite(root, entries)
    id_map = {entry["fq_method"]: entry["test_id"] for entry in entries}
    result = DeterministicResult(id_map)
    result.startTestRun()
    try:
        suite.run(result)
    finally:
        result.stopTestRun()
    records = [result.records[entry["fq_method"]] for entry in entries]
    for record in records:
        if record["status"] == "running":
            record["status"] = "error"
            record["detail"] = "test ended without a terminal unittest result"
    counts = {
        status: sum(record["status"] == status for record in records)
        for status in (
            "pass",
            "failure",
            "error",
            "skipped",
            "expected_failure",
            "unexpected_success",
        )
    }
    passed = counts["pass"] == 18 and sum(counts.values()) == 18
    summary = {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "source_manifest_sha256": gate["manifest_sha256"],
        "catalog_sha256": hashlib.sha256(
            (root / "tests/test_catalog.json").read_bytes()
        ).hexdigest(),
        "expected_test_methods": 18,
        "executed_test_methods": len(records),
        "counts": counts,
        "tests": records,
        "status": "pass" if passed else "fail",
        "scope": "synthetic_contract_conformance_only",
    }
    atomic_write(
        output_root / "results/reference_run/unit_test_summary.json",
        (canonical_json(summary) + "\n").encode("utf-8"),
    )
    log = "".join(
        f"{item['test_id']}\t{item['status'].upper()}\t{item['fq_method']}"
        f"\t{item['detail'] or '-'}\n"
        for item in records
    )
    atomic_write(output_root / "logs/reference_run/unittest.log", log.encode("utf-8"))
    report = {
        "run_id": RUN_ID,
        "expected": 18,
        "executed": len(records),
        "passed": counts["pass"],
        "source_manifest_sha256": gate["manifest_sha256"],
        "status": summary["status"],
    }
    return report, 0 if passed else 1


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
        report, exit_code = execute(args.root, args.output_root)
    except (TestRunError, OSError, ValueError) as exc:
        print(f"run_tests.py: ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json(report))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
