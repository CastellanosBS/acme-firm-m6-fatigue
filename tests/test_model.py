"""UT-001 through UT-005: numeric behavior, domain and locality."""

from __future__ import annotations

import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ifatigue_infra6.model import PROTECTED_DIMENSIONS  # noqa: E402
from ifatigue_infra6.runner import evaluate_scenario  # noqa: E402


def _read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


CONFIG = _read("config/resolved_instance.json")


def _execute(scenario_id: str):
    scenario = _read(f"scenarios/{scenario_id}.json")
    oracle = _read(f"oracles/{scenario_id}.expected.json")
    outcome = evaluate_scenario(scenario, CONFIG)
    return scenario, oracle, outcome


class TestModel(unittest.TestCase):
    def test_neutrality_s00_s06(self):
        for scenario_id in ("S00", "S06"):
            with self.subTest(scenario_id=scenario_id):
                scenario, oracle, outcome = _execute(scenario_id)
                self.assertEqual(outcome.result["output"], scenario["baseline"])
                self.assertEqual(
                    outcome.result["output"],
                    oracle["expected"]["output_contract"]["appraisal_vector"],
                )
                self.assertEqual(outcome.result["disposition"], "applied_no_change")

    def test_formula_correspondence_s01_s04_s14(self):
        for scenario_id in ("S01", "S02", "S03", "S04", "S14"):
            with self.subTest(scenario_id=scenario_id):
                scenario, oracle, outcome = _execute(scenario_id)
                formula = outcome.trace["trace_core"]["formula"]
                expected = Decimal(scenario["baseline"]["coping_potential"]) * (
                    Decimal("1") - Decimal("0.3") * Decimal(scenario["factor_state"]["level"])
                )
                self.assertEqual(Decimal(formula["raw_result"]), expected)
                self.assertEqual(
                    outcome.result["output"],
                    oracle["expected"]["output_contract"]["appraisal_vector"],
                )

    def test_locality_protected_coordinates_s00_s14(self):
        for index in range(15):
            scenario_id = f"S{index:02d}"
            with self.subTest(scenario_id=scenario_id):
                scenario, oracle, outcome = _execute(scenario_id)
                for coordinate in PROTECTED_DIMENSIONS:
                    self.assertEqual(
                        outcome.result["output"][coordinate],
                        scenario["baseline"][coordinate],
                    )
                self.assertEqual(
                    outcome.result["output"],
                    oracle["expected"]["output_contract"]["appraisal_vector"],
                )

    def test_domain_limits_s05_s06(self):
        for scenario_id, expected in (("S05", "0"), ("S06", "1")):
            with self.subTest(scenario_id=scenario_id):
                _scenario, oracle, outcome = _execute(scenario_id)
                self.assertEqual(outcome.result["output"]["coping_potential"], expected)
                self.assertEqual(
                    outcome.result["output"],
                    oracle["expected"]["output_contract"]["appraisal_vector"],
                )

    def test_monotone_non_increasing_s00_s04(self):
        outputs = []
        for index in range(5):
            _scenario, oracle, outcome = _execute(f"S{index:02d}")
            outputs.append(Decimal(outcome.result["output"]["coping_potential"]))
            self.assertEqual(
                outcome.result["output"],
                oracle["expected"]["output_contract"]["appraisal_vector"],
            )
        self.assertEqual(outputs, sorted(outputs, reverse=True))

