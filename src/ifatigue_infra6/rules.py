"""Bounded adapters for the two published rule fragments used by the instance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .host import classify_coping_potential


ANTECEDENT_FIELD_MAPS = {
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
BOUNDARY_ADAPTERS = {
    "SRC-2018A-COGNITION-APPRAISAL": {
        "producer": "General Appraisal",
        "integration_boundary": "Emotional Filter",
    },
    "SRC-2018B-FLEXIBLE-SCHEME": {
        "producer": "General Appraisal (GA)",
        "integration_boundary": "Emotion Filter (EF)",
    },
}
CANONICAL_BOUNDARY = {
    "producer": "general_appraisal",
    "integration_boundary": "emotional_filter",
}
ANGER_PROTECTED_LABELS = {
    "desirability": "undesirable",
    "expectedness": "unexpected",
    "novelty": "not_novelty",
    "pleasure": "not_pleasant",
    "goal_conduciveness": "negative",
    "source": "anger_2018b_host_payload_not_derived_from_numeric_sentinels",
}
SADNESS_SOURCE_PAYLOAD = {
    "Consequence (E)": "myself",
    "Coping potential (E)": "positive",
    "Desirability(E)": "highly undesirable",
    "Expectedness(E)": "expected",
    "Goal conduciveness (E)": "negative",
    "Novelty (E)": "low novelty",
    "Pleasantness(E)": "unpleasant",
}


class RuleAdapterError(ValueError):
    """An undeclared source lexeme or boundary mapping was requested."""


@dataclass(frozen=True)
class PublishedSubsetAmbiguity(ValueError):
    matches: tuple[str, ...]
    diagnostic_code: str = "PUBLISHED_SUBSET_AMBIGUOUS"

    def __str__(self) -> str:
        return f"{self.diagnostic_code}: {len(self.matches)} published matches"


def adapt_antecedent_field(source_id: str, source_lexeme: str) -> str:
    """Resolve only an exact, source-specific antecedent lexeme."""
    try:
        return ANTECEDENT_FIELD_MAPS[source_id][source_lexeme]
    except KeyError as exc:
        raise RuleAdapterError("unknown source or non-exact antecedent lexeme") from exc


def adapt_boundary(
    source_id: str, *, producer: str, integration_boundary: str
) -> dict[str, str]:
    """Validate the exact published boundary terms and emit doctoral terms."""
    observed = {
        "producer": producer,
        "integration_boundary": integration_boundary,
    }
    if BOUNDARY_ADAPTERS.get(source_id) != observed:
        raise RuleAdapterError("unknown source or non-exact boundary terminology")
    return dict(CANONICAL_BOUNDARY)


def select_unique_published_match(matches: Sequence[str]) -> str:
    """Return a sole consequent, fallback on zero, and fail closed on ambiguity."""
    exact = tuple(matches)
    if not exact:
        return "unclassified_by_published_subset"
    if len(exact) > 1:
        raise PublishedSubsetAmbiguity(exact)
    return exact[0]


def classify_anger_subset(
    symbolic_payload: object, coping_potential: str
) -> str:
    """Evaluate only the preserved consistent 2018b row selected by T03-RS-005."""
    if type(symbolic_payload) is not dict or symbolic_payload != ANGER_PROTECTED_LABELS:
        return select_unique_published_match(())
    coping_label = classify_coping_potential(coping_potential)
    matches = ("anger",) if coping_label == "null" else ()
    return select_unique_published_match(matches)


def classify_anger_before_after(
    symbolic_payload: object, *, before: str, after: str
) -> dict[str, str]:
    return {
        "before": classify_anger_subset(symbolic_payload, before),
        "after": classify_anger_subset(symbolic_payload, after),
    }


def evaluate_sadness_symbolic(fixture: object) -> dict[str, object]:
    """Exercise the isolated symbolic rule without entering the numeric pipeline."""
    if type(fixture) is not dict:
        return {"match": False, "emotion": None, "numeric_pipeline_used": False}
    event_context = fixture.get("event_context")
    payload = fixture.get("published_symbolic_payload")
    match = (
        fixture.get("numeric_pipeline_input") is False
        and fixture.get("source_rule_ref") == "RULE-SADNESS-2018A"
        and event_context
        == {
            "cause_class": "unwanted_event_occurred",
            "consequence_target": "myself",
        }
        and payload == SADNESS_SOURCE_PAYLOAD
    )
    return {
        "match": match,
        "emotion": "sadness" if match else None,
        "numeric_pipeline_used": False,
    }


def conflicting_2018b_row_status(rule_document: object) -> str:
    """Confirm that the contradictory row remains present but is never executable."""
    if type(rule_document) is not dict:
        raise RuleAdapterError("the 2018b rule document is not an object")
    row = rule_document.get("source", {}).get("conflicting_row")
    if (
        type(row) is not dict
        or row.get("emotion_column") != "Sadness"
        or row.get("then", {}).get("value") != "Anger"
        or len(row.get("if_antecedents", [])) != 6
    ):
        raise RuleAdapterError("the preserved conflicting 2018b row diverges")
    return "excluded_from_execution"

