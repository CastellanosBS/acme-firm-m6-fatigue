"""UT-017 and UT-018: deterministic trace identity and sensitivity."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ifatigue_infra6.runner import evaluate_scenario  # noqa: E402
from ifatigue_infra6.trace import trace_id, trace_id_is_valid  # noqa: E402


def _read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


CONFIG = _read("config/resolved_instance.json")


class TestTrace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = _read("scenarios/S02.json")
        cls.oracle = _read("oracles/S02.expected.json")
        cls.outcome = evaluate_scenario(cls.scenario, CONFIG)

    def test_same_trace_core_produces_same_trace_id(self):
        core = self.outcome.trace["trace_core"]
        first = trace_id(core)
        second = trace_id(copy.deepcopy(core))
        self.assertEqual(first, second)
        self.assertEqual(first, self.outcome.trace["trace_id"])
        self.assertTrue(trace_id_is_valid(self.outcome.trace))
        self.assertEqual(
            self.outcome.result["output"],
            self.oracle["expected"]["output_contract"]["appraisal_vector"],
        )

    def test_each_trace_core_component_changes_trace_id(self):
        core = self.outcome.trace["trace_core"]
        baseline_id = trace_id(core)

        mutations = {
            "event": lambda value: value["event"].__setitem__(
                "event_id", "EVT-CONFORMANCE-MUTATED"
            ),
            "state": lambda value: value["state"].__setitem__("level", "0.51"),
            "baseline": lambda value: value["baseline"].__setitem__(
                "expectedness", "0.12"
            ),
            "output": lambda value: value["output"].__setitem__(
                "expectedness", "0.12"
            ),
            "policy": lambda value: value["policy"].__setitem__(
                "max_age_seconds", 301
            ),
            "mask": lambda value: value["mask"].__setitem__(
                "writable_coordinate", "expectedness"
            ),
            "formula": lambda value: value["formula"].__setitem__(
                "raw_result", "0.68001"
            ),
            "classification": lambda value: value.__setitem__(
                "classification",
                {
                    "published_rule_ref": "RULE-ANGER-2018B-CONSISTENT",
                    "before": "unclassified_by_published_subset",
                    "after": "unclassified_by_published_subset",
                },
            ),
            "versions": lambda value: value["versions"].__setitem__(
                "package_version", "1.1.0-mutated"
            ),
        }
        self.assertEqual(set(mutations), set(core))
        for component, mutate in mutations.items():
            with self.subTest(component=component):
                changed = copy.deepcopy(core)
                mutate(changed)
                self.assertNotEqual(trace_id(changed), baseline_id)
