"""Domain constants and immutable execution records for the doctoral instance."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


PACKAGE_ID = "IFATIGUE-INFRA6-M6"
PACKAGE_VERSION = "1.1.0"
ARTIFACT_INTERNAL_VERSION = "1.0.0"
QA_CONTRACT_ID = "IFM6-QA-CONTRACT-1.0.0"
FORMULA_ID = "F6-COPING-MOD-001"

APPRAISAL_DIMENSIONS = (
    "expectedness",
    "desirability",
    "novelty",
    "pleasure",
    "goal_conduciveness",
    "coping_potential",
)
PROTECTED_DIMENSIONS = APPRAISAL_DIMENSIONS[:-1]
WRITABLE_DIMENSION = "coping_potential"

BINDING_MAP = MappingProxyType(
    {
        # @binding-coping-potential: host.baseline.coping_potential
        "coping_potential": "host.baseline.coping_potential",
        # @binding-lambda: influence.parameters.lambda
        "lambda": "influence.parameters.lambda",
        # @binding-z: factor_state.level
        "z": "factor_state.level",
        # @binding-result: output.coping_potential
        "result": "output.coping_potential",
    }
)

DIAGNOSTIC_PRIORITY = (
    "HOST_BASELINE_MISSING_FIELD",
    "HOST_BASELINE_TYPE_INVALID",
    "HOST_BASELINE_OUT_OF_RANGE",
    "FACTOR_STATE_MISSING",
    "FACTOR_STATE_TYPE_INVALID",
    "FACTOR_LEVEL_MISSING",
    "FACTOR_LEVEL_TYPE_INVALID",
    "FACTOR_LEVEL_OUT_OF_RANGE",
    "FACTOR_CONFIDENCE_MISSING",
    "FACTOR_CONFIDENCE_TYPE_INVALID",
    "FACTOR_CONFIDENCE_OUT_OF_RANGE",
    "FACTOR_CONFIDENCE_BELOW_MIN",
    "FACTOR_OBSERVED_AT_MISSING",
    "FACTOR_OBSERVED_AT_INVALID",
    "FACTOR_STATE_STALE",
    "FACTOR_STATE_FROM_FUTURE",
    "FACTOR_SOURCE_ID_MISSING",
    "FACTOR_SOURCE_ID_TYPE_INVALID",
    "FACTOR_SCHEMA_VERSION_MISSING",
    "FACTOR_SCHEMA_VERSION_TYPE_INVALID",
    "FACTOR_SCHEMA_VERSION_UNSUPPORTED",
    "PUBLISHED_SUBSET_AMBIGUOUS",
)


@dataclass(frozen=True)
class ContractAssessment:
    """Ordered diagnostics and the validation phase reached by the pipeline."""

    diagnostics: tuple[str, ...]
    factor_validation_performed: bool

    @property
    def valid(self) -> bool:
        return not self.diagnostics


@dataclass(frozen=True)
class ModulationOutcome:
    """One deterministic appraisal output and its arithmetic audit record."""

    output: Mapping[str, str]
    formula_record: Mapping[str, str]


@dataclass(frozen=True)
class ExecutionOutcome:
    """In-memory execution products; persistence is delegated to later scripts."""

    result: Mapping[str, Any]
    trace: Mapping[str, Any] | None
    rejection: Mapping[str, Any] | None

