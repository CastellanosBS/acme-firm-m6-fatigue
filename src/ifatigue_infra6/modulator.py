"""Authorized fatigue-to-coping modulation using exact decimal arithmetic."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Mapping

from .canonical_json import decimal_to_string, parse_decimal_string
from .host import copy_appraisal_vector, protected_coordinates_equal
from .model import FORMULA_ID, ModulationOutcome


def clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    if lower > upper:
        raise ValueError("lower bound exceeds upper bound")
    return min(max(value, lower), upper)


def modulate_coping_potential(
    baseline: Mapping[str, str], factor_state: Mapping[str, str], *, lambda_value: str
) -> ModulationOutcome:
    """Evaluate coping_in × (1 − lambda × z), clamp it, and preserve locality."""
    coping = parse_decimal_string(
        baseline["coping_potential"], field="host.baseline.coping_potential"
    )
    weight = parse_decimal_string(lambda_value, field="influence.parameters.lambda")
    level = parse_decimal_string(factor_state["level"], field="factor_state.level")
    with localcontext() as context:
        context.prec = 50
        multiplicative_factor = Decimal(1) - weight * level
        raw_result = coping * multiplicative_factor
        bounded_result = clamp(raw_result, Decimal(0), Decimal(1))

    output = copy_appraisal_vector(baseline)
    output["coping_potential"] = decimal_to_string(bounded_result)
    if not protected_coordinates_equal(baseline, output):
        raise RuntimeError("the modulation changed a protected appraisal coordinate")
    formula_record = {
        "formula_id": FORMULA_ID,
        "coping_potential_in": decimal_to_string(coping),
        "lambda": decimal_to_string(weight),
        "factor_level": decimal_to_string(level),
        "multiplicative_factor": decimal_to_string(multiplicative_factor),
        "raw_result": decimal_to_string(raw_result),
        "bounded_result": decimal_to_string(bounded_result),
    }
    return ModulationOutcome(output=output, formula_record=formula_record)

