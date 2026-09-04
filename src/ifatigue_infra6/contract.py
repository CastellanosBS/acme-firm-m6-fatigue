"""Fail-closed host, factor-state and resolved-configuration contracts."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from .canonical_json import CanonicalizationError, parse_decimal_string
from .model import (
    APPRAISAL_DIMENSIONS,
    BINDING_MAP,
    DIAGNOSTIC_PRIORITY,
    PROTECTED_DIMENSIONS,
    ContractAssessment,
)


RFC3339_UTC_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
FACTOR_FIELDS = (
    "level",
    "confidence",
    "observed_at",
    "source_id",
    "state_schema_version",
)


class RuntimeContractError(ValueError):
    """A trusted package configuration violates its frozen contract."""


def ordered_diagnostics(values: Iterable[str]) -> tuple[str, ...]:
    """Deduplicate diagnostic classes and impose the fixed 1–22 priority."""
    unique = set(values)
    unknown = unique.difference(DIAGNOSTIC_PRIORITY)
    if unknown:
        raise RuntimeContractError(f"unknown diagnostics: {sorted(unknown)}")
    return tuple(code for code in DIAGNOSTIC_PRIORITY if code in unique)


def _decimal_or_none(value: object, field: str) -> Decimal | None:
    try:
        return parse_decimal_string(value, field=field)
    except CanonicalizationError:
        return None


def parse_rfc3339_utc(value: object, *, field: str) -> datetime:
    if type(value) is not str or RFC3339_UTC_PATTERN.fullmatch(value) is None:
        raise RuntimeContractError(f"{field} must be an exact RFC3339 UTC timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise RuntimeContractError(f"{field} is not a calendar-valid UTC timestamp") from exc


def validate_host_baseline(baseline: object) -> tuple[str, ...]:
    """Validate all six host coordinates and aggregate diagnostic classes."""
    if baseline is None:
        return ("HOST_BASELINE_MISSING_FIELD",)
    if type(baseline) is not dict:
        return ("HOST_BASELINE_TYPE_INVALID",)

    diagnostics: list[str] = []
    if set(baseline).difference(APPRAISAL_DIMENSIONS):
        diagnostics.append("HOST_BASELINE_TYPE_INVALID")
    for dimension in APPRAISAL_DIMENSIONS:
        if dimension not in baseline:
            diagnostics.append("HOST_BASELINE_MISSING_FIELD")
            continue
        parsed = _decimal_or_none(baseline[dimension], f"baseline.{dimension}")
        if parsed is None:
            diagnostics.append("HOST_BASELINE_TYPE_INVALID")
        elif parsed < 0 or parsed > 1:
            diagnostics.append("HOST_BASELINE_OUT_OF_RANGE")
    return ordered_diagnostics(diagnostics)


def validate_factor_state(
    factor_state: object, *, evaluation_time: object
) -> tuple[str, ...]:
    """Validate the factor container with non-cascading field diagnostics."""
    if factor_state is None:
        return ("FACTOR_STATE_MISSING",)
    if type(factor_state) is not dict:
        return ("FACTOR_STATE_TYPE_INVALID",)
    if set(factor_state).difference(FACTOR_FIELDS):
        return ("FACTOR_STATE_TYPE_INVALID",)

    evaluation = parse_rfc3339_utc(evaluation_time, field="evaluation_time")
    diagnostics: list[str] = []

    if "level" not in factor_state:
        diagnostics.append("FACTOR_LEVEL_MISSING")
    else:
        level = _decimal_or_none(factor_state["level"], "factor_state.level")
        if level is None:
            diagnostics.append("FACTOR_LEVEL_TYPE_INVALID")
        elif level < 0 or level > 1:
            diagnostics.append("FACTOR_LEVEL_OUT_OF_RANGE")

    if "confidence" not in factor_state:
        diagnostics.append("FACTOR_CONFIDENCE_MISSING")
    else:
        confidence = _decimal_or_none(
            factor_state["confidence"], "factor_state.confidence"
        )
        if confidence is None:
            diagnostics.append("FACTOR_CONFIDENCE_TYPE_INVALID")
        elif confidence < 0 or confidence > 1:
            diagnostics.append("FACTOR_CONFIDENCE_OUT_OF_RANGE")
        elif confidence < Decimal("0.5"):
            diagnostics.append("FACTOR_CONFIDENCE_BELOW_MIN")

    if "observed_at" not in factor_state:
        diagnostics.append("FACTOR_OBSERVED_AT_MISSING")
    else:
        try:
            observed = parse_rfc3339_utc(
                factor_state["observed_at"], field="factor_state.observed_at"
            )
        except RuntimeContractError:
            diagnostics.append("FACTOR_OBSERVED_AT_INVALID")
        else:
            age_seconds = (evaluation - observed).total_seconds()
            future_seconds = (observed - evaluation).total_seconds()
            if age_seconds >= 300:
                diagnostics.append("FACTOR_STATE_STALE")
            if future_seconds > 5:
                diagnostics.append("FACTOR_STATE_FROM_FUTURE")

    if "source_id" not in factor_state:
        diagnostics.append("FACTOR_SOURCE_ID_MISSING")
    else:
        source_id = factor_state["source_id"]
        if (
            type(source_id) is not str
            or not source_id
            or not any(not character.isspace() for character in source_id)
            or unicodedata.normalize("NFC", source_id) != source_id
        ):
            diagnostics.append("FACTOR_SOURCE_ID_TYPE_INVALID")

    if "state_schema_version" not in factor_state:
        diagnostics.append("FACTOR_SCHEMA_VERSION_MISSING")
    else:
        version = factor_state["state_schema_version"]
        if type(version) is not str:
            diagnostics.append("FACTOR_SCHEMA_VERSION_TYPE_INVALID")
        elif version != "1.0.0":
            diagnostics.append("FACTOR_SCHEMA_VERSION_UNSUPPORTED")

    return ordered_diagnostics(diagnostics)


def assess_contracts(
    baseline: object, factor_state: object, *, evaluation_time: object
) -> ContractAssessment:
    """Apply host-first short-circuiting followed by factor validation."""
    host_diagnostics = validate_host_baseline(baseline)
    if host_diagnostics:
        return ContractAssessment(host_diagnostics, factor_validation_performed=False)
    factor_diagnostics = validate_factor_state(
        factor_state, evaluation_time=evaluation_time
    )
    return ContractAssessment(factor_diagnostics, factor_validation_performed=True)


def validate_runtime_configuration(config: object) -> None:
    """Refuse any runtime configuration that diverges from the resolved instance."""
    if type(config) is not dict:
        raise RuntimeContractError("resolved configuration must be a JSON object")
    try:
        influence = config["influence"]
        contract = config["contract"]
        host = config["host"]
        factor = config["factor"]
        runtime = config["runtime"]
    except KeyError as exc:
        raise RuntimeContractError(f"resolved configuration is missing {exc.args[0]}") from exc

    if influence.get("binding_map") != dict(BINDING_MAP):
        raise RuntimeContractError("the four executable bindings are not exact")
    if influence.get("parameters") != {"lambda": "0.3"}:
        raise RuntimeContractError("lambda must be the approved decimal string 0.3")
    if influence.get("authorized") != ["coping_potential"]:
        raise RuntimeContractError("only coping_potential may be modified")
    if influence.get("protected") != list(PROTECTED_DIMENSIONS):
        raise RuntimeContractError("protected-coordinate order is not exact")
    expected_mask = {name: name == "coping_potential" for name in APPRAISAL_DIMENSIONS}
    if influence.get("mask") != expected_mask:
        raise RuntimeContractError("the monofactorial mask is not exact")
    if contract.get("validation_order") != ["host_baseline", "factor_state"]:
        raise RuntimeContractError("host-first validation order is not exact")
    if contract.get("diagnostics", {}).get("codes") != list(DIAGNOSTIC_PRIORITY):
        raise RuntimeContractError("diagnostic priority is not exact")
    temporal = contract.get("temporal_policy", {})
    if temporal.get("stale", {}).get("max_age_seconds") != 300:
        raise RuntimeContractError("stale boundary must be 300 seconds")
    if temporal.get("future", {}).get("future_tolerance_seconds") != 5:
        raise RuntimeContractError("future tolerance must be 5 seconds")
    if factor.get("state", {}).get("neutral_value") != "0":
        raise RuntimeContractError("factor neutral value must be 0")
    vector = host.get("appraisal_vector", {})
    if vector.get("order") != list(APPRAISAL_DIMENSIONS):
        raise RuntimeContractError("host appraisal order is not exact")
    if runtime.get("numeric") != {
        "negative_zero": "normalize_to_zero",
        "non_finite": False,
        "representation": "Decimal_from_strings",
    }:
        raise RuntimeContractError("numeric runtime profile is not exact")

