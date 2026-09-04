"""Pure in-memory execution pipeline; file generation is intentionally external."""

from __future__ import annotations

from typing import Any, Mapping

from .contract import assess_contracts, validate_runtime_configuration
from .host import copy_appraisal_vector
from .model import ExecutionOutcome
from .modulator import modulate_coping_potential
from .rules import classify_anger_before_after
from .trace import build_trace


def _rejected_outcome(
    scenario: Mapping[str, Any], diagnostics: tuple[str, ...]
) -> ExecutionOutcome:
    scenario_id = scenario["scenario_id"]
    rejection_path = f"traces/reference_run/rejections/{scenario_id}.rejection.json"
    result = {
        "$schema": "../../schemas/result.schema.json",
        "schema_version": "1.0.0",
        "scenario_id": scenario_id,
        "evaluation_time": scenario["evaluation_time"],
        "disposition": "rejected",
        "diagnostics": list(diagnostics),
        "factor_validation_performed": False,
        "modulation": {
            "attempted": False,
            "formula_evaluated": False,
            "coping_potential_changed": False,
        },
        "classification": {"attempted": False},
        "modulation_trace": {"exists": False},
        "rejection_record": {"exists": True, "path": rejection_path},
    }
    rejection = {
        "$schema": "../../../schemas/rejection.schema.json",
        "schema_version": "1.0.0",
        "rejection_id": f"{scenario_id}.rejection",
        "scenario_id": scenario_id,
        "result_ref": f"results/reference_run/{scenario_id}.result.json",
        "phase": "host_baseline",
        "baseline_validation": "rejected",
        "diagnostics": list(diagnostics),
        "factor_validation_performed": False,
        "modulation_attempted": False,
        "classification_attempted": False,
        "modulation_trace": False,
        "trace_id_present": False,
    }
    return ExecutionOutcome(result=result, trace=None, rejection=rejection)


def evaluate_scenario(
    scenario: Mapping[str, Any], config: Mapping[str, Any]
) -> ExecutionOutcome:
    """Evaluate one already schema-validated scenario without consulting an oracle."""
    validate_runtime_configuration(config)
    if type(scenario) is not dict:
        raise ValueError("scenario must be a JSON object")
    required = {"scenario_id", "evaluation_time", "event", "baseline", "factor_state"}
    missing = required.difference(scenario)
    if missing:
        raise ValueError(f"scenario envelope is missing {sorted(missing)}")

    assessment = assess_contracts(
        scenario["baseline"],
        scenario["factor_state"],
        evaluation_time=scenario["evaluation_time"],
    )
    if assessment.diagnostics and not assessment.factor_validation_performed:
        return _rejected_outcome(scenario, assessment.diagnostics)

    scenario_id = scenario["scenario_id"]
    classification: dict[str, Any] = {"attempted": False}
    formula_record: Mapping[str, str] | None = None
    if assessment.diagnostics:
        output = copy_appraisal_vector(scenario["baseline"])
        disposition = "abstained"
        modulation = {
            "attempted": False,
            "formula_evaluated": False,
            "coping_potential_changed": False,
        }
    else:
        modulation_outcome = modulate_coping_potential(
            scenario["baseline"],
            scenario["factor_state"],
            lambda_value=config["influence"]["parameters"]["lambda"],
        )
        output = dict(modulation_outcome.output)
        formula_record = modulation_outcome.formula_record
        changed = output["coping_potential"] != scenario["baseline"]["coping_potential"]
        disposition = "modulated" if changed else "applied_no_change"
        modulation = {
            "attempted": True,
            "formula_evaluated": True,
            "coping_potential_changed": changed,
        }
        if "host_symbolic_payload" in scenario:
            before_after = classify_anger_before_after(
                scenario["host_symbolic_payload"],
                before=scenario["baseline"]["coping_potential"],
                after=output["coping_potential"],
            )
            classification = {"attempted": True, **before_after}

    result = {
        "$schema": "../../schemas/result.schema.json",
        "schema_version": "1.0.0",
        "scenario_id": scenario_id,
        "evaluation_time": scenario["evaluation_time"],
        "disposition": disposition,
        "diagnostics": list(assessment.diagnostics),
        "factor_validation_performed": assessment.factor_validation_performed,
        "modulation": modulation,
        "classification": classification,
        "modulation_trace": {
            "exists": True,
            "path": f"traces/reference_run/{scenario_id}.trace.json",
        },
        "rejection_record": {"exists": False},
        "output": output,
    }
    trace = build_trace(
        scenario=scenario,
        result=result,
        config=config,
        formula_record=formula_record,
    )
    return ExecutionOutcome(result=result, trace=trace, rejection=None)

