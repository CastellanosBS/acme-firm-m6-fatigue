"""UT-006 through UT-012: failure boundaries, ordering and abstention."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ifatigue_infra6.contract import validate_factor_state  # noqa: E402
from ifatigue_infra6.runner import evaluate_scenario  # noqa: E402


def _read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


CONFIG = _read("config/resolved_instance.json")


def _execute(scenario_id: str):
    scenario = _read(f"scenarios/{scenario_id}.json")
    oracle = _read(f"oracles/{scenario_id}.expected.json")
    return scenario, oracle, evaluate_scenario(scenario, CONFIG)


class TestContract(unittest.TestCase):
    def test_missing_factor_abstains_s07(self):
        scenario, oracle, outcome = _execute("S07")
        self.assertEqual(outcome.result["disposition"], "abstained")
        self.assertEqual(outcome.result["diagnostics"], ["FACTOR_STATE_MISSING"])
        self.assertEqual(outcome.result["output"], scenario["baseline"])
        self.assertEqual(outcome.result["diagnostics"], oracle["expected"]["diagnostics"])

    def test_factor_level_below_and_above_range_s09_s10(self):
        for scenario_id in ("S09", "S10"):
            with self.subTest(scenario_id=scenario_id):
                scenario, oracle, outcome = _execute(scenario_id)
                self.assertEqual(outcome.result["disposition"], "abstained")
                self.assertEqual(
                    outcome.result["diagnostics"],
                    ["FACTOR_LEVEL_OUT_OF_RANGE"],
                )
                self.assertEqual(outcome.result["output"], scenario["baseline"])
                self.assertEqual(outcome.result["diagnostics"], oracle["expected"]["diagnostics"])

    def test_confidence_below_minimum_s11(self):
        scenario, oracle, outcome = _execute("S11")
        self.assertEqual(outcome.result["disposition"], "abstained")
        self.assertEqual(outcome.result["diagnostics"], ["FACTOR_CONFIDENCE_BELOW_MIN"])
        self.assertEqual(outcome.result["output"], scenario["baseline"])
        self.assertEqual(outcome.result["diagnostics"], oracle["expected"]["diagnostics"])

    def test_temporal_stale_future_and_boundary_s08_s12_s13(self):
        expected = {
            "S08": ["FACTOR_STATE_STALE"],
            "S12": ["FACTOR_STATE_FROM_FUTURE"],
            "S13": ["FACTOR_STATE_STALE"],
        }
        for scenario_id, diagnostics in expected.items():
            with self.subTest(scenario_id=scenario_id):
                scenario, oracle, outcome = _execute(scenario_id)
                self.assertEqual(outcome.result["disposition"], "abstained")
                self.assertEqual(outcome.result["diagnostics"], diagnostics)
                self.assertEqual(outcome.result["output"], scenario["baseline"])
                self.assertEqual(outcome.result["diagnostics"], oracle["expected"]["diagnostics"])

    def test_host_validation_precedes_factor_validation_s15(self):
        scenario = _read("scenarios/S15.json")
        oracle = _read("oracles/S15.expected.json")
        variant = copy.deepcopy(scenario)
        variant["factor_state"] = []
        outcome = evaluate_scenario(variant, CONFIG)
        self.assertEqual(outcome.result["diagnostics"], ["HOST_BASELINE_OUT_OF_RANGE"])
        self.assertFalse(outcome.result["factor_validation_performed"])
        self.assertIsNone(outcome.trace)
        self.assertFalse(outcome.rejection["factor_validation_performed"])
        self.assertEqual(outcome.result["diagnostics"], oracle["expected"]["diagnostics"])

    def test_multierror_diagnostics_order_and_non_cascade(self):
        invalid = {
            "confidence": "2",
            "observed_at": "not-a-time",
            "source_id": " \t",
            "state_schema_version": 1,
        }
        diagnostics = validate_factor_state(
            invalid, evaluation_time="2026-09-04T12:00:00Z"
        )
        self.assertEqual(
            diagnostics,
            (
                "FACTOR_LEVEL_MISSING",
                "FACTOR_CONFIDENCE_OUT_OF_RANGE",
                "FACTOR_OBSERVED_AT_INVALID",
                "FACTOR_SOURCE_ID_TYPE_INVALID",
                "FACTOR_SCHEMA_VERSION_TYPE_INVALID",
            ),
        )
        self.assertNotIn("FACTOR_CONFIDENCE_BELOW_MIN", diagnostics)
        self.assertNotIn("FACTOR_STATE_STALE", diagnostics)
        self.assertNotIn("FACTOR_STATE_FROM_FUTURE", diagnostics)
        self.assertNotIn("FACTOR_SCHEMA_VERSION_UNSUPPORTED", diagnostics)

    def test_factor_schema_version_unsupported(self):
        scenario = _read("scenarios/S00.json")
        state = copy.deepcopy(scenario["factor_state"])
        state["state_schema_version"] = "2.0.0"
        self.assertEqual(
            validate_factor_state(state, evaluation_time=scenario["evaluation_time"]),
            ("FACTOR_SCHEMA_VERSION_UNSUPPORTED",),
        )

