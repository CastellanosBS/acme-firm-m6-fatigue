"""Reconstructed six-coordinate ACME host boundary."""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from .canonical_json import parse_decimal_string
from .model import APPRAISAL_DIMENSIONS, PROTECTED_DIMENSIONS


def copy_appraisal_vector(value: Mapping[str, str]) -> dict[str, str]:
    """Copy a validated vector in its normative coordinate order."""
    return {dimension: value[dimension] for dimension in APPRAISAL_DIMENSIONS}


def classify_coping_potential(value: str) -> str:
    """Apply the doctoral crisp partition without inferring published labels."""
    coping = parse_decimal_string(value, field="coping_potential")
    if coping <= Decimal("0.3"):
        return "null"
    if coping <= Decimal("0.7"):
        return "approachable"
    return "highly_approachable"


def protected_coordinates_equal(
    baseline: Mapping[str, str], output: Mapping[str, str]
) -> bool:
    return all(baseline[name] == output[name] for name in PROTECTED_DIMENSIONS)

