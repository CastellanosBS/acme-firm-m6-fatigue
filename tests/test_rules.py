"""UT-013 through UT-016: bounded published-rule adapters."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ifatigue_infra6.rules import (  # noqa: E402
    PublishedSubsetAmbiguity,
    conflicting_2018b_row_status,
    evaluate_sadness_symbolic,
    select_unique_published_match,
)
from ifatigue_infra6.runner import evaluate_scenario  # noqa: E402


def _read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


CONFIG = _read("config/resolved_instance.json")


class TestRules(unittest.TestCase):
    def test_anger_bounded_continuity_s14(self):
        scenario = _read("scenarios/S14.json")
        oracle = _read("oracles/S14.expected.json")
        outcome = evaluate_scenario(scenario, CONFIG)
        expected = oracle["expected"]["classification"]
        self.assertTrue(outcome.result["classification"]["attempted"])
        self.assertEqual(
            outcome.result["classification"]["before"], expected["before"]
        )
        self.assertEqual(
            outcome.result["classification"]["after"], expected["after"]
        )
        self.assertEqual(
            outcome.trace["trace_core"]["classification"]["published_rule_ref"],
            "RULE-ANGER-2018B-CONSISTENT",
        )

    def test_sadness_source_terms_and_context_preserved(self):
        fixture = _read("tests/fixtures/sadness_2018a_symbolic.json")
        oracle = _read("tests/oracles/sadness_2018a_symbolic.expected.json")
        self.assertEqual(evaluate_sadness_symbolic(fixture), oracle["expected"])
        self.assertFalse(fixture["numeric_pipeline_input"])
        self.assertEqual(fixture["source_rule_ref"], "RULE-SADNESS-2018A")

    def test_conflicting_2018b_row_preserved_and_excluded(self):
        document = _read("spec/published/rule_anger_2018b.json")
        row = document["source"]["conflicting_row"]
        self.assertEqual(row["emotion_column"], "Sadness")
        self.assertEqual(row["then"]["value"], "Anger")
        self.assertEqual(len(row["if_antecedents"]), 6)
        self.assertEqual(conflicting_2018b_row_status(document), "excluded_from_execution")

    def test_multiple_published_rule_match_rejected(self):
        with self.assertRaises(PublishedSubsetAmbiguity) as context:
            select_unique_published_match(("anger", "anger"))
        self.assertEqual(
            context.exception.diagnostic_code,
            "PUBLISHED_SUBSET_AMBIGUOUS",
        )
        self.assertEqual(context.exception.matches, ("anger", "anger"))

