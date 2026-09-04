"""Canonical JSON and decimal primitives for IFATIGUE-INFRA6-M6."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any


DECIMAL_STRING_PATTERN = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented by IFM6-JSON-v1."""


def parse_decimal_string(value: object, *, field: str = "value") -> Decimal:
    """Parse an exact, finite decimal string without accepting numeric coercions."""
    if type(value) is not str or DECIMAL_STRING_PATTERN.fullmatch(value) is None:
        raise CanonicalizationError(f"{field} must be an IFM6-DEC-v1 decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise CanonicalizationError(f"{field} is not a finite decimal") from exc
    if not parsed.is_finite():
        raise CanonicalizationError(f"{field} is not finite")
    return parsed


def decimal_to_string(value: Decimal) -> str:
    """Return the unique non-exponent IFM6-DEC-v1 representation."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise CanonicalizationError("a finite Decimal is required")
    if value == 0:
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered == "-0":
        return "0"
    if DECIMAL_STRING_PATTERN.fullmatch(rendered) is None:
        raise CanonicalizationError("decimal normalization produced an invalid value")
    return rendered


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_to_string(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise CanonicalizationError("binary floating-point values are prohibited")
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise CanonicalizationError("JSON object keys must be strings")
        return {key: _json_ready(item) for key, item in value.items()}
    raise CanonicalizationError(f"unsupported canonical JSON type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize one value under the frozen IFM6-JSON-v1 profile."""
    return json.dumps(
        _json_ready(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_bytes(value: Any, *, terminal_lf: bool = False) -> bytes:
    payload = canonical_json(value)
    if terminal_lf:
        payload += "\n"
    return payload.encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Hash canonical JSON without a terminal line feed, as required for traces."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()

