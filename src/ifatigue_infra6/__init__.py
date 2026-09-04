"""Reference implementation surface for IFATIGUE-INFRA6-M6."""

from .canonical_json import canonical_sha256
from .contract import (
    RuntimeContractError,
    assess_contracts,
    validate_factor_state,
    validate_host_baseline,
    validate_runtime_configuration,
)
from .host import classify_coping_potential
from .model import PACKAGE_ID, PACKAGE_VERSION, ExecutionOutcome
from .modulator import modulate_coping_potential
from .runner import evaluate_scenario
from .trace import trace_id, trace_id_is_valid


__all__ = [
    "ExecutionOutcome",
    "PACKAGE_ID",
    "PACKAGE_VERSION",
    "RuntimeContractError",
    "assess_contracts",
    "canonical_sha256",
    "classify_coping_potential",
    "evaluate_scenario",
    "modulate_coping_potential",
    "trace_id",
    "trace_id_is_valid",
    "validate_factor_state",
    "validate_host_baseline",
    "validate_runtime_configuration",
]
