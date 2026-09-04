"""Deterministic trace-core assembly and SHA-256 identity."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .canonical_json import canonical_sha256
from .contract import ordered_diagnostics
from .model import (
    ARTIFACT_INTERNAL_VERSION,
    PACKAGE_VERSION,
    PROTECTED_DIMENSIONS,
    QA_CONTRACT_ID,
)


def trace_policy(config: Mapping[str, Any], evaluation_time: str) -> dict[str, Any]:
    temporal = config["contract"]["temporal_policy"]
    return {
        "qa_contract_id": QA_CONTRACT_ID,
        "factor_contract_decision_id": "T03-CT-009",
        "temporal_policy_decision_id": "T03-TM-004",
        "evaluation_time": evaluation_time,
        "validation_order": ["host_baseline", "factor_state"],
        "min_confidence": "0.5",
        "max_age_seconds": temporal["stale"]["max_age_seconds"],
        "future_tolerance_seconds": temporal["future"]["future_tolerance_seconds"],
        "stale_operator": ">=",
        "future_operator": ">",
    }


def trace_versions() -> dict[str, str]:
    return {
        "package_version": PACKAGE_VERSION,
        "artifact_internal_version": ARTIFACT_INTERNAL_VERSION,
        "scenario_schema_version": "1.0.0",
        "trace_schema_version": "1.0.0",
        "resolved_specification_version": "1.1.0",
        "qa_contract_id": QA_CONTRACT_ID,
    }


def trace_mask() -> dict[str, Any]:
    return {
        "writable_coordinate": "coping_potential",
        "protected_coordinates": list(PROTECTED_DIMENSIONS),
    }


def _classification_record(classification: Mapping[str, Any]) -> dict[str, str] | None:
    if classification.get("attempted") is False:
        return None
    if classification.get("attempted") is not True:
        raise ValueError("classification attempt flag is required")
    return {
        "published_rule_ref": "RULE-ANGER-2018B-CONSISTENT",
        "before": classification["before"],
        "after": classification["after"],
    }


def build_trace_core(
    *,
    scenario: Mapping[str, Any],
    output: Mapping[str, str],
    config: Mapping[str, Any],
    formula_record: Mapping[str, str] | None,
    classification: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble exactly the nine trace-core components."""
    return {
        "event": deepcopy(scenario["event"]),
        "state": deepcopy(scenario.get("factor_state")),
        "baseline": deepcopy(scenario["baseline"]),
        "output": deepcopy(dict(output)),
        "policy": trace_policy(config, scenario["evaluation_time"]),
        "mask": trace_mask(),
        "formula": deepcopy(dict(formula_record)) if formula_record is not None else None,
        "classification": _classification_record(classification),
        "versions": trace_versions(),
    }


def trace_id(trace_core: Mapping[str, Any]) -> str:
    return canonical_sha256(dict(trace_core))


def build_trace(
    *,
    scenario: Mapping[str, Any],
    result: Mapping[str, Any],
    config: Mapping[str, Any],
    formula_record: Mapping[str, str] | None,
) -> dict[str, Any]:
    if result["scenario_id"] != scenario["scenario_id"]:
        raise ValueError("result and scenario identifiers diverge")
    if result["evaluation_time"] != scenario["evaluation_time"]:
        raise ValueError("result and scenario evaluation times diverge")
    diagnostics = list(ordered_diagnostics(result["diagnostics"]))
    if diagnostics != result["diagnostics"]:
        raise ValueError("result diagnostics are not in fixed priority order")
    core = build_trace_core(
        scenario=scenario,
        output=result["output"],
        config=config,
        formula_record=formula_record,
        classification=result["classification"],
    )
    return {
        "$schema": "../../schemas/trace.schema.json",
        "schema_version": "1.0.0",
        "scenario_id": scenario["scenario_id"],
        "evaluation_time": scenario["evaluation_time"],
        "disposition": result["disposition"],
        "diagnostics": diagnostics,
        "trace_core": core,
        "trace_id": trace_id(core),
    }


def trace_id_is_valid(trace: Mapping[str, Any]) -> bool:
    return trace.get("trace_id") == trace_id(trace["trace_core"])

